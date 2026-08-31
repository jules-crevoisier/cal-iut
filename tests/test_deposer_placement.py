"""POST /placements/{session_id}/deposer — déposer sans supprimer la séance.

La séance reste dans le catalogue et rejoint « À placer ». Idempotent.
Ce n'est PAS `DELETE /placements/{id}` (réservé au forçage pédagogique).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10


def _seance(sid: str, groupe: str = "but1-td-ab", prof: str = "MRI") -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code="WR101",
        course_name="Culture numérique",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=[groupe],
        teacher_codes=[prof],
        duration_slots=1,
    )


def _place(s: SessionToPlace, day: int, slot: int, week: int = SEMAINE) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id,
        week=week,
        day=day,
        slot=slot,
        course_code=s.course_code,
        group_ids=list(s.group_ids),
        teacher_codes=list(s.teacher_codes),
    )


@pytest.fixture
def monter():
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "teacher_duos", "corrections",
            "courses", "config_dir",
        )
    }

    def _monter(paires):
        etat.sessions = [s for s, _ in paires]
        etat.sessions_by_id = {s.id: s for s, _ in paires}
        etat.timetable = [p for _, p in paires if p is not None]
        etat.groups = GROUPES
        etat.rooms = []
        etat.calendar = build_default_calendar_2026_2027()
        etat.current_run_id = None
        etat.teacher_availability = []
        etat.teacher_duos = []
        etat.corrections = []
        etat.courses = []
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        client.post("/auth/login", json={"password": "test-password"})
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_should_unplace_and_keep_session_when_deposer_is_posted(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.post("/placements/a/deposer")
    assert reponse.status_code == 200, reponse.text
    etat = get_state()
    assert "a" in etat.sessions_by_id
    assert any(s.id == "a" for s in etat.sessions)
    assert not any(p.session_id == "a" for p in etat.timetable)
    manquantes = client.get("/placements/manquantes").json()["manquantes"]
    assert "a" in [m["session_id"] for m in manquantes]


def test_should_stay_unplaced_when_deposer_is_posted_twice(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    premiere = client.post("/placements/a/deposer")
    seconde = client.post("/placements/a/deposer")
    assert premiere.status_code == 200, premiere.text
    assert seconde.status_code == 200, seconde.text
    etat = get_state()
    assert "a" in etat.sessions_by_id
    assert not any(p.session_id == "a" for p in etat.timetable)


def test_should_not_unplace_via_delete_when_placement_is_not_a_forced_pending(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.delete("/placements/a")
    assert reponse.status_code == 400
    etat = get_state()
    assert any(p.session_id == "a" for p in etat.timetable)
    assert "a" in etat.sessions_by_id


def test_should_return_401_when_deposer_is_called_without_login():
    client = TestClient(app)
    reponse = client.post("/placements/a/deposer")
    assert reponse.status_code == 401
