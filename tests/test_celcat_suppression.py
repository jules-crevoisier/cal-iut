"""Supprimer une séance déjà posée dans Celcat, via RPC — même cause racine
que modifier_seance : localiser l'événement d'abord, jamais deviner.

Le garde-fou (`file_attente.autoriser_suppression`) est réévalué sur
l'enregistrement FRAIS relu depuis Celcat, jamais sur l'instantané porté par
le job en file — un jour férié protégé bloque même si le job a été mis en
file avant que la protection ne soit visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_celcat_rpc import FaussePage

from cal_iut.celcat.rpc import MethodeSuppressionAbsente, supprimer_evenement_rpc
from cal_iut.celcat.rpc_config import charger_methodes
from cal_iut.celcat.suppression import (
    ElementSuppression,
    ResultatSuppression,
    SuppressionRefusee,
    supprimer_evenement,
    supprimer_manquants,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972


def _bruts() -> list[dict]:
    return json.loads(FIX.read_text(encoding="utf-8"))


def _brut(event_id: int) -> dict:
    return dict(next(b for b in _bruts() if b["event_id"] == event_id))


def _brut_protege(event_id: int = 5001) -> dict:
    """Séance ordinaire, protected=Y — isolé du cas férié/fantôme."""
    return {
        "event_id": event_id,
        "day_of_week": 0,
        "start_time": "08:00",
        "end_time": "09:30",
        "evCatName": "[TD]",
        "event_cat_id": 4,
        "rooms": [{"id": 104105, "name": "H.105"}],
        "modules": [{"id": 601106, "name": "WR106"}],
        "staff": [{"name": "RIGUET Marine"}],
        "groups": [{"id": GROUP_ID, "name": "BUT MMI S1 TD AB"}],
        "weeks": "Y" + "N" * 53,
        "protected": "Y",
        "global_event": "N",
        "suspended": "N",
    }


def _methodes_appelees(page: FaussePage) -> list[str | None]:
    return [
        (arg.get("methode") or arg.get("method"))
        for _js, arg in page.journal
        if isinstance(arg, dict)
    ]


# ---------------------------------------------------------------------------
# rpc.py::supprimer_evenement_rpc — mirroir de enregistrer_evenement
# ---------------------------------------------------------------------------


def test_should_raise_methode_suppression_absente_when_supprimer_evenement_rpc_methode_is_empty() -> None:
    page = FaussePage()
    with pytest.raises(MethodeSuppressionAbsente):
        supprimer_evenement_rpc(page, 1931666, methode="")
    assert page.journal == []  # jamais d'appel RPC réel


def test_should_send_a_minus_event_id_only_payload_when_supprimer_evenement_rpc_is_called() -> None:
    """Prouvé par canari le 05/09/2026 sur URCA_FORMATION : suppression =
    udlTimetables.save (même méthode que create/update) avec un
    enregistrement MINIMAL {"-event_id": id, "_type_": "Event"} — pas
    l'enregistrement complet."""
    page = FaussePage()
    page.reponses["udlTimetables.save"] = [{"event_id": 1931666}]
    supprimer_evenement_rpc(page, 1931666, methode="udlTimetables.save")
    envoi = next(arg for _js, arg in page.journal if isinstance(arg, dict) and arg.get("methode") == "udlTimetables.save")
    assert envoi["params"] == [[{"-event_id": 1931666, "_type_": "Event"}]]


def test_should_read_methode_suppression_from_yaml_via_charger_methodes(tmp_path) -> None:
    (tmp_path / "celcat_rpc.yaml").write_text(
        "methode_ecriture: udlTimetables.save\nmethode_suppression:\nevent_id_create: omit\n",
        encoding="utf-8",
    )
    cfg = charger_methodes(tmp_path)
    assert cfg.methode_ecriture == "udlTimetables.save"
    assert cfg.methode_suppression == ""


# ---------------------------------------------------------------------------
# suppression.py::supprimer_evenement
# ---------------------------------------------------------------------------


def test_should_raise_suppression_refusee_and_not_call_supprimer_evenement_rpc_when_freshly_localized_event_is_protected_even_if_the_queued_job_predates_that_state() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [_brut_protege()]

    with pytest.raises(SuppressionRefusee):
        supprimer_evenement(page, 5001, group_id=GROUP_ID, methode="udlTimetables.remove")

    assert "udlTimetables.remove" not in _methodes_appelees(page)


def test_should_raise_suppression_refusee_and_not_call_supprimer_evenement_rpc_when_freshly_localized_event_is_a_fantome() -> None:
    page = FaussePage()
    fantome = _brut(1929034)
    page.reponses["udlTimetables.load"] = [fantome]

    with pytest.raises(SuppressionRefusee):
        supprimer_evenement(page, 1929034, group_id=GROUP_ID, methode="udlTimetables.remove")

    assert "udlTimetables.remove" not in _methodes_appelees(page)


def test_should_treat_evenement_introuvable_during_supprimer_evenement_as_a_no_op_success_not_an_error() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = []  # rien à trouver : déjà supprimé

    resultat = supprimer_evenement(page, 999999999, group_id=GROUP_ID, methode="udlTimetables.remove")

    assert resultat is None
    assert "udlTimetables.remove" not in _methodes_appelees(page)


# ---------------------------------------------------------------------------
# suppression.py::supprimer_manquants
# ---------------------------------------------------------------------------


def test_should_keep_a_failed_element_in_refusees_guard_vs_echecs_rpc_exception_correctly_in_supprimer_manquants() -> None:
    protege = _brut_protege(event_id=5001)
    normal = _brut(1931666)  # protected=N, non férié, non fantôme
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [protege, normal]
    # Provoque une VRAIE exception RPC (pas un refus de garde-fou) pour la
    # suppression de l'événement normal.
    page.reponses["udlTimetables.remove"] = {"error": {"code": "boom"}}

    elements = [
        ElementSuppression(session_id="s-protege", event_id=5001, group_id=GROUP_ID),
        ElementSuppression(session_id="s-normal", event_id=1931666, group_id=GROUP_ID),
    ]

    resultat = supprimer_manquants(page, elements, methode="udlTimetables.remove")

    assert isinstance(resultat, ResultatSuppression)
    refusees_ids = {sid for sid, _msg in resultat.refusees}
    echecs_ids = {sid for sid, _msg in resultat.echecs}
    assert "s-protege" in refusees_ids
    assert "s-protege" not in echecs_ids
    assert "s-normal" in echecs_ids
    assert "s-normal" not in refusees_ids
