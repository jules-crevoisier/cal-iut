"""Verrou unique d'écriture du planning (audit 29/09/2026, P1-4).

Les routes d'écriture sont des `def` synchrones, exécutées en parallèle dans
le pool de threads de Starlette. Sans verrou, « valider puis écrire » n'est
pas atomique : deux personnes posent deux séances dans la même salle au même
créneau, les deux validations passent, les deux écritures aussi.

Règle : toute route (ou outil MCP) qui MODIFIE le planning en mémoire
(`state.timetable`, `state.sessions`, `state.sessions_by_id`) le fait sous
`verrou_planning`. Les lectures ne le prennent pas.

`RLock` (réentrant) et non `Lock` : une route d'écriture en appelle d'autres
(`creer_seance_personnalisee` -> `placer_seance`, `lissage.appliquer` ->
`move_session`, MCP `apply` -> chaque route) ; le même thread reprend le
verrou sans se bloquer lui-même.

Les calculs longs (régénération de semaine, lissage, solveur) ne le tiennent
PAS pendant la résolution : ils calculent sur un instantané, puis prennent le
verrou le temps de la fusion (cf. `api/regen.py`).
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import TypeVar

verrou_planning = threading.RLock()

F = TypeVar("F", bound=Callable[..., object])


def ecriture_planning(fn: F) -> F:
    """Exécute `fn` sous le verrou d'écriture du planning.

    Se place SOUS le décorateur de route (`@app.patch(...)` puis
    `@ecriture_planning`) : FastAPI lit la signature de la fonction d'origine
    (`functools.wraps` pose `__wrapped__`). Pas une dépendance `Depends` à
    `yield` : FastAPI peut en exécuter l'entrée et la sortie dans deux threads
    différents du pool, et un `RLock` ne se libère que depuis le thread qui l'a
    pris."""

    @functools.wraps(fn)
    def _sous_verrou(*args: object, **kwargs: object) -> object:
        with verrou_planning:
            return fn(*args, **kwargs)

    return _sous_verrou  # type: ignore[return-value]
