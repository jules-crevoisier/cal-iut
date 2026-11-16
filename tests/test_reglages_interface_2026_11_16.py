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


# --------------------------------------------------------------------------
# 3. Dates des SAE du prochain semestre
# --------------------------------------------------------------------------


@pytest.fixture
def generations_isolees(tmp_path, monkeypatch):
    from cal_iut.generation import taches

    monkeypatch.setattr(taches, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(taches, "GENERATIONS_DIR", tmp_path / "state" / "generations")
    monkeypatch.setattr(taches, "lancer", lambda generation_id: 4242)


def _fenetres(semestres: list[str]) -> dict[str, list[str]]:
    from cal_iut.ingestion.planning_loader import load_mmi_planning_for_semestres

    bundle = load_mmi_planning_for_semestres(CONFIG.parents[1], semestres)
    return {f.course_codes[0]: [d.isoformat() for d in f.dates] for f in bundle.sae_windows}


def test_des_dates_saisies_valent_des_dates_officielles():
    from cal_iut.ingestion.planning_loader import load_sae_windows

    assert "WS201" not in _fenetres(["S2", "S4", "S6"])
    reglages.definir_dates_sae(CONFIG, "ws201", ["2027-03-09", "2027-03-08", "2027-03-09"], "admin")
    assert _fenetres(["S2", "S4", "S6"])["WS201"] == ["2027-03-08", "2027-03-09"]
    # Avec le parcours et les référents de la SAE, comme une date du fichier.
    fenetre = next(f for f in load_sae_windows(CONFIG.parents[1], ["S2"]) if f.course_codes == ["WS201"])
    assert fenetre.parcours == "BUT1" and fenetre.teachers
    # Le semestre impair ne les voit pas.
    assert "WS201" not in _fenetres(["S1", "S3", "S5"])
    # Une liste vide retire tout.
    assert reglages.definir_dates_sae(CONFIG, "WS201", [], "admin") == []
    assert "WS201" not in _fenetres(["S2", "S4", "S6"])


def test_des_dates_saisies_s_ajoutent_a_celles_du_fichier():
    avant = _fenetres(["S1"])["WS101"]
    reglages.definir_dates_sae(CONFIG, "WS101", ["2026-12-01"], "admin")
    assert _fenetres(["S1"])["WS101"] == sorted([*avant, "2026-12-01"])


def test_l_audit_ne_reclame_plus_les_dates_d_une_sae_saisie_ou_corrigee(admin, generations_isolees):
    def _sans_dates() -> list[str]:
        constats = admin.get("/generations/verification/even").json()["constats"]
        return next((c["details"] for c in constats if c["controle"] == "donnees.sae_sans_dates"), [])

    avant = _sans_dates()
    assert any(d.startswith("WS201 ") for d in avant)
    reglages.definir_dates_sae(CONFIG, "WS201", ["2027-03-08"], "admin")
    apres = _sans_dates()
    assert len(apres) == len(avant) - 1 and not any(d.startswith("WS201 ") for d in apres)
    # Côté impair, WS110 est datée par `sae_corrections.yaml` : plus d'alerte.
    impair = admin.get("/generations/verification/odd").json()["constats"]
    details = next((c["details"] for c in impair if c["controle"] == "donnees.sae_sans_dates"), [])
    assert not any(d.startswith("WS110 ") for d in details)


def test_saisir_les_dates_d_une_sae_depuis_l_ecran_nouveau_semestre(admin, generations_isolees):
    depart = admin.get("/generations/sae/even").json()
    assert depart["verrouille"] is None
    ws201 = next(s for s in depart["sae"] if s["code"] == "WS201")
    assert (ws201["semestre"], ws201["dates_officielles"], ws201["dates_saisies"]) == ("S2", [], [])
    assert ws201["seances"] > 0 and ws201["nom"]
    assert {s["semestre"] for s in depart["sae"]} <= {"S2", "S4", "S6"}

    reponse = admin.put("/generations/sae/even/WS201", json={"dates": ["2027-03-09", "2027-03-08"]})
    assert reponse.status_code == 200, reponse.text
    ws201 = next(s for s in reponse.json()["sae"] if s["code"] == "WS201")
    assert ws201["dates_saisies"] == ["2027-03-08", "2027-03-09"]

    # Un samedi, une date illisible, une SAE d'un autre semestre : refusés, rien n'est écrit.
    assert admin.put("/generations/sae/even/WS201", json={"dates": ["2027-03-13"]}).status_code == 422
    assert admin.put("/generations/sae/even/WS201", json={"dates": ["bientôt"]}).status_code == 422
    assert admin.put("/generations/sae/even/WS101", json={"dates": ["2027-03-08"]}).status_code == 404
    assert admin.put("/generations/sae/tout/WS201", json={"dates": []}).status_code == 422
    assert reglages.dates_sae(CONFIG) == {"WS201": ["2027-03-08", "2027-03-09"]}

    assert admin.put("/generations/sae/even/WS201", json={"dates": []}).status_code == 200
    assert reglages.dates_sae(CONFIG) == {}


def test_les_dates_sae_d_un_semestre_en_service_ne_se_modifient_pas(admin, generations_isolees, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(id=1, semestre="ODD", parcours="MMI"), 3000)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())
    assert "déjà en service" in admin.get("/generations/sae/odd").json()["verrouille"]
    assert admin.put("/generations/sae/odd/WS101", json={"dates": ["2026-12-01"]}).status_code == 409
    assert reglages.dates_sae(CONFIG) == {}
    assert admin.get("/generations/sae/even").json()["verrouille"] is None


