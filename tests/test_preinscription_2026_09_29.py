"""Prise de contrôle d'un compte par pré-inscription — audit du 29/09/2026, P0-3.

Scénario corrigé : un tiers s'inscrit avec l'adresse d'un collègue et SON
mot de passe ; le collègue s'inscrit ensuite (201, lien de confirmation
reçu) puis confirme. Avant : le compte gardait le mot de passe du tiers.
Après : le mot de passe appliqué est celui de l'inscription qui a émis le
lien confirmé.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import accounts, mailer
from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.db.models import User
from cal_iut.db.session import get_db

VICTIME = "collegue@example.test"
MDP_ATTAQUANT = "MotDePasseAttaquant1"
MDP_VICTIME = "MotDePasseVictime22"


@pytest.fixture
def client(db_isole, monkeypatch):
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    boite: list[str] = []
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html=None: boite.append(text))
    c = TestClient(app)
    c.boite = boite  # type: ignore[attr-defined]
    return c


def _dernier_jeton(client) -> str:
    m = re.search(r"token=([^&\s]+)", client.boite[-1])
    assert m
    return m.group(1)


def _activer(email: str) -> None:
    db = get_db(get_state().db_path)
    try:
        user = db.query(User).filter(User.email == email).one()
        user.status = "active"
        user.role = "edit"
        db.commit()
    finally:
        db.close()


def _signup(client, password: str) -> str:
    r = client.post("/auth/signup", json={"email": VICTIME, "password": password})
    assert r.status_code == 201, r.text
    return _dernier_jeton(client)


def test_le_mot_de_passe_du_preinscrit_ne_survit_pas_a_la_confirmation(client) -> None:
    _signup(client, MDP_ATTAQUANT)
    jeton_victime = _signup(client, MDP_VICTIME)
    assert client.get("/auth/confirm-email", params={"token": jeton_victime}, follow_redirects=False).status_code == 302
    _activer(VICTIME)

    attaquant = client.post("/auth/login", json={"email": VICTIME, "password": MDP_ATTAQUANT})
    assert attaquant.status_code == 401
    victime = client.post("/auth/login", json={"email": VICTIME, "password": MDP_VICTIME})
    assert victime.status_code == 200, victime.text


def test_une_reinscription_posterieure_ne_change_pas_le_mot_de_passe_confirme(client) -> None:
    """Le tiers se réinscrit APRÈS la victime (avant qu'elle clique) : son
    inscription invalide le lien de la victime, qui n'a donc rien à
    confirmer avec — et aucun des deux mots de passe n'ouvre un compte
    non confirmé."""
    jeton_victime = _signup(client, MDP_VICTIME)
    _signup(client, MDP_ATTAQUANT)
    r = client.get("/auth/confirm-email", params={"token": jeton_victime}, follow_redirects=False)
    assert "statut=erreur" in r.headers["location"]
    db = get_db(get_state().db_path)
    try:
        assert db.query(User).filter(User.email == VICTIME).one().status == "pending_email"
    finally:
        db.close()


def test_le_jeton_porte_le_mot_de_passe_de_son_inscription(client) -> None:
    jeton = _signup(client, MDP_VICTIME)
    # Même si le hash du compte est modifié entre-temps, c'est celui du
    # jeton confirmé qui s'applique.
    db = get_db(get_state().db_path)
    try:
        user = db.query(User).filter(User.email == VICTIME).one()
        user.password_hash = accounts.hash_password(f"autre-{uuid.uuid4().hex}")
        db.commit()
    finally:
        db.close()
    client.get("/auth/confirm-email", params={"token": jeton}, follow_redirects=False)
    _activer(VICTIME)
    assert client.post("/auth/login", json={"email": VICTIME, "password": MDP_VICTIME}).status_code == 200
