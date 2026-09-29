"""`POST /mcp` ne bloque plus la boucle d'événements — audit du 29/09/2026, P1-7.

`handle_mcp_post` (async) appelait l'outil synchrone directement : pendant un
`apply`, plus aucune requête n'était servie. L'outil tourne désormais dans le
pool de threads, avec le contexte de la requête (principal MCP).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

from starlette.requests import Request

from cal_iut.mcp import auth as mcp_auth
from cal_iut.mcp import http_rpc


def _requete(corps: dict) -> Request:
    brut = json.dumps(corps).encode()

    async def recevoir():
        return {"type": "http.request", "body": brut, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/mcp", "headers": []}, recevoir)


def test_l_outil_tourne_hors_de_la_boucle_et_ne_la_bloque_pas(monkeypatch) -> None:
    vus: dict[str, object] = {}

    def _outil_lent(nom, arguments):
        vus["thread"] = threading.get_ident()
        vus["principal"] = mcp_auth.get_mcp_principal()
        time.sleep(0.3)
        return {"ok": True}

    monkeypatch.setattr(http_rpc, "_appeler", _outil_lent)
    corps = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "inspect", "arguments": {}}}

    async def scenario():
        principal = mcp_auth.McpPrincipal(role="edit", via="env")
        jeton = mcp_auth.set_mcp_principal(principal)
        try:
            tic: list[float] = []

            async def horloge():
                # Tourne pendant l'appel : impossible si la boucle est bloquée.
                for _ in range(5):
                    tic.append(time.monotonic())
                    await asyncio.sleep(0.02)

            reponse, _ = await asyncio.gather(http_rpc.handle_mcp_post(_requete(corps)), horloge())
        finally:
            mcp_auth.reset_mcp_principal(jeton)
        return reponse, tic, threading.get_ident(), principal

    reponse, tic, thread_boucle, principal = asyncio.run(scenario())
    assert reponse.status_code == 200
    assert vus["thread"] != thread_boucle
    assert vus["principal"] == principal
    assert len(tic) == 5
    assert tic[-1] - tic[0] < 0.25, "la boucle d'événements a été bloquée pendant l'appel de l'outil"
