"""Nouveau semestre depuis l'interface — lot 2 (16/11/2026) : génération en
tâche de fond.

Trois volets :

1. `generation/taches.py` — l'état d'une génération vit sur disque : une
   seule à la fois, annulation, reprise après un redémarrage du serveur.
2. `api/generations_routes.py` — réservé aux administrateurs.
3. `generation/ouvrier.py` et `generation/finition.py` — le déroulé complet
   avec un solveur simulé : le résultat est un BROUILLON, le planning en
   service n'est pas touché.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.generation import ouvrier as module_ouvrier
from cal_iut.generation import taches

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")


@pytest.fixture(autouse=True)
def generations_isolees(tmp_path, monkeypatch):
    """Jamais le vrai `data/state/generations/`, et aucun processus lancé."""
    monkeypatch.setattr(taches, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(taches, "GENERATIONS_DIR", tmp_path / "state" / "generations")
    lancees: list[str] = []
    monkeypatch.setattr(taches, "lancer", lambda generation_id: lancees.append(generation_id) or 4242)
    return lancees


def _vieillir_battement(generation_id: str) -> None:
    battement = taches.GENERATIONS_DIR / generation_id / "battement"
    battement.touch()
    ancien = time.time() - taches.BATTEMENT_MAX_S - 60
    os.utime(battement, (ancien, ancien))


# --------------------------------------------------------------------------
# 1. Les tâches sur disque
# --------------------------------------------------------------------------


def test_les_reglages_par_defaut_reprennent_la_recette_de_l_automne():
    impair = taches.parametres_par_defaut("odd")
    assert (impair["weeks"], impair["fi_max_week"], impair["spread_weight"]) == (24, 18, 8)
    pair = taches.parametres_par_defaut("even")
    # Le semestre pair suit son propre calendrier : aucun horizon imposé.
    assert (pair["weeks"], pair["fi_max_week"]) == (None, None)
    assert 1 <= pair["num_workers"] <= taches.coeurs_disponibles()


@pytest.mark.parametrize(
    "saisie",
    [
        {"semestre_group": "tout"},
        {"semestre_group": "even", "tentatives": 0},
        {"semestre_group": "even", "tentatives": "6"},
        {"semestre_group": "even", "heures": 48},
        {"semestre_group": "even", "num_workers": 4096},
    ],
)
def test_une_saisie_hors_bornes_est_refusee(saisie):
    with pytest.raises(ValueError):
        taches.valider_parametres(saisie)


def test_une_seule_generation_a_la_fois():
    premiere = taches.creer({"semestre_group": "even"}, "admin@exemple.fr")
    assert premiere["statut"] == "en_attente"
    assert [e["statut"] for e in premiere["etapes"]] == ["a_faire"] * len(taches.ETAPES)
    assert taches.active()["id"] == premiere["id"]

    with pytest.raises(taches.GenerationDejaEnCours):
        taches.creer({"semestre_group": "odd"}, "admin@exemple.fr")


@pytest.mark.parametrize("identifiant", ["", "..", "../etc", "20261116-171750-87bc/../x", "inconnue"])
def test_un_identifiant_invalide_ne_sort_jamais_du_dossier(identifiant):
    with pytest.raises(taches.GenerationIntrouvable):
        taches.dossier(identifiant)


def test_annuler_une_generation_dont_l_ouvrier_ne_tourne_plus_la_clot():
    etat = taches.creer({"semestre_group": "even"}, "admin")
    etat["statut"] = "en_cours"
    etat["etapes"][2]["statut"] = "en_cours"
    taches.ecrire(taches.GENERATIONS_DIR / etat["id"], etat)
    _vieillir_battement(etat["id"])

    apres = taches.demander_annulation(etat["id"])

    assert apres["statut"] == "annulee"
    assert apres["etapes"][2]["statut"] == "annulee"
    assert taches.active() is None


def test_annuler_une_generation_vivante_laisse_l_ouvrier_s_arreter():
    etat = taches.creer({"semestre_group": "even"}, "admin")
    (taches.GENERATIONS_DIR / etat["id"] / "battement").touch()

    apres = taches.demander_annulation(etat["id"])

    assert apres["statut"] == "en_attente"
    assert (taches.GENERATIONS_DIR / etat["id"] / "annuler").exists()


def test_une_generation_interrompue_par_un_redemarrage_est_relancee(generations_isolees):
    etat = taches.creer({"semestre_group": "even"}, "admin")
    etat["statut"] = "en_cours"
    taches.ecrire(taches.GENERATIONS_DIR / etat["id"], etat)

    # L'ouvrier bat encore : on n'y touche pas.
    (taches.GENERATIONS_DIR / etat["id"] / "battement").touch()
    assert taches.reprendre_interrompues() == []

    _vieillir_battement(etat["id"])
    assert taches.reprendre_interrompues() == [etat["id"]]
    assert generations_isolees == [etat["id"]]
    assert taches.lire(etat["id"])["reprises"] == 1


def test_une_generation_qui_tombe_a_chaque_reprise_finit_en_echec(generations_isolees):
    etat = taches.creer({"semestre_group": "even"}, "admin")
    etat["statut"] = "en_cours"
    etat["reprises"] = taches.REPRISES_MAX
    taches.ecrire(taches.GENERATIONS_DIR / etat["id"], etat)
    _vieillir_battement(etat["id"])

    assert taches.reprendre_interrompues() == []
    assert generations_isolees == []
    assert taches.lire(etat["id"])["statut"] == "echec"


def test_sans_generation_en_cours_le_demarrage_du_serveur_ne_surveille_rien():
    assert taches.surveiller_reprises() is None


def test_seules_les_dernieres_generations_finies_sont_gardees():
    for numero in range(taches.CONSERVEES + 3):
        chemin = taches.GENERATIONS_DIR / f"202611{numero + 1:02d}-090000-abcd"
        chemin.mkdir(parents=True)
        taches.ecrire(chemin, {"id": chemin.name, "statut": "terminee", "parametres": {"semestre_group": "even"}})

    taches.creer({"semestre_group": "even"}, "admin")

    finies = [e for e in taches.lister() if e["statut"] == "terminee"]
    assert len(finies) == taches.CONSERVEES
    assert finies[0]["id"].startswith(f"202611{taches.CONSERVEES + 3:02d}")


# --------------------------------------------------------------------------
# 2. Les routes
# --------------------------------------------------------------------------


@pytest.fixture
def admin(db_isole) -> TestClient:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def test_les_routes_sont_reservees_aux_administrateurs(db_isole):
    assert TestClient(app).get("/generations").status_code == 401
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    assert editeur.get("/generations").status_code == 403
    assert editeur.post("/generations", json={"semestre_group": "even"}).status_code == 403
    assert taches.lister() == []


def test_lancer_suivre_et_annuler_une_generation(admin, generations_isolees):
    accueil = admin.get("/generations").json()
    assert [g["cle"] for g in accueil["groupes"]] == ["odd", "even"]
    assert accueil["active"] is None and accueil["generations"] == []

    reponse = admin.post("/generations", json={"semestre_group": "even", "tentatives": 2, "heures": 0.5})
    assert reponse.status_code == 201, reponse.text
    creee = reponse.json()
    assert creee["parametres"]["tentatives"] == 2
    assert creee["cree_par"].endswith("@example.test")
    assert generations_isolees == [creee["id"]]

    # Une seule à la fois.
    assert admin.post("/generations", json={"semestre_group": "odd"}).status_code == 409
    assert generations_isolees == [creee["id"]]

    suivi = admin.get("/generations").json()
    assert suivi["active"]["id"] == creee["id"]
    assert suivi["generations"][0]["semestre_group"] == "even"
    assert admin.get(f"/generations/{creee['id']}").json()["statut"] == "en_attente"

    _vieillir_battement(creee["id"])
    annulee = admin.post(f"/generations/{creee['id']}/annuler").json()
    assert annulee["statut"] == "annulee"
    assert admin.get("/generations").json()["active"] is None


def test_une_demande_invalide_ou_inconnue_est_refusee_proprement(admin, generations_isolees):
    assert admin.post("/generations", json={"semestre_group": "tout"}).status_code == 422
    assert admin.post("/generations", json={"semestre_group": "even", "tentatives": 500}).status_code == 422
    assert generations_isolees == []
    assert admin.get("/generations/20260101-000000-abcd").status_code == 404
    assert admin.post("/generations/..%2F..%2Fetc/annuler").status_code in (404, 405)


def test_lancer_une_generation_ne_fait_pas_recharger_le_planning_aux_autres(admin):
    from cal_iut.api import revision

    avant = revision.actuelle().numero
    assert admin.post("/generations", json={"semestre_group": "even"}).status_code == 201
    assert revision.actuelle().numero == avant


# --------------------------------------------------------------------------
# 3. L'ouvrier : le déroulé complet, solveur simulé
# --------------------------------------------------------------------------


def _solveur_simule(nombre: int):
    """Remplace `cal-iut solve` : place les `nombre` premières séances, une
    par créneau, dans l'ordre du fichier."""

    def _lancer(self, graine: int, sortie: Path) -> str:
        seances = json.loads((self.dossier / "sessions.json").read_text(encoding="utf-8"))
        placements = [
            {
                "session_id": s["id"], "week": i // 20, "day": (i // 4) % 5, "slot": i % 4,
                "course_code": s["course_code"], "group_ids": s["group_ids"],
                "teacher_codes": s["teacher_codes"], "room_id": None, "room_label": None,
            }
            for i, s in enumerate(seances[:nombre])
        ]
        sortie.write_text(
            json.dumps({"status": "FEASIBLE", "objective_value": 12.0, "gap_penalty": 0,
                        "placements": placements, "seed": graine}),
            encoding="utf-8",
        )
        return "FEASIBLE"

    return _lancer


