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


# ── Début et fin des cours du semestre ────────────────────────────────


def test_sans_saisie_les_dates_des_semestres_ne_changent_pas():
    from datetime import date

    from cal_iut.calendar.academic import (
        build_default_calendar_2026_2027,
        default_horizon_weeks,
        periode_des_cours,
        semester_week_offset,
    )

    calendrier = build_default_calendar_2026_2027()
    assert calendrier.periodes == {}
    assert (semester_week_offset(calendrier, "S1"), default_horizon_weeks(calendrier, "S1")) == (0, 19)
    assert (semester_week_offset(calendrier, "S2"), default_horizon_weeks(calendrier, "S4")) == (19, 19)
    assert calendrier.teaching_mondays[19] == date(2027, 2, 1)
    assert periode_des_cours(calendrier, "even") == (date(2027, 2, 1), date(2027, 6, 30))
    # Les dates d'origine décrivent bien l'horizon d'origine.
    debut, fin = periode_des_cours(calendrier, "odd")
    assert calendrier.date_to_week_day_any(fin)[0] - calendrier.date_to_week_day_any(debut)[0] + 1 == 19


def test_les_dates_saisies_deplacent_le_debut_et_l_horizon_du_semestre():
    from datetime import date

    from cal_iut.calendar.academic import build_default_calendar_2026_2027, default_horizon_weeks, semester_week_offset
    from cal_iut.generation import verification

    reglages.definir_dates_semestre(CONFIG, "even", "2027-01-04", "2027-06-11", "admin")
    calendrier = build_default_calendar_2026_2027()
    assert calendrier.periodes == {"even": (date(2027, 1, 4), date(2027, 6, 11))}
    assert semester_week_offset(calendrier, "S2") == semester_week_offset(calendrier, "S6") == 15
    # Du 4 janvier (index 15) à la semaine du 7 juin (index 34) : 20 semaines.
    assert default_horizon_weeks(calendrier, "S2") == 20
    assert verification.horizon(CONFIG.parents[1], "even") == 20
    # L'impair n'a pas bougé.
    assert (semester_week_offset(calendrier, "S1"), default_horizon_weeks(calendrier, "S3")) == (0, 19)

    reglages.definir_dates_semestre(CONFIG, "even", None, None, "admin")
    assert build_default_calendar_2026_2027().periodes == {}
    for debut, fin in (("2027-02-01", None), ("2027-06-01", "2027-02-01"), ("bientôt", "2027-06-01")):
        with pytest.raises(reglages.ReglageInvalide):
            reglages.definir_dates_semestre(CONFIG, "even", debut, fin, "admin")


def test_regler_les_dates_du_semestre_depuis_l_ecran_nouveau_semestre(admin, generations_isolees):
    from cal_iut.api.state import get_state

    depart = admin.get("/generations/periode/even").json()
    assert depart["verrouille"] is None and depart["personnalise"] is False
    assert (depart["debut"], depart["fin"], depart["semaines"]) == ("2027-02-01", "2027-06-30", 19)
    assert depart["vacances"] == [
        {"debut": "2027-02-22", "fin": "2027-02-26"},
        {"debut": "2027-04-19", "fin": "2027-04-30"},
    ]
    assert depart["autre"] == {"libelle": "Semestre impair", "debut": "2026-08-31", "fin": "2027-01-29", "chevauche": False}

    reponse = admin.put("/generations/periode/even", json={"debut": "2027-01-04", "fin": "2027-06-11"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["debut"], corps["fin"], corps["semaines"], corps["personnalise"]) == ("2027-01-04", "2027-06-11", 20, True)
    assert corps["autre"]["chevauche"] is True
    assert corps["origine"] == {"debut": "2027-02-01", "fin": "2027-06-30", "fin_alternants": None}
    # Le serveur lit les nouvelles dates sans redémarrage.
    assert "even" in get_state().calendar.periodes

    for debut, fin in (
        ("2027-02-06", "2027-06-11"),  # samedi
        ("2027-02-22", "2027-06-11"),  # vacances d'hiver
        ("2027-02-01", "2027-08-02"),  # hors de l'année
        ("2027-06-11", "2027-02-01"),
        ("2027-02-01", "2027-02-12"),  # deux semaines
        ("bientôt", "2027-06-11"),
    ):
        assert admin.put("/generations/periode/even", json={"debut": debut, "fin": fin}).status_code == 422, (debut, fin)
    assert admin.put("/generations/periode/tout", json={"debut": "2027-02-01", "fin": "2027-06-11"}).status_code == 422

    reponse = admin.delete("/generations/periode/even")
    assert reponse.status_code == 200 and reponse.json()["personnalise"] is False
    assert get_state().calendar.periodes == {}


def test_les_dates_d_un_semestre_en_service_ne_se_modifient_pas(admin, generations_isolees, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(id=1, semestre="ODD", parcours="MMI"), 3000)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())
    assert "déjà en service" in admin.get("/generations/periode/odd").json()["verrouille"]
    assert admin.put("/generations/periode/odd", json={"debut": "2026-09-07", "fin": "2027-01-29"}).status_code == 409
    assert admin.delete("/generations/periode/odd").status_code == 409
    assert reglages.dates_semestres(CONFIG) == {}


