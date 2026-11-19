"""Salle créée deux fois (E.201, 19/11/2026) : rattachée à celle du bâtiment."""

import json

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import custom_rooms, dedoublonnage_salles
from cal_iut.api.main import app
from cal_iut.api.state import get_repo, get_state
from cal_iut.db.models import CurrentPlacement
from cal_iut.models.entities import Room, RoomType

from conftest import creer_compte_actif_et_connecter


@pytest.fixture
def salles(tmp_path, monkeypatch):
    monkeypatch.setattr(custom_rooms, "_path", lambda: tmp_path / "custom_rooms.json")
    return tmp_path


def _room(id_, label):
    return Room(id=id_, label=label, capacity=91, room_type=RoomType.STANDARD)


def test_cle_libelle():
    assert dedoublonnage_salles.cle_libelle("E.201") == dedoublonnage_salles.cle_libelle(" e 201 ") == "e201"


def test_doublon_rattache_a_la_salle_du_batiment(salles, db_isole):
    batiment = [_room("e201", "E.201"), _room("b002", "B.002")]
    custom_rooms.add_custom_room(_room("e-201", "E.201"))
    custom_rooms.add_custom_room(_room("annexe", "Annexe"))
    custom_rooms.set_room_override("e-201", placement_auto=False)
    repo = get_repo()
    db = repo.db
    db.add(CurrentPlacement(session_id="s1", run_id=1, week=1, day=0, slot=0, course_code="X", room_id="e-201", room_label="E.201"))
    db.add(CurrentPlacement(session_id="s2", run_id=1, week=1, day=0, slot=1, course_code="X", room_id="e201", room_label="E.201"))
    db.commit()

    assert dedoublonnage_salles.dedoublonner(batiment, db) == {"e-201": "e201"}

    assert {p.room_id for p in db.query(CurrentPlacement).all()} == {"e201"}
    assert [r.id for r in custom_rooms.load_custom_rooms()] == ["annexe"]
    assert "e-201" not in json.loads(custom_rooms._path().read_text())["overrides"]
    # Rien à refaire la fois suivante.
    assert dedoublonnage_salles.dedoublonner(batiment, db) == {}


def test_deux_salles_ajoutees_de_meme_nom_gardent_la_plus_ancienne(salles):
    custom_rooms.add_custom_room(_room("amphi", "Amphi A"))
    custom_rooms.add_custom_room(_room("amphi-2", "amphi  a"))
    assert dedoublonnage_salles.doublons([]) == {"amphi-2": "amphi"}


def test_creation_refusee_si_le_nom_existe_a_la_ponctuation_pres(salles, db_isole):
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    state = get_state()
    state.rooms = [_room("e201", "E.201")]
    r = client.post("/rooms", json={"label": "E201", "capacity": 30})
    assert r.status_code == 409
