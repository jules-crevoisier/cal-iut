"""Teste l'hypothèse : `suspended: "Y"` via `udlTimetables.save` (méthode
déjà PROUVÉE, `methode_ecriture`) fait-il disparaître un événement du
rechargement d'EDT, sans passer par une méthode `delete` dédiée (aucune
trouvée dans `udlTimetables.*` — cf. `scanner_methodes_udl_celcat.py`) ?

Cible un event_id de canari déjà créé sur URCA_FORMATION (laissé par des
tentatives précédentes de capture de suppression), localise son
enregistrement FRAIS, clone-le en ne changeant QUE `suspended`, sauve,
puis relit l'EDT pour vérifier.

    python scripts/tester_suspended_celcat.py --vpn --event-id 1523408 --group-id 47925
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
from cal_iut.celcat.modification import EvenementIntrouvable, localiser_evenement  # noqa: E402
from cal_iut.celcat.rpc import charger_edt, enregistrer_evenement  # noqa: E402


def _methode_ecriture() -> str:
    chemin = RACINE / "data" / "config" / "celcat_rpc.yaml"
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("methode_ecriture:"):
            return ligne.split(":", 1)[1].strip()
    return ""


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--event-id", type=int, required=True)
    parseur.add_argument("--group-id", type=int, required=True)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    parseur.add_argument("--weeks-all-n", action="store_true", help="teste weeks=tout à N au lieu de suspended=Y")
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

    methode = _methode_ecriture()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion URCA_FORMATION rôle {args.role}…")
            nav.connexion(page, base=nav.BASE_ENTRAINEMENT, role=args.role)

            try:
                brut = localiser_evenement(page, args.event_id, group_ids=[args.group_id])
            except EvenementIntrouvable:
                print(f"event_id={args.event_id} déjà introuvable (peut-être déjà nettoyé)", file=sys.stderr)
                return 2
            print(f"  localisé : suspended actuel = {brut.get('suspended')!r}, weeks={brut.get('weeks')!r}")

            fusionne = dict(brut)
            if args.weeks_all_n:
                fusionne["weeks"] = "N" * len(str(brut.get("weeks") or "N" * 54))
                print(f"  sauvegarde avec weeks tout à N ({fusionne['weeks']})…")
            else:
                fusionne["suspended"] = "Y"
                print("  sauvegarde avec suspended='Y'…")
            retour = enregistrer_evenement(page, fusionne, methode=methode)
            print(f"  retour save : {retour!r}")

            print("  rechargement EDT pour vérifier (RPC direct, pas besoin d'UI)…")
            evenements = charger_edt(page, group_ids=[args.group_id])
            trouve = next(
                (e for e in evenements if int(e.get("event_id") or e.get("id") or -1) == args.event_id),
                None,
            )
            if trouve is None:
                print(f"\n>>> event_id={args.event_id} N'APPARAÎT PLUS dans udlTimetables.load — suspended fonctionne comme suppression !")
            else:
                print(f"\n>>> event_id={args.event_id} apparaît TOUJOURS, suspended={trouve.get('suspended')!r} — l'hypothèse est fausse.")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
