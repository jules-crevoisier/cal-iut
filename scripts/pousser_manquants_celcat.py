"""Lit Celcat Live, diffère avec cal-iut, n'écrit que les manquants.

Par défaut : URCA_FORMATION, répétition. Jamais de suppression.
`--ecrire` sur URCA_2026 exige `--production`. Refusé tant que
`data/config/celcat_rpc.yaml` n'a pas de methode_ecriture (capture
FORMATION d'abord). Le clicker n'est pas utilisé.

    python scripts/pousser_manquants_celcat.py --lundi 2026-09-07 --vpn
    python scripts/pousser_manquants_celcat.py --lundi 2026-09-07 --vpn --groupe "TD AB"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.diff import comparer  # noqa: E402
from cal_iut.celcat.ecriture import (  # noqa: E402
    ProductionRefusee,
    creer_manquants,
    resoudre_groupe,
    resoudre_ids,
)
from cal_iut.celcat.formulaire import charger_carte  # noqa: E402
from cal_iut.celcat.lecture import evenement_depuis_rpc, indice_depuis_lundi  # noqa: E402
from cal_iut.celcat.mapping import EntreeCelcat  # noqa: E402
from cal_iut.celcat.rpc import MethodeEcritureAbsente, charger_edt, masquer_semaine  # noqa: E402
from cal_iut.celcat.sync import marquer_saisi  # noqa: E402

PREMIERE_SEMAINE_CELCAT = 34
GROUPES_S1 = (
    "BUT MMI S1 CM",
    "BUT MMI S1 TD AB",
    "BUT MMI S1 TD CD",
    "BUT MMI S1 TD EF",
    "BUT MMI S1 TD GH",
    "BUT MMI S1 TP A",
    "BUT MMI S1 TP B",
    "BUT MMI S1 TP C",
    "BUT MMI S1 TP D",
    "BUT MMI S1 TP E",
    "BUT MMI S1 TP F",
    "BUT MMI S1 TP G",
    "BUT MMI S1 TP H",
)


class EspionEdt:
    def __init__(self, page) -> None:
        self.dernier: list[dict] = []
        page.on("response", self._noter)

    def _noter(self, reponse) -> None:
        req = reponse.request
        if req.method != "POST" or "CTWebService.dll" not in reponse.url:
            return
        try:
            envoi = json.loads(req.post_data or "{}")
            if envoi.get("method") != "udlTimetables.load":
                return
            corps = nav.lire_reponse(reponse.text())
        except Exception:  # noqa: BLE001
            return
        res = corps.get("result")
        if isinstance(res, list):
            self.dernier = [e for e in res if isinstance(e, dict)]


def _ouvrir_groupe(page, nom: str, lundi: dt.date) -> None:
    nav.ouvrir_ressource(page, nav.TYPE_GROUPES)
    nav.filtrer(page, nom)
    nav.double_cliquer_texte(page, nom)
    nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
    try:
        nav.cliquer_icone_barre(page, "rafraichir")
    except LookupError:
        pass
    nav.choisir_semaine(page, lundi)
    try:
        nav.cliquer_icone_barre(page, "rafraichir")
    except LookupError:
        pass
    page.wait_for_timeout(2000)


def _fragments_groupes(texte: str) -> list[str]:
    return [g.strip() for g in texte.split(",") if g.strip()]


def _concerne_groupe(nom: str, fragments: list[str]) -> bool:
    if not fragments:
        return True
    cible = f" {nom.upper()} "
    return any(f" {frag.upper()} " in cible or nom.upper().endswith(frag.upper()) for frag in fragments)


def _methode_yaml() -> str:
    chemin = RACINE / "data" / "config" / "celcat_rpc.yaml"
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("methode_ecriture:"):
            return ligne.split(":", 1)[1].strip()
    return ""


def _entrees_depuis_json(chemin: Path) -> tuple[int, list]:
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    semaine = int(brut["semaine"])
    entrees = [EntreeCelcat(**e) for e in brut["entrees"]]
    return semaine, entrees


def _inventaire(plan) -> None:
    print(
        f"{len(plan.a_creer)} à créer, {len(plan.deja_la)} déjà là, "
        f"{len(plan.ambigu)} ambiguë(s), {len(plan.bloquees)} bloquée(s), "
        f"{len(plan.celcat_en_plus)} Celcat en plus, {len(plan.fantomes)} fantôme(s)"
    )
    for e in plan.a_creer:
        print(
            f"  CRÉER  {e.nom_groupe_celcat:24} {e.course_code:8} "
            f"j{e.jour} {e.heure_debut}-{e.heure_fin} {e.salle or '—'}"
        )
    for e, ev in plan.deja_la:
        print(f"  OK     {e.nom_groupe_celcat:24} {e.course_code:8} id={ev.event_id}")
    for e in plan.ambigu:
        print(f"  AMBIGU {e.nom_groupe_celcat:24} {e.course_code:8} (on ne touche pas)")
    for ev in plan.fantomes:
        print(f"  FANTÔME id={ev.event_id} {ev.weeks.count('Y')} sem")


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--lundi", default="2026-09-07")
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    parseur.add_argument("--ecrire", action="store_true")
    parseur.add_argument("--production", action="store_true")
    parseur.add_argument("--groupe", default="")
    parseur.add_argument("--jour", type=int, default=0, help="1=lundi … 5=vendredi (Celcat)")
    parseur.add_argument("--limite", type=int, default=0)
    parseur.add_argument("--entrees", default="")
    parseur.add_argument("--semestre", default="")
    parseur.add_argument("--semaine-celcat", type=int, default=0)
    parseur.add_argument("--premiere-semaine-celcat", type=int, default=PREMIERE_SEMAINE_CELCAT)
    args = parseur.parse_args()
    lundi = dt.date.fromisoformat(args.lundi)

    if args.ecrire and args.base == nav.BASE_PRODUCTION and not args.production:
        print("refus : URCA_2026 exige --production", file=sys.stderr)
        return 2
    methode = _methode_yaml()
    if args.ecrire and not methode:
        print(
            "refus : methode_ecriture vide (data/config/celcat_rpc.yaml). "
            "Capturer un Enregistrer sur URCA_FORMATION d'abord.",
            file=sys.stderr,
        )
        raise MethodeEcritureAbsente("methode_ecriture vide")

    if args.entrees:
        semaine, entrees = _entrees_depuis_json(Path(args.entrees))
    else:
        from saisir_semaine_celcat import _charger_entrees
        semaine, entrees = _charger_entrees(lundi)
    fragments = _fragments_groupes(args.groupe)
    if fragments:
        entrees = [e for e in entrees if _concerne_groupe(e.nom_groupe_celcat, fragments)]
    if args.semestre:
        sem = args.semestre.strip().upper()
        entrees = [e for e in entrees if e.semestre.upper() == sem]
    if args.jour:
        entrees = [e for e in entrees if e.jour == args.jour]
    indice = (
        args.semaine_celcat - args.premiere_semaine_celcat
        if args.semaine_celcat
        else indice_depuis_lundi(lundi, premiere_semaine_celcat=args.premiere_semaine_celcat)
    )
    print(f"semaine solveur {semaine} = lundi {lundi} = indice weeks {indice}")
    print(f"{len(entrees)} séance(s) cal-iut")
    for e in entrees:
        print(
            f"  cal-iut {e.semestre:2} {e.nom_groupe_celcat:22} {e.course_code:8} "
            f"j{e.jour} {e.heure_debut}-{e.heure_fin} {e.salle or '—'}"
        )

    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ.get("CELCAT_URL", "")
    if not url:
        print("CELCAT_URL absent", file=sys.stderr)
        return 2
    diag = reseau.exiger_acces(url, monter_le_vpn=args.vpn) if args.vpn else reseau.verifier(url)
    if not getattr(diag, "joignable", False):
        print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
        return 3

    from playwright.sync_api import sync_playwright

    noms = sorted({e.nom_groupe_celcat for e in entrees}) or [
        n for n in GROUPES_S1 if _concerne_groupe(n, fragments)
    ]
    role = nav.ROLE_ECRITURE if args.ecrire else args.role
    carte = charger_carte(RACINE / "data" / "config")
    evenements = []
    group_ids: dict[str, int] = {}
    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {args.base} rôle {role} (aucun new)…")
            nav.connexion(page, base=args.base, role=role)
            for nom in noms:
                print(f"  lecture {nom}")
                try:
                    gid = resoudre_groupe(page, nom)
                except Exception as exc:  # noqa: BLE001
                    print(f"    groupe introuvable : {exc}")
                    continue
                group_ids[nom] = gid
                for brut in charger_edt(page, group_ids=[gid]):
                    evenements.append(
                        evenement_depuis_rpc(brut, group_id=gid, groupe_nom=nom)
                    )
            plan = comparer(entrees, evenements, indice_semaine=indice)
            _inventaire(plan)
            if not args.ecrire:
                print("répétition (rien n'est envoyé). --ecrire pour créer les manquants.")
                return 0
            a_faire = plan.a_creer[: args.limite] if args.limite else plan.a_creer
            if not a_faire:
                print("rien à créer")
                return 0
            masque = masquer_semaine(longueur=54, indice=indice)
            print(f"création de {len(a_faire)} séance(s), masque 1×Y")
            cache_ids: dict[tuple, dict] = {}
            for e in a_faire:
                gid = group_ids.get(e.nom_groupe_celcat)
                if gid is None:
                    try:
                        gid = resoudre_groupe(page, e.nom_groupe_celcat)
                    except Exception as exc:  # noqa: BLE001
                        print(f"  ÉCHEC  {e.session_id} groupe : {exc}")
                        continue
                try:
                    cle_ids = (
                        e.code_module,
                        e.salle,
                        e.code_enseignant,
                        e.type_seance_nom,
                    )
                    if cle_ids not in cache_ids:
                        cache_ids[cle_ids] = resoudre_ids(
                            page, e, categorie=carte.categorie(e.type_seance_nom)
                        )
                    ids = cache_ids[cle_ids]
                except Exception as exc:  # noqa: BLE001
                    print(f"  ÉCHEC  {e.session_id} ids : {exc}")
                    continue
                resultat = creer_manquants(
                    page,
                    [e],
                    group_id=gid,
                    ids=ids,
                    masque=masque,
                    methode=methode,
                    base=args.base,
                    production_autorisee=args.production,
                    event_id=0,
                )
                for sid, eid in resultat.crees:
                    marquer_saisi(e, event_id=eid)
                    print(f"  CRÉÉ   {sid} event_id={eid}")
                for sid, err in resultat.echecs:
                    print(f"  ÉCHEC  {sid} {err}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(principal())
    except (MethodeEcritureAbsente, ProductionRefusee) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
