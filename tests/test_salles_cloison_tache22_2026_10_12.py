"""Tâche 22 (Kyllian Bresson, 11/10/2026) : salles à cloison amovible.

« Si une séance est placée en H.007, empêcher le placement d'une autre
séance en H.008, et inversement. Autoriser une exception uniquement si les
deux séances concernent le même code module et sont assurées en parallèle
par deux enseignants différents. Appliquer la même règle aux salles H.201 et
H.203. »
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cal_iut.api.validation import validate_move
from cal_iut.ingestion.config_loader import load_groups, load_rooms
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.cpsat import PlacedSession
from cal_iut.solver.rooms import build_manual_conflict_map

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"
GROUPES = load_groups(CONFIG)
CARTE = build_manual_conflict_map(load_rooms(CONFIG))


def _session(sid: str, code: str, groupe: str, profs: list[str]) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TP,
        sequence_order=1, group_ids=[groupe], teacher_codes=profs,
    )


def _valider(salle_autre: str, salle_moi: str, code_autre: str, code_moi: str,
             profs_autre: list[str], profs_moi: list[str]):
    autre = PlacedSession(
        session_id="autre", week=0, day=0, slot=1, course_code=code_autre,
        group_ids=["but1-tp-a"], teacher_codes=profs_autre,
    )
    autre.room_id = salle_autre
    sessions = {
        "autre": _session("autre", code_autre, "but1-tp-a", profs_autre),
        "moi": _session("moi", code_moi, "but1-tp-b", profs_moi),
    }
    return validate_move(
        "moi", 0, 0, 1, [autre], ["but1-tp-b"], profs_moi, room_id=salle_moi,
        sessions_by_id=sessions, groups=GROUPES, conflicting_room_ids=CARTE.get(salle_moi, set()),
    )


@pytest.mark.parametrize(("a", "b"), [("h007", "h008"), ("h008", "h007"), ("h201", "h203"), ("h203", "h201")])
def test_deux_modules_differents_de_part_et_d_autre_de_la_cloison_sont_refuses(a, b):
    r = _valider(a, b, "WR112", "WR117", ["X"], ["Y"])
    assert not r.valid
    assert any("salle" in c.lower() for c in r.hard_conflicts)


@pytest.mark.parametrize(("a", "b"), [("h007", "h008"), ("h201", "h203")])
def test_meme_module_avec_deux_enseignants_differents_est_autorise(a, b):
    assert _valider(a, b, "WR112", "WR112", ["X"], ["Y"]).valid


def test_meme_module_sans_enseignant_d_un_cote_est_refuse():
    r = _valider("h007", "h008", "WR112", "WR112", ["X"], [])
    assert any("salle" in c.lower() for c in r.hard_conflicts)


def test_meme_module_meme_enseignant_est_refuse():
    r = _valider("h201", "h203", "WR112", "WR112", ["X"], ["X"])
    assert any("salle" in c.lower() for c in r.hard_conflicts)


def test_la_meme_salle_reste_refusee_meme_pour_un_duo():
    r = _valider("h007", "h007", "WR112", "WR112", ["X"], ["Y"])
    assert not r.valid


def test_une_autre_salle_sans_cloison_n_est_pas_concernee():
    assert _valider("h007", "h101", "WR112", "WR117", ["X"], ["Y"]).valid


def test_les_salles_regroupees_ne_sont_plus_choisies_par_la_generation():
    """Jules, 12/10/2026 : H.007-008 et H.201-203 sortent aussi de la
    génération automatique (`placement_auto: false`), et aucune règle ne
    les nomme pour passer outre."""
    from cal_iut.ingestion.config_loader import load_room_assignment_rules
    from cal_iut.solver.rooms import _auto_eligible

    salles = load_rooms(CONFIG)
    fusionnees = {r.id for r in salles if r.combines}
    assert fusionnees == {"h007_h008", "h201_h203"}
    assert not {r.id for r in _auto_eligible(salles, None)} & fusionnees
    for regle in load_room_assignment_rules(CONFIG):
        assert not set(regle.get("preferred_room_ids") or []) & fusionnees
        assert "combined" not in (regle.get("preferred_room_types") or [])
        assert "combined" not in (regle.get("fallback_room_types") or [])
