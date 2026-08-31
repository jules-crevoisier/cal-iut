"""Clés MCP par compte — brut une fois, hash en base, rôles honorés.

Le cookie de session n'authentifie jamais `/mcp`. Sans Bearer valide → 401
(plus de 503 « token env absent » : une clé user suffit). `read_only` peut
inspecter, pas plan/apply. Le jeton d'environnement reste un secours `edit`.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from cal_iut.api.main import app
from conftest import creer_compte_actif_et_connecter

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
_ENV_TOKEN = "test-mcp-env-token-not-for-prod"


def _post_mcp(client: TestClient, body: dict, bearer: str | None = None):
    headers = dict(_ACCEPT)
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return client.post("/mcp", json=body, headers=headers)


def _call_tool(client: TestClient, nom: str, arguments: dict, bearer: str):
    return _post_mcp(
        client,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": nom, "arguments": arguments},
        },
        bearer,
    )


def _creer_cle(client: TestClient) -> dict:
    reponse = client.post("/auth/mcp-keys")
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def test_should_create_mcp_key_with_caliut_prefix_and_never_return_raw_on_get(db_isole):
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    creee = _creer_cle(client)
    assert creee["token"].startswith("caliut_")
    assert creee["prefix"] == creee["token"][:12]
    assert "id" in creee

    liste = client.get("/auth/mcp-keys")
    assert liste.status_code == 200
    cles = liste.json()["keys"]
    assert len(cles) == 1
    assert "token" not in cles[0]
    assert cles[0]["prefix"] == creee["prefix"]
    assert cles[0]["id"] == creee["id"]


def test_should_accept_user_key_on_mcp_when_env_token_is_unset(monkeypatch, db_isole):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    token = _creer_cle(client)["token"]

    reponse = _post_mcp(client, _INIT, token)
    assert reponse.status_code == 200


def test_should_return_401_on_mcp_after_key_is_revoked(monkeypatch, db_isole):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    creee = _creer_cle(client)
    revoke = client.delete(f"/auth/mcp-keys/{creee['id']}")
    assert revoke.status_code == 200

    reponse = _post_mcp(client, _INIT, creee["token"])
    assert reponse.status_code == 401


def test_should_refuse_plan_and_apply_for_read_only_user_key(monkeypatch, db_isole):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="read_only")
    token = _creer_cle(client)["token"]

    inspect_ok = _call_tool(client, "inspect", {}, token)
    assert inspect_ok.status_code == 200
    inspect_body = inspect_ok.json()["result"]
    assert inspect_body.get("isError") is not True

    apply_ko = _call_tool(
        client,
        "apply",
        {"confirm": True, "ops": [{"op": "unplace", "session_id": "x", "status": "ok"}]},
        token,
    )
    assert apply_ko.status_code == 200
    apply_body = apply_ko.json()["result"]
    assert apply_body["isError"] is True
    payload = json.loads(apply_body["content"][0]["text"])
    assert payload["ok"] is False
    assert "lecture seule" in payload["error"].lower() or "permissions" in payload["error"].lower()

    plan_ko = _call_tool(client, "plan", {"ops": []}, token)
    assert plan_ko.status_code == 200
    plan_body = plan_ko.json()["result"]
    assert plan_body["isError"] is True


def test_should_keep_env_token_working_as_edit(monkeypatch, db_isole):
    monkeypatch.setenv("CAL_IUT_MCP_TOKEN", _ENV_TOKEN)
    client = TestClient(app)
    reponse = _post_mcp(client, _INIT, _ENV_TOKEN)
    assert reponse.status_code == 200

    plan_ok = _call_tool(client, "plan", {"ops": []}, _ENV_TOKEN)
    assert plan_ok.status_code == 200
    plan_body = plan_ok.json()["result"]
    assert plan_body.get("isError") is not True


def test_should_return_401_on_mcp_with_session_cookie_only(monkeypatch, db_isole):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    reponse = _post_mcp(client, _INIT)
    assert reponse.status_code == 401


def test_should_return_401_on_mcp_when_account_is_disabled(monkeypatch, db_isole):
    monkeypatch.delenv("CAL_IUT_MCP_TOKEN", raising=False)
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    moi = client.get("/auth/me").json()
    token = _creer_cle(client)["token"]

    from cal_iut.api.state import get_state
    from cal_iut.db.models import User
    from cal_iut.db.session import get_db

    db = get_db(get_state().db_path)
    try:
        user = db.get(User, moi["id"])
        assert user is not None
        user.status = "disabled"
        db.commit()
    finally:
        db.close()

    reponse = _post_mcp(client, _INIT, token)
    assert reponse.status_code == 401


def test_should_include_email_in_apply_journal_when_using_user_key(monkeypatch):
    from cal_iut.mcp import journal as mcp_journal
    from cal_iut.mcp import tools
    from cal_iut.mcp.auth import McpPrincipal, reset_mcp_principal, set_mcp_principal

    captured: list[dict] = []
    monkeypatch.setattr(tools, "_executer_item", lambda _item: None)
    monkeypatch.setattr(mcp_journal, "append", captured.append)
    jeton = set_mcp_principal(McpPrincipal(role="edit", via="user_key", email="prof@example.test", user_id=1))
    try:
        resultat = tools.apply(
            confirm=True,
            ops=[{"op": "unplace", "session_id": "s1", "status": "ok"}],
        )
    finally:
        reset_mcp_principal(jeton)
    assert resultat["ok"] is True
    assert captured[0]["email"] == "prof@example.test"


def test_should_omit_email_in_apply_journal_when_using_env_token(monkeypatch):
    from cal_iut.mcp import journal as mcp_journal
    from cal_iut.mcp import tools
    from cal_iut.mcp.auth import McpPrincipal, reset_mcp_principal, set_mcp_principal

    captured: list[dict] = []
    monkeypatch.setattr(tools, "_executer_item", lambda _item: None)
    monkeypatch.setattr(mcp_journal, "append", captured.append)
    jeton = set_mcp_principal(McpPrincipal(role="edit", via="env"))
    try:
        resultat = tools.apply(
            confirm=True,
            ops=[{"op": "unplace", "session_id": "s1", "status": "ok"}],
        )
    finally:
        reset_mcp_principal(jeton)
    assert resultat["ok"] is True
    assert "email" not in captured[0]


def test_should_allow_direct_apply_when_no_mcp_principal(monkeypatch):
    """Les tests d'outils appellent apply() hors HTTP : pas de principal → pas de refus."""
    from cal_iut.mcp import journal as mcp_journal
    from cal_iut.mcp import tools

    captured: list[dict] = []
    monkeypatch.setattr(tools, "_executer_item", lambda _item: None)
    monkeypatch.setattr(mcp_journal, "append", captured.append)
    resultat = tools.apply(
        confirm=True,
        ops=[{"op": "unplace", "session_id": "s1", "status": "ok"}],
    )
    assert resultat["ok"] is True
