"""JSON-RPC Streamable HTTP pour POST /mcp.

Le SDK officiel exige `session_manager.run()` dans le lifespan — TestClient
sans `with` ne l'ouvre pas. Ce handler sert initialize / tools sans ce
prérequis, tout en restant derrière le middleware Bearer.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from cal_iut.mcp.tools import apply, inspect, plan

_PROTOCOL = "2024-11-05"

_TOOLS = [
    {
        "name": "inspect",
        "description": (
            "Catalogue live (filtre enseignant / matière). Sans filtre : index compact. "
            "Avec filtre : séances + teachers/rooms/groups/weeks/unplaced/constraints + journal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "teacher_code": {"type": "string"},
                "course_code": {"type": "string"},
                "course_codes": {"type": "array", "items": {"type": "string"}},
                "session_type": {"type": "string"},
            },
        },
    },
    {
        "name": "plan",
        "description": (
            "Dry-run : chaque item ok | blocked | forceable. "
            "ops : place, move, swap, unplace, salle, seance, custom_create/patch/delete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "teacher_code": {"type": "string"},
                "course_code": {"type": "string"},
                "course_codes": {"type": "array", "items": {"type": "string"}},
                "session_type": {"type": "string"},
                "op": {"type": "string"},
                "duration_slots": {"type": "integer"},
                "slot": {"type": "integer"},
                "ops": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    {
        "name": "apply",
        "description": (
            "Appliquer un plan déjà montré (confirm=true). "
            "force seulement si l'item était forceable. Jamais sur blocking_conflicts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean"},
                "ops": {"type": "array", "items": {"type": "object"}},
                "plan_id": {"type": "string"},
            },
            "required": ["confirm", "ops"],
        },
    },
]


def _rpc_ok(req_id: object, result: object) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _rpc_err(req_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _appeler(nom: str, arguments: dict[str, Any]) -> object:
    if nom in ("inspect", "inspect_edt"):
        return inspect(
            teacher_code=arguments.get("teacher_code"),
            course_code=arguments.get("course_code"),
            course_codes=arguments.get("course_codes"),
            session_type=arguments.get("session_type"),
        )
    if nom in ("plan", "plan_edt"):
        return plan(
            teacher_code=arguments.get("teacher_code"),
            course_code=arguments.get("course_code"),
            course_codes=arguments.get("course_codes"),
            session_type=arguments.get("session_type"),
            op=arguments.get("op"),
            duration_slots=arguments.get("duration_slots"),
            slot=arguments.get("slot"),
            ops=arguments.get("ops"),
        )
    if nom in ("apply", "apply_edt"):
        return apply(
            confirm=bool(arguments.get("confirm", False)),
            ops=arguments.get("ops"),
            plan_id=arguments.get("plan_id"),
        )
    raise KeyError(nom)


async def handle_mcp_post(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, 400)
    if not isinstance(body, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}, 400)

    method = str(body.get("method") or "")
    req_id = body.get("id")
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    if method == "initialize":
        return _rpc_ok(req_id, {
            "protocolVersion": str(params.get("protocolVersion") or _PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "cal-iut", "version": "1.0.0"},
        })
    if method.startswith("notifications/"):
        return Response(status_code=202)
    if method == "ping":
        return _rpc_ok(req_id, {})
    if method == "tools/list":
        return _rpc_ok(req_id, {"tools": _TOOLS})
    if method == "tools/call":
        nom = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            resultat = _appeler(nom, arguments)
        except KeyError:
            return _rpc_err(req_id, -32601, f"Unknown tool: {nom}")
        except Exception as exc:  # noqa: BLE001 — renvoyé au client MCP
            return _rpc_ok(req_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        import json

        return _rpc_ok(req_id, {"content": [{"type": "text", "text": json.dumps(resultat, ensure_ascii=False)}]})
    return _rpc_err(req_id, -32601, f"Method not found: {method}")
