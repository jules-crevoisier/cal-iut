"""
Régénération manuelle ciblée (1 semaine, ou 2 semaines consécutives) — cf.
plan "gestion manuelle du planning" : un enseignant absent, un cours à
déplacer, sans jamais recalculer tout le semestre ni toucher une semaine déjà
passée/en cours. Orchestration séparée de `api/main.py` (déjà volumineux)
mais appelée depuis là-bas (job asynchrone, même patron que `/solve/async`).
"""

from __future__ import annotations

from dataclasses import dataclass

from cal_iut.calendar.academic import semester_week_offset, week_status
from cal_iut.db.models import ScheduleException
from cal_iut.db.repository import PlanningRepository
from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR
from cal_iut.ingestion.planning_loader import (
    load_mmi_planning_for_semestres,
    planning_event_blocked_slots_by_parcours,
    sae_group_labels_by_course,
)
from cal_iut.models.entities import TeacherAvailability
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import SLOTS_PER_DAY
from cal_iut.solver.constraints import sae_blocked_days_by_group, sae_blocked_days_by_parcours
from cal_iut.solver.decomposed import (
    SLOTS_PER_WEEK,
    _build_sequence_neighbors,
    _movable_bounds,
    solve_week_detail,
)
from cal_iut.solver.rooms import PlacedSession, PlacedSessionWithRoom, assign_rooms

# Plafond hebdo enseignant repris de `assign_weeks` (decomposed.py, défaut
# réel de l'étage 2) — source de vérité unique pour rester cohérent avec le
# dernier run complet. Confirmé par Kyllian Bresson (05/08/2026) : 40h max
# "devant étudiant" si un plafond doit exister, donc 26 créneaux (39h).
_TEACHER_WEEKLY_CAP_SLOTS = 26


class RegenError(Exception):
    """Erreur métier (portée invalide, semaine gelée, rien à régénérer...) — 409 côté API."""


@dataclass
class RegenResult:
    status: str
    touched_weeks: list[int]
    placements: list[PlacedSessionWithRoom]
    message: str = ""


def resolve_semestre(state) -> str:
    semestre = state.filter_semestre or (
        SEMESTRE_GROUP_ANCHOR.get(state.semestre_group) if state.semestre_group else None
    )
    if not semestre and state.sessions:
        semestre = state.sessions[0].semestre
    if not semestre:
        raise RegenError("Semestre indéterminé — lancez POST /ingest d'abord")
    return semestre


def check_weeks_editable(state, weeks: list[int]) -> None:
    semestre = resolve_semestre(state)
    for w in weeks:
        status = week_status(state.calendar, semestre, w)
        if status != "future":
            raise RegenError(f"Semaine {w + 1} non modifiable (statut : {status})")


def _target_sessions(state, weeks: list[int]) -> tuple[list[SessionToPlace], list[SessionToPlace]]:
    """Séances de la portée demandée, scindées (mobiles / verrouillées) à
    partir du dernier planning courant (`state.timetable`), PAS d'un
    recalcul de l'étage 2 — la régénération réutilise l'assignation semaine
    déjà en place, elle ne la refait pas."""
    week_set = set(weeks)
    movable: list[SessionToPlace] = []
    locked: list[SessionToPlace] = []
    for p in state.timetable:
        if p.week not in week_set:
            continue
        s = state.sessions_by_id.get(p.session_id)
        if s is None:
            continue
        (locked if s.locked else movable).append(s)
    return movable, locked


