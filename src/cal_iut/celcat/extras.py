"""Extras Live-only : cours présents dans Celcat, absents de cal-iut."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_extras.json"


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


def enregistrer(extra: dict[str, Any]) -> None:
    items = _lire()
    identifiant = extra.get("id")
    if identifiant is None:
        items.append(dict(extra))
        _ecrire(items)
        return
    for i, ligne in enumerate(items):
        if ligne.get("id") == identifiant:
            fusion = dict(ligne)
            fusion.update(extra)
            items[i] = fusion
            _ecrire(items)
            return
    items.append(dict(extra))
    _ecrire(items)


def lister(statut: str | None = None) -> list[dict[str, Any]]:
    items = _lire()
    if statut is None:
        return items
    return [x for x in items if x.get("statut") == statut]


def trouver(identifiant: str) -> dict[str, Any] | None:
    for ligne in _lire():
        if ligne.get("id") == identifiant:
            return dict(ligne)
    return None
