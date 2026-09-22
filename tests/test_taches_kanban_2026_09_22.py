"""Kanban « Tâches » (22/09/2026, retour utilisateur Jules) : « on voudrait
une partie kanban pour les choses à faire, exemple : ce prof a dit qu'il ne
serait pas présent ce jour, déplacer ». Tableau partagé pour le suivi des
tâches HUMAINES (l'équipe se le passait par mail jusqu'ici) — distinct de
« À traiter » (`TodoView`, problèmes de qualité de données détectés
automatiquement), qui reste inchangé.

Contrat verrouillé (cf. prompt de session) : modèle `Tache` (`db/models.py`),
`PlanningRepository.{create,list,update,delete}_tache` (`db/repository.py`),
schémas `Tache*` (`api/schemas.py`), endpoints `/taches*` (`api/main.py`).

Style et isolation : même patron que `tests/test_api_key_bearer_general.py`
(fixture `db_isole` + `conftest.creer_compte_actif_et_connecter`).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cal_iut.api.main import app
from conftest import creer_compte_actif_et_connecter


def _client_edit(db_isole) -> TestClient:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    return client


# --------------------------------------------------------------------------
# Création de la table sur une base existante.
# --------------------------------------------------------------------------


def test_should_create_the_taches_table_on_startup_without_breaking_an_existing_db(tmp_path):
    """`init_db` (`create_all`) doit ajouter la table `taches` sur un fichier
    SQLite EXISTANT (déjà peuplé par d'autres tables) sans lever ni perdre de
    données — même garantie que pour toute nouvelle table (cf. `db/session.py`,
    contrat de session : « vérifier sur une copie d'un fichier DB existant que
    le démarrage ne casse pas »)."""
    import sqlalchemy as sa

    from cal_iut.db import session as db_session
    from cal_iut.db.models import PlanningRun
    from cal_iut.db.session import get_db, init_db

    db_path = tmp_path / "existante.db"
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(db_path)  # 1ère génération : sans la table taches dans le schéma "ancien" simulé
    db = get_db(db_path)
    db.add(PlanningRun(parcours="BUT1", semestre="S1", status="OPTIMAL"))
    db.commit()
    db.close()

    # Redémarrage (nouveau process simulé) : re-appelle init_db comme au boot.
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(db_path)

    inspecteur = sa.inspect(db_session._engine)
    assert "taches" in inspecteur.get_table_names()

    db2 = get_db(db_path)
    assert db2.query(PlanningRun).count() == 1  # rien perdu
    db2.close()
    db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None


# --------------------------------------------------------------------------
# CRUD.
# --------------------------------------------------------------------------


def test_should_create_and_list_a_tache(db_isole):
    client = _client_edit(db_isole)

    reponse = client.post("/taches", json={"titre": "Prévenir Kyllian, absent jeudi"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["titre"] == "Prévenir Kyllian, absent jeudi"
    assert corps["colonne"] == "a_faire"
    assert corps["cree_par"]
    assert corps["fait_le"] is None

    liste = client.get("/taches")
    assert liste.status_code == 200
    assert len(liste.json()) == 1
    assert liste.json()[0]["id"] == corps["id"]


def test_should_create_a_tache_with_all_optional_fields(db_isole):
    client = _client_edit(db_isole)

    reponse = client.post(
        "/taches",
        json={
            "titre": "Déplacer le TD de KBR",
            "description": "Absent le 25/09, à replacer ailleurs dans la semaine.",
            "colonne": "en_cours",
            "enseignant_code": "KBR",
            "date_debut": "2026-09-25",
            "date_fin": "2026-09-25",
        },
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["enseignant_code"] == "KBR"
    assert corps["date_debut"] == "2026-09-25"
    assert corps["date_fin"] == "2026-09-25"
    assert corps["colonne"] == "en_cours"


def test_should_update_a_tache_column_and_order(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "Tâche à déplacer"}).json()

    reponse = client.patch(f"/taches/{cree['id']}", json={"colonne": "en_cours", "ordre": 3.5})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["colonne"] == "en_cours"
    assert corps["ordre"] == 3.5


def test_should_delete_a_tache(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "À supprimer"}).json()

    reponse = client.delete(f"/taches/{cree['id']}")
    assert reponse.status_code == 200
    assert client.get("/taches").json() == []


def test_should_404_updating_an_unknown_tache(db_isole):
    client = _client_edit(db_isole)
    assert client.patch("/taches/999999", json={"titre": "x"}).status_code == 404


def test_should_404_deleting_an_unknown_tache(db_isole):
    client = _client_edit(db_isole)
    assert client.delete("/taches/999999").status_code == 404


# --------------------------------------------------------------------------
# `fait_le` — posé à l'entrée dans "fait", effacé à la sortie.
# --------------------------------------------------------------------------


def test_fait_le_is_set_when_moved_to_fait_and_cleared_when_moved_out(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "Tâche à terminer"}).json()
    assert cree["fait_le"] is None

    terminee = client.patch(f"/taches/{cree['id']}", json={"colonne": "fait"}).json()
    assert terminee["fait_le"] is not None

    reouverte = client.patch(f"/taches/{cree['id']}", json={"colonne": "a_faire"}).json()
    assert reouverte["fait_le"] is None


def test_creating_directly_in_fait_sets_fait_le(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "Déjà faite", "colonne": "fait"}).json()
    assert cree["fait_le"] is not None


# --------------------------------------------------------------------------
# Validation.
# --------------------------------------------------------------------------


def test_should_reject_an_empty_titre(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post("/taches", json={"titre": "   "})
    assert reponse.status_code == 422


def test_should_reject_a_titre_over_200_chars(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post("/taches", json={"titre": "x" * 201})
    assert reponse.status_code == 422


def test_should_reject_date_fin_before_date_debut_on_create(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post(
        "/taches",
        json={"titre": "Dates inversées", "date_debut": "2026-09-25", "date_fin": "2026-09-20"},
    )
    assert reponse.status_code == 422


def test_should_reject_date_fin_before_date_debut_on_update(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "T", "date_debut": "2026-09-20", "date_fin": "2026-09-20"}).json()
    reponse = client.patch(f"/taches/{cree['id']}", json={"date_fin": "2026-09-01"})
    assert reponse.status_code == 422


def test_should_reject_an_unknown_colonne(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post("/taches", json={"titre": "T", "colonne": "quelque_part"})
    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# Auth : 401 anonyme, 403 read_only en écriture, read_only peut lire.
# --------------------------------------------------------------------------


def test_should_return_401_anonymous(db_isole):
    client = TestClient(app)
    assert client.get("/taches").status_code == 401
    assert client.post("/taches", json={"titre": "T"}).status_code == 401


def test_should_return_403_for_read_only_on_write_routes(db_isole):
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="read_only")

    assert client.post("/taches", json={"titre": "T"}).status_code == 403

    # Une tâche créée par un autre compte, pour tester PATCH/DELETE en 403.
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    cree = editeur.post("/taches", json={"titre": "T"}).json()

    assert client.patch(f"/taches/{cree['id']}", json={"titre": "y"}).status_code == 403
    assert client.delete(f"/taches/{cree['id']}").status_code == 403


def test_read_only_can_list_taches(db_isole):
    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    editeur.post("/taches", json={"titre": "T"})

    lecteur = TestClient(app)
    creer_compte_actif_et_connecter(lecteur, role="read_only")
    reponse = lecteur.get("/taches")
    assert reponse.status_code == 200
    assert len(reponse.json()) == 1
