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


# Plafond du journal. Un fichier qui ne cesse de grossir finit par coûter
# plus cher qu'il ne rend service, et c'est le RÉCENT qu'on consulte : au-delà,
# les plus anciennes entrées sont écartées.
MAX_ENTREES = 2000


def append(
    *,
    kind: str,
    motif: str | None = None,
    session_id: str | None = None,
    event_id: int | None = None,
    course_code: str | None = None,
    regrouper: bool = False,
) -> None:
    """Ajoute une ligne au journal.

    `regrouper` : réservé aux ÉCHECS. Le worker repasse toutes les 30 à 60
    secondes et retente les jobs en échec, qui restent en file par
    conception — journaliser chaque tentative écrirait des centaines de
    milliers de lignes identiques par jour. Une même séance qui échoue pour
    la même raison occupe donc UNE ligne, dont on met à jour l'horodatage et
    le compteur de tentatives : « échoue depuis 14h, 87 tentatives » est
    aussi plus utile que 87 lignes jumelles.

    Jamais pour les réussites : deux créations de la même séance sont deux
    évènements réels, à des moments différents.
    """
    items = _lire()
    maintenant = datetime.now(timezone.utc).isoformat()

    if regrouper:
        for item in reversed(items):
            if (
                item.get("kind") == kind
                and item.get("session_id") == session_id
                and item.get("motif") == motif
            ):
                item["at"] = maintenant
                item["repetitions"] = int(item.get("repetitions") or 1) + 1
                _ecrire(items)
                return

    items.append(
        {
            "kind": kind,
            "motif": motif,
            "session_id": session_id,
            "event_id": event_id,
            "course_code": course_code,
            "at": maintenant,
            **({"repetitions": 1} if regrouper else {}),
        }
    )
    _ecrire(items[-MAX_ENTREES:])


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