def _merge_adhoc_teacher_exceptions(
    base: list[TeacherAvailability], rows: list[ScheduleException]
) -> list[TeacherAvailability]:
    """
    Fusionne les exceptions ponctuelles actives (DB) dans la liste de dispos
    enseignants, PAR `teacher_code` — jamais en écrasant une entrée
    existante : `add_teacher_availability_constraints` indexe par code
    (`avail_by_code = {a.teacher_code: a for a in availability}`), une 2e
    entrée pour le même prof effacerait silencieusement la 1re.

    Réutilise le mécanisme `metadata["forbidden_dates"]` déjà supporté par le
    solveur (aucun changement solveur nécessaire pour ce cas). Une exception
    à créneaux partiels (`slots` renseigné) est traitée comme une journée
    entière pour l'instant (simplification assumée : sur-bloquer est sans
    risque, jamais incorrect — affiner si le besoin se confirme à l'usage).
    Hors de la fenêtre régénérée, une date n'a de toute façon aucun effet :
    `add_teacher_availability_constraints` résout chaque date contre le
    calendrier TRANCHÉ (1-2 semaines) et ignore silencieusement celles qui
    ne s'y trouvent pas.
    """
    merged: dict[str, TeacherAvailability] = {a.teacher_code: a for a in base}
    for row in rows:
        if row.kind != "teacher_absence" or not row.teacher_code:
            continue
        existing = merged.get(row.teacher_code)
        forbidden_dates = set((existing.metadata.get("forbidden_dates") if existing else None) or [])
        forbidden_dates.add(row.exception_date.isoformat())
        if existing:
            merged[row.teacher_code] = existing.model_copy(
                update={"metadata": {**existing.metadata, "forbidden_dates": sorted(forbidden_dates)}}
            )
        else:
            merged[row.teacher_code] = TeacherAvailability(
                teacher_code=row.teacher_code, metadata={"forbidden_dates": sorted(forbidden_dates)}
            )
    return list(merged.values())


def _placement_dict(p: PlacedSessionWithRoom) -> dict[str, object]:
    return {
        "session_id": p.session_id,
        "week": p.week,
        "day": p.day,
        "slot": p.slot,
        "course_code": p.course_code,
        "room_id": getattr(p, "room_id", None),
        "room_label": getattr(p, "room_label", None),
        "locked": False,  # seules des séances non verrouillées (`movable`) sont jamais réécrites ici
    }


