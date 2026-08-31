"""MCP inspect + catalogue Promo, plan/apply (place/move/swap/salle/patch/custom),
journal, force seulement après plan forceable. Fixtures synthétiques.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, Room, RoomType, SessionType, Teacher, TeacherAvailability, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10
SALLE_A = "h101"
SALLE_B = "h104"


def _outils():
    import importlib

    for nom in ("cal_iut.mcp.tools", "cal_iut.mcp.ops"):
        try:
            return importlib.import_module(nom)
        except ImportError:
            continue
    pytest.fail("module cal_iut.mcp.tools (ou cal_iut.mcp.ops) absent")


def inspect(*args, **kwargs):
    return _outils().inspect(*args, **kwargs)


def plan(*args, **kwargs):
    return _outils().plan(*args, **kwargs)


def apply(*args, **kwargs):
    return _outils().apply(*args, **kwargs)


def _seance(
    sid: str,
    *,
    code: str,
    prof: str,
    type_seance: SessionType = SessionType.CM,
    groupe: str = "but1-td-ab",
    duree: int = 1,
) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code=code,
        course_name=code,
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=type_seance,
        sequence_order=1,
        group_ids=[groupe],
        teacher_codes=[prof],
        duration_slots=duree,
    )


def _place(s: SessionToPlace, day: int, slot: int, week: int = SEMAINE, room_id: str | None = None) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id,
        week=week,
        day=day,
        slot=slot,
        course_code=s.course_code,
        group_ids=list(s.group_ids),
        teacher_codes=list(s.teacher_codes),
        room_id=room_id,
        room_label=room_id.upper() if room_id else None,
    )


def _cours(code: str, prof: Teacher) -> Course:
    return Course(
        code=code,
        name=code,
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        lead=prof,
        profs=[TeacherBlock(teacher=prof, block="1", td=1, nbGpTd=1, nbGpTp=1)],
        volumes={"cm": 1, "td": 1, "tp": 0},
        groupes_td=1,
        groupes_tp=1,
        progression_defined=False,
        seance_sequence=[],
        ordonnancement=[],
    )


def _salles() -> list[Room]:
    return [
        Room(id=SALLE_A, label="H.101", capacity=30, room_type=RoomType.STANDARD),
        Room(id=SALLE_B, label="H.104", capacity=30, room_type=RoomType.STANDARD),
    ]


def _ids_planning() -> list[str]:
    return sorted(p.session_id for p in get_state().timetable)


def _placement(sid: str) -> PlacedSessionWithRoom:
    return next(p for p in get_state().timetable if p.session_id == sid)


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

    def _monter(paires, courses=None, rooms=None, availability=None):
        etat.sessions = [s for s, _ in paires]
        etat.sessions_by_id = {s.id: s for s, _ in paires}
        etat.timetable = [p for _, p in paires if p is not None]
        etat.groups = GROUPES
        etat.rooms = rooms if rooms is not None else _salles()
        etat.calendar = build_default_calendar_2026_2027()
        etat.current_run_id = None
        etat.teacher_availability = availability if availability is not None else []
        etat.teacher_duos = []
        etat.corrections = []
        etat.courses = courses if courses is not None else []
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        client.post("/auth/login", json={"password": "test-password"})
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _etat_ara(monter, *, placee: bool = True, room_id: str = SALLE_A):
    ara = Teacher(code="ARA", nom="Museum", prenom="A")
    seance = _seance("wra507c-cm", code="WRA507C", prof="ARA", type_seance=SessionType.CM)
    pose = _place(seance, 2, 0, room_id=room_id) if placee else None
    monter(
        [(seance, pose)],
        courses=[_cours("WRA507C", ara)],
    )
    return seance


def _etat_deux_cm(monter):
    jhu = Teacher(code="JHU", nom="Huet", prenom="Julie")
    a = _seance("cm-a", code="WR303D", prof="JHU", type_seance=SessionType.CM)
    b = _seance("cm-b", code="WRA303M", prof="JHU", type_seance=SessionType.CM, groupe="but1-td-cd")
    monter(
        [(a, _place(a, 0, 0, room_id=SALLE_A)), (b, _place(b, 2, 0, room_id=SALLE_B))],
        courses=[_cours("WR303D", jhu), _cours("WRA303M", jhu)],
    )
    return a, b


def test_should_return_compact_index_when_inspect_has_no_filter(monter):
    _etat_ara(monter)
    resultat = inspect()
    assert not resultat.get("sessions")
    assert resultat["index"]["n_sessions"] == 1
    assert "WRA507C" in resultat["index"]["course_codes"]
    assert "ARA" in resultat["index"]["teacher_codes"]


def test_should_include_catalog_and_slots_when_inspect_filters_wra507c(monter):
    seance = _etat_ara(monter)
    resultat = inspect(course_code="WRA507C")
    ids = {item["session_id"] for item in resultat["sessions"]}
    assert ids == {seance.id}
    item = resultat["sessions"][0]
    assert item["week"] == SEMAINE
    assert item["day"] == 2
    assert item["slot"] == 0
    assert item["room_id"] == SALLE_A
    assert "ARA" in item["teacher_codes"]
    catalogue = resultat["catalog"]
    assert any("Semaine" in (w if isinstance(w, str) else w.get("label", "")) for w in catalogue["weeks"])
    assert {r["id"] for r in catalogue["rooms"]} >= {SALLE_A, SALLE_B}
    assert any(t["code"] == "ARA" for t in catalogue["teachers"])


def test_should_list_unplaced_in_catalog_when_inspect_filters_course(monter):
    seance = _etat_ara(monter, placee=False)
    resultat = inspect(course_code="WRA507C")
    assert resultat["sessions"][0]["placed"] is False
    assert seance.id in {u["session_id"] if isinstance(u, dict) else u for u in resultat["catalog"]["unplaced"]}


def test_should_place_unplaced_session_when_plan_is_applied(monter):
    seance = _etat_ara(monter, placee=False)
    propose = plan(ops=[{
        "op": "place",
        "session_id": seance.id,
        "week": SEMAINE,
        "day": 0,
        "slot": 5,
    }])
    assert propose["items"][0]["status"] == "ok"
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    pose = _placement(seance.id)
    assert (pose.week, pose.day, pose.slot) == (SEMAINE, 0, 5)


def test_should_move_across_weeks_when_plan_is_applied(monter):
    seance = _etat_ara(monter)
    cible = SEMAINE - 2
    propose = plan(ops=[{
        "op": "move",
        "session_id": seance.id,
        "week": cible,
        "day": 1,
        "slot": 2,
    }])
    assert propose["items"][0]["status"] == "ok"
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    pose = _placement(seance.id)
    assert (pose.week, pose.day, pose.slot) == (cible, 1, 2)


def test_should_swap_two_sessions_when_plan_is_applied(monter):
    a, b = _etat_deux_cm(monter)
    avant_a = ( _placement(a.id).week, _placement(a.id).day, _placement(a.id).slot )
    avant_b = ( _placement(b.id).week, _placement(b.id).day, _placement(b.id).slot )
    propose = plan(ops=[{"op": "swap", "session_id": a.id, "session_b": b.id}])
    assert propose["items"][0]["status"] == "ok"
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    assert (_placement(a.id).week, _placement(a.id).day, _placement(a.id).slot) == avant_b
    assert (_placement(b.id).week, _placement(b.id).day, _placement(b.id).slot) == avant_a


def test_should_change_room_when_salle_plan_is_applied(monter):
    seance = _etat_ara(monter, room_id=SALLE_A)
    propose = plan(ops=[{"op": "salle", "session_id": seance.id, "room_id": SALLE_B}])
    assert propose["items"][0]["status"] == "ok"
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    assert _placement(seance.id).room_id == SALLE_B


def test_should_patch_teachers_type_duration_eval_when_seance_plan_is_applied(monter):
    seance = _etat_ara(monter)
    propose = plan(ops=[{
        "op": "seance",
        "session_id": seance.id,
        "teacher_codes": ["ARA"],
        "session_type": "CM",
        "duration_slots": 2,
        "is_eval": True,
    }])
    assert propose["items"][0]["status"] == "ok"
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    etat = get_state()
    maj = etat.sessions_by_id[seance.id]
    assert maj.duration_slots == 2
    assert maj.is_eval is True
    assert str(getattr(maj.session_type, "value", maj.session_type)) == "CM"


def test_should_create_custom_session_when_custom_create_plan_is_applied(monter):
    _etat_ara(monter)
    propose = plan(ops=[{
        "op": "custom_create",
        "course_code": "WRA507C",
        "session_type": "TD",
        "group_ids": ["but1-td-ab"],
        "teacher_codes": ["ARA"],
        "week": SEMAINE,
        "day": 0,
        "slot": 5,
        "duration_slots": 1,
    }])
    assert propose["items"][0]["status"] == "ok"
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    customs = [s for s in get_state().sessions if s.metadata.get("custom_session")]
    assert len(customs) == 1
    assert customs[0].course_code == "WRA507C"
    assert customs[0].id in set(_ids_planning())


def test_should_append_journal_when_apply_succeeds(monter):
    seance = _etat_ara(monter, placee=False)
    propose = plan(ops=[{
        "op": "place",
        "session_id": seance.id,
        "week": SEMAINE,
        "day": 0,
        "slot": 5,
    }])
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    second = inspect(course_code="WRA507C")
    assert second["journal"]
    dernier = second["journal"][-1]
    texte = str(dernier).lower()
    assert "place" in texte or any(op.get("op") == "place" for op in dernier.get("ops", []))


def test_should_mark_forceable_when_plan_hits_resource_conflict(monter):
    a, b = _etat_deux_cm(monter)
    cible = _placement(a.id)
    propose = plan(ops=[{
        "op": "move",
        "session_id": b.id,
        "week": cible.week,
        "day": cible.day,
        "slot": cible.slot,
    }])
    item = propose["items"][0]
    assert item["status"] != "blocked"
    assert item.get("forceable") is True


def test_should_write_nothing_when_apply_force_without_confirm_on_forceable(monter):
    a, b = _etat_deux_cm(monter)
    cible = _placement(a.id)
    avant = (_placement(b.id).week, _placement(b.id).day, _placement(b.id).slot)
    propose = plan(ops=[{
        "op": "move",
        "session_id": b.id,
        "week": cible.week,
        "day": cible.day,
        "slot": cible.slot,
    }])
    item = dict(propose["items"][0])
    item["force"] = True
    retour = apply(confirm=False, ops=[item], plan_id=propose["plan_id"])
    if isinstance(retour, dict):
        assert retour.get("ok") is not True
    assert (_placement(b.id).week, _placement(b.id).day, _placement(b.id).slot) == avant


def test_should_move_when_apply_confirms_forceable_conflict(monter):
    a, b = _etat_deux_cm(monter)
    cible = _placement(a.id)
    propose = plan(ops=[{
        "op": "move",
        "session_id": b.id,
        "week": cible.week,
        "day": cible.day,
        "slot": cible.slot,
    }])
    item = dict(propose["items"][0])
    assert item.get("forceable") is True
    item["force"] = True
    apply(confirm=True, ops=[item], plan_id=None)
    pose = _placement(b.id)
    assert (pose.week, pose.day, pose.slot) == (cible.week, cible.day, cible.slot)


def test_should_block_and_never_apply_when_declared_indispo(monter):
    ara = Teacher(code="ARA", nom="Museum", prenom="A")
    seance = _seance("wra507c-cm", code="WRA507C", prof="ARA")
    monter(
        [(seance, _place(seance, 2, 0, room_id=SALLE_A))],
        courses=[_cours("WRA507C", ara)],
        availability=[TeacherAvailability(teacher_code="ARA", forbidden_slots=[(0, 5)])],
    )
    propose = plan(ops=[{
        "op": "move",
        "session_id": seance.id,
        "week": SEMAINE,
        "day": 0,
        "slot": 5,
        "force": True,
    }])
    item = propose["items"][0]
    assert item["status"] == "blocked"
    avant = (_placement(seance.id).week, _placement(seance.id).day, _placement(seance.id).slot)
    item["force"] = True
    retour = apply(confirm=True, ops=[item], plan_id=propose["plan_id"])
    if isinstance(retour, dict):
        assert retour.get("ok") is not True
        assert retour.get("forced") is not True
    assert (_placement(seance.id).week, _placement(seance.id).day, _placement(seance.id).slot) == avant


def test_should_list_ops_on_plan_tool_when_mcp_tools_listed(monkeypatch):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", "test-mcp-token-not-for-prod")
    client = TestClient(app)
    reponse = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer test-mcp-token-not-for-prod",
        },
    )
    assert reponse.status_code == 200
    outils = reponse.json()["result"]["tools"]
    noms = {t["name"] for t in outils}
    assert noms == {"inspect", "plan", "apply"}
    plan_tool = next(t for t in outils if t["name"] == "plan")
    assert "ops" in plan_tool["inputSchema"]["properties"]


def test_should_document_tools_journal_and_force_when_skill_file_exists():
    chemin = ROOT / ".cursor" / "skills" / "cal-iut-edt" / "SKILL.md"
    assert chemin.is_file()
    texte = chemin.read_text(encoding="utf-8").lower()
    assert "inspect" in texte
    assert "plan" in texte
    assert "apply" in texte
    assert "mcp_journal" in texte
    assert "forceable" in texte or "blocking" in texte
    assert "semaine" in texte
