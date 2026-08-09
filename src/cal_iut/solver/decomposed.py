"""Solveur décomposé : ordre pédagogique -> semaine -> jour/créneau.

Alternative à `TimetableSolver.solve()`/`solve_tiered()` pour les instances
larges où le modèle joint (~1400 séances × ~570 créneaux) devient peu fiable
en pratique (cf. docs/DATA.md §14 — variance de convergence observée sur le
run complet BUT1-S1, indépendante du budget de temps alloué). Casse le
problème en 3 étages de taille décroissante au lieu d'un seul CP-SAT joint :

1. Ordre pédagogique + ordonnancement : déjà porté par les données
   (`sequence_order`, `metadata["ordonnancement"]`), pas de calcul séparé.
2. Affectation SEMAINE (`assign_weeks`) : CP-SAT réduit, domaine ~n_weeks par
   séance (~19) au lieu de ~n_weeks*30 (~570) — un ordre de grandeur plus
   petit, où vivent naturellement le plafond horaire hebdomadaire et le
   lissage/front-load.
3. Placement jour/créneau PAR SEMAINE (`solve_week_detail`) : CP-SAT à pleine
   fidélité (mêmes règles que le modèle joint — NoOverlap cohortes/profs,
   PAC, calendrier, SAE, dispos enseignants, duo salle rare), mais sur un
   sous-ensemble ~15-20x plus petit (une semaine à la fois) donc largement
   dans la zone de confort de CP-SAT.

Contrepartie assumée : les arbitrages inter-semaines (ex. déplacer une séance
d'une semaine à l'autre pour mieux combler les trous) ne sont plus possibles
une fois l'étage 2 figé — gain de fiabilité et de vitesse contre un optimum
un peu moins global. cf. §14 pour le comparatif chiffré.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.ingestion.config_loader import load_course_min_week_rules
from cal_iut.ingestion.constraints_loader import StudentPresence, allowed_week_days_for_parcours
from cal_iut.models.entities import Group, TeacherAvailability, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import (
    add_blocked_calendar_constraints,
    add_duo_synchronized_rare_room_constraints,
    add_duration_domain_constraints,
    add_pedagogical_sequence_constraints,
    add_planning_event_block_constraints,
    add_student_presence_constraints,
    add_teacher_availability_constraints,
    add_teacher_weekly_hour_cap_constraints,
    add_thursday_afternoon_pac_lock,
    duo_episode_pairs,
    sae_blocked_days_by_parcours,
)
from cal_iut.solver.objectives import (
    add_avoid_zone_penalties,
    add_edge_slot_penalties,
    add_intra_day_gap_penalties,
    add_midday_fill_penalties,
)
from cal_iut.solver.resources import add_student_and_teacher_no_overlap, build_student_cohorts

SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY


def _teacher_available_slots_by_week(
    teacher_availability: list[TeacherAvailability] | None,
    weeks: int,
    calendar: AcademicCalendar | None,
    week_offset: int,
    fi_only_teachers: set[str] | None = None,
) -> dict[tuple[str, int], int]:
    """
    Créneaux DISPONIBLES par (enseignant, semaine) — utilisé pour plafonner
    dynamiquement l'étage 2 (`assign_weeks`) sous le vrai maximum atteignable
    pour cet enseignant CETTE semaine, pas seulement le plafond générique.

    Bug réel trouvé le 06/08/2026 : `assign_weeks` n'a jamais eu connaissance
    de `teacher_availability` (seule l'étage 3, `solve_week_detail`, la
    connaît) — après correction des indispos réelles de RHU (19-22 octobre)
    et KNG (2-6 novembre, semaine entière), l'étage 2 continuait d'assigner
    leurs séances à ces semaines-là sans le savoir, rendant l'étage 3
    structurellement incapable de les placer (`PARTIAL_WEEKS_FAILED`
    reproductible sur exactement ces semaines, 2 tentatives de suite).

    Complété le 08/08/2026 (mêmes symptômes, cause jumelle côté enseignant du
    plafond physique de cohorte, cf. `_physical_slots_by_week`) : deux sources
    d'indisponibilité manquaient encore et faisaient SUR-ESTIMER la capacité —
    (a) les jours fériés / fermetures du calendrier, (b) le jeudi après-midi
    réservé aux PAC pour un enseignant qui n'intervient QU'EN formation
    initiale (`fi_only_teachers`), qui ne peut donc jamais y placer de séance.
    Exemple mesuré : JLE en semaine 8 était plafonné à 21 créneaux alors que
    son maximum réel était 18 — l'étage 2 lui en assignait 20, rendant la
    semaine PROUVÉE infaisable en 0s à l'étage 3.
    """
    result: dict[tuple[str, int], int] = {}
    if not teacher_availability:
        return result
    fi_only_teachers = fi_only_teachers or set()
    for avail in teacher_availability:
        forbidden_dates = set((avail.metadata or {}).get("forbidden_dates") or [])
        for w in range(weeks):
            blocked_slots = set(avail.forbidden_slots or [])
            if calendar is not None:
                for day in range(DAYS_PER_WEEK):
                    d = calendar.week_day_to_date(week_offset + w, day)
                    off = d is None or d in calendar.blocked_dates or d in calendar.holidays
                    if off or (d is not None and d.isoformat() in forbidden_dates):
                        blocked_slots.update((day, s) for s in range(SLOTS_PER_DAY))
            if avail.teacher_code in fi_only_teachers:
                blocked_slots.update((3, s) for s in (3, 4, 5))
            available = SLOTS_PER_WEEK - len(blocked_slots)
            result[(avail.teacher_code, w)] = max(0, available)
    return result


def _physical_slots_by_week(
    parcours: str,
    weeks: int,
    calendar: AcademicCalendar | None,
    week_offset: int,
    sae_days: set[tuple[int, int]],
    presence_days: set[tuple[int, int]] | None,
    is_fc: bool,
) -> list[int]:
    """
    Nombre de créneaux RÉELLEMENT enseignables par semaine pour ce parcours :
    jours ouvrables restants une fois retirés les jours fériés, les journées
    SAE sanctuarisées et — pour la FI seulement — le jeudi après-midi réservé
    aux PAC. Pour un parcours FC, seuls les jours de présence à l'IUT comptent.

    Sert de borne haute au plafond hebdomadaire de cohorte dans `assign_weeks`
    (cf. son usage) : sans elle, l'étage 2 pouvait remplir une semaine bien
    au-delà de ce que la semaine peut physiquement contenir, rendant l'étage 3
    prouvé infaisable sur cette semaine.
    """
    result: list[int] = []
    for w in range(weeks):
        if is_fc and presence_days is not None:
            days = {d for (wk, d) in presence_days if wk == w}
        else:
            days = set(range(DAYS_PER_WEEK))

        days -= {d for (wk, d) in sae_days if wk == w}

        if calendar is not None:
            days = {
                d
                for d in days
                if (dt := calendar.week_day_to_date(week_offset + w, d)) is not None
                and dt not in calendar.blocked_dates
                and dt not in calendar.holidays
            }

        slots = len(days) * SLOTS_PER_DAY
        # Jeudi après-midi (créneaux 3-4-5) réservé aux PAC pour la FI.
        if not is_fc and 3 in days:
            slots -= 3
        result.append(max(0, slots))
    return result


@dataclass
class WeekAssignmentResult:
    status: str
    week_by_session: dict[str, int] = field(default_factory=dict)


def assign_weeks(
    sessions: list[SessionToPlace],
    groups: list[Group],
    weeks: int,
    *,
    duos: list[TeacherDuo] | None = None,
    blocked_by_parcours: dict[str, set[tuple[int, int]]] | None = None,
    student_presences: list[StudentPresence] | None = None,
    teacher_availability: list[TeacherAvailability] | None = None,
    calendar: AcademicCalendar | None = None,
    week_offset: int = 0,
    fi_cap_slots: int = 22,
    fc_cap_slots: int = 23,
    # Confirmé par Kyllian Bresson (05/08/2026) : pas de plafond bas jugé
    # nécessaire pédagogiquement, mais 40h/semaine "devant étudiant" comme
    # garde-fou si un plafond doit exister quand même — 26 créneaux de 1h30
    # (39h, sous la barre des 40h) plutôt que les 20 (30h) précédents, qui
    # n'avaient jamais été confirmés. Remplace aussi la valeur incohérente
    # (14, 21h) que `solve_decomposed` imposait en pratique sur les runs
    # réels — source unique désormais.
    teacher_weekly_cap_slots: int = 26,
    spread_weight: int = 2,
    ordonnancement_weight: int = 400,
    eval_clustering_weight: int = 30,
    time_limit_seconds: float = 180,
    num_workers: int = 8,
    random_seed: int = 2027,
    # Horizon étendu réservé aux alternants (retour utilisateur, 06/08/2026 :
    # "que les parcours alternance" — pas un allongement global) : quand
    # fourni et < max_week, les séances des parcours FC (DEV-FC/CREACOM-FC)
    # peuvent utiliser tout l'horizon `weeks`, les autres restent bornées à
    # `fi_max_week` (compris) — jamais l'inverse, un cours FI ne doit jamais
    # glisser dans la marge ouverte pour les FC. Calibré sur le calendrier
    # RÉEL de présence IUT des alternants (`contraintes/
    # 03_calendrier_alternance_officiel.json`) : BUT3-DEV-FC/CREACOM-FC S5
    # n'ont que 8 semaines de présence dans l'horizon standard (19 semaines,
    # jusqu'au 25/01/2027) contre 10 si étendu à 24 semaines (jusqu'au
    # 08/03/2027, juste avant leur SAE601 du 30/03) — 27 créneaux/semaine
    # nécessaires (90% de la capacité) contre 21,6 (72%) étendu. Cf.
    # docs/DATA.md §33.
    fi_max_week: int | None = None,
    # Marge laissée SOUS la capacité physique réelle d'une semaine (cohorte
    # ET enseignant) — cf. `_physical_slots_by_week`. Remplir une semaine
    # jusqu'au dernier créneau disponible rend l'étage 3 prouvé infaisable
    # dès qu'il doit en plus entrelacer plusieurs cohortes et enseignants
    # sur les mêmes créneaux : constaté le 07/08/2026 sur les semaines 3 et
    # 8 (aucune ressource individuellement saturée — BUT1 22/27, JLE 20/21 —
    # mais aucune combinaison valide). 2 créneaux de marge suffisent, et le
    # volume total reste largement plaçable (vérifié : la cohorte la plus
    # tendue, BUT3-CREACOM-FC, garde +10 créneaux de marge cumulée).
    physical_margin: int = 2,
) -> WeekAssignmentResult:
    """Étage 2 : une semaine par séance (domaine ~n_weeks, pas ~n_weeks*30)."""
    model = cp_model.CpModel()
    max_week = max(0, weeks - 1)
    week_var: dict[str, cp_model.IntVar] = {
        s.id: model.new_int_var(0, max_week, f"wk_{s.id}") for s in sessions
    }
    session_index = {s.id: s for s in sessions}
    objective_terms: list[cp_model.IntVar] = []

    if fi_max_week is not None and fi_max_week < max_week:
        for s in sessions:
            if "FC" not in s.parcours:
                model.add(week_var[s.id] <= fi_max_week)

    # -- Semaine d'intégration BUT1 (S1 uniquement, semaine-index 0) --
    if max_week > 0:
        for s in sessions:
            if s.semestre == "S1":
                model.add(week_var[s.id] != 0)

    # -- Démarrage minimum par cours (cf. course_scheduling_rules.yaml, ex.
    # WR119/PPP S1 ne démarre pas dès la rentrée, retour utilisateur) --
    from pathlib import Path

    min_week_rules = load_course_min_week_rules(Path(__file__).resolve().parents[3] / "data" / "config")
    if min_week_rules:
        by_key = {(r.course_code, r.semestre): r for r in min_week_rules}
        for s in sessions:
            rule = by_key.get((s.course_code, s.semestre))
            if rule is not None and 0 < rule.min_week <= max_week:
                model.add(week_var[s.id] >= rule.min_week)

    # -- Séquence pédagogique (par groupe brut) : semaine(N) <= semaine(N+1) --
    by_group_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        if s.sequence_order is None:
            continue
        for gid in s.group_ids:
            by_group_course[(s.course_code, s.semestre, gid)].append(s)
    for group_sessions in by_group_course.values():
        ordered = sorted(group_sessions, key=lambda s: s.sequence_order or 0)
        for prev, nxt in zip(ordered, ordered[1:]):
            if (prev.sequence_order or 0) < (nxt.sequence_order or 0):
                model.add(week_var[prev.id] <= week_var[nxt.id])

    # -- Éval après le dernier contenu de chaque cohorte réelle --
    # Tentative testée et abandonnée (05/08/2026) : étendre cette barrière
    # aux CM intermédiaires (pas seulement l'éval finale), dans les deux sens
    # — cf. le même historique détaillé dans `constraints.py::
    # add_pedagogical_sequence_constraints`. Dégradait la fiabilité sur
    # BUT1-S1 réel (`PARTIAL_WEEKS_FAILED` sur 5 semaines) ; décision
    # utilisateur de revenir à la version molle ci-dessous.
    cohorts = build_student_cohorts(groups) if groups else {}
    if cohorts:
        by_course: dict[tuple[str, str], list[SessionToPlace]] = defaultdict(list)
        for s in sessions:
            if s.sequence_order is not None:
                by_course[(s.course_code, s.semestre)].append(s)
        for course_sessions in by_course.values():
            evals = [s for s in course_sessions if s.is_eval]
            non_evals = [s for s in course_sessions if not s.is_eval]
            if not evals or not non_evals:
                continue
            for cohort_ids in cohorts.values():
                cohort_non_evals = [s for s in non_evals if cohort_ids.intersection(s.group_ids)]
                if not cohort_non_evals:
                    continue
                last = max(cohort_non_evals, key=lambda s: s.sequence_order or 0)
                for e in evals:
                    if (last.sequence_order or 0) < (e.sequence_order or 0):
                        model.add(week_var[last.id] <= week_var[e.id])

    # -- Duo salle rare : même semaine pour chaque paire synchronisée --
    if duos:
        for sid1, sid2 in duo_episode_pairs(sessions, duos):
            model.add(week_var[sid1] == week_var[sid2])

    # -- Ordonnancement inter-matières (molle, moyenne par groupe brut) --
    by_course_key: dict[str, list[str]] = defaultdict(list)
    for s in sessions:
        by_course_key[f"{s.course_code}:{s.semestre}:{s.parcours}"].append(s.id)
    seen_pairs: set[tuple[str, str, str]] = set()
    ord_idx = 0
    for s in sessions:
        for raw in s.metadata.get("ordonnancement") or []:
            position = str(raw.get("position", ""))
            target_code = str(raw.get("target_course_code", ""))
            semestre = str(raw.get("semestre", s.semestre))
            if not target_code or position == "same":
                continue
            source_key = f"{s.course_code}:{semestre}:{s.parcours}"
            target_key = f"{target_code}:{semestre}:{s.parcours}"
            pair_key = (position, source_key, target_key)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            source_ids = by_course_key.get(source_key, [])
            target_ids = by_course_key.get(target_key, [])
            if not source_ids or not target_ids:
                continue
            src_by_group: dict[str, list[str]] = defaultdict(list)
            tgt_by_group: dict[str, list[str]] = defaultdict(list)
            for sid in source_ids:
                for gid in session_index[sid].group_ids:
                    src_by_group[gid].append(sid)
            for sid in target_ids:
                for gid in session_index[sid].group_ids:
                    tgt_by_group[gid].append(sid)
            for gid in sorted(set(src_by_group) & set(tgt_by_group)):
                s_ids, t_ids = src_by_group[gid], tgt_by_group[gid]
                sum_s = cp_model.LinearExpr.sum([week_var[i] for i in s_ids])
                sum_t = cp_model.LinearExpr.sum([week_var[i] for i in t_ids])
                lhs = sum_s * len(t_ids)
                rhs = sum_t * len(s_ids)
                ord_idx += 1
                ok = model.new_bool_var(f"ordwk_ok_{ord_idx}")
                if position == "before":
                    model.add(lhs <= rhs).only_enforce_if(ok)
                else:
                    model.add(lhs >= rhs).only_enforce_if(ok)
                pen = model.new_int_var(0, ordonnancement_weight, f"ordwk_pen_{ord_idx}")
                model.add(pen == 0).only_enforce_if(ok)
                model.add(pen == ordonnancement_weight).only_enforce_if(ok.Not())
                objective_terms.append(pen)

    # Jours SAE bloqués par parcours (mêmes règles que le modèle joint) :
    # précalculé UNE FOIS par l'appelant (`solve_decomposed`) sur la liste
    # WS-incluse, avant que les séances WS elles-mêmes ne soient retirées de
    # la planification — cf. `add_sae_sanctuarization_constraints` pour le
    # même choix côté modèle joint. Réutilisé ci-dessous pour (a) tendre le
    # plafond hebdo dans une semaine partiellement bloquée (b) exclure les
    # semaines entièrement bloquées.
    blocked_by_parcours = blocked_by_parcours or {}
    blocked_days_count_by_parcours_week: dict[tuple[str, int], int] = defaultdict(int)
    for parcours, days in blocked_by_parcours.items():
        by_week: dict[int, set[int]] = defaultdict(set)
        for w, d in days:
            by_week[w].add(d)
        for w, ds in by_week.items():
            blocked_days_count_by_parcours_week[(parcours, w)] = len(ds)

    # Jours de présence IUT réels des alternants (cf. `_physical_slots_by_week`) :
    # un parcours FC n'a pas 5 jours ouvrables par semaine, mais uniquement
    # ceux de son calendrier d'alternance.
    presence_days_by_parcours: dict[str, set[tuple[int, int]]] = {}
    if student_presences and calendar:
        for presence in student_presences:
            if not presence.presence_dates:
                continue
            days_set = allowed_week_days_for_parcours(presence, calendar, week_offset, weeks)
            for key in presence.parcours_keys:
                presence_days_by_parcours[key] = days_set

    # -- Plafond horaire hebdomadaire (dur, direct sur week_var) --
    if cohorts:
        group_by_id = {g.id: g for g in groups}
        for resource_key, cohort_ids in cohorts.items():
            cohort_sessions = [s for s in sessions if cohort_ids.intersection(s.group_ids)]
            if not cohort_sessions:
                continue
            parcours_sample = next(
                (group_by_id[gid].parcours for gid in cohort_ids if gid in group_by_id), ""
            )
            is_fc = "FC" in parcours_sample
            cap = fc_cap_slots if is_fc else fi_cap_slots
            safe_key = resource_key.replace(":", "_").replace("-", "_")
            # Capacité PHYSIQUE réelle de chaque semaine pour ce parcours
            # (jours ouvrables restants une fois retirés fériés, jours SAE
            # sanctuarisés et, pour la FI, le jeudi après-midi PAC).
            physical = _physical_slots_by_week(
                parcours_sample, weeks, calendar, week_offset,
                blocked_by_parcours.get(parcours_sample, set()),
                presence_days_by_parcours.get(parcours_sample),
                is_fc,
            )
            for w in range(weeks):
                # Le plafond nominal (22 FI / 23 FC) ne suffit pas seul : une
                # semaine dont 3 jours sur 5 sont sanctuarisés SAE n'offre
                # physiquement que 12 créneaux. Sans cette borne, l'étage 2
                # pouvait y affecter jusqu'à 23 séances d'une même cohorte,
                # rendant l'étage 3 PROUVÉ infaisable sur cette semaine
                # (constaté le 07/08/2026 : semaines 1/3/9/15 déclarées
                # INFEASIBLE en 0-10s, pas par manque de temps) — le
                # rééquilibrage devait alors rattraper après coup, au prix
                # d'heures de calcul.
                #
                # Une tentative antérieure de réduction (cf. docs/DATA.md §14)
                # avait rendu l'étage 2 lui-même infaisable ; elle retranchait
                # les jours bloqués du plafond NOMINAL au lieu de borner par
                # la capacité physique. `min(...)` ne peut jamais durcir
                # au-delà du réel : vérifié que le volume total tient
                # (BUT3-CREACOM-FC = 173 séances pour 192 créneaux réellement
                # disponibles, le cas le plus tendu).
                cap_w = min(cap, max(1, physical[w] - physical_margin))
                terms = []
                for s in cohort_sessions:
                    ind = model.new_bool_var(f"capwk_{safe_key}_{s.id}_w{w}")
                    model.add(week_var[s.id] == w).only_enforce_if(ind)
                    model.add(week_var[s.id] != w).only_enforce_if(ind.Not())
                    duration = max(1, s.duration_slots)
                    terms.append(ind * duration if duration != 1 else ind)
                if terms:
                    model.add(sum(terms) <= cap_w)

    # -- Plafond horaire hebdomadaire PAR ENSEIGNANT (dur) --
    # Un enseignant est aussi une ressource NoOverlap (une seule salle à la
    # fois) : sans ce plafond, l'étage 2 peut concentrer 10-15+ séances d'un
    # même enseignant sur une seule semaine (ex. KBR sur WR110, cf.
    # docs/DATA.md §14) — respecte le plafond hebdo étudiant (22-23 créneaux)
    # mais rend le sous-problème jour/créneau de cette semaine très difficile,
    # voire proche de l'infaisable, pour ce seul enseignant. Plafond fixé en
    # dessous du maximum théorique FI (27 créneaux hors jeudi PM) pour garder
    # de la marge de manœuvre à l'étage 3.
    #
    # Plafonné en plus par la disponibilité RÉELLE cette semaine-là
    # (`teacher_availability`) — bug réel trouvé le 06/08/2026 : sans ça,
    # l'étage 2 peut assigner une séance à une semaine où l'enseignant est
    # presque/totalement absent (ex. RHU 4 jours sur 5 indisponible une
    # semaine, KNG une semaine entière), rendant l'étage 3 structurellement
    # incapable de la placer (`PARTIAL_WEEKS_FAILED` reproductible sur
    # exactement ces semaines). cf. `_teacher_available_slots_by_week`.
    by_teacher: dict[str, list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        for tc in s.teacher_codes:
            by_teacher[tc].append(s)
    # Enseignants n'intervenant QU'EN formation initiale : le jeudi après-midi
    # (réservé aux PAC) leur est structurellement inaccessible. Un enseignant
    # ayant ne serait-ce qu'une séance FC garde, lui, ces créneaux.
    fi_only_teachers = {
        tc for tc, ts in by_teacher.items() if all("FC" not in s.parcours for s in ts)
    }
    availability_by_week = _teacher_available_slots_by_week(
        teacher_availability, weeks, calendar, week_offset, fi_only_teachers
    )
    # Capacité physique par défaut (fériés + jeudi PAC), pour les enseignants
    # SANS entrée de disponibilité déclarée : sans ça ils gardaient le plafond
    # nominal (26) même une semaine à 4 jours ouvrables.
    def _default_teacher_slots(teacher_code: str, w: int) -> int:
        slots = SLOTS_PER_WEEK
        thursday_open = True
        if calendar is not None:
            for day in range(DAYS_PER_WEEK):
                d = calendar.week_day_to_date(week_offset + w, day)
                if d is None or d in calendar.blocked_dates or d in calendar.holidays:
                    slots -= SLOTS_PER_DAY
                    if day == 3:
                        thursday_open = False
        if teacher_code in fi_only_teachers and thursday_open:
            slots -= 3
        return max(0, slots)

    for teacher_code, teacher_sessions in by_teacher.items():
        for w in range(weeks):
            terms = []
            for s in teacher_sessions:
                ind = model.new_bool_var(f"tcapwk_{teacher_code}_{s.id}_w{w}")
                model.add(week_var[s.id] == w).only_enforce_if(ind)
                model.add(week_var[s.id] != w).only_enforce_if(ind.Not())
                duration = max(1, s.duration_slots)
                terms.append(ind * duration if duration != 1 else ind)
            if terms:
                # Même marge que le plafond de cohorte ci-dessus : un
                # enseignant rempli EXACTEMENT à sa disponibilité physique
                # (ex. JLE 20/21 en semaine 8, 3 créneaux interdits + 1 jour
                # d'absence) ne laisse aucune liberté d'entrelacement à
                # l'étage 3, qui doit en plus respecter les cohortes.
                phys = availability_by_week.get((teacher_code, w))
                if phys is None:
                    phys = _default_teacher_slots(teacher_code, w)
                cap_this_week = min(teacher_weekly_cap_slots, max(1, phys - physical_margin))
                model.add(sum(terms) <= cap_this_week)

    # -- SAE : semaine entièrement bloquée pour un parcours -> exclue pour ses cours classiques --
    if blocked_by_parcours:
        fully_blocked_weeks: dict[str, set[int]] = defaultdict(set)
        for (parcours, w), count in blocked_days_count_by_parcours_week.items():
            if count >= DAYS_PER_WEEK:
                fully_blocked_weeks[parcours].add(w)
        for s in sessions:
            if s.course_code.upper().startswith("WS"):
                continue
            blocked = fully_blocked_weeks.get(s.parcours)
            if not blocked:
                continue
            allowed = [w for w in range(weeks) if w not in blocked]
            if allowed and len(allowed) < weeks:
                model.add_allowed_assignments([week_var[s.id]], [[w] for w in allowed])

    # -- SAE : éviter (molle, pas interdire) de charger une semaine
    # PARTIELLEMENT bloquée pour un parcours --
    # Une semaine bloquée bloquée sur 3-4 jours ne laisse qu'1-2 jours (6-12
    # créneaux) aux cours classiques de ce parcours — l'étage 2 ne le voit
    # pas nativement (son plafond hebdo reste nominal, volontairement, cf.
    # note plus haut) et peut y assigner plus de séances que l'étage 3 ne
    # pourra effectivement caser. Rendre ça dur s'est révélé sur-contraignant
    # (INFEASIBLE, cf. docs/DATA.md §14) ; une pénalité proportionnelle au
    # nombre de jours bloqués incite l'optimisation à préférer une semaine
    # plus dégagée sans jamais l'interdire.
    partial_blocked_by_parcours: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for (parcours, w), count in blocked_days_count_by_parcours_week.items():
        if 0 < count < DAYS_PER_WEEK:
            partial_blocked_by_parcours[parcours].append((w, count))
    if partial_blocked_by_parcours:
        sae_avoid_weight = 80
        for s in sessions:
            if s.course_code.upper().startswith("WS"):
                continue
            for w, count in partial_blocked_by_parcours.get(s.parcours, []):
                ind = model.new_bool_var(f"saeavoid_{s.id}_w{w}")
                model.add(week_var[s.id] == w).only_enforce_if(ind)
                model.add(week_var[s.id] != w).only_enforce_if(ind.Not())
                weight = sae_avoid_weight * count
                pen = model.new_int_var(0, weight, f"saeavoidpen_{s.id}_w{w}")
                model.add(pen == weight).only_enforce_if(ind)
                model.add(pen == 0).only_enforce_if(ind.Not())
                objective_terms.append(pen)

    # -- Présence FC : la semaine doit contenir au moins un jour de présence --
    if student_presences and calendar:
        presence_by_parcours: dict[str, StudentPresence] = {}
        for p in student_presences:
            for key in p.parcours_keys:
                presence_by_parcours[key] = p
        for s in sessions:
            if "FC" not in s.parcours:
                continue
            presence = presence_by_parcours.get(s.parcours)
            if not presence or not presence.presence_dates:
                continue
            allowed_days = allowed_week_days_for_parcours(presence, calendar, week_offset, weeks)
            allowed_weeks = sorted({w for w, _ in allowed_days})
            if allowed_weeks and len(allowed_weeks) < weeks:
                model.add_allowed_assignments([week_var[s.id]], [[w] for w in allowed_weeks])

    # -- Objectif : lissage proportionnel par cours (pas de compression artificielle) --
    if spread_weight > 0:
        buckets: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
        for s in sessions:
            for gid in s.group_ids:
                buckets[(s.course_code, s.session_type.value, gid)].append(s)
        for group in buckets.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda s: (s.sequence_order or 0, s.id))
            n = len(ordered)
            for index, s in enumerate(ordered):
                target = min(int((index + 0.5) * max_week / n), max_week) if n and max_week else 0
                diff = model.new_int_var(-max_week, max_week, f"wspr_d_{s.id}")
                model.add(diff == week_var[s.id] - target)
                abs_diff = model.new_int_var(0, max_week, f"wspr_a_{s.id}")
                model.add_abs_equality(abs_diff, diff)
                weighted = model.new_int_var(0, max(1, max_week * spread_weight), f"wspr_w_{s.id}")
                model.add(weighted == abs_diff * spread_weight)
                objective_terms.append(weighted)

    # -- Regroupement des évaluations sur une même semaine (molle) --
    if eval_clustering_weight > 0:
        eval_buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
        for s in sessions:
            if s.is_eval:
                eval_buckets[(s.semestre, s.parcours)].append(s.id)
        for ids in eval_buckets.values():
            if len(ids) < 2:
                continue
            wvars = [week_var[i] for i in ids]
            mn = model.new_int_var(0, max_week, f"evwk_min_{ids[0]}")
            mx = model.new_int_var(0, max_week, f"evwk_max_{ids[0]}")
            model.add_min_equality(mn, wvars)
            model.add_max_equality(mx, wvars)
            span = model.new_int_var(0, max_week, f"evwk_span_{ids[0]}")
            model.add(span == mx - mn)
            weighted = model.new_int_var(0, max(1, max_week * eval_clustering_weight), f"evwk_w_{ids[0]}")
            model.add(weighted == span * eval_clustering_weight)
            objective_terms.append(weighted)

    if objective_terms:
        model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = num_workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(model)
    status_name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return WeekAssignmentResult(status=status_name)

    return WeekAssignmentResult(
        status=status_name,
        week_by_session={s.id: solver.value(week_var[s.id]) for s in sessions},
    )


def _slice_calendar(calendar: AcademicCalendar, absolute_week: int, num_weeks: int = 1) -> AcademicCalendar:
    """
    Calendrier réduit à `num_weeks` semaine(s) CONSÉCUTIVE(S) à partir de
    l'index absolu `absolute_week` (0-based depuis `calendar.teaching_mondays[0]`)
    — permet de réutiliser telles quelles les fonctions de contrainte
    existantes qui attendent `calendar.teaching_mondays` (jours fériés, dispos
    enseignants par date, présence FC) sans dupliquer leur logique pour un
    sous-problème d'une ou deux semaines. `teaching_mondays` est déjà
    contigu par construction, donc une simple tranche suffit.
    """
    mondays = calendar.teaching_mondays[absolute_week : absolute_week + num_weeks]
    return replace(calendar, teaching_mondays=mondays)


def _apply_sae_sanctuarization_for_week(
    model: cp_model.CpModel,
    week_sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    blocked_days_by_parcours_week: dict[str, set[tuple[int, int]]],
) -> None:
    """
    Version « étage 3 » de `add_sae_sanctuarization_constraints`, prenant en
    entrée des jours DÉJÀ résolus par parcours (calculés une fois pour tout
    le semestre dans `solve_decomposed`, cf. commentaire là-bas) plutôt que de
    re-dériver le blocage à partir des séances SAE présentes CETTE semaine —
    la présence effective d'une séance WSxxx dans le lot hebdomadaire n'a
    aucune raison de coïncider avec ses vraies dates calendaires (l'étage 2 ne
    contraint pas sa semaine, volontairement, cf. §14 pour l'historique).

    `blocked_days_by_parcours_week` : (semaine LOCALE 0..num_weeks-1, jour) —
    pas juste `jour` (bug corrigé : un lot à plusieurs semaines jointes
    bloquait auparavant implicitement le même jour dans TOUTES ses semaines
    locales, faute de distinguer laquelle).
    """
    for s in week_sessions:
        if s.course_code.upper().startswith("WS"):
            continue
        blocked = blocked_days_by_parcours_week.get(s.parcours)
        if not blocked:
            continue
        start = session_starts[s.id]
        for local_week, day in blocked:
            base = local_week * SLOTS_PER_WEEK + day * SLOTS_PER_DAY
            for slot in range(SLOTS_PER_DAY):
                model.add(start != base + slot)


def solve_week_detail(
    week_sessions: list[SessionToPlace],
    absolute_week: int,
    *,
    teacher_availability: list[TeacherAvailability] | None,
    calendar: AcademicCalendar,
    student_presences: list[StudentPresence] | None,
    groups: list[Group],
    blocked_days_by_parcours_week: dict[str, set[tuple[int, int]]] | None,
    duos: list[TeacherDuo] | None,
    enforce_student_cohort: bool = True,
    time_limit_seconds: float = 90,
    num_workers: int = 8,
    random_seed: int = 2027,
    hints: dict[str, int] | None = None,
    planning_event_blocked_local: set[tuple[int, int, int]] | None = None,
    num_weeks: int = 1,
    fixed: dict[str, int] | None = None,
    allowed_weeks: dict[str, set[int]] | None = None,
    teacher_weekly_cap_slots: int | None = None,
) -> tuple[str, dict[str, int]]:
    """
    Étage 3 : placement jour/créneau à pleine fidélité, pour les séances d'UNE
    semaine (déjà figée par `assign_weeks`), ou de `num_weeks` semaines
    CONSÉCUTIVES jointes (régénération manuelle "cette semaine + la
    suivante", cf. plan "gestion manuelle du planning" — une séance peut
    alors changer de semaine locale, contrairement au cas normal). Mêmes
    règles que le modèle joint (`TimetableSolver._build_hard_model`),
    réutilisées telles quelles — seule la taille du sous-problème change.

    `fixed` : session_id -> créneau LOCAL (0..SLOTS_PER_WEEK*num_weeks-1) à
    figer (séances verrouillées dans la portée régénérée — incluses dans le
    modèle pour compter dans les NoOverlap, mais jamais déplacées).
    `allowed_weeks` : session_id -> semaines LOCALES (0..num_weeks-1)
    admissibles (borne l'ordre pédagogique face à des voisins hors fenêtre,
    cf. `_movable_bounds`) ; ignoré pour les séances déjà dans `fixed`.

    Retourne `(status, {session_id: index_local_0..SLOTS_PER_WEEK*num_weeks-1})`.
    """
    if not week_sessions:
        return "NO_SESSIONS", {}

    horizon = SLOTS_PER_WEEK * num_weeks
    model = cp_model.CpModel()
    session_starts = {
        s.id: model.new_int_var(0, horizon - 1, f"t_{s.id}") for s in week_sessions
    }

    fixed = fixed or {}
    for session_id, t in fixed.items():
        if session_id in session_starts and 0 <= t < horizon:
            model.add(session_starts[session_id] == t)

    if allowed_weeks:
        for session_id, weeks_ok in allowed_weeks.items():
            if session_id not in session_starts or session_id in fixed or not weeks_ok:
                continue
            allowed_times = [t for t in range(horizon) if t // SLOTS_PER_WEEK in weeks_ok]
            if allowed_times:
                model.add_allowed_assignments([session_starts[session_id]], [[t] for t in allowed_times])

    if hints:
        for s in week_sessions:
            h = hints.get(s.id)
            if h is not None and 0 <= h < horizon:
                model.add_hint(session_starts[s.id], h)

    add_duration_domain_constraints(model, week_sessions, session_starts, num_weeks)
    add_student_and_teacher_no_overlap(
        model, week_sessions, session_starts, groups, enforce_student_cohort=enforce_student_cohort
    )
    add_pedagogical_sequence_constraints(model, week_sessions, session_starts, groups)
    add_thursday_afternoon_pac_lock(model, week_sessions, session_starts, num_weeks)

    sliced_calendar = _slice_calendar(calendar, absolute_week, num_weeks)
    add_blocked_calendar_constraints(model, session_starts, sliced_calendar, num_weeks)

    if planning_event_blocked_local:
        # (semaine locale, jour, slot) attendu directement par
        # `add_planning_event_block_constraints` (grain du créneau, cf.
        # docstring — retour utilisateur : créneaux affichés mais pas bloqués).
        add_planning_event_block_constraints(
            model, week_sessions, session_starts, planning_event_blocked_local, num_weeks
        )

    if teacher_availability:
        add_teacher_availability_constraints(
            model, week_sessions, session_starts, teacher_availability, num_weeks,
            calendar=sliced_calendar, week_offset=0,
        )

    if student_presences:
        add_student_presence_constraints(
            model, week_sessions, session_starts, student_presences, sliced_calendar, 0, num_weeks
        )

    if blocked_days_by_parcours_week:
        _apply_sae_sanctuarization_for_week(model, week_sessions, session_starts, blocked_days_by_parcours_week)

    if duos:
        add_duo_synchronized_rare_room_constraints(model, week_sessions, session_starts, duos)

    if num_weeks > 1 and teacher_weekly_cap_slots:
        # Le plafond hebdo enseignant n'est garanti par l'étage 2
        # (`assign_weeks`) que tant qu'une séance ne change pas de semaine —
        # une régénération jointe sur plusieurs semaines doit le refaire
        # respecter localement (cf. `add_teacher_weekly_hour_cap_constraints`).
        add_teacher_weekly_hour_cap_constraints(
            model, week_sessions, session_starts, num_weeks, cap_slots=teacher_weekly_cap_slots
        )

    objective_terms: list[cp_model.IntVar] = []
    objective_terms += add_avoid_zone_penalties(model, week_sessions, session_starts, 15)
    objective_terms += add_midday_fill_penalties(model, week_sessions, session_starts, 8)
    # Retour utilisateur (07/08/2026) : lisser au maximum les emplois du
    # temps de 3e année — éviter les créneaux 8h/17h n'importe quel jour
    # (préférence forte), et si possible finir à 15h30 (préférence plus
    # faible, cf. `add_edge_slot_penalties`). Scopé à `annee == "BUT3"`
    # uniquement, ne change rien pour BUT1/BUT2.
    but3_sessions = [s for s in week_sessions if s.annee == "BUT3"]
    objective_terms += add_edge_slot_penalties(model, but3_sessions, session_starts, 25, 10)
    if len(week_sessions) <= 150:
        group_sessions: dict[str, list[str]] = defaultdict(list)
        for s in week_sessions:
            for gid in s.group_ids:
                group_sessions[gid].append(s.id)
        objective_terms += add_intra_day_gap_penalties(model, session_starts, group_sessions, num_weeks, 100)

    if objective_terms:
        model.minimize(sum(objective_terms))
    else:
        model.minimize(0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = num_workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(model)
    status_name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return status_name, {}

    return status_name, {s.id: solver.value(session_starts[s.id]) for s in week_sessions}


def _build_sequence_neighbors(sessions: list[SessionToPlace]) -> dict[str, tuple[list[str], list[str]]]:
    """
    session_id -> (ids devant le précéder, ids devant le suivre), au sein du
    même (cours, semestre, groupe brut) — utilisé par `_movable_bounds` pour
    le rééquilibrage post-échec sans dupliquer l'ordonnancement de l'étage 2.
    """
    by_group_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        if s.sequence_order is None:
            continue
        for gid in s.group_ids:
            by_group_course[(s.course_code, s.semestre, gid)].append(s)

    neighbors: dict[str, tuple[list[str], list[str]]] = {s.id: ([], []) for s in sessions}
    for group_sessions in by_group_course.values():
        ordered = sorted(group_sessions, key=lambda s: s.sequence_order or 0)
        for prev, nxt in zip(ordered, ordered[1:]):
            if (prev.sequence_order or 0) < (nxt.sequence_order or 0):
                neighbors[nxt.id][0].append(prev.id)
                neighbors[prev.id][1].append(nxt.id)
    return neighbors


def _movable_bounds(
    session_id: str,
    neighbors: dict[str, tuple[list[str], list[str]]],
    week_by_session: dict[str, int],
    weeks: int,
) -> tuple[int, int]:
    """[min_week, max_week] admissible pour déplacer `session_id`, compte tenu
    de l'ordre pédagogique déjà résolu par l'étage 2 (ses voisins immédiats
    restent où ils sont — seule `session_id` bouge)."""
    lo, hi = 0, weeks - 1
    preds, succs = neighbors.get(session_id, ([], []))
    for p in preds:
        lo = max(lo, week_by_session.get(p, 0))
    for n in succs:
        hi = min(hi, week_by_session.get(n, weeks - 1))
    return lo, hi


def _teacher_week_counts(sessions_by_week: dict[int, list[SessionToPlace]]) -> dict[tuple[str, int], int]:
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for w, sess_list in sessions_by_week.items():
        for s in sess_list:
            for tc in s.teacher_codes:
                counts[(tc, w)] += max(1, s.duration_slots)
    return counts


def _cohort_week_counts(
    sessions_by_week: dict[int, list[SessionToPlace]],
    cohorts: dict[str, set[str]],
) -> dict[tuple[str, int], int]:
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for w, sess_list in sessions_by_week.items():
        for s in sess_list:
            for key, cohort_ids in cohorts.items():
                if cohort_ids.intersection(s.group_ids):
                    counts[(key, w)] += max(1, s.duration_slots)
    return counts


def _rebalance_failed_weeks(
    failed_weeks: list[int],
    sessions_by_week: dict[int, list[SessionToPlace]],
    week_by_session: dict[str, int],
    session_by_id: dict[str, SessionToPlace],
    weeks: int,
    *,
    duos: list[TeacherDuo] | None,
    cohorts: dict[str, set[str]],
    group_by_id: dict[str, Group],
    teacher_weekly_cap_slots: int,
    fi_cap_slots: int,
    fc_cap_slots: int,
    blocked_by_parcours: dict[str, set[tuple[int, int]]] | None = None,
    max_moves_per_week: int = 60,
    allowed_weeks_by_parcours: dict[str, set[int]] | None = None,
    physical_by_parcours: dict[str, list[int]] | None = None,
) -> set[int]:
    """
    Déplace quelques séances des semaines en échec vers une semaine voisine
    avec de la marge (plafond enseignant/cohorte respecté, bornes d'ordre
    pédagogique respectées) — mute `sessions_by_week`/`week_by_session` en
    place. Les paires de duo bougent ensemble (même semaine obligatoire).
    Retourne l'ensemble des semaines à re-résoudre à l'étage 3 (semaines en
    échec + semaines destination, dont l'effectif a changé).

    `allowed_weeks_by_parcours` : bug réel corrigé (07/08/2026, retour
    utilisateur : "pourquoi pour les S5 FC créa et com la semaine 16 est une
    semaine de cours ?") — cette fonction ne vérifiait AUCUNE contrainte de
    présence FC avant de déplacer une séance : la contrainte dure côté étage
    2 (`assign_weeks`, section "Présence FC") exclut correctement les
    semaines où les alternants ne sont pas physiquement à l'IUT, mais le
    rééquilibrage pouvait ensuite y déplacer une séance quand même, une
    semaine "hors présence" étant justement TOUJOURS vide donc maximalement
    attractive pour `fits()` (plafonds enseignant/cohorte au plus bas).
    Confirmé sur le run réel : les 3 parcours FC (BUT2-CREACOM-FC,
    BUT3-CREACOM-FC, BUT3-DEV-FC) avaient tous des séances déplacées vers
    LA MÊME semaine 13 (7-11 déc. 2026, absente des 3 calendriers de
    présence). Cf. docs/DATA.md §35.
    """
    all_sessions = [s for sess in sessions_by_week.values() for s in sess]
    neighbors = _build_sequence_neighbors(all_sessions)

    partner_of: dict[str, str] = {}
    if duos:
        for a, b in duo_episode_pairs(all_sessions, duos):
            partner_of[a] = b
            partner_of[b] = a

    teacher_counts = _teacher_week_counts(sessions_by_week)
    cohort_counts = _cohort_week_counts(sessions_by_week, cohorts)

    fully_blocked_weeks_by_parcours: dict[str, set[int]] = defaultdict(set)
    if blocked_by_parcours:
        for parcours, days in blocked_by_parcours.items():
            by_week: dict[int, set[int]] = defaultdict(set)
            for wk, d in days:
                by_week[wk].add(d)
            for wk, ds in by_week.items():
                if len(ds) >= DAYS_PER_WEEK:
                    fully_blocked_weeks_by_parcours[parcours].add(wk)

    def cohort_cap_for(session: SessionToPlace, target_w: int) -> int:
        parcours_values = {group_by_id[gid].parcours for gid in session.group_ids if gid in group_by_id}
        cap = fc_cap_slots if any("FC" in p for p in parcours_values) else fi_cap_slots
        # Borne par la capacité PHYSIQUE de la semaine cible (fériés, jours
        # SAE, jeudi PAC) — sans ça le rééquilibrage déplaçait volontiers
        # l'excédent d'une semaine en échec vers une semaine tout aussi
        # saturée, voire pire : une semaine à 2 jours ouvrables paraissait
        # attractive puisque son compteur d'occupation était bas.
        if physical_by_parcours:
            for p in parcours_values:
                phys = physical_by_parcours.get(p)
                if phys is not None and target_w < len(phys):
                    cap = min(cap, phys[target_w])
        return cap

    def fits(session: SessionToPlace, target_w: int) -> bool:
        if target_w == 0 and session.semestre == "S1" and weeks > 1:
            return False  # semaine d'intégration BUT1 (verrou dur, cf. add_s1_integration_week_lock)
        if target_w in fully_blocked_weeks_by_parcours.get(session.parcours, ()):
            return False  # semaine entièrement sanctuarisée SAE pour ce parcours
        if allowed_weeks_by_parcours is not None and "FC" in session.parcours:
            allowed = allowed_weeks_by_parcours.get(session.parcours)
            if allowed is not None and target_w not in allowed:
                return False  # alternant absent de l'IUT cette semaine-là
        duration = max(1, session.duration_slots)
        for tc in session.teacher_codes:
            if teacher_counts.get((tc, target_w), 0) + duration > teacher_weekly_cap_slots:
                return False
        for key, cohort_ids in cohorts.items():
            if cohort_ids.intersection(session.group_ids):
                if cohort_counts.get((key, target_w), 0) + duration > cohort_cap_for(session, target_w):
                    return False
        return True

    def apply_move(session: SessionToPlace, from_w: int, to_w: int) -> None:
        sessions_by_week[from_w].remove(session)
        sessions_by_week[to_w].append(session)
        week_by_session[session.id] = to_w
        duration = max(1, session.duration_slots)
        for tc in session.teacher_codes:
            teacher_counts[(tc, from_w)] -= duration
            teacher_counts[(tc, to_w)] += duration
        for key, cohort_ids in cohorts.items():
            if cohort_ids.intersection(session.group_ids):
                cohort_counts[(key, from_w)] -= duration
                cohort_counts[(key, to_w)] += duration

    touched: set[int] = set(failed_weeks)

    for w in failed_weeks:
        candidates = sorted(
            # Les séances SAE (WSxxx) ont une semaine imposée par le calendrier
            # réel (contrainte dure ajoutée dans `assign_weeks`) — jamais
            # rééquilibrées, sous peine de casser la sanctuarisation.
            [s for s in sessions_by_week[w] if not s.course_code.upper().startswith("WS")],
            key=lambda s: -max((teacher_counts.get((tc, w), 0) for tc in s.teacher_codes), default=0),
        )
        moved = 0
        for s in candidates:
            if moved >= max_moves_per_week or s.id not in week_by_session or week_by_session[s.id] != w:
                continue
            partner_id = partner_of.get(s.id)
            group = [s] if partner_id is None else [s, session_by_id[partner_id]]

            lo, hi = _movable_bounds(s.id, neighbors, week_by_session, weeks)
            if partner_id is not None:
                plo, phi = _movable_bounds(partner_id, neighbors, week_by_session, weeks)
                lo, hi = max(lo, plo), min(hi, phi)
            if lo > hi or (lo == w and hi == w):
                continue

            target_weeks = sorted((cw for cw in range(lo, hi + 1) if cw != w), key=lambda cw: abs(cw - w))
            for target_w in target_weeks:
                if all(fits(gs, target_w) for gs in group):
                    for gs in group:
                        apply_move(gs, w, target_w)
                    touched.add(target_w)
                    moved += len(group)
                    break

    return touched


def _solve_week_with_retry(
    week_sessions: list[SessionToPlace],
    w: int,
    week_offset: int,
    *,
    teacher_availability: list[TeacherAvailability] | None,
    calendar: AcademicCalendar,
    student_presences: list[StudentPresence] | None,
    groups: list[Group],
    blocked_by_parcours: dict[str, set[tuple[int, int]]] | None,
    duos: list[TeacherDuo] | None,
    week_detail_time_limit: float,
    num_workers: int,
    random_seed: int,
    hints: dict[str, int] | None,
    planning_event_blocked: set[tuple[int, int, int]] | None = None,
) -> tuple[str, dict[str, int]]:
    # Semaine locale 0 (une seule semaine par appel ici, cf. `solve_week_detail`
    # docstring — le cas multi-semaines jointes est réservé à la régénération
    # manuelle, pas à ce chemin de résolution complète du semestre).
    blocked_days_by_parcours_week: dict[str, set[tuple[int, int]]] | None = None
    if blocked_by_parcours:
        blocked_days_by_parcours_week = {}
        for parcours, days in blocked_by_parcours.items():
            local = {(0, d) for (wk, d) in days if wk == w}
            if local:
                blocked_days_by_parcours_week[parcours] = local

    planning_event_blocked_local: set[tuple[int, int, int]] | None = None
    if planning_event_blocked:
        local_evt = {(0, d, s) for (wk, d, s) in planning_event_blocked if wk == w}
        if local_evt:
            planning_event_blocked_local = local_evt

    week_hints: dict[str, int] | None = None
    if hints:
        week_hints = {}
        for s in week_sessions:
            abs_t = hints.get(s.id)
            if abs_t is not None and abs_t // SLOTS_PER_WEEK == w:
                week_hints[s.id] = abs_t % SLOTS_PER_WEEK

    # Nouvelles tentatives en cas d'échec : la variance CP-SAT observée sur le
    # modèle joint (cf. docs/DATA.md §14) existe aussi, en plus petit, sur
    # chaque sous-problème hebdomadaire — mais c'est bien la SEED qui domine,
    # pas le budget : un budget 3x plus large sur la MÊME seed relance la même
    # recherche coincée dans la même zone de l'espace, alors qu'une seed
    # différente au budget NORMAL explore une zone différente et réussit
    # souvent directement (observé empiriquement à plusieurs reprises pendant
    # ce chantier : mêmes données, seed différente => FEASIBLE immédiat).
    # Deux tentatives à seed différente et budget normal (peu coûteuses)
    # AVANT d'escalader au budget 3x — inverse l'ordre précédent qui brûlait
    # systématiquement le budget large sur une seed qui ne bougeait pas.
    attempts = (
        (week_detail_time_limit, random_seed),
        (week_detail_time_limit, random_seed + 5000),
        (week_detail_time_limit * 3, random_seed + 9000),
    )
    status_name, local_times = "", {}
    for attempt_budget, attempt_seed in attempts:
        status_name, local_times = solve_week_detail(
            week_sessions,
            week_offset + w,
            teacher_availability=teacher_availability,
            calendar=calendar,
            student_presences=student_presences,
            groups=groups,
            blocked_days_by_parcours_week=blocked_days_by_parcours_week,
            duos=duos,
            time_limit_seconds=attempt_budget,
            num_workers=num_workers,
            random_seed=attempt_seed,
            hints=week_hints,
            planning_event_blocked_local=planning_event_blocked_local,
        )
        if status_name in ("OPTIMAL", "FEASIBLE"):
            break
    return status_name, local_times


def solve_decomposed(
    sessions: list[SessionToPlace],
    teacher_availability: list[TeacherAvailability] | None = None,
    calendar: AcademicCalendar | None = None,
    student_presences: list[StudentPresence] | None = None,
    semestre: str | None = None,
    groups: list[Group] | None = None,
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None = None,
    duos: list[TeacherDuo] | None = None,
    weeks: int | None = None,
    # cf. commentaire sur `assign_weeks` : 26 créneaux (39h), confirmé par
    # Kyllian Bresson (05/08/2026) — remplace l'ancien 14 (21h), jamais
    # confirmé et incohérent avec le 20 par défaut d'`assign_weeks`.
    teacher_weekly_cap_slots: int = 26,
    week_assignment_time_limit: float = 180,
    week_detail_time_limit: float = 90,
    num_workers: int = 8,
    random_seed: int = 2027,
    hints: dict[str, int] | None = None,
    fi_cap_slots: int = 22,
    fc_cap_slots: int = 23,
    # Remis à 0 (désactivé) après test empirique le 04/08/2026 : une marge de
    # 2 sur BUT1-S1 réel n'a pas clairement amélioré la convergence (a
    # simplement déplacé la semaine qui coince, résultats bruyants sur
    # plusieurs runs) et pourrait même durcir l'étage 2 lui-même (moins de
    # capacité par semaine à volume total inchangé = étalement plus contraint)
    # — hypothèse non isolée proprement (changée le même jour que 2 autres
    # choses). Gardé configurable (pas supprimé) pour retester isolément.
    stage2_cap_margin: int = 0,
    # cf. `assign_weeks` : horizon étendu réservé aux alternants uniquement.
    fi_max_week: int | None = None,
    # cf. `assign_weeks::physical_margin`.
    physical_margin: int = 2,
):
    """
    Orchestrateur : étage 2 (`assign_weeks`) puis étage 3 (`solve_week_detail`
    par semaine). Retourne un `SolverResult` (même contrat que
    `TimetableSolver.solve`/`solve_tiered`).

    `stage2_cap_margin` (défaut 2) : diagnostic empirique sur BUT1-S1 réel —
    une semaine où CHAQUE cohorte est assignée EXACTEMENT au plafond dur
    (22/22 FI) laisse zéro marge à l'étage 3 pour composer avec le verrou
    jeudi PAC (3 créneaux FI en moins) et le NoOverlap enseignant/cohorte ;
    ce n'est pas juste "malchance de seed" mais un vrai goulot structurel —
    observé sur une semaine à 8/8 cohortes pile à 22/22, contre 19/22 une
    semaine avec de la marge qui se résout sans difficulté. L'étage 2
    applique donc un plafond légèrement plus strict que le vrai plafond dur
    (qui reste, lui, inchangé — c'est bien lui qui est vérifié au final) :
    ne change jamais la correction, laisse juste de l'air à l'étage 3.
    """
    from cal_iut.calendar.academic import (
        build_default_calendar_2026_2027,
        default_horizon_weeks,
        semester_week_offset,
    )
    from cal_iut.solver.cpsat import PlacedSession, SolverResult

    unlocked = [s for s in sessions if not s.locked]
    if not unlocked:
        return SolverResult(status="NO_SESSIONS")

    calendar = calendar or build_default_calendar_2026_2027()
    semestre = semestre or unlocked[0].semestre
    if weeks is None:
        weeks = default_horizon_weeks(calendar, semestre)
    week_offset = semester_week_offset(calendar, semestre)
    groups = groups or []

    # Jours SAE bloqués par parcours (mêmes règles que le modèle joint,
    # `sae_blocked_days_by_parcours`) : calculé UNE FOIS ici sur la liste
    # encore WS-incluse, indépendamment de la semaine où une séance SAE
    # finirait par être placée. Les séances WS/WSA elles-mêmes sont ensuite
    # retirées de la planification — retour utilisateur : une SAE est
    # définie par les enseignants eux-mêmes, seules ses dates calendaires
    # réelles servent ici à sanctuariser les jours pour les cours classiques
    # (cf. `add_sae_sanctuarization_constraints` pour le même choix côté
    # modèle joint).
    blocked_by_parcours = sae_blocked_days_by_parcours(unlocked, sae_days_by_course) if sae_days_by_course else {}
    unlocked = [s for s in unlocked if not s.course_code.upper().startswith("WS")]
    if not unlocked:
        return SolverResult(status="NO_SESSIONS")

    # Créneaux du planning officiel avec horaire explicite à bloquer pour les
    # cours classiques (ex. "9h30 Echange IA" — retour utilisateur, cf.
    # `add_planning_event_block_constraints`). Auto-chargé comme les fenêtres
    # SAE côté modèle joint (`TimetableSolver._build_hard_model`).
    from pathlib import Path

    from cal_iut.ingestion.planning_loader import load_mmi_planning_for_semestres, planning_event_blocked_slots

    # cf. `load_mmi_planning_for_semestres` : un run multi-parcours (ex.
    # Groupe A, S1+S3+S5) contient plusieurs semestres réels partageant le
    # même offset calendaire — charger uniquement `semestre` (l'ancre du
    # groupe) privait BUT2/BUT3 de leurs propres événements (rentrées, etc.,
    # bug réel corrigé 07/08/2026, cf. docs/DATA.md §37).
    real_semestres = sorted({s.semestre for s in unlocked}) or [semestre]
    planning = load_mmi_planning_for_semestres(Path(__file__).resolve().parents[3], real_semestres)
    planning_event_blocked = planning_event_blocked_slots(
        planning, calendar.date_to_week_day_any, week_offset, weeks
    )

    stage2_fi_cap = max(1, fi_cap_slots - stage2_cap_margin)
    stage2_fc_cap = max(1, fc_cap_slots - stage2_cap_margin)
    week_result = assign_weeks(
        unlocked,
        groups,
        weeks,
        duos=duos,
        blocked_by_parcours=blocked_by_parcours,
        student_presences=student_presences,
        teacher_availability=teacher_availability,
        calendar=calendar,
        week_offset=week_offset,
        teacher_weekly_cap_slots=teacher_weekly_cap_slots,
        fi_cap_slots=stage2_fi_cap,
        fc_cap_slots=stage2_fc_cap,
        time_limit_seconds=week_assignment_time_limit,
        num_workers=num_workers,
        random_seed=random_seed,
        fi_max_week=fi_max_week,
        physical_margin=physical_margin,
    )
    if week_result.status not in ("OPTIMAL", "FEASIBLE"):
        return SolverResult(status=f"WEEK_ASSIGNMENT_{week_result.status}")

    sessions_by_week: dict[int, list[SessionToPlace]] = defaultdict(list)
    week_by_session: dict[str, int] = dict(week_result.week_by_session)
    session_by_id = {s.id: s for s in unlocked}
    for s in unlocked:
        sessions_by_week[week_by_session[s.id]].append(s)

    local_times_by_week: dict[int, dict[str, int]] = {}
    failed_weeks: list[int] = []

    def _solve_weeks(week_indices: list[int], seed_bump: int = 0) -> None:
        for w in week_indices:
            status_name, local_times = _solve_week_with_retry(
                sessions_by_week[w],
                w,
                week_offset,
                teacher_availability=teacher_availability,
                calendar=calendar,
                student_presences=student_presences,
                groups=groups,
                blocked_by_parcours=blocked_by_parcours,
                duos=duos,
                week_detail_time_limit=week_detail_time_limit,
                num_workers=num_workers,
                random_seed=random_seed + seed_bump,
                hints=hints,
                planning_event_blocked=planning_event_blocked,
            )
            if status_name == "NO_SESSIONS":
                # Le rééquilibrage a pu vider entièrement cette semaine (tout
                # déplacé ailleurs) — rien à placer n'est un succès trivial,
                # pas un échec.
                local_times_by_week.pop(w, None)
                failed_weeks[:] = [fw for fw in failed_weeks if fw != w]
            elif status_name in ("OPTIMAL", "FEASIBLE"):
                local_times_by_week[w] = local_times
                failed_weeks[:] = [fw for fw in failed_weeks if fw != w]
            elif w not in failed_weeks:
                failed_weeks.append(w)

    _solve_weeks(sorted(sessions_by_week))

    # Rééquilibrage : une semaine en échec après re-essai (budget x3) est
    # souvent due à une concentration locale (ex. un même enseignant surchargé
    # cette semaine-là, cf. docs/DATA.md §14) plutôt qu'à une vraie
    # impossibilité — déplacer quelques séances vers une semaine voisine avec
    # de la marge, puis ne re-résoudre QUE les semaines touchées (rapide,
    # quelques secondes chacune), au lieu de tout recalculer.
    if failed_weeks and groups:
        cohorts = build_student_cohorts(groups)
        group_by_id = {g.id: g for g in groups}

        # cf. docstring de `_rebalance_failed_weeks` : mêmes calendriers de
        # présence FC que la contrainte dure de l'étage 2 ci-dessus, pour
        # que le rééquilibrage ne les viole jamais après coup.
        allowed_weeks_by_parcours: dict[str, set[int]] = {}
        if student_presences and calendar:
            presence_by_parcours_rb: dict[str, StudentPresence] = {}
            for p in student_presences:
                for key in p.parcours_keys:
                    presence_by_parcours_rb[key] = p
            for parcours_key, presence in presence_by_parcours_rb.items():
                if not presence.presence_dates:
                    continue
                days = allowed_week_days_for_parcours(presence, calendar, week_offset, weeks)
                allowed_weeks_by_parcours[parcours_key] = {w for w, _ in days}

        # Capacité physique par semaine et par parcours — même calcul que
        # l'étage 2 (cf. `_physical_slots_by_week`), pour que le
        # rééquilibrage ne déplace jamais vers une semaine qui ne peut pas
        # physiquement absorber la séance.
        presence_days_rb: dict[str, set[tuple[int, int]]] = {}
        for p in student_presences or []:
            if p.presence_dates and calendar:
                d = allowed_week_days_for_parcours(p, calendar, week_offset, weeks)
                for k in p.parcours_keys:
                    presence_days_rb[k] = d
        physical_by_parcours: dict[str, list[int]] = {}
        for parcours_key in {s.parcours for s in unlocked}:
            physical_by_parcours[parcours_key] = _physical_slots_by_week(
                parcours_key, weeks, calendar, week_offset,
                blocked_by_parcours.get(parcours_key, set()),
                presence_days_rb.get(parcours_key),
                "FC" in parcours_key,
            )
        for round_idx in range(6):
            if not failed_weeks:
                break
            touched = _rebalance_failed_weeks(
                list(failed_weeks),
                sessions_by_week,
                week_by_session,
                session_by_id,
                weeks,
                duos=duos,
                cohorts=cohorts,
                group_by_id=group_by_id,
                teacher_weekly_cap_slots=teacher_weekly_cap_slots,
                fi_cap_slots=stage2_fi_cap,
                fc_cap_slots=stage2_fc_cap,
                blocked_by_parcours=blocked_by_parcours,
                allowed_weeks_by_parcours=allowed_weeks_by_parcours,
                physical_by_parcours=physical_by_parcours,
            )
            if not touched:
                break
            _solve_weeks(sorted(touched), seed_bump=(round_idx + 1) * 20_000)

    # Dernier filet, peu coûteux : le rééquilibrage épuisé (6 rounds) laisse
    # parfois 1-2 semaines en échec alors qu'une seed encore différente, sans
    # rien déplacer, suffit (même logique que `_solve_week_with_retry`, à
    # l'échelle de l'orchestrateur) — bien moins cher qu'un restart complet du
    # pipeline (étage 2 + toutes les semaines) côté appelant, cf.
    # `TimetableSolver.solve_decomposed` qui ne garde plus qu'UN filet de
    # sécurité au lieu de ré-essayer systématiquement le pipeline entier.
    for extra_round in range(3):
        if not failed_weeks:
            break
        _solve_weeks(sorted(failed_weeks), seed_bump=500_000 + extra_round * 20_000)

    placements: list[PlacedSession] = []
    for w, local_times in local_times_by_week.items():
        for s in sessions_by_week[w]:
            t_local = local_times.get(s.id)
            if t_local is None:
                continue
            day = t_local // SLOTS_PER_DAY
            slot = t_local % SLOTS_PER_DAY
            placements.append(
                PlacedSession(
                    session_id=s.id,
                    week=w,
                    day=day,
                    slot=slot,
                    course_code=s.course_code,
                    group_ids=s.group_ids,
                    teacher_codes=s.teacher_codes,
                )
            )

    if failed_weeks:
        return SolverResult(
            status=f"PARTIAL_WEEKS_FAILED:{sorted(failed_weeks)}",
            placements=placements,
        )

    return SolverResult(status="FEASIBLE", placements=placements)
