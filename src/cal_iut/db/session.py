"""Session SQLite.

UN moteur par fichier de base, créé une fois puis réutilisé (audit du
29/09/2026, P1-9). Avant : `get_repo()` appelait `init_db()` à CHAQUE appel,
qui recréait un moteur, un pool, puis rejouait `create_all` et l'inspection
de toutes les tables — 5,8 ms et un moteur neuf par appel, 25 appels dans
`api/main.py`.

Réglages SQLite, posés sur chaque connexion :

- `journal_mode=WAL` : les lecteurs ne bloquent plus l'écrivain (deux
  processus écrivent la même base : `backend` et `celcat-nuit`) ;
- `busy_timeout` : une écriture qui trouve la base verrouillée attend au
  lieu d'échouer aussitôt en « database is locked ».

`NullPool` : chaque `Session` ouvre sa connexion SQLite (quelques dizaines de
microsecondes) et la ferme en se refermant. Un pool classique plafonne le
nombre de connexions ouvertes (15 par défaut) : les `Session` que le code
ne referme pas explicitement (`get_repo()` en garde plusieurs par requête)
l'épuiseraient sous charge, et les requêtes suivantes attendraient 30 s.

Fermeture : `get_db` inscrit chaque `Session` dans la portée ouverte par
`portee_sessions()` (une par requête HTTP, cf. `api/main.py`), qui les
referme toutes à la fin de la requête.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from cal_iut.db.models import Base

# `data/state/`, pas `data/` directement — cf. commentaire équivalent dans
# `api/state.py::DB_PATH` (même constante, dupliquée ici pour ce module
# utilisable indépendamment).
DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "state" / "cal-iut.db"

BUSY_TIMEOUT_MS = 10_000

# Dernier moteur servi — conservé pour compatibilité (tests et scripts qui
# lisent ou remettent à zéro `db_session._engine`/`_SessionLocal`).
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None

_moteurs: dict[str, Engine] = {}
_fabriques: dict[str, sessionmaker] = {}
_initialisees: set[str] = set()
_verrou = threading.Lock()

_sessions_de_la_portee: ContextVar[list[Session] | None] = ContextVar(
    "cal_iut_sessions_db", default=None
)


def _cle(path: Path) -> str:
    return str(Path(path).resolve())


def _pragmas(connexion_dbapi, _enregistrement) -> None:
    curseur = connexion_dbapi.cursor()
    try:
        curseur.execute("PRAGMA journal_mode=WAL")
        curseur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    finally:
        curseur.close()


def _moteur_et_fabrique(db_path: Path | None) -> tuple[Engine, sessionmaker]:
    path = Path(db_path or DEFAULT_DB)
    cle = _cle(path)
    with _verrou:
        moteur = _moteurs.get(cle)
        if moteur is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            moteur = create_engine(
                f"sqlite:///{path}",
                connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000},
                poolclass=NullPool,
            )
            event.listen(moteur, "connect", _pragmas)
            _moteurs[cle] = moteur
            _fabriques[cle] = sessionmaker(bind=moteur, autoflush=False, autocommit=False)
        return moteur, _fabriques[cle]


def get_engine(db_path: Path | None = None) -> Engine:
    """Moteur (mis en cache) de `db_path`, qui devient aussi le moteur par
    défaut de `get_db()` sans argument."""
    global _engine, _SessionLocal
    moteur, fabrique = _moteur_et_fabrique(db_path)
    _engine, _SessionLocal = moteur, fabrique
    return moteur


def init_db(db_path: Path | None = None) -> None:
    """Crée les tables absentes et ajoute les colonnes manquantes. Toujours
    exécuté en entier quand on l'appelle (démarrage, tests) ; pour un appel
    répété sur un chemin déjà prêt, passer par `init_db_une_fois`."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _ajouter_colonnes_manquantes(engine)
    _initialisees.add(_cle(Path(db_path or DEFAULT_DB)))


def init_db_une_fois(db_path: Path | None = None) -> None:
    """`init_db` seulement si ce chemin n'a pas encore été préparé par ce
    processus (ou si le fichier a disparu depuis)."""
    path = Path(db_path or DEFAULT_DB)
    if _cle(path) in _initialisees and path.exists():
        return
    init_db(path)


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
    """Nouvelle `Session` sur `db_path` (ou, sans argument, sur le dernier
    moteur servi, à défaut `DEFAULT_DB`). Refermée à la fin de la portée
    `portee_sessions()` en cours s'il y en a une ; sinon à l'appelant."""
    if db_path is None:
        if _SessionLocal is None:
            get_engine(None)
        assert _SessionLocal is not None
        session = _SessionLocal()
    else:
        session = _moteur_et_fabrique(db_path)[1]()
    portee = _sessions_de_la_portee.get()
    if portee is not None:
        portee.append(session)
    return session


@contextmanager
def portee_sessions() -> Iterator[None]:
    """Referme, en sortant, toutes les `Session` ouvertes par `get_db`
    pendant la portée — y compris depuis les threads du pool de Starlette,
    qui héritent du contexte de la requête."""
    jeton = _sessions_de_la_portee.set([])
    try:
        yield
    finally:
        sessions = _sessions_de_la_portee.get() or []
        _sessions_de_la_portee.reset(jeton)
        for session in sessions:
            try:
                session.close()
            except Exception:  # noqa: BLE001, S110 — fermer les autres quoi qu'il arrive
                pass
