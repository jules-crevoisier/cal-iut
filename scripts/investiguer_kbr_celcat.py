"""Investigue en direct (lecture seule) le CM de Kyllian Bresson (KBR) sur
Celcat — retour utilisateur 04/09/2026 : un CM déplacé mardi soir -> mercredi
matin sur cal-iut ne s'est jamais reflété sur Celcat, et Kyllian a ensuite
recréé un second CM le mardi soir directement dans Celcat (n'ayant
probablement pas vu celui déjà en place). Liste tous les événements [CM] de
la promo BUT MMI S1 (groupe partagé par tous ses CM S1) le mardi et le
mercredi, avec le libellé du module et le nombre de semaines actives, pour
repérer le doublon et l'écart sans rien modifier.

    python scripts/investiguer_kbr_celcat.py --vpn --base URCA_2026
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
from cal_iut.celcat.ecriture import resoudre_groupe
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.rpc import charger_edt

GROUPES_A_SCANNER = [
    "BUT MMI S1 CM",
    "BUT MMI S3 CM",
]


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
            for nom in GROUPES_A_SCANNER:
                try:
                    gid = resoudre_groupe(page, nom)
                except Exception as exc:  # noqa: BLE001
                    print(f"  groupe introuvable {nom} : {exc}")
                    continue
                evenements = [
                    evenement_depuis_rpc(b, group_id=gid, groupe_nom=nom)
                    for b in charger_edt(page, group_ids=[gid])
                ]
                # jour Celcat : 1=lundi ... on regarde mardi (2) et mercredi (3).
                cibles = [e for e in evenements if e.jour in (2, 3) and e.categorie == "[CM]"]
                cibles.sort(key=lambda e: (e.jour, e.heure_debut, e.event_id))
                print(f"\n=== {nom} (gid={gid}) — {len(cibles)} CM mardi/mercredi ===")
                for e in cibles:
                    print(
                        f"  event_id={e.event_id:8} jour={e.jour} {e.heure_debut}-{e.heure_fin} "
                        f"salle={e.salle or '—':12} module={e.module_nom!r} "
                        f"enseignant={e.enseignant!r} weeks_Y={e.weeks.count('Y')} "
                        f"weeks={e.weeks}"
                    )
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
