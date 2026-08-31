"""Séances ajoutées depuis l'interface, en plus de celles de la maquette —
retour utilisateur 31/08/2026 : « il va falloir créer un système où l'on
peut créer des cours pour une matière [...] imaginons dans une matière on
veuille rajouter un CM éval ou un TD, il faut pouvoir le faire ».

Même architecture que les salles ajoutées (`api/custom_rooms.py`), pour la
même raison : stockées dans `data/state/custom_sessions.json`, PAS dans
`contraintes/*.json` (régénéré à chaque `cal-iut fetch`/rebuild) ni dans un
fichier de `data/config/` tenu à la main. `data/state/` est le volume
persistant — le seul endroit où une donnée saisie en production survit à un
redéploiement.

Une séance personnalisée porte `metadata["custom_session"] = True` — c'est
ce qui la distingue d'une séance de la maquette partout où le reste du code
en a besoin (affichage « ajoutée manuellement », droit à suppression : on
ne permet JAMAIS de supprimer une séance dont la maquette a la charge,
seulement celles créées ici).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "custom_sessions.json"


def load_custom_sessions() -> list[SessionToPlace]:
    path = _path()
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Fichier absent/corrompu = aucune séance ajoutée, jamais une erreur
        # qui empêcherait l'application entière de démarrer pour ça — même
        # principe que `custom_rooms.load_custom_rooms`.
        return []
    seances: list[SessionToPlace] = []
    for item in brut if isinstance(brut, list) else []:
        try:
            seances.append(
                SessionToPlace(
                    id=str(item["id"]),
                    course_code=str(item["course_code"]),
                    course_name=str(item["course_name"]),
                    semestre=str(item["semestre"]),
                    parcours=str(item["parcours"]),
                    annee=str(item["annee"]),
                    session_type=SessionType(item["session_type"]),
                    group_ids=list(item.get("group_ids", [])),
                    teacher_codes=list(item.get("teacher_codes", [])),
                    duration_slots=int(item.get("duration_slots", 1)),
                    is_eval=bool(item.get("is_eval", False)),
                    metadata={
                        "custom_session": True,
                        "note": item.get("note") or "",
                        "created_at": item.get("created_at"),
                    },
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # entrée illisible ignorée, les autres restent utilisables
    return seances


def _ecrire(seances: list[SessionToPlace]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "id": s.id,
                    "course_code": s.course_code,
                    "course_name": s.course_name,
                    "semestre": s.semestre,
                    "parcours": s.parcours,
                    "annee": s.annee,
                    "session_type": s.session_type.value,
                    "group_ids": list(s.group_ids),
                    "teacher_codes": list(s.teacher_codes),
                    "duration_slots": s.duration_slots,
                    "is_eval": s.is_eval,
                    "note": s.metadata.get("note") or "",
                    "created_at": s.metadata.get("created_at"),
                }
                for s in seances
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def add_custom_session(seance: SessionToPlace) -> None:
    existantes = load_custom_sessions()
    if any(s.id == seance.id for s in existantes):
        return
    seance.metadata.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    existantes.append(seance)
    _ecrire(existantes)


def update_custom_session(seance: SessionToPlace) -> bool:
    """Remplace l'entrée `seance.id` par la version fournie. Rend `False`
    si cette séance n'a jamais été créée par ce système — on ne modifie
    jamais ici une séance dont la maquette a la charge."""
    existantes = load_custom_sessions()
    for i, s in enumerate(existantes):
        if s.id == seance.id:
            seance.metadata.setdefault("created_at", s.metadata.get("created_at"))
            existantes[i] = seance
            _ecrire(existantes)
            return True
    return False


def remove_custom_session(session_id: str) -> bool:
    """Retire une séance personnalisée. Rend `False` si elle n'existait pas
    ici — jamais une erreur : l'état visé (séance absente) est déjà atteint,
    et surtout ça empêche qu'on supprime jamais autre chose qu'une séance
    créée par ce système."""
    existantes = load_custom_sessions()
    restantes = [s for s in existantes if s.id != session_id]
    if len(restantes) == len(existantes):
        return False
    _ecrire(restantes)
    return True


def merge_into(
    sessions: list[SessionToPlace], sessions_by_id: dict[str, SessionToPlace]
) -> tuple[list[SessionToPlace], dict[str, SessionToPlace]]:
    """Séances de la maquette + séances ajoutées, sans écraser un id déjà
    connu — la maquette gagne toujours (même logique que
    `custom_rooms.merge_into` pour les salles)."""
    connus = set(sessions_by_id)
    ajoutees = [s for s in load_custom_sessions() if s.id not in connus]
    if not ajoutees:
        return sessions, sessions_by_id
    fusion = dict(sessions_by_id)
    fusion.update({s.id: s for s in ajoutees})
    return sessions + ajoutees, fusion
