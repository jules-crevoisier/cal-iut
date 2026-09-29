"""Sessions révocables — audit du 29/09/2026, P1-2.

Avant : le cookie ne portait que `user_id.expiration.signature` ; un cookie
volé restait valable 30 jours après une réinitialisation du mot de passe.
Après : `User.session_version` est incluse dans le cookie signé et
incrémentée à la réinitialisation (et à la confirmation d'email).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from cal_iut.api import accounts, mailer
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.db.models import User
from cal_iut.db.session import get_db, init_db

EMAIL = "revocable@example.test"
MDP = "Motdepasse123"
NOUVEAU = "NouveauMotdepasse456"


@pytest.fixture
def user_id(db_isole) -> int:
    db = get_db(get_state().db_path)
    try:
        user = User(email=EMAIL, password_hash=accounts.hash_password(MDP), role="edit", status="active")
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def _connecte() -> TestClient:
    client = TestClient(app)
    assert client.post("/auth/login", json={"email": EMAIL, "password": MDP}).status_code == 200
    assert client.get("/auth/me").status_code == 200
    return client


def _reinitialiser(monkeypatch) -> None:
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    boite: list[str] = []
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html=None: boite.append(text))
    anonyme = TestClient(app)
    assert anonyme.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 200
    jeton = re.search(r"token=([^&\s]+)", boite[-1]).group(1)
    r = anonyme.post("/auth/reset-password", json={"token": jeton, "new_password": NOUVEAU})
    assert r.status_code == 200, r.text


def test_un_cookie_emis_avant_la_reinitialisation_est_refuse(user_id, monkeypatch) -> None:
    vole = _connecte()
    _reinitialiser(monkeypatch)
    assert vole.get("/auth/me").status_code == 401
    assert vole.get("/taches").status_code == 401


def test_une_nouvelle_connexion_apres_reinitialisation_fonctionne(user_id, monkeypatch) -> None:
    _reinitialiser(monkeypatch)
    client = TestClient(app)
    assert client.post("/auth/login", json={"email": EMAIL, "password": NOUVEAU}).status_code == 200
    assert client.get("/auth/me").status_code == 200


def test_la_version_est_signee(user_id) -> None:
    jeton = accounts.make_account_session_token(user_id, 0)
    uid, version, expiry, sig = jeton.split(".")
    falsifie = f"{uid}.{int(version) + 1}.{expiry}.{sig}"
    assert accounts.lire_jeton_session(falsifie) is None


def test_un_ancien_cookie_sans_version_vaut_version_zero(user_id, monkeypatch) -> None:
    """Pas de déconnexion générale au déploiement, mais l'ancien format ne
    survit pas à une réinitialisation."""
    import time

    payload = f"{user_id}.{int(time.time()) + 3600}"
    ancien = f"{payload}.{accounts._sign(payload)}"
    client = TestClient(app)
    client.cookies.set(accounts.ACCOUNT_SESSION_COOKIE, ancien)
    assert client.get("/auth/me").status_code == 200
    _reinitialiser(monkeypatch)
    assert client.get("/auth/me").status_code == 401


def test_la_colonne_est_ajoutee_a_une_base_existante(tmp_path) -> None:
    """Base déployée avant le correctif : `users` sans `session_version`."""
    chemin = tmp_path / "ancienne.db"
    moteur = create_engine(f"sqlite:///{chemin}")
    with moteur.begin() as c:
        c.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(255), "
            "role VARCHAR(16), status VARCHAR(32), created_at DATETIME, email_confirmed_at DATETIME, "
            "activated_at DATETIME, activated_by INTEGER)"
        ))
        c.execute(text("INSERT INTO users (email, password_hash, role, status) VALUES ('a@b.c', 'x', 'edit', 'active')"))
    moteur.dispose()
    init_db(chemin)
    moteur = create_engine(f"sqlite:///{chemin}")
    assert "session_version" in {c["name"] for c in inspect(moteur).get_columns("users")}
    with moteur.begin() as c:
        assert c.execute(text("SELECT session_version FROM users")).scalar() is None
    moteur.dispose()
