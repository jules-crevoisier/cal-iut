"""Deux onglets au-dessus du kanban « Tâches » et une urgence par carte.

Contrat verrouillé (cf. prompt de session, Jules dicté 25/09/2026) : « je
voudrais bien dans l'onglet Tâches mettre au-dessus deux petits boutons qui
seraient des onglets : entre les affaires par rapport à l'emploi du temps
[...] et les affaires à propos de la plateforme [...] je ne sais pas aussi
s'il y a des statuts urgents ou pas, etc., mais il faudrait le faire. »

`categorie` ("edt" | "plateforme", défaut "edt") et `priorite` ("normale" |
"urgente", défaut "normale") sur `Tache` (`db/models.py`) — colonnes
NULLABLES ajoutées automatiquement au démarrage par
`db/session.py::_ajouter_colonnes_manquantes` (cf. docstring : panne du
25/09/2026 sur `Tache.concerne`), jamais de migration à la main.

Style et isolation : même patron que `test_taches_kanban_2026_09_22.py`.
"""

from __future__ import annotations

import sqlalchemy as sa
from test_taches_kanban_2026_09_22 import _client_edit  # type: ignore[import-not-found]

from cal_iut.api.state import get_state
from cal_iut.db import session as db_session
from cal_iut.db.models import Tache
from cal_iut.db.session import get_db, init_db

# --------------------------------------------------------------------------
# Défauts et champs, création / liste / patch.
# --------------------------------------------------------------------------


def test_should_default_to_edt_and_normale_on_create(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "Sans catégorie précisée"}).json()
    assert cree["categorie"] == "edt"
    assert cree["priorite"] == "normale"


