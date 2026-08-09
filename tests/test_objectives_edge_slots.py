"""
Lissage des emplois du temps de 3e année (retour utilisateur, 07/08/2026 :
"évitant au max les cours de 8h et de 17h [...] si on peut les faire finir
à 15h30 c'est bien") — cf. `objectives.py::add_edge_slot_penalties`.
"""

from ortools.sat.python import cp_model

from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY, TimeSlot
from cal_iut.solver.objectives import add_edge_slot_penalties


def _session(sid: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="C", course_name="C", semestre="S5", parcours="BUT3-DEV-FI",
        annee="BUT3", session_type=SessionType.TD, group_ids=["g1"], teacher_codes=["T"],
    )


def _penalty_for_slot(slot: TimeSlot, early_late_weight: int, late_afternoon_weight: int) -> int:
    model = cp_model.CpModel()
    session = _session("S1")
    horizon = DAYS_PER_WEEK * SLOTS_PER_DAY
    start = model.new_int_var(0, horizon - 1, "start")
    model.add(start == slot.value)  # lundi, ce créneau précis
    penalties = add_edge_slot_penalties(model, [session], {"S1": start}, early_late_weight, late_afternoon_weight)
    model.minimize(sum(penalties) if penalties else 0)
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return sum(solver.value(p) for p in penalties)


def test_8h_and_17h_penalized() -> None:
    assert _penalty_for_slot(TimeSlot.SLOT_08_0930, 25, 10) == 25
    assert _penalty_for_slot(TimeSlot.SLOT_17_1830, 25, 10) == 25


def test_1530_penalized_lightly() -> None:
    assert _penalty_for_slot(TimeSlot.SLOT_1530_17, 25, 10) == 10


def test_midday_slots_not_penalized() -> None:
    for slot in (TimeSlot.SLOT_0930_11, TimeSlot.SLOT_11_1230, TimeSlot.SLOT_14_1530):
        assert _penalty_for_slot(slot, 25, 10) == 0


def test_zero_weights_produce_no_penalty_terms() -> None:
    model = cp_model.CpModel()
    session = _session("S1")
    start = model.new_int_var(0, DAYS_PER_WEEK * SLOTS_PER_DAY - 1, "start")
    assert add_edge_slot_penalties(model, [session], {"S1": start}, 0, 0) == []


def test_solver_prefers_non_edge_slot_when_free_to_choose() -> None:
    """Sans autre contrainte, minimiser cette pénalité seule doit faire
    atterrir la séance sur un créneau non bordure (résultat, pas juste la
    valeur de pénalité)."""
    model = cp_model.CpModel()
    session = _session("S1")
    horizon = DAYS_PER_WEEK * SLOTS_PER_DAY
    start = model.new_int_var(0, horizon - 1, "start")
    penalties = add_edge_slot_penalties(model, [session], {"S1": start}, 25, 10)
    model.minimize(sum(penalties))
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    chosen_slot = solver.value(start) % SLOTS_PER_DAY
    assert chosen_slot in (
        TimeSlot.SLOT_0930_11.value,
        TimeSlot.SLOT_11_1230.value,
        TimeSlot.SLOT_14_1530.value,
    )
