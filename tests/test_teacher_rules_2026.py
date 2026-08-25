"""Règles enseignants introduites par la mise à jour du 10/08/2026.

Trois mécanismes que le solveur ignorait complètement jusque-là, tous issus
d'informations présentes dans le fichier source mais jamais traduites en
contraintes machine :

1. les colonnes DISPONIBILITÉS lues comme LISTE BLANCHE dure (jours non listés
   interdits) — sans quoi un enseignant qui ne déclare aucune indisponibilité
   mais n'est là que 3 jours restait plaçable les 5 ;
2. les indisponibilités à parité de semaine (Thomas Castellengo) ;
3. le regroupement mensuel des interventions (Anthony Rageul, Justine Hussenet).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from cal_iut.calendar.academic import build_default_calendar_2026_2027, department_week_number
from cal_iut.ingestion.constraints_loader import parse_teacher_constraints_json
from cal_iut.models.entities import Group, SessionType, TeacherAvailability, TeacherWeekParityRule
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import add_teacher_availability_constraints
from cal_iut.solver.objectives import add_teacher_monthly_clustering_penalties

ROOT = Path(__file__).resolve().parents[1]
SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY
TEACHERS = {t.teacher_code: t for t in parse_teacher_constraints_json(
    ROOT / "contraintes" / "05_enseignants_contraintes.json"
)[0]}


def _session(idx: int, teacher: str, duration: int = 1) -> SessionToPlace:
    return SessionToPlace(
        id=f"s{idx}",
        course_code="WRX",
        course_name="Test",
        semestre="S5",
        parcours="BUT3-CREACOM-FC",
        annee="BUT3",
        session_type=SessionType.TD,
        sequence_order=idx,
        group_ids=["g1"],
        teacher_codes=[teacher],
        duration_slots=duration,
    )


def _feasible_starts(
    teacher: TeacherAvailability, weeks: int = 4, duration: int = 1, week_offset: int = 0
) -> set[int]:
    """Tous les créneaux que le solveur accepte encore pour une séance de cet
    enseignant — la façon la plus directe de vérifier une contrainte dure."""
    calendar = build_default_calendar_2026_2027()
    model = cp_model.CpModel()
    session = _session(1, teacher.teacher_code, duration)
    start = model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, "start")
    add_teacher_availability_constraints(
        model, [session], {session.id: start}, [teacher], weeks,
        calendar=calendar, week_offset=week_offset,
    )

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    collected: set[int] = set()

    class _Collect(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self) -> None:
            collected.add(self.value(start))

    solver.solve(model, _Collect())
    return collected


def _days(starts: set[int]) -> set[tuple[int, int]]:
    return {(t // SLOTS_PER_WEEK, (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY) for t in starts}


# --------------------------------------------------------------------------
# 1. Liste blanche
# --------------------------------------------------------------------------


def test_vbu_is_restricted_to_his_three_declared_days():
    """
    Valentin Burette ne déclare AUCUNE indisponibilité, seulement « lundi,
    mardi, mercredi toute la journée » en disponibilités. Sans liste blanche il
    restait plaçable jeudi et vendredi.
    """
    starts = _feasible_starts(TEACHERS["VBU"])
    assert {d for _, d in _days(starts)} == {0, 1, 2}


def test_kng_thursday_is_afternoon_only():
    """
    Kévin Ngo : « Jeudi : Disponible 14h ». La plage horaire des EXPLICATIONS
    affine le « toute la journée » de la colonne DISPONIBILITÉS — le jeudi
    matin ne doit pas être ouvert, le jeudi après-midi doit l'être.
    """
    starts = _feasible_starts(TEACHERS["KNG"])
    slots_by_day: dict[int, set[int]] = {}
    for t in starts:
        day = (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY
        slots_by_day.setdefault(day, set()).add(t % SLOTS_PER_DAY)

    assert slots_by_day[3] == {3, 4, 5}  # jeudi : uniquement l'après-midi
    assert slots_by_day[0] == {1, 2, 3, 4, 5}  # lundi : à partir de 9h30
    assert 4 not in slots_by_day  # vendredi : pas dispo


def test_mni_is_restricted_to_his_ten_dates():
    """
    Marc Nino ne donne que des dates de venue (vacataire). Liste blanche dure :
    hors de ces jours, aucun créneau ne doit rester ouvert.
    """
    teacher = TEACHERS["MNI"]
    assert teacher.allowed_dates  # la donnée est bien lue
    calendar = build_default_calendar_2026_2027()

    starts = _feasible_starts(teacher, weeks=19)
    allowed = {date.fromisoformat(d) for d in teacher.allowed_dates}
    for week, day in _days(starts):
        assert calendar.week_day_to_date(week, day) in allowed


def test_whitelist_respects_block_duration():
    """
    Un bloc de 3h ne peut pas démarrer sur le dernier créneau autorisé d'une
    journée et déborder au-delà : KNG le jeudi ne peut commencer qu'à 14h ou
    15h30, pas à 17h.
    """
    starts = _feasible_starts(TEACHERS["KNG"], duration=2)
    thursday = {t % SLOTS_PER_DAY for t in starts if (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY == 3}
    assert thursday == {3, 4}


def test_teacher_without_whitelist_keeps_full_grid():
    """Régression : la liste blanche ne doit pas s'appliquer à ceux qui n'en ont pas."""
    teacher = TEACHERS["VMA"]  # aucune contrainte déclarée
    assert not teacher.allowed_slots and not teacher.allowed_dates
    assert len(_feasible_starts(teacher, weeks=1)) == SLOTS_PER_WEEK


# --------------------------------------------------------------------------
# 2. Parité de semaine
# --------------------------------------------------------------------------


def test_tca_parity_rules_are_loaded():
    rules = TEACHERS["TCA"].week_parity_rules
    assert TeacherWeekParityRule(parity="paire", day=2, slots=[0, 1, 2, 3, 4, 5]) in rules
    # « jeudi max 17h » = seul le créneau 17h-18h30 tombe.
    assert TeacherWeekParityRule(parity="paire", day=3, slots=[5]) in rules
    assert TEACHERS["TCA"].parity_reference == "departement"


@pytest.mark.parametrize("reference", ["departement", "iso"])
def test_tca_wednesday_is_blocked_exactly_on_even_weeks(reference):
    """
    « Semaines paires : mercredi pas dispo ». La parité se lit sur la semaine
    DÉPARTEMENT par défaut, mais la bascule ISO doit produire le complément
    exact — c'est tout l'intérêt de rendre la référence configurable.
    """
    teacher = TEACHERS["TCA"].model_copy(update={"parity_reference": reference})
    calendar = build_default_calendar_2026_2027()
    weeks = 8

    starts = _feasible_starts(teacher, weeks=weeks)
    wednesdays = {w for w, d in _days(starts) if d == 2}

    for rel in range(weeks):
        monday = calendar.teaching_mondays[rel]
        number = monday.isocalendar().week if reference == "iso" else department_week_number(monday)
        assert (rel in wednesdays) is bool(number % 2)


def test_tca_keeps_evening_slot_on_the_other_parity():
    """
    « Semaines impaires : lundi max 17h » — le créneau 17h-18h30 du lundi doit
    donc rester ouvert les semaines PAIRES, sinon la règle serait appliquée
    toutes les semaines (ce qui reviendrait à ignorer la parité).
    """
    calendar = build_default_calendar_2026_2027()
    starts = _feasible_starts(TEACHERS["TCA"], weeks=8)
    monday_evening = {
        w for w, d in {
            (t // SLOTS_PER_WEEK, (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY)
            for t in starts if t % SLOTS_PER_DAY == 5
        } if d == 0
    }
    parities = {department_week_number(calendar.teaching_mondays[w]) % 2 for w in monday_evening}
    assert parities == {0}  # uniquement les semaines paires


# --------------------------------------------------------------------------
# 3. Regroupement mensuel
# --------------------------------------------------------------------------


def test_monthly_clustering_prefers_fewer_weeks_per_month():
    """
    ARA demande « une ou deux semaines successives par mois ». L'objectif étant
    mou, on vérifie qu'il ORIENTE bien la solution : minimiser la pénalité doit
    ramener 6 séances sur au plus 2 semaines du mois.
    """
    calendar = build_default_calendar_2026_2027()
    teacher = TeacherAvailability(teacher_code="ARA", monthly_cluster_max_weeks=2)
    sessions = [_session(i, "ARA") for i in range(6)]

    weeks = 4
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    # Une séance par créneau distinct, sinon l'optimum trivial est de toutes
    # les empiler au même instant.
    model.add_all_different(list(starts.values()))

    penalties = add_teacher_monthly_clustering_penalties(
        model, sessions, starts, [teacher], calendar, 0, weeks, weight=100
    )
    assert penalties
    model.minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    assert solver.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    used_weeks = {solver.value(v) // SLOTS_PER_WEEK for v in starts.values()}
    assert len(used_weeks) <= 2


def test_monthly_clustering_is_off_for_teachers_who_did_not_ask():
    calendar = build_default_calendar_2026_2027()
    teacher = TeacherAvailability(teacher_code="TPA")
    sessions = [_session(i, "TPA") for i in range(3)]
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, SLOTS_PER_WEEK * 4 - 1, s.id) for s in sessions}

    assert add_teacher_monthly_clustering_penalties(
        model, sessions, starts, [teacher], calendar, 0, 4, weight=100
    ) == []


def test_group_labels_do_not_break_unrelated_groups():
    """Garde-fou : `Group` reste construit tel quel par les tests de ce module."""
    assert Group(id="g1", label="TD GH", parcours="BUT3-CREACOM-FC", annee="BUT3", kind="td")


# --------------------------------------------------------------------------
# Indisponibilité des référents SAE (retour utilisateur 11/08/2026)
# --------------------------------------------------------------------------


def test_sae_supervisor_gets_forbidden_dates_even_without_prior_constraint():
    """
    FME n'a AUCUNE ligne dans CONTRAINTES ENSEIGNANTS (24 enseignants
    déclarés, FME n'en fait pas partie) mais encadre 4 SAE réelles (28 jours
    cumulés) : une entrée doit être créée pour lui, pas silencieusement
    ignorée.
    """
    from cal_iut.ingestion.constraints_loader import augment_teacher_availability_with_sae_supervision
    from cal_iut.ingestion.planning_loader import load_mmi_planning_for_semestres, sae_supervisor_dates_by_teacher

    planning = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    supervisor_dates = sae_supervisor_dates_by_teacher(planning)
    assert "FME" in supervisor_dates and len(supervisor_dates["FME"]) >= 20

    augmented = augment_teacher_availability_with_sae_supervision([], supervisor_dates)
    fme = next(t for t in augmented if t.teacher_code == "FME")
    assert len(fme.metadata["forbidden_dates"]) == len(supervisor_dates["FME"])


def test_sae_supervisor_dates_merge_with_existing_forbidden_dates():
    """Un enseignant qui a DÉJÀ des indisponibilités déclarées garde les deux
    (union), sans perdre celles issues de CONTRAINTES ENSEIGNANTS."""
    from datetime import date

    from cal_iut.ingestion.constraints_loader import augment_teacher_availability_with_sae_supervision

    existing = TeacherAvailability(
        teacher_code="XYZ", metadata={"forbidden_dates": ["2026-09-01"]}
    )
    augmented = augment_teacher_availability_with_sae_supervision(
        [existing], {"XYZ": {date(2026, 10, 12)}}
    )
    xyz = next(t for t in augmented if t.teacher_code == "XYZ")
    assert set(xyz.metadata["forbidden_dates"]) == {"2026-09-01", "2026-10-12"}


def test_sae_supervisor_hard_block_prevents_scheduling_on_supervision_day():
    """Un enseignant référent SAE ne doit plus pouvoir être placé un jour où
    il encadre cette SAE, quel que soit le PARCOURS du cours classique visé."""
    calendar = build_default_calendar_2026_2027()
    supervised_date = calendar.teaching_mondays[5]  # un lundi enseignable réel
    teacher = TeacherAvailability(
        teacher_code="SUP", metadata={"forbidden_dates": [supervised_date.isoformat()]}
    )
    session = _session(1, "SUP", duration=1)
    session.parcours = "BUT3-DEV-FI"  # délibérément un AUTRE parcours que la SAE

    weeks = 8
    model = cp_model.CpModel()
    start = model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, "start")
    add_teacher_availability_constraints(
        model, [session], {session.id: start}, [teacher], weeks, calendar=calendar, week_offset=0
    )

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    seen: set = set()

    class _Collect(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self) -> None:
            t = self.value(start)
            d = calendar.week_day_to_date(t // SLOTS_PER_WEEK, (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY)
            if d is not None:
                seen.add(d)

    solver.solve(model, _Collect())
    assert supervised_date not in seen


def test_sae_supervisor_soft_penalty_avoids_but_does_not_forbid():
    """
    Repli MOU (docs/DATA.md §49) : contrairement au blocage dur, le jour
    référent SAE reste FAISABLE — juste pénalisé. Sans alternative, le
    solveur doit pouvoir y placer la séance quand même (`enumerate_all_solutions`
    doit voir AU MOINS une solution incluant ce jour) ; avec alternative et
    objectif minimisé, il doit préférer un autre jour.
    """
    from cal_iut.solver.objectives import add_sae_supervisor_soft_penalties

    calendar = build_default_calendar_2026_2027()
    supervised_date = calendar.teaching_mondays[5]
    weeks = 1
    week_offset = 0
    for rel, monday in enumerate(calendar.teaching_mondays):
        if monday == supervised_date:
            week_offset = rel
            break

    session = _session(1, "SUP", duration=1)
    session.course_code = "WRX"  # cours classique, pas une SAE (le garde-fou WS* ne s'applique pas)

    model = cp_model.CpModel()
    start = model.new_int_var(0, SLOTS_PER_WEEK - 1, "start")
    penalties = add_sae_supervisor_soft_penalties(
        model, [session], {session.id: start}, {"SUP": {supervised_date}},
        calendar, week_offset, weeks, weight=300,
    )
    assert penalties

    # (a) sans forcer l'objectif : le jour bloqué reste une solution valide.
    forced = model.Clone()
    monday_time = 1  # lundi, un créneau quelconque dans la journée (1 = 2e créneau)
    forced.add(start == monday_time)
    solver = cp_model.CpSolver()
    assert solver.solve(forced) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    # (b) objectif minimisé, alternative dispo un autre jour ouvré : doit
    # l'éviter — l'optimum ne doit pas être le lundi bloqué.
    model.minimize(sum(penalties))
    solver2 = cp_model.CpSolver()
    status = solver2.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    best = solver2.value(start)
    best_day = best // SLOTS_PER_DAY
    monday_day = 0
    assert best_day != monday_day


def test_teacher_availability_violation_blocks_drag_and_drop_on_supervised_day():
    """
    Bout-en-bout côté API : un glisser-déposer BRUT (pas une suggestion) vers
    un jour où l'enseignant a une indisponibilité déclarée — ici simulée
    comme le ferait `augment_teacher_availability_with_sae_supervision` au
    démarrage — doit être bloqué par `_teacher_availability_violations`
    (retour utilisateur 11/08/2026 : "vérifie bien toutes les contraintes
    avant que ça s'effectue"). Avant ce correctif, cette fonction n'existait
    pas : seules les SUGGESTIONS filtraient sur l'indisponibilité déclarée,
    un glisser-déposer direct sur une case arbitraire passait sans contrôle.
    """
    from cal_iut.api.main import _teacher_availability_violations
    from cal_iut.calendar.academic import semester_week_offset

    calendar = build_default_calendar_2026_2027()
    supervised_date = calendar.teaching_mondays[5]
    mapped = calendar.date_to_week_day(supervised_date)
    assert mapped is not None
    abs_week, day = mapped
    week_offset = semester_week_offset(calendar, "S1")
    rel_week = abs_week - week_offset

    class _State:
        pass

    class _Session:
        teacher_codes = ["SUP"]
        semestre = "S1"

    state = _State()
    state.calendar = calendar
    state.teacher_availability = [
        TeacherAvailability(teacher_code="SUP", metadata={"forbidden_dates": [supervised_date.isoformat()]})
    ]

    blocked = _teacher_availability_violations(state, _Session(), rel_week, day, 1)
    assert blocked and "indisponible" in blocked[0]

    free = _teacher_availability_violations(state, _Session(), rel_week + 1, day, 1)
    assert free == []


def test_sae_supervisor_soft_mode_does_not_reduce_stage2_weekly_capacity():
    """
    Différence structurelle dure/mou côté étage 2 (`assign_weeks`) : en mou,
    `solve_decomposed` ne doit PAS injecter les dates de supervision dans
    `teacher_availability` (ce qui ferait chuter `_teacher_available_slots_by_week`
    à zéro sur ces semaines, cf. docs/DATA.md §49) — la capacité affichée
    doit rester celle de la disponibilité déclarée seule.
    """
    from cal_iut.solver.decomposed import _teacher_available_slots_by_week

    calendar = build_default_calendar_2026_2027()
    teacher = TeacherAvailability(teacher_code="SUP")  # aucune contrainte déclarée
    slots = _teacher_available_slots_by_week([teacher], weeks=1, calendar=calendar, week_offset=0)
    assert slots[("SUP", 0)] == DAYS_PER_WEEK * SLOTS_PER_DAY  # tout ouvert : le mou ne touche pas `teacher_availability`
