"""Helpers de test — sync Celcat (onglet + file d'attente + job nuit).

Pas de production : isolation des JSON, client admin, planning minimal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
SEMAINE = 12
V1_JOURNAL = Path(__file__).resolve().parent / "fixtures" / "celcat_sync_v1.json"


def seance(
    sid: str,
    groupe: str = "but1-td-ab",
    prof: str = "MRI",
    code: str = "WR101",
) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code=code,
        course_name="Cours",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=[groupe],
        teacher_codes=[prof],
        duration_slots=1,
    )


def place(
    s: SessionToPlace,
    day: int = 0,
    slot: int = 0,
    week: int = SEMAINE,
    room_id: str = "h101",
    room_label: str = "H.101",
) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id,
        week=week,
        day=day,
        slot=slot,
        course_code=s.course_code,
        group_ids=list(s.group_ids),
        teacher_codes=list(s.teacher_codes),
        room_id=room_id,
        room_label=room_label,
    )


def cours(code: str = "WR101") -> Course:
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


def monter_planning(paires: list, courses: list[Course] | None = None) -> TestClient:
    """État applicatif minimal + client admin (écritures /celcat + placements)."""
    etat = get_state()
    etat.sessions = [s for s, _ in paires]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [p for _, p in paires if p is not None]
    etat.groups = GROUPES
    etat.rooms = [
        Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h103", label="H.103", capacity=30, room_type=RoomType.STANDARD),
    ]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = courses if courses is not None else [cours()]
    etat.config_dir = ROOT / "data" / "config"
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def snapshot_etat(etat: Any) -> dict[str, Any]:
    return {
        c: getattr(etat, c)
        for c in (
            "sessions",
            "sessions_by_id",
            "timetable",
            "groups",
            "rooms",
            "calendar",
            "current_run_id",
            "teacher_availability",
            "teacher_duos",
            "corrections",
            "courses",
            "config_dir",
        )
    }


def restaurer_etat(etat: Any, ancien: dict[str, Any]) -> None:
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def jobs_en_attente() -> list[dict[str, Any]]:
    from cal_iut.celcat.file_attente import lister

    return list(lister())


def vider_file() -> None:
    from cal_iut.celcat.file_attente import vider

    vider()


def charger_etat() -> dict[str, Any]:
    from cal_iut.celcat.etat import charger

    return charger()


def activer_saisie(client: TestClient) -> None:
    reponse = client.patch("/celcat/saisie", json={"active": True})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["saisie_active"] is True


def extraire_extras(corps: object) -> list[dict[str, Any]]:
    if isinstance(corps, list):
        return [x for x in corps if isinstance(x, dict)]
    if isinstance(corps, dict):
        brut = corps.get("extras")
        if isinstance(brut, list):
            return [x for x in brut if isinstance(x, dict)]
    return []


def extraire_logs(corps: object) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(corps, dict):
        items = corps.get("items")
        cursor = corps.get("cursor")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)], cursor if isinstance(cursor, str) else None
    if isinstance(corps, list):
        return [x for x in corps if isinstance(x, dict)], None
    return [], None
