"""Relire un brouillon avant de le publier — lot 3 (16/11/2026).

Un brouillon s'ouvre dans les vues habituelles par `GET /brouillons/{id}/
app-state` et `/timetable`, construits sur un état À PART : le planning en
service, lui, ne doit pas bouger d'une séance, ni en mémoire ni en base.
"""

from __future__ import annotations

import dataclasses

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import brouillons
from cal_iut.api.main import app, charger_etat_applicatif
from cal_iut.api.state import get_repo, get_state
from cal_iut.db.models import CurrentPlacement, PlanningRun, SolverPlacement
from cal_iut.db.repository import ETAT_BROUILLON
from cal_iut.ingestion.pipeline import run_ingestion

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")


def _placements(seances, premiere_semaine: int, par_creneau: int = 1) -> list[dict[str, object]]:
    """`par_creneau` séances sur chaque créneau, toutes dans la même salle."""
    rangs = [i // par_creneau for i in range(len(seances))]
    return [
        {
            "session_id": s.id, "week": premiere_semaine + rangs[i] // 20, "day": (rangs[i] // 4) % 5,
            "slot": rangs[i] % 4,
            "course_code": s.course_code, "group_ids": s.group_ids, "teacher_codes": s.teacher_codes,
            "room_id": "h007", "room_label": "H.007",
        }
        for i, s in enumerate(seances)
    ]


@pytest.fixture
def planning(db_isole):
    """Un automne en service (40 séances) et un brouillon du semestre pair
    (30 séances), dans une base isolée. Rend `(run en service, brouillon)`."""
    etat = get_state()
    avant = dataclasses.replace(etat)
    brouillons.oublier()
    config = etat.config_dir if (etat.config_dir / "groups.yaml").exists() else None
    charger_etat_applicatif()
    etat = get_state()
    assert config is None or etat.config_dir == config
    repo = get_repo()
    automne = _placements(run_ingestion(etat.config_dir, semestre_group="odd").sessions[:40], 2)
    en_service = repo.save_run(
        parcours="MMI", semestre="ODD", status="FEASIBLE", objective_value=1, gap_penalty=0, weeks=24,
        solver_placements=automne, current_placements=automne,
    )
    printemps = _placements(run_ingestion(etat.config_dir, semestre_group="even").sessions[:30], 22, par_creneau=2)
    brouillon = repo.save_run(
        parcours="MMI", semestre="EVEN", status="FEASIBLE", objective_value=1, gap_penalty=0, weeks=40,
        solver_placements=printemps, current_placements=[], etat=ETAT_BROUILLON,
    )
    ids = (en_service.id, brouillon.id)
    charger_etat_applicatif()
    yield ids
    brouillons.oublier()
    for champ in dataclasses.fields(avant):
        setattr(etat, champ.name, getattr(avant, champ.name))


@pytest.fixture
def admin(planning) -> TestClient:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def _en_service_en_base() -> list[tuple[int, str]]:
    return sorted((c.run_id, c.session_id) for c in get_repo().db.query(CurrentPlacement))


def test_la_liste_distingue_les_brouillons_de_ce_qui_est_en_service(admin, planning):
    en_service, brouillon = planning

    liste = admin.get("/brouillons").json()

    assert [(b["run_id"], b["groupe"], b["placements"]) for b in liste["brouillons"]] == [(brouillon, "even", 30)]
    assert liste["brouillons"][0]["libelle"] == "Semestre pair (S2, S4, S6)"
    assert liste["brouillons"][0]["cree_le"].endswith("+00:00")
    assert [(r["run_id"], r["groupe"], r["placements"], r["affiche"]) for r in liste["en_service"]] == [
        (en_service, "odd", 40, True)
    ]


def test_relire_un_brouillon_ne_change_rien_au_planning_en_service(admin, planning):
    en_service, brouillon = planning
    etat = get_state()
    service_avant = admin.get("/app-state").json()
    base_avant = _en_service_en_base()
    assert (etat.semestre_group, etat.current_run_id, len(etat.timetable)) == ("odd", en_service, 40)

    reponse = admin.get(f"/brouillons/{brouillon}/app-state")

    assert reponse.status_code == 200, reponse.text
    relu = reponse.json()
    assert relu["brouillon"]["run_id"] == brouillon
    assert len(relu["rows"]) == 30
    # Mêmes clés que le planning en service : les vues l'affichent telles quelles.
    assert set(service_avant) <= set(relu)
    # Les séances du brouillon sont celles du semestre pair, à partir de février.
    assert {r["id"] for r in relu["rows"]}.isdisjoint({r["id"] for r in service_avant["rows"]})
    assert "2027" in relu["weekLabels"][0]
    # Le calcul ne garde que l'identifiant de la salle ; on relit son libellé.
    assert {r["r"] for r in relu["rows"]} == {"H.007"}

    # Le planning en service : même mémoire, même base, même réponse.
    assert (etat.semestre_group, etat.current_run_id, len(etat.timetable)) == ("odd", en_service, 40)
    assert _en_service_en_base() == base_avant
    assert admin.get("/app-state").json() == service_avant


def test_les_placements_du_brouillon_se_filtrent_comme_ceux_du_planning(admin, planning):
    _, brouillon = planning

    tout = admin.get(f"/brouillons/{brouillon}/timetable").json()
    assert len(tout["placements"]) == 30
    enseignant = tout["placements"][0]["teacher_codes"][0]
    filtre = admin.get(f"/brouillons/{brouillon}/timetable", params={"teacher_code": enseignant}).json()
    assert 1 <= len(filtre["placements"]) <= 30
    assert all(enseignant in p["teacher_codes"] for p in filtre["placements"])
    # `/timetable` sert toujours l'automne.
    assert len(admin.get("/timetable").json()["placements"]) == 40


def test_les_doublons_relus_sont_ceux_du_brouillon(admin, planning):
    """Le brouillon d'essai met deux séances par créneau dans la même salle :
    cela doit se voir à la relecture."""
    _, brouillon = planning

    reponse = admin.get(f"/brouillons/{brouillon}/controles/doublons")

    assert reponse.status_code == 200, reponse.text
    relus = reponse.json()["doublons"]
    assert relus
    du_brouillon = {p.session_id for p in get_repo().placements_calcules(brouillon)}
    for doublon in relus:
        assert {s["session_id"] for s in doublon["seances"]} <= du_brouillon
    # Le planning en service, lui, n'en a aucun.
    assert admin.get("/controles/doublons").json()["doublons"] == []


def test_supprimer_un_brouillon_ne_touche_pas_aux_runs_en_service(admin, planning):
    en_service, brouillon = planning

    # Un run en service ne se supprime pas par cette route.
    assert admin.delete(f"/brouillons/{en_service}").status_code == 404
    assert admin.delete(f"/brouillons/{brouillon}").status_code == 200

    repo = get_repo()
    repo.db.expire_all()
    assert repo.db.get(PlanningRun, brouillon) is None
    assert repo.db.query(SolverPlacement).filter_by(run_id=brouillon).count() == 0
    assert repo.db.get(PlanningRun, en_service) is not None
    assert len(_en_service_en_base()) == 40
    assert admin.get(f"/brouillons/{brouillon}/app-state").status_code == 404
    assert admin.get("/brouillons").json()["brouillons"] == []


def test_les_brouillons_sont_reserves_aux_administrateurs(planning):
    _, brouillon = planning
    assert TestClient(app).get("/brouillons").status_code == 401
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    for chemin in (
        "/brouillons", f"/brouillons/{brouillon}/app-state", f"/brouillons/{brouillon}/timetable",
        f"/brouillons/{brouillon}/controles/doublons",
    ):
        assert editeur.get(chemin).status_code == 403, chemin
    assert editeur.delete(f"/brouillons/{brouillon}").status_code == 403
    assert get_repo().get_brouillon(brouillon) is not None


def test_publier_un_brouillon_garde_le_nom_des_salles(planning):
    """`publier_run` n'est encore appelé par aucune route (les deux semestres
    doivent d'abord pouvoir être chargés ensemble), mais il doit rendre des
    placements complets."""
    _, brouillon = planning
    repo = get_repo()

    repo.publier_run(brouillon, {salle.id: salle.label for salle in get_state().rooms})

    publies = repo.db.query(CurrentPlacement).filter_by(run_id=brouillon).all()
    assert len(publies) == 30
    assert {(p.room_id, p.room_label) for p in publies} == {("h007", "H.007")}


def test_aucune_route_ne_publie_encore_un_brouillon():
    """Garde-fou : publier le semestre pair ferait disparaître l'automne de
    l'application (elle ne sert qu'un run) et le sidecar Celcat y verrait des
    séances à supprimer. À lever quand les deux semestres se chargent
    ensemble."""
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1] / "src" / "cal_iut"
    appelants = [
        str(f.relative_to(racine))
        for f in racine.rglob("*.py")
        if "publier_run(" in f.read_text(encoding="utf-8") and f.name != "repository.py"
    ]
    assert appelants == []
