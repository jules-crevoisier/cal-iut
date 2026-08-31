"""Overlay persisté des séances de maquette (enseignant / type / durée).

Distinct de `custom_sessions` : on ne crée pas de séance, on ne fait que
remplacer quelques champs d'une séance dont la maquette a la charge. Même
volume `data/state/` — survit à un redéploiement, pas à un `cal-iut fetch`
des YAML de config.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "session_overrides.json"


def load_overrides() -> dict[str, dict[str, Any]]:
    path = _path()
    if not path.exists():
        return {}
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(brut, dict):
        return {}
    return {str(k): v for k, v in brut.items() if isinstance(v, dict)}


def upsert_overlay(session_id: str, champs: dict[str, Any]) -> None:
    existants = load_overrides()
    actuel = dict(existants.get(session_id, {}))
    actuel.update(champs)
    existants[session_id] = actuel
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existants, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_to(sessions_by_id: dict[str, SessionToPlace]) -> None:
    """Applique l'overlay sur les séances déjà chargées (maquette + custom)."""
    for sid, champs in load_overrides().items():
        seance = sessions_by_id.get(sid)
        if seance is None:
            continue
        if "teacher_codes" in champs and isinstance(champs["teacher_codes"], list):
            seance.teacher_codes = [str(c) for c in champs["teacher_codes"]]
        if "session_type" in champs:
            try:
                seance.session_type = SessionType(str(champs["session_type"]))
            except ValueError:
                continue
        if "duration_slots" in champs:
            try:
                seance.duration_slots = int(champs["duration_slots"])
            except (TypeError, ValueError):
                continue
        if "is_eval" in champs:
            seance.is_eval = bool(champs["is_eval"])
