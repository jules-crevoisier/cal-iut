"""Salles en double : une salle créée depuis l'interface (`custom_rooms.json`)
sous un nom qui existe déjà.

Cas rencontré le 19/11/2026 : « E.201 » a été créée à la main avant d'être
ajoutée à `rooms.yaml` (id `e201`) ; l'outil la connaissait alors deux fois
(`e-201` et `e201`), avec des séances sur l'une et sur l'autre, donc des
conflits de salle fictifs.

Deux salles sont la même quand leur libellé donne la même clé une fois
ramené aux lettres et chiffres (« E.201 », « e 201 », « E201 »). La salle du
bâtiment gagne ; entre deux salles ajoutées, la plus ancienne. Le
dédoublonnage tourne au démarrage (`api/main.py::startup`) : il réécrit les
références de la base vers la salle gardée, puis retire la copie du fichier.
Sans doublon, il ne touche à rien.
"""

from __future__ import annotations

import logging

from sqlalchemy import update
from sqlalchemy.orm import Session

from cal_iut.api import custom_rooms
from cal_iut.db.models import CurrentPlacement, ScheduleException, SolverPlacement
from cal_iut.models.entities import Room

logger = logging.getLogger(__name__)


def cle_libelle(libelle: str) -> str:
    """« E.201 », « e 201 » et « E201 » donnent la même clé."""
    return "".join(c for c in libelle.lower() if c.isalnum())


def doublons(batiment: list[Room]) -> dict[str, str]:
    """`{id de la copie à retirer: id de la salle gardée}`."""
    gardees = {cle_libelle(r.label): r.id for r in batiment}
    ids_batiment = {r.id for r in batiment}
    resultat: dict[str, str] = {}
    for salle in custom_rooms.load_custom_rooms():
        if salle.id in ids_batiment:
            continue  # même id : `merge_into` écarte déjà la copie
        garde = gardees.setdefault(cle_libelle(salle.label), salle.id)
        if garde != salle.id:
            resultat[salle.id] = garde
    return resultat


def retirer_des_salles_ajoutees(a_retirer: set[str]) -> None:
    """Retire ces salles (et leurs surcharges) de `custom_rooms.json`, en
    gardant les champs des autres tels qu'ils sont dans le fichier."""
    with custom_rooms._verrou:
        brut = custom_rooms._read_raw()
        brut["rooms"] = [
            r for r in brut["rooms"] if not (isinstance(r, dict) and str(r.get("id")) in a_retirer)
        ]
        brut["overrides"] = {k: v for k, v in brut["overrides"].items() if k not in a_retirer}
        custom_rooms._write_raw(brut)


def dedoublonner(batiment: list[Room], db: Session) -> dict[str, str]:
    """Rattache à la salle gardée tout ce qui pointait vers une copie, puis
    retire la copie. Rend `{copie: salle gardée}` (vide : rien à faire)."""
    correspondance = doublons(batiment)
    if not correspondance:
        return {}
    libelles = {r.id: r.label for r in batiment}
    libelles.update({r.id: r.label for r in custom_rooms.load_custom_rooms()})
    for copie, garde in correspondance.items():
        for modele in (CurrentPlacement, SolverPlacement, ScheduleException):
            db.execute(update(modele).where(modele.room_id == copie).values(room_id=garde))
        db.execute(
            update(CurrentPlacement).where(CurrentPlacement.room_id == garde).values(room_label=libelles[garde])
        )
        logger.warning("Salle en double « %s » (%s) rattachée à %s", libelles.get(copie), copie, garde)
    db.commit()
    retirer_des_salles_ajoutees(set(correspondance))
    return correspondance
