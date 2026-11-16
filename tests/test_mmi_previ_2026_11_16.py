"""Nouveau semestre — maquette et progression récupérées depuis MMI Prévi
(16/11/2026).

1. `ingestion/mmi_previ.py` — l'appel (jeton dans l'en-tête seulement,
   filtre `?semestres=`), le contrôle de ce qui est reçu, les copies sur le
   volume et leur prise en compte par l'ingestion.
2. `api/generations_routes.py` — réservé aux administrateurs, refusé pour un
   semestre déjà en service ou pendant une génération.

Aucun appel réseau : `httpx.Client` est remplacé par un transport simulé.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.generation import taches
from cal_iut.ingestion import mmi_previ
from cal_iut.ingestion.pipeline import _load_cached_or_fetch

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")

JETON = "mmip_jeton-de-test-jamais-reel"
PAIR = ("S2", "S4", "S6")


def _module(code: str, semestre: str, parcours: str = "BUT1", td: int = 10, lead: str | None = "ABC") -> dict:
    return {
        "code_matiere": code,
        "nom_matiere": f"Module {code}",
        "semestre": semestre,
        "parcours": parcours,
        "total": {"cm": 2, "td": td, "tp": 4},
        "lead": {"code": lead, "nom": "DUPONT", "prenom": "CAMILLE"} if lead else None,
        "profs": [],
        "maquette": {"codelement": None, "groupes": {"td": 2, "tp": 4}},
        "commentaires": ["commentaire interne à ne pas diffuser"],
    }


def _progression(code: str, semestre: str, parcours: str = "BUT1", lead: str | None = "ABC") -> dict:
    return {
        "code_matiere": code,
        "nom_matiere": f"Module {code}",
        "semestre": semestre,
        "parcours": parcours,
        "codelement": None,
        "lead": {"code": lead, "nom": "DUPONT", "prenom": "CAMILLE"} if lead else None,
        "volumes": {"cm": 2, "td": 10, "tp": 4, "ptut": 0},
        "groupes": {"td": 2, "tp": 4},
        "progression": {"definie": True, "nb_seances": 1, "seances": [{"ordre": 1, "type": "CM", "eval": False}]},
        "ordonnancement": [],
        "commentaire_edt": None,
        "commentaires": [],
    }


class _Serveur:
    """MMI Prévi simulé : note chaque requête reçue."""

    def __init__(self) -> None:
        self.requetes: list[httpx.Request] = []
        self.statut = 200
        self.maquette: object = [_module("WR201", "S2"), _module("WR401", "S4", "BUT2-DEV-FI")]
        self.progression: object = [_progression("WR201", "S2"), _progression("WR401", "S4", "BUT2-DEV-FI")]

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        if requete.headers.get("Authorization") != f"Bearer {JETON}":
            return httpx.Response(401, json={"erreur": "Jeton d'accès requis"})
        if self.statut != 200:
            return httpx.Response(self.statut, json={"erreur": "…"})
        return httpx.Response(200, json=self.maquette if requete.url.path.endswith("maquette") else self.progression)


@pytest.fixture
def serveur(monkeypatch):
    faux = _Serveur()
    vrai_client = httpx.Client

    def _client(**options):
        return vrai_client(transport=httpx.MockTransport(faux), **options)

    monkeypatch.setattr(mmi_previ.httpx, "Client", _client)
    monkeypatch.setenv(mmi_previ.VAR_JETON, JETON)
    monkeypatch.delenv(mmi_previ.VAR_URL, raising=False)
    return faux


@pytest.fixture
def racine(tmp_path) -> Path:
    """Un dépôt réduit : une copie livrée avec un module impair et un pair."""
    contraintes = tmp_path / "contraintes"
    contraintes.mkdir()
    (contraintes / "maquette.json").write_text(
        json.dumps([_module("WR101", "S1"), _module("WR201", "S2", td=6), _module("WR299", "S2")]), encoding="utf-8"
    )
    (contraintes / "progression.json").write_text(
        json.dumps([_progression("WR101", "S1"), _progression("WR201", "S2"), _progression("WR299", "S2")]),
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------
# 1. L'appel à MMI Prévi
# --------------------------------------------------------------------------


def test_le_jeton_part_dans_l_en_tete_et_jamais_dans_l_adresse(serveur):
    modules = mmi_previ.telecharger("maquette", PAIR)
    assert [m["code_matiere"] for m in modules] == ["WR201", "WR401"]
    requete = serveur.requetes[0]
    assert requete.headers["Authorization"] == f"Bearer {JETON}"
    assert JETON not in str(requete.url)
    assert requete.url.path == "/export/maquette"
    assert requete.url.params["semestres"] == "S2,S4,S6"


def test_sans_jeton_configure_aucun_appel_ne_part(serveur, monkeypatch):
    monkeypatch.delenv(mmi_previ.VAR_JETON)
    with pytest.raises(mmi_previ.JetonAbsent, match=mmi_previ.VAR_JETON):
        mmi_previ.telecharger("maquette", PAIR)
    assert serveur.requetes == []
    assert mmi_previ.configure() is False


def test_un_jeton_refuse_donne_un_message_clair_sans_le_jeton(serveur, monkeypatch):
    monkeypatch.setenv(mmi_previ.VAR_JETON, "mmip_perime")
    with pytest.raises(mmi_previ.JetonRefuse) as erreur:
        mmi_previ.telecharger("progression", PAIR)
    assert "expiré" in str(erreur.value)
    assert "mmip_perime" not in str(erreur.value)


def test_une_adresse_sans_https_est_refusee_avant_tout_envoi(serveur, monkeypatch):
    monkeypatch.setenv(mmi_previ.VAR_URL, "http://mmi-previ.example")
    with pytest.raises(mmi_previ.MmiPreviInjoignable, match="https"):
        mmi_previ.telecharger("maquette", PAIR)
    assert serveur.requetes == []


def test_une_panne_reseau_ne_cite_ni_le_jeton_ni_l_adresse(monkeypatch):
    def _panne(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"échec vers {requete.url} avec {requete.headers['Authorization']}")

    vrai_client = httpx.Client
    monkeypatch.setattr(mmi_previ.httpx, "Client", lambda **o: vrai_client(transport=httpx.MockTransport(_panne), **o))
    monkeypatch.setenv(mmi_previ.VAR_JETON, JETON)
    with pytest.raises(mmi_previ.MmiPreviInjoignable) as erreur:
        mmi_previ.telecharger("maquette", PAIR)
    assert JETON not in str(erreur.value)
    assert erreur.value.__cause__ is None


@pytest.mark.parametrize("statut", [400, 500])
def test_une_erreur_de_mmi_previ_est_rapportee(serveur, statut):
    serveur.statut = statut
    with pytest.raises(mmi_previ.ReponseInattendue, match=str(statut)):
        mmi_previ.telecharger("maquette", PAIR)


def test_l_ancien_telechargement_envoie_aussi_le_jeton(monkeypatch):
    """`cal-iut fetch` et l'installation passent par `ingestion/fetch.py`."""
    monkeypatch.setenv(mmi_previ.VAR_JETON, JETON)
    assert mmi_previ.entetes()["Authorization"] == f"Bearer {JETON}"
    monkeypatch.delenv(mmi_previ.VAR_JETON)
    assert "Authorization" not in mmi_previ.entetes()


