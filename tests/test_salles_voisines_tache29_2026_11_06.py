"""Tâche 29 (Kyllian Bresson, 03/11/2026) : un même code (module, ressource ou
SAE) programmé en simultané dans deux salles VOISINES n'est pas un conflit de
salle. Les paires viennent de la configuration (`Room.voisines`). Le doublon
enseignant, lui, reste toujours signalé."""

from __future__ import annotations

from pathlib import Path

from test_doublons_salle_enseignant_2026_09_25 import _place, _seance, _state

from cal_iut.api.doublons import doublons
from cal_iut.api.validation import meme_code_en_salles_voisines
from cal_iut.ingestion.config_loader import load_rooms
from cal_iut.models.entities import Room, RoomType

ROOT = Path(__file__).resolve().parents[1]


def _salles() -> list[Room]:
    return load_rooms(ROOT / "data" / "config")


def test_la_configuration_declare_les_trois_paires_voisines():
    voisines = {r.id: set(r.voisines) for r in _salles()}
    assert voisines["h007"] == {"h008"} and voisines["h008"] == {"h007"}
    assert voisines["h201"] == {"h203"} and voisines["h203"] == {"h201"}
    assert voisines["h017"] == {"h022"} and voisines["h022"] == {"h017"}


def test_meme_code_dans_h007_et_h008_avec_un_seul_enseignant_n_est_pas_un_conflit_de_salle():
    a, b = _seance("a", "g1", "MRI"), _seance("b", "g2", "MRI")
    tt = [
        _place("a", 5, 2, 3, "g1", "MRI", "h007", "H.007", code="WR101"),
        _place("b", 5, 2, 3, "g2", "MRI", "h008", "H.008", code="WR101"),
    ]
    res = doublons(_state([a, b], tt, rooms=_salles()))
    assert [e["type"] for e in res] == ["enseignant"]  # le doublon prof reste signalé


def test_codes_differents_dans_h201_et_h203_restent_un_conflit_de_salle():
    a, b = _seance("a", "g1", "MRI"), _seance("b", "g2", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "g1", "MRI", "h201", "H.201", code="WR101"),
        _place("b", 5, 2, 3, "g2", "AUTRE", "h203", "H.203", code="WR102"),
    ]
    res = doublons(_state([a, b], tt, rooms=_salles()))
    assert [e["type"] for e in res] == ["salle"]


def test_deux_enseignants_differents_meme_code_h201_h203_aucun_conflit():
    a, b = _seance("a", "g1", "MRI"), _seance("b", "g2", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "g1", "MRI", "h201", "H.201", code="WR101"),
        _place("b", 5, 2, 3, "g2", "AUTRE", "h203", "H.203", code="WR101"),
    ]
    assert doublons(_state([a, b], tt, rooms=_salles())) == []


def test_meme_code_dans_deux_salles_non_voisines_reste_un_conflit_de_salle_si_equivalentes():
    r = [Room(id="x", label="X", capacity=1, room_type=RoomType.STANDARD),
         Room(id="y", label="Y", capacity=1, room_type=RoomType.STANDARD)]
    assert not meme_code_en_salles_voisines(["C", "C"], ["x", "y"], r)


def test_la_meme_salle_deux_fois_n_est_jamais_voisine_d_elle_meme():
    assert not meme_code_en_salles_voisines(["C", "C"], ["h007", "h007"], _salles())
