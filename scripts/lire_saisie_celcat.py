"""Lit ce qui est VRAIMENT posé dans Celcat Timetabler Live.

Lecture seule : rôle `985_consultation`, aucun clic sur `new` / save / delete.
On ouvre chaque groupe S1, on rafraîchit (les mises à jour n'apparaissent
qu'après reload), on cale la semaine du lundi donné, et on intercepte
`udlTimetables.load`.

    python scripts/lire_saisie_celcat.py --vpn --lundi 2026-09-07
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

# Première cellule du sélecteur URCA_2026 : Week 34 (8/17/26). La semaine 37
# (7 sept.) est donc l'index 3 de la chaîne `weeks` (54 caractères Y/N).
PREMIERE_SEMAINE_CELCAT = 34

CLES_JOUR = ("day_of_week", "day", "dayOfWeek", "Day", "DayOfWeek")
CLES_DEBUT = ("start_time", "start", "startTime", "StartTime", "event_start", "begin")
CLES_FIN = ("end_time", "end", "endTime", "EndTime", "event_end", "finish")

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

JOURS = {1: "lun", 2: "mar", 3: "mer", 4: "jeu", 5: "ven", 6: "sam", 7: "dim"}


class EspionEdt:
    """Garde le dernier `udlTimetables.load` complet."""

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


def _noms(valeurs: object) -> str:
    if not isinstance(valeurs, list):
        return ""
    morceaux = []
    for item in valeurs:
        if isinstance(item, dict):
            morceaux.append(str(item.get("name") or item.get("unique_name") or ""))
        else:
            morceaux.append(str(item))
    return ", ".join(x for x in morceaux if x)


def _heure(valeur: object) -> str:
    if valeur is None or valeur == "":
        return ""
    if isinstance(valeur, bool):
        return ""
    if isinstance(valeur, (int, float)):
        total = int(valeur)
        if total > 24 * 60:
            total //= 60
        return f"{total // 60:02d}:{total % 60:02d}"
    if isinstance(valeur, dict):
        for cle in ("hours", "hour", "Minutes", "minutes"):
            if cle.lower() in {k.lower() for k in valeur}:
                pass
        h = valeur.get("hours", valeur.get("hour"))
        m = valeur.get("minutes", valeur.get("minute", 0))
        if h is not None:
            return f"{int(h):02d}:{int(m or 0):02d}"
        return ""
    if isinstance(valeur, str) and "T" in valeur:
        return valeur.split("T", 1)[1][:5]
    texte = str(valeur)
    if ":" in texte:
        return texte[:5]
    return ""


def _sur_la_semaine(evenement: dict, indice: int) -> bool:
    masque = str(evenement.get("weeks") or "")
    if not masque or indice < 0 or indice >= len(masque):
        return False
    return masque[indice] == "Y"


def _premier(evenement: dict, cles: tuple[str, ...]) -> object:
    for cle in cles:
        if evenement.get(cle) not in (None, ""):
            return evenement[cle]
    return None


def _jour(evenement: dict) -> str:
    brut = _premier(evenement, CLES_JOUR)
    try:
        return JOURS.get(int(brut), str(brut) if brut is not None else "?")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(brut) if brut is not None else "?"


def _resume(evenement: dict) -> dict:
    masque = str(evenement.get("weeks") or "")
    return {
        "id": evenement.get("event_id") or evenement.get("id"),
        "jour": _jour(evenement),
        "debut": _heure(_premier(evenement, CLES_DEBUT)),
        "fin": _heure(_premier(evenement, CLES_FIN)),
        "categorie": evenement.get("evCatName") or "",
        "module": _noms(evenement.get("modules")),
        "salle": _noms(evenement.get("rooms")),
        "ens": _noms(evenement.get("staff")),
        "n_semaines": masque.count("Y"),
        "protege": evenement.get("protected"),
    }


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


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--lundi", default="2026-09-07")
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_PRODUCTION)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    parseur.add_argument("--semaine-celcat", type=int, default=37)
    parseur.add_argument("--groupe", default="", help="ne lire que les groupes dont le nom contient ce texte")
    args = parseur.parse_args()
    lundi = dt.date.fromisoformat(args.lundi)
    indice = args.semaine_celcat - PREMIERE_SEMAINE_CELCAT

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

    dossier = RACINE / "data" / "releves"
    dossier.mkdir(parents=True, exist_ok=True)
    sortie = {
        "quand": dt.datetime.now().isoformat(timespec="seconds"),
        "base": args.base,
        "role": args.role,
        "lundi": args.lundi,
        "semaine_celcat": args.semaine_celcat,
        "indice_weeks": indice,
        "groupes": {},
    }

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        espion = EspionEdt(page)
        try:
            print(f"Connexion {args.base} rôle {args.role} (lecture, aucun new)…")
            nav.connexion(page, base=args.base, role=args.role)
            cibles = [
                n for n in GROUPES_S1
                if not args.groupe or args.groupe.upper() in n.upper()
            ]
            for nom in cibles:
                print(f"\n=== {nom} ===")
                try:
                    _ouvrir_groupe(page, nom, lundi)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ouverture impossible : {exc}")
                    sortie["groupes"][nom] = {"erreur": str(exc)}
                    continue
                evenements = list(espion.dernier)
                if evenements and "cles_evenement" not in sortie:
                    sortie["cles_evenement"] = sorted(evenements[0].keys())
                    avec_horaire = next(
                        (e for e in evenements if e.get("start_time") or e.get("start") or e.get("day_of_week")),
                        evenements[0],
                    )
                    sortie["exemple"] = {k: avec_horaire.get(k) for k in sorted(avec_horaire) if k != "weeks"}
                cours, fantomes, feries = [], [], []
                for ev in evenements:
                    if not _sur_la_semaine(ev, indice):
                        continue
                    cat = str(ev.get("evCatName") or "")
                    ligne = _resume(ev)
                    if "férié" in cat.lower() or "ferie" in cat.lower():
                        feries.append(ligne)
                    elif ligne["debut"] or ligne["module"] or ligne["salle"]:
                        cours.append(ligne)
                    else:
                        fantomes.append(ligne)
                cours.sort(key=lambda e: (e["jour"], e["debut"] or "99"))
                print(f"  {len(evenements)} événement(s) RPC, "
                      f"{len(cours)} cours / {len(fantomes)} fantôme(s) / "
                      f"{len(feries)} férié(s) sur la semaine {args.semaine_celcat}")
                for c in cours:
                    print(
                        f"  {c['jour']} {c['debut']}-{c['fin']}  {c['categorie']:8}  "
                        f"{c['module'] or '—':12}  {c['salle'] or '—':12}  "
                        f"{c['ens'] or '—'}  [{c['n_semaines']} sem] id={c['id']}"
                    )
                for f in fantomes:
                    print(f"  FANTÔME id={f['id']} {f['n_semaines']} sem")
                sortie["groupes"][nom] = {
                    "rpc": len(evenements),
                    "cours": cours,
                    "fantomes": fantomes,
                    "feries": len(feries),
                }
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()

    chemin = dossier / f"celcat-saisie-s1-{args.lundi}.json"
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nÉcrit dans {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