# --------------------------------------------------------------------------
# 2. Contrôle, copies, ingestion
# --------------------------------------------------------------------------


def test_recuperer_enregistre_une_copie_et_dit_ce_qui_change(serveur, racine):
    resultat = mmi_previ.recuperer(racine, "even", "admin@example.org")
    assert resultat["source"]["modules"] == 2
    assert resultat["source"]["avec_progression"] == 2
    assert resultat["source"]["par"] == "admin@example.org"
    differences = resultat["differences"]
    assert [m["code"] for m in differences["ajoutes"]] == ["WR401"]
    assert [m["code"] for m in differences["retires"]] == ["WR299"]
    assert [m["code"] for m in differences["modifies"]] == ["WR201"]
    # Le résumé ne porte ni nom d'enseignant ni commentaire.
    assert "DUPONT" not in json.dumps(resultat) and "commentaire" not in json.dumps(resultat)
    # Le jeton n'est écrit dans aucun fichier.
    for fichier in mmi_previ.dossier_des_copies(racine).rglob("*"):
        if fichier.is_file():
            assert JETON not in fichier.read_text(encoding="utf-8")


def test_la_copie_remplace_les_modules_de_ses_semestres_seulement(serveur, racine):
    mmi_previ.recuperer(racine, "even", "admin")
    maquette, progression = _load_cached_or_fetch(racine / "data" / "config")
    assert sorted(m["code_matiere"] for m in maquette) == ["WR101", "WR201", "WR401"]
    assert sorted(m["code_matiere"] for m in progression) == ["WR101", "WR201", "WR401"]
    # Le semestre impair vient toujours de la copie livrée.
    assert mmi_previ.etat_de_la_copie(racine, "odd") is None

    assert mmi_previ.supprimer_copie(racine, "even") is True
    maquette, _ = _load_cached_or_fetch(racine / "data" / "config")
    assert sorted(m["code_matiere"] for m in maquette) == ["WR101", "WR201", "WR299"]


