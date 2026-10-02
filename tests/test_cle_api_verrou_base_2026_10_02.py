"""Une clé API ne doit jamais laisser la base verrouillée derrière elle.

Signalement d'origine (02/10/2026) : la production cessait de répondre à tout
le monde pendant une à huit minutes — `/health` compris, 504 côté proxy —
dès qu'un client ouvrait une dizaine de requêtes SIMULTANÉES avec une clé
« caliut_… ». Reproduit en local sur un vrai serveur : « database is locked »
sur `UPDATE mcp_keys SET last_used_at`, 40 s d'arrêt pour 9 requêtes ; avec
un cookie de session, 0,6 s et aucun effet.

Cause : `touch_mcp_key_si_ancien` n'écrit la date qu'une fois par minute.
Quand il n'y avait rien à écrire, l'UPDATE (zéro ligne) avait quand même
ouvert une transaction d'ÉCRITURE, jamais refermée : la session gardait le
verrou de la base jusqu'à la fin de la requête. La requête suivante,
authentifiée dans la boucle d'évènements, attendait ce verrou — et la
première ne pouvait finir que quand la boucle reprenait la main.
"""

from __future__ import annotations

import sqlite3

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.db.accounts_repository import AccountRepository
from cal_iut.db.session import get_db


@pytest.fixture
def cle(db_isole) -> dict:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    r = client.post("/auth/mcp-keys", json={"nom": "verrou"})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()


def _ecrire_depuis_une_autre_connexion() -> None:
    """Ce que ferait n'importe quelle autre requête : une écriture, sans
    attendre. Lève « database is locked » si quelqu'un garde le verrou."""
    autre = sqlite3.connect(str(get_state().db_path), timeout=0.2)
    try:
        autre.execute("UPDATE mcp_keys SET label = label")
        autre.commit()
    finally:
        autre.close()


def test_rien_a_ecrire_ne_garde_pas_le_verrou(cle) -> None:
    chemin = get_state().db_path
    premier = AccountRepository(get_db(chemin))
    premier.touch_mcp_key_si_ancien(cle["id"], 60)  # première utilisation : la date est écrite
    assert not premier.db.in_transaction()

    second = AccountRepository(get_db(chemin))  # moins d'une minute après : rien à écrire
    second.touch_mcp_key_si_ancien(cle["id"], 60)
    try:
        assert not second.db.in_transaction(), "transaction laissée ouverte"
        _ecrire_depuis_une_autre_connexion()
    finally:
        second.db.close()
        premier.db.close()


def test_la_date_n_est_ecrite_qu_une_fois_par_intervalle(cle) -> None:
    chemin = get_state().db_path
    repo = AccountRepository(get_db(chemin))
    try:
        repo.touch_mcp_key_si_ancien(cle["id"], 60)
        premiere = repo.db.execute(__import__("sqlalchemy").text("SELECT last_used_at FROM mcp_keys")).scalar()
        repo.db.rollback()
        repo.touch_mcp_key_si_ancien(cle["id"], 60)
        seconde = repo.db.execute(__import__("sqlalchemy").text("SELECT last_used_at FROM mcp_keys")).scalar()
        assert premiere is not None and seconde == premiere
        repo.db.rollback()
        repo.touch_mcp_key_si_ancien(cle["id"], 0)  # intervalle écoulé : réécrite
        troisieme = repo.db.execute(__import__("sqlalchemy").text("SELECT last_used_at FROM mcp_keys")).scalar()
        assert troisieme != premiere
    finally:
        repo.db.close()


def test_deux_requetes_avec_la_meme_cle_laissent_la_base_libre(cle) -> None:
    """Le chemin réel : l'authentification par clé, deux fois de suite, comme
    deux requêtes dont la première n'est pas encore terminée."""
    from starlette.requests import Request

    from cal_iut.api import main
    from cal_iut.db.session import portee_sessions

    def requete() -> Request:
        return Request({"type": "http", "method": "GET", "path": "/api/v1/version", "query_string": b"",
                        "headers": [(b"authorization", f"Bearer {cle['token']}".encode())]})

    with portee_sessions():  # la portée d'une requête encore en cours
        assert main._user_depuis_cle_api(requete()) is not None
        with portee_sessions():  # une seconde requête arrive pendant ce temps
            assert main._user_depuis_cle_api(requete()) is not None
            _ecrire_depuis_une_autre_connexion()
        _ecrire_depuis_une_autre_connexion()
