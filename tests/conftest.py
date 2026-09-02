"""Config partagée pytest — un seul souci pour l'instant : le mot de passe
partagé (`src/cal_iut/api/auth.py`, retour utilisateur 28/08/2026) bloque
maintenant TOUTES les routes API par défaut. Sans ce fixture, les tests
utilisant `TestClient(app)` (test_alternance_fc_2026_08_27.py,
test_ordre_meme_semaine_2026_08_27.py, test_placement_manuel.py)
recevraient un 503 systématique (« Authentification non configurée ») —
`CAL_IUT_PASSWORD` doit être positionné AVANT que `TestClient(app)` ne
déclenche l'import de l'appli, donc en session-scoped/autouse ici plutôt
que dans chaque fichier.

`CAL_IUT_SECRET_KEY` fixé aussi : sans lui, `auth.get_secret()` écrirait
`data/state/.secret_key` au premier test qui l'utilise — un effet de bord
sur le disque du dépôt, inutile en test.
"""

import os

import pytest

os.environ.setdefault("CAL_IUT_PASSWORD", "test-password")
os.environ.setdefault("CAL_IUT_SECRET_KEY", "test-secret-key-not-for-prod")


@pytest.fixture
def auth_password() -> str:
    """Mot de passe de test — à passer à `client.post("/auth/login", ...)`
    dans les fixtures `TestClient` existantes plutôt que de dupliquer la
    valeur en dur partout."""
    return os.environ["CAL_IUT_PASSWORD"]


@pytest.fixture
def db_isole(tmp_path):
    """Bascule `state.db_path` vers un fichier SQLite temporaire pour la
    durée du test, puis restaure à la fin — à demander explicitement
    (paramètre de fixture, ex. `def client(db_isole):`) dans tout test qui
    appelle `creer_compte_actif_et_connecter`, sans quoi ce compte de test
    atterrirait dans la vraie `data/state/cal-iut.db` du dépôt (committée,
    cf. `.gitignore` : `!data/state/cal-iut.db`)."""
    import uuid

    from cal_iut.api.state import get_state
    from cal_iut.db import session as db_session
    from cal_iut.db.session import init_db

    etat = get_state()
    ancien_db_path = etat.db_path
    db_path = tmp_path / f"isole_{uuid.uuid4().hex}.db"
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(db_path)
    etat.db_path = db_path
    yield
    etat.db_path = ancien_db_path
    if db_session._engine:
        db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None


def creer_compte_actif_et_connecter(client, role: str = "edit") -> None:
    """Remplace l'ancien login au mot de passe partagé (`CAL_IUT_PASSWORD`,
    supprimé le 31/08/2026 par le cutover comptes utilisateurs, cf.
    `api/accounts.py`) dans les fixtures qui montent un état de test à la
    main : crée un compte ACTIF du rôle donné dans `state.db_path` COURANT
    (à la fixture appelante de l'isoler d'abord vers un `tmp_path`, sans
    quoi ce compte de test atterrirait dans la vraie `data/state/cal-iut.db`
    du dépôt — cf. `tests/test_comptes_utilisateurs.py::_isolation` pour le
    patron), puis connecte `client` avec.

    Email tiré au sort (uuid) : ce même helper peut être appelé plusieurs
    fois dans la même base (plusieurs tests d'un même fichier partageant un
    `db_path` non ré-isolé par test) sans jamais entrer en collision avec la
    contrainte `unique=True` de `User.email`.
    """
    import uuid

    from cal_iut.api import accounts
    from cal_iut.api.state import get_state
    from cal_iut.db.models import User
    from cal_iut.db.session import get_db, init_db

    etat = get_state()
    init_db(etat.db_path)
    email = f"test-{role}-{uuid.uuid4().hex}@example.test"
    db = get_db(etat.db_path)
    try:
        db.add(User(
            email=email, password_hash=accounts.hash_password("Motdepasse123"),
            role=role, status="active",
        ))
        db.commit()
    finally:
        db.close()
    reponse = client.post("/auth/login", json={"email": email, "password": "Motdepasse123"})
    assert reponse.status_code == 200, reponse.text


@pytest.fixture(autouse=True)
def _fichiers_etat_isoles(tmp_path, monkeypatch):
    """Isole TOUS les petits fichiers JSON d'état persisté (`api/mailer.py`,
    `api/forced_pending.py`) vers un répertoire temporaire — sans ça,
    n'importe quel test qui force un placement (ordre pédagogique) ou envoie
    un mail écrirait dans le VRAI `data/state/mail_log.json`/`data/state/
    forced_pending.json` du dépôt. Autouse : la pollution serait sinon aussi
    facile à introduire par erreur dans un futur test que le bug qu'elle
    évite est difficile à remarquer après coup."""
    from cal_iut.api import custom_rooms, custom_sessions, forced_pending, mailer

    monkeypatch.setattr(mailer, "_log_path", lambda: tmp_path / "mail_log.json")
    monkeypatch.setattr(forced_pending, "_path", lambda: tmp_path / "forced_pending.json")
    monkeypatch.setattr(custom_rooms, "_path", lambda: tmp_path / "custom_rooms.json")
    monkeypatch.setattr(custom_sessions, "_path", lambda: tmp_path / "custom_sessions.json")
    # Overlay maquette (PATCH /placements/{id}/seance) — le module n'existe
    # pas encore au moment du TDD ; dès qu'il est là, l'isoler comme le reste.
    try:
        from cal_iut.api import session_overrides
    except ImportError:
        session_overrides = None
    if session_overrides is not None:
        monkeypatch.setattr(session_overrides, "_path", lambda: tmp_path / "session_overrides.json")
    try:
        from cal_iut.mcp import journal as mcp_journal
    except ImportError:
        mcp_journal = None
    if mcp_journal is not None:
        monkeypatch.setattr(mcp_journal, "_path", lambda: tmp_path / "mcp_journal.json")
    # Journal / réglages Celcat — même fichier que le sync historique.
    try:
        from cal_iut.celcat import sync as celcat_sync
    except ImportError:
        celcat_sync = None
    if celcat_sync is not None and hasattr(celcat_sync, "_path"):
        monkeypatch.setattr(celcat_sync, "_path", lambda: tmp_path / "celcat_sync.json")
    for nom_mod, fichier in (
        ("etat", "celcat_sync.json"),
        ("file_attente", "celcat_file_attente.json"),
        ("logs", "celcat_logs.json"),
        ("extras", "celcat_extras.json"),
        ("nuit", "celcat_sync.json"),
    ):
        try:
            module = __import__(f"cal_iut.celcat.{nom_mod}", fromlist=["*"])
        except ImportError:
            continue
        if hasattr(module, "_path"):
            monkeypatch.setattr(module, "_path", lambda f=fichier: tmp_path / f)
