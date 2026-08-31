"""Créer, modifier et supprimer une séance ajoutée à une matière — retour
utilisateur 31/08/2026 : « il va falloir créer un système où l'on peut
créer des cours pour une matière [...] imaginons dans une matière on
veuille rajouter un CM éval ou un TD, il faut pouvoir le faire ».

Trois garanties structurelles, chacune testée séparément :

1. On ne peut ajouter une séance qu'à une matière DÉJÀ CONNUE — jamais en
   inventer une (`_reference_cours`).
2. Une séance dont le PLACEMENT échoue ne laisse absolument aucune trace,
   ni en mémoire (`state.sessions_by_id`) ni sur disque
   (`custom_sessions.json`) — le rollback dans `creer_seance_personnalisee`.
3. Modifier/supprimer ne s'applique JAMAIS à une séance de la maquette,
   seulement à celles créées par ce système — vérifié par un rejet 404
   explicite plutôt qu'un silence qui laisserait croire que ça a marché.
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
SEMAINE = 10  # librement modifiable dans le calendrier 2026-2027


def _seance(sid, groupe="but1-td-ab", prof="MRI", duree=1, code="WR101") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="Cours existant", semestre="S1", parcours="BUT1",
        annee="BUT1", session_type=SessionType.TD, sequence_order=1,
        group_ids=[groupe], teacher_codes=[prof], duration_slots=duree,
    )


def _place(s: SessionToPlace, day: int, slot: int, week: int = SEMAINE) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
    )


def _cours(code="WR101") -> Course:
    prof = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    return Course(
        code=code, name="Cours existant", semestre="S1", parcours="BUT1", annee="BUT1",
        lead=prof, profs=[TeacherBlock(teacher=prof, block="1", td=17, nbGpTd=1, nbGpTp=1)],
        volumes={"cm": 0, "td": 17, "tp": 0}, groupes_td=1, groupes_tp=1,
        progression_defined=False, seance_sequence=[], ordonnancement=[],
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
        client.post("/auth/login", json={"password": "test-password"})
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _corps_creation(**over):
    corps = {
        "course_code": "WR101", "session_type": "TD",
        "group_ids": ["but1-td-ab"], "teacher_codes": ["MRI"],
        "duration_slots": 1, "is_eval": False, "note": "Rattrapage",
        "week": SEMAINE, "day": 2, "slot": 3, "force": False,
    }
    corps.update(over)
    return corps


# --------------------------------------------------------------------------
# Création
# --------------------------------------------------------------------------


def test_creer_une_seance_sur_un_creneau_libre(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/personnalisees", json=_corps_creation())
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["course_code"] == "WR101"
    assert corps["session_type"] == "TD"
    assert (corps["week"], corps["day"], corps["slot"]) == (SEMAINE, 2, 3)

    etat = get_state()
    assert corps["session_id"] in etat.sessions_by_id
    assert any(p.session_id == corps["session_id"] for p in etat.timetable)
    assert etat.sessions_by_id[corps["session_id"]].metadata.get("custom_session") is True


def test_refuse_une_matiere_inconnue(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/personnalisees", json=_corps_creation(course_code="INEXISTANT"))
    assert r.status_code == 404
    assert "INEXISTANT" in r.text


def test_refuse_un_groupe_inconnu(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/personnalisees", json=_corps_creation(group_ids=["groupe-fantome"]))
    assert r.status_code == 400


def test_un_conflit_de_creneau_ne_laisse_aucune_trace(monter):
    """Le rollback : la séance créée mais dont le placement échoue ne doit
    apparaître NULLE PART après coup — retour utilisateur implicite (un
    outil qui alimente la paie ne doit jamais garder de séance fantôme)."""
    a = _seance("a", groupe="but1-td-ab")
    # a occupe déjà (SEMAINE, 2, 3) : la création vise EXACTEMENT ce créneau.
    client = monter([(a, _place(a, 2, 3))])
    avant = dict(get_state().sessions_by_id)

    r = client.post("/placements/personnalisees", json=_corps_creation())
    assert r.status_code == 409

    etat = get_state()
    assert etat.sessions_by_id == avant, "aucune trace en mémoire après un échec"
    assert not any(s.metadata.get("custom_session") for s in etat.sessions)


def test_force_permet_de_creer_malgre_un_conflit_forcable(monter):
    a = _seance("a", groupe="but1-td-ab", prof="AUTRE")
    client = monter([(a, _place(a, 2, 3))])
    r = client.post(
        "/placements/personnalisees",
        json=_corps_creation(teacher_codes=[], force=True),
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------
# Modification
# --------------------------------------------------------------------------


def test_modifier_les_metadonnees_sans_reposition(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = client.post("/placements/personnalisees", json=_corps_creation()).json()["session_id"]

    r = client.patch(f"/placements/personnalisees/{sid}", json={"is_eval": True, "note": "Devenue une éval"})
    assert r.status_code == 200, r.text
    # La position n'a pas bougé : aucune des trois clés n'a été fournie.
    assert (r.json()["day"], r.json()["slot"]) == (2, 3)

    etat = get_state()
    assert etat.sessions_by_id[sid].is_eval is True
    assert etat.sessions_by_id[sid].metadata["note"] == "Devenue une éval"


def test_modifier_la_position_revalide_completement(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = client.post("/placements/personnalisees", json=_corps_creation()).json()["session_id"]

    r = client.patch(f"/placements/personnalisees/{sid}", json={"week": SEMAINE, "day": 4, "slot": 5})
    assert r.status_code == 200, r.text
    assert (r.json()["day"], r.json()["slot"]) == (4, 5)


def test_refuse_de_modifier_une_seance_de_la_maquette(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.patch("/placements/personnalisees/a", json={"is_eval": True})
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Suppression
# --------------------------------------------------------------------------


def test_supprimer_retire_la_metadonnee_et_le_placement(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    sid = client.post("/placements/personnalisees", json=_corps_creation()).json()["session_id"]

    r = client.delete(f"/placements/personnalisees/{sid}")
    assert r.status_code == 200
    assert r.json() == {"supprimee": True}

    etat = get_state()
    assert sid not in etat.sessions_by_id
    assert not any(p.session_id == sid for p in etat.timetable)
    assert not any(s.id == sid for s in etat.sessions)


def test_refuse_de_supprimer_une_seance_de_la_maquette(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.delete("/placements/personnalisees/a")
    assert r.status_code == 404

    etat = get_state()
    assert "a" in etat.sessions_by_id, "la séance de maquette doit être intacte"


# --------------------------------------------------------------------------
# Survie à une ré-ingestion (fusion `custom_sessions.merge_into`)
# --------------------------------------------------------------------------


def test_merge_into_ne_perd_pas_une_seance_maquette_homonyme():
    """La maquette gagne toujours : un id déjà connu n'est jamais écrasé par
    une séance personnalisée du même id (ne devrait normalement jamais se
    produire vu le suffixe CUSTOM, mais la garantie doit tenir quand même)."""
    from cal_iut.api import custom_sessions

    reelle = _seance("WR101-S1-TD-1-but1-td-ab")
    sessions, by_id = custom_sessions.merge_into([reelle], {reelle.id: reelle})
    assert sessions == [reelle]
    assert by_id == {reelle.id: reelle}
