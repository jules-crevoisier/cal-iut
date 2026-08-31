"""Génération des clés MCP par compte — brut une fois, hash SHA-256 en base."""

from __future__ import annotations

import hashlib
import secrets

MCP_TOKEN_PREFIX = "caliut_"
MCP_VISIBLE_PREFIX_LEN = 12
MCP_MAX_ACTIVE_KEYS = 5


def generate_raw_mcp_token() -> str:
    return MCP_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_mcp_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def visible_prefix(raw: str) -> str:
    return raw[:MCP_VISIBLE_PREFIX_LEN]
