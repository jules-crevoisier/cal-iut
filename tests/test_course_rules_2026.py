"""Règles par cours introduites par la mise à jour du 10/08/2026.

- Fenêtres de dates civiles par séance (WR100BU) : borner une séance PRÉCISE
  dans le calendrier était impossible jusque-là (`CourseMinWeekRule` agissait
  au grain du cours entier, sans borne haute).
- Sanctuarisation SAE au grain du GROUPE (WS502D) : le fichier officiel ne date
  cette SAE que pour le TD AB, bloquer tout le parcours priverait les autres
  groupes d'une journée sans raison.
- Ordre souple entre enseignants d'un module (WRA505C : ALO puis AFR).
- Blocs de N créneaux bornés en nombre (WRA308M : seuls les 3 derniers TD).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
from cal_iut.ingestion.config_loader import (
    load_course_teacher_orders,
    load_double_sessions,
    load_groups,
    load_session_date_windows,
)
from cal_iut.ingestion.normalize import _merge_double_sessions
from cal_iut.models.entities import CourseTeacherOrderRule, SessionDateWindowRule, SessionType, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import (
    add_duo_synchronized_rare_room_constraints,
    add_session_date_window_constraints,
    duo_episode_pairs_by_room,
    sae_blocked_days_by_group,
    sae_blocked_days_by_parcours,
)
from cal_iut.solver.objectives import add_course_teacher_order_penalties

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY


def _session(
    idx: int,
    *,
    course_code: str = "WR100BU",
    semestre: str = "S1",
    parcours: str = "BUT1",
    teacher: str = "VMA",
    group_ids: list[str] | None = None,
    session_type: SessionType = SessionType.TD,
) -> SessionToPlace:
    return SessionToPlace(
        id=f"{course_code}-{idx}",
        course_code=course_code,
        course_name="Test",
        semestre=semestre,
        parcours=parcours,
        annee=parcours.split("-")[0],
        session_type=session_type,
        sequence_order=idx,
        group_ids=group_ids or ["g1"],
        teacher_codes=[teacher],
    )


# --------------------------------------------------------------------------
# Fenêtres de dates par séance
# --------------------------------------------------------------------------


def test_wr100bu_windows_are_configured():
    rules = {(r.course_code, tuple(r.sequence_orders)): r for r in load_session_date_windows(CONFIG)}
    visite = rules[("WR100BU", (1,))]
    informatique = rules[("WR100BU", (2, 3))]

    assert (visite.start_date, visite.end_date) == ("2026-09-01", "2026-09-15")
    assert (informatique.start_date, informatique.end_date) == ("2026-09-14", "2026-10-15")


def test_date_window_confines_the_targeted_session_only():
    calendar = build_default_calendar_2026_2027()
    week_offset = semester_week_offset(calendar, "S1")
    weeks = 12
    rule = SessionDateWindowRule(
        course_code="WR100BU", semestre="S1", session_type=SessionType.TD,
        sequence_orders=[1], start_date="2026-09-01", end_date="2026-09-15",
    )
    targeted, untouched = _session(1), _session(2)

    model = cp_model.CpModel()
    starts = {
        s.id: model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, s.id)
        for s in (targeted, untouched)
    }
    add_session_date_window_constraints(
        model, [targeted, untouched], starts, [rule], calendar, week_offset, weeks
    )

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    seen: dict[str, set[date]] = {targeted.id: set(), untouched.id: set()}

    class _Collect(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self) -> None:
            for sid, var in starts.items():
                t = self.value(var)
                d = calendar.week_day_to_date(
                    week_offset + t // SLOTS_PER_WEEK, (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY
                )
                if d is not None:
                    seen[sid].add(d)

    solver.parameters.max_time_in_seconds = 30
    solver.solve(model, _Collect())

    assert seen[targeted.id]
    assert max(seen[targeted.id]) <= date(2026, 9, 15)
    # La séance non visée par la règle garde tout l'horizon.
    assert max(seen[untouched.id]) > date(2026, 9, 15)


def test_date_window_excludes_closed_days():
    """La fenêtre ne doit jamais ouvrir un jour férié ou de pause pédagogique."""
    calendar = build_default_calendar_2026_2027()
    week_offset = semester_week_offset(calendar, "S1")
    weeks = 19
    # Fenêtre englobant l'Armistice (mercredi 11 novembre 2026).
    rule = SessionDateWindowRule(
        course_code="WR100BU", semestre="S1",
        start_date="2026-11-09", end_date="2026-11-13",
    )
    session = _session(1)
    model = cp_model.CpModel()
    starts = {session.id: model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, session.id)}
    add_session_date_window_constraints(
        model, [session], starts, [rule], calendar, week_offset, weeks
    )

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    days: set[date] = set()

    class _Collect(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self) -> None:
            t = self.value(starts[session.id])
            d = calendar.week_day_to_date(
                week_offset + t // SLOTS_PER_WEEK, (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY
            )
            if d is not None:
                days.add(d)

    solver.solve(model, _Collect())
    assert days
    assert date(2026, 11, 11) not in days


# --------------------------------------------------------------------------
# Sanctuarisation SAE au grain du groupe
# --------------------------------------------------------------------------


def test_partial_sae_blocks_only_its_own_groups():
    groups = load_groups(CONFIG)
    sae_days = {"WS502D": {(3, 1), (3, 2)}}
    labels = {"WS502D": ["AB"]}
    sessions = [_session(1, course_code="WS502D", parcours="BUT3-DEV-FI", group_ids=["x"])]

    # Le parcours entier ne doit PAS être bloqué...
    assert sae_blocked_days_by_parcours(sessions, sae_days, labels) == {}

    # ...seulement le TD AB, ses TP et — TD unique du parcours — la promo.
    blocked = sae_blocked_days_by_group(sessions, sae_days, labels, groups)
    assert set(blocked) == {
        "but3-dev-fi-td-ab", "but3-dev-fi-tp-a", "but3-dev-fi-tp-b", "but3-dev-fi-promo",
    }
    assert all(days == {(3, 1), (3, 2)} for days in blocked.values())


def test_full_promotion_sae_still_blocks_the_parcours():
    """Régression : une SAE sans restriction de groupe garde l'ancien comportement."""
    sae_days = {"WS501D": {(2, 3), (2, 4)}}
    sessions = [_session(1, course_code="WS501D", parcours="BUT3-DEV-FI")]

    assert sae_blocked_days_by_parcours(sessions, sae_days, {}) == {
        "BUT3-DEV-FI": {(2, 3), (2, 4)}
    }
    assert sae_blocked_days_by_group(sessions, sae_days, {}, load_groups(CONFIG)) == {}


