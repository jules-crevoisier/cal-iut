"""Auth HTTP du MCP Streamable (`POST /mcp`) — jeton dédié, pas le cookie admin.

Règle verrouillée : `Authorization: Bearer CAL_IUT_MCP_TOKEN` est le SEUL
moyen d'authentifier le MCP. Un cookie de session admin valide ne suffit
jamais. Sans jeton configuré, l'endpoint est inutilisable (503) ; le login
site et `GET /app-state` restent inchangés.

Le jeton MCP n'est PAS posé en autouse (cf. `tests/conftest.py`) : chaque
test déclare lui-même s'il en a un.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state

_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
_TOKEN = "test-mcp-token-not-for-prod"


def _post_mcp(client: TestClient, extra_headers: dict[str, str] | None = None):
    headers = dict(_ACCEPT)
    if extra_headers:
        headers.update(extra_headers)
    return client.post("/mcp", json=_INIT, headers=headers)


def test_should_return_503_when_mcp_token_env_is_unset(monkeypatch):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    reponse = _post_mcp(client, {"Authorization": f"Bearer {_TOKEN}"})
    assert reponse.status_code == 503


def test_should_return_503_when_mcp_token_env_is_empty(monkeypatch):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", "")
    client = TestClient(app)
    reponse = _post_mcp(client, {"Authorization": "Bearer anything"})
    assert reponse.status_code == 503


def test_should_still_accept_site_login_when_mcp_token_env_is_unset(monkeypatch):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    reponse = client.post("/auth/login", json={"password": "test-password"})
    assert reponse.status_code == 200


def test_should_keep_app_state_reachable_when_mcp_token_env_is_unset(monkeypatch):
    # `state.timetable` est un singleton global partagé par TOUT le
    # processus pytest — sans le vider explicitement ici, ce test dépend de
    # ce qu'un test complètement différent, exécuté avant lui dans la suite
    # complète, a laissé dedans (potentiellement des objets qui ne
    # ressemblent pas du tout à une vraie séance, cf. `_build_app_context`
    # dans `api/main.py` qui suppose `p.session_id` sur chaque entrée). Un
    # `timetable` vide donne un 404 propre, ce que ce test accepte déjà
    # (seuls 401/503 sont exclus) — le rendre déterministe évite un
    # `AttributeError` aléatoire selon l'ordre d'exécution de la suite.
    etat = get_state()
    ancien_timetable = etat.timetable
    etat.timetable = []
    try:
        monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
        client = TestClient(app)
        client.post("/auth/login", json={"password": "test-password"})
        reponse = client.get("/app-state")
        assert reponse.status_code != 401
        assert reponse.status_code != 503
    finally:
        etat.timetable = ancien_timetable


def test_should_return_401_when_bearer_is_missing_even_if_admin_cookie_is_valid(monkeypatch):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", _TOKEN)
    client = TestClient(app)
    client.post("/auth/login", json={"password": "test-password"})
    reponse = _post_mcp(client)
    assert reponse.status_code == 401


def test_should_return_401_when_bearer_is_malformed_even_if_admin_cookie_is_valid(monkeypatch):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", _TOKEN)
    client = TestClient(app)
    client.post("/auth/login", json={"password": "test-password"})
    reponse = _post_mcp(client, {"Authorization": f"Token {_TOKEN}"})
    assert reponse.status_code == 401


def test_should_return_401_when_bearer_token_is_wrong_even_if_admin_cookie_is_valid(monkeypatch):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", _TOKEN)
    client = TestClient(app)
    client.post("/auth/login", json={"password": "test-password"})
    reponse = _post_mcp(client, {"Authorization": "Bearer wrong-token"})
    assert reponse.status_code == 401


def test_should_accept_mcp_when_bearer_matches_configured_token(monkeypatch):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", _TOKEN)
    client = TestClient(app)
    reponse = _post_mcp(client, {"Authorization": f"Bearer {_TOKEN}"})
    assert reponse.status_code == 200
