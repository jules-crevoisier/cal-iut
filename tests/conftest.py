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
`data/.secret_key` au premier test qui l'utilise — un effet de bord sur le
disque du dépôt, inutile en test.
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