@pytest.fixture
def base_en_service(tmp_path):
    """Une base avec un planning publié du semestre impair, à la place que
    lira l'ouvrier (`taches.STATE_DIR / cal-iut.db`)."""
    from cal_iut.db import session as db_session
    from cal_iut.db.repository import PlanningRepository
    from cal_iut.db.session import get_db, init_db

    chemin = taches.STATE_DIR / "cal-iut.db"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(chemin)
    base = get_db(chemin)
    try:
        en_service = [{
            "session_id": "S1-WR101-TD-1", "week": 2, "day": 1, "slot": 0, "course_code": "WR101",
            "group_ids": ["but1-td-ab"], "teacher_codes": ["MRI"], "room_id": "H.007", "room_label": "H.007",
        }]
        PlanningRepository(base).save_run(
            parcours="MMI", semestre="ODD", status="FEASIBLE", objective_value=1.0, gap_penalty=0,
            weeks=24, solver_placements=en_service, current_placements=en_service,
        )
    finally:
        base.close()
    yield chemin
    if db_session._engine:
        db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None


def _placements_en_service(chemin: Path) -> list[str]:
    import sqlite3

    with sqlite3.connect(chemin) as connexion:
        return [ligne[0] for ligne in connexion.execute("SELECT session_id FROM current_placements")]