# ── Séances annulées ──────────────────────────────────────────────────


def _ids(groupe: str, **kw) -> set[str]:
    import warnings

    from cal_iut.ingestion.pipeline import run_ingestion

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {s.id for s in run_ingestion(CONFIG, semestre_group=groupe, **kw).sessions}


def test_une_seance_annulee_a_l_ecran_disparait_de_l_ingestion():
    from cal_iut.ingestion.config_loader import load_seances_annulees, load_seances_annulees_entries

    cible = "WR203-S2-TD-1-but1-td-ab"
    assert cible in _ids("even")
    reglages.annuler_seance(CONFIG, cible, "Pont de l'Ascension", "admin")
    assert cible in load_seances_annulees(CONFIG)
    assert cible not in _ids("even")
    assert cible in _ids("even", avec_annulees=True)
    entree = next(e for e in load_seances_annulees_entries(CONFIG) if e["session_id"] == cible)
    assert (entree["origine"], entree["motif"], entree["demande_par"]) == ("ajoutee", "Pont de l'Ascension", "admin")

    reglages.retablir_seance(CONFIG, cible, livree=False)
    assert cible in _ids("even")
    with pytest.raises(reglages.ReglageInvalide):
        reglages.annuler_seance(CONFIG, cible, "  ", "admin")


def test_une_annulation_livree_se_retablit_puis_se_remet():
    from cal_iut.ingestion.config_loader import load_seances_annulees

    livree = "WR104-S1-CM-5"
    assert livree in load_seances_annulees(CONFIG)
    reglages.retablir_seance(CONFIG, livree, livree=True)
    assert livree not in load_seances_annulees(CONFIG)
    assert livree in _ids("odd")
    reglages.annuler_seance(CONFIG, livree, "", "admin", livree=True)
    assert livree in load_seances_annulees(CONFIG)


def test_annuler_et_retablir_une_seance_depuis_l_ecran_nouveau_semestre(admin, generations_isolees):
    depart = admin.get("/generations/annulations/even").json()
    assert depart["verrouille"] is None
    assert depart["annulees"] == []
    module = next(m for m in depart["modules"] if m["code"] == "WR203")
    assert module["semestre"] == "S2" and module["seances"] > 0

    seances = admin.get("/generations/annulations/even/seances", params={"code": "WR203"}).json()["seances"]
    assert len(seances) == module["seances"]
    cible = next(s for s in seances if s["id"] == "WR203-S2-TD-1-but1-td-ab")
    assert cible == {"id": "WR203-S2-TD-1-but1-td-ab", "libelle": "TD 1 · TD AB", "annulee": False}

    corps = {"session_id": cible["id"], "motif": "Intervenant indisponible"}
    reponse = admin.post("/generations/annulations/even", json=corps)
    assert reponse.status_code == 201, reponse.text
    (annulee,) = reponse.json()["annulees"]
    assert annulee["libelle"] == "TD 1 · TD AB" and annulee["code"] == "WR203"
    assert annulee["origine"] == "ajoutee" and annulee["existe"] is True
    assert admin.post("/generations/annulations/even", json=corps).status_code == 409
    assert admin.post("/generations/annulations/even", json={"session_id": cible["id"] + "x", "motif": "m"}).status_code == 404
    assert admin.post("/generations/annulations/even", json={"session_id": "WR104-S1-CM-1", "motif": "m"}).status_code == 404
    assert admin.post("/generations/annulations/tout", json=corps).status_code == 422
    autre = next(s["id"] for s in seances if s["id"] != cible["id"])
    assert admin.post("/generations/annulations/even", json={"session_id": autre, "motif": " "}).status_code == 422
    seances = admin.get("/generations/annulations/even/seances", params={"code": "wr203"}).json()["seances"]
    assert next(s for s in seances if s["id"] == cible["id"])["annulee"] is True

    assert admin.delete("/generations/annulations/even", params={"session_id": autre}).status_code == 404
    reponse = admin.delete("/generations/annulations/even", params={"session_id": cible["id"]})
    assert reponse.status_code == 200 and reponse.json()["annulees"] == []
    assert cible["id"] in _ids("even")


