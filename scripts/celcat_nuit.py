"""Job de nuit Celcat : file d'attente des semaines validées + extras, et
(avec `--ecrire`) consommation RPC des jobs create/update/delete en file.

Par défaut (sans `--ecrire`) : AUDIT SEUL, ne se connecte pas à Live —
`executer_job_nuit()` sans page ne fait qu'empiler les jobs des semaines
validées et scanner les extras déjà connus. Avec `--ecrire` : ouvre
Playwright, monte le VPN si `--vpn`, se connecte, puis laisse
`executer_job_nuit(page=...)` consommer la file (create/update/delete) —
un échec RPC isolé reste en file pour la prochaine nuit, jamais un blocage
du lot entier. Mêmes conventions que `scripts/pousser_manquants_celcat.py` :
`--production` exigé pour écrire sur URCA_2026.

    python scripts/celcat_nuit.py
    python scripts/celcat_nuit.py --ecrire --vpn
    python scripts/celcat_nuit.py --ecrire --vpn --base URCA_2026 --production
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
from cal_iut.celcat.etat import charger
from cal_iut.celcat.nuit import executer_job_nuit


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    parseur.add_argument("--ecrire", action="store_true")
    parseur.add_argument("--production", action="store_true")
    args = parseur.parse_args()

    doc = charger()
    if not doc.get("saisie_active"):
        print("saisie inactive — rien à faire")
        return 0

    if args.ecrire and args.base == nav.BASE_PRODUCTION and not args.production:
        print("refus : URCA_2026 exige --production", file=sys.stderr)
        return 2

    if not args.ecrire:
        executer_job_nuit()
        print(
            "job nuit : file d'attente + extras mis à jour "
            "(audit — --ecrire pour consommer la file RPC create/update/delete)"
        )
        return 0

    try:
        from dotenv import load_dotenv

        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ.get("CELCAT_URL", "")
    if not url:
        print("CELCAT_URL absent", file=sys.stderr)
        return 2
    identifiant = os.environ.get("CELCAT_UTILISATEUR", "")
    motdepasse = os.environ.get("CELCAT_MOT_DE_PASSE", "")
    if not identifiant or not motdepasse:
        print(
            "CELCAT_UTILISATEUR / CELCAT_MOT_DE_PASSE absents de l'environnement (.env)",
            file=sys.stderr,
        )
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
            print(f"Connexion {args.base} rôle {args.role}…")
            nav.connexion(page, base=args.base, role=args.role)
            executer_job_nuit(page=page, base=args.base, production_autorisee=args.production)
            print("job nuit : file d'attente consommée (create/update/delete) + extras mis à jour")
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001, S110
                pass
            navigateur.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
