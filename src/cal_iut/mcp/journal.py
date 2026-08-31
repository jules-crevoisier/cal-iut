"""Journal MCP — ce que l'agent a appliqué, pour la génération suivante.

Pas une contrainte solveur : les placements vivent déjà dans SQLite +
overlays + custom_sessions. Ce fichier documente *qui a changé quoi* via
inspect/plan/apply, pour qu'un regen/solve suivant voie l'intention.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAX = 200


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "mcp_journal.json"


def lire() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(brut, list):
        return []
    return [e for e in brut if isinstance(e, dict)]


def append(entree: dict[str, Any]) -> None:
    historique = lire()
    historique.append(entree)
    historique = historique[-_MAX:]
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(historique, ensure_ascii=False, indent=2), encoding="utf-8")
