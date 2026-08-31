"""Réexport des outils MCP — les tests importent `tools` ou `ops`."""

from cal_iut.mcp.tools import apply, inspect, plan

__all__ = ["inspect", "plan", "apply"]
