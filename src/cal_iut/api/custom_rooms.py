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
(`main.py::startup`) et à chaque ajout. Elles n'ont AUCUNE règle
d'affectation (`room_assignment_rules`, `rooms.yaml`) dédiée, mais restent
proposables à la génération automatique via les règles GÉNÉRIQUES par type
de salle tant que leur `placement_auto` (défaut `True`) n'est pas décoché à
la création ou depuis la fiche salle — cf. `Room.placement_auto` et
`overrides` ci-dessous.

`overrides` (22/09/2026, retour utilisateur : « supprimer la BU du placement
automatique des salles car elle est utilisée pour un seul module ») : permet
de modifier `placement_auto` (et, à terme, d'autres attributs) sur N'IMPORTE
QUELLE salle — y compris une salle du BÂTIMENT (`rooms.yaml`), qui n'a pas de
fiche ici sinon. `PATCH /rooms/{room_id}` (cf. `api/main.py`) écrit dans les
salles personnalisées directement si l'id en est une, ou dans `overrides`
sinon — pour survivre au redéploiement sans toucher `rooms.yaml`, exactement
comme les salles créées depuis l'interface.
"""

from __future__ import annotations

import threading
from pathlib import Path

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat
from cal_iut.models.entities import Room, RoomType

# Lecture-modification-écriture sous verrou (audit du 29/09/2026, P0-4).
_verrou = threading.RLock()


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "custom_rooms.json"


def _read_raw() -> dict[str, object]:
    """Lit le fichier, normalisé en `{"rooms": [...], "overrides": {...}}`.

    Rétrocompatible avec l'ancien format (une simple liste de salles,
    avant l'ajout des overrides) : une liste brute devient `{"rooms":
    <liste>, "overrides": {}}`.
    """
    # Absent = aucune salle ajoutée. Illisible = mis de côté puis
    # `FichierEtatIllisible` (audit du 29/09/2026, P0-4) : rendre un
    # contenu vide faisait réécrire le fichier sans les autres salles au
    # prochain ajout. Au démarrage, `charger_etat_applicatif` rattrape
    # l'erreur et continue avec les seules salles du bâtiment.
    brut = lire_json_etat(_path(), {"rooms": [], "overrides": {}}, types=(list, dict))
    if isinstance(brut, list):
        return {"rooms": brut, "overrides": {}}
    if isinstance(brut, dict):
        return {
            "rooms": brut.get("rooms", []) if isinstance(brut.get("rooms"), list) else [],
            "overrides": brut.get("overrides", {}) if isinstance(brut.get("overrides"), dict) else {},
        }
    return {"rooms": [], "overrides": {}}


def _write_raw(data: dict[str, object]) -> None:
    ecrire_json(_path(), data)


def load_custom_rooms() -> list[Room]:
    brut = _read_raw()
    salles: list[Room] = []
    for item in brut["rooms"]:
        try:
            salles.append(
                Room(
                    id=str(item["id"]),
                    label=str(item["label"]),
                    capacity=int(item.get("capacity", 30)),
                    room_type=RoomType(item.get("room_type", RoomType.STANDARD.value)),
                    equipment=list(item.get("equipment", [])),
                    # Absent = True (rétrocompat) — cf. `Room.placement_auto`.
                    placement_auto=bool(item.get("placement_auto", True)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # entrée illisible ignorée, les autres restent utilisables
    return salles


def load_overrides() -> dict[str, dict[str, object]]:
    """`{room_id: {"placement_auto": bool}}` — surcharges posées sur des
    salles qui ne sont PAS des salles personnalisées (typiquement une salle
    du bâtiment, `rooms.yaml`)."""
    brut = _read_raw()
    overrides = {}
    for room_id, patch in brut["overrides"].items():
        if isinstance(patch, dict):
            overrides[str(room_id)] = dict(patch)
    return overrides


def _serialize_room(r: Room) -> dict[str, object]:
    return {
        "id": r.id,
        "label": r.label,
        "capacity": r.capacity,
        "room_type": r.room_type.value,
        "equipment": list(r.equipment),
        "placement_auto": r.placement_auto,
    }


def add_custom_room(room: Room) -> None:
    with _verrou:
        brut = _read_raw()
        existantes = load_custom_rooms()
        if any(r.id == room.id for r in existantes):
            return
        existantes.append(room)
        brut["rooms"] = [_serialize_room(r) for r in existantes]
        _write_raw(brut)


def set_room_override(room_id: str, *, placement_auto: bool) -> None:
    """Applique `placement_auto` à la salle `room_id`, persisté dans le volume.

    Si `room_id` est une salle personnalisée (créée depuis l'interface), le
    champ est modifié DIRECTEMENT sur son enregistrement. Sinon (salle du
    bâtiment, `rooms.yaml`), la modification est posée dans `overrides` —
    `rooms.yaml` lui-même n'est jamais réécrit (cf. docstring du module).
    """
    with _verrou:
        brut = _read_raw()
        salles_brutes = list(brut["rooms"])
        trouvee = False
        for item in salles_brutes:
            if isinstance(item, dict) and str(item.get("id")) == room_id:
                item["placement_auto"] = placement_auto
                trouvee = True
                break
        if trouvee:
            brut["rooms"] = salles_brutes
        else:
            overrides = dict(brut["overrides"])
            overrides[room_id] = {**overrides.get(room_id, {}), "placement_auto": placement_auto}
            brut["overrides"] = overrides
        _write_raw(brut)


def merge_into(rooms_du_batiment: list[Room]) -> list[Room]:
    """Salles du bâtiment + salles ajoutées, sans doublon d'`id` — celles du
    bâtiment (`rooms.yaml`) gagnent toujours sur leurs champs propres : si un
    jour une salle ajoutée à la main finit par être intégrée au fichier
    officiel, c'est la version officielle qui doit primer, pas la copie
    locale devenue obsolète.

    `overrides` s'applique en dernier, sur les DEUX groupes : une salle du
    bâtiment dont on a coché/décoché « placement automatique » depuis
    l'interface garde ce choix même si `rooms.yaml` ne le déclare pas."""
    overrides = load_overrides()

    def _appliquer(room: Room) -> Room:
        patch = overrides.get(room.id)
        if not patch:
            return room
        return room.model_copy(update={k: v for k, v in patch.items() if k == "placement_auto"})

    connus = {r.id for r in rooms_du_batiment}
    fusion = [_appliquer(r) for r in rooms_du_batiment]
    fusion += [_appliquer(r) for r in load_custom_rooms() if r.id not in connus]
    return fusion
