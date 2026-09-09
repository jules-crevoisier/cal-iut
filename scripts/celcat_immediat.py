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
from contextlib import nullcontext
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import reseau
from cal_iut.celcat.etat import charger, worker_en_pause
from cal_iut.celcat.file_attente import lister
from cal_iut.celcat.nuit import drainer_file_immediate


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    parseur.add_argument("--ecrire", action="store_true")
    parseur.add_argument("--production", action="store_true")
    parseur.add_argument(
        "--limite",
        type=int,
        default=0,
        help=(
            "nombre maximum de jobs par cycle (0 = tous, le défaut). Ce plafond "
            "valait 25, proxy d'un coût de ~16 s/job qui n'existe plus : c'est "
            "--duree-max qui borne désormais le cycle."
        ),
    )
    parseur.add_argument(
        "--duree-max",
        type=float,
        default=600.0,
        dest="duree_max",
        help=(
            "budget de temps du cycle, en secondes (0 = sans limite). C'est la "
            "vraie contrainte : la session du compte Celcat est PARTAGÉE avec "
            "l'équipe et ne doit pas être tenue des heures. Ce qui dépasse "
            "reste en file et repart au cycle suivant."
        ),
    )
    args = parseur.parse_args()

    # Le worker peut être mis en PAUSE depuis l'interface : le VPN et le
    # compte Celcat sont partagés avec l'équipe, et un cycle toutes les 90
    # secondes empêche quiconque d'ouvrir une session durable. La pause ne
    # touche PAS à la file d'attente — elle reprendra telle quelle.
    if worker_en_pause():
        print("worker en pause — VPN non monté")
        return 0

    doc = charger()
    if not doc.get("saisie_active"):
        print("saisie inactive — rien à faire")
        return 0

    # INDISPENSABLE avant tout drainage : `get_state()` rend un état VIDE
    # tant que personne ne l'a peuplé, et `startup()` (qui s'en charge côté
    # API) n'est jamais exécuté ici. Sans cet appel, `entrees_pour_state()`
    # ne connaît aucune séance et TOUS les jobs sont écartés comme
    # « inconnus de la maquette » — sans erreur, sans exception : c'est
    # exactement ce qui a bloqué 463 écritures Celcat jusqu'au 07/09/2026.
    from cal_iut.api.main import charger_etat_applicatif

    charger_etat_applicatif()

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
    # `reseau.acces` rend le tunnel en sortant du bloc — appelé toutes les
    # 30 s par le sidecar, ce script ne doit garder la session du compte que
    # le temps du drainage (retour utilisateur 07/09/2026 : « quand on a pas
    # besoin de faire des actions dessus, le VPN se désactive »). Sans VPN
    # (sur site), `nullcontext` porte le même diagnostic sans rien à rendre.
    contexte = reseau.acces(url, monter_le_vpn=True) if args.vpn else nullcontext(reseau.verifier(url))
    try:
        with contexte as diag:
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
                    bilan = drainer_file_immediate(
                        page=page,
                        base=args.base,
                        production_autorisee=args.production,
                        limite=args.limite,
                        duree_max_s=args.duree_max,
                    )
                    # Le bilan, jamais un « drainée » de principe : c'est ce
                    # message trop optimiste qui a laissé passer plusieurs
                    # jours de panne totale (07/09/2026), le worker répétant
                    # « file d'attente drainée » sans écrire une seule fois.
                    print(bilan.resume())
                    # Trace lue par l'interface : sans elle, l'information
                    # n'existe que dans `docker compose logs`, c'est-à-dire
                    # nulle part pour qui utilise l'application.
                    from cal_iut.celcat.drainage import enregistrer as tracer

                    tracer(
                        en_attente=bilan.en_attente, reussis=bilan.reussis,
                        echecs=len(bilan.echecs), ignores=len(bilan.ignores),
                        differes=len(bilan.differes),
                        resume=bilan.resume(),
                    )
                finally:
                    try:
                        nav.deconnexion(page)
                    except Exception:  # noqa: BLE001, S110
                        pass
                    navigateur.close()
    except reseau.AccesIndisponible as exc:
        print(f"Celcat injoignable : {exc}", file=sys.stderr)
        return 3
    if getattr(diag, "monte_par_nous", False):
        print("VPN rendu (session libérée pour le compte partagé)")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
