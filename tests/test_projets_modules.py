"""Projets de modules (S4 : SAE, back, front, retour sur la SAE) : saisie à
l'écran, chargeur et effet sur le calcul."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient
from ortools.sat.python import cp_model

from cal_iut.api import main as api
from cal_iut.api.main import app
from cal_iut.ingestion import reglages
from cal_iut.ingestion.config_loader import load_projets_modules
from cal_iut.models.entities import EtapeProjet, ProjetModules
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.objectives import add_projet_modules_penalties

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


@pytest.fixture
def admin(db_isole) -> TestClient:
    api.charger_etat_applicatif()
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


@pytest.fixture
def generations_isolees(tmp_path, monkeypatch):
    from cal_iut.generation import taches

    monkeypatch.setattr(taches, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(taches, "GENERATIONS_DIR", tmp_path / "state" / "generations")
    monkeypatch.setattr(taches, "lancer", lambda generation_id: 4242)


def _corps(**extra) -> dict:
    corps = {
        "nom": "Projet S4",
        "etapes": [
            {"code": "WS401D", "type": "TD", "de": 1, "a": 4},
            {"code": "WR407D"},
            {"code": "WR406D"},
            {"code": "WS401D", "type": "TD", "de": 5, "a": 7},
        ],
        "jours_par_semaine": 2,
        "motif": "Demande de l'équipe pédagogique",
    }
    corps.update(extra)
    return corps


def test_un_projet_se_saisit_se_charge_et_se_retire(admin, generations_isolees):
    reponse = admin.post("/generations/regles/even/projets", json=_corps())
    assert reponse.status_code == 201, reponse.text
    (projet,) = reponse.json()["projets"]
    assert projet["jours_par_semaine"] == 2 and len(projet["etapes"]) == 4
    (charge,) = load_projets_modules(CONFIG)
    assert [(e.course_code, e.de, e.a) for e in charge.etapes][0] == ("WS401D", 1, 4)
    assert charge.semestre == "S4"

    retire = admin.delete(f"/generations/regles/even/projets/{projet['id']}")
    assert retire.status_code == 200 and retire.json()["projets"] == []
    assert load_projets_modules(CONFIG) == []


def test_un_projet_refuse_les_saisies_incorrectes(admin, generations_isolees):
    assert admin.post("/generations/regles/even/projets", json=_corps(etapes=[{"code": "WR407D"}])).status_code == 422
    assert admin.post("/generations/regles/even/projets", json=_corps(jours_par_semaine=6)).status_code == 422
    assert admin.post("/generations/regles/even/projets", json=_corps(motif="")).status_code == 422
    inconnu = _corps(etapes=[{"code": "WR407D"}, {"code": "XXX999"}])
    assert admin.post("/generations/regles/even/projets", json=inconnu).status_code == 422
    assert reglages.regles_de_modules(CONFIG, "projets_modules") == []


def _seance(code: str, idx: int, groupe: str = "g1") -> SessionToPlace:
    return SessionToPlace(
        id=f"{code}-S4-TD-{idx}-{groupe}", course_code=code, course_name=code, semestre="S4",
        parcours="P", annee="BUT2", session_type="TD", sequence_order=idx, group_ids=[groupe],
        teacher_codes=["AAA"], teachers=[], duration_slots=2,
    )


def test_le_calcul_place_les_etapes_dans_l_ordre_et_limite_les_jours():
    seances = [_seance("A", 1), _seance("B", 1), _seance("C", 1)]
    projet = ProjetModules(
        id="p", nom="p", semestre="S4", jours_par_semaine=1,
        etapes=[EtapeProjet(course_code=c) for c in ("A", "B", "C")],
    )
    model = cp_model.CpModel()
    semaines = {s.id: model.new_int_var(0, 3, f"w_{s.id}") for s in seances}
    pen = add_projet_modules_penalties(model, seances, semaines, [projet], week_vars=semaines, weeks=4)
    model.minimize(sum(pen))
    solveur = cp_model.CpSolver()
    assert solveur.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    a, b, c = (solveur.value(semaines[s.id]) for s in seances)
    assert a < b < c
    assert solveur.objective_value == 0


def test_le_rang_d_une_etape_se_compte_en_seances_de_1h30():
    from cal_iut.solver.objectives import _sessions_de_l_etape

    # 7 TD dont les 6 premiers regroupés par deux : 3 blocs de 3 h puis 1 séance simple.
    seances = [_seance("A", i) for i in (1, 3, 5)] + [
        _seance("A", 7).model_copy(update={"duration_slots": 1})
    ]
    etape = EtapeProjet(course_code="A", session_type="TD", de=1, a=4)
    assert [s.sequence_order for s in _sessions_de_l_etape(seances, "S4", etape)] == [1, 3]
    suite = EtapeProjet(course_code="A", session_type="TD", de=5)
    assert [s.sequence_order for s in _sessions_de_l_etape(seances, "S4", suite)] == [5, 7]


def test_un_duo_de_td_se_saisit_et_synchronise_les_deux_enseignants(admin, generations_isolees):
    from cal_iut.ingestion.config_loader import load_teacher_duos
    from cal_iut.ingestion.pipeline import run_ingestion
    from cal_iut.solver.constraints import duo_episode_pairs

    etat = admin.get("/generations/regles/even").json()
    module = next(m for m in etat["modules"] if m["code"] == "WR407D")
    assert len(module["groupes_td"]) >= 2
    t1, t2 = [e["code"] for e in module["enseignants"] if e["td_tp"]][:2]
    a, b = module["groupes_td"][:2]

    corps = {
        "code": "WR407D", "enseignants": [t1, t2], "salles": [], "type": "TD", "de": 1, "a": 7,
        "groupes": {t1: [a], t2: [b]}, "motif": "TD en parallèle (tâche #36)",
    }
    reponse = admin.post("/generations/regles/even/duos", json=corps)
    assert reponse.status_code == 201, reponse.text
    (duo_saisi,) = [d for d in reponse.json()["duos"] if d["type"] == "TD"]
    assert (duo_saisi["de"], duo_saisi["a"], duo_saisi["salles"]) == (1, 7, [])
    # Un second duo de TD pour les mêmes enseignants est refusé, un duo de TP reste possible.
    assert admin.post("/generations/regles/even/duos", json=corps).status_code == 409

    (duo,) = [d for d in load_teacher_duos(CONFIG) if d.course_codes == ["WR407D"]]
    assert duo.session_types == ["TD"] and duo.rare_rooms == () and (duo.rang_de, duo.rang_a) == (1, 7)

    seances = [s for s in run_ingestion(CONFIG, semestre_group="even").sessions if s.course_code == "WR407D"]
    tds = [s for s in seances if s.session_type.value == "TD"]
    assert {s.teacher_codes[0] for s in tds if s.group_ids[0].lower().endswith(f"-td-{a.lower()}")} == {t1}
    assert {s.teacher_codes[0] for s in tds if s.group_ids[0].lower().endswith(f"-td-{b.lower()}")} == {t2}
    paires = duo_episode_pairs(seances, [duo])
    assert paires and all(
        len(p) == 2 for p in paires
    )
