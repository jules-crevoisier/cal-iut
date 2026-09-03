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


def test_should_record_semaines_validees_as_lancees_after_nightly_runs_and_saisie_is_on(
    planning,
) -> None:
    from cal_iut.celcat.etat import charger

    activer_saisie(planning)
    planning.post("/celcat/valider", json={"semaines": [SEMAINE]})
    _executer_nuit()
    lancees = charger().get("semaines_lancees") or []
    assert SEMAINE in [int(s) for s in lancees]


def test_should_not_reenqueue_when_week_already_in_semaines_lancees(
    planning,
) -> None:
    activer_saisie(planning)
    planning.post("/celcat/valider", json={"semaines": [SEMAINE]})
    _executer_nuit()
    vider_file()
    _executer_nuit()
    assert jobs_en_attente() == []


def test_should_skip_past_weeks_and_not_mark_them_lancees(
    planning,
    monkeypatch,
) -> None:
    from cal_iut.celcat.etat import charger

    activer_saisie(planning)
    planning.post("/celcat/valider", json={"semaines": [SEMAINE]})
    monkeypatch.setattr(
        "cal_iut.celcat.etat.semaines_celcat_passees",
        lambda **_: [SEMAINE],
    )
    vider_file()
    _executer_nuit()
    assert jobs_en_attente() == []
    assert SEMAINE not in [int(s) for s in charger().get("semaines_lancees") or []]


def test_should_drain_create_update_delete_jobs_from_file_attente_and_call_matching_rpc_function_when_executer_job_nuit_runs_with_a_page_and_do_nothing_rpc_wise_when_page_is_none(
    planning,
    monkeypatch,
) -> None:
    activer_saisie(planning)
    from cal_iut.celcat.file_attente import enfiler

    vider_file()
    enfiler({"action": "create", "session_id": "s-sem-validee", "semaine": SEMAINE})
    enfiler(
        {
            "action": "update",
            "session_id": "s-sem-validee",
            "event_id": 1931666,
            "group_id": GROUP_ID,
            "semaine": SEMAINE,
        }
    )
    enfiler(
        {
            "action": "delete",
            "session_id": "s-disparue",
            "event_id": 1665591,
            "group_id": GROUP_ID,
            "semaine": SEMAINE,
        }
    )

    appels = {"create": 0, "update": 0, "delete": 0}

    def _faux_creer(*_a, **_k):
        from cal_iut.celcat.ecriture import ResultatEcriture

        appels["create"] += 1
        return ResultatEcriture()

    def _faux_modifier(*_a, **_k):
        from cal_iut.celcat.modification import ResultatModification

        appels["update"] += 1
        return ResultatModification()

    def _faux_supprimer(*_a, **_k):
        from cal_iut.celcat.suppression import ResultatSuppression

        appels["delete"] += 1
        return ResultatSuppression()

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _faux_creer)
    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _faux_modifier)
    monkeypatch.setattr("cal_iut.celcat.nuit.supprimer_manquants", _faux_supprimer)

    page = FaussePage()
    _executer_nuit(page)
    assert appels == {"create": 1, "update": 1, "delete": 1}

    apres_page = dict(appels)
    vider_file()
    enfiler({"action": "create", "session_id": "s-sem-validee", "semaine": SEMAINE})
    _executer_nuit(None)
    assert appels == apres_page  # aucun appel RPC supplémentaire sans page


def test_should_remove_only_successfully_processed_or_guard_refused_jobs_from_the_queue_after_consommer_file_leaving_rpc_failed_jobs_for_the_next_run(
    planning,
    monkeypatch,
) -> None:
    activer_saisie(planning)
    from cal_iut.celcat.file_attente import enfiler

    etat = get_state()
    ok = seance("s-create-ok")
    echec = seance("s-create-echec-rpc")
    etat.sessions += [ok, echec]
    etat.sessions_by_id["s-create-ok"] = ok
    etat.sessions_by_id["s-create-echec-rpc"] = echec
    etat.timetable += [
        place(ok, week=SEMAINE, day=2),
        place(echec, week=SEMAINE, day=3),
    ]

    vider_file()
    enfiler({"action": "create", "session_id": "s-create-ok", "semaine": SEMAINE})
    enfiler({"action": "create", "session_id": "s-create-echec-rpc", "semaine": SEMAINE})
    enfiler(
        {
            "action": "delete",
            "session_id": "s-delete-refuse",
            "event_id": 1665591,
            "group_id": GROUP_ID,
            "semaine": SEMAINE,
        }
    )
    enfiler(
        {
            "action": "delete",
            "session_id": "s-delete-echec-rpc",
            "event_id": 9999999,
            "group_id": GROUP_ID,
            "semaine": SEMAINE,
        }
    )

    def _faux_creer(_page, entrees, **_k):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        for e in entrees:
            if e.session_id == "s-create-ok":
                resultat.crees.append((e.session_id, 4242))
            else:
                resultat.echecs.append((e.session_id, "boom RPC create"))
        return resultat

    def _faux_supprimer(_page, elements, **_k):
        from cal_iut.celcat.suppression import ResultatSuppression

        resultat = ResultatSuppression()
        for el in elements:
            if el.session_id == "s-delete-refuse":
                resultat.refusees.append((el.session_id, "protégé"))
            else:
                resultat.echecs.append((el.session_id, "boom RPC delete"))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _faux_creer)
    monkeypatch.setattr("cal_iut.celcat.nuit.supprimer_manquants", _faux_supprimer)

    page = FaussePage()
    _executer_nuit(page)

    restants_ids = {j.get("session_id") for j in jobs_en_attente()}
    assert restants_ids == {"s-create-echec-rpc", "s-delete-echec-rpc"}

