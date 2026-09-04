"""Inspecte le RAW d'un event_id précis (via un groupe donné), lecture seule.

    python scripts/inspecter_evenement_celcat.py --vpn --base URCA_2026 --groupe "BUT MMI S1 CM" --event-id 1933217
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.ecriture import resoudre_groupe  # noqa: E402
from cal_iut.celcat.rpc import charger_edt  # noqa: E402


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--groupe", required=True)
    parseur.add_argument("--event-id", type=int, required=True)
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

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {args.base} rôle lecture…")
            nav.connexion(page, base=args.base, role=nav.ROLE_LECTURE)
            gid = resoudre_groupe(page, args.groupe)
            for b in charger_edt(page, group_ids=[gid]):
                if int(b.get("event_id") or b.get("id") or -1) == args.event_id:
                    print(json.dumps(b, ensure_ascii=False, indent=2))
                    return 0
            print(f"event_id={args.event_id} introuvable dans {args.groupe!r}", file=sys.stderr)
            return 2
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
