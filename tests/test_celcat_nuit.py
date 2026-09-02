"""Job de nuit : semaines validées, skip si saisie OFF, extras Live-only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cal_iut.api.state import get_state
from cal_iut.celcat.lecture import evenement_depuis_rpc
from celcat_sync_helpers import (
    SEMAINE,
    activer_saisie,
    cours,
    extraire_extras,
    jobs_en_attente,
    monter_planning,
    place,
    restaurer_etat,
    seance,
    snapshot_etat,
    vider_file,
)
from test_celcat_rpc import FaussePage

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
GROUPE = "BUT MMI S1 TD AB"


def _wr106():
    brut = next(b for b in json.loads(FIX.read_text(encoding="utf-8")) if b["event_id"] == 1931666)
    return evenement_depuis_rpc(brut, group_id=GROUP_ID, groupe_nom=GROUPE)


def _executer_nuit(page: FaussePage | None = None):
    from cal_iut.celcat.nuit import executer_job_nuit

    if page is None:
        return executer_job_nuit()
    return executer_job_nuit(page=page)


@pytest.fixture
def planning(db_isole):
    etat = get_state()
    ancien = snapshot_etat(etat)
    a = seance("s-sem-validee")
    b = seance("s-hors-lot")
    client = monter_planning(
        [(a, place(a, week=SEMAINE)), (b, place(b, week=SEMAINE + 1, day=1))],
        courses=[cours()],
    )
    yield client
    restaurer_etat(etat, ancien)


def test_should_create_update_delete_only_semaines_validees_when_nightly_runs_and_saisie_is_on(
    planning,
) -> None:
    activer_saisie(planning)
    valide = planning.post("/celcat/valider", json={"semaines": [SEMAINE]})
    assert valide.status_code == 200, valide.text
    vider_file()
    page = FaussePage()
    _executer_nuit(page)
    jobs = jobs_en_attente()
    ids = {j.get("session_id") for j in jobs}
    assert "s-sem-validee" in ids
    assert "s-hors-lot" not in ids
    semaines = {j.get("semaine") for j in jobs if j.get("semaine") is not None}
    assert semaines <= {SEMAINE}


def test_should_skip_login_and_all_rpc_when_nightly_runs_and_saisie_is_off(
    planning,
    monkeypatch,
) -> None:
    assert planning.get("/celcat/etat").json()["saisie_active"] is False
    appels: list[str] = []

    def _rpc(*_a: object, **_k: object):
        appels.append("rpc")
        raise AssertionError("saisie OFF : aucun RPC")

    monkeypatch.setattr("cal_iut.celcat.rpc.appeler", _rpc)
    page = FaussePage()
    _executer_nuit(page)
    assert page.journal == []
    assert appels == []
    assert jobs_en_attente() == []


def test_should_list_a_live_only_mmi_course_as_extra_statut_ouvert_after_nightly_scan(
    planning,
) -> None:
    from cal_iut.celcat.etat import definir_live

    activer_saisie(planning)
    planning.post("/celcat/valider", json={"semaines": [4]})
    definir_live([_wr106()])
    page = FaussePage()
    wr106 = next(b for b in json.loads(FIX.read_text(encoding="utf-8")) if b["event_id"] == 1931666)
    page.reponses["udlTimetables.load"] = [wr106]
    _executer_nuit(page)

    reponse = planning.get("/celcat/extras?statut=ouvert")
    assert reponse.status_code == 200, reponse.text
    lignes = extraire_extras(reponse.json())
    assert any(
        x.get("statut") == "ouvert"
        and (x.get("course_code") == "WR106" or "WR106" in str(x.get("libelle") or x.get("module_nom") or ""))
        for x in lignes
    )
