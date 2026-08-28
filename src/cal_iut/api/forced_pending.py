"""Placements posés en forçant l'ordre pédagogique — restent visibles dans
« À placer » jusqu'à validation explicite, pour qu'on puisse revenir en
arrière facilement (retour utilisateur 28/08/2026, après avoir forcé le
placement d'un CM coincé par une fenêtre pédagogique saturée : « une fois le
cm placé il faut le laisser dans la liste pour peut-être revenir en
arrière, et il faut peut-être un bouton valider »).

Scope volontairement étroit : seuls les placements qui ont dû CONTOURNER
l'ordre pédagogique (`_pedagogical_order_violations`, cf. `main.py`) sont
suivis ici — pas tout usage de `force` (un conflit de ressources forcé
existe depuis longtemps dans l'app sans que personne n'ait demandé ce
garde-fou pour lui).

Persisté dans un petit fichier JSON (même traitement que
`data/mail_log.json`/`data/.secret_key`) plutôt qu'une table SQL dédiée :
état administratif léger (quelques entrées à la fois), pas une donnée de
planning à part entière.
"""

from __future__ import annotations

import json
from pathlib import Path


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "forced_pending.json"


def _load() -> dict[str, dict[str, int]]:
    path = _path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, dict[str, int]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def mark(session_id: str, week: int, day: int, slot: int) -> None:
    data = _load()
    data[session_id] = {"week": week, "day": day, "slot": slot}
    _save(data)


def clear(session_id: str) -> None:
    data = _load()
    if session_id in data:
        del data[session_id]
        _save(data)


def get(session_id: str) -> dict[str, int] | None:
    return _load().get(session_id)


def all_pending() -> dict[str, dict[str, int]]:
    return _load()


def sync_after_move(session_id: str, week: int, day: int, slot: int, still_violates_pedagogical_order: bool) -> None:
    """Appelé après CHAQUE déplacement/placement réussi (forcé ou non) d'une
    séance déjà suivie ou nouvellement forcée — tient le journal à jour sans
    dupliquer cette logique aux 2 points d'appel (`move_session`,
    `placer_seance`). Un placement qui ne viole plus l'ordre pédagogique
    n'a plus rien à surveiller ; un qui le viole encore (déplacé ailleurs,
    toujours en force) garde son entrée à jour avec la nouvelle position."""
    if still_violates_pedagogical_order:
        mark(session_id, week, day, slot)
    else:
        clear(session_id)
