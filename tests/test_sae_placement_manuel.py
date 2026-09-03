"""SAE manuelle : inventaire + sanctuarisation (retour 03/09/2026)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import _hard_constraint_context, app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom
from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")


def _seance(sid: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code="WR101",
        course_name="Culture numérique",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=["but1-td-ab"],
        teacher_codes=["MRI"],
        duration_slots=1,
    )


def _place(session: SessionToPlace, week: int, day: int, slot: int) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=session.id,
        week=week,
        day=day,
        slot=slot,
        course_code=session.course_code,
        group_ids=list(session.group_ids),
        teacher_codes=list(session.teacher_codes),
    )


@pytest.fixture
def client(db_isole):
    etat = get_state()
    ancien = {
        "sessions": etat.sessions,
        "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable,
        "groups": etat.groups,
        "rooms": etat.rooms,
        "calendar": etat.calendar,
        "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability,
        "teacher_duos": etat.teacher_duos,
        "corrections": etat.corrections,
        "courses": etat.courses,
        "config_dir": etat.config_dir,
    }
    placee = _seance("placee")
    manquante = _seance("manquante")
    etat.sessions = [placee, manquante]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [_place(placee, 10, 0, 0)]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.config_dir = ROOT / "data" / "config"
    http = TestClient(app)
    creer_compte_actif_et_connecter(http)
    yield http
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_should_list_unplaced_ws_sae_in_manquantes(client) -> None:
    """Les SAE (WS*) doivent pouvoir être placées à la main dans leurs
    fenêtres — les exclure de « À placer » rendait l'exemption serveur
    inutilisable depuis l'UI (retour Kyllian 03/09/2026)."""
    etat = get_state()
    sae = SessionToPlace(
        id="sae-a-placer",
        course_code="WSA310M",
        course_name="SAE",
        semestre="S3",
        parcours="BUT2-DEV-FI",
        annee="BUT2",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=["but1-td-ab"],
        teacher_codes=["MRI"],
    )
    etat.sessions = list(etat.sessions) + [sae]
    etat.sessions_by_id[sae.id] = sae

    ids = {m["session_id"] for m in client.get("/placements/manquantes").json()["manquantes"]}
    assert "sae-a-placer" in ids


def test_should_skip_sae_day_block_for_ws_but_not_for_wr(monkeypatch, client) -> None:
    etat = get_state()
    wr = next(s for s in etat.sessions if s.id == "manquante")
    ws = SessionToPlace(
        id="ws-sae",
        course_code="WS101",
        course_name="SAE",
        semestre=wr.semestre,
        parcours=wr.parcours,
        annee=wr.annee,
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=list(wr.group_ids),
        teacher_codes=list(wr.teacher_codes),
    )
    etat.sessions_by_id[ws.id] = ws

    jour_sae = {(0, 0)}

    monkeypatch.setattr(
        "cal_iut.ingestion.planning_loader.load_mmi_planning",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "cal_iut.ingestion.planning_loader.planning_event_blocked_slots_by_parcours",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "cal_iut.ingestion.planning_loader.sae_windows_as_week_days",
        lambda *_a, **_k: {"WS101": jour_sae},
    )
    monkeypatch.setattr(
        "cal_iut.ingestion.planning_loader.sae_group_labels_by_course",
        lambda *_a, **_k: {"WS101": set()},
    )
    monkeypatch.setattr(
        "cal_iut.solver.constraints.sae_blocked_days_by_parcours",
        lambda *_a, **_k: {wr.parcours: jour_sae},
    )
    monkeypatch.setattr(
        "cal_iut.solver.constraints.sae_blocked_days_by_group",
        lambda *_a, **_k: {},
    )

    blocked_wr, _, _ = _hard_constraint_context(etat, wr)
    blocked_ws, _, _ = _hard_constraint_context(etat, ws)
    assert (0, 0, 0) in blocked_wr
    assert (0, 0, 0) not in blocked_ws


def test_should_return_blocking_and_forceable_together_on_validate(client, monkeypatch) -> None:
    """Toutes les contraintes visibles d'un coup, pas seulement le premier
    verrou institutionnel (brief polish 03/09/2026)."""
    monkeypatch.setattr(
        "cal_iut.api.main._conflits_deplacement",
        lambda *_a, **_k: (
            ["Jour férié (01/01/2026) : l'IUT est fermé."],
            ["Enseignant indisponible à ce créneau (MRI)"],
        ),
    )
    reponse = client.post(
        "/placements/placee/validate",
        json={"week": 0, "day": 0, "slot": 1},
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["valid"] is False
    assert corps["blocking_conflicts"]
    assert any("indisponible" in m.lower() for m in corps["hard_conflicts"])