# ── Enseignants d'un module : répartition, ordre, duos ────────────────


def _enseignants_par_rang(code: str, type_: str) -> list[tuple[int, str, str]]:
    from cal_iut.ingestion.pipeline import run_ingestion

    seances = run_ingestion(CONFIG, semestre_group="even").sessions
    return sorted(
        (s.sequence_order, ",".join(s.group_ids), ",".join(s.teacher_codes))
        for s in seances
        if s.course_code == code and s.session_type.value == type_
    )


def test_repartition_ordre_et_duo_se_saisissent_a_l_ecran(admin, generations_isolees):
    from cal_iut.ingestion.config_loader import (
        load_course_teacher_orders,
        load_teacher_distributions,
        load_teacher_duos,
    )

    depart = admin.get("/generations/regles/even").json()
    module = next(m for m in depart["modules"] if m["code"] == "WR208")
    assert {e["code"] for e in module["enseignants"]} == {"ALO", "GLE"}
    assert module["groupes_tp"] == list("ABCDEFGH")
    assert depart["repartitions"] == [] and depart["ordres"] == [] and depart["duos"] == []
    assert {s["id"] for s in depart["salles"]} >= {"h017", "h022", "h201", "h203"}
    avant = _enseignants_par_rang("WR208", "TP")

    # Répartition
    rep = {"code": "WR208", "type": "TP", "mode": "alterne", "ordre": ["GLE", "ALO"], "motif": "Demande des enseignants"}
    reponse = admin.post("/generations/regles/even/repartitions", json=rep)
    assert reponse.status_code == 201, reponse.text
    saisie = reponse.json()["repartitions"][0]
    assert saisie["origine"] == "ajoutee" and saisie["id"] and saisie["libelle"].startswith("À tour de rôle")
    assert [e["code"] for e in saisie["ordre"]] == ["GLE", "ALO"]
    regle = next(r for r in load_teacher_distributions(CONFIG) if r.course_code == "WR208")
    assert (regle.mode, regle.semestre, regle.session_type.value, regle.teacher_order) == ("alterne", "S2", "TP", ["GLE", "ALO"])
    apres = _enseignants_par_rang("WR208", "TP")
    assert apres != avant and len(apres) == len(avant)
    assert admin.post("/generations/regles/even/repartitions", json=rep).status_code == 409
    assert admin.post("/generations/regles/even/repartitions", json={**rep, "type": None}).status_code == 409
    assert admin.post("/generations/regles/even/repartitions", json={**rep, "code": "WR201"}).status_code == 422
    assert admin.post("/generations/regles/even/repartitions", json={**rep, "code": "WR104"}).status_code == 404
    assert admin.delete(f"/generations/regles/even/repartitions/{saisie['id']}").status_code == 200
    assert _enseignants_par_rang("WR208", "TP") == avant
    for refus in ({"mode": "au hasard"}, {"type": "CM"}, {"motif": ""}, {"ordre": ["ZZZ"]}):
        assert admin.post("/generations/regles/even/repartitions", json={**rep, **refus}).status_code == 422, refus

    # Ordre dans le semestre
    ordre = {"code": "WR208", "ordre": ["ALO", "GLE"], "motif": "Les bases d'abord"}
    reponse = admin.post("/generations/regles/even/ordres", json=ordre)
    assert reponse.status_code == 201, reponse.text
    saisie = reponse.json()["ordres"][0]
    assert [e["code"] for e in saisie["ordre"]] == ["ALO", "GLE"] and saisie["ordre"][0]["nom"] != "ALO"
    assert [r.teacher_order for r in load_course_teacher_orders(CONFIG) if r.course_code == "WR208"] == [["ALO", "GLE"]]
    assert admin.post("/generations/regles/even/ordres", json=ordre).status_code == 409
    assert admin.delete(f"/generations/regles/even/ordres/{saisie['id']}").status_code == 200
    assert admin.post("/generations/regles/even/ordres", json={**ordre, "ordre": ["ALO", "ALO"]}).status_code == 422
    assert admin.post("/generations/regles/even/ordres", json={**ordre, "ordre": ["ALO", "ZZZ"]}).status_code == 422

    # Duo en salles voisines
    duo = {
        "code": "WR208", "enseignants": ["ALO", "GLE"], "salles": ["h201", "h203"],
        "groupes": {"ALO": ["A", "C"], "GLE": ["B", "D"]}, "motif": "Atelier commun",
    }
    reponse = admin.post("/generations/regles/even/duos", json=duo)
    assert reponse.status_code == 201, reponse.text
    saisie = reponse.json()["duos"][0]
    assert saisie["groupes"] == {"ALO": ["A", "C"], "GLE": ["B", "D"]}
    assert [s["label"] for s in saisie["salles"]] == ["H.201", "H.203"]
    charge = next(d for d in load_teacher_duos(CONFIG) if "WR208" in d.course_codes)
    assert charge.teacher_codes == ("ALO", "GLE") and charge.rare_rooms == ("h201", "h203")
    tp = {groupes: qui for _, groupes, qui in _enseignants_par_rang("WR208", "TP")}
    assert tp["but1-tp-a"] == tp["but1-tp-c"] == "ALO" and tp["but1-tp-b"] == tp["but1-tp-d"] == "GLE"
    assert admin.post("/generations/regles/even/duos", json=duo).status_code == 409
    assert admin.delete(f"/generations/regles/even/duos/{saisie['id']}").status_code == 200
    for refus in (
        {"salles": ["h201", "h201"]}, {"salles": ["h201", "nulle-part"]}, {"enseignants": ["ALO", "ALO"]},
        {"groupes": {"ALO": ["A"], "GLE": ["A"]}}, {"groupes": {"ALO": ["Z"], "GLE": ["B"]}}, {"code": "WR203"},
    ):
        assert admin.post("/generations/regles/even/duos", json={**duo, **refus}).status_code == 422, refus
    assert reglages.regles_de_modules(CONFIG, "duos") == []


