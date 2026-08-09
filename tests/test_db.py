"""Tests persistance SQLite."""

import uuid
from pathlib import Path

import pytest

from cal_iut.db import session as db_session
from cal_iut.db.repository import PlanningRepository
from cal_iut.db.session import get_db, init_db


@pytest.fixture()
def repo() -> PlanningRepository:
    db_path = Path(__file__).resolve().parents[1] / "data" / f"test_{uuid.uuid4().hex}.db"
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(db_path)
    db = get_db(db_path)
    r = PlanningRepository(db)
    yield r
    db.close()
    if db_session._engine:
        db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None
    db_path.unlink(missing_ok=True)


def test_save_run_and_diff(repo: PlanningRepository) -> None:
    run = repo.save_run(
        parcours="BUT1",
        semestre="S1",
        status="OPTIMAL",
        objective_value=0,
        gap_penalty=0,
        weeks=16,
        solver_placements=[
            {"session_id": "s1", "week": 0, "day": 0, "slot": 0, "course_code": "WR108", "room_id": None},
        ],
        current_placements=[
            {"session_id": "s1", "week": 0, "day": 0, "slot": 1, "course_code": "WR108", "room_id": "s101", "locked": False},
        ],
    )

    diff = repo.get_diff(run.id)
    assert len(diff) == 1
    assert diff[0].changed
    assert diff[0].solver_slot == 0
    assert diff[0].current_slot == 1


def test_save_correction_and_weights(repo: PlanningRepository) -> None:
    run = repo.save_run(
        parcours="BUT1",
        semestre="S1",
        status="OPTIMAL",
        objective_value=0,
        gap_penalty=0,
        weeks=16,
        solver_placements=[],
        current_placements=[],
    )

    repo.save_correction(
        run.id,
        "s1",
        {"week": 0, "day": 0, "slot": 0},
        {"week": 0, "day": 0, "slot": 3},
        False,
        False,
        "WR108",
        ["ALO"],
    )

    weights = repo.weights_as_dict()
    assert weights["gap_penalty"] == 100

    merged = {**weights, "gap_penalty": 120}
    repo.save_weights(merged, "test")
    assert repo.weights_as_dict()["gap_penalty"] == 120
