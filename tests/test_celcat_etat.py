"""État Celcat, Valider (lot de nuit), auth admin, pagination des logs."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from celcat_sync_helpers import (
    V1_JOURNAL,
    charger_etat,
    extraire_logs,
    jobs_en_attente,
)
from conftest import creer_compte_actif_et_connecter
from test_celcat_rpc import FaussePage

NOUVELLES_ECRITURES = (
    ("patch", "/celcat/saisie", {"active": True}),
    ("post", "/celcat/valider", {"semaines": [1, 2]}),
    ("post", "/celcat/lancer-nuit", None),
    ("post", "/celcat/extras/extra-1/ajouter", None),
    ("post", "/celcat/extras/extra-1/ignorer", None),
)


def _appeler(client: TestClient, methode: str, url: str, corps: dict | None):
    fn = getattr(client, methode)
    return fn(url, json=corps) if corps is not None else fn(url)


@pytest.fixture
def client_admin(db_isole):
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def test_should_wrap_legacy_flat_journal_under_journal_when_loading_v1_celcat_sync_json(
    tmp_path,
    monkeypatch,
) -> None:
    from cal_iut.celcat import sync

    dest = tmp_path / "celcat_sync.json"
    dest.write_text(V1_JOURNAL.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sync, "_path", lambda: dest)
    try:
        from cal_iut.celcat import etat as celcat_etat
    except ImportError:
        celcat_etat = None
    if celcat_etat is not None and hasattr(celcat_etat, "_path"):
        monkeypatch.setattr(celcat_etat, "_path", lambda: dest)

    v1 = json.loads(dest.read_text(encoding="utf-8"))
    assert "journal" not in v1
    assert "s-legacy" in v1

    charge = charger_etat()
    assert "journal" in charge
    assert "s-legacy" in charge["journal"]
    assert charge["journal"]["s-legacy"]["event_id"] == 1931666
    assert charge["journal"]["s-legacy"]["session_id"] == "s-legacy"
    assert "s-legacy" in sync.journal()


def test_should_persist_saisie_active_false_by_default_when_no_settings_exist(
    client_admin,
    tmp_path,
) -> None:
    sync_path = tmp_path / "celcat_sync.json"
    if sync_path.exists():
        sync_path.unlink()

    reponse = client_admin.get("/celcat/etat")
    assert reponse.status_code == 200, reponse.text
    etat = reponse.json()
    assert etat["saisie_active"] is False
    assert "semaines_validees" in etat
    assert "semaines_passees" in etat
    assert "semaines_lancees" in etat
    assert "valide_le" in etat
    assert "dernier_job" in etat
    assert "compteurs" in etat
    assert "worker_ok" in etat

    charge = charger_etat()
    assert charge["saisie_active"] is False
    assert client_admin.get("/celcat/etat").json()["saisie_active"] is False


def test_should_return_updated_etat_when_patch_celcat_saisie_active_true_as_admin(
    client_admin,
) -> None:
    reponse = client_admin.patch("/celcat/saisie", json={"active": True})
    assert reponse.status_code == 200, reponse.text
    etat = reponse.json()
    assert etat["saisie_active"] is True
    assert client_admin.get("/celcat/etat").json()["saisie_active"] is True
    assert charger_etat()["saisie_active"] is True


def test_should_return_401_or_403_when_non_admin_hits_any_new_celcat_write(db_isole) -> None:
    anonyme = TestClient(app)
    for methode, url, corps in NOUVELLES_ECRITURES:
        statut = _appeler(anonyme, methode, url, corps).status_code
        assert statut in (401, 403), f"{methode.upper()} {url} anonyme → {statut}"

    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    for methode, url, corps in NOUVELLES_ECRITURES:
        statut = _appeler(editeur, methode, url, corps).status_code
        assert statut in (401, 403), f"{methode.upper()} {url} edit → {statut}"


def test_should_store_semaines_validees_and_valide_le_when_post_celcat_valider(
    client_admin,
) -> None:
    reponse = client_admin.post("/celcat/valider", json={"semaines": [1, 2]})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["semaines_validees"] == [1, 2]
    assert corps["valide_le"]
    etat = client_admin.get("/celcat/etat").json()
    assert etat["semaines_validees"] == [1, 2]
    assert etat["valide_le"] == corps["valide_le"]


def test_should_not_enqueue_queue_jobs_and_not_call_rpc_when_valider_succeeds(
    client_admin,
    monkeypatch,
) -> None:
    appels_rpc: list[object] = []

    def _interdit(*_a: object, **_k: object) -> None:
        appels_rpc.append((_a, _k))
        raise AssertionError("Valider ne doit pas appeler le RPC Live")

    monkeypatch.setattr("cal_iut.celcat.rpc.appeler", _interdit)
    page = FaussePage()
    monkeypatch.setattr("cal_iut.celcat.rpc.charger_edt", lambda *_a, **_k: page.journal.append("load") or [])

    reponse = client_admin.post("/celcat/valider", json={"semaines": [1, 2]})
    assert reponse.status_code == 200, reponse.text
    assert appels_rpc == []
    assert page.journal == []
    assert jobs_en_attente() == []


def test_should_paginate_get_celcat_logs_and_include_created_modified_deleted_blocked_with_motif(
    client_admin,
) -> None:
    from cal_iut.celcat.logs import append as append_log

    append_log(kind="created", motif=None, session_id="s-a")
    append_log(kind="modified", motif=None, session_id="s-b")
    append_log(kind="deleted", motif=None, session_id="s-c")
    append_log(kind="blocked", motif="WR314D sans code Celcat", session_id="s-d")
    append_log(kind="created", motif=None, session_id="s-e")

    premiere = client_admin.get("/celcat/logs?limit=2")
    assert premiere.status_code == 200, premiere.text
    page1, cursor = extraire_logs(premiere.json())
    assert len(page1) == 2
    assert cursor

    suite = client_admin.get(f"/celcat/logs?limit=2&cursor={cursor}")
    assert suite.status_code == 200, suite.text
    page2, _ = extraire_logs(suite.json())
    assert page2
    assert [x.get("session_id") for x in page1] != [x.get("session_id") for x in page2] or page1 != page2

    tout = extraire_logs(client_admin.get("/celcat/logs?limit=50").json())[0]
    kinds = {str(item.get("kind")) for item in tout}
    assert {"created", "modified", "deleted", "blocked"} <= kinds
    bloques = [item for item in tout if item.get("kind") == "blocked"]
    assert bloques
    assert any(item.get("motif") and "WR314D" in str(item["motif"]) for item in bloques)


def test_should_expose_the_last_real_write_separately_from_blocked_attempts(
    client_admin,
) -> None:
    """Retour utilisateur (03/09/2026) : « on voudrait la dernière fois
    qu'une modification faite dans l'app a été appliquée dans Celcat » —
    `valide_le`/`dernier_job` ne mesurent que des actions admin (valider un
    lot, lancer le job), jamais une écriture réellement confirmée."""
    from cal_iut.celcat.logs import append as append_log

    append_log(kind="created", motif=None, session_id="s-a")
    append_log(kind="blocked", motif="WR314D sans code Celcat", session_id="s-d")

    etat = client_admin.get("/celcat/etat").json()
    apres_created = etat["derniere_ecriture_celcat"]
    assert apres_created is not None

    # Un « blocked » plus RÉCENT ne doit pas passer pour une écriture réelle.
    append_log(kind="blocked", motif="WS310D sans code Celcat", session_id="s-f")
    etat2 = client_admin.get("/celcat/etat").json()
    assert etat2["derniere_ecriture_celcat"] == apres_created

    append_log(kind="modified", motif=None, session_id="s-g")
    etat3 = client_admin.get("/celcat/etat").json()
    assert etat3["derniere_ecriture_celcat"] != apres_created


def test_should_list_past_solver_weeks_as_semaines_passees_when_today_is_after_them(
    client_admin,
) -> None:
    from datetime import date

    from cal_iut.celcat.etat import semaines_celcat_passees

    passees = semaines_celcat_passees(today=date(2026, 9, 16))
    assert 1 in passees
    assert 2 in passees
    assert 4 not in passees
    etat = client_admin.get("/celcat/etat").json()
    assert isinstance(etat["semaines_passees"], list)
    assert isinstance(etat["semaines_lancees"], list)


def test_should_return_409_when_post_celcat_lancer_nuit_and_saisie_is_off(
    client_admin,
) -> None:
    reponse = client_admin.post("/celcat/lancer-nuit")
    assert reponse.status_code == 409, reponse.text
    assert client_admin.get("/celcat/etat").json()["semaines_lancees"] == []


def test_should_mark_validees_as_lancees_when_post_celcat_lancer_nuit_and_saisie_is_on(
    client_admin,
) -> None:
    client_admin.patch("/celcat/saisie", json={"active": True})
    client_admin.post("/celcat/valider", json={"semaines": [4, 5]})
    reponse = client_admin.post("/celcat/lancer-nuit")
    assert reponse.status_code == 200, reponse.text
    lancees = reponse.json()["semaines_lancees"]
    assert 4 in lancees
    assert 5 in lancees
    assert client_admin.get("/celcat/etat").json()["semaines_lancees"] == lancees
    assert reponse.json()["dernier_job"]

