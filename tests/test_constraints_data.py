"""Tests chargement contraintes et ordre pédagogique."""

from datetime import date
from pathlib import Path

from cal_iut.calendar.academic import build_default_calendar_2026_2027, parse_french_date
from cal_iut.ingestion.constraints_loader import (
    load_all_constraints,
    parse_teacher_unavailability,
)
from cal_iut.models.session import SessionToPlace
from cal_iut.models.entities import SessionType
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver

ROOT = Path(__file__).resolve().parents[1]


def test_parse_french_date() -> None:
    assert parse_french_date("vendredi 20 novembre 2026") == date(2026, 11, 20)
    assert parse_french_date("lundi 4 janvier 2027") == date(2027, 1, 4)


def test_parse_teacher_unavailability_patterns() -> None:
    slots, dates = parse_teacher_unavailability(
        "vendredi après-midi - lundi 14 décembre 2026 - lundi toute la journée"
    )
    assert (4, 3) in slots  # vendredi 14h
    assert (0, 0) in slots  # lundi 8h
    assert date(2026, 12, 14) in dates


def test_load_all_constraints_from_project() -> None:
    bundle = load_all_constraints(ROOT)
    assert bundle.calendar.weeks >= 20
    assert len(bundle.teachers) >= 10
    assert any(t.teacher_code == "DAN" for t in bundle.teachers)
    assert any(p.label for p in bundle.student_presences)
    but3 = next(p for p in bundle.student_presences if "BUT3" in ",".join(p.parcours_keys))
    assert len(but3.presence_dates) > 10


def test_calendar_blocks_holidays() -> None:
    cal = build_default_calendar_2026_2027()
    assert date(2026, 11, 11) in cal.holidays
    blocked = cal.blocked_time_indices(weeks=40)
    assert len(blocked) > 0


def test_pedagogical_order_and_group_sync() -> None:
    """Deux groupes TD : ordre 1 avant ordre 2, même semaine."""
    sessions = [
        SessionToPlace(
            id="c-td1-g1",
            course_code="WR101",
            course_name="Anglais",
            semestre="S1",
            parcours="BUT1",
            annee="BUT1",
            session_type=SessionType.TD,
            sequence_order=1,
            group_ids=["g1"],
            teacher_codes=["T1"],
        ),
        SessionToPlace(
            id="c-td1-g2",
            course_code="WR101",
            course_name="Anglais",
            semestre="S1",
            parcours="BUT1",
            annee="BUT1",
            session_type=SessionType.TD,
            sequence_order=1,
            group_ids=["g2"],
            teacher_codes=["T2"],
        ),
        SessionToPlace(
            id="c-td2-g1",
            course_code="WR101",
            course_name="Anglais",
            semestre="S1",
            parcours="BUT1",
            annee="BUT1",
            session_type=SessionType.TD,
            sequence_order=2,
            group_ids=["g1"],
            teacher_codes=["T1"],
        ),
        SessionToPlace(
            id="c-td2-g2",
            course_code="WR101",
            course_name="Anglais",
            semestre="S1",
            parcours="BUT1",
            annee="BUT1",
            session_type=SessionType.TD,
            sequence_order=2,
            group_ids=["g2"],
            teacher_codes=["T2"],
        ),
    ]
    result = TimetableSolver(
        SolverConfig(weeks=4, optimize_gaps=False, time_limit_seconds=30)
    ).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    by_id = {p.session_id: p for p in result.placements}
    # Sync molle : ordre pédagogique reste dur
    t1 = by_id["c-td1-g1"].week * 30 + by_id["c-td1-g1"].day * 6 + by_id["c-td1-g1"].slot
    t2 = by_id["c-td2-g1"].week * 30 + by_id["c-td2-g1"].day * 6 + by_id["c-td2-g1"].slot
    assert t1 < t2
    # Avec peu de séances, la sync molle aligne encore les groupes
    assert by_id["c-td1-g1"].week == by_id["c-td1-g2"].week