def test_les_annulations_d_un_semestre_en_service_ne_se_modifient_pas(admin, generations_isolees, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state
    from cal_iut.ingestion.config_loader import load_seances_annulees

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(id=1, semestre="ODD", parcours="MMI"), 3000)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())

    impair = admin.get("/generations/annulations/odd").json()
    assert "déjà en service" in impair["verrouille"]
    # Les annulations livrées du semestre impair sont listées, avec leur motif.
    assert {a["session_id"] for a in impair["annulees"]} >= {"WR104-S1-CM-5", "WR303D-S3-CM-1"}
    assert all(a["origine"] == "livree" and a["motif"] for a in impair["annulees"])
    avant = load_seances_annulees(CONFIG)
    assert admin.post("/generations/annulations/odd", json={"session_id": "WR104-S1-CM-1", "motif": "m"}).status_code == 409
    assert admin.delete("/generations/annulations/odd", params={"session_id": "WR104-S1-CM-5"}).status_code == 409
    assert load_seances_annulees(CONFIG) == avant


# ── Règles de modules : séances longues et périodes ───────────────────


def _seances(groupe: str, code: str) -> list:
    import warnings

    from cal_iut.ingestion.pipeline import run_ingestion

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return [s for s in run_ingestion(CONFIG, semestre_group=groupe).sessions if s.course_code == code]


def test_des_seances_longues_saisies_a_l_ecran_fusionnent_les_seances():
    from cal_iut.ingestion.config_loader import load_double_sessions

    avant = [s for s in _seances("even", "WR203") if s.session_type.value == "TD"]
    assert avant and all(s.duration_slots == 1 for s in avant)
    livrees = len(load_double_sessions(CONFIG))

    regle = reglages.ajouter_regle_de_module(
        CONFIG, "doubles_seances",
        {"course_code": "WR203", "session_type": "td", "slots_per_session": 2, "motif": "TD de 3 h demandés"}, "admin",
    )
    assert len(load_double_sessions(CONFIG)) == livrees + 1
    apres = [s for s in _seances("even", "WR203") if s.session_type.value == "TD"]
    assert len(apres) == len(avant) // 2 and all(s.duration_slots == 2 for s in apres)

    assert reglages.retirer_regle_de_module(CONFIG, "doubles_seances", regle["id"]) is True
    assert len(load_double_sessions(CONFIG)) == livrees
    for mauvaise in (
        {"course_code": "WR203", "session_type": "TD", "slots_per_session": 5, "motif": "m"},
        {"course_code": "WR203", "session_type": "XX", "slots_per_session": 2, "motif": "m"},
        {"course_code": "WR203", "session_type": "TD", "slots_per_session": 2, "motif": " "},
        {"course_code": "", "session_type": "TD", "slots_per_session": 2, "motif": "m"},
    ):
        with pytest.raises(reglages.ReglageInvalide):
            reglages.ajouter_regle_de_module(CONFIG, "doubles_seances", mauvaise, "admin")


def test_une_periode_saisie_a_l_ecran_devient_une_fenetre_de_dates():
    from cal_iut.ingestion.config_loader import load_session_date_windows

    livrees = load_session_date_windows(CONFIG)
    reglages.ajouter_regle_de_module(
        CONFIG, "periodes_modules",
        {"course_code": "WR203", "semestre": "S2", "session_type": None, "debut": "2027-03-01", "fin": None, "motif": "Après les vacances"},
        "admin",
    )
    toutes = load_session_date_windows(CONFIG)
    assert len(toutes) == len(livrees) + 1
    assert load_session_date_windows(CONFIG, avec_saisies=False) == livrees
    regle = toutes[-1]
    assert (regle.course_code, regle.semestre, regle.session_type) == ("WR203", "S2", None)
    assert (regle.start_date, regle.end_date, regle.note) == ("2027-03-01", None, "Après les vacances")
    for mauvaise in (
        {"course_code": "WR203", "semestre": "S2", "motif": "m"},
        {"course_code": "WR203", "semestre": "S2", "debut": "2027-04-01", "fin": "2027-03-01", "motif": "m"},
        {"course_code": "WR203", "semestre": "S2", "debut": "bientôt", "motif": "m"},
    ):
        with pytest.raises(reglages.ReglageInvalide):
            reglages.ajouter_regle_de_module(CONFIG, "periodes_modules", mauvaise, "admin")


