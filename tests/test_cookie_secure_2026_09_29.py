"""Cookie de session `Secure` — audit du 29/09/2026, P1-1.

Les tests tournent sur `http://testserver` : `conftest.py` pose
`CAL_IUT_COOKIE_SECURE=0` (sinon le client HTTP ne renverrait jamais le
cookie). Ici on vérifie l'en-tête `Set-Cookie` lui-même, dans les deux cas.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import accounts
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.db.models import User
from cal_iut.db.session import get_db

EMAIL = "cookie@example.test"
MDP = "Motdepasse123"


@pytest.fixture
def compte(db_isole):
    db = get_db(get_state().db_path)
    try:
        db.add(User(email=EMAIL, password_hash=accounts.hash_password(MDP), role="edit", status="active"))
        db.commit()
    finally:
        db.close()


def _set_cookie(monkeypatch, valeur: str | None) -> str:
    if valeur is None:
        monkeypatch.delenv("CAL_IUT_COOKIE_SECURE", raising=False)
    else:
        monkeypatch.setenv("CAL_IUT_COOKIE_SECURE", valeur)
    reponse = TestClient(app).post("/auth/login", json={"email": EMAIL, "password": MDP})
    assert reponse.status_code == 200, reponse.text
    return reponse.headers["set-cookie"]


def test_le_cookie_est_secure_par_defaut(compte, monkeypatch) -> None:
    entete = _set_cookie(monkeypatch, None)
    assert "secure" in entete.lower()
    assert "httponly" in entete.lower()


def test_le_cookie_peut_etre_non_secure_en_developpement(compte, monkeypatch) -> None:
    entete = _set_cookie(monkeypatch, "0")
    assert "secure" not in entete.lower()


def test_la_deconnexion_efface_le_cookie_avec_les_memes_attributs(monkeypatch) -> None:
    monkeypatch.delenv("CAL_IUT_COOKIE_SECURE", raising=False)
    entete = TestClient(app).post("/auth/logout").headers["set-cookie"]
    assert accounts.ACCOUNT_SESSION_COOKIE in entete
    assert "secure" in entete.lower()