def regen_and_persist(state, repo: PlanningRepository, weeks: list[int]) -> RegenResult:
    if len(weeks) not in (1, 2) or (len(weeks) == 2 and weeks[1] != weeks[0] + 1):
        raise RegenError("La régénération porte sur 1 semaine, ou 2 semaines consécutives")
    check_weeks_editable(state, weeks)

    semestre = resolve_semestre(state)
    week_offset = semester_week_offset(state.calendar, semestre)
    absolute_week = week_offset + weeks[0]
    num_weeks = len(weeks)
    week_set = set(weeks)

    movable, locked_in_scope = _target_sessions(state, weeks)
    if not movable and not locked_in_scope:
        raise RegenError("Aucune séance dans la portée demandée")
    if not movable:
        raise RegenError("Toutes les séances de cette portée sont verrouillées — rien à régénérer")

    all_in_scope = movable + locked_in_scope
    n_weeks_horizon = max((p.week for p in state.timetable), default=0) + 1

    # SAE : mêmes jours bloqués que le run complet (cf. `solve_decomposed`),
    # recalculés sur les seules séances de la portée — suffisant, la
    # sanctuarisation ne dépend que du `parcours`, présent dans ce sous-ensemble.
    #
    # `load_mmi_planning_for_semestres` (pas `load_mmi_planning(root, semestre)`
    # seul) : bug réel corrigé 07/08/2026 (cf. docs/DATA.md §37) — `semestre`
    # ici n'est que l'ANCRE du groupe multi-parcours ("S1" pour odd), la
    # portée régénérée peut très bien contenir des séances BUT2/BUT3 (S3/S5)
    # dont les fenêtres SAE ne sont QUE sur leurs propres feuilles.
    project_root = state.config_dir.parents[1]
    real_semestres = sorted({s.semestre for s in all_in_scope}) or [semestre]
    planning = load_mmi_planning_for_semestres(project_root, real_semestres)
    from cal_iut.ingestion.planning_loader import sae_windows_as_week_days

    sae_days_by_course = sae_windows_as_week_days(
        planning, state.calendar.date_to_week_day, week_offset, n_weeks_horizon
    )
    sae_group_labels = sae_group_labels_by_course(planning)
    blocked_by_parcours_abs = (
        sae_blocked_days_by_parcours(all_in_scope, sae_days_by_course, sae_group_labels)
        if sae_days_by_course
        else {}
    )
    # SAE ne datée que pour certains groupes TD (ex. WS502D) : rattachée aux
    # groupes concernés, pas au parcours entier (cf. `sae_blocked_days_by_group`).
    blocked_by_group_abs = (
        sae_blocked_days_by_group(all_in_scope, sae_days_by_course, sae_group_labels, state.groups)
        if sae_days_by_course and sae_group_labels
        else {}
    )
    # `sae_days_by_course`/`blocked_by_parcours_abs` sont en semaine RELATIVE
    # (à `week_offset`, même convention que `state.timetable[...].week` et
    # `weeks[0]`) — PAS `absolute_week` (index absolu dans
    # `calendar.teaching_mondays`, utilisé uniquement pour `solve_week_detail`).
    def _to_local_days(source: dict[str, set[tuple[int, int]]]) -> dict[str, set[tuple[int, int]]]:
        out: dict[str, set[tuple[int, int]]] = {}
        for key, days in source.items():
            local = {(wk - weeks[0], d) for (wk, d) in days if weeks[0] <= wk < weeks[0] + num_weeks}
            if local:
                out[key] = local
        return out

    blocked_days_by_parcours_week = _to_local_days(blocked_by_parcours_abs)
    blocked_days_by_group_week = _to_local_days(blocked_by_group_abs)

    planning_event_blocked_abs = planning_event_blocked_slots_by_parcours(
        planning, state.calendar.date_to_week_day_any, week_offset, n_weeks_horizon
    )
    planning_event_blocked_local = {
        parcours: {(wk - weeks[0], d, s) for (wk, d, s) in slots if wk in week_set}
        for parcours, slots in planning_event_blocked_abs.items()
    }
    planning_event_blocked_local = {
        parcours: slots for parcours, slots in planning_event_blocked_local.items() if slots
    }

    exceptions = repo.list_exceptions(active_only=True)
    teacher_availability = _merge_adhoc_teacher_exceptions(state.teacher_availability, exceptions)

    # `fixed` : séances verrouillées dans la portée -> pinnées à leur créneau
    # LOCAL actuel (incluses dans le modèle pour les NoOverlap, jamais déplacées).
    placement_by_session = {p.session_id: p for p in state.timetable}
    fixed: dict[str, int] = {}
    for s in locked_in_scope:
        p = placement_by_session[s.id]
        local_week = p.week - weeks[0]
        fixed[s.id] = local_week * SLOTS_PER_WEEK + p.day * SLOTS_PER_DAY + p.slot

    allowed_weeks: dict[str, set[int]] | None = None
    if num_weeks > 1:
        # Bornes de déplacement (ordre pédagogique) : recalculées sur TOUTES
        # les séances connues (pas juste la portée) pour voir les voisins
        # hors fenêtre — réutilise telles quelles les fonctions déjà en place
        # pour le rééquilibrage étage 3 (`_build_sequence_neighbors`/`_movable_bounds`).
        # `state.groups` est indispensable : sans lui, `_build_sequence_neighbors`
        # ne rend que l'ordre au sein d'un MÊME group_id brut et ignore les
        # paires inter-granularités (CM promo ↔ TD/TP de sous-groupe). Une
        # régénération sur deux semaines pouvait alors déplacer un CM APRÈS les
        # TD qu'il doit précéder — exactement le défaut corrigé le 25/08/2026
        # sur le rééquilibrage de l'étage 3, qui subsistait ici.
        neighbors = _build_sequence_neighbors(state.sessions, state.groups)
        # Semaine RELATIVE (même convention que `state.timetable[...].week`),
        # pas `absolute_week` — `_movable_bounds` a été conçu pour ce référentiel.
        week_by_session_rel = {p.session_id: p.week for p in state.timetable}
        allowed_weeks = {}
        for s in movable:
            lo_rel, hi_rel = _movable_bounds(s.id, neighbors, week_by_session_rel, n_weeks_horizon)
            lo_local = max(0, lo_rel - weeks[0])
            hi_local = min(num_weeks - 1, hi_rel - weeks[0])
            allowed_weeks[s.id] = set(range(lo_local, hi_local + 1)) if hi_local >= lo_local else {0}

    status, local_result = solve_week_detail(
        all_in_scope,
        absolute_week,
        teacher_availability=teacher_availability,
        calendar=state.calendar,
        student_presences=state.student_presences,
        groups=state.groups,
        blocked_days_by_parcours_week=blocked_days_by_parcours_week or None,
        blocked_days_by_group_week=blocked_days_by_group_week or None,
        duos=state.teacher_duos,
        planning_event_blocked_local=planning_event_blocked_local or None,
        num_weeks=num_weeks,
        fixed=fixed,
        allowed_weeks=allowed_weeks,
        teacher_weekly_cap_slots=_TEACHER_WEEKLY_CAP_SLOTS if num_weeks > 1 else None,
        time_limit_seconds=90 if num_weeks == 1 else 150,
    )
    if status not in ("OPTIMAL", "FEASIBLE"):
        return RegenResult(status=status, touched_weeks=weeks, placements=[], message=f"Échec ({status}) — planning inchangé, rien n'a été modifié")

    new_placements: list[PlacedSession] = []
    for s in movable:
        t = local_result[s.id]
        local_week, rem = divmod(t, SLOTS_PER_WEEK)
        day, slot = divmod(rem, SLOTS_PER_DAY)
        new_placements.append(
            PlacedSession(
                session_id=s.id, week=weeks[0] + local_week, day=day, slot=slot,
                course_code=s.course_code, group_ids=s.group_ids, teacher_codes=s.teacher_codes,
            )
        )

    # Garde-fou explicite : ne jamais écrire un id hors de la portée calculée.
    scope_ids = {s.id for s in movable}
    returned_ids = {p.session_id for p in new_placements}
    if not returned_ids <= scope_ids:
        raise RegenError("Régénération a produit des séances hors de la portée demandée — annulé")

    # Salles : seed avec la salle déjà utilisée par le même cours HORS de la
    # fenêtre régénérée (`same_room_for_course`) — un cours qui n'a pas
    # changé de semaine ne doit pas changer de salle non plus.
    course_cm_room_seed: dict[str, str] = {}
    for p in state.timetable:
        if p.week in week_set:
            continue
        room_id = getattr(p, "room_id", None)
        if room_id:
            course_cm_room_seed.setdefault(p.course_code, room_id)

    with_rooms = assign_rooms(
        new_placements, state.sessions_by_id, state.rooms, state.groups, state.room_rules,
        state.teacher_duos, course_cm_room_seed=course_cm_room_seed,
        reserved=getattr(state, "room_reservations", None),
    )

    # Écrit UNIQUEMENT les séances touchées dans l'état en mémoire (jamais un
    # remplacement global de `state.timetable`).
    by_id = {p.session_id: p for p in with_rooms}
    state.timetable = [by_id.get(p.session_id, p) for p in state.timetable]

    if state.current_run_id:
        repo.upsert_current_placements(state.current_run_id, [_placement_dict(p) for p in with_rooms])
        for p in with_rooms:
            old = placement_by_session.get(p.session_id)
            if old:
                repo.save_correction(
                    state.current_run_id, p.session_id,
                    {"week": old.week, "day": old.day, "slot": old.slot},
                    {"week": p.week, "day": p.day, "slot": p.slot},
                    False, False, p.course_code, p.teacher_codes,
                )

    return RegenResult(status=status, touched_weeks=weeks, placements=with_rooms, message="")