def test_la_generation_complete_enregistre_un_brouillon_sans_toucher_au_service(
    base_en_service, monkeypatch,
):
    from cal_iut.generation import finition

    monkeypatch.setattr(module_ouvrier.Ouvrier, "_lancer_solveur", _solveur_simule(40))
    vus: dict = {}

    def _finition_simulee(donnees, fichier_seances, racine, groupe):
        vus.update(groupe=groupe, placements=len(donnees["placements"]))
        return {
            "a_placer": 45, "completees": 0, "sans_salle": 40,
            "non_placees": [{"session_id": "x", "course_code": "R2.01", "raison": "Aucun créneau libre"}],
        }

    monkeypatch.setattr(finition, "finir_planning", _finition_simulee)
    etat = taches.creer({"semestre_group": "even", "tentatives": 2, "arret_si_complet": False}, "admin")
    chemin = taches.GENERATIONS_DIR / etat["id"]

    assert module_ouvrier.Ouvrier(chemin).executer() == 0

    fin = taches.lire(etat["id"])
    assert fin["statut"] == "terminee", fin["erreur"]
    assert [e["statut"] for e in fin["etapes"]] == ["faite"] * len(taches.ETAPES)
    assert vus == {"groupe": "even", "placements": 40}
    # Deux essais, deux tirages différents ; à résultat égal le premier reste.
    assert [t["graine"] for t in fin["tentatives"]] == [2027, 3040]
    assert fin["meilleur"]["numero"] == 1
    assert fin["resultat"]["motifs"] == [{"raison": "Aucun créneau libre", "nombre": 1}]
    # Le contrôle sur la date des fichiers sources n'a pas de sens ici.
    assert all(c["controle"] != "donnees.sources_plus_recentes" for c in fin["verification"]["constats"])

    from cal_iut.db.repository import ETAT_BROUILLON, PlanningRepository
    from cal_iut.db.session import get_db

    base = get_db(base_en_service)
    try:
        from cal_iut.db.models import PlanningRun

        depot = PlanningRepository(base)
        brouillon = base.get(PlanningRun, fin["run_id"])
        assert (brouillon.etat, brouillon.semestre) == (ETAT_BROUILLON, "EVEN")
        # Le planning servi reste celui de l'automne.
        assert depot.get_latest_run().semestre == "ODD"
    finally:
        base.close()
    assert _placements_en_service(base_en_service) == ["S1-WR101-TD-1"]


