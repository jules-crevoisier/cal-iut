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

import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.ingestion.config_loader import load_course_min_week_rules, load_weekly_cap_exceptions
from cal_iut.ingestion.constraints_loader import (
    StudentPresence,
    allowed_week_days_for_parcours,
    augment_teacher_availability_with_sae_supervision,
)
from cal_iut.ingestion.planning_loader import (
    fc_rentree_first_week_by_parcours,
    load_mmi_planning_for_semestres,
    planning_event_blocked_slots_by_parcours,
    sae_group_labels_by_course,
    sae_supervisor_dates_by_teacher,
)
from cal_iut.models.entities import Group, TeacherAvailability, TeacherDuo, WeeklyCapException
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
    sae_blocked_days_by_group,
    sae_blocked_days_by_parcours,
)
from cal_iut.solver.objectives import (
    add_avoid_zone_penalties,
    add_edge_slot_penalties,
    add_intra_day_gap_penalties,
    add_midday_fill_penalties,
    add_sae_supervisor_soft_penalties,
)
from cal_iut.solver.resources import add_student_and_teacher_no_overlap, build_student_cohorts

SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY


def default_num_workers() -> int:
    """
    Parallélisme CP-SAT par défaut = nombre de processeurs logiques de la
    machine, au lieu du `8` codé en dur historiquement.

    Sur la machine de production actuelle (Ryzen 7 7800X3D, 8 cœurs / 16
    threads), ce `8` n'exploitait que la moitié du CPU disponible. CP-SAT
    n'utilise pas ses workers pour découper le problème mais pour faire tourner
    un PORTEFEUILLE de stratégies de recherche différentes en parallèle : en
    doubler le nombre double les chances qu'une stratégie chanceuse trouve
    rapidement une solution, sans changer le modèle ni le résultat attendu.

    Borné à 32 : au-delà, le portefeuille de stratégies distinctes de CP-SAT
    est épuisé et les workers supplémentaires se contentent de dupliquer.
    """
    return max(1, min(32, os.cpu_count() or 8))


