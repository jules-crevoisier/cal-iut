"""Drainage IMMÉDIAT de la file d'attente Celcat (create/update/delete) —
jamais le balayage par semaine ni le marquage `semaines_lancees`, réservés
au job de nuit (`scripts/celcat_nuit.py`). Retour utilisateur 07/09/2026 :
« sur les update on veut tenter en temps réel, pas la nuit ».

Conçu pour être appelé souvent (cf. `deploy/celcat-sidecar/nuit-
quotidienne.sh`) : se termine tout de suite, sans connexion Live, si la
file est vide — la vérification est un simple JSON local, aucun coût VPN.

    python scripts/celcat_immediat.py --ecrire --vpn --base URCA_2026 --production
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
from cal_iut.celcat.file_attente import lister
from cal_iut.celcat.nuit import drainer_file_immediate


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

    # Vérification SANS VPN : pas la peine de monter une connexion Live
    # pour une file vide, c'est le cas le plus fréquent entre deux
    # déplacements de séance.
    if not lister():
        print("file d'attente vide — rien à faire")
        return 0

    if args.ecrire and args.base == nav.BASE_PRODUCTION and not args.production:
        print("refus : URCA_2026 exige --production", file=sys.stderr)
        return 2

    if not args.ecrire:
        print(f"{len(lister())} job(s) en attente — --ecrire pour les consommer")
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
            traite = drainer_file_immediate(page=page, base=args.base, production_autorisee=args.production)
            print("file d'attente drainée (temps réel)" if traite else "rien à drainer")
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001, S110
                pass
            navigateur.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
