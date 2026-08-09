"""Tests feedback et export."""

from cal_iut.db.models import Correction
from cal_iut.export.formatter import build_export_rows, to_csv
from cal_iut.feedback.weights import analyze_corrections, apply_learned_weights
from cal_iut.solver.rooms import PlacedSessionWithRoom


def test_analyze_afternoon_pattern() -> None:
    corrections = [
        Correction(
            id=1,
            run_id=1,
            session_id="s1",
            proposed_week=0,
            proposed_day=0,
            proposed_slot=0,
            manual_week=0,
            manual_day=0,
            manual_slot=3,
            locked=False,
            forced=False,
            course_code="WR108",
            teacher_codes="ALO",
        ),
        Correction(
            id=2,
            run_id=1,
            session_id="s2",
            proposed_week=0,
            proposed_day=1,
            proposed_slot=1,
            manual_week=0,
            manual_day=1,
            manual_slot=4,
            locked=False,
            forced=False,
            course_code="WR109",
            teacher_codes="ALO",
        ),
        Correction(
            id=3,
            run_id=1,
            session_id="s3",
            proposed_week=0,
            proposed_day=2,
            proposed_slot=0,
            manual_week=0,
            manual_day=2,
            manual_slot=3,
            locked=False,
            forced=False,
            course_code="WS103",
            teacher_codes="JUL",
        ),
    ]
    analysis = analyze_corrections(corrections)
    assert analysis["total_corrections"] == 3
    assert "afternoon_preference" in analysis["suggestions"]


def test_export_csv() -> None:
    class FakeSession:
        course_name = "Production graphique"
        session_type = type("T", (), {"value": "TP"})()
        semestre = "S1"
        parcours = "BUT1"
        locked = False
        is_eval = False

    p = PlacedSessionWithRoom(
        session_id="s1",
        week=0,
        day=0,
        slot=0,
        course_code="WR108",
        group_ids=["g1"],
        teacher_codes=["ALO"],
        room_id="s101",
        room_label="Salle 101",
    )
    rows = build_export_rows([p], {"s1": FakeSession()})
    csv = to_csv(rows)
    assert "WR108" in csv
    assert "Production graphique" in csv