# --------------------------------------------------------------------------
# Ordre souple entre enseignants
# --------------------------------------------------------------------------


def test_wra505c_teacher_order_is_configured():
    rule = next(r for r in load_course_teacher_orders(CONFIG) if r.course_code == "WRA505C")
    assert rule.teacher_order == ["ALO", "AFR"]


def test_teacher_order_pushes_the_first_teacher_earlier():
    rule = CourseTeacherOrderRule(
        course_code="WRA505C", semestre="S5", teacher_order=["ALO", "AFR"], weight=200
    )
    sessions = [
        _session(i, course_code="WRA505C", semestre="S5",
                 parcours="BUT3-CREACOM-FC", teacher="ALO" if i < 3 else "AFR")
        for i in range(6)
    ]

    weeks = 4
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    model.add_all_different(list(starts.values()))

    penalties = add_course_teacher_order_penalties(model, sessions, starts, [rule])
    assert penalties
    model.minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    assert solver.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def mean(codes: str) -> float:
        vals = [solver.value(starts[s.id]) for s in sessions if codes in s.teacher_codes]
        return sum(vals) / len(vals)

    assert mean("ALO") < mean("AFR")


# --------------------------------------------------------------------------
# Blocs de N créneaux bornés en nombre
# --------------------------------------------------------------------------


def test_wra308m_merges_only_the_last_three_td():
    rule = next(r for r in load_double_sessions(CONFIG) if r.course_code == "WRA308M")
    assert (rule.slots_per_session, rule.pair_from, rule.max_blocks) == (3, "end", 1)

    sequence = [{"ordre": i, "type": "TD", "eval": False} for i in range(1, 7)]
    merged = _merge_double_sessions(sequence, rule)

    assert [(e["ordre"], e.get("duration_slots", 1)) for e in merged] == [
        (1, 1), (2, 1), (3, 1), (4, 3),
    ]


def test_max_blocks_none_keeps_previous_behaviour():
    """Régression : sans `max_blocks`, tout ce qui colle est fusionné."""
    rule = next(r for r in load_double_sessions(CONFIG) if r.course_code == "WR110")
    assert rule.max_blocks is None

    sequence = [{"ordre": i, "type": "TP", "eval": False} for i in range(1, 5)]
    merged = _merge_double_sessions(sequence, rule)
    assert [(e["ordre"], e.get("duration_slots", 1)) for e in merged] == [(1, 2), (3, 2)]


# --------------------------------------------------------------------------
# Duos synchronisés : paires de salles DISTINCTES = groupes de non-
# chevauchement indépendants (correction du 11/08/2026)
# --------------------------------------------------------------------------


def _duo_episode_session(idx: int, course_code: str, teacher: str, order: int, tp_group: str) -> SessionToPlace:
    return SessionToPlace(
        id=f"{course_code}-{teacher}-{idx}",
        course_code=course_code,
        course_name="Test",
        semestre="S3",
        parcours="BUT2-DEV-FI",
        annee="BUT2",
        session_type=SessionType.TP,
        sequence_order=order,
        group_ids=[tp_group],
        teacher_codes=[teacher],
    )


