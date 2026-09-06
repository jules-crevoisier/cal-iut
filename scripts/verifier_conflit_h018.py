"""Vérifie en direct (lecture seule) l'occupation COMPLÈTE de la salle
H.018 (Amphi 3 MMI) le mercredi, tous groupes/départements confondus —
retour utilisateur 06/09/2026 : doublon de salle mercredi après-midi
entre Régis Huez (CM MMI) et une enseignante de TC.

    python verifier_conflit_h018.py --vpn
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
from cal_iut.celcat.ecriture import resoudre_groupe  # noqa: E402
from cal_iut.celcat.lecture import evenement_depuis_rpc  # noqa: E402
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

            gid = resoudre_groupe(page, "BUT MMI S1 CM")
            room_id = 1604428  # H.018 / Amphi 3 MMI, relevé le 04-05/09/2026

            bruts = appeler(page, "udlTimetables.load", [{"RoomIDs": [room_id]}])
            print(f"{len(bruts)} événement(s) au total dans cette salle\n")
            evenements = [evenement_depuis_rpc(b, group_id=gid, groupe_nom="?") for b in bruts]

            mercredi = sorted(
                [e for e in evenements if e.jour == 3],
                key=lambda e: (e.heure_debut, e.event_id),
            )
            print(f"=== Mercredi (jour=3) — {len(mercredi)} événement(s) dans H.018 ===")
            for e in mercredi:
                print(
                    f"  event_id={e.event_id:8} {e.heure_debut}-{e.heure_fin} "
                    f"module={e.module_nom!r} enseignant={e.enseignant!r} "
                    f"groupe={e.groupe_nom!r} cat={e.categorie!r} weeks_Y={e.weeks.count('Y')}"
                )

            # Détection de recouvrement horaire brut, même semaine.
            print("\n=== Recouvrements horaires détectés (même semaine, même salle) ===")
            trouve = False
            for i, a in enumerate(mercredi):
                for b in mercredi[i + 1:]:
                    if a.heure_debut >= b.heure_fin or b.heure_debut >= a.heure_fin:
                        continue
                    memes_semaines = any(x == "Y" and y == "Y" for x, y in zip(a.weeks, b.weeks))
                    if memes_semaines:
                        trouve = True
                        print(f"  CONFLIT : {a.event_id} ({a.enseignant}, {a.heure_debut}-{a.heure_fin}) <-> {b.event_id} ({b.enseignant}, {b.heure_debut}-{b.heure_fin})")
            if not trouve:
                print("  aucun recouvrement horaire trouvé sur une semaine commune")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
