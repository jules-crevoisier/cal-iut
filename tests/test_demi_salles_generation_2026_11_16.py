"""L'affectation automatique des salles respecte la cloison (16/11/2026).

H.007 et H.008 (comme H.201 et H.203) sont les deux moitiés d'une même
salle : « il ne faut pas deux modules différents en même temps dans ces
deux salles » (Kyllian Bresson, 25/09/2026), le même module y étant permis
(tâche 29). Les contrôles manuels l'appliquaient déjà ; un emploi du temps
tout juste généré sortait pourtant avec 65 « doublons de salle » entre ces
moitiés (brouillon du semestre pair du 16/11/2026).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cal_iut.api import doublons
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.cpsat import PlacedSession
from cal_iut.solver.rooms import assign_rooms

GROUPES = load_groups(Path(__file__).resolve().parents[1] / "data" / "config")


def _salles(avec_secours: bool = True) -> list[Room]:
    salles = [
        Room(id="h007", label="H.007", capacity=15, room_type=RoomType.STANDARD, voisines=["h008"]),
        Room(id="h008", label="H.008", capacity=15, room_type=RoomType.STANDARD, voisines=["h007"]),
        Room(
            id="h007_h008", label="H.007-008", capacity=30, room_type=RoomType.COMBINED,
            combines=["h007", "h008"], placement_auto=False,
        ),
    ]
    if avec_secours:
        # Plus grande : choisie seulement si les petites ne conviennent pas.
        salles.append(Room(id="h101", label="H.101", capacity=40, room_type=RoomType.STANDARD))
    return salles


def _seance(sid: str, code: str, groupe: str, prof: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name=code, semestre="S2", parcours="BUT1", annee="BUT1",
        session_type=SessionType.TP, sequence_order=1, group_ids=[groupe], teacher_codes=[prof],
    )


def _affecter(seances: list[SessionToPlace], salles: list[Room]):
    par_id = {s.id: s for s in seances}
    places = [
        PlacedSession(
            session_id=s.id, week=3, day=0, slot=0, course_code=s.course_code,
            group_ids=s.group_ids, teacher_codes=s.teacher_codes,
        )
        for s in seances
    ]
    resultat = assign_rooms(places, par_id, salles, GROUPES, [])
    etat = SimpleNamespace(rooms=salles, sessions_by_id=par_id, timetable=resultat, courses=[])
    return {p.session_id: p.room_id for p in resultat}, doublons.doublons(etat, None)


def test_deux_modules_differents_ne_partagent_pas_les_deux_moities():
    seances = [_seance("a", "WR201", "but1-tp-a", "KBR"), _seance("b", "WR202", "but1-tp-b", "ALO")]

    salles, signales = _affecter(seances, _salles())

    assert {salles["a"], salles["b"]} != {"h007", "h008"}
    assert None not in salles.values()
    assert signales == []


def test_le_meme_module_peut_occuper_les_deux_moities():
    seances = [_seance("a", "WR201", "but1-tp-a", "KBR"), _seance("b", "WR201", "but1-tp-b", "ALO")]

    salles, signales = _affecter(seances, _salles(avec_secours=False))

    assert {salles["a"], salles["b"]} == {"h007", "h008"}
    assert signales == []


def test_sans_autre_salle_la_seconde_seance_reste_sans_salle_plutot_qu_en_doublon():
    seances = [_seance("a", "WR201", "but1-tp-a", "KBR"), _seance("b", "WR202", "but1-tp-b", "ALO")]

    salles, signales = _affecter(seances, _salles(avec_secours=False))

    assert sorted(v or "" for v in salles.values()) in (["", "h007"], ["", "h008"])
    assert signales == []
