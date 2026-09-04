"""Correctif ponctuel : WR107-S1-CM-1 a été créé aujourd'hui (04/09/2026,
`pousser_manquants_celcat.py`) sur le CRÉNEAU LOCAL (mardi 15h30-17h),
alors que la production — vérifiée via `cal-iut prod diff` avec la
nouvelle clé API — le place en réalité mercredi 9h30-11h (le déplacement
que Kyllian Bresson a fait sur cal-iut, jamais remonté sur Celcat faute de
drain nocturne, cf. docs/CELCAT.md). Corrige l'event_id créé par erreur
plutôt que d'en laisser un troisième traîner à côté du doublon déjà connu.

    python scripts/corriger_wr107_cm1_celcat.py --vpn --base URCA_2026 --production --ecrire
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

SESSION_ID = "WR107-S1-CM-1"
EVENT_ID = 1944992
GROUP_ID = 1661971  # BUT MMI S1 CM
# Valeurs prod confirmées par `cal-iut prod diff` le 05/09/2026 :
# WR107-S1-CM-1  local=(1, 1, 4, 'h018')  prod=(1, 2, 1, 'h018')
WEEK, DAY, SLOT, ROOM_ID = 1, 2, 1, "h018"


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", required=True)
    parseur.add_argument("--role", default=None)
    parseur.add_argument("--ecrire", action="store_true")
    parseur.add_argument("--production", action="store_true")
    args = parseur.parse_args()

    from cal_iut.celcat import navigateur as nav
    from cal_iut.celcat import reseau
    from cal_iut.celcat.ecriture import resoudre_ids
    from cal_iut.celcat.formulaire import charger_carte
    from cal_iut.celcat.mapping import entree_pour_placement, load_celcat_config
    from cal_iut.celcat.modification import modifier_evenement
    from cal_iut.celcat.rpc import MethodeEcritureAbsente, masquer_semaine

    # Champs intrinsèques à la séance (courses.json, invariants quel que
    # soit le placement) — pas besoin de `get_state()`/la base locale pour
    # ça, seulement le nouveau créneau confirmé côté prod ci-dessus.
    cfg = load_celcat_config(RACINE / "data" / "config")
    entree = entree_pour_placement(
        cfg,
        session_id=SESSION_ID,
        course_code="WR107",
        session_type="CM",
        week=WEEK, day=DAY, slot=SLOT,
        duration_slots=1,
        teacher_codes=["KBR"],
        room_id=ROOM_ID,
        groupe="BUT MMI S1 CM",
        semestre="S1",
        lundi="2026-09-07",  # semaine solveur 1 == lundi 2026-09-07 (confirmé 04/09/2026)
    )
    print(f"cible : jour={entree.jour} {entree.heure_debut}-{entree.heure_fin} salle={entree.salle}")
    if entree.bloquants:
        print(f"bloquants : {entree.bloquants}", file=sys.stderr)
        return 2

    def _methode_yaml() -> str:
        chemin = RACINE / "data" / "config" / "celcat_rpc.yaml"
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            if ligne.startswith("methode_ecriture:"):
                return ligne.split(":", 1)[1].strip()
        return ""

    methode = _methode_yaml()
    if args.ecrire and not methode:
        raise MethodeEcritureAbsente("methode_ecriture vide")

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

    role = args.role or (nav.ROLE_ECRITURE if args.ecrire else nav.ROLE_LECTURE)
    carte = charger_carte(RACINE / "data" / "config")
    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {args.base} rôle {role}…")
            nav.connexion(page, base=args.base, role=role)
            ids = resoudre_ids(page, entree, categorie=carte.categorie(entree.type_seance_nom))
            print(f"ids résolus : {ids}")
            if not args.ecrire:
                print("répétition (rien n'est envoyé). --ecrire pour appliquer.")
                return 0
            # indice=3 confirmé le 04/09/2026 (audit du même push) : "semaine
            # solveur 1 = lundi 2026-09-07 = indice weeks 3" — inchangé ici,
            # on ne déplace PAS de semaine, seulement de jour/heure.
            masque = masquer_semaine(longueur=54, indice=3)
            confirme = modifier_evenement(
                page, entree, event_id=EVENT_ID, group_id=GROUP_ID, ids=ids, masque=masque,
                methode=methode, base=args.base, production_autorisee=args.production,
            )
            print(f"OK — event_id confirmé : {confirme}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