def _split_cpu_budget(num_workers: int, n_weeks: int = 1_000_000) -> tuple[int, int]:
    """
    Répartit `num_workers` entre le nombre de SEMAINES résolues en parallèle et
    le nombre de workers CP-SAT accordés à chacune (cf. `solve_decomposed`).

    Chaque modèle hebdomadaire est petit (quelques centaines de séances) : le
    rendement de `num_search_workers` y sature vite, alors que les semaines
    sont, elles, parfaitement indépendantes. On privilégie donc la largeur —
    4 workers par semaine, ce qui laisse à CP-SAT de quoi faire tourner
    plusieurs stratégies, et autant de semaines simultanées que le budget le
    permet. En dessous de 8 workers on ne parallélise pas les semaines : il n'y
    aurait plus assez de workers pour que chaque solve reste efficace.

    `n_weeks` (nombre RÉEL de semaines à résoudre dans cet appel précis, pas
    l'horizon total) évite un piège réel : calculer la répartition UNE FOIS sur
    l'horizon complet (ex. 24 semaines -> 4 en parallèle × 4 workers) et la
    réutiliser telle quelle pour les passes de rééquilibrage/retry — qui ne
    portent souvent que sur 1 ou 2 semaines en échec — revient à laisser 12
    threads sur 16 inactifs pendant que la semaine qui coince tourne à 4
    workers seulement. Bug réel observé le 10/08/2026 : un run complet a fini
    en `PARTIAL_WEEKS_FAILED:[12, 14]` alors qu'une résolution DE CES DEUX
    SEMAINES SEULES, à pleine puissance, aurait eu de bien meilleures chances
    (`assign_weeks`/l'étage 3 ont chacun leurs propres filets de secours, mais
    aucun n'avait jamais son plein budget CPU sur un retry ciblé). Concentrer
    tout le budget sur les quelques semaines réellement en jeu, plutôt que de
    répéter la répartition « horizon complet », corrige ce gâchis.
    """
    if num_workers < 8:
        return 1, max(1, num_workers)
    workers_per_week = 4
    parallelism = max(1, num_workers // workers_per_week)
    if n_weeks < parallelism:
        # Moins de semaines à traiter que de créneaux de parallélisme : redonne
        # tout le budget CPU disponible à ces quelques semaines plutôt que de
        # laisser des threads inactifs.
        parallelism = max(1, n_weeks)
        workers_per_week = max(1, num_workers // parallelism)
    return parallelism, workers_per_week


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

    Complété le 10/08/2026, même cause jumelle, avec les LISTES BLANCHES
    (`allowed_slots` / `allowed_dates`, cf. `TeacherAvailability`) : sans elles
    l'étage 2 créditait VBU de 30 créneaux/semaine alors qu'il n'est là que
    lundi/mardi/mercredi (18), et MNI de 30 sur TOUTE l'année alors qu'il ne
    vient que 10 jours. Une liste blanche ne s'ajoute pas aux
    `forbidden_slots` : elle les remplace comme borne haute, d'où le calcul par
    intersection ci-dessous plutôt qu'un simple cumul de créneaux bloqués.

    Les règles de parité (`week_parity_rules`) sont volontairement ignorées
    ici : elles retirent au plus un créneau par jour une semaine sur deux, donc
    sous-estimer leur effet ne peut pas rendre une semaine infaisable à
    l'étage 3 de façon structurelle — contrairement à une liste blanche, qui
    peut fermer des journées entières.
    """
    result: dict[tuple[str, int], int] = {}
    if not teacher_availability:
        return result
    fi_only_teachers = fi_only_teachers or set()
    all_slots = {(day, s) for day in range(DAYS_PER_WEEK) for s in range(SLOTS_PER_DAY)}

    for avail in teacher_availability:
        forbidden_dates = set((avail.metadata or {}).get("forbidden_dates") or [])
        allowed_slots = {tuple(pair) for pair in (avail.allowed_slots or [])}
        allowed_dates = set(avail.allowed_dates or [])

        for w in range(weeks):
            open_slots = set(allowed_slots) if allowed_slots else set(all_slots)
            open_slots -= set(avail.forbidden_slots or [])
            if avail.teacher_code in fi_only_teachers:
                open_slots -= {(3, s) for s in (3, 4, 5)}

            if calendar is not None:
                for day in range(DAYS_PER_WEEK):
                    d = calendar.week_day_to_date(week_offset + w, day)
                    closed = d is None or d in calendar.blocked_dates or d in calendar.holidays
                    if not closed and d is not None:
                        iso = d.isoformat()
                        closed = iso in forbidden_dates or (
                            bool(allowed_dates) and iso not in allowed_dates
                        )
                    if closed:
                        open_slots -= {(day, s) for s in range(SLOTS_PER_DAY)}
            elif allowed_dates:
                # Sans calendrier on ne peut pas dater les semaines : une liste
                # blanche de DATES est alors inexploitable ici. On ne devine
                # pas — l'étage 3, lui, l'appliquera de toute façon.
                pass

            result[(avail.teacher_code, w)] = len(open_slots)
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


def weekly_cap_exceptions_by_parcours_week(
    exceptions: list[WeeklyCapException],
    calendar: AcademicCalendar,
    week_offset: int,
) -> dict[tuple[str, int], int]:
    """
    Résout les dérogations `WeeklyCapException` (semaine civile réelle,
    `week_monday`) en bornes (parcours, semaine-index SOLVEUR) -> plafond,
    consommées par `assign_weeks`/`_rebalance_failed_weeks::cap_exceptions`.
    Cf. `WeeklyCapException` pour le contexte complet et docs/DATA.md §62.
    """
    resolved: dict[tuple[str, int], int] = {}
    for exc in exceptions:
        try:
            monday = date.fromisoformat(exc.week_monday)
        except ValueError:
            continue
        # `_any` : une dérogation reste valide même si son lundi précis
        # tombe un jour férié isolé — seule la semaine compte ici, pas le
        # jour exact (contrairement au blocage SAE au grain du jour).
        mapped = calendar.date_to_week_day_any(monday)
        if mapped is None:
            continue
        abs_week, _ = mapped
        rel = abs_week - week_offset
        if rel < 0:
            continue
        resolved[(exc.parcours, rel)] = exc.cap
    return resolved


def assign_weeks(
    sessions: list[SessionToPlace],
    groups: list[Group],
    weeks: int,
    *,
    duos: list[TeacherDuo] | None = None,
    blocked_by_parcours: dict[str, set[tuple[int, int]]] | None = None,
    # SAE propre à UN groupe seulement (ex. WS502D, groupe TD AB) — cf. la
    # section "SAE (granularité GROUPE)" plus bas pour le bug que ce
    # paramètre corrige.
    blocked_by_group: dict[str, set[tuple[int, int]]] | None = None,
    student_presences: list[StudentPresence] | None = None,
    teacher_availability: list[TeacherAvailability] | None = None,
    calendar: AcademicCalendar | None = None,
    week_offset: int = 0,
    # Relevé 22 -> 23 GLOBALEMENT le 14/08/2026 puis REVENU à 22 le même
    # jour, infirmé par les faits (run réel : 61 paires cohorte/semaine
    # poussées à la nouvelle limite au lieu de 14, fiabilité globale
    # dégradée) — remplacé par `cap_exceptions`, une dérogation CIBLÉE
    # (parcours + semaine civile précise) ci-dessous. Cf. docs/DATA.md §62.
    fi_cap_slots: int = 22,
    fc_cap_slots: int = 23,
    # Dérogation ciblée au plafond hebdomadaire (14/08/2026) — RELÈVE le
    # plafond `fi_cap_slots`/`fc_cap_slots` UNIQUEMENT pour les (parcours,
    # semaine-index) listés ici, jamais la valeur par défaut globale (cf.
    # commentaire ci-dessus). Clé = (parcours, semaine-index solveur),
    # valeur = plafond à utiliser CETTE semaine-là pour CE parcours.
    # Alimenté depuis `course_scheduling_rules.yaml::weekly_cap_exceptions`
    # (`WeeklyCapException`), résolu par `weekly_cap_exceptions_by_parcours_week`.
    cap_exceptions: dict[tuple[str, int], int] | None = None,
    # Confirmé par Kyllian Bresson (05/08/2026) : pas de plafond bas jugé
    # nécessaire pédagogiquement, mais 40h/semaine "devant étudiant" comme
    # garde-fou si un plafond doit exister quand même — 26 créneaux de 1h30
    # (39h, sous la barre des 40h) plutôt que les 20 (30h) précédents, qui
    # n'avaient jamais été confirmés. Remplace aussi la valeur incohérente
    # (14, 21h) que `solve_decomposed` imposait en pratique sur les runs
    # réels — source unique désormais.
    teacher_weekly_cap_slots: int = 26,
    spread_weight: int = 2,
    # Relevé 400 -> 2500 le 12/08/2026 puis REVENU à 400 le 13/08/2026,
    # infirmé par les faits : run réel relancé après le relevé, toujours
    # 16/89 relations d'ordonnancement non respectées — EXACTEMENT le même
    # total qu'avant, aucun effet mesurable (l'hypothèse de grandeur
    # relative face à `spread_weight` ne s'est pas vérifiée en pratique,
    # probablement parce que l'étage 2 est de toute façon limité par son
    # budget de recherche, 180s, pas par ce poids précis). En prime, ce run
    # a aussi régressé en fiabilité globale (3 semaines en échec au lieu de
    # 0) — sans certitude que ce soit CE changement plutôt que la variance
    # CP-SAT habituelle, mais sans bénéfice prouvé à contrebalancer, autant
    # revenir à la valeur d'origine. Reste une pénalité MOLLE par
    # construction, jamais une garantie (cf. docs/DATA.md §60.3,
    # `_rule_checks::ordonnancement`) — seul le mode paliers (`solve_tiered`)
    # offre un vrai minimum verrouillé, écarté pour l'instance complète
    # (fiabilité insuffisante à cette échelle, cf. §14).
    ordonnancement_weight: int = 400,
    eval_clustering_weight: int = 30,
    time_limit_seconds: float = 180,
    num_workers: int | None = None,
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
    # Semaine RELATIVE minimale par parcours FC (rentrée exacte, cf.
    # `fc_rentree_first_week_by_parcours`) — bug réel du 11/08/2026 : sans
    # cette borne, l'étage 2 peut assigner une semaine ENTIÈREMENT antérieure
    # à la rentrée d'un parcours FC (ex. BUT2-CREACOM-FC en semaine 0, alors
    # que sa rentrée n'est que le 14/09) ; l'étage 3 prouve alors
    # l'infaisabilité en 0s (les 30 créneaux de la semaine sont tous bloqués
    # par `planning_event_blocked_local` pour ce parcours). Cf. docs/DATA.md
    # §58.
    fc_min_week: dict[str, int] | None = None,
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

    # -- Semaine d'intégration, TOUS les FI (semaine-index 0) --
    # Généralisé le 11/08/2026 (retour utilisateur) de "S1 uniquement" à tous
    # les parcours FI — cf. `constraints.py::add_s1_integration_week_lock`
    # pour le raisonnement complet (même règle, dupliquée ici pour l'étage 2
    # du solveur décomposé).
    if max_week > 0:
        for s in sessions:
            if "FC" not in s.parcours:
                model.add(week_var[s.id] != 0)

    # -- Rentrée exacte des parcours FC : aucune semaine ENTIÈREMENT
    # antérieure (cf. docstring de `fc_min_week` ci-dessus et
    # `fc_rentree_first_week_by_parcours`) --
    if fc_min_week:
        for s in sessions:
            min_w = fc_min_week.get(s.parcours)
            if min_w is not None and min_w > 0:
                model.add(week_var[s.id] >= min(min_w, max_week))

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
            # Capacité PHYSIQUE réelle de chaque semaine pour cette cohorte
            # (jours ouvrables restants une fois retirés fériés, jours SAE
            # sanctuarisés — PARCOURS **et** GROUPE — et, pour la FI, le
            # jeudi après-midi PAC).
            #
            # Bug réel du 12/08/2026, trouvé en diagnostiquant un run réel
            # bloqué en `PARTIAL_WEEKS_FAILED` : jusqu'ici, seul le blocage
            # SAE au niveau PARCOURS entrait dans ce calcul — une SAE propre
            # à UN SEUL groupe (`blocked_by_group`, ex. WS502D pour le seul
            # TD-AB) pouvait laisser croire à l'étage 2 qu'une semaine
            # gardait 3 jours ouverts (18 créneaux) pour ce groupe, alors
            # qu'en réalité, combinée au blocage parcours, il ne lui en
            # restait qu'1 (6 créneaux) — 16 séances TD assignées quand même,
            # l'étage 3 prouvant l'infaisabilité en 0s. Cf. docs/DATA.md §58.
            combined_blocked_days = set(blocked_by_parcours.get(parcours_sample, set()))
            if blocked_by_group:
                for gid in cohort_ids:
                    combined_blocked_days |= blocked_by_group.get(gid, set())
            physical = _physical_slots_by_week(
                parcours_sample, weeks, calendar, week_offset,
                combined_blocked_days,
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
                #
                # Dérogation ciblée (14/08/2026, cf. commentaire sur
                # `cap_exceptions` plus haut) : RELÈVE `cap` (jamais ne
                # l'abaisse — `max()`, pas un remplacement direct, protège
                # contre une dérogation mal saisie qui durcirait la règle
                # par erreur) UNIQUEMENT pour le (parcours, semaine) exact
                # listé — jamais pour les autres semaines/parcours, jamais
                # au-delà de la capacité physique réelle (`min(...)`
                # toujours appliqué après).
                effective_cap = cap
                if cap_exceptions is not None:
                    override = cap_exceptions.get((parcours_sample, w))
                    if override is not None:
                        effective_cap = max(cap, override)
                cap_w = min(effective_cap, max(1, physical[w] - physical_margin))
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

    # -- SAE (granularité GROUPE) : semaine entièrement bloquée pour UN
    # groupe précis -> exclue pour ses cours classiques --
    #
    # Bug réel du 12/08/2026, trouvé en diagnostiquant un run réel bloqué en
    # `PARTIAL_WEEKS_FAILED` : le blocage ci-dessus ne raisonne qu'au niveau
    # PARCOURS. Une SAE propre à UN SEUL groupe (`blocked_by_group`, ex.
    # WS502D pour le seul TD-AB) peut se COMBINER avec le blocage parcours
    # pour fermer TOUS les jours d'une semaine à CE groupe précis, sans
    # qu'aucun des deux blocages pris isolément ne le fasse — ex. réel :
    # BUT3-DEV-FI bloqué jeu/ven au niveau parcours, but3-dev-fi-td-ab bloqué
    # mar/mer au niveau groupe -> lundi seul reste ouvert pour ce groupe (6
    # créneaux), pour 16 séances TD -> l'étage 3 prouve l'infaisabilité en 0s,
    # alors que l'étage 2 (qui ne voit QUE le blocage parcours, 2 jours sur
    # 5) le croit encore à moitié libre et lui assigne quand même 16 séances.
    # Cf. docs/DATA.md §58.
    if blocked_by_group:
        parcours_days_by_week: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
        for parcours, days in blocked_by_parcours.items():
            for w, d in days:
                parcours_days_by_week[parcours][w].add(d)
        group_days_by_week: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
        for gid, days in blocked_by_group.items():
            for w, d in days:
                group_days_by_week[gid][w].add(d)
        for s in sessions:
            if s.course_code.upper().startswith("WS"):
                continue
            combined_blocked_weeks: set[int] = set()
            for gid in s.group_ids:
                gdays = group_days_by_week.get(gid)
                if not gdays:
                    continue
                pdays = parcours_days_by_week.get(s.parcours, {})
                for w, ds in gdays.items():
                    if len(ds | pdays.get(w, set())) >= DAYS_PER_WEEK:
                        combined_blocked_weeks.add(w)
            if combined_blocked_weeks:
                allowed = [w for w in range(weeks) if w not in combined_blocked_weeks]
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
    solver.parameters.num_search_workers = num_workers or default_num_workers()
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
    blocked_days_by_group_week: dict[str, set[tuple[int, int]]] | None = None,
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

    `blocked_days_by_group_week` : même chose au grain du `group_id`, pour les
    SAE que le fichier officiel ne date que pour une partie de la promotion
    (ex. WS502D, groupe TD AB) — bloquer tout le parcours priverait les autres
    groupes d'une journée sans raison.
    """
    by_group = blocked_days_by_group_week or {}
    for s in week_sessions:
        if s.course_code.upper().startswith("WS"):
            continue
        blocked = set(blocked_days_by_parcours_week.get(s.parcours) or ())
        for gid in s.group_ids:
            blocked |= by_group.get(gid) or set()
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
    blocked_days_by_group_week: dict[str, set[tuple[int, int]]] | None = None,
    enforce_student_cohort: bool = True,
    time_limit_seconds: float = 90,
    num_workers: int | None = None,
    random_seed: int = 2027,
    hints: dict[str, int] | None = None,
    planning_event_blocked_local: dict[str, set[tuple[int, int, int]]] | None = None,
    num_weeks: int = 1,
    fixed: dict[str, int] | None = None,
    allowed_weeks: dict[str, set[int]] | None = None,
    teacher_weekly_cap_slots: int | None = None,
    sae_supervisor_dates: dict[str, set] | None = None,
    sae_supervisor_weight: int = 300,
    # Dernier recours (12/08/2026, cf. `_solve_week_with_retry::long_budget`)
    # : arrête CP-SAT dès la PREMIÈRE solution FAISABLE trouvée, sans
    # chercher à l'améliorer sur les objectifs mous (trous, créneaux bord,
    # remplissage midi...). Quand on lutte pour éviter un `PARTIAL_WEEKS_
    # FAILED`, une semaine placée mais un peu moins "jolie" vaut infiniment
    # mieux qu'une semaine non placée du tout — et laisser CP-SAT chercher
    # l'optimum consomme tout le budget à optimiser une semaine qu'il a
    # peut-être déjà résolue dans les toutes premières secondes. Jamais
    # utilisé en routine (fixed=False par défaut, résolution normale = la
    # meilleure semaine possible).
    stop_at_first_solution: bool = False,
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

    `sae_supervisor_dates` : repli MOU de l'indisponibilité référent SAE
    (cf. docs/DATA.md §48.2 puis §49) — pénalité, pas interdiction ; utilisé
    UNIQUEMENT quand `enforce_sae_supervisor_availability=False` côté
    `solve_decomposed` (sinon ces dates sont déjà dures via
    `teacher_availability`, ce paramètre reste alors vide).

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

    if blocked_days_by_parcours_week or blocked_days_by_group_week:
        _apply_sae_sanctuarization_for_week(
            model,
            week_sessions,
            session_starts,
            blocked_days_by_parcours_week or {},
            blocked_days_by_group_week,
        )

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
    if sae_supervisor_dates:
        objective_terms += add_sae_supervisor_soft_penalties(
            model, week_sessions, session_starts, sae_supervisor_dates,
            sliced_calendar, 0, num_weeks, sae_supervisor_weight,
        )
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
    solver.parameters.num_search_workers = num_workers or default_num_workers()
    solver.parameters.random_seed = random_seed
    if stop_at_first_solution:
        solver.parameters.stop_after_first_solution = True
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


def _eval_after_content_bounds(
    sessions: list[SessionToPlace],
    groups: list[Group],
    week_by_session: dict[str, int],
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Bornes hebdo (`eval_min_week`, `content_max_week`) protégeant, PENDANT le
    rééquilibrage, la même garantie que l'étage 2 assure déjà à la sortie
    d'`assign_weeks` : une éval (`is_eval`) ne précède jamais le dernier
    contenu de CHAQUE cohorte réelle (`build_student_cohorts`) — même règle
    que `_add_eval_after_cohort_content_constraints` (constraints.py),
    reprise ici en bornes simples (pas un modèle CP-SAT) pour `fits()`.

    Bug réel du 12/08/2026, trouvé en diagnostiquant un run réel FEASIBLE
    mais avec 10 évaluations placées avant la fin du contenu (retour
    utilisateur : « ça c'est critique ») : l'étage 2 respecte bien cette
    règle (contrainte dure `week_var[last] <= week_var[e]`), et l'étage 3 la
    respecte aussi mais SEULEMENT quand éval et dernier contenu tombent dans
    LA MÊME semaine (`_add_eval_after_cohort_content_constraints`, appelée
    par semaine dans `solve_week_detail` — ne voit jamais deux semaines à la
    fois). `_rebalance_failed_weeks` (rééquilibrage post-échec), lui, déplace
    des séances d'une semaine à l'autre SANS connaître cette relation
    cohorte↔éval du tout (seul `_movable_bounds`/`neighbors`, réservé au
    MÊME group_id brut, la contredit involontairement dès qu'une éval
    "promo" et le dernier contenu d'un TP précis — deux group_id différents
    — se retrouvent déplacés indépendamment). Les 10 violations réelles
    étaient TOUTES entre semaines différentes (éval déplacée avant le
    dernier contenu de son cohorte), jamais au sein d'une même semaine — la
    garantie étage 2 avait donc bien été respectée initialement, puis cassée
    PAR le rééquilibrage lui-même. Cf. docs/DATA.md §60.

    Calculées UNE FOIS depuis `week_by_session` juste après l'étage 2 (état
    connu correct, cf. ci-dessus) — pas recalculées à chaque round, pour
    rester bon marché ; suffisant pour empêcher le rééquilibrage de
    RÉINTRODUIRE une violation qui n'existait pas à la sortie de l'étage 2.
    """
    from cal_iut.solver.resources import build_student_cohorts

    cohorts = build_student_cohorts(groups) if groups else {}
    if not cohorts:
        return {}, {}

    by_course: dict[tuple[str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        if s.sequence_order is not None:
            by_course[(s.course_code, s.semestre)].append(s)

    eval_min_week: dict[str, int] = {}
    content_max_week: dict[str, int] = {}
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
            last_week = week_by_session.get(last.id)
            if last_week is None:
                continue
            for e in evals:
                if (last.sequence_order or 0) >= (e.sequence_order or 0):
                    continue
                eval_min_week[e.id] = max(eval_min_week.get(e.id, 0), last_week)
                eval_week = week_by_session.get(e.id)
                if eval_week is not None:
                    content_max_week[last.id] = min(content_max_week.get(last.id, eval_week), eval_week)
    return eval_min_week, content_max_week


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
    fc_min_week: dict[str, int] | None = None,
    eval_min_week: dict[str, int] | None = None,
    content_max_week: dict[str, int] | None = None,
    # Même dérogation ciblée que `assign_weeks::cap_exceptions` (14/08/2026,
    # docs/DATA.md §62) — le rééquilibrage doit voir la MÊME capacité que
    # l'étage 2, sous peine de refuser un déplacement pourtant valide vers
    # une semaine dérogatoire, ou d'en autoriser un au-delà du plafond réel.
    cap_exceptions: dict[tuple[str, int], int] | None = None,
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
        if cap_exceptions is not None:
            for p in parcours_values:
                override = cap_exceptions.get((p, target_w))
                if override is not None:
                    cap = max(cap, override)
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
        if target_w == 0 and "FC" not in session.parcours and weeks > 1:
            return False  # semaine d'intégration, tous les FI (verrou dur, cf. add_s1_integration_week_lock)
        if fc_min_week is not None and "FC" in session.parcours:
            min_w = fc_min_week.get(session.parcours)
            if min_w is not None and target_w < min_w:
                return False  # avant la rentrée exacte de ce parcours FC (cf. assign_weeks::fc_min_week)
        if target_w in fully_blocked_weeks_by_parcours.get(session.parcours, ()):
            return False  # semaine entièrement sanctuarisée SAE pour ce parcours
        if allowed_weeks_by_parcours is not None and "FC" in session.parcours:
            allowed = allowed_weeks_by_parcours.get(session.parcours)
            if allowed is not None and target_w not in allowed:
                return False  # alternant absent de l'IUT cette semaine-là
        if eval_min_week is not None:
            min_w = eval_min_week.get(session.id)
            if min_w is not None and target_w < min_w:
                return False  # éval déplacée avant le dernier contenu d'une de ses cohortes (cf. _eval_after_content_bounds)
        if content_max_week is not None:
            max_w = content_max_week.get(session.id)
            if max_w is not None and target_w > max_w:
                return False  # dernier contenu déplacé après l'éval qui doit le suivre (cf. _eval_after_content_bounds)
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
    blocked_by_group: dict[str, set[tuple[int, int]]] | None,
    duos: list[TeacherDuo] | None,
    week_detail_time_limit: float,
    num_workers: int,
    random_seed: int,
    hints: dict[str, int] | None,
    planning_event_blocked: dict[str, set[tuple[int, int, int]]] | None = None,
    sae_supervisor_dates: dict[str, set] | None = None,
    sae_supervisor_weight: int = 300,
    # Dernier recours (12/08/2026, cf. `solve_decomposed`) : REMPLACE les 3
    # tentatives normales par 2 tentatives CONTINUES à ce budget (2 seeds
    # différentes, pas 3 fractionnées) — vérifié empiriquement qu'une
    # recherche continue plus longue réussit là où 3 tentatives fractionnées
    # à budget standard échouent encore (semaine 12 réelle, 256 séances : 90s
    # x3 fractionné -> UNKNOWN, 400s continus -> FEASIBLE immédiat), ET
    # qu'une seule seed à ce budget élevé ne suffit pas toujours (constaté
    # sur un run ultérieur : semaine 14 persistante avec 1 seule seed
    # longue, résolue avec une 2e) — la variance de seed domine encore à ce
    # budget, comme au budget standard. Utilisé uniquement pour les quelques
    # semaines encore en échec après tout le reste (rééquilibrage + 3
    # tentatives standard), jamais en routine.
    long_budget: float | None = None,
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

    blocked_days_by_group_week: dict[str, set[tuple[int, int]]] | None = None
    if blocked_by_group:
        blocked_days_by_group_week = {}
        for gid, days in blocked_by_group.items():
            local = {(0, d) for (wk, d) in days if wk == w}
            if local:
                blocked_days_by_group_week[gid] = local

    planning_event_blocked_local: dict[str, set[tuple[int, int, int]]] | None = None
    if planning_event_blocked:
        local_evt = {
            parcours: {(0, d, s) for (wk, d, s) in slots if wk == w}
            for parcours, slots in planning_event_blocked.items()
        }
        local_evt = {parcours: slots for parcours, slots in local_evt.items() if slots}
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
    if long_budget is not None:
        # 8 seeds (12/08/2026, 2e itération — 4 s'est révélé encore
        # insuffisant sur un run réel malgré un diagnostic isolé
        # concluant : semaines 5/10/14 résolues à 100% EN ISOLATION en
        # 60s, aucun manque de prof/salle/temps, cf. docs/DATA.md §58).
        # Rendu abordable par `stop_at_first_solution` (ci-dessous) : une
        # tentative qui réussit s'arrête presque tout de suite, le coût
        # total de 8 tentatives reste donc proche de celui de 2-3 avant —
        # seule une tentative qui échoue consomme tout son budget (réduit
        # en contrepartie côté appelant, cf. `solve_decomposed`).
        attempts = tuple((long_budget, random_seed + 5000 * i) for i in range(8))
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
            blocked_days_by_group_week=blocked_days_by_group_week,
            duos=duos,
            time_limit_seconds=attempt_budget,
            num_workers=num_workers,
            random_seed=attempt_seed,
            hints=week_hints,
            planning_event_blocked_local=planning_event_blocked_local,
            sae_supervisor_dates=sae_supervisor_dates,
            sae_supervisor_weight=sae_supervisor_weight,
            # Dernier recours seulement : la PREMIÈRE solution faisable
            # suffit, pas la peine de brûler le budget à l'améliorer sur les
            # objectifs mous — cf. docstring de `stop_at_first_solution` sur
            # `solve_week_detail`.
            stop_at_first_solution=long_budget is not None,
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
    num_workers: int | None = None,
    random_seed: int = 2027,
    hints: dict[str, int] | None = None,
    # Relevé 22 -> 23 le 14/08/2026, cf. le même relevé sur `assign_weeks`
    # ci-dessus (autorisation Kyllian Bresson, docs/DATA.md §61.1).
    fi_cap_slots: int = 23,
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
    enforce_sae_supervisor_availability: bool = True,
    sae_supervisor_weight: int = 300,
    spread_weight: int = 2,
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

    num_workers = num_workers or default_num_workers()
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
    sae_group_labels = sae_group_labels_by_course(
        load_mmi_planning_for_semestres(
            Path(__file__).resolve().parents[3], sorted({s.semestre for s in unlocked})
        )
    )
    blocked_by_parcours = (
        sae_blocked_days_by_parcours(unlocked, sae_days_by_course, sae_group_labels)
        if sae_days_by_course
        else {}
    )
    # SAE ne concernant qu'une partie de la promotion (ex. WS502D, groupe TD
    # AB) : rattachées à leurs groupes, pas au parcours entier. L'étage 2
    # (`assign_weeks`) raisonne par parcours ; on ne descend donc ce volet
    # qu'à l'étage 3, au grain du jour, via `blocked_days_by_group_week`.
    blocked_by_group = (
        sae_blocked_days_by_group(unlocked, sae_days_by_course, sae_group_labels, groups)
        if sae_days_by_course and sae_group_labels
        else {}
    )
    unlocked = [s for s in unlocked if not s.course_code.upper().startswith("WS")]
    if not unlocked:
        return SolverResult(status="NO_SESSIONS")

    # Créneaux du planning officiel avec horaire explicite à bloquer pour les
    # cours classiques (ex. "9h30 Echange IA" — retour utilisateur, cf.
    # `add_planning_event_block_constraints`). Auto-chargé comme les fenêtres
    # SAE côté modèle joint (`TimetableSolver._build_hard_model`).
    # cf. `load_mmi_planning_for_semestres` : un run multi-parcours (ex.
    # Groupe A, S1+S3+S5) contient plusieurs semestres réels partageant le
    # même offset calendaire — charger uniquement `semestre` (l'ancre du
    # groupe) privait BUT2/BUT3 de leurs propres événements (rentrées, etc.,
    # bug réel corrigé 07/08/2026, cf. docs/DATA.md §37).
    real_semestres = sorted({s.semestre for s in unlocked}) or [semestre]
    planning = load_mmi_planning_for_semestres(Path(__file__).resolve().parents[3], real_semestres)
    planning_event_blocked = planning_event_blocked_slots_by_parcours(
        planning, calendar.date_to_week_day_any, week_offset, weeks
    )
    # Borne étage 2 (cf. docstring de `fc_min_week` sur `assign_weeks`) : sans
    # elle, l'étage 2 ignore la règle "avant rentrée exacte" ci-dessus et peut
    # assigner une semaine entièrement fermée à un parcours FC -> INFEASIBLE
    # prouvé à l'étage 3. Bug réel du 11/08/2026, cf. docs/DATA.md §58.
    fc_min_week = fc_rentree_first_week_by_parcours(
        planning, calendar.date_to_week_day_any, week_offset
    )

    # Dérogation ciblée au plafond hebdomadaire (14/08/2026, cf.
    # `WeeklyCapException`, `assign_weeks::cap_exceptions`, docs/DATA.md §62).
    cap_exceptions = weekly_cap_exceptions_by_parcours_week(
        load_weekly_cap_exceptions(Path(__file__).resolve().parents[3] / "data" / "config"),
        calendar,
        week_offset,
    )

    # Référent SAE = très peu disponible ces jours-là pour un cours classique,
    # sur N'IMPORTE QUEL AUTRE parcours (retour utilisateur 11/08/2026).
    # Version DURE (`enforce_sae_supervisor_availability=True`) : augmentée
    # ICI, avant d'être threadée dans `assign_weeks` (étage 2, capacité
    # hebdomadaire via `_teacher_available_slots_by_week`) ET
    # `solve_week_detail` (étage 3, `add_teacher_availability_constraints`) —
    # les deux lisent déjà `metadata["forbidden_dates"]`, donc les deux en
    # bénéficient automatiquement sans code supplémentaire.
    #
    # Repli MOU (`enforce_sae_supervisor_availability=False`, cf. docs/DATA.md
    # §49) : la version dure s'est avérée catastrophique sur un run complet
    # réel (BUT1+BUT2+BUT3-FI, S1+S3+S5, `--weeks 24 --fi-max-week 18`) — des
    # enseignants comme ALO (40 jours bloqués sur 10 semaines quasi
    # consécutives, plusieurs SAE différentes accumulées) ou FME (26 jours)
    # font s'effondrer l'étage 2 : la capacité hebdomadaire chute à zéro sur
    # de nombreuses semaines pour des enseignants à fort volume, et l'étage 2
    # est alors contraint de les concentrer ailleurs au point de rendre CES
    # semaines-là infaisables à leur tour — passage de 2 semaines en échec
    # (baseline sans ce mécanisme) à 13, et de ~95% à 52% de séances placées.
    # En mou : la capacité étage 2 n'est PAS réduite (les dates ne sont pas
    # injectées dans `teacher_availability`, seulement conservées à part) ;
    # l'étage 3 les traite comme une pénalité (`add_sae_supervisor_soft_penalties`),
    # donc évitées quand c'est possible, acceptées sinon plutôt que de faire
    # échouer toute la semaine.
    supervisor_dates = sae_supervisor_dates_by_teacher(planning)
    soft_supervisor_dates: dict[str, set] = {}
    if supervisor_dates:
        if enforce_sae_supervisor_availability:
            teacher_availability = augment_teacher_availability_with_sae_supervision(
                list(teacher_availability or []), supervisor_dates
            )
        else:
            soft_supervisor_dates = supervisor_dates

    stage2_fi_cap = max(1, fi_cap_slots - stage2_cap_margin)
    stage2_fc_cap = max(1, fc_cap_slots - stage2_cap_margin)
    week_result = assign_weeks(
        unlocked,
        groups,
        weeks,
        duos=duos,
        blocked_by_parcours=blocked_by_parcours,
        blocked_by_group=blocked_by_group,
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
        fc_min_week=fc_min_week,
        cap_exceptions=cap_exceptions,
        physical_margin=physical_margin,
        spread_weight=spread_weight,
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

    # Étage 3 : les semaines sont RÉSOLUES EN PARALLÈLE. Chaque appel à
    # `_solve_week_with_retry` ne lit que `sessions_by_week[w]` et des données
    # partagées en lecture seule, et son résultat ne dépend que de (w, seed) —
    # les semaines sont donc indépendantes par construction une fois l'étage 2
    # figé. CP-SAT libère le GIL pendant `solve()`, un pool de threads suffit.
    #
    # Le budget CPU est réparti entre les deux niveaux de parallélisme
    # (`_split_cpu_budget`) : lancer N semaines à W workers chacune vaut mieux
    # que 1 semaine à N*W sur ces modèles-là — le rendement de
    # `num_search_workers` sature vite sur un modèle d'une seule semaine
    # (quelques centaines de séances), alors que les semaines, elles, sont
    # parfaitement parallèles.
    #
    # Déterminisme préservé : les résultats sont collectés puis appliqués dans
    # l'ordre CROISSANT des semaines, jamais dans l'ordre d'arrivée du pool.

    def _solve_weeks(
        week_indices: list[int],
        seed_bump: int = 0,
        long_budget: float | None = None,
        sequential: bool = False,
    ) -> None:
        ordered = sorted(week_indices)
        # Recalculée à CHAQUE appel sur le nombre réel de semaines à traiter
        # ICI (pas l'horizon complet) : un retry ciblé sur 1-2 semaines en
        # échec doit leur donner tout le budget CPU, pas se limiter aux 4
        # workers qu'aurait reçus chacune dans le lot initial de 24 semaines
        # (cf. docstring de `_split_cpu_budget`).
        #
        # `sequential=True` (dernier recours, cf. appel plus bas) : force
        # CHAQUE semaine à tourner seule avec la totalité de `num_workers`,
        # au lieu de partager entre plusieurs semaines en parallèle — vérifié
        # empiriquement qu'une recherche à pleine puissance CP-SAT converge
        # là où la même recherche divisée entre plusieurs semaines échoue
        # (cf. docstring de `long_budget` sur `_solve_week_with_retry`).
        if sequential:
            week_parallelism, workers_per_week = 1, num_workers
        else:
            week_parallelism, workers_per_week = _split_cpu_budget(num_workers, len(ordered))

        def _run(w: int) -> tuple[int, str, dict[str, int]]:
            status_name, local_times = _solve_week_with_retry(
                sessions_by_week[w],
                w,
                week_offset,
                teacher_availability=teacher_availability,
                calendar=calendar,
                student_presences=student_presences,
                groups=groups,
                blocked_by_parcours=blocked_by_parcours,
                blocked_by_group=blocked_by_group,
                duos=duos,
                week_detail_time_limit=week_detail_time_limit,
                num_workers=workers_per_week,
                random_seed=random_seed + seed_bump,
                hints=hints,
                planning_event_blocked=planning_event_blocked,
                sae_supervisor_dates=soft_supervisor_dates,
                sae_supervisor_weight=sae_supervisor_weight,
                long_budget=long_budget,
            )
            return w, status_name, local_times

        if week_parallelism > 1 and len(ordered) > 1:
            with ThreadPoolExecutor(max_workers=week_parallelism) as pool:
                results = list(pool.map(_run, ordered))
        else:
            results = [_run(w) for w in ordered]

        for w, status_name, local_times in results:
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
        # Calculées ICI, sur l'état ENCORE INTACT de l'étage 2 (avant tout
        # déplacement) — cf. docstring de `_eval_after_content_bounds` : bug
        # réel du 12/08/2026, le rééquilibrage cassait silencieusement la
        # garantie "éval après le dernier contenu de chaque cohorte" que
        # l'étage 2 vient de satisfaire, faute de la connaître.
        eval_min_week, content_max_week = _eval_after_content_bounds(unlocked, groups, week_by_session)
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
                fc_min_week=fc_min_week,
                eval_min_week=eval_min_week,
                content_max_week=content_max_week,
                cap_exceptions=cap_exceptions,
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

    # Dernier recours (12/08/2026) : au-delà des rounds ci-dessus (semaines
    # encore réparties en parallèle, donc PAS pleine puissance CP-SAT
    # chacune), certaines semaines restent en échec non pas parce qu'elles
    # sont infaisables, mais parce qu'il leur faut une recherche CONTINUE
    # plus longue sur UNE SEULE seed, à pleine puissance — vérifié
    # empiriquement : semaine 12 réelle (256 séances), fractionnée en 3
    # tentatives à budget standard (dont seeds différentes) -> UNKNOWN,
    # 400s continus sur LA MÊME seed, pleine puissance -> FEASIBLE immédiat
    # (cf. docs/DATA.md §58). Résolues ICI une par une, JAMAIS en parallèle
    # (il ne reste que quelques semaines à ce stade — autant leur donner
    # tout le budget CPU plutôt que de le refractionner) avec un budget
    # nettement plus long ; s'arrête dès qu'une semaine réussit, sans
    # attendre le budget complet.
    if failed_weeks:
        # 300s par tentative (12/08/2026, 3e itération — 150s s'est révélé
        # trop juste sur un run réel malgré `stop_at_first_solution` : les
        # semaines qui arrivent jusqu'ici ont déjà traversé 9 rounds de
        # rééquilibrage/retry, leur composition résiduelle n'est plus celle,
        # plus simple, d'un étage 2 fraîchement calculé — cf. docs/DATA.md
        # §58). `stop_at_first_solution` reste actif : une tentative qui
        # RÉUSSIT s'arrête toujours presque immédiatement quel que soit ce
        # plafond, qui ne coûte donc cher que sur les tentatives qui échouent
        # réellement.
        last_resort_budget = max(week_detail_time_limit * 3, 300.0)
        for w in sorted(failed_weeks):
            _solve_weeks([w], seed_bump=900_000, long_budget=last_resort_budget, sequential=True)

    # Dernier filet ULTIME (13/08/2026, retour utilisateur — compromis
    # explicite demandé entre "garantie stricte éval-après-contenu" et
    # "atteindre 100% des séances placées", cf. docs/DATA.md §60.2/§61) :
    # si des semaines résistent encore à TOUT ce qui précède (rééquilibrage
    # borné + retries + dernier recours ci-dessus, bornes `eval_min_week`/
    # `content_max_week` actives partout jusqu'ici), retente le
    # rééquilibrage UNE fois de plus SANS ces bornes. Elles restent le
    # comportement par défaut PARTOUT ailleurs (la vaste majorité des
    # rééquilibrages s'en satisfont sans y toucher) — seulement levées ici,
    # en dernier recours, sur les quelques semaines qui n'ont littéralement
    # aucune autre issue : une séance non placée DU TOUT est un dommage plus
    # grave qu'un ordre éval/contenu ponctuellement rompu pour la sauver.
    # Jamais déclenché si les bornes n'ont empêché aucun mouvement utile.
    if failed_weeks and groups:
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
            fc_min_week=fc_min_week,
            cap_exceptions=cap_exceptions,
            # Volontairement PAS de eval_min_week/content_max_week ici, cf.
            # commentaire ci-dessus.
        )
        if touched:
            _solve_weeks(sorted(touched), seed_bump=950_000)
            if failed_weeks:
                last_resort_budget = max(week_detail_time_limit * 3, 300.0)
                for w in sorted(failed_weeks):
                    _solve_weeks([w], seed_bump=980_000, long_budget=last_resort_budget, sequential=True)

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