def test_should_create_a_tache_with_categorie_and_priorite(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post(
        "/taches",
        json={"titre": "Bug export Celcat", "categorie": "plateforme", "priorite": "urgente"},
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["categorie"] == "plateforme"
    assert corps["priorite"] == "urgente"


def test_list_taches_returns_categorie_and_priorite(db_isole):
    client = _client_edit(db_isole)
    client.post("/taches", json={"titre": "T", "categorie": "plateforme"})
    liste = client.get("/taches").json()
    assert liste[0]["categorie"] == "plateforme"
    assert liste[0]["priorite"] == "normale"


def test_should_patch_categorie_and_priorite(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "À reclasser"}).json()

    maj = client.patch(f"/taches/{cree['id']}", json={"categorie": "plateforme", "priorite": "urgente"})
    assert maj.status_code == 200, maj.text
    corps = maj.json()
    assert corps["categorie"] == "plateforme"
    assert corps["priorite"] == "urgente"


# --------------------------------------------------------------------------
# Validation — valeurs inconnues, messages en français.
# --------------------------------------------------------------------------


def test_should_reject_an_unknown_categorie_on_create(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post("/taches", json={"titre": "T", "categorie": "autre_chose"})
    assert reponse.status_code == 422
    assert "atégorie" in reponse.text  # message français, pas le message anglais par défaut de Literal


def test_should_reject_an_unknown_priorite_on_create(db_isole):
    client = _client_edit(db_isole)
    reponse = client.post("/taches", json={"titre": "T", "priorite": "haute"})
    assert reponse.status_code == 422
    assert "riorité" in reponse.text


def test_should_reject_an_unknown_categorie_on_patch(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "T"}).json()
    reponse = client.patch(f"/taches/{cree['id']}", json={"categorie": "autre_chose"})
    assert reponse.status_code == 422


def test_should_reject_an_unknown_priorite_on_patch(db_isole):
    client = _client_edit(db_isole)
    cree = client.post("/taches", json={"titre": "T"}).json()
    reponse = client.patch(f"/taches/{cree['id']}", json={"priorite": "haute"})
    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# Ligne antérieure à ce changement — pas de crash, lue comme "edt"/"normale".
# --------------------------------------------------------------------------


def test_legacy_tache_without_categorie_or_priorite_reads_as_edt_normale(db_isole):
    """Une ligne insérée SANS `categorie` ni `priorite` (comme une tâche
    créée avant ce changement, `categorie=None`/`priorite=None` en base
    depuis l'ajout automatique de colonne) doit être lue comme "edt" /
    "normale" partout, jamais planter — contrat explicite de la session."""
    db = get_db(get_state().db_path)
    row = Tache(titre="Ancienne tâche", colonne="a_faire", ordre=0.0, cree_par="prof@example.test")
    db.add(row)
    db.commit()
    tache_id = row.id
    db.close()

    client = _client_edit(db_isole)
    reponse = client.get("/taches")
    assert reponse.status_code == 200, reponse.text
    cible = next(t for t in reponse.json() if t["id"] == tache_id)
    assert cible["categorie"] == "edt"
    assert cible["priorite"] == "normale"

    # Un PATCH qui ne touche ni l'un ni l'autre doit aussi rester lisible.
    maj = client.patch(f"/taches/{tache_id}", json={"titre": "Ancienne tâche (renommée)"})
    assert maj.status_code == 200, maj.text
    assert maj.json()["categorie"] == "edt"
    assert maj.json()["priorite"] == "normale"


# --------------------------------------------------------------------------
# Migration automatique — colonnes ajoutées sur une base déjà déployée.
# --------------------------------------------------------------------------


def test_should_add_categorie_and_priorite_columns_to_an_existing_taches_table(tmp_path):
    """Une base qui a déjà la table `taches` SANS `categorie`/`priorite`
    (schéma d'avant ce changement) doit les gagner au démarrage suivant,
    sans perdre les lignes existantes — même garantie que la panne réelle du
    25/09/2026 documentée dans `db/session.py::_ajouter_colonnes_manquantes`
    (`Tache.concerne` ajouté le matin, `GET /taches` en 500 l'après-midi)."""
    db_path = tmp_path / "sans_categorie_priorite.db"
    db_session._engine = None
    db_session._SessionLocal = None

    # Schéma "ancien" simulé : la table `taches` existe déjà, sans les deux
    # nouvelles colonnes, avec une ligne déjà en place.
    ancien_moteur = sa.create_engine(f"sqlite:///{db_path}")
    with ancien_moteur.begin() as connexion:
        connexion.execute(
            sa.text(
                """
                CREATE TABLE taches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titre VARCHAR(200) NOT NULL,
                    description TEXT,
                    colonne VARCHAR(16) NOT NULL,
                    ordre FLOAT NOT NULL,
                    enseignant_code VARCHAR(16),
                    concerne VARCHAR(64),
                    date_debut DATE,
                    date_fin DATE,
                    cree_par VARCHAR(255) NOT NULL,
                    cree_le DATETIME NOT NULL,
                    maj_le DATETIME NOT NULL,
                    fait_le DATETIME
                )
                """
            )
        )
        connexion.execute(
            sa.text(
                "INSERT INTO taches (titre, colonne, ordre, cree_par, cree_le, maj_le) "
                "VALUES ('Ancienne tâche', 'a_faire', 0.0, 'prof@example.test', "
                "'2026-09-01T00:00:00', '2026-09-01T00:00:00')"
            )
        )
    ancien_moteur.dispose()

    # Redémarrage (nouveau process simulé) : re-appelle init_db comme au boot.
    init_db(db_path)

    inspecteur = sa.inspect(db_session._engine)
    colonnes = {c["name"] for c in inspecteur.get_columns("taches")}
    assert "categorie" in colonnes
    assert "priorite" in colonnes

    db = get_db(db_path)
    ligne = db.query(Tache).filter(Tache.titre == "Ancienne tâche").one()
    assert ligne.categorie is None  # colonne ajoutée nullable, sans défaut SQL
    assert ligne.priorite is None
    db.close()

    db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None
