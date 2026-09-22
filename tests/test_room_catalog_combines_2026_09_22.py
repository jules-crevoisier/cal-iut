"""`_room_catalog` expose `combines` (todo departement 22/09/2026, Kyllian
Bresson : « Planning des salles disponibles »).

La Vue « Salles libres » a besoin de savoir qu'une salle fusionnee (ex.
`h007_h008`, cf. `data/config/rooms.yaml`) occupe aussi ses deux moitiés —
sans ce champ dans le payload JSON, le frontend n'a aucun moyen de le
determiner (le catalogue est la seule source de verite cote client, les
lignes `AppRow` ne portent que le libelle de la salle reellement occupee).
Ajout additif : le champ existe deja sur `Room` (`solver/rooms.py` s'en sert
pour le conflit croise), seule l'exposition dans `_room_catalog` manquait.
"""

from __future__ import annotations

from cal_iut.export.html_view import _room_catalog
from cal_iut.models.entities import Room, RoomType


def test_room_catalog_expose_combines_pour_salle_fusionnee():
    rooms = [
        Room(id="h007", label="H.007", capacity=24, room_type=RoomType.TP_STANDARD),
        Room(id="h008", label="H.008", capacity=24, room_type=RoomType.TP_STANDARD),
        Room(
            id="h007_h008",
            label="H.007+H.008",
            capacity=48,
            room_type=RoomType.COMBINED,
            combines=["h007", "h008"],
        ),
    ]

    catalog = {entry["id"]: entry for entry in _room_catalog(rooms, rows=[])}

    assert catalog["h007_h008"]["combines"] == ["h007", "h008"]


def test_room_catalog_combines_vide_par_defaut():
    rooms = [Room(id="h009", label="H.009", capacity=24, room_type=RoomType.TD_DESIGN)]

    catalog = _room_catalog(rooms, rows=[])

    assert catalog[0]["combines"] == []