def test_regler_les_modules_depuis_l_ecran_nouveau_semestre(admin, generations_isolees):
    depart = admin.get("/generations/regles/even").json()
    assert depart["verrouille"] is None
    assert depart["seances_longues"] == [] and depart["periodes"] == []
    module = next(m for m in depart["modules"] if m["code"] == "WR203")
    assert module["semestre"] == "S2" and module["types"]["TD"] >= 2

    corps = {"code": "WR203", "type": "TD", "creneaux": 2, "motif": "TD de 3 h demandés"}
    reponse = admin.post("/generations/regles/even/seances-longues", json=corps)
    assert reponse.status_code == 201, reponse.text
    (longue,) = reponse.json()["seances_longues"]
    assert (longue["code"], longue["type"], longue["duree"], longue["origine"]) == ("WR203", "TD", "3 h", "ajoutee")
    assert admin.post("/generations/regles/even/seances-longues", json=corps).status_code == 409
    assert admin.post("/generations/regles/even/seances-longues", json={**corps, "code": "WR104"}).status_code == 404
    assert admin.post("/generations/regles/even/seances-longues", json={**corps, "type": "TP"}).status_code == 422
    assert admin.post("/generations/regles/even/seances-longues", json={**corps, "type": "CM", "motif": ""}).status_code == 422

    periode = {"code": "WR203", "type": None, "debut": "2027-03-01", "fin": "2027-04-02", "motif": "Après les vacances"}
    reponse = admin.post("/generations/regles/even/periodes", json=periode)
    assert reponse.status_code == 201, reponse.text
    (saisie,) = reponse.json()["periodes"]
    assert (saisie["debut"], saisie["fin"], saisie["type"], saisie["origine"]) == ("2027-03-01", "2027-04-02", None, "ajoutee")
    assert admin.post("/generations/regles/even/periodes", json={**periode, "debut": None, "fin": None}).status_code == 422
    assert admin.post("/generations/regles/even/periodes", json={**periode, "type": "TP"}).status_code == 422
    assert admin.post("/generations/regles/even/periodes", json={**periode, "code": "WR104"}).status_code == 404

    assert admin.delete(f"/generations/regles/even/periodes/{longue['id']}").status_code == 404
    assert admin.delete(f"/generations/regles/even/autre/{longue['id']}").status_code == 404
    assert admin.delete(f"/generations/regles/even/periodes/{saisie['id']}").status_code == 200
    reponse = admin.delete(f"/generations/regles/even/seances-longues/{longue['id']}")
    assert reponse.status_code == 200
    assert reponse.json()["seances_longues"] == [] and reponse.json()["periodes"] == []


def test_les_regles_d_un_semestre_en_service_ne_se_modifient_pas(admin, generations_isolees, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(id=1, semestre="ODD", parcours="MMI"), 3000)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())
    impair = admin.get("/generations/regles/odd").json()
    assert "déjà en service" in impair["verrouille"]
    # Les règles livrées du semestre impair sont listées, sans pouvoir être retirées.
    assert {(r["code"], r["type"]) for r in impair["seances_longues"]} >= {("WR110", "TP"), ("WR104", "TD")}
    assert {r["code"] for r in impair["periodes"]} >= {"WR100BU", "WR308D"}
    assert all(r["id"] is None and r["origine"] == "livree" for r in impair["seances_longues"] + impair["periodes"])
    corps = {"code": "WR119", "type": "TD", "creneaux": 2, "motif": "m"}
    assert admin.post("/generations/regles/odd/seances-longues", json=corps).status_code == 409
    assert admin.post("/generations/regles/odd/periodes", json={"code": "WR119", "debut": "2026-10-01", "motif": "m"}).status_code == 409
    assert reglages.regles_de_modules(CONFIG, "doubles_seances") == []
