"""Supprime les doublons connus en PRODUCTION (URCA_2026), maintenant que
`methode_suppression` est prouvée (05/09/2026) :

- WR107-S1-CM-1 : event_id 1933243 (mardi 17h-18h30), résidu antérieur au
  04/09/2026, laissé à côté du bon event_id 1944992 (corrigé le 05/09 pour
  refléter le déplacement de Kyllian Bresson vers mercredi 9h30-11h).
- WR116, mardi 14h : TRIPLE doublon connu depuis le 02/09/2026 — event_ids
  1931709, 1933218, 1933241, tous identiques. On garde le PLUS ANCIEN
  (1931709) et supprime les deux autres.

Toujours en groupe « BUT MMI S1 CM » (group_id 1661971).

    python scripts/nettoyer_doublons_production_celcat.py --vpn --ecrire
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
from cal_iut.celcat.suppression import SuppressionRefusee, supprimer_evenement  # noqa: E402

GROUP_ID = 1661971  # BUT MMI S1 CM

CIBLES = [
    (1933243, "WR107 mardi 17h-18h30, résidu antérieur au 04/09"),
    (1933218, "WR116 mardi 14h, doublon 2/3 (on garde 1931709)"),
    (1933241, "WR116 mardi 14h, doublon 3/3 (on garde 1931709)"),
]


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    parseur.add_argument("--ecrire", action="store_true")
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

    methodes = charger_methodes(RACINE / "data" / "config")
    if not methodes.methode_suppression:
        print("methode_suppression vide", file=sys.stderr)
        return 2

    print(f"{'ÉCRITURE RÉELLE' if args.ecrire else 'RÉPÉTITION (rien envoyé)'} sur URCA_2026")
    for eid, motif in CIBLES:
        print(f"  {eid} : {motif}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"\nConnexion URCA_2026 rôle {args.role}…")
            nav.connexion(page, base=nav.BASE_PRODUCTION, role=args.role)
            for eid, motif in CIBLES:
                if not args.ecrire:
                    print(f"  {eid} : (répétition, rien envoyé) — {motif}")
                    continue
                try:
                    supprimer_evenement(
                        page, eid, group_id=GROUP_ID, methode=methodes.methode_suppression,
                        base=nav.BASE_PRODUCTION, production_autorisee=True,
                    )
                    print(f"  {eid} : SUPPRIMÉ")
                except SuppressionRefusee as exc:
                    print(f"  {eid} : REFUSÉ (garde-fou) — {exc}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  {eid} : ÉCHEC — {exc}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
