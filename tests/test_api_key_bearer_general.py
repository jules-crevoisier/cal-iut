"""Une clé `caliut_…` (onglet « Clé API », ex-« Clés MCP ») authentifie
maintenant N'IMPORTE QUELLE route protégée, pas seulement `/mcp`.

Retour utilisateur 05/09/2026 : l'accès programmatique à la production
(`cal-iut prod diff/pull/push`) exigeait jusqu'ici email + mot de passe du
compte admin — l'utilisateur ne voulait pas donner ses identifiants
personnels et a demandé la possibilité de créer une clé dédiée à la place.
Plutôt que construire un second système de clés, `require_auth` (le
middleware général) accepte désormais le même Bearer que `/mcp` : même
table, même hash, même rôle relu sur le compte, même révocation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cal_iut.api.main import app
from conftest import creer_compte_actif_et_connecter


def _creer_cle(client: TestClient) -> dict:
    reponse = client.post("/auth/mcp-keys")
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def test_should_accept_api_key_bearer_on_a_general_protected_route(db_isole) -> None:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    token = _creer_cle(client)["token"]

    anonyme = TestClient(app)
    reponse = anonyme.get("/placements/manquantes", headers={"Authorization": f"Bearer {token}"})
    assert reponse.status_code == 200, reponse.text


def test_should_return_401_without_cookie_or_bearer_on_a_general_protected_route() -> None:
    anonyme = TestClient(app)
    reponse = anonyme.get("/placements/manquantes")
    assert reponse.status_code == 401


def test_should_return_401_on_a_general_route_after_the_key_is_revoked(db_isole) -> None:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    creee = _creer_cle(client)
    assert client.delete(f"/auth/mcp-keys/{creee['id']}").status_code == 200

    anonyme = TestClient(app)
    reponse = anonyme.get("/placements/manquantes", headers={"Authorization": f"Bearer {creee['token']}"})
    assert reponse.status_code == 401


def test_should_honor_the_key_owner_role_on_a_general_route(db_isole) -> None:
    """Une clé lecture seule reste lecture seule partout, pas seulement sur /mcp."""
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="read_only")
    token = _creer_cle(client)["token"]

    anonyme = TestClient(app)
    lecture = anonyme.get("/placements/manquantes", headers={"Authorization": f"Bearer {token}"})
    assert lecture.status_code == 200

    ecriture = anonyme.post(
        "/placements/manquante/placer",
        json={"week": 0, "day": 0, "slot": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ecriture.status_code == 403


def test_should_return_401_on_a_general_route_when_the_bearer_key_is_unknown(db_isole) -> None:
    anonyme = TestClient(app)
    reponse = anonyme.get(
        "/placements/manquantes", headers={"Authorization": "Bearer caliut_ceci-nexiste-pas"}
    )
    assert reponse.status_code == 401


def test_should_still_accept_the_session_cookie_on_a_general_route(db_isole) -> None:
    """Le Bearer s'ajoute, il ne remplace rien : le cookie continue de marcher seul."""
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    reponse = client.get("/placements/manquantes")
    assert reponse.status_code == 200
