"""Tests validation déplacements."""

from cal_iut.api.validation import validate_move
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
