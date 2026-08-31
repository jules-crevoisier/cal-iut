"""Jeton Bearer dédié au MCP — jamais le mot de passe site ni le cookie admin."""

from __future__ import annotations

import hmac
import os

from fastapi import Request
from starlette.responses import JSONResponse, Response


def get_mcp_token() -> str | None:
    brut = os.environ.get("CAL_IUT_MCP_TOKEN")
    if brut is None:
        return None
    jeton = brut.strip()
    return jeton or None


async def mcp_bearer_middleware(request: Request, call_next) -> Response:
    if not request.url.path.startswith("/mcp"):
        return await call_next(request)
    jeton = get_mcp_token()
    if not jeton:
        return JSONResponse(
            status_code=503,
            content={"detail": "MCP non configuré (CAL_IUT_MCP_TOKEN absent)."},
        )
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Jeton MCP invalide."})
    fourni = auth[7:]
    if len(fourni) != len(jeton) or not hmac.compare_digest(fourni, jeton):
        return JSONResponse(status_code=401, content={"detail": "Jeton MCP invalide."})
    return await call_next(request)
