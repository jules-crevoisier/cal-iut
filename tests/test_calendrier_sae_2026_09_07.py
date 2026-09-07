"""GET /calendrier/sae — retour utilisateur 07/09/2026 : « les SAE il faut
que ça remonte » dans l'EDT. Repère informatif (jours COMPLETS, aucun
horaire), jamais une réservation de créneau : cf. `SaeFenetreResponse`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups

from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")


@pytest.fixture
def client(db_isole):
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in ("sessions", "sessions_by_id", "timetable", "groups", "calendar", "config_dir")
    }
    etat.sessions = []
    etat.sessions_by_id = {}
    etat.timetable = []
    etat.groups = GROUPES
    etat.calendar = build_default_calendar_2026_2027()
    etat.config_dir = ROOT / "data" / "config"
    http = TestClient(app)
    creer_compte_actif_et_connecter(http)
    yield http
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_refuse_anonyme(client) -> None:
    anonyme = TestClient(app)
    assert anonyme.get("/calendrier/sae").status_code in (401, 403)


def test_liste_les_fenetres_sae_avec_leurs_jours_semaine_jour_absolus(client) -> None:
    r = client.get("/calendrier/sae?semestre=S1")
    assert r.status_code == 200, r.text
    fenetres = r.json()["fenetres"]
    assert fenetres, "au moins une fenêtre SAE S1 attendue (WS101...)"

    ws101 = next((f for f in fenetres if f["course_code"] == "WS101"), None)
    assert ws101 is not None, [f["course_code"] for f in fenetres]
    assert ws101["parcours"] == "BUT1"
    assert ws101["jours"], "WS101 doit couvrir au moins un jour"
    # Jours COMPLETS et CONSÉCUTIFS attendus (pas de trou dans le calendrier
    # enseignable) — chaque jour est un couple (semaine, jour) valide.
    for j in ws101["jours"]:
        assert 0 <= j["jour"] <= 4
        assert j["semaine"] >= 0


def test_filtre_par_semestre(client) -> None:
    tous = client.get("/calendrier/sae").json()["fenetres"]
    s1_seul = client.get("/calendrier/sae?semestre=S1").json()["fenetres"]
    assert len(s1_seul) <= len(tous)
    assert all(f["parcours"] == "BUT1" or f["parcours"] is None for f in s1_seul)
