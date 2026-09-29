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
`data/state/mail_log.json`/`data/state/.secret_key`) plutôt qu'une table SQL dédiée :
état administratif léger (quelques entrées à la fois), pas une donnée de
planning à part entière.
"""

from __future__ import annotations

import threading
from pathlib import Path

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat

# Lecture-modification-écriture sous verrou (audit du 29/09/2026, P0-4).
_verrou = threading.RLock()


def _path() -> Path:
    # `data/state/`, pas `data/` directement — cf. `api/state.py::DB_PATH`
    # pour pourquoi (config vs état, volume Docker).
    return Path(__file__).resolve().parents[3] / "data" / "state" / "forced_pending.json"


def _load() -> dict[str, dict[str, int]]:
    # Illisible = mis de côté puis `FichierEtatIllisible`, jamais `{}`
    # (audit du 29/09/2026, P0-4).
    return lire_json_etat(_path(), {}, types=dict)


def _save(data: dict[str, dict[str, int]]) -> None:
    ecrire_json(_path(), data, sort_keys=True)


def mark(session_id: str, week: int, day: int, slot: int) -> None:
    with _verrou:
        data = _load()
        data[session_id] = {"week": week, "day": day, "slot": slot}
        _save(data)


def clear(session_id: str) -> None:
    with _verrou:
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
