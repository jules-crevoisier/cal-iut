"""Modèle CP-SAT pour le University Course Timetabling."""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import (
    AcademicCalendar,
    build_default_calendar_2026_2027,
    default_horizon_weeks,
    semester_week_offset,
)
from cal_iut.ingestion.config_loader import (
    load_course_min_week_rules,
    load_course_teacher_orders,
    load_session_date_windows,
)
from cal_iut.ingestion.constraints_loader import (
    StudentPresence,
    augment_teacher_availability_with_sae_supervision,
)
from cal_iut.ingestion.planning_loader import (
    load_mmi_planning_for_semestres,
    planning_event_blocked_slots_by_parcours,
    sae_group_labels_by_course,
    sae_supervisor_dates_by_teacher,
    sae_windows_as_week_days,
)
from cal_iut.models.entities import Group, TeacherAvailability, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import (
    add_blocked_calendar_constraints,
    add_cohort_sequence_constraints,
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
    add_session_date_window_constraints,
    add_student_presence_constraints,
    add_teacher_availability_constraints,
    add_thursday_afternoon_pac_lock,
    add_weekly_hour_cap_constraints,
    sae_blocked_days_by_group,
    sae_blocked_days_by_parcours,
)
from cal_iut.solver.objectives import (
    add_avoid_zone_penalties,
    add_course_teacher_order_penalties,
    add_intra_day_gap_penalties,
    add_midday_fill_penalties,
    add_sae_supervisor_soft_penalties,
    add_semester_spread_penalties,
    add_teacher_monthly_clustering_penalties,
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
    #
    # `spread_weight` (ci-dessus) était déjà utilisé par le modèle joint sans
    # jamais être threadé vers `--decomposed` (`assign_weeks` gardait son
    # propre défaut interne, 2, quel que soit ce réglage). Retour utilisateur
    # (11/08/2026) : « peux-tu essayer de lisser les cours sur les autres
    # semaines ? » — diagnostic sur un run réel (BUT1+BUT2+BUT3, S1+S3+S5,
    # `--decomposed`) : deux semaines (8, 14) restaient en échec sans qu'AUCUNE
    # ressource individuelle ne soit saturée (aucun enseignant à son plafond
    # hebdo) — un vrai goulot combinatoire de regroupement, pas de capacité.
    # `spread_weight=8` au lieu de 2 a suffi à rendre tout l'horizon FEASIBLE
    # (2389/2389 séances classiques placées, 0 semaine en échec) sur ce même
    # run — cf. docs/DATA.md §49. Défaut du champ inchangé (2, calibré pour le
    # modèle joint) : `cal-iut solve --decomposed` recommande `--spread-weight
    # 8` explicitement plutôt que de changer ce défaut partagé sans nouvelle
    # validation côté joint.
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
    # Relevé 22 -> 23 GLOBALEMENT le 14/08/2026 puis REVENU à 22 le même
    # jour : mesuré sur run réel que le relevé global pousse l'étage 2 à
    # exploiter la marge PARTOUT (61 paires cohorte/semaine à la limite au
    # lieu de 14), dégradant la fiabilité du run complet au lieu de la seule
    # semaine visée (WR106). Remplacé par une dérogation CIBLÉE
    # (`weekly_cap_exceptions` dans `course_scheduling_rules.yaml`,
    # `WeeklyCapException` — parcours + semaine civile précise seulement),
    # qui ne touche pas cette valeur par défaut. Cf. docs/DATA.md §62.
    # Même valeur que le solveur décomposé — cf. `decomposed.FI_WEEKLY_CAP_SLOTS`
    # pour l'historique et l'arbitrage (23 créneaux = 34h30, au-dessus des 33h
    # de la règle ; mesuré indispensable à la faisabilité le 26/08/2026).
    # Avoir eu deux valeurs distinctes ici et là a masqué le problème dix jours.
    fi_weekly_cap_slots: int = 23
    fc_weekly_cap_slots: int = 23
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
    # Un enseignant qui encadre une SAE (lead ou co-enseignant) est très peu
    # disponible ces jours-là pour un cours classique, sur N'IMPORTE QUEL
    # AUTRE parcours — retour utilisateur du 11/08/2026. Dur par défaut (même
    # granularité — journée entière — que la sanctuarisation SAE par
    # parcours) ; `False` = molle si le dur s'avère infaisable sur un cas
    # réel (cf. `ordonnancement_hard` pour le même patron de repli).
    enforce_sae_supervisor_availability: bool = True
    sae_supervisor_weight: int = 300
    # Fenêtres de dates civiles par séance (ex. WR100BU : visite BU entre le
    # 1er et le 15 septembre) — cf. data/config/course_scheduling_rules.yaml.
    enforce_session_date_windows: bool = True
    # Regroupement mensuel des interventions d'un enseignant (ARA, JHU) : mou,
    # fortement pondéré — arbitrage utilisateur du 10/08/2026.
    optimize_teacher_clustering: bool = True
    teacher_clustering_weight: int = 120
    # Ordre souple entre enseignants d'un même module (ex. WRA505C ALO -> AFR).
    optimize_teacher_order: bool = True
    # Parallélisme CP-SAT : `None` = nombre de processeurs logiques de la
    # machine (cf. `decomposed.default_num_workers`). Remplace le `8` codé en
    # dur, qui n'exploitait que la moitié d'un CPU 16 threads.
    num_workers: int | None = None
    # Dernier recours du solveur décomposé (cf. `decomposed.solve_decomposed`) :
    # None = valeurs éprouvées (300 s x 8 graines par semaine en échec). Les
    # abaisser fait échouer un run difficile PLUS VITE, ce qui est préférable
    # quand on relance en boucle sur des graines différentes
    # (`scripts/solve_until_ok.py`) — la variance de graine domine le budget.
    last_resort_seconds: float | None = None
    last_resort_seeds: int = 8
    # Tours de la boucle de retour étage 3 -> étage 2 (coupes de Benders
    # logiques, cf. `decomposed._cuts_from_failed_weeks`). 0 = l'étage 2 décide
    # une fois pour toutes, sans jamais apprendre de ses échecs.
    benders_rounds: int = 3
    random_seed: int = 2027  # même graine à chaque palier d'un même run
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
    week_offset: int = 0
    teacher_availability: list[TeacherAvailability] = field(default_factory=list)
    sae_supervisor_dates: dict[str, set] = field(default_factory=dict)


class TimetableSolver:
    """Solveur CP-SAT : NoOverlap cohortes (alias) + progression + SAE + étalement."""

    def __init__(self, config: SolverConfig | None = None) -> None:
        self.config = config or SolverConfig()

    def _horizon(self) -> int:
        return self.config.weeks * DAYS_PER_WEEK * SLOTS_PER_DAY

    def _new_solver(self, time_limit_seconds: float) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.0, time_limit_seconds)
        from cal_iut.solver.decomposed import default_num_workers

        solver.parameters.num_search_workers = self.config.num_workers or default_num_workers()
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

        planning_event_blocked: dict[str, set[tuple[int, int, int]]] = {}
        sae_group_labels: dict[str, list[str]] = {}
        sae_supervisor_dates: dict[str, set] = {}
        if (
            sae_days_by_course is None
            and (self.config.enforce_sae_windows or self.config.enforce_sae_sanctuarization)
        ) or self.config.enforce_planning_events:
            root = self.config.data_root or Path(__file__).resolve().parents[3]
            # cf. docs/DATA.md §37 : `semestre` peut n'être que l'ancre d'un
            # groupe multi-parcours — charger tous les semestres réels présents.
            real_semestres = sorted({s.semestre for s in unlocked}) or [semestre]
            planning = load_mmi_planning_for_semestres(root, real_semestres)
            sae_group_labels = sae_group_labels_by_course(planning)
            if sae_days_by_course is None:
                sae_days_by_course = sae_windows_as_week_days(
                    planning, calendar.date_to_week_day, week_offset, self.config.weeks
                )
            if self.config.enforce_planning_events:
                planning_event_blocked = planning_event_blocked_slots_by_parcours(
                    planning, calendar.date_to_week_day_any, week_offset, self.config.weeks
                )
            # Référent SAE = très peu disponible ces jours-là pour un cours
            # classique, sur N'IMPORTE QUEL AUTRE parcours (retour utilisateur
            # 11/08/2026). Dur par défaut : on augmente `teacher_availability`
            # elle-même (mécanisme `forbidden_dates` déjà câblé et testé) plutôt
            # que d'ajouter un chemin de contrainte séparé. Repli mou disponible
            # via `enforce_sae_supervisor_availability=False`, cf.
            # `_teacher_preference_terms`.
            sae_supervisor_dates = sae_supervisor_dates_by_teacher(planning)
            if sae_supervisor_dates and self.config.enforce_sae_supervisor_availability:
                teacher_availability = augment_teacher_availability_with_sae_supervision(
                    list(teacher_availability or []), sae_supervisor_dates
                )

        # Les séances SAE (WSxxx) ne sont plus planifiées par l'algorithme
        # (retour utilisateur : définies par les enseignants eux-mêmes) —
        # seules leurs dates calendaires réelles servent à sanctuariser les
        # cours classiques. `blocked_by_parcours` doit être calculé AVANT ce
        # filtrage (sinon plus aucune séance WS n'est présente pour indiquer
        # à quel parcours rattacher ses jours bloqués).
        blocked_by_parcours: dict[str, set[tuple[int, int]]] = {}
        blocked_by_group: dict[str, set[tuple[int, int]]] = {}
        if sae_days_by_course:
            blocked_by_parcours = sae_blocked_days_by_parcours(
                unlocked, sae_days_by_course, sae_group_labels
            )
            blocked_by_group = sae_blocked_days_by_group(
                unlocked, sae_days_by_course, sae_group_labels, groups
            )
        # cf. `solve_decomposed` : mêmes règles, une SAE déclarée dans
        # `solver_scheduled_sae` (ex. WSA501D) reste à planifier.
        from cal_iut.ingestion.config_loader import load_solver_scheduled_sae
        from cal_iut.solver.decomposed import _tag_scheduled_sae

        scheduled_sae = load_solver_scheduled_sae(
            (self.config.data_root or Path(__file__).resolve().parents[3]) / "data" / "config"
        )
        unlocked = [
            _tag_scheduled_sae(s, scheduled_sae)
            for s in unlocked
            if not s.course_code.upper().startswith("WS")
            or (s.course_code.upper(), s.semestre) in scheduled_sae
        ]
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
            # Ordre pédagogique vu par l'étudiant, toutes granularités
            # confondues (CM promo ↔ TD/TP sous-groupe) — cf.
            # `constraints.py::cohort_sequence_pairs`. Le modèle joint place
            # tout le semestre d'un coup : il peut donc porter cette relation
            # en dur, contrairement au décomposé où elle est graduée à
            # l'étage 2 puis dure à l'étage 3.
            add_cohort_sequence_constraints(model, unlocked, session_starts, groups)

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

        if self.config.enforce_session_date_windows:
            root = self.config.data_root or Path(__file__).resolve().parents[3]
            add_session_date_window_constraints(
                model,
                unlocked,
                session_starts,
                load_session_date_windows(root / "data" / "config"),
                calendar,
                week_offset,
                self.config.weeks,
            )

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

        if self.config.enforce_sae_sanctuarization and (blocked_by_parcours or blocked_by_group):
            add_sae_sanctuarization_constraints(
                model,
                unlocked,
                session_starts,
                blocked_by_parcours,
                self.config.weeks,
                blocked_by_group=blocked_by_group,
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
            week_offset=week_offset,
            teacher_availability=list(teacher_availability or []),
            sae_supervisor_dates=sae_supervisor_dates,
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

        objective_terms.extend(self._teacher_preference_terms(model, built))

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
        comfort_terms.extend(self._teacher_preference_terms(model, built))
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
        max_attempts: int = 3,
    ) -> SolverResult:
        """
        Résolution en 3 étages (ordre -> semaine -> jour/créneau), alternative
        à `solve()`/`solve_tiered()` pour les instances larges où le modèle
        joint devient peu fiable (cf. docs/DATA.md §14). Implémentation dans
        `solver/decomposed.py` — délègue ici pour rester au même point
        d'entrée que les deux autres modes.

        `max_attempts` (défaut 3, retour utilisateur 12/08/2026 : « fais les
        ajustements nécessaires pour arriver à 100% ») : filet de sécurité —
        `solve_decomposed` gère lui-même la variance CP-SAT en interne (seeds
        alternatives sur les semaines en échec après rééquilibrage, cf. sa
        docstring), bien moins coûteux qu'un restart complet du pipeline
        (étage 2 + toutes les semaines) depuis ici. Mais un run réel complet a
        montré que même ce filet interne (8 seeds/semaine en dernier recours)
        ne suffit pas toujours À LUI SEUL à atteindre 100% — chaque tentative
        complète (étage 2 inclus) explore une combinatoire assez différente
        pour qu'un 3e essai indépendant ait de bonnes chances de réussir là où
        les 2 premiers ont chacun laissé 2-3 semaines en échec ; `best_result`
        (juste en dessous) garde de toute façon la meilleure des tentatives,
        jamais moins bien que l'ancien comportement à 2. Cf. docs/DATA.md §58.
        """
        from cal_iut.solver.decomposed import _split_cpu_budget, default_num_workers
        from cal_iut.solver.decomposed import solve_decomposed as _solve_decomposed

        resolved_calendar = calendar or build_default_calendar_2026_2027()
        resolved_semestre = semestre or (sessions[0].semestre if sessions else "S1")
        if self.config.weeks is None:
            self.config.weeks = default_horizon_weeks(resolved_calendar, resolved_semestre)

        if sae_days_by_course is None and (
            self.config.enforce_sae_windows or self.config.enforce_sae_sanctuarization
        ):
            from pathlib import Path

            from cal_iut.ingestion.planning_loader import (
                load_mmi_planning_for_semestres,
                sae_windows_as_week_days,
            )

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

        # `--time-limit` ne pilotait RIEN sur ce chemin : `solve_decomposed`
        # gardait ses valeurs par défaut (180 s pour l'étage 2, 90 s par
        # semaine à l'étage 3), quel que soit le budget demandé. Un
        # `--time-limit 2400` n'avait donc aucun effet observable, ce qui rendait
        # la durée d'un run impossible à piloter.
        #
        # Répartition, PLAFONNÉE aux valeurs historiques (180 s / 90 s) plutôt
        # que scalée librement avec `total_budget` : un premier essai à 600 s /
        # 300 s (11/08/2026) a produit un run PIRE que l'ancien comportement
        # fixe — PARTIAL_WEEKS_FAILED sur 3 semaines au lieu de 2, 142 séances
        # non placées de plus. Cause réelle, pas une coïncidence : l'étage 2
        # (`assign_weeks`) n'est pas juste "plus fiable avec plus de temps" —
        # un budget de recherche différent fait converger CP-SAT vers une
        # affectation semaine PAR SEMAINE différente (meilleure sur SES propres
        # objectifs, ordonnancement/frontload), sans aucune garantie que cette
        # nouvelle répartition soit plus facile à placer pour l'étage 3 en
        # aval — c'est un risque connu des approches décomposées : optimiser
        # localement un étage amont ne garantit pas la faisabilité globale en
        # aval. Les bornes hautes (180/90) sont donc conservées comme PLAFOND
        # (valeurs éprouvées empiriquement, cf. l'historique de ce fichier) ;
        # seul un `--time-limit` VOLONTAIREMENT COURT (usage : itération
        # rapide) réduit encore ce budget, jamais ne l'augmente au-delà.
        week_parallelism, _ = _split_cpu_budget(
            self.config.num_workers or default_num_workers()
        )
        total_budget = max(60.0, float(self.config.time_limit_seconds))
        stage2_budget = min(180.0, max(60.0, total_budget * 0.2))
        n_waves = max(1, math.ceil((self.config.weeks or 1) / max(1, week_parallelism)))
        stage3_budget = min(90.0, max(30.0, (total_budget - stage2_budget) / n_waves))

        # `best_result` : bug réel trouvé le 12/08/2026 en diagnostiquant un
        # run réel qui régressait de [0, 12, 14] à [12, 14, 16] en échec
        # d'une tentative à l'autre — la boucle ne gardait QUE le résultat de
        # la DERNIÈRE tentative (`result`, écrasé à chaque itération), même
        # si une tentative précédente avait moins de semaines en échec /
        # plus de séances placées. Chaque tentative reseed ÉTAGE 2 ENTIER
        # depuis zéro (`random_seed + attempt`), donc rien ne garantit que la
        # suivante soit meilleure — sur une instance difficile, revenir
        # bêtement au dernier essai pouvait rendre un run PIRE qu'un essai
        # antérieur silencieusement jeté. Cf. docs/DATA.md §58.
        result: SolverResult | None = None
        best_result: SolverResult | None = None
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
                week_assignment_time_limit=stage2_budget,
                week_detail_time_limit=stage3_budget,
                num_workers=self.config.num_workers,
                random_seed=self.config.random_seed + attempt,
                hints=hints,
                fi_max_week=self.config.fi_max_week,
                enforce_sae_supervisor_availability=self.config.enforce_sae_supervisor_availability,
                sae_supervisor_weight=self.config.sae_supervisor_weight,
                spread_weight=self.config.spread_weight,
                last_resort_seconds=self.config.last_resort_seconds,
                last_resort_seeds=self.config.last_resort_seeds,
                benders_rounds=self.config.benders_rounds,
            )
            if not result.status.startswith("PARTIAL_WEEKS_FAILED"):
                return result
            if best_result is None or len(result.placements) > len(best_result.placements):
                best_result = result
        return best_result

    def _teacher_preference_terms(
        self, model: cp_model.CpModel, built: _HardModel
    ) -> list[cp_model.LinearExprT]:
        """
        Objectifs mous propres aux enseignants, communs à `solve()` et à
        `solve_tiered()` (palier confort) :

        - regroupement mensuel des interventions (ARA, JHU) ;
        - ordre souple entre enseignants d'un même module (WRA505C : ALO puis AFR).

        Tous deux sont des demandes explicites d'enseignants, arbitrées en MOU
        le 10/08/2026 : en dur elles risqueraient l'infaisabilité sur des
        modules qui occupent presque tout le semestre.
        """
        terms: list[cp_model.LinearExprT] = []
        root = self.config.data_root or Path(__file__).resolve().parents[3]

        if (
            self.config.optimize_teacher_clustering
            and self.config.teacher_clustering_weight > 0
            and built.teacher_availability
        ):
            terms.extend(
                add_teacher_monthly_clustering_penalties(
                    model,
                    built.unlocked,
                    built.session_starts,
                    built.teacher_availability,
                    built.calendar,
                    built.week_offset,
                    self.config.weeks,
                    self.config.teacher_clustering_weight,
                )
            )

        if self.config.optimize_teacher_order:
            terms.extend(
                add_course_teacher_order_penalties(
                    model,
                    built.unlocked,
                    built.session_starts,
                    load_course_teacher_orders(root / "data" / "config"),
                )
            )

        # Repli MOU de `enforce_sae_supervisor_availability=False` : la
        # version dure (par défaut) est déjà posée en amont dans
        # `_build_hard_model` en augmentant `teacher_availability` — ce terme
        # ne s'active que si l'utilisateur a explicitement demandé le mode
        # mou (ex. la version dure s'est avérée infaisable sur un cas réel).
        if not self.config.enforce_sae_supervisor_availability and built.sae_supervisor_dates:
            terms.extend(
                add_sae_supervisor_soft_penalties(
                    model,
                    built.unlocked,
                    built.session_starts,
                    built.sae_supervisor_dates,
                    built.calendar,
                    built.week_offset,
                    self.config.weeks,
                    self.config.sae_supervisor_weight,
                )
            )

        return terms

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
