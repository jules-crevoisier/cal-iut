"""Les trois demandes de Kyllian Bresson du 26/08/2026.

Deux d'entre elles ont exigé un mécanisme qui n'existait pas :

1. **Indisponibilité enseignant à une DATE ET UN HORAIRE précis.** Les quatre
   mécanismes existants étaient soit récurrents (« tous les jeudis à 8h »), soit
   à la journée entière. Aucun ne savait dire « ce jeudi-là, de 9h30 à 12h30 ».
   Cas fondateur : la pré-rentrée BUT2 FC alternants du 3 septembre, où Florent
   Libbrecht et Anthony Froli doivent être présents — sans perdre leur
   après-midi pour autant.

2. **Salle réservée par un tiers.** Le solveur ne modélise pas les salles : une
   salle prise par la Direction ne peut se déclarer que du côté de
   l'attribution.

Un piège commun aux deux, qu'un seul de ces tests suffit à rappeler : bloquer le
PARCOURS ne protège pas les ENSEIGNANTS. Florent Libbrecht intervient aussi en
BUT1 ; interdire les cours de BUT2-CREACOM-FC le laisserait programmable devant
la promotion BUT1 à la même heure.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_room_reservations, load_teacher_availability
from cal_iut.models.entities import (
    Group,
    Room,
    RoomType,
    SessionType,
    TeacherAvailability,
    TeacherDateSlotRule,
)
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import add_teacher_availability_constraints
from cal_iut.solver.cpsat import PlacedSession
from cal_iut.solver.rooms import assign_rooms, find_room_for_slot

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
CAL = build_default_calendar_2026_2027()
SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY

PRE_RENTREE = date(2026, 9, 3)  # jeudi
AMPHI_DIRECTION = date(2026, 9, 11)  # vendredi


# ==========================================================================
# 1. Indisponibilité enseignant à date + horaire précis
# ==========================================================================


def _creneaux_possibles(regles: list[TeacherDateSlotRule], duree: int = 1) -> set[int]:
    """Créneaux qu'un CP-SAT laisse encore à une séance, sous ces règles."""
    session = SessionToPlace(
        id="s", course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["FLI"],
        duration_slots=duree,
    )
    semaines = 3
    model = cp_model.CpModel()
    depart = model.new_int_var(0, semaines * SLOTS_PER_WEEK - duree, "s")
    add_teacher_availability_constraints(
        model, [session], {"s": depart},
        [TeacherAvailability(teacher_code="FLI", forbidden_date_slots=regles)],
        semaines, calendar=CAL, week_offset=0,
    )
    solveur = cp_model.CpSolver()
    solveur.parameters.enumerate_all_solutions = True
    possibles: set[int] = set()

    class _Collecte(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            possibles.add(self.value(depart))

    solveur.solve(model, _Collecte())
    return possibles


def _index(jour_iso: date, slot: int) -> int:
    semaine, jour = CAL.date_to_week_day(jour_iso)
    return semaine * SLOTS_PER_WEEK + jour * SLOTS_PER_DAY + slot


def test_les_creneaux_interdits_a_cette_date_sont_bien_retires():
    regles = [TeacherDateSlotRule(date=PRE_RENTREE.isoformat(), slots=[1, 2])]
    possibles = _creneaux_possibles(regles)
    for slot in (1, 2):
        assert _index(PRE_RENTREE, slot) not in possibles


def test_le_reste_de_la_journee_reste_disponible():
    """Bloquer la journée entière priverait l'enseignant de quatre créneaux
    sans que personne ne l'ait demandé."""
    regles = [TeacherDateSlotRule(date=PRE_RENTREE.isoformat(), slots=[1, 2])]
    possibles = _creneaux_possibles(regles)
    for slot in (0, 3, 4, 5):
        assert _index(PRE_RENTREE, slot) in possibles, f"créneau {slot} perdu sans raison"


def test_les_autres_dates_ne_sont_pas_touchees():
    regles = [TeacherDateSlotRule(date=PRE_RENTREE.isoformat(), slots=[1, 2])]
    possibles = _creneaux_possibles(regles)
    autre_jeudi = date(2026, 9, 10)
    for slot in (1, 2):
        assert _index(autre_jeudi, slot) in possibles


def test_un_bloc_de_3h_ne_peut_pas_recouvrir_le_creneau_interdit():
    """Le piège : un bloc démarrant AVANT le créneau interdit le recouvre.

    Avec une simple interdiction de DÉMARRAGE, une séance de 3h posée à 8h
    déborderait sur 9h30-11h — l'enseignant serait en cours à l'heure exacte où
    on le veut ailleurs.
    """
    regles = [TeacherDateSlotRule(date=PRE_RENTREE.isoformat(), slots=[1, 2])]
    possibles = _creneaux_possibles(regles, duree=2)
    assert _index(PRE_RENTREE, 0) not in possibles, "un bloc de 3h à 8h recouvre 9h30-11h"
    assert _index(PRE_RENTREE, 3) in possibles, "l'après-midi doit rester utilisable"


def test_la_validation_manuelle_refuse_aussi_ce_creneau():
    """Elle ne doit jamais être plus permissive que le solveur : sinon un
    glisser-déposer défait ce que le solveur a respecté."""
    from cal_iut.api.validation import _teacher_free_at

    avail = [TeacherAvailability(
        teacher_code="FLI",
        forbidden_date_slots=[TeacherDateSlotRule(date=PRE_RENTREE.isoformat(), slots=[1, 2])],
    )]
    semaine, jour = CAL.date_to_week_day(PRE_RENTREE)
    assert not _teacher_free_at(["FLI"], semaine, jour, 1, PRE_RENTREE, avail, CAL, 0)
    assert not _teacher_free_at(["FLI"], semaine, jour, 2, PRE_RENTREE, avail, CAL, 0)
    assert _teacher_free_at(["FLI"], semaine, jour, 3, PRE_RENTREE, avail, CAL, 0)


def test_la_fusion_yaml_csv_ne_perd_pas_la_regle():
    """Cette fusion RECONSTRUIT l'objet : tout champ oublié disparaît en silence
    dès qu'un enseignant est présent des deux côtés — ce qui est le cas de
    presque tous."""
    from cal_iut.ingestion.constraints_loader import merge_teacher_availability

    depuis_yaml = [TeacherAvailability(
        teacher_code="FLI",
        forbidden_date_slots=[TeacherDateSlotRule(date=PRE_RENTREE.isoformat(), slots=[1, 2])],
    )]
    depuis_csv = [TeacherAvailability(teacher_code="FLI", forbidden_slots=[(0, 0)])]
    fusionne = merge_teacher_availability(depuis_yaml, depuis_csv)
    fli = next(t for t in fusionne if t.teacher_code == "FLI")
    assert [(r.date, r.slots) for r in fli.forbidden_date_slots] == [(PRE_RENTREE.isoformat(), [1, 2])]
    assert (0, 0) in fli.forbidden_slots  # l'autre source n'est pas perdue non plus


def test_la_pre_rentree_est_bien_declaree_pour_les_deux_enseignants():
    """Demande de Kyllian Bresson : FLI et AFR doivent être libres 9h30-12h30."""
    par_code = {t.teacher_code: t for t in load_teacher_availability(CONFIG)}
    for code in ("FLI", "AFR"):
        assert code in par_code, f"{code} absent de teacher_availability.yaml"
        regles = [r for r in par_code[code].forbidden_date_slots if r.date == PRE_RENTREE.isoformat()]
        assert regles, f"{code} n'est pas déclaré indisponible le {PRE_RENTREE}"
        assert sorted(regles[0].slots) == [1, 2], f"{code} : {regles[0].slots} au lieu de 9h30-12h30"


def test_l_evenement_de_pre_rentree_est_fusionne_dans_les_dates_fixes():
    """`10_dates_fixes.json` étant REGÉNÉRÉ depuis le CSV de l'établissement,
    l'ajout doit venir de la configuration — sinon il disparaît au prochain
    `build_contraintes.py`."""
    import json

    data = json.loads((ROOT / "contraintes" / "10_dates_fixes.json").read_text(encoding="utf-8"))
    evt = [
        e for e in data["evenements"]
        if e["date"] == PRE_RENTREE.isoformat() and "rentrée" in (e.get("motif") or "").lower()
    ]
    assert evt, "la pré-rentrée n'a pas survécu à la régénération"
    assert evt[0]["parcours"] == ["BUT2-CREACOM-FC"]
    assert evt[0].get("demande_par"), "l'origine de la demande doit rester tracée"


# ==========================================================================
# 2. Salle réservée par un tiers
# ==========================================================================


def _salles() -> list[Room]:
    return [
        Room(id="h018", label="H.018 (Amphi MMI)", capacity=150, room_type=RoomType.AMPHI),
        Room(id="h101", label="H.101", capacity=36, room_type=RoomType.STANDARD),
    ]


# La promotion BUT1 (120 étudiants) ne tient QUE dans l'amphi : c'est
# précisément le cas où une réservation extérieure se voit — pour un TD de 24
# étudiants, l'outil aurait de toute façon choisi une autre salle, et le test ne
# prouverait rien.
_PROMO_BUT1 = Group(id="but1", label="BUT1", parcours="BUT1", annee="BUT1", kind="promo", headcount=120)
_RESERVE_VENDREDI_9H30 = {"h018": {1 * SLOTS_PER_WEEK + 4 * SLOTS_PER_DAY + 1}}


def _cm(session_id: str, week: int, day: int, slot: int):
    session = SessionToPlace(
        id=session_id, course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
        sequence_order=1, group_ids=["but1"], teacher_codes=["MRI"],
    )
    place = PlacedSession(session_id, week, day, slot, "WR101", ["but1"], ["MRI"])
    return session, place


def test_l_amphi_est_bien_le_choix_par_defaut_pour_une_promotion_entiere():
    """Point de départ : sans réservation, ce CM va dans l'amphi. Sans quoi les
    deux tests suivants ne prouveraient rien."""
    session, place = _cm("s", 1, 4, 1)
    resultat = assign_rooms([place], {"s": session}, _salles(), [_PROMO_BUT1], [])
    assert resultat[0].room_id == "h018"


def test_une_salle_reservee_n_est_pas_attribuee():
    session, place = _cm("s", 1, 4, 1)
    resultat = assign_rooms(
        [place], {"s": session}, _salles(), [_PROMO_BUT1], [], reserved=_RESERVE_VENDREDI_9H30,
    )
    assert resultat[0].room_id != "h018"


def test_la_reservation_ne_vaut_que_pour_le_creneau_declare():
    """Réserver 9h30-11h ne doit pas retirer l'amphi de toute la journée."""
    session, place = _cm("s", 1, 4, 3)  # 14h, hors réservation
    resultat = assign_rooms(
        [place], {"s": session}, _salles(), [_PROMO_BUT1], [], reserved=_RESERVE_VENDREDI_9H30,
    )
    assert resultat[0].room_id == "h018"


def test_le_deplacement_manuel_respecte_aussi_la_reservation():
    """Sinon un glisser-déposer remettrait un cours dans la salle occupée par
    la Direction, alors que la génération complète l'évitait."""
    session, _ = _cm("s", 1, 4, 1)
    reserve = {"h018": {1 * SLOTS_PER_WEEK + 4 * SLOTS_PER_DAY + 1}}
    salle = find_room_for_slot(
        session, 1, 4, 1, [], {"s": session}, _salles(), [_PROMO_BUT1], [], reserved=reserve,
    )
    assert salle is None or salle.id != "h018"


def test_l_amphi_est_bien_reserve_pour_la_direction():
    """Demande de Kyllian Bresson : amphi H le vendredi 11/09, 9h30-12h30."""
    reserve = load_room_reservations(CONFIG, CAL)
    assert "h018" in reserve, "aucune réservation d'amphi déclarée"
    semaine, jour = CAL.date_to_week_day_any(AMPHI_DIRECTION)
    attendus = {semaine * SLOTS_PER_WEEK + jour * SLOTS_PER_DAY + s for s in (1, 2)}
    assert attendus <= reserve["h018"], "le créneau 9h30-12h30 du 11/09 n'est pas réservé"
