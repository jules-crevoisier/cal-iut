"""Les deux groupes de semestres servis ensemble (lot 3, 16/11/2026).

Décision de Jules : « Les deux semestres ensemble ». Dès que S1/S3/S5 ET
S2/S4/S6 ont un planning en service, chacun est restauré dans son état :
celui du semestre en cours reste le planning servi par défaut (Celcat,
tâches de fond), l'autre se choisit avec l'en-tête `X-Semestre-Groupe`, et
les agendas .ics réunissent les deux.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import main, semestres_charges
from cal_iut.api import state as etats
from cal_iut.api.main import app, charger_etat_applicatif
from cal_iut.api.state import get_repo, get_state
from cal_iut.celcat import file_attente
from cal_iut.db.models import CurrentPlacement
from cal_iut.ingestion.pipeline import run_ingestion

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")

PAIR = {"X-Semestre-Groupe": "even"}


def _placements(seances, premiere_semaine: int) -> list[dict[str, object]]:
    return [
        {
            "session_id": s.id, "week": premiere_semaine + i // 20, "day": (i // 4) % 5, "slot": i % 4,
            "course_code": s.course_code, "group_ids": s.group_ids, "teacher_codes": s.teacher_codes,
            "room_id": "h007", "room_label": "H.007",
        }
        for i, s in enumerate(seances)
    ]


def _enregistrer(groupe: str, nombre: int) -> int:
    etat = etats.etat_principal()
    lignes = _placements(run_ingestion(etat.config_dir, semestre_group=groupe).sessions[:nombre], 2)
    run = get_repo().save_run(
        parcours="MMI", semestre=groupe.upper(), status="FEASIBLE", objective_value=1, gap_penalty=0, weeks=24,
        solver_placements=lignes, current_placements=lignes,
    )
    return run.id


@pytest.fixture
def base(db_isole):
    """Une base isolée, et l'état principal remis comme il était à la fin."""
    etat = etats.etat_principal()
    avant = dataclasses.replace(etat)
    charger_etat_applicatif()
    yield
    etats.definir_secondaires({})
    for champ in dataclasses.fields(avant):
        setattr(etat, champ.name, getattr(avant, champ.name))


@pytest.fixture
def deux_semestres(base):
    """Un automne (40 séances) et un printemps (30 séances) en service.
    Rend `(run impair, run pair)`. Le printemps est enregistré en DERNIER :
    c'est lui que l'ancienne restauration aurait servi à tout le monde."""
    impair = _enregistrer("odd", 40)
    pair = _enregistrer("even", 30)
    charger_etat_applicatif()
    return impair, pair


@pytest.fixture
def client(deux_semestres) -> TestClient:
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="admin")
    return c


def test_un_seul_semestre_en_service_rien_ne_change(base):
    run = _enregistrer("odd", 40)

    charger_etat_applicatif()

    etat = get_state()
    assert (etat.semestre_group, etat.current_run_id, len(etat.timetable)) == ("odd", run, 40)
    assert etats.groupes_charges() == ["odd"]
    assert len(etats.etats_charges()) == 1
    assert etats.groupe_actif() == ""


def test_le_semestre_en_cours_reste_le_planning_par_defaut(deux_semestres):
    impair, pair = deux_semestres

    etat = get_state()

    # 1er septembre 2026 : l'automne, bien que le printemps soit plus récent.
    assert (etat.semestre_group, etat.current_run_id, len(etat.timetable)) == ("odd", impair, 40)
    assert etats.groupes_charges() == ["odd", "even"]
    with etats.pour_le_groupe("even"):
        autre = get_state()
        assert (autre.semestre_group, autre.current_run_id, len(autre.timetable)) == ("even", pair, 30)
        assert etats.groupe_actif() == "even"
    assert get_state() is etat


def test_a_partir_de_fevrier_le_printemps_devient_le_planning_par_defaut(deux_semestres, monkeypatch):
    impair, pair = deux_semestres
    monkeypatch.setattr(main, "_today", lambda: date(2027, 2, 3))

    charger_etat_applicatif()

    assert (get_state().semestre_group, get_state().current_run_id) == ("even", pair)
    assert etats.groupes_charges() == ["even", "odd"]
    with etats.pour_le_groupe("odd"):
        assert get_state().current_run_id == impair


