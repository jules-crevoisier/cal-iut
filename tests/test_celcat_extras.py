"""Extras Live-only : Ajouter (séance cal-iut), Ignorer (plus jamais ouvert)."""

from __future__ import annotations

import pytest

from cal_iut.api.state import get_state
from cal_iut.celcat.mapping import CelcatConfig
from celcat_sync_helpers import (
    cours,
    extraire_extras,
    monter_planning,
    place,
    restaurer_etat,
    seance,
    snapshot_etat,
)


def _enregistrer_extra(extra: dict) -> None:
    from cal_iut.celcat.extras import enregistrer

    enregistrer(extra)


@pytest.fixture
def planning(db_isole):
    etat = get_state()
    ancien = snapshot_etat(etat)
    a = seance("deja-la")
    client = monter_planning([(a, place(a))], courses=[cours("WR101"), cours("WR106")])
    yield client
    restaurer_etat(etat, ancien)


def test_should_omit_an_extra_from_ouverts_forever_when_post_ignorer(planning) -> None:
    _enregistrer_extra(
        {
            "id": "extra-ignore",
            "statut": "ouvert",
            "course_code": "WR106",
            "event_id": 1931666,
            "semaine": 4,
            "groupe": "TD AB",
        }
    )
    reponse = planning.post("/celcat/extras/extra-ignore/ignorer")
    assert reponse.status_code == 200, reponse.text

    ouverts = extraire_extras(planning.get("/celcat/extras?statut=ouvert").json())
    assert all(x.get("id") != "extra-ignore" for x in ouverts)

    from cal_iut.celcat.nuit import executer_job_nuit
    from test_celcat_rpc import FaussePage

    executer_job_nuit(page=FaussePage())
    encore = extraire_extras(planning.get("/celcat/extras?statut=ouvert").json())
    assert all(x.get("id") != "extra-ignore" for x in encore)


def test_should_create_a_cal_iut_custom_session_and_set_statut_ajoute_when_post_ajouter_on_a_mapped_module(
    planning,
) -> None:
    _enregistrer_extra(
        {
            "id": "extra-ajoute",
            "statut": "ouvert",
            "course_code": "WR101",
            "event_id": 8000001,
            "semaine": 12,
            "jour": 1,
            "heure_debut": "14:00",
            "heure_fin": "15:30",
            "groupe": "TD AB",
            "group_ids": ["but1-td-ab"],
            "session_type": "TD",
            "teacher_codes": ["MRI"],
        }
    )
    avant = {s.id for s in get_state().sessions}
    reponse = planning.post("/celcat/extras/extra-ajoute/ajouter")
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps.get("statut") == "ajoute"
    sid = corps.get("session_id")
    assert sid
    assert sid not in avant
    creee = get_state().sessions_by_id[sid]
    assert creee.course_code == "WR101"
    assert creee.metadata.get("custom_session") is True
    assert any(p.session_id == sid for p in get_state().timetable)

    ouverts = extraire_extras(planning.get("/celcat/extras?statut=ouvert").json())
    assert all(x.get("id") != "extra-ajoute" for x in ouverts)


def test_should_409_and_invent_no_code_when_ajouter_targets_an_unmapped_s3_module(
    planning,
    monkeypatch,
) -> None:
    cfg = CelcatConfig(
        enseignants={"MRI": "34044"},
        salles={"h101": "H.101"},
        types_seance={"TD": 4},
        modules={"WR101": "TSBZ2104"},
    )
    monkeypatch.setattr("cal_iut.celcat.mapping.load_celcat_config", lambda *_a, **_k: cfg)
    _enregistrer_extra(
        {
            "id": "extra-s3",
            "statut": "ouvert",
            "course_code": "WR314D",
            "event_id": 8000002,
            "semaine": 12,
            "groupe": "TD AB",
            "group_ids": ["but1-td-ab"],
        }
    )
    ids_avant = set(get_state().sessions_by_id)
    chemin_yaml = get_state().config_dir / "celcat.yaml"
    yaml_avant = chemin_yaml.read_text(encoding="utf-8")
    reponse = planning.post("/celcat/extras/extra-s3/ajouter")
    assert reponse.status_code == 409, reponse.text
    assert "WR314D" in reponse.text
    assert set(get_state().sessions_by_id) == ids_avant
    assert chemin_yaml.read_text(encoding="utf-8") == yaml_avant
    assert cfg.modules == {"WR101": "TSBZ2104"}
