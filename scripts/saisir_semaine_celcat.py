"""Saisir UNE semaine dans Celcat, en sautant les correspondances manquantes.

Ne clique jamais Enregistrer si le formulaire porte autre chose qu'UNE
semaine (incident du 01/09/2026 : `new` coche les 54 semaines). Ne supprime
rien. Modifier = double-clic, pas encore automatisé.

    python scripts/saisir_semaine_celcat.py --lundi 2026-09-07
    python scripts/saisir_semaine_celcat.py --lundi 2026-09-07 --ecrire --vpn --production
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.api import custom_sessions, session_overrides  # noqa: E402
from cal_iut.calendar.academic import (  # noqa: E402
    build_default_calendar_2026_2027,
    semester_week_offset,
)
from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau, sync  # noqa: E402
from cal_iut.celcat.driver import PilotePlaywright, PiloteSimule, Rythme, SaisieCelcat  # noqa: E402
from cal_iut.celcat.formulaire import charger_carte  # noqa: E402
from cal_iut.celcat.mapping import entree_pour_placement, load_celcat_config  # noqa: E402
from cal_iut.db.models import CurrentPlacement  # noqa: E402
from cal_iut.db.repository import PlanningRepository  # noqa: E402
from cal_iut.db.session import get_db, init_db  # noqa: E402
from cal_iut.ingestion.config_loader import load_groups  # noqa: E402
from cal_iut.ingestion.pipeline import run_ingestion  # noqa: E402


def _lundi_iso(calendrier, semestre: str, week: int) -> str:
    index = semester_week_offset(calendrier, semestre) + week
    if 0 <= index < len(calendrier.teaching_mondays):
        return calendrier.teaching_mondays[index].isoformat()
    return ""


def _semaine_relative(calendrier, lundi: dt.date) -> int:
    offset = semester_week_offset(calendrier, "S1")
    for i, m in enumerate(calendrier.teaching_mondays):
        if m == lundi:
            return i - offset
    raise SystemExit(f"lundi {lundi.isoformat()} hors calendrier enseignable")


def _charger_entrees(lundi: dt.date):
    config_dir = RACINE / "data" / "config"
    calendrier = build_default_calendar_2026_2027()
    semaine = _semaine_relative(calendrier, lundi)
    result = run_ingestion(config_dir, semestre_group="odd")
    sessions = {s.id: s for s in result.sessions}
    sessions_list, sessions = custom_sessions.merge_into(list(sessions.values()), sessions)
    session_overrides.apply_to(sessions)

    init_db()
    repo = PlanningRepository(get_db())
    run = repo.get_latest_run()
    if run is None:
        raise SystemExit("aucun planning en base (data/state/cal-iut.db)")
    rows = repo.db.query(CurrentPlacement).filter_by(run_id=run.id).all()

    groups = {g.id: g.label for g in load_groups(config_dir)}
    cfg = load_celcat_config(config_dir)
    entrees = []
    for row in rows:
        if row.week != semaine:
            continue
        session = sessions.get(row.session_id)
        if session is None:
            continue
        semestre = session.semestre or ""
        entrees.append(entree_pour_placement(
            cfg,
            session_id=row.session_id,
            course_code=row.course_code,
            session_type=str(session.session_type),
            week=row.week,
            day=row.day,
            slot=row.slot,
            duration_slots=max(1, session.duration_slots or 1),
            teacher_codes=list(session.teacher_codes or []),
            room_id=row.room_id,
            groupe=", ".join(groups.get(g, g) for g in (session.group_ids or [])),
            semestre=semestre,
            lundi=_lundi_iso(calendrier, semestre, row.week),
        ))
    return semaine, entrees


def _inventaire(plan) -> None:
    print(plan.resume())
    motifs: Counter[str] = Counter()
    for e in plan.bloquees:
        for b in e.bloquants:
            motifs[b] += 1
    if motifs:
        print("bloquées (ignorées à l'écriture) :")
        for motif, n in motifs.most_common(12):
            print(f"  {n:4d}  {motif}")
    par_groupe = Counter(e.nom_groupe_celcat for e in plan.a_creer)
    if par_groupe:
        print("à créer :")
        for nom, n in sorted(par_groupe.items()):
            print(f"  {n:4d}  {nom}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lundi", default="2026-09-07")
    parser.add_argument("--ecrire", action="store_true")
    parser.add_argument("--vpn", action="store_true")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--limite", type=int, default=0)
    parser.add_argument("--groupe", default="")
    args = parser.parse_args()

    lundi = dt.date.fromisoformat(args.lundi)
    semaine, entrees = _charger_entrees(lundi)
    if args.groupe:
        frag = args.groupe.strip().upper()
        entrees = [e for e in entrees if frag in e.nom_groupe_celcat.upper()]
    plan = sync.construire_plan(entrees, {semaine})
    print(f"semaine solveur {semaine} = lundi {lundi.isoformat()}")
    _inventaire(plan)

    if args.limite and plan.a_creer:
        plan.a_creer = plan.a_creer[: args.limite]
        print(f"limite : {len(plan.a_creer)} séance(s) seront saisies")

    if not args.ecrire:
        print("répétition (rien n'est envoyé). --ecrire pour écrire.")
        pilote = PiloteSimule()
        SaisieCelcat(pilote, Rythme(
            entre_actions=(0, 0), entre_seances=(0, 0), entre_groupes=(0, 0),
            pause_longue_toutes_les=0,
        )).executer(plan, "(simulation)", "", ignorer_bloquees=True)
        for action in pilote.actions[:40]:
            print(" ", action)
        if len(pilote.actions) > 40:
            print(f"  … {len(pilote.actions) - 40} de plus")
        return 0

    carte = charger_carte(RACINE / "data" / "config")
    if not carte.confirmee:
        raise SystemExit("formulaire incomplet : " + ", ".join(carte.manques()))
    identifiant = os.environ.get("CELCAT_UTILISATEUR", "")
    motdepasse = os.environ.get("CELCAT_MOT_DE_PASSE", "")
    if not identifiant or not motdepasse:
        raise SystemExit("CELCAT_UTILISATEUR / CELCAT_MOT_DE_PASSE absents")
    reseau.exiger_acces(PilotePlaywright.URL_CONNEXION, monter_le_vpn=args.vpn)
    base = nav.BASE_PRODUCTION if args.production else nav.BASE_ENTRAINEMENT
    visible = bool(os.environ.get("DISPLAY"))
    pilote = PilotePlaywright(
        Rythme(), base=base, carte=carte,
        config_dir=RACINE / "data" / "config", visible=visible,
    )
    print(f"écriture {base} rôle {pilote.role} visible={visible}")
    resultat = SaisieCelcat(
        pilote, Rythme(), journaliser=sync.marquer_saisi,
        verifier_acces=lambda: bool(reseau.verifier(PilotePlaywright.URL_CONNEXION)),
    ).executer(plan, identifiant, motdepasse, ignorer_bloquees=True)
    print(resultat.resume())
    for sid, motif in resultat.echecs:
        print(f"  échec {sid}: {motif}")
    for action in pilote.actions:
        print(" ", action)
    return 0 if not resultat.echecs and not resultat.interrompu else 1


if __name__ == "__main__":
    raise SystemExit(main())