def test_groupe_en_cours_avant_la_rentree():
    calendrier = etats.etat_principal().calendar
    assert semestres_charges.groupe_en_cours(["even", "odd"], calendrier, date(2026, 8, 1)) == "odd"
    assert semestres_charges.groupe_en_cours(["odd", "even"], calendrier, date(2027, 1, 31)) == "odd"
    assert semestres_charges.groupe_en_cours(["odd", "even"], calendrier, date(2027, 2, 1)) == "even"


def test_l_en_tete_choisit_le_semestre_affiche(client, deux_semestres):
    defaut = client.get("/app-state").json()
    printemps = client.get("/app-state", headers=PAIR).json()
    automne = client.get("/app-state", headers={"X-Semestre-Groupe": "odd"}).json()

    assert (defaut["semestreGroupe"], len(defaut["rows"])) == ("odd", 40)
    assert (printemps["semestreGroupe"], len(printemps["rows"])) == ("even", 30)
    assert automne["rows"] == defaut["rows"]
    assert {r["id"] for r in printemps["rows"]}.isdisjoint({r["id"] for r in defaut["rows"]})
    assert defaut["semestresCharges"] == printemps["semestresCharges"] == [
        {"groupe": "odd", "libelle": "Semestre impair", "semestres": ["S1", "S3", "S5"], "principal": True},
        {"groupe": "even", "libelle": "Semestre pair", "semestres": ["S2", "S4", "S6"], "principal": False},
    ]
    # Le printemps est daté à partir de février, l'automne de septembre.
    assert defaut["weekDates"][0].startswith("2026-08-31")
    assert printemps["weekDates"][0].startswith("2027-02-01")
    # Le cache ne mélange pas les deux : même révision, deux réponses.
    assert client.get("/app-state").json()["semestreGroupe"] == "odd"
    assert client.get("/timetable", headers=PAIR).json() != client.get("/timetable").json()


def test_un_groupe_inconnu_sert_le_planning_par_defaut(client):
    assert client.get("/app-state", headers={"X-Semestre-Groupe": "nimporte"}).json()["semestreGroupe"] == "odd"


def test_deplacer_une_seance_du_printemps_ne_touche_pas_l_automne(client, deux_semestres, monkeypatch):
    impair, pair = deux_semestres
    enfiles: list[dict] = []
    monkeypatch.setattr(file_attente, "_poser", lambda job: enfiles.append(job) or True)
    with etats.pour_le_groupe("even"):
        cible = get_state().timetable[0].session_id
    automne_avant = sorted(
        (c.session_id, c.week, c.day, c.slot) for c in get_repo().db.query(CurrentPlacement).filter_by(run_id=impair)
    )

    reponse = client.patch(
        f"/placements/{cible}", json={"week": 9, "day": 4, "slot": 3, "force": True}, headers=PAIR
    )

    assert reponse.status_code == 200, reponse.text
    get_repo().db.expire_all()
    ligne = get_repo().db.query(CurrentPlacement).filter_by(session_id=cible).one()
    assert (ligne.run_id, ligne.week, ligne.day, ligne.slot) == (pair, 9, 4, 3)
    assert automne_avant == sorted(
        (c.session_id, c.week, c.day, c.slot) for c in get_repo().db.query(CurrentPlacement).filter_by(run_id=impair)
    )
    with etats.pour_le_groupe("even"):
        deplacee = next(p for p in get_state().timetable if p.session_id == cible)
        assert (deplacee.week, deplacee.day, deplacee.slot) == (9, 4, 3)
    assert all(p.session_id != cible for p in get_state().timetable)
    # Rien ne part vers Celcat depuis le semestre qui n'est pas en cours.
    assert enfiles == []


