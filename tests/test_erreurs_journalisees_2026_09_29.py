"""Erreurs avalées sans trace sur les chemins critiques — audit du
29/09/2026, P1-6.

- `_try_restore_latest` : `except Exception: pass` démarrait le serveur sur
  un planning vide sans rien dire, et `/health` répondait `ok`.
- `celcat.ops.apres_ecriture_planning` : un échec de mise en file Celcat
  était ignoré, la modification n'atteignait jamais Celcat.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import main
from cal_iut.api.state import AppState, get_state
from cal_iut.celcat import ops


@pytest.fixture
def etat_sauf():
    etat = get_state()
    ancien = (etat.current_run_id, etat.timetable, etat.restauration_erreur)
    yield etat
    etat.current_run_id, etat.timetable, etat.restauration_erreur = ancien


def test_une_restauration_ratee_est_journalisee_et_retenue(monkeypatch, caplog) -> None:
    etat = AppState()
    faux_repo = SimpleNamespace(get_latest_run=lambda: SimpleNamespace(id=7, parcours="BUT1", semestre="S1"))
    monkeypatch.setattr(main, "get_repo", lambda: faux_repo)

    def _casse(*_a, **_k):
        raise ValueError("groups.yaml illisible")

    monkeypatch.setattr(main, "run_ingestion", _casse)
    with caplog.at_level("ERROR"):
        main._try_restore_latest(etat)
    assert "Restauration du planning (run 7) impossible" in caplog.text
    assert "groups.yaml illisible" in caplog.text
    assert etat.restauration_erreur == "ValueError: groups.yaml illisible"


def test_health_503_si_un_run_existe_mais_le_planning_n_est_pas_charge(etat_sauf) -> None:
    etat_sauf.current_run_id = 7
    etat_sauf.timetable = []
    etat_sauf.restauration_erreur = "ValueError: groups.yaml illisible"
    reponse = TestClient(main.app).get("/health")
    assert reponse.status_code == 503
    assert reponse.json()["status"] == "degraded"
    assert "groups.yaml" in reponse.json()["detail"]


def test_health_ok_sans_run(etat_sauf) -> None:
    etat_sauf.current_run_id = None
    etat_sauf.timetable = []
    etat_sauf.restauration_erreur = None
    reponse = TestClient(main.app).get("/health")
    assert reponse.status_code == 200
    assert reponse.json()["status"] == "ok"


def test_health_ok_quand_le_planning_est_charge(etat_sauf) -> None:
    etat_sauf.current_run_id = 7
    etat_sauf.timetable = [object()]
    etat_sauf.restauration_erreur = None
    assert TestClient(main.app).get("/health").status_code == 200


def test_un_echec_de_mise_en_file_celcat_est_journalise_et_visible(monkeypatch, caplog) -> None:
    def _casse(*_a, **_k):
        raise OSError("volume plein")

    lignes: list[dict] = []
    monkeypatch.setattr(ops, "_executer", _casse)
    monkeypatch.setattr(ops, "append_log", lambda **k: lignes.append(k))
    with caplog.at_level("ERROR"):
        ops.apres_ecriture_planning("s1", "update")  # ne lève pas
    assert "File Celcat" in caplog.text
    assert lignes and lignes[0]["kind"] == "blocked"
    assert lignes[0]["session_id"] == "s1"
    assert "volume plein" in lignes[0]["motif"]


def test_le_hook_de_main_journalise_aussi(monkeypatch, caplog) -> None:
    def _casse(*_a, **_k):
        raise RuntimeError("boum")

    monkeypatch.setattr(ops, "apres_ecriture_planning", _casse)
    monkeypatch.setattr(main.sauvegardes, "snapshot_si_necessaire", lambda _s: None)
    monkeypatch.setattr(main.controle_doublons_hebdo, "verifier_si_necessaire", lambda _s: None)
    with caplog.at_level("ERROR"):
        main._apres_ecriture_planning("s1", "update")
    assert "hook après écriture" in caplog.text
