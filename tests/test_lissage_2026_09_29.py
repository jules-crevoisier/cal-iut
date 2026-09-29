"""Lissage d'un parcours (demande du 29/09/2026 sur la 3e année DEV FC :
« on ne veut pas de cours de 8h à 9h30 […] les cours commencent à 9h30 »,
sans trou, journées équilibrées, en vérifiant bien les autres parcours).

Trois familles de tests :
- l'ordre d'application (un échange A↔B ne doit jamais poser deux séances
  de la même cohorte au même créneau, même transitoirement) ;
- les indicateurs (`mesurer`), qui fondent le rapport avant/après ;
- le correctif de salle trouvé en chemin : un déplacement MANUEL choisissait
  sa salle avec la carte de l'affectation automatique (H.007 et H.008
  indépendantes) puis se faisait refuser par sa propre validation, qui les
  tient pour la même salle (Kyllian Bresson, 25/09/2026).

Plus un test d'intégration (lent) sur le vrai planning du dépôt.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cal_iut.api.lissage import Deplacement, ordre_application
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]


def _mv(sid: str, de: tuple[int, int, int], vers: tuple[int, int, int]) -> Deplacement:
    return Deplacement(session_id=sid, course_code="WRX", enseignants=[], de=de, vers=vers)


def _rejouer(etapes, depart: dict[str, tuple[int, int, int]], durees: dict[str, int]):
    """Rejoue les étapes en vérifiant qu'à AUCUN moment deux séances de la
    cohorte ne se chevauchent. Rend la position finale."""
    pos = dict(depart)
    for m, _ in etapes:
        pos[m.session_id] = m.vers
        cases: dict[tuple[int, int, int], str] = {}
        for sid, (w, d, s) in pos.items():
            for k in range(durees.get(sid, 1)):
                assert (w, d, s + k) not in cases, f"{sid} et {cases[(w, d, s + k)]} se chevauchent"
                cases[(w, d, s + k)] = sid
    return pos


def test_un_echange_passe_par_une_case_libre():
    depart = {"A": (5, 0, 1), "B": (5, 0, 2)}
    deplacements = [_mv("A", (5, 0, 1), (5, 0, 2)), _mv("B", (5, 0, 2), (5, 0, 1))]
    etapes = ordre_application(deplacements, depart, {})
    fin = _rejouer(etapes, depart, {})
    assert fin == {"A": (5, 0, 2), "B": (5, 0, 1)}
    assert len(etapes) == 3  # une étape intermédiaire pour briser le cycle


def test_une_chaine_se_deroule_dans_le_bon_ordre_sans_etape_intermediaire():
    depart = {"A": (5, 0, 1), "B": (5, 0, 2), "C": (5, 0, 3)}
    # A va où est B, B va où est C, C va sur une case libre : C d'abord.
    deplacements = [
        _mv("A", (5, 0, 1), (5, 0, 2)),
        _mv("B", (5, 0, 2), (5, 0, 3)),
        _mv("C", (5, 0, 3), (5, 1, 1)),
    ]
    etapes = ordre_application(deplacements, depart, {})
    assert [m.session_id for m, _ in etapes] == ["C", "B", "A"]
    assert _rejouer(etapes, depart, {}) == {"A": (5, 0, 2), "B": (5, 0, 3), "C": (5, 1, 1)}


def test_une_seance_de_trois_heures_occupe_ses_deux_creneaux():
    depart = {"LONG": (5, 0, 1), "B": (5, 0, 3)}
    # LONG (2 créneaux) va sur 3-4 : B, en 3, doit partir avant.
    deplacements = [_mv("LONG", (5, 0, 1), (5, 0, 3)), _mv("B", (5, 0, 3), (5, 0, 1))]
    etapes = ordre_application(deplacements, depart, {"LONG": 2})
    assert _rejouer(etapes, depart, {"LONG": 2}) == {"LONG": (5, 0, 3), "B": (5, 0, 1)}


# ── Salle d'un déplacement manuel : même carte que la validation ─────────────


def test_un_deplacement_manuel_n_est_pas_mis_dans_la_moitie_occupee_d_une_salle_double():
    from cal_iut.api.main import _resolve_room

    groupes = load_groups(ROOT / "data" / "config")
    rooms = [
        Room(id="h007", label="H.007", capacity=15, room_type=RoomType.TP_STANDARD),
        Room(id="h008", label="H.008", capacity=15, room_type=RoomType.TP_STANDARD),
        Room(id="h007_h008", label="H.007-008", capacity=30, room_type=RoomType.COMBINED, combines=["h007", "h008"]),
        Room(id="h101", label="H.101", capacity=35, room_type=RoomType.STANDARD),
    ]

    def seance(sid: str, groupe: str) -> SessionToPlace:
        return SessionToPlace(
            id=sid, course_code="WRX" + sid, course_name="x", semestre="S5", parcours="BUT3-DEV-FC",
            annee="BUT3", session_type=SessionType.TD, group_ids=[groupe], teacher_codes=[sid],
        )

    occupante = seance("OCC", "but1-td-ab")
    mobile = seance("MOB", "but3-dev-fc-td-ef")
    etat = SimpleNamespace(
        timetable=[
            PlacedSessionWithRoom(session_id="OCC", week=8, day=1, slot=2, course_code="WRXOCC",
                                  group_ids=["but1-td-ab"], teacher_codes=["OCC"], room_id="h007", room_label="H.007"),
            PlacedSessionWithRoom(session_id="MOB", week=8, day=3, slot=2, course_code="WRXMOB",
                                  group_ids=["but3-dev-fc-td-ef"], teacher_codes=["MOB"], room_id="h008", room_label="H.008"),
        ],
        sessions_by_id={"OCC": occupante, "MOB": mobile},
        rooms=rooms, groups=groupes, room_rules=[], room_reservations={},
    )
    salle = _resolve_room(etat, mobile, 8, 1, 2, "h008")
    assert salle is not None
    assert salle.id not in {"h008", "h007", "h007_h008"}


# ── Intégration : vrai planning du dépôt ─────────────────────────────────────


@pytest.mark.slow
def test_lissage_fc_sur_le_vrai_planning():
    """Sur le planning versionné : aucune séance proposée à 8h, aucun trou
    créé, contre-vérification vide, et seules des séances FC futures bougent."""
    from cal_iut.api import lissage
    from cal_iut.api.main import charger_etat_applicatif
    from cal_iut.api.state import get_state
    from cal_iut.calendar.academic import week_status

    charger_etat_applicatif()
    etat = get_state()
    semaines_futures = sorted({
        p.week for p in etat.timetable if week_status(etat.calendar, "S5", p.week) == "future"
    })
    # Une seule semaine, sans changement de semaine : rapide et suffisant.
    cible = next(w for w in semaines_futures if any(
        "dev-fc" in g for p in etat.timetable if p.week == w for g in p.group_ids
    ))
    proposition = lissage.proposer(
        etat, "BUT3-DEV-FC", semaines=[cible], entre_semaines=False, temps_max_s=20,
    )
    assert proposition.statut in ("OPTIMAL", "FEASIBLE")
    assert proposition.verification == []
    groupes_fc = {g.id for g in etat.groups if g.parcours == "BUT3-DEV-FC"}
    for m in proposition.deplacements:
        assert m.vers[0] == cible
        assert m.vers[2] != 0, "aucune séance déplacée vers 8h"
        assert set(etat.sessions_by_id[m.session_id].group_ids) <= groupes_fc
    avant, apres = proposition.avant[0], proposition.apres[0]
    assert apres.cours_8h <= avant.cours_8h
    assert apres.trous <= avant.trous
    assert apres.seances == avant.seances