def test_rien_ne_part_vers_celcat_depuis_le_semestre_secondaire(deux_semestres, monkeypatch):
    poses: list[dict] = []
    monkeypatch.setattr(file_attente, "_migrer", lambda: None)
    monkeypatch.setattr(file_attente, "_poser", lambda job: poses.append(job) or True)

    with etats.pour_le_groupe("even"):
        assert file_attente.enfiler({"action": "delete", "session_id": "x"}) is False
    assert file_attente.enfiler({"action": "create", "session_id": "y"}) is True

    assert [j["action"] for j in poses] == ["create"]


def test_les_agendas_reunissent_les_deux_semestres(client, deux_semestres):
    with etats.pour_le_groupe("even"):
        printemps = get_state()
        code = next(c for p in printemps.timetable for c in p.teacher_codes or [])
        attendu_printemps = sum(1 for p in printemps.timetable if code in (p.teacher_codes or []))
    attendu_automne = sum(1 for p in get_state().timetable if code in (p.teacher_codes or []))

    ics = client.get(f"/ics/prof/{code}.ics").text

    assert ics.count("BEGIN:VEVENT") >= attendu_printemps + attendu_automne
    assert "DTSTART;TZID=Europe/Paris:202702" in ics or "DTSTART:202702" in ics
    codes = {e["code"] for e in client.get("/ics/version").json()["enseignants"]}
    assert code in codes


def test_ce_qui_est_commun_suit_d_un_etat_a_l_autre(deux_semestres):
    with etats.pour_le_groupe("even"):
        printemps = get_state()
        printemps.rooms = [*printemps.rooms][:3]
        etats.synchroniser_le_commun()
    automne = get_state()
    assert automne.rooms is printemps.rooms
    assert (len(automne.timetable), len(printemps.timetable)) == (40, 30)


# ── Celcat : chaque semestre ne répond que de ses évènements ────────────


def _evenement(groupe: str, event_id: int, semaine: int = 5) -> dict:
    return {
        "event_id": event_id, "semaine": semaine, "module": "WR999 Module", "groupe": groupe,
        "jour": 0, "heure_debut": "08:00", "salle": "H.007",
    }


def test_un_evenement_celcat_de_l_autre_semestre_n_est_pas_en_trop(deux_semestres):
    from cal_iut.celcat import planification

    automne = get_state()
    evenements = [_evenement("BUT MMI S2 TD AB", 1), _evenement("BUT MMI S1 TD AB", 2), _evenement("Réunion", 3)]

    gardes = planification.evenements_du_planning(automne, evenements)
    lignes = planification.lignes(automne, semaine=30, semaine_celcat=5, evenements=evenements)

    assert [e["event_id"] for e in gardes] == [2, 3]
    # Semaine 30 : aucune séance de l'automne. Le cours de S2 n'est pas
    # proposé à la suppression ; celui de S1, si.
    assert sorted(l["celcat"]["event_id"] for l in lignes if l["statut"] == "en_trop_celcat") == [2, 3]


def test_le_semestre_pair_n_est_ni_compare_ni_envoye_a_celcat(deux_semestres, monkeypatch):
    from cal_iut.celcat import planification

    monkeypatch.setattr(main, "_today", lambda: date(2027, 2, 3))
    charger_etat_applicatif()
    printemps = get_state()
    assert printemps.semestre_group == "even"
    poses: list[dict] = []
    monkeypatch.setattr(file_attente, "_migrer", lambda: None)
    monkeypatch.setattr(file_attente, "_poser", lambda job: poses.append(job) or True)

    assert planification.comparaison_prise_en_charge(printemps) is False
    assert planification.lignes(
        printemps, semaine=2, semaine_celcat=5, evenements=[_evenement("BUT MMI S1 TD AB", 2)]
    ) == []
    assert file_attente.enfiler({"action": "delete", "session_id": "x", "event_id": 2}) is False
    assert poses == []


def test_l_automne_reste_compare_et_envoye_comme_avant(deux_semestres, monkeypatch):
    from cal_iut.celcat import planification

    poses: list[dict] = []
    monkeypatch.setattr(file_attente, "_migrer", lambda: None)
    monkeypatch.setattr(file_attente, "_poser", lambda job: poses.append(job) or True)

    assert planification.comparaison_prise_en_charge(get_state()) is True
    assert file_attente.enfiler({"action": "create", "session_id": "y"}) is True
    assert len(poses) == 1
