"""Lecture des événements Live — parsing RPC, pas de navigateur."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cal_iut.celcat.lecture import (
    est_cours,
    est_fantome,
    est_ferie,
    evenement_depuis_rpc,
    indice_depuis_lundi,
    premiere_semaine_depuis_infobulle,
    sur_la_semaine,
)
from cal_iut.celcat.rpc import parser_reponse

GROUP_ID = 1661972
GROUPE = "BUT MMI S1 TD AB"
_FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"


def _bruts() -> list[dict]:
    return json.loads(_FIX.read_text(encoding="utf-8"))


def _par_id(event_id: int) -> dict:
    for brut in _bruts():
        if brut.get("event_id") == event_id:
            return brut
    raise LookupError(event_id)


def _ev(brut: dict):
    return evenement_depuis_rpc(brut, group_id=GROUP_ID, groupe_nom=GROUPE)


def test_should_parse_celcat_epoch_clock_when_start_time_has_date() -> None:
    ev = _ev({
        "event_id": 4, "day_of_week": 0,
        "start_time": "1899-12-31 09:30:00+00:00",
        "end_time": "1899-12-31 11:00:00+00:00",
        "evCatName": "[CM]", "modules": [{"name": "WR106"}], "rooms": [],
        "groups": [], "weeks": "Y", "protected": "N",
    })
    assert ev.heure_debut == "09:30"
    assert ev.heure_fin == "11:00"


def test_should_map_rpc_monday_zero_to_entree_jour_one() -> None:
    ev = _ev({
        "event_id": 3, "day_of_week": 0, "start_time": "08:00", "end_time": "09:30",
        "evCatName": "[TD]", "modules": [{"name": "WR107"}], "rooms": [],
        "groups": [], "weeks": "Y", "protected": "N",
    })
    assert ev.jour == 1


def test_should_parse_iso_june_morning_when_start_time_is_js_date() -> None:
    brut = parser_reponse(
        '{"event_id": 1, "day_of_week": 1, "start_time": new Date(2026,5,12,8,0,0,0),'
        ' "end_time": new Date(2026,5,12,9,30,0,0), "evCatName": "[TD]",'
        ' "modules": [], "rooms": [], "groups": [], "weeks": "Y", "protected": "N"}'
    )
    assert brut["start_time"] == "2026-06-12T08:00:00"
    ev = _ev(brut)
    assert ev.heure_debut == "08:00"


def test_should_convert_minutes_to_clock_when_times_are_ints() -> None:
    ev = _ev({
        "event_id": 2, "day_of_week": 1, "start_time": 480, "end_time": 570,
        "evCatName": "[TD]", "modules": [{"name": "WR107"}], "rooms": [],
        "groups": [], "weeks": "Y", "protected": "N",
    })
    assert ev.heure_debut == "08:00"
    assert ev.heure_fin == "09:30"


def test_should_mark_fantome_when_module_and_times_empty() -> None:
    ev = _ev(_par_id(1929034))
    assert est_fantome(ev)
    assert not est_ferie(ev)
    assert not est_cours(ev)


def test_should_mark_ferie_when_category_contains_ferie() -> None:
    assert est_ferie(_ev(_par_id(1665591)))
    autre = _ev({
        "event_id": 9, "day_of_week": 1, "start_time": None, "end_time": None,
        "evCatName": "férié", "modules": [], "rooms": [], "groups": [],
        "weeks": "Y" * 54, "protected": "Y",
    })
    assert est_ferie(autre)


def test_should_return_indice_3_when_lundi_is_september_7_and_first_week_34() -> None:
    assert indice_depuis_lundi(date(2026, 9, 7), premiere_semaine_celcat=34) == 3


def test_should_extract_week_number_when_infobulle_has_week_prefix() -> None:
    assert premiere_semaine_depuis_infobulle("Week: 34 (8/17/26-8/23/26)") == 34
    assert premiere_semaine_depuis_infobulle("pas une infobulle") is None


def test_should_be_on_week_three_when_wr106_weeks_has_y_at_index() -> None:
    ev = _ev(_par_id(1931666))
    assert sur_la_semaine(ev, 3)
    assert not sur_la_semaine(ev, 0)
    assert est_cours(ev)
