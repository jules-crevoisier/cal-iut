"""Tests validation déplacements."""

from cal_iut.api.validation import _teacher_free_at, validate_move
from cal_iut.calendar.academic import build_default_calendar_2026_2027, department_week_number
from cal_iut.models.entities import TeacherAvailability, TeacherWeekParityRule
from cal_iut.solver.cpsat import PlacedSession


def test_validate_no_conflict() -> None:
    timetable = [
        PlacedSession("a", 0, 0, 0, "WR101", ["g1"], ["T1"]),
        PlacedSession("b", 0, 0, 1, "WR102", ["g2"], ["T2"]),
    ]
    result = validate_move("a", 0, 0, 2, timetable, ["g1"], ["T1"])
    assert result.valid


def test_validate_group_conflict() -> None:
    timetable = [
        PlacedSession("a", 0, 0, 0, "WR101", ["g1"], ["T1"]),
        PlacedSession("b", 0, 0, 1, "WR102", ["g1"], ["T2"]),
    ]
    result = validate_move("b", 0, 0, 0, timetable, ["g1"], ["T2"])
    assert not result.valid
    assert len(result.hard_conflicts) > 0


def test_validate_teacher_conflict() -> None:
    timetable = [
        PlacedSession("a", 0, 0, 0, "WR101", ["g1"], ["T1"]),
    ]
    result = validate_move("b", 0, 0, 0, timetable, ["g2"], ["T1"])
    assert not result.valid


# --------------------------------------------------------------------------
# _teacher_free_at (retour utilisateur 11/08/2026 : "vérifie bien toutes les
# contraintes avant que ça s'effectue" — les 4 mécanismes du solveur, pas
# seulement forbidden_slots/forbidden_dates).
# --------------------------------------------------------------------------


def test_teacher_free_at_respects_hard_whitelist() -> None:
    """Un enseignant en liste blanche (ex. VBU) n'est PAS libre hors de ses
    créneaux déclarés, même sans indisponibilité explicite ce jour-là."""
    avail = [TeacherAvailability(teacher_code="VBU", allowed_slots=[(0, 0), (0, 1)])]
    assert _teacher_free_at(["VBU"], 0, 0, 0, None, avail) is True
    assert _teacher_free_at(["VBU"], 0, 2, 0, None, avail) is False  # mercredi hors liste blanche


def test_teacher_free_at_respects_week_parity() -> None:
    calendar = build_default_calendar_2026_2027()
    rule = TeacherWeekParityRule(parity="paire", day=2, slots=[0, 1, 2, 3, 4, 5])
    avail = [TeacherAvailability(teacher_code="TCA", week_parity_rules=[rule])]

    for rel in range(6):
        monday = calendar.teaching_mondays[rel]
        even = department_week_number(monday) % 2 == 0
        free = _teacher_free_at(["TCA"], rel, 2, 0, None, avail, calendar, 0)
        assert free is (not even)  # mercredi bloqué UNIQUEMENT les semaines paires
