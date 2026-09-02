"""File d'attente des écritures Celcat (create / update / delete).

Le worker Docker consomme cette file. Le planning HTTP n'attend jamais
la réponse Live : `enfiler` est le seul geste immédiat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cal_iut.celcat.lecture import EvenementCelcat, est_fantome, est_ferie

_CONNUS: dict[int, EvenementCelcat] = {}


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_file_attente.json"


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


def _ecrire(jobs: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def enfiler(job: dict[str, Any]) -> None:
    jobs = _lire()
    jobs.append(dict(job))
    _ecrire(jobs)


def lister() -> list[dict[str, Any]]:
    return _lire()


def vider() -> None:
    _ecrire([])


def retenir_evenement(ev: EvenementCelcat) -> None:
    _CONNUS[ev.event_id] = ev


def evenement_connu(event_id: int) -> EvenementCelcat | None:
    return _CONNUS.get(event_id)


def autoriser_suppression(ev: EvenementCelcat, categorie: str | None = None) -> bool:
    retenir_evenement(ev)
    if est_ferie(ev) or est_fantome(ev):
        return False
    if ev.protected == "Y":
        return False
    if categorie == "celcat_en_plus":
        return False
    return True
