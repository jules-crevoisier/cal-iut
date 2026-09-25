"""Une colonne ajoutée à un modèle arrive dans une base DÉJÀ créée.

Panne du 25/09/2026, signalée par Jules : « les tâches, en production, elles
chargent à l'infini ». `Tache.concerne` avait été ajouté le matin ;
`create_all` ne touchant jamais une table existante, la colonne manquait dans
la base déployée et `GET /taches` répondait 500. Tous les tests passaient,
parce qu'ils partent tous d'une base neuve — d'où ces tests-ci, qui partent
au contraire d'une base ANCIENNE.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from cal_iut.db.session import get_engine, init_db

# Table « taches » telle qu'elle existait AVANT l'ajout de `concerne`
# (#177, 22/09/2026) — recopiée ici plutôt que produite par un `DROP COLUMN`,
# que le SQLite embarqué ne sait pas toujours faire.
TACHES_SANS_CONCERNE = """
CREATE TABLE taches (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    titre VARCHAR(200) NOT NULL,
    description TEXT,
    colonne VARCHAR(16) NOT NULL,
    ordre FLOAT NOT NULL,
    enseignant_code VARCHAR(16),
    date_debut DATE,
    date_fin DATE,
    cree_par VARCHAR(255) NOT NULL,
    cree_le DATETIME NOT NULL,
    maj_le DATETIME NOT NULL,
    fait_le DATETIME
)
"""


def _base_ancienne(chemin):
    init_db(chemin)
    moteur = get_engine(chemin)
    with moteur.begin() as c:
        c.execute(text("DROP TABLE taches"))
        c.execute(text(TACHES_SANS_CONCERNE))
    return moteur


def _colonnes(moteur, table: str) -> set[str]:
    return {col["name"] for col in inspect(moteur).get_columns(table)}


def test_une_colonne_ajoutee_apres_coup_est_creee(tmp_path) -> None:
    chemin = tmp_path / "ancienne.db"
    moteur = _base_ancienne(chemin)
    assert "concerne" not in _colonnes(moteur, "taches")

    init_db(chemin)  # redémarrage de l'application

    assert "concerne" in _colonnes(moteur, "taches")


def test_les_donnees_existantes_survivent(tmp_path) -> None:
    chemin = tmp_path / "avec_donnees.db"
    moteur = _base_ancienne(chemin)
    with moteur.begin() as c:
        c.execute(
            text(
                "INSERT INTO taches (titre, colonne, ordre, cree_par, cree_le, maj_le) "
                "VALUES ('Déplacer le TD', 'a_faire', 0, 'kyllian@iut', '2026-09-25', '2026-09-25')"
            )
        )

    init_db(chemin)

    with moteur.begin() as c:
        assert list(c.execute(text("SELECT titre, concerne FROM taches"))) == [("Déplacer le TD", None)]


def test_une_colonne_inconnue_du_modele_nest_pas_supprimee(tmp_path) -> None:
    """On ajoute, on ne retire jamais : une colonne en trop reste intacte."""
    chemin = tmp_path / "surnumeraire.db"
    init_db(chemin)
    moteur = get_engine(chemin)
    with moteur.begin() as c:
        c.execute(text("ALTER TABLE taches ADD COLUMN vestige TEXT"))

    init_db(chemin)

    assert "vestige" in _colonnes(moteur, "taches")


def test_rien_ne_bouge_sur_une_base_a_jour(tmp_path) -> None:
    chemin = tmp_path / "a_jour.db"
    init_db(chemin)
    moteur = get_engine(chemin)
    avant = {t: _colonnes(moteur, t) for t in inspect(moteur).get_table_names()}

    init_db(chemin)

    assert {t: _colonnes(moteur, t) for t in inspect(moteur).get_table_names()} == avant