def test_une_generation_reprise_ne_refait_pas_les_essais_deja_faits(base_en_service, monkeypatch):
    from cal_iut.generation import finition

    appels: list[int] = []
    simule = _solveur_simule(10)

    def _compter(self, graine, sortie):
        appels.append(graine)
        return simule(self, graine, sortie)

    monkeypatch.setattr(module_ouvrier.Ouvrier, "_lancer_solveur", _compter)
    monkeypatch.setattr(
        finition, "finir_planning",
        lambda *a, **k: {"a_placer": 10, "completees": 0, "sans_salle": 0, "non_placees": []},
    )
    etat = taches.creer({"semestre_group": "even", "tentatives": 3, "arret_si_complet": False}, "admin")
    chemin = taches.GENERATIONS_DIR / etat["id"]

    # Premier ouvrier : interrompu (redémarrage du serveur) pendant l'essai 2.
    premier = module_ouvrier.Ouvrier(chemin)
    premier.preparer()
    premier.verifier()

    def _coupure(self, graine, sortie):
        if len(appels) == 1:
            raise KeyboardInterrupt
        return _compter(self, graine, sortie)

    monkeypatch.setattr(module_ouvrier.Ouvrier, "_lancer_solveur", _coupure)
    with pytest.raises(KeyboardInterrupt):
        premier.calculer()
    assert len(taches.lire(etat["id"])["tentatives"]) == 1

    monkeypatch.setattr(module_ouvrier.Ouvrier, "_lancer_solveur", _compter)
    assert module_ouvrier.Ouvrier(chemin).executer() == 0

    fin = taches.lire(etat["id"])
    assert fin["statut"] == "terminee", fin["erreur"]
    assert [t["numero"] for t in fin["tentatives"]] == [1, 2, 3]
    assert appels == [2027, 3040, 4053]


def test_une_generation_annulee_s_arrete_sans_rien_enregistrer(base_en_service, monkeypatch):
    def _annulation_pendant_le_calcul(self, graine, sortie):
        (self.dossier / "annuler").touch()
        raise module_ouvrier.Annulee

    monkeypatch.setattr(module_ouvrier.Ouvrier, "_lancer_solveur", _annulation_pendant_le_calcul)
    etat = taches.creer({"semestre_group": "even"}, "admin")

    assert module_ouvrier.Ouvrier(taches.GENERATIONS_DIR / etat["id"]).executer() == 0

    fin = taches.lire(etat["id"])
    assert (fin["statut"], fin["run_id"]) == ("annulee", None)
    assert fin["etapes"][2]["statut"] == "annulee"


