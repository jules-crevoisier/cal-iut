"""Décisions « C'est une Éval » / « Pas une Éval » sur les derniers CM.

Les enseignants n'ont pas tous coché « Éval » dans Previsio : le dernier CM
d'un module est proposé « à confirmer » dans Référence → Évaluations, et la
réponse de l'enseignant s'enregistre ici (Jules, 19/10/2026).

Volontairement SÉPARÉ de `session_overrides` : cocher `is_eval` change les
règles de salle (A.018 obligatoire) et peut déclencher un contrôle de
placement ; une simple réponse d'enseignant ne doit déplacer aucune séance ni
écrire dans Celcat. Même volume `data/state/`, écriture atomique.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat

Decision = Literal["eval", "pas_eval"]
DECISIONS: tuple[str, ...] = ("eval", "pas_eval")

_verrou = threading.RLock()


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "evaluations_validees.json"


def charger() -> dict[str, str]:
    brut = lire_json_etat(_path(), {}, types=dict)
    return {str(k): v for k, v in brut.items() if v in DECISIONS}


def enregistrer(session_id: str, decision: Decision | None) -> None:
    """`None` : revient à « à confirmer » (annule la décision)."""
    with _verrou:
        existantes = charger()
        if decision is None:
            existantes.pop(session_id, None)
        else:
            existantes[session_id] = decision
        ecrire_json(_path(), existantes)
