"""Serveur MCP Streamable HTTP monté sous `/mcp` sur l'app FastAPI."""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from cal_iut.mcp.tools import apply, inspect, plan

mcp = MCPServer("cal-iut")


@mcp.tool()
def inspect_edt(
    teacher_code: str | None = None,
    course_code: str | None = None,
    course_codes: list[str] | None = None,
    session_type: str | None = None,
) -> dict:
    """Catalogue live. Sans filtre : index compact. Avec teacher_code ou course_code : séances + catalogue + journal."""
    return inspect(
        teacher_code=teacher_code,
        course_code=course_code,
        course_codes=course_codes,
        session_type=session_type,
    )


@mcp.tool()
def plan_edt(
    teacher_code: str | None = None,
    course_code: str | None = None,
    course_codes: list[str] | None = None,
    session_type: str | None = None,
    op: str | None = None,
    duration_slots: int | None = None,
    slot: int | None = None,
    ops: list[dict] | None = None,
) -> dict:
    """Dry-run (ok | blocked | forceable). ops = place/move/swap/unplace/salle/seance/custom_*."""
    return plan(
        teacher_code=teacher_code,
        course_code=course_code,
        course_codes=course_codes,
        session_type=session_type,
        op=op,
        duration_slots=duration_slots,
        slot=slot,
        ops=ops,
    )


@mcp.tool()
def apply_edt(confirm: bool, ops: list[dict], plan_id: str | None = None) -> dict:
    """Appliquer un plan déjà montré. force seulement si l'item était forceable. Jamais blocking_conflicts."""
    return apply(confirm=confirm, ops=ops, plan_id=plan_id)


MCP_ASGI = mcp.streamable_http_app(
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "testserver",
            "testserver:*",
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
            "[::1]",
            "[::1]:*",
            "cal-iut-mmi.srko.fr",
            "cal-iut-mmi.srko.fr:*",
        ],
    ),
)
