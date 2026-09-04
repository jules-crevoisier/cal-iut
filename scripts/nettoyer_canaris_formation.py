"""Nettoie les canaris laissés sur URCA_FORMATION par les tentatives de
capture de methode_suppression du 05/09/2026 (group_id 47925, BUT MMI S1
TD AB - 2024).

    python scripts/nettoyer_canaris_formation.py --vpn
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
from cal_iut.celcat.rpc_config import charger_methodes  # noqa: E402
from cal_iut.celcat.suppression import supprimer_evenement  # noqa: E402

GROUP_ID = 47925
EVENT_IDS = [1523406, 1523407, 1523408, 1523409, 1523410]


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    args = parseur.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ.get("CELCAT_URL", "")
    diag = reseau.exiger_acces(url, monter_le_vpn=args.vpn) if args.vpn else reseau.verifier(url)
    if not getattr(diag, "joignable", False):
        print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
        return 3

    methodes = charger_methodes(RACINE / "data" / "config")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {nav.BASE_ENTRAINEMENT} rôle {args.role}…")
            nav.connexion(page, base=nav.BASE_ENTRAINEMENT, role=args.role)
            for eid in EVENT_IDS:
                try:
                    supprimer_evenement(
                        page, eid, group_id=GROUP_ID, methode=methodes.methode_suppression,
                        base=nav.BASE_ENTRAINEMENT, production_autorisee=False,
                    )
                    print(f"  {eid} : supprimé (ou déjà absent)")
                except Exception as exc:  # noqa: BLE001
                    print(f"  {eid} : ÉCHEC {exc}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