def test_le_solveur_lit_la_meme_progression_que_l_ingestion(serveur, racine):
    from cal_iut.solver.decomposed import _cours_avec_progression_declaree

    _cours_avec_progression_declaree.cache_clear()
    try:
        mmi_previ.recuperer(racine, "even", "admin")
        assert ("WR401", "S4") in _cours_avec_progression_declaree(racine)
        assert ("WR299", "S2") not in _cours_avec_progression_declaree(racine)
    finally:
        _cours_avec_progression_declaree.cache_clear()


def test_un_module_sans_responsable_bloque_tout_sans_rien_ecrire(serveur, racine):
    serveur.maquette = [_module("WR201", "S2"), _module("WR202", "S2", lead=None)]
    serveur.progression = [_progression("WR201", "S2"), _progression("WR202", "S2", lead=None)]
    with pytest.raises(mmi_previ.ReponseInattendue, match="WR202"):
        mmi_previ.recuperer(racine, "even", "admin")
    assert mmi_previ.lire_copie(racine, "even") is None


@pytest.mark.parametrize(
    "maquette",
    [
        [],
        {"erreur": "pas une liste"},
        [{"code_matiere": "WR201"}],
        [_module("WR101", "S1")],  # un semestre non demandé
    ],
)
def test_une_reponse_inattendue_ne_remplace_rien(serveur, racine, maquette):
    serveur.maquette = maquette
    with pytest.raises(mmi_previ.ReponseInattendue):
        mmi_previ.recuperer(racine, "even", "admin")
    assert mmi_previ.lire_copie(racine, "even") is None


# --------------------------------------------------------------------------
# 3. Les routes
# --------------------------------------------------------------------------


@pytest.fixture
def depot_isole(racine, monkeypatch):
    monkeypatch.setattr(taches, "RACINE", racine)
    monkeypatch.setattr(taches, "STATE_DIR", racine / "data" / "state")
    monkeypatch.setattr(taches, "GENERATIONS_DIR", racine / "data" / "state" / "generations")
    monkeypatch.setattr(taches, "lancer", lambda generation_id: 4242)
    return racine


@pytest.fixture
def admin(db_isole, depot_isole):
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    return client


