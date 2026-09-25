"""Session SQLite."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cal_iut.db.models import Base

# `data/state/`, pas `data/` directement — cf. commentaire équivalent dans
# `api/state.py::DB_PATH` (même constante, dupliquée ici pour ce module
# utilisable indépendamment).
DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "state" / "cal-iut.db"

_engine = None
_SessionLocal = None


def get_engine(db_path: Path | None = None):
    global _engine, _SessionLocal
    path = db_path or DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{path}"
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def init_db(db_path: Path | None = None) -> None:
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _ajouter_colonnes_manquantes(engine)


def _ajouter_colonnes_manquantes(engine) -> None:
    """Ajoute les colonnes qu'un modèle a gagnées depuis la création de sa table.

    `create_all` ne crée que les tables ABSENTES : il ne touche jamais une
    table existante. Une colonne ajoutée à un modèle n'existe donc pas dans la
    base déjà déployée, et la première lecture casse — panne réelle du
    25/09/2026 : `Tache.concerne` ajouté le matin, `GET /taches` en erreur 500
    en production l'après-midi (« les tâches chargent à l'infini »), alors que
    tous les tests passaient sur des bases neuves.

    Volontairement minimal : seulement des colonnes NULLABLES ajoutées en fin
    de table (`ALTER TABLE ... ADD COLUMN`, ce que SQLite sait faire sans
    réécrire la table). Aucune suppression, aucun renommage, aucun changement
    de type — tout ça reste une migration à écrire à la main, et la base
    n'est jamais modifiée en silence au-delà de cet ajout.
    """
    from sqlalchemy import inspect, text

    inspecteur = inspect(engine)
    with engine.begin() as connexion:
        for table in Base.metadata.sorted_tables:
            if not inspecteur.has_table(table.name):
                continue
            presentes = {c["name"] for c in inspecteur.get_columns(table.name)}
            for colonne in table.columns:
                if colonne.name in presentes or not colonne.nullable or colonne.primary_key:
                    continue
                type_sql = colonne.type.compile(engine.dialect)
                connexion.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{colonne.name}" {type_sql}')
                )


def get_db(db_path: Path | None = None) -> Session:
    if _SessionLocal is None:
        get_engine(db_path)
    assert _SessionLocal is not None
    return _SessionLocal()
