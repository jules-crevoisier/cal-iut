"""Diff cal-iut ↔ Celcat Live — créer les manquants, jamais supprimer."""

from __future__ import annotations

import json
from pathlib import Path

from cal_iut.celcat.diff import comparer
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.mapping import EntreeCelcat

GROUP_ID = 1661972
GROUPE = "BUT MMI S1 TD AB"
_FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"


def _bruts() -> list[dict]:
    return json.loads(_FIX.read_text(encoding="utf-8"))


def _ev(brut: dict):
    return evenement_depuis_rpc(brut, group_id=GROUP_ID, groupe_nom=GROUPE)


def _live():
    return [_ev(b) for b in _bruts()]


def _entree(**kw) -> EntreeCelcat:
    base = dict(
        session_id="s-wr106-ab",
        semaine=4,
        jour=1,
        heure_debut="08:00",
        heure_fin="09:30",
        code_enseignant="RIGUET",
        salle="H.105",
        code_module="TSBZ2106",
        type_seance=4,
        type_seance_nom="CM",
        groupe="TD AB",
        semestre="S1",
        lundi="2026-09-07",
        course_code="WR106",
    )
    base.update(kw)
    return EntreeCelcat(**base)


def _ids(evenements) -> set[int]:
    return {e.event_id for e in evenements}


def test_should_put_entree_in_a_creer_when_no_live_event_matches() -> None:
    manquante = _entree(session_id="s-wr107", course_code="WR107", code_module="TSBZ2107")
    plan = comparer([manquante], _live(), indice_semaine=3)
    assert manquante in plan.a_creer
    assert manquante not in [p[0] for p in plan.deja_la]


def test_should_put_pair_in_deja_la_when_exactly_one_course_matches() -> None:
    entree = _entree()
    plan = comparer([entree], _live(), indice_semaine=3)
    assert len(plan.deja_la) == 1
    paire = plan.deja_la[0]
    assert paire[0].session_id == entree.session_id
    assert paire[1].event_id == 1931666
    assert entree not in plan.a_creer


def test_should_put_entree_in_ambigu_when_two_live_events_match() -> None:
    wr106 = next(b for b in _bruts() if b["event_id"] == 1931666)
    jumeau = dict(wr106, event_id=1931667)
    entree = _entree()
    plan = comparer([entree], [_ev(wr106), _ev(jumeau)], indice_semaine=3)
    assert entree in plan.ambigu
    assert entree not in plan.a_creer


def test_should_put_celcat_only_course_in_celcat_en_plus_when_no_entree() -> None:
    plan = comparer([], _live(), indice_semaine=3)
    assert 1931666 in _ids(plan.celcat_en_plus)
    assert 1931666 not in {getattr(e, "event_id", None) for e in plan.a_creer}


def test_should_expose_a_modifier_and_a_supprimer_when_plan_is_built() -> None:
    plan = comparer([_entree()], _live(), indice_semaine=3)
    assert hasattr(plan, "a_supprimer")
    assert hasattr(plan, "a_modifier")
    for nom in ("a_creer", "deja_la", "ambigu", "bloquees", "celcat_en_plus", "fantomes"):
        assert hasattr(plan, nom)


def test_should_put_entree_in_a_modifier_when_live_category_is_tp_for_cm() -> None:
    """CM journalisé en [TP] (bug autoclicker) doit partir en update, pas OK."""
    wr106 = next(b for b in _bruts() if b["event_id"] == 1931666)
    faux_tp = dict(wr106, evCatName="[TP]", event_cat_id=999)
    entree = _entree(type_seance_nom="CM")
    plan = comparer([entree], [_ev(faux_tp)], indice_semaine=3)
    assert any(p[0].session_id == entree.session_id for p in plan.a_modifier)
    assert entree not in [p[0] for p in plan.deja_la]


def test_should_put_entree_in_a_modifier_when_live_room_differs() -> None:
    entree = _entree(salle="H.999")
    plan = comparer([entree], _live(), indice_semaine=3)
    assert any(p[0].session_id == entree.session_id for p in plan.a_modifier)
    assert entree not in plan.a_creer


def test_should_keep_protected_holiday_out_of_create_targets_when_protected_y() -> None:
    plan = comparer([_entree()], _live(), indice_semaine=3)
    feries = list(getattr(plan, "feries", []))
    dest = _ids(plan.celcat_en_plus) | _ids(feries)
    assert 1665591 in dest
    partenaires = [p[1].event_id for p in plan.deja_la]
    assert 1665591 not in partenaires
    assert 1929034 in _ids(plan.fantomes)


def test_should_treat_as_deja_la_when_live_hours_are_empty() -> None:
    wr106 = next(b for b in _bruts() if b["event_id"] == 1931666)
    sans_heure = dict(wr106, start_time=None, end_time="")
    entree = _entree()
    plan = comparer([entree], [_ev(sans_heure)], indice_semaine=3)
    assert len(plan.deja_la) == 1
    assert plan.deja_la[0][0].session_id == entree.session_id
    assert entree not in plan.a_creer


def test_should_treat_as_deja_la_when_amphi_name_is_shortened() -> None:
    wr106 = next(b for b in _bruts() if b["event_id"] == 1931666)
    live = dict(
        wr106,
        rooms=[{"id": 1, "name": "Amphi 3"}],
        modules=[{"unique_name": "TSBZ1M18", "name": "WR118 Eco."}],
        groups=[{"id": 1661971, "name": "BUT MMI S1 CM"}],
        day_of_week=0,
        start_time="15:30",
    )
    ev = evenement_depuis_rpc(live, group_id=1661971, groupe_nom="BUT MMI S1 CM")
    entree = _entree(
        session_id="s-wr118-cm",
        course_code="WR118",
        code_module="TSBZ1M18",
        salle="Amphi 3 MMI",
        heure_debut="15:30",
        groupe="CM",
    )
    plan = comparer([entree], [ev], indice_semaine=3)
    assert len(plan.deja_la) == 1
    assert entree not in plan.a_creer