def test_les_enseignants_d_un_semestre_en_service_ne_se_reglent_pas(admin, generations_isolees, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(id=1, semestre="ODD", parcours="MMI"), 3000)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())
    assert admin.get("/generations/regles/odd").json()["duos"]
    for chemin, corps in (
        ("repartitions", {"code": "WR108", "mode": "alterne", "motif": "m"}),
        ("ordres", {"code": "WR108", "ordre": ["ALO", "GLE"], "motif": "m"}),
        ("duos", {"code": "WR108", "enseignants": ["ALO", "GLE"], "salles": ["h201", "h203"], "motif": "m"}),
    ):
        assert admin.post(f"/generations/regles/odd/{chemin}", json=corps).status_code == 409, chemin


# ── Fin des cours des alternants, réglages du calcul ──────────────────


def test_l_horizon_du_calcul_se_deduit_des_dates(admin, generations_isolees):
    from cal_iut.generation import taches

    # Dates d'origine : exactement la recette d'avant (24 semaines, FI jusqu'à la 18).
    impair = admin.get("/generations/periode/odd").json()
    assert (impair["fin_alternants"], impair["semaines"], impair["semaines_alternants"]) == ("2027-03-12", 19, 24)
    assert impair["origine"]["fin_alternants"] == "2027-03-12"
    origine = taches.parametres_par_defaut("odd")
    assert (origine["weeks"], origine["fi_max_week"]) == (24, 18)
    pair = taches.parametres_par_defaut("even")
    assert (pair["weeks"], pair["fi_max_week"]) == (None, None)

    # Les alternants du pair finissent deux semaines après les autres.
    dates = {"debut": "2027-02-01", "fin": "2027-06-11"}
    reponse = admin.put("/generations/periode/even", json={**dates, "fin_alternants": "2027-06-25"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["fin_alternants"], corps["semaines"], corps["semaines_alternants"]) == ("2027-06-25", 16, 18)
    pair = taches.parametres_par_defaut("even")
    assert (pair["weeks"], pair["fi_max_week"]) == (18, 15)
    # Sans le champ, la date des alternants ne bouge pas.
    assert admin.put("/generations/periode/even", json=dates).json()["fin_alternants"] == "2027-06-25"
    for mauvaise in ("2027-06-11", "2027-06-26", "2027-04-20", "un jour"):
        refus = admin.put("/generations/periode/even", json={**dates, "fin_alternants": mauvaise})
        assert refus.status_code == 422, mauvaise
    # Vide : ils finissent avec les autres.
    corps = admin.put("/generations/periode/even", json={**dates, "fin_alternants": None}).json()
    assert (corps["fin_alternants"], corps["semaines_alternants"], corps["personnalise"]) == (None, None, True)
    corps = admin.delete("/generations/periode/even").json()
    assert (corps["fin_alternants"], corps["personnalise"]) == (None, False)


def test_les_reglages_du_calcul_sont_retenus_pour_la_fois_suivante(admin, generations_isolees):
    from cal_iut.generation import taches

    accueil = admin.get("/generations").json()
    pair = next(g for g in accueil["groupes"] if g["cle"] == "even")
    assert pair["parametres"] == pair["parametres_d_origine"]
    assert pair["parametres"]["referent_sae_strict"] is False and pair["parametres"]["spread_weight"] == 8

    choix = {"semestre_group": "even", "tentatives": 3, "spread_weight": 12, "arret_si_complet": False}
    reponse = admin.post("/generations", json=choix)
    assert reponse.status_code == 201, reponse.text
    lances = reponse.json()["parametres"]
    assert (lances["tentatives"], lances["spread_weight"], lances["arret_si_complet"]) == (3, 12, False)
    retenus = taches.parametres_par_defaut("even")
    assert (retenus["tentatives"], retenus["spread_weight"], retenus["arret_si_complet"], retenus["heures"]) == (3, 12, False, 4.0)
    # L'autre semestre garde ses réglages, et l'origine reste connue.
    assert taches.parametres_par_defaut("odd")["tentatives"] == 6
    assert taches.parametres_d_origine("even")["tentatives"] == 6
    assert reglages.parametres_calcul(CONFIG)["even"] == {"tentatives": 3, "spread_weight": 12, "arret_si_complet": False}
    with pytest.raises(ValueError):
        taches.valider_parametres({"semestre_group": "even", "spread_weight": 500})


def test_le_referent_de_sae_strict_est_un_choix_du_lancement(tmp_path, monkeypatch):
    from cal_iut.generation import ouvrier

    commandes: list[list[str]] = []

    class _Processus:
        pid = 1

        def wait(self, *a, **k):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(ouvrier.subprocess, "Popen", lambda commande, **k: commandes.append(commande) or _Processus())
    for strict in (False, True):
        o = ouvrier.Ouvrier.__new__(ouvrier.Ouvrier)
        o.dossier, o.groupe = tmp_path, "even"
        o.params = {"spread_weight": 8, "num_workers": 1, "weeks": None, "fi_max_week": None, "referent_sae_strict": strict}
        try:
            o._lancer_solveur(1, tmp_path / "sortie.json")
        except Exception:  # noqa: BLE001 — seule la commande construite nous intéresse
            pass
    assert "--no-sae-supervisor-hard" in commandes[0]
    assert "--no-sae-supervisor-hard" not in commandes[1]


# ── Semaine type d'un enseignant ──────────────────────────────────────


def _semaine(admin, code: str) -> dict:
    return next((s for s in admin.get("/reglages").json()["semaines_types"] if s["teacher_code"] == code), None)


def test_la_semaine_type_d_un_enseignant_se_regle_a_l_ecran(admin):
    etat = get_state()
    depart = admin.get("/reglages").json()
    assert depart["jours"] == ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
    # Kyllian Bresson : jamais à 8 h, c'est dans le fichier livré.
    kbr = _semaine(admin, "KBR")
    assert [0, 0] in kbr["origine"] and kbr["bloques"] == [] and kbr["liberes"] == [] and kbr["fixes"] == []

    # On lui rend le lundi 8 h et on lui retire le vendredi après-midi.
    voulue = [c for c in kbr["origine"] if c != [0, 0]] + [[4, 3], [4, 4], [4, 5]]
    assert admin.put("/reglages/semaines-types/KBR", json={"indisponibles": voulue}).status_code == 422  # motif
    reponse = admin.put("/reglages/semaines-types/KBR", json={"indisponibles": voulue, "motif": "Demande du 17/11"})
    assert reponse.status_code == 200, reponse.text
    kbr = next(s for s in reponse.json()["semaines_types"] if s["teacher_code"] == "KBR")
    assert kbr["liberes"] == [[0, 0]] and kbr["bloques"] == [[4, 3], [4, 4], [4, 5]]
    assert [0, 0] in kbr["origine"], "la semaine d'origine reste connue"
    # Le planning en service et la prochaine génération lisent la nouvelle semaine.
    en_service = {tuple(c) for c in next(t for t in etat.teacher_availability if t.teacher_code == "KBR").forbidden_slots}
    assert (0, 0) not in en_service and {(4, 3), (4, 4), (4, 5)} <= en_service and (1, 0) in en_service
    charge = next(t for t in load_teacher_availability(CONFIG) if t.teacher_code == "KBR")
    assert (0, 0) in {tuple(c) for c in charge.cancelled_forbidden_slots}

    # Un enseignant sans aucune contrainte connue.
    assert _semaine(admin, "ZZZ") is None
    assert admin.put("/reglages/semaines-types/ZZZ", json={"indisponibles": [[2, 5]], "motif": "m"}).status_code == 200
    assert _semaine(admin, "ZZZ")["bloques"] == [[2, 5]]
    assert admin.put("/reglages/semaines-types/ZZZ", json={"indisponibles": [[7, 0]], "motif": "m"}).status_code == 422
    assert admin.put("/reglages/semaines-types/..x", json={"indisponibles": [], "motif": "m"}).status_code in (404, 422)

    # Retour à la semaine d'origine.
    assert admin.delete("/reglages/semaines-types/KBR").status_code == 200
    assert admin.delete("/reglages/semaines-types/KBR").status_code == 404
    assert admin.delete("/reglages/semaines-types/ZZZ").status_code == 200
    en_service = {tuple(c) for c in next(t for t in etat.teacher_availability if t.teacher_code == "KBR").forbidden_slots}
    assert (0, 0) in en_service and (4, 3) not in en_service
    assert reglages.semaines_types(CONFIG) == {}


def test_une_liste_de_creneaux_possibles_ne_s_elargit_pas_a_l_ecran(admin):
    # Kévin Ngo déclare les créneaux où il PEUT venir : tout le reste est fixe.
    kng = _semaine(admin, "KNG")
    assert kng["fixes"] and all(c in kng["origine"] for c in kng["fixes"])
    moins = [c for c in kng["origine"] if c != kng["fixes"][0]]
    assert admin.put("/reglages/semaines-types/KNG", json={"indisponibles": moins, "motif": "m"}).status_code == 422
    libre = next([j, c] for j in range(5) for c in range(6) if [j, c] not in kng["origine"])
    plus = [*kng["origine"], libre]
    assert admin.put("/reglages/semaines-types/KNG", json={"indisponibles": plus, "motif": "m"}).status_code == 200
    assert _semaine(admin, "KNG")["bloques"] == [libre]
    assert admin.delete("/reglages/semaines-types/KNG").status_code == 200


# ── SAE : placement par le calcul, périodes d'encadrement ─────────────


def test_confier_une_sae_au_calcul_et_dire_qui_l_encadre_quand(admin, generations_isolees):
    from cal_iut.ingestion.config_loader import load_sae_teacher_phases, load_solver_scheduled_sae

    def _sae(code: str) -> dict:
        return next(s for s in admin.get("/generations/sae/even").json()["sae"] if s["code"] == code)

    depart = _sae("WS202")
    assert depart["placee_par_le_calcul"] is False and depart["phases"] == []
    assert {e["code"] for e in depart["enseignants"]} == {"ALO", "FLI", "JLE", "KBR"}

    # Placement par le calcul : seulement sans journées réservées, et avec un motif.
    assert admin.put("/generations/sae/even/WS202/placement", json={"par_le_calcul": True}).status_code == 422
    reponse = admin.put("/generations/sae/even/WS202/placement", json={"par_le_calcul": True, "motif": "Pas de dates"})
    assert reponse.status_code == 200, reponse.text
    assert _sae("WS202")["placee_par_le_calcul"] is True and _sae("WS202")["placement_saisi"] is True
    assert ("WS202", "S2") in load_solver_scheduled_sae(CONFIG)
    assert admin.put("/generations/sae/even/WS202", json={"dates": ["2027-03-08"]}).status_code == 422
    assert admin.put("/generations/sae/even/WS202/placement", json={"par_le_calcul": False}).status_code == 200
    assert ("WS202", "S2") not in load_solver_scheduled_sae(CONFIG)
    assert admin.put("/generations/sae/even/WS999/placement", json={"par_le_calcul": True, "motif": "m"}).status_code == 404

    dates = ["2027-03-08", "2027-03-09", "2027-03-10", "2027-03-11", "2027-03-12"]
    assert admin.put("/generations/sae/even/WS202", json={"dates": dates}).status_code == 200
    refus = admin.put("/generations/sae/even/WS202/placement", json={"par_le_calcul": True, "motif": "m"})
    assert refus.status_code == 422 and "journées réservées" in refus.json()["detail"]

    # Kyllian Bresson n'encadre que les deux premiers jours.
    phase = {"teacher_code": "KBR", "debut": "2027-03-08", "fin": "2027-03-09", "motif": "Lancement"}
    reponse = admin.post("/generations/sae/even/WS202/phases", json=phase)
    assert reponse.status_code == 201, reponse.text
    saisie = _sae("WS202")["phases"][0]
    assert (saisie["origine"], saisie["teacher_code"], saisie["debut"], saisie["fin"]) == ("ajoutee", "KBR", "2027-03-08", "2027-03-09")
    assert saisie["nom"] != "KBR" and saisie["id"]
    chargee = next(p for p in load_sae_teacher_phases(CONFIG) if p.course_code == "WS202")
    assert (chargee.teacher_code, chargee.semestre, chargee.debut, chargee.fin) == ("KBR", "S2", "2027-03-08", "2027-03-09")
    for refus in ({"teacher_code": "TPA"}, {"debut": "2027-03-10"}, {"fin": "bientôt"}):
        assert admin.post("/generations/sae/even/WS202/phases", json={**phase, **refus}).status_code == 422, refus
    assert admin.delete(f"/generations/sae/even/WS204/phases/{saisie['id']}").status_code == 404
    assert admin.delete(f"/generations/sae/even/WS202/phases/{saisie['id']}").status_code == 200
    assert _sae("WS202")["phases"] == []


def test_les_sae_d_un_semestre_en_service_gardent_leurs_reglages(admin, generations_isolees, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(id=1, semestre="ODD", parcours="MMI"), 3000)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())
    sae = {s["code"]: s for s in admin.get("/generations/sae/odd").json()["sae"]}
    # Les réglages d'origine sont listés : WSA501D placée par le calcul, WS501D découpée.
    assert sae["WSA501D"]["placee_par_le_calcul"] is True and sae["WSA501D"]["placement_saisi"] is False
    assert len(sae["WS501D"]["phases"]) == 4 and all(p["origine"] == "livree" for p in sae["WS501D"]["phases"])
    phase = {"teacher_code": "ALO", "debut": "2026-11-12", "fin": "2026-11-13", "motif": "m"}
    assert admin.post("/generations/sae/odd/WS501D/phases", json=phase).status_code == 409
    assert admin.put("/generations/sae/odd/WSA310M/placement", json={"par_le_calcul": True, "motif": "m"}).status_code == 409
