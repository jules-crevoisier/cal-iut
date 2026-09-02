"""Journal des actions Celcat (créé / modifié / supprimé / bloqué)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_logs.json"


def _lire() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(brut, list):
        return []
    return [x for x in brut if isinstance(x, dict)]


def _ecrire(items: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def append(
    *,
    kind: str,
    motif: str | None = None,
    session_id: str | None = None,
    event_id: int | None = None,
    course_code: str | None = None,
) -> None:
    items = _lire()
    items.append(
        {
            "kind": kind,
            "motif": motif,
            "session_id": session_id,
            "event_id": event_id,
            "course_code": course_code,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _ecrire(items)


def tous() -> list[dict[str, Any]]:
    return _lire()


def paginer(limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    items = list(reversed(_lire()))
    try:
        offset = int(cursor) if cursor else 0
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    page = items[offset : offset + max(1, limit)]
    suivant = offset + len(page)
    prochain = str(suivant) if suivant < len(items) else None
    return page, prochain
