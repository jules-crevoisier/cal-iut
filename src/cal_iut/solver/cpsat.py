"""Modèle CP-SAT pour le University Course Timetabling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import (
    AcademicCalendar,
    build_default_calendar_2026_2027,
    default_horizon_weeks,
    semester_week_offset,
)
from cal_iut.ingestion.config_loader import load_course_min_week_rules
from cal_iut.ingestion.constraints_loader import StudentPresence
from cal_iut.ingestion.planning_loader import (
    load_mmi_planning_for_semestres,
    planning_event_blocked_slots,
    sae_windows_as_week_days,
)
from cal_iut.models.entities import Group, TeacherAvailability, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import (
    add_blocked_calendar_constraints,
    add_course_min_week_constraints,
    add_duo_synchronized_rare_room_constraints,
    add_duration_domain_constraints,
    add_eval_clustering_penalties,
    add_group_sync_penalties,
    add_ordonnancement_constraints,
    add_pedagogical_sequence_constraints,
    add_planning_event_block_constraints,
    add_s1_integration_week_lock,
    add_sae_sanctuarization_constraints,
    add_sae_window_constraints,
    add_student_presence_constraints,
    add_teacher_availability_constraints,
    add_thursday_afternoon_pac_lock,
    add_weekly_hour_cap_constraints,
    sae_blocked_days_by_parcours,
)
from cal_iut.solver.objectives import (
    add_avoid_zone_penalties,
    add_intra_day_gap_penalties,
    add_midday_fill_penalties,
    add_semester_spread_penalties,
)
from cal_iut.solver.resources import add_student_and_teacher_no_overlap


@dataclass
class SolverConfig:
    # None = calculé automatiquement depuis le calendrier réel à la résolution
    # (cf. `default_horizon_weeks`) : pour S1/S3/S5, nombre de semaines
    # enseignables jusqu'au 1er février 2027 (S2) — plus un nombre magique
    # dupliqué, une seule fonction de vérité calée sur le calendrier.
    weeks: int | None = None
    # 900s (pas 300s) : mesuré empiriquement nécessaire pour atteindre FEASIBLE
    # sur le run complet BUT1-S1 réel (1437 séances) une fois les contraintes
    # enseignants/SAE réellement actives (cf. docs/DATA.md §12.3) — à 300s le
    # solveur retombe à UNKNOWN (aucune solution). Un sous-ensemble ou un
    # warm-start (`hints`) reste bien plus rapide ; ce budget n'est atteint
    # que sur les cas déjà difficiles.
    time_limit_seconds: int = 900
    gap_weight: int = 100
    optimize_gaps: bool = True
    spread_weight: int = 2
    optimize_spread: bool = True
    # 1.0 = étale proportionnellement sur tout l'horizon S1 (lissage demandé
    # par l'utilisateur : évite que les semaines 2-11 soient pleines et 12-19
    # vides) ; <1.0 recompresse artificiellement vers le début (cf.
    # objectives.py::add_semester_spread_penalties pour l'historique).
    spread_frontload_fraction: float = 1.0
    enforce_ordonnancement: bool = True
    # Essentiel pédagogiquement (retour utilisateur), mais testé empiriquement
    # dur sur données réelles : combiné à la sanctuarisation SAE complète, ça
    # devient prouvé infaisable (cf. docs/DATA.md §11.1/§12) ; même sans les
    # dates SAE complémentaires, 20 min n'ont pas suffi à trouver une solution
    # dure, contre ~15 min de façon fiable en molle. Poids fortement relevé
    # (400, contre 80 par défaut) pour la rendre très prioritaire face aux
    # autres objectifs mous, sans risquer l'infaisabilité.
    ordonnancement_hard: bool = False
    ordonnancement_weight: int = 400
    enforce_sequence: bool = True
    enforce_group_sync: bool = True
    group_sync_weight: int = 50
    enforce_calendar: bool = True
    enforce_student_cohort: bool = True
    enforce_sae_windows: bool = True
    enforce_sae_sanctuarization: bool = True
    enforce_weekly_hour_cap: bool = True
    fi_weekly_cap_slots: int = 22  # 33h/semaine = 22 créneaux de 1h30 (dur, strict)
    fc_weekly_cap_slots: int = 23  # ~35h/semaine = 23 créneaux de 1h30 max
    # Horizon étendu réservé aux alternants uniquement (`solve_decomposed`
    # seulement, cf. `decomposed.py::assign_weeks` pour le détail) — None =
    # comportement inchangé, tous les parcours bornés à `weeks`. Retour
    # utilisateur (06/08/2026) : "oui mais que les parcours alternance" —
    # ne jamais étendre l'horizon des parcours FI par ce biais.
    fi_max_week: int | None = None
    enforce_thursday_pac_lock: bool = True
    optimize_avoid_zones: bool = True
    avoid_zone_weight: int = 15  # lundi 8h / vendredi 17h : dernier recours, molle
    optimize_midday_fill: bool = True
    midday_fill_weight: int = 8  # remplir en priorité près de la pause déjeuner
    optimize_eval_clustering: bool = True
    eval_clustering_weight: int = 30  # regrouper les évals sur une même semaine
    enforce_s1_integration_week_lock: bool = True
    enforce_duo_rare_room: bool = True
    # cf. data/config/course_scheduling_rules.yaml (ex. WR119/PPP S1 ne
    # démarre pas dès la rentrée, retour utilisateur du 04/08/2026).
    enforce_course_min_week: bool = True
    # Événements du planning officiel avec horaire explicite (ex. "9h30
    # Echange IA") : retour utilisateur, ces créneaux étaient affichés dans
    # l'interface mais pas réellement bloqués pour les cours classiques.
    enforce_planning_events: bool = True
    num_workers: int = 8
    random_seed: int = 2027  # déterminisme : même graine à chaque palier/run
    data_root: Path | None = None
    # Résolution en paliers (`solve_tiered`) : fraction de `time_limit_seconds`
    # allouée à chaque palier (ordonnancement, densification S1, confort). La
    # somme ne doit pas dépasser 1.0 ; le confort récupère aussi le temps
    # restant si un palier précédent a convergé plus vite que son budget.
    tier_time_fractions: tuple[float, float, float] = (0.3, 0.4, 0.3)


@dataclass
class PlacedSession:
    session_id: str
    week: int
    day: int
    slot: int
    course_code: str
    group_ids: list[str]
    teacher_codes: list[str]


@dataclass
class SolverResult:
    status: str
    placements: list[PlacedSession] = field(default_factory=list)
    objective_value: int | None = None
    gap_penalty: int = 0
    # Rempli uniquement par `solve_tiered` : coût atteint à chaque palier,
    # exposé séparément plutôt qu'agrégé dans `objective_value` — permet de
    # dire précisément quelle priorité métier a coûté quoi (cf. contexte du
    # chantier : la somme pondérée ne le permettait pas).
    tier_values: dict[str, int] | None = None


@dataclass
class _HardModel:
    """Modèle CP-SAT avec uniquement le palier 0 (contraintes dures) posé —
    partagé par `solve()` (somme pondérée) et `solve_tiered()` (paliers)."""

    model: cp_model.CpModel
    session_starts: dict[str, cp_model.IntVar]
    unlocked: list[SessionToPlace]
    calendar: AcademicCalendar
    semestre: str
    groups: list[Group]
    horizon: int
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None


class TimetableSolver:
    """Solveur CP-SAT : NoOverlap cohortes (alias) + progression + SAE + étalement."""

    def __init__(self, config: SolverConfig | None = None) -> None:
        self.config = config or SolverConfig()

    def _horizon(self) -> int:
        return self.config.weeks * DAYS_PER_WEEK * SLOTS_PER_DAY

    def _new_solver(self, time_limit_seconds: float) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.0, time_limit_seconds)
        solver.parameters.num_search_workers = self.config.num_workers
        solver.parameters.random_seed = self.config.random_seed
        return solver

    def _build_hard_model(
        self,
        sessions: list[SessionToPlace],
        teacher_availability: list[TeacherAvailability] | None,
        calendar: AcademicCalendar | None,
        student_presences: list[StudentPresence] | None,
        semestre: str | None,
        groups: list[Group] | None,
        sae_days_by_course: dict[str, set[tuple[int, int]]] | None,
        hints: dict[str, int] | None,
        duos: list[TeacherDuo] | None = None,
    ) -> _HardModel | None:
        """
        `hints` (warm-start) : session_id -> index temporel absolu (0..horizon-1)
        d'une solution connue (ex. run précédent). Accélère la recherche du
        premier point faisable sans changer le modèle ni les contraintes — le
        solveur reste libre de s'en écarter, la qualité/correction n'est jamais
        sacrifiée, seule la vitesse de convergence peut s'en trouver améliorée.
        """
        unlocked = [s for s in sessions if not s.locked]
        if not unlocked:
            return None

        calendar = calendar or build_default_calendar_2026_2027()
        semestre = semestre or unlocked[0].semestre
        if self.config.weeks is None:
            self.config.weeks = default_horizon_weeks(calendar, semestre)
        week_offset = semester_week_offset(calendar, semestre)
        groups = groups or []

        planning_event_blocked: set[tuple[int, int, int]] = set()
        if (
            sae_days_by_course is None
            and (self.config.enforce_sae_windows or self.config.enforce_sae_sanctuarization)
        ) or self.config.enforce_planning_events:
            root = self.config.data_root or Path(__file__).resolve().parents[3]
            # cf. docs/DATA.md §37 : `semestre` peut n'être que l'ancre d'un
            # groupe multi-parcours — charger tous les semestres réels présents.
            real_semestres = sorted({s.semestre for s in unlocked}) or [semestre]
            planning = load_mmi_planning_for_semestres(root, real_semestres)
            if sae_days_by_course is None:
                sae_days_by_course = sae_windows_as_week_days(
                    planning, calendar.date_to_week_day, week_offset, self.config.weeks
                )
            if self.config.enforce_planning_events:
                planning_event_blocked = planning_event_blocked_slots(
                    planning, calendar.date_to_week_day_any, week_offset, self.config.weeks
                )

        # Les séances SAE (WSxxx) ne sont plus planifiées par l'algorithme
        # (retour utilisateur : définies par les enseignants eux-mêmes) —
        # seules leurs dates calendaires réelles servent à sanctuariser les
        # cours classiques. `blocked_by_parcours` doit être calculé AVANT ce
        # filtrage (sinon plus aucune séance WS n'est présente pour indiquer
        # à quel parcours rattacher ses jours bloqués).
        blocked_by_parcours: dict[str, set[tuple[int, int]]] = (
            sae_blocked_days_by_parcours(unlocked, sae_days_by_course) if sae_days_by_course else {}
        )
        unlocked = [s for s in unlocked if not s.course_code.upper().startswith("WS")]
        if not unlocked:
            return None

        horizon = self._horizon()
        model = cp_model.CpModel()
        session_starts: dict[str, cp_model.IntVar] = {}

        for session in unlocked:
            start = model.new_int_var(0, horizon - 1, f"start_{session.id}")
            session_starts[session.id] = start

            if session.locked_day is not None and session.locked_slot is not None:
                week = int(session.metadata.get("locked_week", 0))
                fixed = (
                    week * DAYS_PER_WEEK * SLOTS_PER_DAY
                    + session.locked_day * SLOTS_PER_DAY
                    + session.locked_slot
                )
                model.add(start == fixed)

        if hints:
            for session in unlocked:
                hint_t = hints.get(session.id)
                if hint_t is None or not (0 <= hint_t < horizon):
                    continue
                model.add_hint(session_starts[session.id], hint_t)

        add_duration_domain_constraints(model, unlocked, session_starts, self.config.weeks)

        # NoOverlap via intervalles alias (1 intervalle = 1 contrainte NoOverlap)
        add_student_and_teacher_no_overlap(
            model,
            unlocked,
            session_starts,
            groups,
            enforce_student_cohort=self.config.enforce_student_cohort,
        )

        if self.config.enforce_sequence:
            add_pedagogical_sequence_constraints(model, unlocked, session_starts, groups)

        if self.config.enforce_calendar:
            add_blocked_calendar_constraints(
                model, session_starts, calendar, self.config.weeks
            )

        if self.config.enforce_planning_events and planning_event_blocked:
            add_planning_event_block_constraints(
                model, unlocked, session_starts, planning_event_blocked, self.config.weeks
            )

        if self.config.enforce_thursday_pac_lock:
            add_thursday_afternoon_pac_lock(
                model, unlocked, session_starts, self.config.weeks
            )

        if self.config.enforce_s1_integration_week_lock:
            add_s1_integration_week_lock(model, unlocked, session_starts)

        if self.config.enforce_course_min_week:
            root = self.config.data_root or Path(__file__).resolve().parents[3]
            min_week_rules = load_course_min_week_rules(root / "data" / "config")
            add_course_min_week_constraints(model, unlocked, session_starts, min_week_rules, self.config.weeks)

        if self.config.enforce_duo_rare_room and duos:
            add_duo_synchronized_rare_room_constraints(model, unlocked, session_starts, duos)

        if self.config.enforce_weekly_hour_cap and groups:
            add_weekly_hour_cap_constraints(
                model,
                unlocked,
                session_starts,
                groups,
                self.config.weeks,
                fi_cap_slots=self.config.fi_weekly_cap_slots,
                fc_cap_slots=self.config.fc_weekly_cap_slots,
            )

        if self.config.enforce_sae_sanctuarization and blocked_by_parcours:
            add_sae_sanctuarization_constraints(
                model, unlocked, session_starts, blocked_by_parcours, self.config.weeks
            )

        if teacher_availability:
            add_teacher_availability_constraints(
                model,
                unlocked,
                session_starts,
                teacher_availability,
                self.config.weeks,
                calendar=calendar,
                week_offset=week_offset,
            )

        if student_presences:
            add_student_presence_constraints(
                model,
                unlocked,
                session_starts,
                student_presences,
                calendar,
                week_offset,
                self.config.weeks,
            )

        return _HardModel(
            model=model,
            session_starts=session_starts,
            unlocked=unlocked,
            calendar=calendar,
            semestre=semestre,
            groups=groups,
            horizon=horizon,
            sae_days_by_course=sae_days_by_course,
        )

    def solve(
        self,
        sessions: list[SessionToPlace],
        teacher_availability: list[TeacherAvailability] | None = None,
        calendar: AcademicCalendar | None = None,
        student_presences: list[StudentPresence] | None = None,
        semestre: str | None = None,
        groups: list[Group] | None = None,
        sae_days_by_course: dict[str, set[tuple[int, int]]] | None = None,
        hints: dict[str, int] | None = None,
        duos: list[TeacherDuo] | None = None,
    ) -> SolverResult:
        """Résolution historique : somme pondérée d'objectifs mous (un seul solve)."""
        built = self._build_hard_model(
            sessions,
            teacher_availability,
            calendar,
            student_presences,
            semestre,
            groups,
            sae_days_by_course,
            hints,
            duos,
        )
        if built is None:
            return SolverResult(status="NO_SESSIONS")

        model = built.model
        session_starts = built.session_starts
        unlocked = built.unlocked
        horizon = built.horizon
        groups = built.groups
        sae_days_by_course = built.sae_days_by_course

        objective_terms: list[cp_model.IntVar] = []

        # Ordonnancement inter-matières : jugé pédagogiquement essentiel
        # (retour utilisateur) -> dur par défaut dès qu'on a des cohortes
        # étudiantes (`ordonnancement_hard`), quitte à demander plus de temps
        # de calcul. Repli molle disponible via `ordonnancement_hard=False`
        # si une combinaison de données donnée s'avère infaisable.
        if self.config.enforce_ordonnancement:
            soft_ord = bool(groups) and self.config.enforce_student_cohort
            objective_terms.extend(
                add_ordonnancement_constraints(
                    model,
                    unlocked,
                    session_starts,
                    horizon,
                    soft=soft_ord,
                    weight=self.config.ordonnancement_weight,
                    strict_mean=self.config.ordonnancement_hard,
                )
            )

        if self.config.enforce_sae_windows and sae_days_by_course:
            objective_terms.extend(
                add_sae_window_constraints(
                    model,
                    unlocked,
                    session_starts,
                    sae_days_by_course,
                    self.config.weeks,
                )
            )

        if (
            self.config.enforce_group_sync
            and self.config.group_sync_weight > 0
            and len(unlocked) <= 400
        ):
            objective_terms.extend(
                add_group_sync_penalties(
                    model,
                    unlocked,
                    session_starts,
                    self.config.weeks,
                    self.config.group_sync_weight,
                )
            )

        if self.config.optimize_spread and self.config.spread_weight > 0:
            objective_terms.extend(
                add_semester_spread_penalties(
                    model,
                    unlocked,
                    session_starts,
                    horizon,
                    self.config.spread_weight,
                    self.config.spread_frontload_fraction,
                )
            )

        if self.config.optimize_avoid_zones and self.config.avoid_zone_weight > 0:
            objective_terms.extend(
                add_avoid_zone_penalties(
                    model,
                    unlocked,
                    session_starts,
                    self.config.avoid_zone_weight,
                )
            )

        if self.config.optimize_midday_fill and self.config.midday_fill_weight > 0:
            objective_terms.extend(
                add_midday_fill_penalties(
                    model,
                    unlocked,
                    session_starts,
                    self.config.midday_fill_weight,
                )
            )

        if self.config.optimize_eval_clustering and self.config.eval_clustering_weight > 0:
            objective_terms.extend(
                add_eval_clustering_penalties(
                    model,
                    unlocked,
                    session_starts,
                    self.config.weeks,
                    self.config.eval_clustering_weight,
                )
            )

        use_gaps = (
            self.config.optimize_gaps
            and self.config.gap_weight > 0
            and len(unlocked) <= 150
        )
        if use_gaps:
            group_sessions = self._index_by_group(unlocked)
            gap_terms = add_intra_day_gap_penalties(
                model,
                session_starts,
                group_sessions,
                self.config.weeks,
                self.config.gap_weight,
            )
            objective_terms.extend(gap_terms)

        if objective_terms:
            model.minimize(sum(objective_terms))
        else:
            model.minimize(0)

        solver = self._new_solver(self.config.time_limit_seconds)
        status = solver.solve(model)

        status_name = solver.status_name(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return SolverResult(status=status_name)

        placements = self._decode_placements(solver, unlocked, session_starts)
        obj = int(solver.objective_value) if objective_terms else 0
        return SolverResult(
            status=status_name,
            placements=placements,
            objective_value=obj,
            gap_penalty=obj,
        )

    def solve_tiered(
        self,
        sessions: list[SessionToPlace],
        teacher_availability: list[TeacherAvailability] | None = None,
        calendar: AcademicCalendar | None = None,
        student_presences: list[StudentPresence] | None = None,
        semestre: str | None = None,
        groups: list[Group] | None = None,
        sae_days_by_course: dict[str, set[tuple[int, int]]] | None = None,
        hints: dict[str, int] | None = None,
        duos: list[TeacherDuo] | None = None,
    ) -> SolverResult:
        """
        Résolution lexicographique en paliers, alternative à `solve()` (somme
        pondérée) : mêmes contraintes dures (palier 0, `_build_hard_model`),
        mais chaque priorité métier est minimisée puis VERROUILLÉE avant de
        passer à la suivante, au lieu d'être simulée par un poids réglé à la
        main. Traduit directement `objective_function.priorite_1/2` du cahier
        des charges (ordonnancement essentiel > densification S1 > confort),
        et rend le résultat diagnosticable palier par palier (`tier_values`)
        plutôt qu'un score agrégé opaque.
        """
        built = self._build_hard_model(
            sessions,
            teacher_availability,
            calendar,
            student_presences,
            semestre,
            groups,
            sae_days_by_course,
            hints,
            duos,
        )
        if built is None:
            return SolverResult(status="NO_SESSIONS")

        model = built.model
        session_starts = built.session_starts
        unlocked = built.unlocked
        horizon = built.horizon
        groups = built.groups

        total_budget = max(1.0, float(self.config.time_limit_seconds))
        f1, f2, f3 = self.config.tier_time_fractions
        budget1 = total_budget * f1
        budget2 = total_budget * f2
        budget3 = total_budget * f3

        tier_values: dict[str, int] = {}
        last_status_name = "NO_SESSIONS"
        last_solver: cp_model.CpSolver | None = None
        time_used = 0.0

        # Palier 1 : ordonnancement inter-matières (jugé pédagogiquement
        # essentiel) — minimisé puis verrouillé, plutôt qu'un poids.
        ord_penalties: list[cp_model.IntVar] = []
        if self.config.enforce_ordonnancement:
            soft_ord = bool(groups) and self.config.enforce_student_cohort
            ord_penalties = add_ordonnancement_constraints(
                model,
                unlocked,
                session_starts,
                horizon,
                soft=soft_ord,
                weight=self.config.ordonnancement_weight,
                strict_mean=False,
            )
        if ord_penalties:
            model.minimize(sum(ord_penalties))
            solver = self._new_solver(budget1)
            status = solver.solve(model)
            time_used += solver.wall_time
            status_name = solver.status_name(status)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return SolverResult(status=status_name, tier_values=tier_values)
            last_status_name, last_solver = status_name, solver
            v1 = int(solver.objective_value)
            tier_values["ordonnancement"] = v1
            model.add(sum(ord_penalties) <= v1)
            self._rehint_from_solution(model, unlocked, session_starts, solver)

        # Palier 2 : densification S1/S3/S5 (front-load) — verrouillé à son tour.
        spread_terms: list[cp_model.IntVar] = []
        if self.config.optimize_spread and self.config.spread_weight > 0:
            spread_terms = add_semester_spread_penalties(
                model,
                unlocked,
                session_starts,
                horizon,
                self.config.spread_weight,
                self.config.spread_frontload_fraction,
            )
        if spread_terms:
            model.minimize(sum(spread_terms))
            solver = self._new_solver(budget2)
            status = solver.solve(model)
            time_used += solver.wall_time
            status_name = solver.status_name(status)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return SolverResult(status=status_name, tier_values=tier_values)
            last_status_name, last_solver = status_name, solver
            v2 = int(solver.objective_value)
            tier_values["frontload"] = v2
            model.add(sum(spread_terms) <= v2)
            self._rehint_from_solution(model, unlocked, session_starts, solver)

        # Palier 3 : confort (déjà non contentieux entre eux) — petite somme
        # pondérée résiduelle, sur le temps restant.
        comfort_terms: list[cp_model.IntVar] = []
        if (
            self.config.enforce_group_sync
            and self.config.group_sync_weight > 0
            and len(unlocked) <= 400
        ):
            comfort_terms.extend(
                add_group_sync_penalties(
                    model, unlocked, session_starts, self.config.weeks, self.config.group_sync_weight
                )
            )
        if self.config.enforce_sae_windows and built.sae_days_by_course:
            comfort_terms.extend(
                add_sae_window_constraints(
                    model, unlocked, session_starts, built.sae_days_by_course, self.config.weeks
                )
            )
        if self.config.optimize_avoid_zones and self.config.avoid_zone_weight > 0:
            comfort_terms.extend(
                add_avoid_zone_penalties(model, unlocked, session_starts, self.config.avoid_zone_weight)
            )
        if self.config.optimize_midday_fill and self.config.midday_fill_weight > 0:
            comfort_terms.extend(
                add_midday_fill_penalties(model, unlocked, session_starts, self.config.midday_fill_weight)
            )
        if self.config.optimize_eval_clustering and self.config.eval_clustering_weight > 0:
            comfort_terms.extend(
                add_eval_clustering_penalties(
                    model, unlocked, session_starts, self.config.weeks, self.config.eval_clustering_weight
                )
            )
        use_gaps = self.config.optimize_gaps and self.config.gap_weight > 0 and len(unlocked) <= 150
        if use_gaps:
            group_sessions = self._index_by_group(unlocked)
            comfort_terms.extend(
                add_intra_day_gap_penalties(
                    model, session_starts, group_sessions, self.config.weeks, self.config.gap_weight
                )
            )

        remaining_budget = max(budget3, total_budget - time_used)
        model.minimize(sum(comfort_terms) if comfort_terms else 0)
        solver = self._new_solver(remaining_budget)
        status = solver.solve(model)
        status_name = solver.status_name(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # Repli sur la dernière solution verrouillée valable (palier précédent).
            if last_solver is not None:
                placements = self._decode_placements(last_solver, unlocked, session_starts)
                return SolverResult(
                    status=last_status_name,
                    placements=placements,
                    objective_value=tier_values.get("frontload", tier_values.get("ordonnancement")),
                    gap_penalty=0,
                    tier_values=tier_values,
                )
            return SolverResult(status=status_name, tier_values=tier_values)

        if comfort_terms:
            tier_values["comfort"] = int(solver.objective_value)

        placements = self._decode_placements(solver, unlocked, session_starts)
        return SolverResult(
            status=status_name,
            placements=placements,
            objective_value=tier_values.get("comfort", 0),
            gap_penalty=tier_values.get("comfort", 0),
            tier_values=tier_values,
        )

    def solve_decomposed(
        self,
        sessions: list[SessionToPlace],
        teacher_availability: list[TeacherAvailability] | None = None,
        calendar: AcademicCalendar | None = None,
        student_presences: list[StudentPresence] | None = None,
        semestre: str | None = None,
        groups: list[Group] | None = None,
        sae_days_by_course: dict[str, set[tuple[int, int]]] | None = None,
        hints: dict[str, int] | None = None,
        duos: list[TeacherDuo] | None = None,
        max_attempts: int = 2,
    ) -> SolverResult:
        """
        Résolution en 3 étages (ordre -> semaine -> jour/créneau), alternative
        à `solve()`/`solve_tiered()` pour les instances larges où le modèle
        joint devient peu fiable (cf. docs/DATA.md §14). Implémentation dans
        `solver/decomposed.py` — délègue ici pour rester au même point
        d'entrée que les deux autres modes.

        `max_attempts` (défaut 2, donc 1 seul ré-essai) : filet de sécurité de
        dernier recours seulement — `solve_decomposed` gère maintenant lui-même
        la variance CP-SAT en interne (seeds alternatives sur les semaines en
        échec après rééquilibrage, cf. sa docstring), bien moins coûteux qu'un
        restart complet du pipeline (étage 2 + toutes les semaines) depuis ici.
        Ce ré-essai externe ne devrait donc quasiment plus jamais servir sur
        une instance de taille raisonnable ; gardé au cas où une instance
        vraiment défavorable épuise aussi les filets internes.
        """
        from cal_iut.solver.decomposed import solve_decomposed as _solve_decomposed

        resolved_calendar = calendar or build_default_calendar_2026_2027()
        resolved_semestre = semestre or (sessions[0].semestre if sessions else "S1")
        if self.config.weeks is None:
            self.config.weeks = default_horizon_weeks(resolved_calendar, resolved_semestre)

        if sae_days_by_course is None and (
            self.config.enforce_sae_windows or self.config.enforce_sae_sanctuarization
        ):
            from pathlib import Path

            from cal_iut.ingestion.planning_loader import load_mmi_planning_for_semestres, sae_windows_as_week_days

            root = self.config.data_root or Path(__file__).resolve().parents[3]
            # cf. `load_mmi_planning_for_semestres` : un run multi-parcours (ex.
            # Groupe A) contient plusieurs semestres réels (S1+S3+S5) partageant
            # le même offset calendaire — charger uniquement l'ancre `semestre`
            # ("S1") privait BUT2/BUT3 de toute fenêtre SAE (bug réel corrigé
            # 07/08/2026, cf. docs/DATA.md §37).
            real_semestres = sorted({s.semestre for s in sessions}) or [resolved_semestre]
            planning = load_mmi_planning_for_semestres(root, real_semestres)
            resolved_offset = semester_week_offset(resolved_calendar, resolved_semestre)
            sae_days_by_course = sae_windows_as_week_days(
                planning, resolved_calendar.date_to_week_day, resolved_offset, self.config.weeks
            )

        result: SolverResult | None = None
        for attempt in range(max(1, max_attempts)):
            result = _solve_decomposed(
                sessions,
                teacher_availability=teacher_availability,
                calendar=calendar,
                student_presences=student_presences,
                semestre=semestre,
                groups=groups,
                sae_days_by_course=sae_days_by_course,
                duos=duos,
                weeks=self.config.weeks,
                num_workers=self.config.num_workers,
                random_seed=self.config.random_seed + attempt,
                hints=hints,
                fi_max_week=self.config.fi_max_week,
            )
            if not result.status.startswith("PARTIAL_WEEKS_FAILED"):
                return result
        return result

    @staticmethod
    def _rehint_from_solution(
        model: cp_model.CpModel,
        unlocked: list[SessionToPlace],
        session_starts: dict[str, cp_model.IntVar],
        solver: cp_model.CpSolver,
    ) -> None:
        """
        Ré-amorce (warm-start) le palier suivant avec la solution du palier
        précédent : sans ça, verrouiller `sum(pénalités) <= V` force chaque
        palier à redémarrer sa recherche de faisabilité de zéro sous une
        contrainte plus stricte, ce qui peut le ralentir ou le faire échouer
        dans son budget de temps alors qu'une solution est déjà connue.
        """
        model.clear_hints()
        for session in unlocked:
            model.add_hint(session_starts[session.id], solver.value(session_starts[session.id]))

    @staticmethod
    def _decode_placements(
        solver: cp_model.CpSolver,
        unlocked: list[SessionToPlace],
        session_starts: dict[str, cp_model.IntVar],
    ) -> list[PlacedSession]:
        slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
        placements: list[PlacedSession] = []
        for session in unlocked:
            t = solver.value(session_starts[session.id])
            week = t // slots_per_week
            remainder = t % slots_per_week
            day = remainder // SLOTS_PER_DAY
            slot = remainder % SLOTS_PER_DAY
            placements.append(
                PlacedSession(
                    session_id=session.id,
                    week=week,
                    day=day,
                    slot=slot,
                    course_code=session.course_code,
                    group_ids=session.group_ids,
                    teacher_codes=session.teacher_codes,
                )
            )
        return placements

    @staticmethod
    def _index_by_group(sessions: list[SessionToPlace]) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for session in sessions:
            for gid in session.group_ids:
                index.setdefault(gid, []).append(session.id)
        return index
