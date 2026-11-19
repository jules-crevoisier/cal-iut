"""Contraintes enseignants du 19/11/2026 (#35, #37, #38, #39) : disponibilité
exclusive sur une période, module non dispensé, journée compacte. Aucune donnée
réelle : des codes de test."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import main as api
from cal_iut.api.main import app
from cal_iut.ingestion import reglages
from cal_iut.ingestion.config_loader import load_teacher_availability
from cal_iut.ingestion.pipeline import run_ingestion

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


@pytest.fixture
def admin(db_isole) -> TestClient:
    api.charger_etat_applicatif()
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def _dispo(code: str):
    return next((e for e in load_teacher_availability(CONFIG) if e.teacher_code == code), None)


def test_disponible_uniquement_ces_dates_interdit_les_autres_jours_ouvres():
    reglages.ajouter_disponibilite_exclusive(
        CONFIG, "ZZT", "2027-02-01", "2027-02-12", ["2027-02-02", "2027-02-10"], "Contrat", "admin"
    )
    regles = _dispo("ZZT").forbidden_date_slots
    interdits = {r.date for r in regles}
    # 10 jours ouvrés dans la période, 2 autorisés.
    assert len(interdits) == 8
    assert "2027-02-02" not in interdits and "2027-02-10" not in interdits
    assert "2027-02-06" not in interdits  # samedi : rien à interdire
    assert all(list(r.slots) == [0, 1, 2, 3, 4, 5] for r in regles)


def test_la_disponibilite_exclusive_s_ajoute_aux_indisponibilites_existantes():
    reglages.ajouter(CONFIG, "indisponibilites",
        {"teacher_code": "ZZT", "date": "2026-12-02", "slots": [0, 1], "motif": "x"}, "admin")
    reglages.ajouter_disponibilite_exclusive(CONFIG, "ZZT", "2027-02-01", "2027-02-05", ["2027-02-02"], "m", "admin")
    dates = {r.date for r in _dispo("ZZT").forbidden_date_slots}
    assert "2026-12-02" in dates and "2027-02-01" in dates


@pytest.mark.parametrize(
    "args",
    [
        ("ZZT", "2027-02-05", "2027-02-01", ["2027-02-02"], "m"),
        ("ZZT", "2027-02-01", "2027-02-05", [], "m"),
        ("ZZT", "2027-02-01", "2027-02-05", ["2027-03-02"], "m"),
        ("ZZT", "2027-02-01", "2027-02-05", ["2027-02-02"], ""),
    ],
)
def test_une_saisie_incoherente_est_refusee(args):
    with pytest.raises(reglages.ReglageInvalide):
        reglages.ajouter_disponibilite_exclusive(CONFIG, *args, "admin")


def test_compacter_la_journee_marque_l_enseignant():
    assert not (_dispo("ZZT") and _dispo("ZZT").compacter_journee)
    reglages.ajouter_compacter_journee(CONFIG, "ZZT", "Déjeune à l'IUT", "admin")
    assert _dispo("ZZT").compacter_journee is True
    with pytest.raises(reglages.ReglageInvalide):
        reglages.ajouter_compacter_journee(CONFIG, "ZZT", "encore", "admin")


def test_un_module_non_dispense_n_a_aucune_seance():
    avant = run_ingestion(CONFIG, semestre="S2", parcours=None)
    assert any(s.course_code == "WR220" for s in avant.sessions)
    reglages.ajouter_module_non_dispense(CONFIG, "wr220", "Pas de soutien cette année", "admin")
    apres = run_ingestion(CONFIG, semestre="S2", parcours=None)
    assert not any(s.course_code == "WR220" for s in apres.sessions)
    assert len(apres.sessions) < len(avant.sessions)


def test_routes_ajouter_puis_retirer(admin):
    r = admin.post("/reglages/disponibilites-exclusives", json={
        "teacher_code": "ZZT", "debut": "2027-02-01", "fin": "2027-02-05",
        "dates": ["2027-02-02"], "motif": "m"})
    assert r.status_code == 201
    cle = r.json()["disponibilites_exclusives"][0]["cle"]
    assert admin.post("/reglages/compacter-journee", json={"teacher_code": "ZZT", "motif": "m"}).status_code == 201
    assert admin.post("/reglages/modules-non-dispenses", json={"course_code": "WR220", "motif": "m"}).status_code == 201
    tout = admin.get("/reglages").json()
    assert len(tout["compacter_journee"]) == 1 and tout["modules_non_dispenses"][0]["course_code"] == "WR220"
    assert admin.post("/reglages/compacter-journee", json={"teacher_code": "ZZT", "motif": ""}).status_code == 422
    assert admin.delete("/reglages/disponibilites-exclusives", params={"cle": cle}).json()["disponibilites_exclusives"] == []
