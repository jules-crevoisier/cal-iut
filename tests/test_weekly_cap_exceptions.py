"""
Dérogation CIBLÉE au plafond horaire hebdomadaire (14/08/2026, cf.
`WeeklyCapException`, `solver/decomposed.py::assign_weeks`, paramètre
`cap_exceptions`) — remplace un premier essai de relevé GLOBAL du plafond
(22 -> 23 partout), annulé le même jour : mesuré sur un run réel que le
relevé global pousse l'étage 2 à exploiter la marge PARTOUT (61 paires
cohorte/semaine poussées à la nouvelle limite au lieu de 14), dégradant la
fiabilité du run entier au lieu de la seule semaine visée (WR106). Cf.
docs/DATA.md §61.1/§62.
"""

from pathlib import Path

from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
from cal_iut.ingestion.config_loader import load_weekly_cap_exceptions
from cal_iut.models.entities import Group, WeeklyCapException
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import (
    _rebalance_failed_weeks,
    assign_weeks,
    weekly_cap_exceptions_by_parcours_week,
)

ROOT = Path(__file__).resolve().parents[1]


def _session(sid: str, parcours: str, group_id: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code="WRTEST",
        course_name="Test",
        semestre="S1",
        parcours=parcours,
        annee="BUT1",
        session_type="TD",
        sequence_order=1,
        group_ids=[group_id],
        teacher_codes=["T1"],
    )


def test_real_config_declares_the_wr106_exception():
    """Le fichier réel `course_scheduling_rules.yaml` déclare bien la
    dérogation WR106 (BUT1/S1, semaine du 30/11/2026, plafond 23) — donnée
    jamais devinée, cf. règle "donnée fraîche" du projet."""
    exceptions = load_weekly_cap_exceptions(ROOT / "data" / "config")
    matching = [e for e in exceptions if e.parcours == "BUT1" and e.semestre == "S1"]
    assert matching, "aucune dérogation BUT1/S1 trouvée dans course_scheduling_rules.yaml"
    exc = matching[0]
    assert exc.week_monday == "2026-11-30"
    assert exc.cap == 23
    assert exc.note and "Kyllian" in exc.note


def test_resolver_maps_the_real_monday_to_the_correct_solver_week_index():
    """`weekly_cap_exceptions_by_parcours_week` doit résoudre le 30/11/2026
    en semaine-index solveur 12 (S1, offset 0) — vérifié indépendamment du
    diagnostic qui a produit cette date, pas une simple ré-affirmation."""
    calendar = build_default_calendar_2026_2027()
    week_offset = semester_week_offset(calendar, "S1")
    exc = WeeklyCapException(parcours="BUT1", semestre="S1", week_monday="2026-11-30", cap=23)

    resolved = weekly_cap_exceptions_by_parcours_week([exc], calendar, week_offset)

    assert resolved == {("BUT1", 12): 23}


def test_assign_weeks_without_exception_caps_at_22():
    groups = [Group(id="g-tp", label="TP", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20)]
    sessions = [_session(f"s{i}", "TEST-FI", "g-tp") for i in range(23)]

    result = assign_weeks(
        sessions, groups, weeks=1,
        teacher_weekly_cap_slots=30,
        fi_cap_slots=22,
        time_limit_seconds=10,
    )
    assert result.status not in ("OPTIMAL", "FEASIBLE")


def test_assign_weeks_respects_a_targeted_cap_exception():
    """La même situation (23 séances, 1 semaine), mais avec une dérogation
    ciblée sur (TEST-FI, semaine 0) -> doit réussir."""
    groups = [Group(id="g-tp", label="TP", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20)]
    sessions = [_session(f"s{i}", "TEST-FI", "g-tp") for i in range(23)]

    result = assign_weeks(
        sessions, groups, weeks=1,
        teacher_weekly_cap_slots=30,
        fi_cap_slots=22,
        cap_exceptions={("TEST-FI", 0): 23},
        time_limit_seconds=10,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_cap_exception_does_not_leak_to_a_different_parcours():
    """La dérogation sur TEST-FI ne doit pas s'appliquer à TEST-AUTRE-FI."""
    groups = [Group(id="g-tp2", label="TP2", parcours="TEST-AUTRE-FI", annee="TEST", kind="tp", headcount=20)]
    sessions = [_session(f"s{i}", "TEST-AUTRE-FI", "g-tp2") for i in range(23)]

    result = assign_weeks(
        sessions, groups, weeks=1,
        teacher_weekly_cap_slots=30,
        fi_cap_slots=22,
        cap_exceptions={("TEST-FI", 0): 23},  # un AUTRE parcours
        time_limit_seconds=10,
    )
    assert result.status not in ("OPTIMAL", "FEASIBLE")


def test_rebalance_cohort_cap_for_respects_cap_exceptions():
    """`_rebalance_failed_weeks` doit voir la MÊME dérogation que l'étage 2 —
    autorise un déplacement vers une semaine à la limite normale (22) mais
    dérogatoire (23) pour ce parcours précis, refuse ce même déplacement
    sans la dérogation."""
    groups = [Group(id="g1", label="G1", parcours="TEST-FI", annee="TEST", kind="td", headcount=10)]

    def _run(cap_exceptions):
        # Horizon à SEULEMENT 2 semaines (pas de 3e semaine vide où S1
        # pourrait s'échapper) : la seule question testée est "la semaine 1,
        # déjà à 22/22, peut-elle accueillir S1 malgré tout ?".
        s1 = _session("S1", "TEST-FI", "g1")
        filler = [_session(f"f{i}", "TEST-FI", "g1") for i in range(22)]  # sature la semaine 1 à 22
        sessions_by_week = {0: [s1], 1: list(filler)}
        week_by_session = {"S1": 0, **{f.id: 1 for f in filler}}
        session_by_id = {"S1": s1, **{f.id: f for f in filler}}
        _rebalance_failed_weeks(
            [0],
            sessions_by_week,
            week_by_session,
            session_by_id,
            weeks=2,
            duos=None,
            cohorts={"g1": {"g1"}},
            group_by_id={"g1": groups[0]},
            teacher_weekly_cap_slots=30,
            fi_cap_slots=22,
            fc_cap_slots=23,
            cap_exceptions=cap_exceptions,
            max_moves_per_week=1,
        )
        return week_by_session

    without = _run(None)
    with_exception = _run({("TEST-FI", 1): 23})

    assert without["S1"] == 0, "sans dérogation, semaine 1 déjà à 22/22 : S1 ne doit pas pouvoir y aller"
    assert with_exception["S1"] == 1, "avec la dérogation (TEST-FI, semaine 1) -> 23, le déplacement doit réussir"
