"""État persisté de la sync Celcat (`data/state/celcat_sync.json`).

Le journal v1 était un dictionnaire plat `session_id → {signature, …}`.
La v2 l'enveloppe sous `journal` et y ajoute l'interrupteur de saisie,
les semaines validées pour le job de nuit, et les files annexes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cal_iut.celcat.lecture import EvenementCelcat

_LIVE: list[EvenementCelcat] = []


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_sync.json"


def _vide() -> dict[str, Any]:
    return {
        "version": 2,
        "saisie_active": False,
        "semaines_validees": [],
        "valide_le": None,
        "journal": {},
        "ignores": {},
        "extras": [],
        "logs": [],
        "queue": [],
        "dernier_job": None,
    }


def _est_v1(data: dict[str, Any]) -> bool:
    if data.get("version") == 2:
        return False
    journal = data.get("journal")
    if isinstance(journal, dict) and (
        "saisie_active" in data or "semaines_validees" in data or "version" in data
    ):
        return False
    return "journal" not in data


def _migrer_v1(data: dict[str, Any]) -> dict[str, Any]:
    doc = _vide()
    journal: dict[str, Any] = {}
    for session_id, row in data.items():
        if not isinstance(row, dict):
            continue
        ligne = dict(row)
        ligne["session_id"] = str(ligne.get("session_id") or session_id)
        journal[str(session_id)] = ligne
    doc["journal"] = journal
    return doc


def _completer(data: dict[str, Any]) -> dict[str, Any]:
    doc = _vide()
    doc.update(data)
    doc["version"] = 2
    doc["saisie_active"] = bool(doc.get("saisie_active"))
    semaines = doc.get("semaines_validees")
    doc["semaines_validees"] = [int(s) for s in semaines] if isinstance(semaines, list) else []
    journal = doc.get("journal")
    if not isinstance(journal, dict):
        journal = {}
    for session_id, row in list(journal.items()):
        if not isinstance(row, dict):
            continue
        if "session_id" not in row:
            row = dict(row)
            row["session_id"] = session_id
            journal[session_id] = row
    doc["journal"] = journal
    if not isinstance(doc.get("ignores"), dict):
        doc["ignores"] = {}
    if not isinstance(doc.get("extras"), list):
        doc["extras"] = []
    if not isinstance(doc.get("logs"), list):
        doc["logs"] = []
    if not isinstance(doc.get("queue"), list):
        doc["queue"] = []
    return doc


def charger() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return _vide()
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _vide()
    if not isinstance(brut, dict):
        return _vide()
    if _est_v1(brut):
        doc = _migrer_v1(brut)
        sauver(doc)
        return doc
    return _completer(brut)


def sauver(doc: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def definir_live(evenements: list[EvenementCelcat]) -> None:
    _LIVE.clear()
    _LIVE.extend(evenements)


def live_actuel() -> list[EvenementCelcat]:
    return list(_LIVE)
