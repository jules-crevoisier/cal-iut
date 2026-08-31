"""Jeton Bearer dédié au MCP — jamais le mot de passe site ni le cookie de session.

Deux origines possibles, même header `Authorization: Bearer …` :
- `CAL_IUT_MCP_TOKEN` d'environnement (secours machine, rôle `edit`)
- clé user `caliut_…` (hash SHA-256 en base, rôle relu sur le compte)

Sans Bearer valide → 401. Le cookie de compte n'est jamais consulté ici.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class McpPrincipal:
    role: str
    via: Literal["env", "user_key"]
    email: str | None = None
    user_id: int | None = None
    key_id: int | None = None


_principal: ContextVar[McpPrincipal | None] = ContextVar("mcp_principal", default=None)


def get_mcp_principal() -> McpPrincipal | None:
    return _principal.get()


def set_mcp_principal(principal: McpPrincipal | None) -> Token:
    return _principal.set(principal)


def reset_mcp_principal(jeton: Token) -> None:
    _principal.reset(jeton)


def get_mcp_token() -> str | None:
    brut = os.environ.get("CAL_IUT_MCP_TOKEN")
    if brut is None:
        return None
    jeton = brut.strip()
    return jeton or None


def _principal_env(fourni: str) -> McpPrincipal | None:
    jeton = get_mcp_token()
    if not jeton or len(fourni) != len(jeton):
        return None
    if not hmac.compare_digest(fourni, jeton):
        return None
    return McpPrincipal(role="edit", via="env")


def _principal_cle_user(fourni: str) -> McpPrincipal | None:
    from cal_iut.api.state import get_state
    from cal_iut.db.accounts_repository import AccountRepository
    from cal_iut.db.session import get_db, init_db

    token_hash = hashlib.sha256(fourni.encode()).hexdigest()
    init_db(get_state().db_path)
    db = get_db(get_state().db_path)
    try:
        repo = AccountRepository(db)
        cle = repo.get_active_mcp_key_by_hash(token_hash)
        if cle is None:
            return None
        user = repo.get_by_id(cle.user_id)
        if user is None or user.status != "active":
            return None
        repo.touch_mcp_key(cle)
        return McpPrincipal(
            role=user.role,
            via="user_key",
            email=user.email,
            user_id=user.id,
            key_id=cle.id,
        )
    finally:
        db.close()


def authentifier_bearer(fourni: str) -> McpPrincipal | None:
    return _principal_env(fourni) or _principal_cle_user(fourni)


async def mcp_bearer_middleware(request: Request, call_next) -> Response:
    if not request.url.path.startswith("/mcp"):
        return await call_next(request)
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Jeton MCP invalide."})
    principal = authentifier_bearer(auth[7:])
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Jeton MCP invalide."})
    jeton = set_mcp_principal(principal)
    try:
        return await call_next(request)
    finally:
        reset_mcp_principal(jeton)