def test_un_solveur_qui_ne_produit_rien_met_la_generation_en_echec(base_en_service, monkeypatch):
    monkeypatch.setattr(module_ouvrier.Ouvrier, "_lancer_solveur", lambda self, graine, sortie: "INFEASIBLE")
    etat = taches.creer({"semestre_group": "even", "tentatives": 1}, "admin")

    assert module_ouvrier.Ouvrier(taches.GENERATIONS_DIR / etat["id"]).executer() == 1

    fin = taches.lire(etat["id"])
    assert fin["statut"] == "echec"
    assert "aucun emploi du temps" in fin["erreur"]
    assert fin["run_id"] is None


# --------------------------------------------------------------------------
# La finition : complétion d'un brouillon, sans aucun effet sur le service
# --------------------------------------------------------------------------


_SCRIPT_FINITION = """
import json, sys
from pathlib import Path
from cal_iut.generation import finition
from cal_iut.ingestion.pipeline import run_ingestion

racine, sortie = Path(sys.argv[1]), Path(sys.argv[2])
seances = [
    s for s in run_ingestion(racine / "data" / "config", semestre_group="even").sessions
    if s.semestre == "S2" and len(s.teacher_codes) == 1
][:6]
fichier = sortie / "sessions.json"
fichier.write_text(json.dumps([s.model_dump() for s in seances]), encoding="utf-8")
premiere = seances[0]
donnees = {"status": "FEASIBLE", "placements": [{
    "session_id": premiere.id, "week": 1, "day": 0, "slot": 0, "course_code": premiere.course_code,
    "group_ids": premiere.group_ids, "teacher_codes": premiere.teacher_codes,
}]}
rapport = finition.finir_planning(donnees, fichier, racine, "even")
(sortie / "rapport.json").write_text(json.dumps({
    "rapport": rapport, "placements": donnees["placements"], "seances": [s.id for s in seances],
}), encoding="utf-8")
"""


def _empreinte(dossier: Path) -> dict[str, tuple[int, int]]:
    return {
        str(f.relative_to(dossier)): (f.stat().st_size, f.stat().st_mtime_ns)
        for f in sorted(dossier.rglob("*"))
        if f.is_file() and "generations" not in f.parts
    }


def test_la_finition_complete_le_brouillon_sans_rien_ecrire_dans_l_etat_en_service(tmp_path):
    """Dans son propre processus, comme l'ouvrier : la complétion passe par le
    moteur du bouton « Tout placer automatiquement », qui d'ordinaire écrit
    en base, alimente la file Celcat et notifie. Sur un brouillon, rien de
    tout cela ne doit se produire."""
    import subprocess
    import sys

    racine = module_ouvrier.RACINE
    etat_en_service = racine / "data" / "state"
    avant = _empreinte(etat_en_service)

    execution = subprocess.run(
        [sys.executable, "-c", _SCRIPT_FINITION, str(racine), str(tmp_path)],
        cwd=racine, capture_output=True, text=True, timeout=300, check=False,
    )
    assert execution.returncode == 0, execution.stderr[-3000:]

    assert _empreinte(etat_en_service) == avant
    resultat = json.loads((tmp_path / "rapport.json").read_text(encoding="utf-8"))
    rapport, placements = resultat["rapport"], resultat["placements"]
    assert rapport["completees"] == len(placements) - 1
    assert rapport["completees"] + len(rapport["non_placees"]) == 5
    assert rapport["completees"] >= 1
    assert {p["session_id"] for p in placements} <= set(resultat["seances"])
    # Le solveur ne connaît pas les salles : la finition les attribue.
    assert rapport["sans_salle"] < len(placements)
