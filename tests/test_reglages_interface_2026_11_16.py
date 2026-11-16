"""Nouveau semestre depuis l'interface — lot 6 (16/11/2026) : réglages du
quotidien saisis à l'écran.

Salles réservées et indisponibilités datées des enseignants : ce qui est
saisi complète les fichiers du dépôt (ajouts et retraits dans le volume
persistant), et tous les chargeurs le voient — serveur, audit, génération.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import main as api
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.ingestion import reglages
from cal_iut.ingestion.config_loader import (
    load_room_reservation_entries,
    load_room_reservations,
    load_teacher_availability,
)

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


@pytest.fixture
def admin(db_isole) -> TestClient:
    api.charger_etat_applicatif()
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def _regles(code: str) -> list[tuple[str, list[int]]]:
    for enseignant in load_teacher_availability(CONFIG):
        if enseignant.teacher_code == code:
            return [(r.date, list(r.slots)) for r in enseignant.forbidden_date_slots]
    return []


# --------------------------------------------------------------------------
# 1. Le magasin et les chargeurs
# --------------------------------------------------------------------------


def test_sans_reglage_saisi_les_chargeurs_lisent_le_depot_tel_quel():
    assert {(e["salle"], e["date"]) for e in load_room_reservation_entries(CONFIG)} >= {("h018", "2026-09-11")}
    assert ("2026-09-03", [1, 2]) in _regles("FLI")


def test_une_reservation_saisie_complete_celles_du_depot():
    avant = load_room_reservation_entries(CONFIG)
    ajout = reglages.ajouter(
        CONFIG, "salles_reservees",
        {"salle": "h018", "date": "2027-02-03", "slots": [4, 3, 3], "motif": "Jury"}, "admin@exemple.fr",
    )
    assert ajout["slots"] == [3, 4] and ajout["demande_par"] == "admin@exemple.fr"
    apres = load_room_reservation_entries(CONFIG)
    assert len(apres) == len(avant) + 1
    assert {"salle": "h018", "date": "2027-02-03", "slots": [3, 4], "motif": "Jury"} in apres
    # Et l'affectation des salles (index de créneaux) la voit aussi.
    calendrier = get_state().calendar or __import__(
        "cal_iut.ingestion.constraints_loader", fromlist=["x"]
    ).load_all_constraints(CONFIG.parents[1]).calendar
    semaine, jour = calendrier.date_to_week_day_any(__import__("datetime").date(2027, 2, 3))
    assert {semaine * 30 + jour * 6 + 3, semaine * 30 + jour * 6 + 4} <= load_room_reservations(CONFIG, calendrier)["h018"]

    assert reglages.retirer(CONFIG, "salles_reservees", ajout["id"], livree=False) is True
    assert load_room_reservation_entries(CONFIG) == avant
    assert reglages.retirer(CONFIG, "salles_reservees", ajout["id"], livree=False) is False


def test_retirer_une_reservation_du_depot_ne_touche_pas_au_fichier():
    contenu = (CONFIG / "salles_reservees.yaml").read_text(encoding="utf-8")
    livree = next(e for e in reglages.reservations(CONFIG, [{"salle": "h018", "date": "2026-09-11", "slots": [1, 2]}]))
    assert livree["origine"] == "livree"
    avant = load_room_reservation_entries(CONFIG)
    assert reglages.retirer(CONFIG, "salles_reservees", livree["cle"], livree=True) is True
    apres = load_room_reservation_entries(CONFIG)
    assert len(apres) == len(avant) - 1
    assert not any(e["salle"] == "h018" and e["date"] == "2026-09-11" and e["slots"] == [1, 2] for e in apres)
    assert (CONFIG / "salles_reservees.yaml").read_text(encoding="utf-8") == contenu


def test_une_indisponibilite_saisie_s_ajoute_a_celles_de_l_enseignant():
    avant = _regles("FLI")
    ajout = reglages.ajouter(
        CONFIG, "indisponibilites",
        {"teacher_code": "FLI", "date": "2027-03-04", "slots": [0, 1, 2], "motif": "Colloque"}, "admin",
    )
    assert _regles("FLI") == [*avant, ("2027-03-04", [0, 1, 2])]
    # Un enseignant absent du fichier du dépôt y gagne une entrée.
    reglages.ajouter(
        CONFIG, "indisponibilites",
        {"teacher_code": "ZZZ", "date": "2027-03-05", "slots": [5], "motif": "Soutenance"}, "admin",
    )
    assert _regles("ZZZ") == [("2027-03-05", [5])]
    # Retirer une règle livrée avec l'application.
    assert reglages.retirer(CONFIG, "indisponibilites", "FLI|2026-09-03|12", livree=True)
    assert _regles("FLI") == [("2027-03-04", [0, 1, 2])]
    assert reglages.retirer(CONFIG, "indisponibilites", ajout["id"], livree=False)
    assert _regles("FLI") == []


@pytest.mark.parametrize(
    "entree, message",
    [
        ({"salle": "h018", "date": "2027-02-30", "slots": [1], "motif": "x"}, "date"),
        ({"salle": "h018", "date": "2027-02-03", "slots": [], "motif": "x"}, "créneau"),
        ({"salle": "h018", "date": "2027-02-03", "slots": [9], "motif": "x"}, "créneau"),
        ({"salle": "h018", "date": "2027-02-03", "slots": [1], "motif": "  "}, "motif"),
    ],
)
def test_une_saisie_incomplete_est_refusee(entree, message):
    with pytest.raises(reglages.ReglageInvalide, match=message):
        reglages.ajouter(CONFIG, "salles_reservees", entree, "admin")
    assert reglages.reservations(CONFIG, []) == []


# --------------------------------------------------------------------------
# 2. Les routes
# --------------------------------------------------------------------------


def test_les_reglages_sont_reserves_aux_administrateurs(db_isole):
    assert TestClient(app).get("/reglages").status_code == 401
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    assert editeur.get("/reglages").status_code == 403
    corps = {"salle": "h018", "date": "2027-02-03", "slots": [1], "motif": "x"}
    assert editeur.post("/reglages/salles-reservees", json=corps).status_code == 403
    assert reglages.reservations(CONFIG, []) == []


def test_reserver_puis_liberer_une_salle_depuis_l_interface(admin):
    depart = admin.get("/reglages").json()
    assert depart["creneaux"][0] == "8h-9h30" and len(depart["creneaux"]) == 6
    assert all(r["origine"] == "livree" for r in depart["salles_reservees"])

    corps = {"salle": "h018", "date": "2027-02-03", "slots": [3, 4], "motif": "Jury de la Direction"}
    reponse = admin.post("/reglages/salles-reservees", json=corps)
    assert reponse.status_code == 201, reponse.text
    ajoutee = next(r for r in reponse.json()["salles_reservees"] if r["origine"] == "ajoutee")
    assert (ajoutee["salle"], ajoutee["date"], ajoutee["slots"]) == ("h018", "2027-02-03", [3, 4])
    assert ajoutee["demande_par"].endswith("@example.test") and ajoutee["salle_libelle"]
    # Appliqué tout de suite au planning en service : affichage et affectation.
    etat = get_state()
    semaine, jour = etat.calendar.date_to_week_day_any(__import__("datetime").date(2027, 2, 3))
    assert semaine * 30 + jour * 6 + 3 in etat.room_reservations["h018"]
    assert corps["motif"] in {r["motif"] for r in load_room_reservation_entries(etat.config_dir)}

    assert admin.delete("/reglages/salles-reservees", params={"cle": ajoutee["cle"]}).status_code == 200
    assert semaine * 30 + jour * 6 + 3 not in get_state().room_reservations.get("h018", set())
    assert admin.delete("/reglages/salles-reservees", params={"cle": ajoutee["cle"]}).status_code == 404

    # Une réservation livrée avec l'application se retire aussi.
    livree = depart["salles_reservees"][0]
    retrait = admin.delete("/reglages/salles-reservees", params={"cle": livree["cle"], "origine": "livree"})
    assert retrait.status_code == 200
    assert livree["cle"] not in {r["cle"] for r in retrait.json()["salles_reservees"]}
    assert admin.delete(
        "/reglages/salles-reservees", params={"cle": livree["cle"], "origine": "livree"}
    ).status_code == 404


def test_une_salle_inconnue_ou_une_saisie_vide_est_refusee(admin):
    base = {"date": "2027-02-03", "slots": [1], "motif": "x"}
    assert admin.post("/reglages/salles-reservees", json={**base, "salle": "nulle-part"}).status_code == 422
    assert admin.post("/reglages/salles-reservees", json={**base, "salle": "h018", "motif": ""}).status_code == 422
    assert admin.post("/reglages/indisponibilites", json={**base, "teacher_code": "../x"}).status_code == 422
    assert reglages.reservations(CONFIG, []) == [] and reglages.indisponibilites_ajoutees(CONFIG) == []


def test_noter_une_indisponibilite_l_applique_au_planning_en_service(admin):
    def _dates(code: str) -> set[str]:
        return {
            r.date for t in get_state().teacher_availability if t.teacher_code == code
            for r in t.forbidden_date_slots
        }

    assert "2027-03-04" not in _dates("FLI")
    reponse = admin.post(
        "/reglages/indisponibilites",
        json={"teacher_code": "FLI", "date": "2027-03-04", "slots": [0, 1, 2], "motif": "Colloque"},
    )
    assert reponse.status_code == 201, reponse.text
    ajoutee = next(r for r in reponse.json()["indisponibilites"] if r["origine"] == "ajoutee")
    assert (ajoutee["teacher_code"], ajoutee["slots"], ajoutee["motif"]) == ("FLI", [0, 1, 2], "Colloque")
    assert "2027-03-04" in _dates("FLI")
    # Les indisponibilités du dépôt sont listées elles aussi.
    assert any(r["origine"] == "livree" and r["teacher_code"] == "FLI" for r in reponse.json()["indisponibilites"])

    assert admin.delete("/reglages/indisponibilites", params={"cle": ajoutee["cle"]}).status_code == 200
    assert "2027-03-04" not in _dates("FLI")
