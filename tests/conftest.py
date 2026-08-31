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
