"""Créer un évènement hors maquette (réunion, conférence...) affiché en
clair sur l'EDT — retour utilisateur 07/09/2026 : « il faudrait que l'on
créer un module WR000Réunion ou WRréunion ou Conférence, pour indiqué sur
cal-iut l'échange IA en clair sur l'emploi du temps des étudiants S1 ».

Contrairement à `POST /placements/personnalisees`
(`test_seances_personnalisees_2026_08_31.py`), CE système invente son
`course_code` depuis un libellé libre — jamais besoin d'une matière déjà
connue dans `state.courses`, puisqu'un évènement n'a ni progression, ni
volume horaire, ni contrainte d'ordonnancement.
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

from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10  # librement modifiable dans le calendrier 2026-2027


def _seance(sid, groupe="but1-promo") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Cours existant", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM, sequence_order=1,
        group_ids=[groupe], teacher_codes=[], duration_slots=1,
    )


def _place(s: SessionToPlace, day: int, slot: int, week: int = SEMAINE) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
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
        etat.courses = courses if courses is not None else []
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        creer_compte_actif_et_connecter(client)
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _corps_creation(**over):
    corps = {
        "libelle": "Conférence", "semestre": "S1",
        "group_ids": ["but1-promo"], "teacher_codes": [],
        "duration_slots": 2, "note": "Échange IA — retour étudiants S1",
        "week": SEMAINE, "day": 1, "slot": 1, "force": False,
    }
    corps.update(over)
    return corps


def test_creer_un_evenement_sur_un_creneau_libre_sans_matiere_connue(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])  # `state.courses` reste vide : aucune matière connue
    r = client.post("/placements/evenements", json=_corps_creation())
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["course_code"] == "CONFERENCE"
    assert corps["session_type"] == "CM"
    assert (corps["week"], corps["day"], corps["slot"]) == (SEMAINE, 1, 1)

    etat = get_state()
    seance = etat.sessions_by_id[corps["session_id"]]
    assert any(p.session_id == corps["session_id"] for p in etat.timetable)
    assert seance.course_name == "Conférence"
    assert seance.metadata.get("custom_session") is True
    assert seance.metadata.get("evenement") is True


def test_le_libelle_est_translitere_en_code_lisible(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/evenements", json=_corps_creation(libelle="Échange IA (S1)"))
    assert r.status_code == 200, r.text
    assert r.json()["course_code"] == "ECHANGE-IA-S1"


def test_refuse_un_groupe_inconnu(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/evenements", json=_corps_creation(group_ids=["groupe-fantome"]))
    assert r.status_code == 400


def test_un_conflit_de_creneau_ne_laisse_aucune_trace(monter):
    a = _seance("a")
    b = _seance("b")
    client = monter([(a, _place(a, 0, 0)), (b, _place(b, 1, 1))])
    avant = dict(get_state().sessions_by_id)
    r = client.post("/placements/evenements", json=_corps_creation(day=1, slot=1))
    assert r.status_code == 409, r.text
    assert get_state().sessions_by_id.keys() == avant.keys()


def test_une_seance_creee_ici_est_modifiable_et_supprimable_par_les_endpoints_personnalises_existants(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    session_id = client.post("/placements/evenements", json=_corps_creation()).json()["session_id"]

    r = client.patch(f"/placements/personnalisees/{session_id}", json={"note": "Salle changée"})
    assert r.status_code == 200, r.text

    r = client.delete(f"/placements/personnalisees/{session_id}")
    assert r.status_code == 200, r.text
    assert session_id not in get_state().sessions_by_id
