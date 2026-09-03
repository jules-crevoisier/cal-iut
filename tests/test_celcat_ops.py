"""File d'attente immédiate : place / move / salle / unplace / seance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from celcat_sync_helpers import (
    SEMAINE,
    activer_saisie,
    cours,
    jobs_en_attente,
    monter_planning,
    place,
    restaurer_etat,
    seance,
    snapshot_etat,
    vider_file,
)

from cal_iut.api.state import get_state
from cal_iut.celcat.lecture import est_fantome, est_ferie, evenement_depuis_rpc
from cal_iut.celcat.mapping import CelcatConfig

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
GROUPE = "BUT MMI S1 TD AB"


def _bruts() -> list[dict]:
    return json.loads(FIX.read_text(encoding="utf-8"))


def _ev(event_id: int):
    brut = next(b for b in _bruts() if b["event_id"] == event_id)
    return evenement_depuis_rpc(brut, group_id=GROUP_ID, groupe_nom=GROUPE)


def _actions(jobs: list[dict]) -> list[str]:
    return [str(j.get("action")) for j in jobs]


@pytest.fixture
def planning(db_isole):
    etat = get_state()
    ancien = snapshot_etat(etat)
    placee = seance("placee")
    manquante = seance("manquante")
    client = monter_planning(
        [(placee, place(placee)), (manquante, None)],
        courses=[cours()],
    )
    yield client
    restaurer_etat(etat, ancien)


def _placer_manquante(client) -> None:
    creneau = client.get("/placements/manquante/creneaux-libres").json()["creneaux"][0]
    reponse = client.post(
        "/placements/manquante/placer",
        json={"week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"]},
    )
    assert reponse.status_code == 200, reponse.text


def _seed_journal_event(session_id: str, event_id: int) -> None:
    from cal_iut.celcat.etat import charger, sauver

    charge = charger()
    journal = dict(charge.get("journal") or {})
    journal[session_id] = {
        "session_id": session_id,
        "event_id": event_id,
        "semaine": SEMAINE,
        "jour": 1,
        "heure_debut": "08:00",
        "heure_fin": "09:30",
    }
    charge["journal"] = journal
    sauver(charge)


def _definir_live(evenements: list) -> None:
    from cal_iut.celcat.etat import definir_live

    definir_live(evenements)


def test_should_enqueue_nothing_when_saisie_active_is_false_and_a_place_move_salle_unplace_seance_succeeds(
    planning,
) -> None:
    client = planning
    assert client.get("/celcat/etat").json()["saisie_active"] is False

    _placer_manquante(client)

    deplace = client.patch(
        "/placements/placee",
        json={"week": SEMAINE, "day": 1, "slot": 1, "force": True},
    )
    assert deplace.status_code == 200, deplace.text

    salle = client.patch("/placements/placee/salle", json={"room_id": "h103"})
    assert salle.status_code == 200, salle.text

    seance_patch = client.patch("/placements/placee/seance", json={"teacher_codes": ["JSA"]})
    assert seance_patch.status_code == 200, seance_patch.text

    deposer = client.post("/placements/placee/deposer")
    assert deposer.status_code == 200, deposer.text

    assert jobs_en_attente() == []


def test_should_return_409_and_write_nothing_live_when_post_celcat_saisie_is_called_while_saisie_active_is_false(
    planning,
    monkeypatch,
) -> None:
    appels: list[str] = []

    def _interdit(*_a: object, **_k: object):
        appels.append("rpc")
        raise AssertionError("POST /celcat/saisie ne doit rien écrire Live si saisie OFF")

    monkeypatch.setattr("cal_iut.celcat.rpc.appeler", _interdit)
    monkeypatch.setattr("cal_iut.celcat.rpc.enregistrer_evenement", _interdit)

    reponse = planning.post("/celcat/saisie", json={"semaines": "12"})
    assert reponse.status_code == 409, reponse.text
    assert appels == []
    assert jobs_en_attente() == []


def test_should_enqueue_create_when_saisie_on_and_a_new_placed_session_has_no_journal_event_id(
    planning,
) -> None:
    activer_saisie(planning)
    vider_file()
    _placer_manquante(planning)
    jobs = jobs_en_attente()
    creates = [j for j in jobs if j.get("action") == "create" and j.get("session_id") == "manquante"]
    assert creates
    for job in creates:
        assert job.get("event_id") not in (0, "0")


def test_should_enqueue_update_when_saisie_on_and_journal_has_event_id_after_move_salle_seance(
    planning,
) -> None:
    activer_saisie(planning)
    _seed_journal_event("placee", 1931666)
    vider_file()

    deplace = planning.patch(
        "/placements/placee",
        json={"week": SEMAINE, "day": 1, "slot": 1, "force": True},
    )
    assert deplace.status_code == 200, deplace.text
    apres_move = [j for j in jobs_en_attente() if j.get("action") == "update"]
    assert any(j.get("session_id") == "placee" for j in apres_move)

    vider_file()
    salle = planning.patch("/placements/placee/salle", json={"room_id": "h103"})
    assert salle.status_code == 200, salle.text
    assert any(j.get("action") == "update" and j.get("session_id") == "placee" for j in jobs_en_attente())

    vider_file()
    seance_patch = planning.patch("/placements/placee/seance", json={"teacher_codes": ["JSA"]})
    assert seance_patch.status_code == 200, seance_patch.text
    assert any(j.get("action") == "update" and j.get("session_id") == "placee" for j in jobs_en_attente())
    assert all(j.get("event_id") == 1931666 for j in jobs_en_attente() if j.get("action") == "update")


def test_should_enqueue_delete_when_saisie_on_and_unplace_resolves_via_journal_event_id(
    planning,
) -> None:
    activer_saisie(planning)
    _seed_journal_event("placee", 1931666)
    vider_file()
    reponse = planning.post("/placements/placee/deposer")
    assert reponse.status_code == 200, reponse.text
    deletes = [j for j in jobs_en_attente() if j.get("action") == "delete"]
    assert any(j.get("event_id") == 1931666 for j in deletes)


def test_should_enqueue_delete_when_saisie_on_and_unplace_resolves_via_unique_live_match(
    planning,
) -> None:
    activer_saisie(planning)
    wr106 = _ev(1931666)
    _definir_live([wr106])
    # Session alignée sur le match Live unique (module + groupe + créneau).
    etat = get_state()
    etat.sessions_by_id["placee"].course_code = "WR106"
    etat.timetable[0].course_code = "WR106"
    vider_file()
    reponse = planning.post("/placements/placee/deposer")
    assert reponse.status_code == 200, reponse.text
    deletes = [j for j in jobs_en_attente() if j.get("action") == "delete"]
    assert any(j.get("event_id") == 1931666 for j in deletes)


def test_should_not_enqueue_delete_when_live_match_count_is_0_or_at_least_2(
    planning,
) -> None:
    activer_saisie(planning)
    vider_file()
    _definir_live([])
    assert planning.post("/placements/placee/deposer").status_code == 200
    assert "delete" not in _actions(jobs_en_attente())

    # Remettre la séance pour le second cas.
    etat = get_state()
    placee = etat.sessions_by_id["placee"]
    etat.timetable.append(place(placee))
    wr106 = _ev(1931666)
    jumeau = evenement_depuis_rpc(
        dict(next(b for b in _bruts() if b["event_id"] == 1931666), event_id=1931667),
        group_id=GROUP_ID,
        groupe_nom=GROUPE,
    )
    _definir_live([wr106, jumeau])
    etat.sessions_by_id["placee"].course_code = "WR106"
    etat.timetable[-1].course_code = "WR106"
    vider_file()
    assert planning.post("/placements/placee/deposer").status_code == 200
    assert "delete" not in _actions(jobs_en_attente())


def test_should_not_delete_a_celcat_en_plus_protected_ferie_fantome_event(planning) -> None:
    from cal_iut.celcat.file_attente import autoriser_suppression

    ferie = _ev(1665591)
    fantome = _ev(1929034)
    cours_live = _ev(1931666)
    assert est_ferie(ferie)
    assert ferie.protected == "Y"
    assert est_fantome(fantome)
    assert autoriser_suppression(ferie) is False
    assert autoriser_suppression(fantome) is False
    assert autoriser_suppression(cours_live, categorie="celcat_en_plus") is False

    activer_saisie(planning)
    _seed_journal_event("placee", 1665591)
    vider_file()
    assert planning.post("/placements/placee/deposer").status_code == 200
    assert not any(j.get("event_id") == 1665591 and j.get("action") == "delete" for j in jobs_en_attente())


def test_should_carry_group_id_on_every_enqueued_delete_job_never_silently_missing_it(planning) -> None:
    activer_saisie(planning)

    # Résolution via l'event_id journalisé.
    _seed_journal_event("placee", 1931666)
    vider_file()
    reponse = planning.post("/placements/placee/deposer")
    assert reponse.status_code == 200, reponse.text
    deletes_journal = [j for j in jobs_en_attente() if j.get("action") == "delete"]
    assert any(j.get("event_id") == 1931666 and j.get("group_id") == GROUP_ID for j in deletes_journal)

    # Résolution via le match Live unique (pas d'event_id journalisé).
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    journal_doc = dict(doc.get("journal") or {})
    journal_doc.pop("placee", None)
    doc["journal"] = journal_doc
    sauver(doc)

    etat = get_state()
    placee = etat.sessions_by_id["placee"]
    etat.timetable.append(place(placee))
    wr106 = _ev(1931666)
    _definir_live([wr106])
    etat.sessions_by_id["placee"].course_code = "WR106"
    etat.timetable[-1].course_code = "WR106"

    vider_file()
    reponse2 = planning.post("/placements/placee/deposer")
    assert reponse2.status_code == 200, reponse2.text
    deletes_live = [j for j in jobs_en_attente() if j.get("action") == "delete"]
    assert any(j.get("event_id") == 1931666 and j.get("group_id") == GROUP_ID for j in deletes_live)


def test_should_enqueue_delete_when_mcp_unplace_and_saisie_is_on(planning) -> None:
    """MCP unplace doit passer par le même dépôt HTTP (noter + file delete)."""
    activer_saisie(planning)
    _seed_journal_event("placee", 1931666)
    vider_file()
    from cal_iut.mcp.tools import _executer_item

    _executer_item({"op": "unplace", "session_id": "placee", "status": "ok"})
    deletes = [j for j in jobs_en_attente() if j.get("action") == "delete"]
    assert any(j.get("event_id") == 1931666 for j in deletes)
    assert not any(p.session_id == "placee" for p in get_state().timetable)


def test_should_append_log_kind_blocked_with_motif_containing_the_course_code_when_module_has_no_celcat_code(
    planning,
    monkeypatch,
) -> None:
    cfg = CelcatConfig(
        enseignants={"MRI": "34044"},
        salles={"h101": "H.101", "h103": "H.103"},
        types_seance={"TD": 4, "CM": None},
        modules={},
    )
    monkeypatch.setattr("cal_iut.celcat.ops.load_celcat_config", lambda *_a, **_k: cfg)

    etat = get_state()
    wr314 = seance("wr314", code="WR314D")
    etat.sessions.append(wr314)
    etat.sessions_by_id["wr314"] = wr314
    etat.courses = [cours("WR314D")]

    activer_saisie(planning)
    creneau = planning.get("/placements/wr314/creneaux-libres").json()["creneaux"][0]
    reponse = planning.post(
        "/placements/wr314/placer",
        json={"week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"]},
    )
    assert reponse.status_code == 200, reponse.text

    logs = planning.get("/celcat/logs?limit=50").json()
    items = logs["items"] if isinstance(logs, dict) else logs
    bloques = [x for x in items if isinstance(x, dict) and x.get("kind") == "blocked"]
    assert bloques
    assert any("WR314D" in str(x.get("motif") or "") for x in bloques)


def test_should_keep_the_cal_iut_placement_200_when_celcat_is_blocked_or_worker_is_down(
    planning,
    monkeypatch,
) -> None:
    cfg = CelcatConfig(
        enseignants={"MRI": "34044"},
        salles={"h101": "H.101"},
        types_seance={"TD": 4},
        modules={},
    )
    monkeypatch.setattr("cal_iut.celcat.ops.load_celcat_config", lambda *_a, **_k: cfg)
    activer_saisie(planning)

    wr314 = seance("wr314b", code="WR314D")
    get_state().sessions.append(wr314)
    get_state().sessions_by_id["wr314b"] = wr314
    get_state().courses = [cours("WR314D")]
    creneau = planning.get("/placements/wr314b/creneaux-libres").json()["creneaux"][0]
    bloque = planning.post(
        "/placements/wr314b/placer",
        json={"week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"]},
    )
    assert bloque.status_code == 200, bloque.text
    assert any(p.session_id == "wr314b" for p in get_state().timetable)

    def _worker_mort(*_a: object, **_k: object) -> None:
        raise ConnectionError("worker down")

    monkeypatch.setattr("cal_iut.celcat.file_attente.enfiler", _worker_mort)
    manquante = seance("encore")
    get_state().sessions.append(manquante)
    get_state().sessions_by_id["encore"] = manquante
    creneau2 = planning.get("/placements/encore/creneaux-libres").json()["creneaux"][0]
    down = planning.post(
        "/placements/encore/placer",
        json={"week": creneau2["week"], "day": creneau2["day"], "slot": creneau2["slot"]},
    )
    assert down.status_code == 200, down.text
    assert any(p.session_id == "encore" for p in get_state().timetable)
