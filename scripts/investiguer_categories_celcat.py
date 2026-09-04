"""Relève en direct (lecture seule) la liste complète des catégories
d'événement Celcat (`TYPE_CATEGORIES_EVENEMENT` = 618) — sert à confirmer
le libellé exact et l'`event_cat_id` de « TD0 » (vue mais jamais utilisée,
cf. docs/CELCAT.md), avant de l'utiliser pour WR100BU (Valérie Mariot, BU).

    python scripts/investiguer_categories_celcat.py --vpn --base URCA_2026
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import reseau
from cal_iut.celcat.ecriture import _filtre_ressource
from cal_iut.celcat.navigateur import TYPE_CATEGORIES_EVENEMENT
from cal_iut.celcat.rpc import charger_ressources


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    args = parseur.parse_args()

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

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {args.base} rôle lecture…")
            nav.connexion(page, base=args.base, role=nav.ROLE_LECTURE)
            lots = charger_ressources(page, TYPE_CATEGORIES_EVENEMENT, _filtre_ressource())
            print(f"{len(lots)} catégorie(s)")
            for enreg in sorted(lots, key=lambda e: str(e.get("name") or "")):
                nom = enreg.get("name") or enreg.get("evCatName")
                unique = enreg.get("unique_name")
                cid = enreg.get("id") or enreg.get("event_cat_id")
                marque = "  <---" if "TD0" in str(unique or "") or "TD0" in str(nom or "") else ""
                print(f"  id={cid} unique_name={unique!r} name={nom!r}{marque}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
