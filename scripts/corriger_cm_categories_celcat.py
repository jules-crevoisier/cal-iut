"""Corrige les CM cal-iut journalisés encore en [TP] sur Celcat Live.

Audit (défaut) : journal local + udlTimetables.load, liste les écarts.
Écriture : `--ecrire --production --base URCA_2026` met à jour vers [CM].

    python scripts/corriger_cm_categories_celcat.py --vpn --lundi 2026-09-07
    python scripts/corriger_cm_categories_celcat.py --vpn --lundi 2026-09-07 \
        --base URCA_2026 --role 985_T_MMI --production --ecrire
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import reseau
from cal_iut.celcat.categories import (
    CATEGORIE_IDS,
    EcartCategorie,
    inventaire_ecarts_categorie,
    libelle_categorie,
)
from cal_iut.celcat.ecriture import resoudre_groupe, resoudre_ids
from cal_iut.celcat.etat import charger
from cal_iut.celcat.formulaire import charger_carte
from cal_iut.celcat.lecture import evenement_depuis_rpc, indice_depuis_lundi
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import modifier_evenement
from cal_iut.celcat.rpc import MethodeEcritureAbsente, charger_edt, masquer_semaine

GROUPES_S1 = (
    "BUT MMI S1 CM",
    "BUT MMI S1 TD AB",
    "BUT MMI S1 TD CD",
    "BUT MMI S1 TD EF",
    "BUT MMI S1 TD GH",
)
PREMIERE_SEMAINE_CELCAT = 34


def _methode_yaml() -> str:
    chemin = RACINE / "data" / "config" / "celcat_rpc.yaml"
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("methode_ecriture:"):
            return ligne.split(":", 1)[1].strip()
    return ""


def _journal_cm() -> dict[str, dict]:
    doc = charger()
    journal = doc.get("journal") or {}
    if not isinstance(journal, dict):
        return {}
    out: dict[str, dict] = {}
    for sid, row in journal.items():
        if not isinstance(row, dict):
            continue
        sig = str(row.get("signature") or "")
        if "-CM-" in sid.upper() or sig.endswith("|CM"):
            out[sid] = row
    return out


def _entree_depuis_signature(session_id: str, row: dict, lundi: str) -> EntreeCelcat:
    parts = str(row.get("signature") or "").split("|")
    while len(parts) < 9:
        parts.append("")
    return EntreeCelcat(
        session_id=session_id,
        semaine=int(parts[0] or 0),
        jour=int(parts[1] or 1),
        heure_debut=parts[2] or "08:00",
        heure_fin=parts[3] or "09:30",
        code_enseignant=parts[4] or None,
        salle=parts[5] or None,
        code_module=parts[6] or None,
        type_seance=None,
        type_seance_nom="CM",
        groupe=parts[8] or "CM",
        semestre="S1",
        lundi=lundi,
        course_code=session_id.split("-")[0],
    )


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--lundi", default="2026-09-07")
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_PRODUCTION)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    parseur.add_argument("--ecrire", action="store_true")
    parseur.add_argument("--production", action="store_true")
    parseur.add_argument("--limite", type=int, default=0)
    parseur.add_argument("--premiere-semaine-celcat", type=int, default=PREMIERE_SEMAINE_CELCAT)
    args = parseur.parse_args()
    lundi = dt.date.fromisoformat(args.lundi)

    if args.ecrire:
        args.role = nav.ROLE_ECRITURE
    if args.ecrire and args.base == nav.BASE_PRODUCTION and not args.production:
        print("refus : URCA_2026 exige --production", file=sys.stderr)
        return 2
    methode = _methode_yaml()
    if args.ecrire and not methode:
        raise MethodeEcritureAbsente("methode_ecriture vide")

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

    journal = _journal_cm()
    print(f"{len(journal)} CM dans le journal local")
    indice = indice_depuis_lundi(lundi, premiere_semaine_celcat=args.premiere_semaine_celcat)
    print(f"lundi {lundi} = indice weeks {indice}")

    from playwright.sync_api import sync_playwright

    carte = charger_carte(RACINE / "data" / "config")
    live_par_id: dict[int, object] = {}
    group_ids: dict[str, int] = {}

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {args.base} rôle {args.role}…")
            nav.connexion(page, base=args.base, role=args.role)
            for nom in GROUPES_S1:
                print(f"  lecture {nom}")
                try:
                    gid = resoudre_groupe(page, nom)
                except Exception as exc:  # noqa: BLE001
                    print(f"    groupe introuvable : {exc}")
                    continue
                group_ids[nom] = gid
                for brut in charger_edt(page, group_ids=[gid]):
                    if not isinstance(brut, dict):
                        continue
                    ev = evenement_depuis_rpc(brut, group_id=gid, groupe_nom=nom)
                    live_par_id[ev.event_id] = ev

            types = {sid: "CM" for sid in journal}
            ecarts = inventaire_ecarts_categorie(
                journal=journal,
                live_par_event_id=live_par_id,
                type_par_session=types,
            )
            codes_cm = {sid.split("-")[0].upper() for sid in journal}
            for ev in live_par_id.values():
                if (getattr(ev, "categorie", "") or "").strip() != "[TP]":
                    continue
                nom_mod = getattr(ev, "module_nom", "") or ""
                code = nom_mod.split()[0].upper() if nom_mod else ""
                if code not in codes_cm:
                    continue
                if any(e.event_id == ev.event_id for e in ecarts):
                    continue
                ecarts.append(
                    EcartCategorie(
                        session_id=f"?-{code}",
                        course_code=code,
                        type_attendu="CM",
                        event_id=ev.event_id,
                        categorie_live="[TP]",
                        motif=f"Live [TP] pour module CM {code} (doublon / hors journal)",
                    )
                )

            print(f"{len(ecarts)} écart(s) catégorie")
            for e in ecarts:
                print(
                    f"  {e.session_id:40} event_id={e.event_id} "
                    f"{e.categorie_live} → {libelle_categorie('CM')} | {e.motif}"
                )

            if not args.ecrire:
                print("répétition (rien n'est envoyé). --ecrire pour corriger.")
                return 0

            a_faire = ecarts[: args.limite] if args.limite else ecarts
            if not a_faire:
                print("rien à corriger")
                return 0

            masque = masquer_semaine(longueur=54, indice=indice)
            cat_cm = carte.categorie("CM")
            gid_cm = group_ids.get("BUT MMI S1 CM") or next(iter(group_ids.values()), None)
            if gid_cm is None:
                print("aucun group_id Celcat", file=sys.stderr)
                return 4

            for ecart in a_faire:
                if ecart.event_id is None:
                    continue
                sid = ecart.session_id
                row = journal.get(sid)
                if row is None:
                    sid = next(
                        (s for s in journal if s.upper().startswith(ecart.course_code.upper() + "-")),
                        "",
                    )
                    row = journal.get(sid)
                if not isinstance(row, dict) or not sid:
                    print(f"  SAUT   event_id={ecart.event_id} : pas de ligne journal")
                    continue
                entree = _entree_depuis_signature(sid, row, args.lundi)
                try:
                    ids = resoudre_ids(page, entree, categorie=cat_cm)
                    if int(ids["event_cat_id"]) != CATEGORIE_IDS["CM"]:
                        print(
                            f"  ÉCHEC  {sid} event_cat_id={ids['event_cat_id']} "
                            f"(attendu {CATEGORIE_IDS['CM']})"
                        )
                        continue
                    # `modifier_evenement`, pas `creer_manquants(event_id=...)` : la
                    # cause racine du bug « partial key » est un objet reconstruit
                    # depuis zéro pour un update — `modifier_evenement` recharge
                    # l'enregistrement COMPLET puis n'écrase que les champs voulus
                    # (cf. .orchestrator/architect-contract-celcat-modifier-seance.md).
                    event_id_confirme = modifier_evenement(
                        page,
                        entree,
                        event_id=int(ecart.event_id),
                        group_id=int(gid_cm),
                        ids=ids,
                        masque=masque,
                        methode=methode,
                        base=args.base,
                        production_autorisee=args.production,
                    )
                    print(f"  OK     {sid} event_id={event_id_confirme} → [CM]")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ÉCHEC  {sid} {exc}")
            return 0
        finally:
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
