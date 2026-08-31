"""Outils MCP inspect / plan / apply — fixtures synthétiques, pas de solveur.

`plan` ne persiste rien. `apply` n'écrit que si confirm=true, ops non vide,
plan_id concordant s'il est fourni, et aucun item bloqué (jamais de force).

Cas métier : CMs JHU uniquement déposés ; WRA507C en 3h (2 créneaux) à 14h
(slot 3).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, SessionType, Teacher, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10
SLOT_14H = 3  # 14h00–15h30 ; duration_slots=2 couvre 14h–17h


def _outils():
    """Les outils n'existent pas encore : l'échec doit être un FAIL de test, pas une erreur de collecte."""
    import importlib

    for nom in ("cal_iut.mcp.tools", "cal_iut.mcp.ops"):
        try:
            return importlib.import_module(nom)
        except ImportError:
            continue
    pytest.fail("module cal_iut.mcp.tools (ou cal_iut.mcp.ops) absent — inspect/plan/apply non implémentés")


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


def _ids_planning() -> list[str]:
    return sorted(p.session_id for p in get_state().timetable)


def _appeler_apply(**kwargs):
    """apply peut refuser en levant ou en rendant ok=False — l'écriture est le contrat."""
    try:
        return apply(**kwargs)
    except Exception as exc:  # noqa: BLE001 — l'API publique n'existe pas encore
        return exc


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
        etat.courses = courses if courses is not None else []
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        client.post("/auth/login", json={"password": "test-password"})
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _etat_jhu(monter):
    jhu = Teacher(code="JHU", nom="Huet", prenom="Julie")
    cm1 = _seance("cm-wr303d", code="WR303D", prof="JHU", type_seance=SessionType.CM)
    td1 = _seance("td-wr303d", code="WR303D", prof="JHU", type_seance=SessionType.TD)
    cm2 = _seance("cm-wra303m", code="WRA303M", prof="JHU", type_seance=SessionType.CM)
    tp3 = _seance("tp-wra309m", code="WRA309M", prof="JHU", type_seance=SessionType.TP)
    monter(
        [
            (cm1, _place(cm1, 0, 0)),
            (td1, _place(td1, 1, 0)),
            (cm2, _place(cm2, 2, 0)),
            (tp3, _place(tp3, 3, 0)),
        ],
        courses=[
            _cours("WR303D", jhu),
            _cours("WRA303M", jhu),
            _cours("WRA309M", jhu),
        ],
    )
    return cm1, td1, cm2, tp3


def _etat_ara(monter):
    ara = Teacher(code="ARA", nom="Museum", prenom="A")
    seance = _seance(
        "wra507c-cm",
        code="WRA507C",
        prof="ARA",
        type_seance=SessionType.CM,
        duree=1,
    )
    monter(
        [(seance, _place(seance, 2, 0))],
        courses=[_cours("WRA507C", ara)],
    )
    return seance


def test_should_list_jhu_sessions_when_inspect_filters_by_teacher(monter):
    _etat_jhu(monter)
    resultat = inspect(teacher_code="JHU")
    ids = {item["session_id"] for item in resultat["sessions"]}
    assert ids == {"cm-wr303d", "td-wr303d", "cm-wra303m", "tp-wra309m"}


def test_should_not_write_when_plan_runs_on_jhu_cms(monter):
    _etat_jhu(monter)
    avant = _ids_planning()
    resultat = plan(
        teacher_code="JHU",
        course_codes=["WR303D", "WRA303M", "WRA309M"],
        session_type="CM",
        op="unplace",
    )
    assert resultat["plan_id"]
    assert {item["session_id"] for item in resultat["items"] if item.get("op") == "unplace"} <= {
        "cm-wr303d",
        "cm-wra303m",
    }
    assert _ids_planning() == avant


def test_should_write_nothing_when_apply_confirm_is_false(monter):
    _etat_jhu(monter)
    avant = _ids_planning()
    ops = [{"op": "unplace", "session_id": "cm-wr303d", "status": "ok"}]
    retour = _appeler_apply(confirm=False, ops=ops)
    assert _ids_planning() == avant
    if isinstance(retour, dict):
        assert retour.get("ok") is not True


def test_should_write_nothing_when_apply_ops_are_empty(monter):
    _etat_jhu(monter)
    avant = _ids_planning()
    retour = _appeler_apply(confirm=True, ops=[])
    assert _ids_planning() == avant
    if isinstance(retour, dict):
        assert retour.get("ok") is not True


def test_should_write_nothing_when_apply_plan_id_does_not_match(monter):
    _etat_jhu(monter)
    propose = plan(
        teacher_code="JHU",
        course_codes=["WR303D", "WRA303M", "WRA309M"],
        session_type="CM",
        op="unplace",
    )
    avant = _ids_planning()
    retour = _appeler_apply(
        confirm=True,
        ops=propose["items"],
        plan_id="plan-id-qui-ne-correspond-pas",
    )
    assert _ids_planning() == avant
    if isinstance(retour, dict):
        assert retour.get("ok") is not True


def test_should_write_nothing_when_apply_contains_a_blocked_item(monter):
    _etat_jhu(monter)
    avant = _ids_planning()
    ops = [
        {"op": "unplace", "session_id": "cm-wr303d", "status": "ok"},
        {
            "op": "unplace",
            "session_id": "td-wr303d",
            "status": "blocked",
            "reason": "règle dure — never force",
        },
    ]
    retour = _appeler_apply(confirm=True, ops=ops)
    assert _ids_planning() == avant
    if isinstance(retour, dict):
        assert retour.get("ok") is not True
        assert retour.get("forced") is not True


def test_should_unplace_only_cms_when_jhu_plan_is_applied(monter):
    _etat_jhu(monter)
    propose = plan(
        teacher_code="JHU",
        course_codes=["WR303D", "WRA303M", "WRA309M"],
        session_type="CM",
        op="unplace",
    )
    assert {item["session_id"] for item in propose["items"]} == {"cm-wr303d", "cm-wra303m"}
    assert all(item.get("status") != "blocked" for item in propose["items"])
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    restants = set(_ids_planning())
    assert "cm-wr303d" not in restants
    assert "cm-wra303m" not in restants
    assert "td-wr303d" in restants
    assert "tp-wra309m" in restants
    etat = get_state()
    assert "cm-wr303d" in etat.sessions_by_id
    assert "cm-wra303m" in etat.sessions_by_id


def test_should_keep_session_at_1h30_when_ara_plan_runs_without_apply(monter):
    seance = _etat_ara(monter)
    propose = plan(course_code="WRA507C", duration_slots=2, slot=SLOT_14H)
    assert propose["plan_id"]
    ok_items = [item for item in propose["items"] if item.get("status") == "ok"]
    assert ok_items
    assert all(item.get("duration_slots") == 2 for item in ok_items)
    assert all(item.get("slot") == SLOT_14H for item in ok_items)
    etat = get_state()
    assert etat.sessions_by_id[seance.id].duration_slots == 1
    pose = next(p for p in etat.timetable if p.session_id == seance.id)
    assert pose.slot == 0


def test_should_place_3h_at_slot_14h_when_ara_plan_is_applied(monter):
    seance = _etat_ara(monter)
    propose = plan(course_code="WRA507C", duration_slots=2, slot=SLOT_14H)
    apply(confirm=True, ops=propose["items"], plan_id=propose["plan_id"])
    etat = get_state()
    assert etat.sessions_by_id[seance.id].duration_slots == 2
    pose = next(p for p in etat.timetable if p.session_id == seance.id)
    assert pose.slot == SLOT_14H