def test_duo_room_pairs_are_grouped_separately():
    """`rare_rooms` doit partitionner les épisodes, pas les fusionner tous
    dans un seul groupe — sinon un cours dev (WR112/WR113) et un cours
    audiovisuel (WR110) se disputent la même ressource pour rien."""
    duos = [
        TeacherDuo(teacher_codes=("KBR", "KNG"), course_codes=["WR110"], rare_rooms=("h017", "h022")),
        TeacherDuo(teacher_codes=("RDE", "FME"), course_codes=["WR112"], rare_rooms=("h201", "h203")),
        TeacherDuo(teacher_codes=("FLI", "AHA"), course_codes=["WR112"], rare_rooms=("h007", "h008")),
    ]
    sessions = [
        _duo_episode_session(1, "WR110", "KBR", 1, "A"),
        _duo_episode_session(2, "WR110", "KNG", 1, "B"),
        _duo_episode_session(3, "WR112", "RDE", 1, "A"),
        _duo_episode_session(4, "WR112", "FME", 1, "C"),
        _duo_episode_session(5, "WR112", "FLI", 1, "E"),
        _duo_episode_session(6, "WR112", "AHA", 1, "F"),
    ]

    grouped = duo_episode_pairs_by_room(sessions, duos)

    assert set(grouped) == {("h017", "h022"), ("h201", "h203"), ("h007", "h008")}
    assert len(grouped[("h017", "h022")]) == 1
    assert len(grouped[("h201", "h203")]) == 1
    assert len(grouped[("h007", "h008")]) == 1


def test_duos_on_different_room_pairs_can_run_at_the_same_time():
    """
    Cœur du bug corrigé : avant la correction, TOUS les duos étaient
    sérialisés dans un seul NoOverlap ("duo_rare_room"), qu'ils partagent ou
    non une vraie ressource physique — un épisode WR110 (Studio) et un
    épisode WR112 (salles dev) ne pouvaient jamais coïncider dans le temps,
    alors qu'ils n'utilisent pas la même salle. Ce test échouerait (aucune
    solution avec les deux au même instant) sur l'ancien code.
    """
    duo_studio = TeacherDuo(teacher_codes=("KBR", "KNG"), course_codes=["WR110"], rare_rooms=("h017", "h022"))
    duo_dev = TeacherDuo(teacher_codes=("RDE", "FME"), course_codes=["WR112"], rare_rooms=("h201", "h203"))
    sessions = [
        _duo_episode_session(1, "WR110", "KBR", 1, "A"),
        _duo_episode_session(2, "WR110", "KNG", 1, "B"),
        _duo_episode_session(3, "WR112", "RDE", 1, "A"),
        _duo_episode_session(4, "WR112", "FME", 1, "C"),
    ]

    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, 5, s.id) for s in sessions}
    add_duo_synchronized_rare_room_constraints(model, sessions, starts, [duo_studio, duo_dev])
    # Force les deux duos au MÊME instant : ne doit PAS être interdit, puisque
    # Studio et salles dev sont des ressources physiques différentes.
    model.add(starts["WR110-KBR-1"] == starts["WR112-RDE-3"])

    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        "un duo Studio (WR110) et un duo salles dev (WR112) devraient pouvoir "
        "coïncider dans le temps : ils n'utilisent pas la même ressource physique"
    )


def test_duos_on_the_same_room_pair_still_cannot_overlap():
    """Régression : deux duos qui PARTAGENT réellement une paire de salles
    (les deux duos WR110 sur le Studio) doivent rester mutuellement exclusifs."""
    duo1 = TeacherDuo(teacher_codes=("KBR", "KNG"), course_codes=["WR110"], rare_rooms=("h017", "h022"))
    duo2 = TeacherDuo(teacher_codes=("FLI", "VBU"), course_codes=["WR110"], rare_rooms=("h017", "h022"))
    sessions = [
        _duo_episode_session(1, "WR110", "KBR", 1, "A"),
        _duo_episode_session(2, "WR110", "KNG", 1, "B"),
        _duo_episode_session(3, "WR110", "FLI", 1, "E"),
        _duo_episode_session(4, "WR110", "VBU", 1, "F"),
    ]

    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, 5, s.id) for s in sessions}
    add_duo_synchronized_rare_room_constraints(model, sessions, starts, [duo1, duo2])
    model.add(starts["WR110-KBR-1"] == starts["WR110-FLI-3"])

    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status == cp_model.INFEASIBLE, (
        "deux duos sur la MÊME paire de salles (Studio) ne doivent jamais coïncider"
    )
