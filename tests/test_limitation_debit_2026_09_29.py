"""Limitation de débit des routes publiques d'authentification — audit du
29/09/2026, P1-3."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cal_iut.api import accounts, mailer, main
from cal_iut.api.limiteur import Limiteur
from cal_iut.api.state import get_state
from cal_iut.db.models import User
from cal_iut.db.session import get_db

EMAIL = "debit@example.test"
MDP = "Motdepasse123"


@pytest.fixture
def client(db_isole, monkeypatch):
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email", lambda *a, **k: "msg")
    db = get_db(get_state().db_path)
    try:
        db.add(User(email=EMAIL, password_hash=accounts.hash_password(MDP), role="edit", status="active"))
        db.commit()
    finally:
        db.close()
    return TestClient(main.app)


def test_fenetre_glissante(monkeypatch) -> None:
    horloge = [1000.0]
    monkeypatch.setattr("cal_iut.api.limiteur.time.monotonic", lambda: horloge[0])
    lim = Limiteur()
    for _ in range(3):
        lim.verifier("k", 3, 60)
    with pytest.raises(HTTPException) as erreur:
        lim.verifier("k", 3, 60)
    assert erreur.value.status_code == 429
    assert "Trop de tentatives" in erreur.value.detail
    assert erreur.value.headers["Retry-After"] == "60"
    horloge[0] += 61
    lim.verifier("k", 3, 60)  # la fenêtre a glissé


def test_force_brute_sur_un_email_bloquee(client) -> None:
    max_essais = main._LIMITE_LOGIN_EMAIL[0]
    for _ in range(max_essais):
        assert client.post("/auth/login", json={"email": EMAIL, "password": "mauvais-mdp"}).status_code == 401
    bloque = client.post("/auth/login", json={"email": EMAIL, "password": MDP})
    assert bloque.status_code == 429
    assert "Réessayez" in bloque.json()["detail"]
    assert "Retry-After" in bloque.headers


def test_une_connexion_reussie_remet_le_compteur_email_a_zero(client) -> None:
    for _ in range(main._LIMITE_LOGIN_EMAIL[0] - 1):
        client.post("/auth/login", json={"email": EMAIL, "password": "mauvais-mdp"})
    assert client.post("/auth/login", json={"email": EMAIL, "password": MDP}).status_code == 200
    assert client.post("/auth/login", json={"email": EMAIL, "password": "mauvais-mdp"}).status_code == 401


def test_force_brute_depuis_une_ip_sur_plusieurs_emails_bloquee(client) -> None:
    max_essais = main._LIMITE_LOGIN_IP[0]
    for n in range(max_essais):
        client.post("/auth/login", json={"email": f"x{n}@example.test", "password": "mauvais-mdp"})
    assert client.post("/auth/login", json={"email": EMAIL, "password": MDP}).status_code == 429


def test_signup_en_masse_sur_une_adresse_bloque(client) -> None:
    corps = {"email": "cible@example.test", "password": MDP}
    for _ in range(main._LIMITE_MAIL_EMAIL[0]):
        assert client.post("/auth/signup", json=corps).status_code == 201
    assert client.post("/auth/signup", json=corps).status_code == 429


def test_mot_de_passe_oublie_en_masse_bloque(client) -> None:
    for _ in range(main._LIMITE_MAIL_EMAIL[0]):
        assert client.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 200
    assert client.post("/auth/forgot-password", json={"email": EMAIL}).status_code == 429


def test_reinitialisation_en_masse_bloquee(client) -> None:
    corps = {"token": "jeton-invente", "new_password": "NouveauMotdepasse1"}
    for _ in range(main._LIMITE_RESET_IP[0]):
        assert client.post("/auth/reset-password", json=corps).status_code == 400
    assert client.post("/auth/reset-password", json=corps).status_code == 429
