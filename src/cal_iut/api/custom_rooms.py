"""Salles ajoutées depuis l'interface, en plus de celles du bâtiment —
retour utilisateur 28/08/2026 : « il se peut que l'on utilise des salles
autres que dans le bâtiment, il faut donc laisser la possibilité de créer
une salle ».

Stockées dans `data/state/custom_rooms.json`, PAS dans `data/config/
rooms.yaml`, pour deux raisons distinctes :

1. `data/config/` est rafraîchi depuis l'image à CHAQUE déploiement (cf.
   Dockerfile, séparation config/état) — une salle créée depuis l'interface
   y serait écrasée au premier redéploiement. `data/state/` est le volume
   persistant, c'est le seul endroit où une donnée saisie en production
   survit.
2. `rooms.yaml` est un fichier tenu à la main, avec ses commentaires et son
   ordre de règles ; le réécrire par programme le dégraderait à chaque
   ajout.

Ces salles sont fusionnées avec celles du bâtiment au démarrage
(`main.py::startup`) et à chaque ajout. Elles n'ont volontairement AUCUNE
règle d'affectation associée : le solveur ne les choisira jamais tout seul,
elles ne servent qu'à une affectation MANUELLE (« modifier uniquement les
salles » depuis la Vue Promo). C'est le comportement voulu — une salle hors
bâtiment est un cas ponctuel, pas une ressource que la génération
automatique doit se mettre à utiliser.
"""

from __future__ import annotations

import json
from pathlib import Path

from cal_iut.models.entities import Room, RoomType


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "custom_rooms.json"


def load_custom_rooms() -> list[Room]:
    path = _path()
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Fichier absent/corrompu = aucune salle ajoutée, jamais une erreur
        # qui empêcherait l'application entière de démarrer pour ça.
        return []
    salles: list[Room] = []
    for item in brut if isinstance(brut, list) else []:
        try:
            salles.append(
                Room(
                    id=str(item["id"]),
                    label=str(item["label"]),
                    capacity=int(item.get("capacity", 30)),
                    room_type=RoomType(item.get("room_type", RoomType.STANDARD.value)),
                    equipment=list(item.get("equipment", [])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # entrée illisible ignorée, les autres restent utilisables
    return salles


def add_custom_room(room: Room) -> None:
    path = _path()
    existantes = load_custom_rooms()
    if any(r.id == room.id for r in existantes):
        return
    existantes.append(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "id": r.id,
                    "label": r.label,
                    "capacity": r.capacity,
                    "room_type": r.room_type.value,
                    "equipment": list(r.equipment),
                }
                for r in existantes
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def merge_into(rooms_du_batiment: list[Room]) -> list[Room]:
    """Salles du bâtiment + salles ajoutées, sans doublon d'`id` — celles du
    bâtiment (`rooms.yaml`) gagnent toujours : si un jour une salle ajoutée à
    la main finit par être intégrée au fichier officiel, c'est la version
    officielle qui doit primer, pas la copie locale devenue obsolète."""
    connus = {r.id for r in rooms_du_batiment}
    return rooms_du_batiment + [r for r in load_custom_rooms() if r.id not in connus]
