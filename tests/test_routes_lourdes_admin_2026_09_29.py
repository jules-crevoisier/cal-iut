"""Routes lourdes réservées aux admins (audit 29/09/2026, P1-5).

`/solve`, `/solve/async`, `/ingest`, `/regen/week` : aucun écran ne les
appelle plus, et chacune peut défaire le travail de tous. Un compte `edit`
(ou sa clé API) reçoit 403. La régénération, elle, met enfin ses séances
déplacées dans la file Celcat.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import main
from cal_iut.api.regen import RegenResult
from conftest import creer_compte_actif_et_connecter

ROUTES = [
    ("/solve", {}),
    ("/solve/async", {}),
    ("/ingest", {"parcours": "BUT1", "semestre": "S1"}),
    ("/regen/week", {"week": 10}),
]


@pytest.mark.parametrize(("chemin", "corps"), ROUTES)
def test_un_compte_edit_ne_peut_plus_appeler_les_routes_lourdes(db_isole, chemin, corps):
    client = TestClient(main.app)
    creer_compte_actif_et_connecter(client, role="edit")
    reponse = client.post(chemin, json=corps)
    assert reponse.status_code == 403, reponse.text


def test_la_regeneration_met_ses_seances_deplacees_dans_la_file_celcat(monkeypatch):
    signales: list[tuple[str, str]] = []
    monkeypatch.setattr(main, "_current_job", None)
    monkeypatch.setattr(main, "_current_regen_job", None)
    monkeypatch.setattr(main, "_current_lissage_job", None)
    monkeypatch.setattr(main, "get_state", lambda: SimpleNamespace(timetable=[object()], sessions_by_id={}))
    monkeypatch.setattr(main, "get_repo", lambda: None)
    monkeypatch.setattr(
        main, "regen_and_persist",
        lambda state, repo, weeks: RegenResult(
            status="OPTIMAL", touched_weeks=weeks, placements=[], deplacees=["A", "C"],
        ),
    )
    monkeypatch.setattr(main, "_apres_ecriture_planning", lambda sid, action: signales.append((sid, action)))

    from cal_iut.api.schemas import RegenRequest

    main.regen_week(RegenRequest(week=10))
    limite = time.monotonic() + 5
    while main._current_regen_job.status == "running" and time.monotonic() < limite:
        time.sleep(0.01)
    assert main._current_regen_job.status == "done", main._current_regen_job.error_detail
    assert signales == [("A", "update"), ("C", "update")]
