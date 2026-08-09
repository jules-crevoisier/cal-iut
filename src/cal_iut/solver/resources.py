"""Ressources NoOverlap — un IntervalVar par contrainte (règle OR-Tools)."""

from __future__ import annotations

from ortools.sat.python import cp_model

from cal_iut.models.entities import Group
from cal_iut.models.group_scope import parent_td_for_tp
from cal_iut.models.session import SessionToPlace


def add_aliased_no_overlap(
    model: cp_model.CpModel,
    session_starts: dict[str, cp_model.IntVar],
    session_ids: list[str],
    resource_key: str,
    durations: dict[str, int] | None = None,
) -> None:
    """
    NoOverlap sur une ressource.

    OR-Tools interdit de réutiliser le même IntervalVar dans plusieurs NoOverlap.
    On crée donc un intervalle alias lié au même start pour chaque ressource.

    `durations` (optionnel) : nombre de créneaux occupés par séance (défaut 1
    si absent/non renseigné) — une séance "double" (`duration_slots=2`, ex.
    TP WR110 collé en bloc de 3h) doit occuper 2 créneaux consécutifs dans
    CETTE ressource aussi, pas seulement dans le plafond horaire hebdomadaire.
    """
    unique_ids = list(dict.fromkeys(session_ids))
    if len(unique_ids) < 2:
        return

    intervals: list[cp_model.IntervalVar] = []
    for sid in unique_ids:
        start = session_starts[sid]
        duration = max(1, (durations or {}).get(sid, 1))
        intervals.append(
            model.new_interval_var(start, duration, start + duration, f"iv_{resource_key}_{sid}")
        )
    model.add_no_overlap(intervals)


def build_student_cohorts(groups: list[Group]) -> dict[str, set[str]]:
    """
    Cohorte étudiant = ce qu'un élève d'un TP voit en même temps.

    - CM promo + TD parent + son TP (pas l'autre TP du binôme)
    - Clé = id du TP (ou du TD s'il n'a pas de TP)
    """
    cohorts: dict[str, set[str]] = {}
    promo_by_parcours = {g.parcours: g.id for g in groups if g.kind == "promo"}
    tp_groups = [g for g in groups if g.kind == "tp"]
    td_groups = [g for g in groups if g.kind == "td"]

    for tp in tp_groups:
        cohort: set[str] = {tp.id}
        parent = parent_td_for_tp(tp, groups)
        if parent:
            cohort.add(parent.id)
        promo = promo_by_parcours.get(tp.parcours)
        if promo:
            cohort.add(promo)
        cohorts[f"student:{tp.id}"] = cohort

    # TD sans TP résolu : cohorte promo+TD
    covered_tds = {
        parent_td_for_tp(tp, groups).id
        for tp in tp_groups
        if parent_td_for_tp(tp, groups) is not None
    }
    for td in td_groups:
        if td.id in covered_tds:
            continue
        cohort = {td.id}
        promo = promo_by_parcours.get(td.parcours)
        if promo:
            cohort.add(promo)
        cohorts[f"student:{td.id}"] = cohort

    return cohorts


def add_student_and_teacher_no_overlap(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    groups: list[Group],
    *,
    enforce_student_cohort: bool = True,
) -> None:
    """Contraintes dures d'occupation : enseignants + cohortes étudiants."""
    durations = {s.id: max(1, s.duration_slots) for s in sessions}

    # Enseignants
    by_teacher: dict[str, list[str]] = {}
    for session in sessions:
        for tid in session.teacher_codes:
            by_teacher.setdefault(tid, []).append(session.id)
    for tid, sids in by_teacher.items():
        add_aliased_no_overlap(model, session_starts, sids, f"teacher:{tid}", durations)

    if not enforce_student_cohort or not groups:
        # Fallback : NoOverlap par group_id exact
        by_group: dict[str, list[str]] = {}
        for session in sessions:
            for gid in session.group_ids:
                by_group.setdefault(gid, []).append(session.id)
        for gid, sids in by_group.items():
            add_aliased_no_overlap(model, session_starts, sids, f"group:{gid}", durations)
        return

    cohorts = build_student_cohorts(groups)
    for resource_key, cohort_ids in cohorts.items():
        sids = [
            s.id
            for s in sessions
            if cohort_ids.intersection(s.group_ids)
        ]
        add_aliased_no_overlap(model, session_starts, sids, resource_key, durations)
