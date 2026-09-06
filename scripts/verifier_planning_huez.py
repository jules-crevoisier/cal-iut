"""Cherche le planning complet de Régis Huez (lecture seule) — retour
utilisateur 06/09/2026 : où est son CM du mercredi après-midi ?

    python verifier_planning_huez.py --vpn
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.ecriture import _catalogue  # noqa: E402
from cal_iut.celcat.lecture import evenement_depuis_rpc  # noqa: E402
from cal_iut.celcat.navigateur import TYPE_PERSONNEL  # noqa: E402
from cal_iut.celcat.rpc import appeler  # noqa: E402


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    args = parseur.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ.get("CELCAT_URL", "")
    diag = reseau.exiger_acces(url, monter_le_vpn=args.vpn) if args.vpn else reseau.verifier(url)
    if not getattr(diag, "joignable", False):
        print("injoignable", diag.detail)
        return 3

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print("Connexion URCA_2026 rôle lecture…")
            nav.connexion(page, base=nav.BASE_PRODUCTION, role=nav.ROLE_LECTURE)

            print("Recherche de HUEZ dans le personnel…")
            lots = _catalogue(page, TYPE_PERSONNEL)
            candidats = [
                p for p in lots
                if "HUEZ" in str(p.get("name") or "").upper() or "HUEZ" in str(p.get("unique_name") or "").upper()
            ]
            for c in candidats:
                print(f"  keys={sorted(c.keys())}")
                print(f"  id={c.get('id')} staff_id={c.get('staff_id')} name={c.get('name')!r} unique_name={c.get('unique_name')!r}")
            if not candidats:
                print("  introuvable")
                return 2
            staff_id = int(candidats[0].get("id") or candidats[0].get("staff_id"))

            print(f"\nRequête udlTimetables.load StaffIDs=[{staff_id}]…")
            for cle in ("StaffIDs", "StaffID"):
                try:
                    bruts = appeler(page, "udlTimetables.load", [{cle: [staff_id]}])
                    print(f"  {cle} : OK, {len(bruts)} événement(s)")
                    if bruts:
                        evenements = [evenement_depuis_rpc(b, group_id=0, groupe_nom="?") for b in bruts]
                        for e in sorted(evenements, key=lambda e: (e.jour, e.heure_debut)):
                            print(
                                f"    event_id={e.event_id:8} jour={e.jour} {e.heure_debut}-{e.heure_fin} "
                                f"salle={e.salle!r} module={e.module_nom!r} groupe={e.groupe_nom!r} "
                                f"weeks_Y={e.weeks.count('Y')}"
                            )
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"  {cle} : ÉCHEC {exc}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
