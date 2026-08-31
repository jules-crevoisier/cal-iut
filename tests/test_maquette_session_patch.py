"""PATCH /placements/{session_id}/seance — overlay sur une séance de maquette.

Au moins un de teacher_codes | session_type | duration_slots (1 ou 2) |
week | day | slot | room_id | is_eval. Enseignant inconnu → 400.
duration_slots=3 → 400. Conflit dur sans force → 409, rien persisté. La
route personnalisées sur une maquette reste 404.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, Room, RoomType, SessionType, Teacher, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom
from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10


def _seance(
    sid: str,
    groupe: str = "but1-td-ab",
    prof: str = "MRI",
    duree: int = 1,
    code: str = "WR101",
    type_seance: SessionType = SessionType.TD,
) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code=code,
        course_name="Cours existant",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=type_seance,
        sequence_order=1,
        group_ids=[groupe],
        teacher_codes=[prof],
        duration_slots=duree,
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


def _cours(code: str = "WR101") -> Course:
    mri = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    jsa = Teacher(code="JSA", nom="Sanson", prenom="Jean")
    return Course(
        code=code,
        name="Cours existant",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        lead=mri,
        profs=[
            TeacherBlock(teacher=mri, block="1", td=17, nbGpTd=1, nbGpTp=1),
            TeacherBlock(teacher=jsa, block="1", td=0, nbGpTd=1, nbGpTp=1),
        ],
        volumes={"cm": 0, "td": 17, "tp": 0},
        groupes_td=1,
        groupes_tp=1,
        progression_defined=False,
        seance_sequence=[],
        ordonnancement=[],
    )


@pytest.fixture
def monter(db_isole):
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "teacher_duos", "corrections",
            "courses", "config_dir",
        )
    }

    def _monter(paires, courses=None):
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
        etat.courses = courses if courses is not None else [_cours()]
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        creer_compte_actif_et_connecter(client)
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_should_update_teacher_when_maquette_seance_is_patched(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/a/seance", json={"teacher_codes": ["JSA"]})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["teacher_codes"] == ["JSA"]
    assert get_state().sessions_by_id["a"].teacher_codes == ["JSA"]


def test_should_persist_overlay_when_maquette_session_is_patched(monter, tmp_path):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/a/seance", json={"teacher_codes": ["JSA"]})
    assert reponse.status_code == 200, reponse.text
    overlay = tmp_path / "session_overrides.json"
    assert overlay.is_file(), "l'overlay maquette doit être écrit sur disque"
    texte = overlay.read_text(encoding="utf-8")
    brut = json.loads(texte)
    assert "a" in texte
    assert "JSA" in texte
    assert brut != [] and brut != {}


def test_should_return_400_when_no_seance_field_is_provided(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/a/seance", json={})
    assert reponse.status_code == 400
    assert get_state().sessions_by_id["a"].teacher_codes == ["MRI"]


def test_should_return_400_when_teacher_code_is_unknown(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/a/seance", json={"teacher_codes": ["XXXX"]})
    assert reponse.status_code == 400
    assert get_state().sessions_by_id["a"].teacher_codes == ["MRI"]


def test_should_return_400_when_duration_slots_is_three(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/a/seance", json={"duration_slots": 3})
    assert reponse.status_code == 400
    assert get_state().sessions_by_id["a"].duration_slots == 1


def test_should_return_409_and_not_persist_when_hard_conflict_without_force(monter, tmp_path):
    a = _seance("a", duree=1)
    b = _seance("b", prof="AUTRE")
    client = monter([(a, _place(a, 2, 3)), (b, _place(b, 2, 4))])
    reponse = client.patch("/placements/a/seance", json={"duration_slots": 2, "force": False})
    assert reponse.status_code == 409, reponse.text
    assert get_state().sessions_by_id["a"].duration_slots == 1
    overlay = tmp_path / "session_overrides.json"
    if overlay.is_file():
        assert "duration_slots" not in overlay.read_text(encoding="utf-8") or '"duration_slots": 2' not in overlay.read_text(
            encoding="utf-8",
        )


def test_should_still_return_404_when_patching_personnalisees_on_a_maquette_row(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/personnalisees/a", json={"session_type": "CM"})
    assert reponse.status_code == 404
    assert get_state().sessions_by_id["a"].session_type == SessionType.TD


def test_should_return_structured_conflict_when_moving_out_of_current_week(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0, week=0))])
    reponse = client.patch("/placements/a/seance", json={"week": 1})
    assert reponse.status_code == 409, reponse.text
    detail = reponse.json()["detail"]
    assert isinstance(detail, dict)
    assert detail.get("hard_conflicts")
    assert "non modifiable" in detail["hard_conflicts"][0]
    assert get_state().timetable[0].week == 0
    forcee = client.patch("/placements/a/seance", json={"week": 1, "force": True})
    assert forcee.status_code == 200, forcee.text
    assert forcee.json()["week"] == 1


def test_should_move_week_when_maquette_seance_is_patched(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    # L'ordre pédagogique (`allowed_weeks`) refuse souvent la semaine
    # voisine sans `force` — le déplacement lui-même doit quand même passer.
    reponse = client.patch("/placements/a/seance", json={"week": SEMAINE + 1, "force": True})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["week"] == SEMAINE + 1
    assert get_state().timetable[0].week == SEMAINE + 1
    assert get_state().timetable[0].day == 0
    assert get_state().timetable[0].slot == 0


def test_should_set_eval_when_cm_is_patched(monter):
    a = _seance("a", type_seance=SessionType.CM)
    client = monter([(a, _place(a, 0, 0))])
    reponse = client.patch("/placements/a/seance", json={"is_eval": True})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["is_eval"] is True
    assert get_state().sessions_by_id["a"].is_eval is True


def test_should_change_room_when_maquette_seance_is_patched(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    get_state().rooms = [Room(id="h005", label="H.005", capacity=30, room_type=RoomType.STANDARD)]
    reponse = client.patch("/placements/a/seance", json={"room_id": "h005"})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "h005"
    assert get_state().timetable[0].room_id == "h005"
