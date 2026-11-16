"""Nouveau semestre depuis l'interface — lot 5 (16/11/2026) : « À régler
avant de générer ».

L'audit des données est lancé AVANT le calcul, depuis l'écran. Tant qu'il
reste une erreur, la génération ne part pas : ni depuis la route, ni dans
l'ouvrier. Les alertes s'affichent sans rien bloquer.
"""

from __future__ import annotations

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.generation import ouvrier as module_ouvrier
from cal_iut.generation import taches, verification

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")

ERREUR = {
    "severite": "erreur", "controle": "capacite.enseignant_impossible",
    "message": "JBA : 120 créneaux à assurer pour 90 créneaux déclarés.",
    "quoi_faire": "Élargir ses disponibilités.", "ou": "", "details": [],
}
ALERTE = {
    "severite": "alerte", "controle": "donnees.sae_sans_dates",
    "message": "15 SAE ont des heures mais aucune date.", "quoi_faire": "", "ou": "", "details": [],
}
INFO = {"severite": "info", "controle": "donnees.volume", "message": "1941 séances.", "details": []}
CODE = {
    "severite": "erreur", "controle": "couverture.controle_absent",
    "message": "1 contrôle attendu ne figure pas dans le tableau de bord.", "details": [],
}


@pytest.fixture(autouse=True)
def generations_isolees(tmp_path, monkeypatch):
    monkeypatch.setattr(taches, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(taches, "GENERATIONS_DIR", tmp_path / "state" / "generations")
    lancees: list[str] = []
    monkeypatch.setattr(taches, "lancer", lambda generation_id: lancees.append(generation_id) or 4242)
    return lancees


@pytest.fixture
def admin(db_isole) -> TestClient:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def _audit_simule(monkeypatch, constats: list[dict]) -> None:
    def _rapport(racine, groupe, *, weeks, fi_max_week):
        return {
            "resume": {
                "erreurs": sum(c["severite"] == "erreur" for c in constats),
                "alertes": sum(c["severite"] == "alerte" for c in constats),
                "infos": 0, "controles_ok": 11,
            },
            "constats": [dict(c) for c in constats],
            "controles_ok": [],
        }

    monkeypatch.setattr(verification, "rapport_des_donnees", _rapport)


def test_les_donnees_du_depot_ne_bloquent_aucun_des_deux_semestres(admin):
    """Le vrai audit, sur les vraies données : des alertes (SAE sans dates au
    semestre pair), aucune erreur — sinon plus personne ne peut générer."""
    for groupe in ("odd", "even"):
        rapport = admin.get(f"/generations/verification/{groupe}").json()
        assert rapport["semestre_group"] == groupe and rapport["seances"] > 1000
        assert rapport["bloquant"] is False and rapport["erreurs"] == 0, rapport["constats"]
        assert all(c["severite"] == "alerte" and c["bloquant"] is False for c in rapport["constats"])
        # Sans objet sur le serveur (dates de fichiers d'une image Docker).
        assert all(c["controle"] != "donnees.sources_plus_recentes" for c in rapport["constats"])
    assert any(c["controle"] == "donnees.sae_sans_dates" for c in rapport["constats"])


def test_la_verification_est_reservee_aux_administrateurs(db_isole):
    assert TestClient(app).get("/generations/verification/even").status_code == 401
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    assert editeur.get("/generations/verification/even").status_code == 403


def test_un_groupe_inconnu_est_refuse(admin):
    assert admin.get("/generations/verification/tout").status_code == 422


def test_les_erreurs_passent_en_tete_et_les_informations_ne_sont_pas_listees(admin, monkeypatch):
    _audit_simule(monkeypatch, [INFO, ALERTE, CODE, ERREUR])
    rapport = admin.get("/generations/verification/even").json()
    assert [c["controle"] for c in rapport["constats"]] == [
        "capacite.enseignant_impossible", "couverture.controle_absent", "donnees.sae_sans_dates",
    ]
    # Un contrôle de cohérence du code ne bloque pas : l'utilisateur n'y peut rien.
    assert [c["bloquant"] for c in rapport["constats"]] == [True, False, False]
    assert (rapport["bloquant"], rapport["erreurs"], rapport["alertes"]) == (True, 1, 2)


def test_une_erreur_empeche_de_lancer_la_generation(admin, monkeypatch, generations_isolees):
    _audit_simule(monkeypatch, [ALERTE, ERREUR])
    refus = admin.post("/generations", json={"semestre_group": "even"})
    assert refus.status_code == 409
    assert "1 point(s) à régler avant de générer" in refus.json()["detail"]
    assert "JBA" in refus.json()["detail"]
    assert generations_isolees == [] and taches.lister() == []


def test_une_alerte_n_empeche_pas_de_lancer(admin, monkeypatch, generations_isolees):
    _audit_simule(monkeypatch, [ALERTE, CODE])
    assert admin.post("/generations", json={"semestre_group": "even"}).status_code == 201
    assert len(generations_isolees) == 1


def test_pendant_une_generation_la_verification_attend(admin, monkeypatch):
    """La vérification réécrit `data/generated/`, que l'ouvrier lit."""
    _audit_simule(monkeypatch, [])
    assert admin.post("/generations", json={"semestre_group": "even"}).status_code == 201
    assert admin.get("/generations/verification/odd").status_code == 409
    # Et une seconde demande reste refusée pour la bonne raison.
    refus = admin.post("/generations", json={"semestre_group": "odd"})
    assert refus.status_code == 409 and "déjà en cours" in refus.json()["detail"]


def test_une_maquette_vide_est_un_point_a_regler_pas_une_panne(admin, monkeypatch):
    from cal_iut.ingestion import pipeline

    class _Vide:
        sessions: list = []
        courses: list = []
        stats: dict = {}

    monkeypatch.setattr(pipeline, "run_ingestion", lambda *a, **k: _Vide())
    rapport = admin.get("/generations/verification/even").json()
    assert rapport["bloquant"] is True and rapport["seances"] == 0
    assert rapport["constats"][0]["controle"] == "chargement.aucune_seance"
    assert "S2, S4, S6" in rapport["constats"][0]["message"]

    def _illisible(*a, **k):
        raise ValueError("maquette.json : JSON invalide")

    monkeypatch.setattr(pipeline, "run_ingestion", _illisible)
    rapport = admin.get("/generations/verification/even").json()
    assert rapport["bloquant"] is True
    assert "JSON invalide" in rapport["constats"][0]["message"]


def test_l_ouvrier_s_arrete_avant_le_calcul_s_il_reste_une_erreur(monkeypatch):
    """Garde-fou si les données changent entre le lancement et le calcul."""
    _audit_simule(monkeypatch, [ERREUR])
    appels: list[int] = []
    monkeypatch.setattr(
        module_ouvrier.Ouvrier, "_lancer_solveur", lambda self, graine, sortie: appels.append(graine) or "OK"
    )
    etat = taches.creer({"semestre_group": "even", "tentatives": 1}, "admin")
    assert module_ouvrier.Ouvrier(taches.GENERATIONS_DIR / etat["id"]).executer() != 0
    fin = taches.lire(etat["id"])
    assert fin["statut"] == "echec"
    assert "à régler avant de générer" in fin["erreur"] and "JBA" in fin["erreur"]
    assert appels == []
    # Les constats restent lisibles sur la fiche de la génération.
    assert fin["verification"]["constats"][0]["controle"] == "capacite.enseignant_impossible"