def test_les_routes_des_sources_sont_reservees_aux_administrateurs(db_isole, depot_isole, serveur):
    anonyme = TestClient(app)
    assert anonyme.post("/generations/sources/mmi-previ", json={"semestre_group": "even"}).status_code == 401
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    assert editeur.post("/generations/sources/mmi-previ", json={"semestre_group": "even"}).status_code == 403
    assert editeur.delete("/generations/sources/mmi-previ/even").status_code == 403
    assert serveur.requetes == []


def test_l_ecran_recupere_la_maquette_puis_revient_a_la_copie_livree(admin, serveur):
    avant = admin.get("/generations").json()
    assert avant["mmi_previ_configure"] is True
    assert {g["cle"]: g["source"]["origine"] for g in avant["groupes"]} == {
        "odd": "copie_livree",
        "even": "copie_livree",
    }

    reponse = admin.post("/generations/sources/mmi-previ", json={"semestre_group": "even"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["source"]["origine"] == "mmi_previ"
    assert corps["source"]["modules"] == 2
    assert [m["code"] for m in corps["differences"]["ajoutes"]] == ["WR401"]
    assert JETON not in reponse.text and "DUPONT" not in reponse.text

    apres = admin.get("/generations").json()
    pair = next(g for g in apres["groupes"] if g["cle"] == "even")
    assert pair["source"]["origine"] == "mmi_previ"
    assert pair["source"]["recuperee_le"]

    assert admin.delete("/generations/sources/mmi-previ/even").json()["source"] == {"origine": "copie_livree"}


def test_sans_jeton_l_ecran_le_dit(admin, serveur, monkeypatch):
    monkeypatch.delenv(mmi_previ.VAR_JETON)
    assert admin.get("/generations").json()["mmi_previ_configure"] is False
    reponse = admin.post("/generations/sources/mmi-previ", json={"semestre_group": "even"})
    assert reponse.status_code == 503
    assert mmi_previ.VAR_JETON in reponse.json()["detail"]


def test_un_jeton_refuse_remonte_en_clair(admin, serveur, monkeypatch):
    monkeypatch.setenv(mmi_previ.VAR_JETON, "mmip_perime")
    reponse = admin.post("/generations/sources/mmi-previ", json={"semestre_group": "even"})
    assert reponse.status_code == 502
    assert "expiré" in reponse.json()["detail"]
    assert "mmip_perime" not in reponse.text


def test_un_groupe_inconnu_est_refuse(admin, serveur):
    assert admin.post("/generations/sources/mmi-previ", json={"semestre_group": "S2"}).status_code == 422
    assert admin.delete("/generations/sources/mmi-previ/S2").status_code == 422
    assert serveur.requetes == []


def test_pas_de_changement_de_source_pendant_une_generation(admin, serveur, monkeypatch):
    # Le dépôt de ce test est vide : le contrôle « À régler avant de générer »
    # (lot 5) y verrait une maquette sans séance. Ce n'est pas le sujet ici.
    from cal_iut.generation import verification

    monkeypatch.setattr(verification, "avant_de_generer", lambda groupe: {"constats": []})
    assert admin.post("/generations", json={"semestre_group": "even"}).status_code == 201
    reponse = admin.post("/generations/sources/mmi-previ", json={"semestre_group": "even"})
    assert reponse.status_code == 409
    assert serveur.requetes == []


def test_pas_de_changement_de_source_pour_un_semestre_en_service(admin, serveur, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import state

    class _Depot:
        def runs_en_service(self):
            return [(SimpleNamespace(semestre="ODD", parcours="MMI"), 12)]

    monkeypatch.setattr(state, "get_repo", lambda: _Depot())
    reponse = admin.post("/generations/sources/mmi-previ", json={"semestre_group": "odd"})
    assert reponse.status_code == 409
    assert "en service" in reponse.json()["detail"]
    assert serveur.requetes == []
    # L'autre semestre, lui, reste modifiable.
    assert admin.post("/generations/sources/mmi-previ", json={"semestre_group": "even"}).status_code == 200
