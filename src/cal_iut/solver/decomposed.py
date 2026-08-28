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
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.ingestion.config_loader import (
    load_course_max_week_rules,
    load_course_min_week_rules,
    load_course_teacher_orders,
    load_session_date_windows,
    load_solver_scheduled_sae,
    load_weekly_cap_exceptions,
)
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
    add_cohort_sequence_constraints,
    add_duo_synchronized_rare_room_constraints,
    add_duration_domain_constraints,
    add_pedagogical_sequence_constraints,
    add_planning_event_block_constraints,
    add_session_date_window_constraints,
    add_student_presence_constraints,
    add_teacher_availability_constraints,
    add_teacher_weekly_hour_cap_constraints,
    add_thursday_afternoon_pac_lock,
    cohort_sequence_pairs,
    duo_episode_pairs,
    sae_blocked_days_by_group,
    sae_blocked_days_by_parcours,
)
from cal_iut.solver.objectives import (
    add_avoid_zone_penalties,
    add_cm_spread_penalties,
    add_course_grouping_penalties,
    add_course_teacher_order_penalties,
    add_edge_slot_penalties,
    add_intra_day_gap_penalties,
    add_midday_fill_penalties,
    add_sae_supervisor_soft_penalties,
    add_teacher_monthly_clustering_penalties,
)
from cal_iut.solver.resources import add_student_and_teacher_no_overlap, build_student_cohorts

SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY

# Plafond horaire hebdomadaire réellement appliqué aux runs complets, et
# SOURCE UNIQUE pour le solveur comme pour le tableau de bord.
#
# Avoir eu deux valeurs différentes (22 dans `SolverConfig`, 23 ici) a coûté
# cher : les runs tournaient à 23 pendant que le contrôle `weekly_cap`
# vérifiait 22 et signalait des « violations » que personne ne savait
# expliquer. Une règle vérifiée à une valeur et appliquée à une autre n'est
# pas une règle.
#
# 23 créneaux = 34h30/semaine, au-dessus des 33h de la règle pédagogique.
# Justification chiffrée et arbitrage : cf. le commentaire détaillé sur
# `solve_decomposed(fi_cap_slots=...)`.
FI_WEEKLY_CAP_SLOTS = 23
FC_WEEKLY_CAP_SLOTS = 23

# Dernière semaine-index admise pour un parcours FI (non-FC) — retour
# utilisateur du 27/08/2026 : « les FI doivent finir leur semestre le 1er
# février, les FC eux ont jusqu'au 12 mars ». Semaine-index 18 = 25-29
# janvier 2027 (juste avant le 1er février), déjà la valeur par défaut de
# `cal-iut audit --fi-max-week` et de `scripts/solve_until_ok.py` — reprise
# ici comme unique source pour que `assign_weeks`, l'audit ET
# `_hard_constraint_context` (verrous manuels : glisser-déposer, suggestions,
# complétion) appliquent tous la MÊME borne, plutôt que trois « 18 » écrits
# à la main à trois endroits différents (même piège que celui documenté
# ci-dessus pour `FI_WEEKLY_CAP_SLOTS`).
FI_MAX_WEEK_DEFAULT = 18


@lru_cache(maxsize=4)
def _session_date_windows(config_dir: Path) -> tuple:
    """Fenêtres de dates par séance, mises en cache : `solve_week_detail` est
    appelé une fois par semaine (et en parallèle), relire le YAML à chaque fois
    ne servirait à rien."""
    return tuple(load_session_date_windows(config_dir))


@lru_cache(maxsize=1)
def _cours_avec_progression_declaree(root: Path) -> frozenset[tuple[str, str]]:
    """{(course_code, semestre)} pour les cours dont `progression.json`
    déclare `"definie": true` — jamais deviné, jamais un défaut permissif.

    Retour utilisateur (27/08/2026, Kyllian Bresson, sur un TD n°3 placé
    avant un TD n°1 du même cours) : « Mais des mélange de TD ce n'est pas
    une erreur ? [...] Pourquoi l'outil bloque ? ». Vérifié : pour WS105
    (et 6 autres cours sur les 8 concernés par les violations du run réel),
    `progression.json` porte `"definie": false, "seances": []` — le
    `sequence_order` de ses séances n'est alors qu'un numéro généré
    automatiquement à l'ingestion (`normalize.py::expand_course_to_sessions`,
    `_synthetic_sequence` quand `progression_defined` est faux), jamais un
    ordre de contenu déclaré par un enseignant. Bloquer TD n°3 avant TD n°1
    dans ce cas n'a donc aucune justification pédagogique — seul CM avant
    TD/TP (l'introduction du contenu avant sa pratique) reste une vraie
    contrainte structurelle, quel que soit `definie`."""
    import json

    chemin = root / "contraintes" / "progression.json"
    if not chemin.exists():
        return frozenset()
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    return frozenset(
        (str(item.get("code_matiere")), str(item.get("semestre")))
        for item in data
        if isinstance(item, dict) and item.get("progression", {}).get("definie")
    )


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
    no_thursday_pm: set[str] | None = None,
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
    initiale, qui ne peut donc jamais y placer de séance. `no_thursday_pm`
    liste les enseignants pour lesquels ce retrait s'applique — `assign_weeks`
    appelle cette fonction DEUX fois, avec et sans, pour poser un plafond par
    cas plutôt qu'un test annuel approximatif (cf. le bug AHA du 25/08/2026).
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
    no_thursday_pm = no_thursday_pm or set()
    all_slots = {(day, s) for day in range(DAYS_PER_WEEK) for s in range(SLOTS_PER_DAY)}

    for avail in teacher_availability:
        forbidden_dates = set((avail.metadata or {}).get("forbidden_dates") or [])
        allowed_slots = {tuple(pair) for pair in (avail.allowed_slots or [])}
        allowed_dates = set(avail.allowed_dates or [])

        for w in range(weeks):
            open_slots = set(allowed_slots) if allowed_slots else set(all_slots)
            open_slots -= set(avail.forbidden_slots or [])
            if avail.teacher_code in no_thursday_pm:
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
    # Ordre pédagogique inter-granularités (CM promo <-> TD/TP sous-groupe),
    # cf. `constraints.py::cohort_sequence_pairs`. Pénalité PAR SEMAINE de
    # retard, appliquée à ~800 paires sur le run complet : à 60, un CM placé
    # une semaine trop tard pèse déjà plus qu'une relation d'ordonnancement
    # inter-matières entière (400 en tout-ou-rien sur ~90 relations), ce qui
    # correspond à la priorité annoncée par l'utilisateur (25/08/2026 :
    # « l'ordonnancement n'est pas bon »). 0 = désactivé.
    cohort_order_weight: int = 60,
    # Critère STRICT de l'ordonnancement inter-matières (« A fini avant que B
    # commence », par cohorte) : pénalité PAR SEMAINE de chevauchement, en
    # complément — pas en remplacement — du critère "moyenne" à
    # `ordonnancement_weight`. Volontairement plus modeste que ce dernier :
    # ~90 couples (relation, cohorte) × un chevauchement initial de 10 à 19
    # semaines, à 400 le terme écraserait tous les autres objectifs (lissage
    # compris) et déstabiliserait l'étage 2 exactement comme le relevé de
    # poids infirmé du 12/08/2026. 0 = désactivé (critère "moyenne" seul,
    # comportement d'avant le 25/08/2026).
    strict_ordonnancement_weight: int = 50,
    # Regroupement mensuel des interventions (ARA, JHU) — même valeur que
    # `SolverConfig.teacher_clustering_weight`, l'objectif étant strictement le
    # même que celui du modèle joint. 0 = désactivé.
    teacher_clustering_weight: int = 120,
    # Inconfort d'une semaine trop pleine — ESSAYÉ ET INFIRMÉ le 26/08/2026,
    # gardé désactivé et configurable pour ne pas avoir à le réécrire si
    # l'hypothèse revient. Mesuré sur 3 graines par configuration (et non sur
    # un tirage unique, la variance entre graines étant de 3 à 6 semaines en
    # échec à configuration identique) :
    #
    #     sans inconfort : 4,7 semaines KO en moyenne  (pic 257 séances)
    #     poids 40       : 6,3                          (pic 246)
    #     poids 120      : 6,0                          (pic 238)
    #
    # Le mécanisme fait pourtant ce qu'on lui demande — le pic de charge baisse
    # nettement. Mais les semaines presque vides le sont pour de BONNES raisons
    # (SAE sanctuarisées, vacances) : y pousser de la charge crée de nouvelles
    # semaines infaisables au lieu d'en soulager. Étaler n'est pas le remède.
    comfort_margin: int = 3,
    comfort_weight: int = 0,
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
    # Combinaisons (semaine, séances) PROUVÉES infaisables par l'étage 3 lors
    # d'une passe précédente — cf. `solve_decomposed` et le commentaire sur les
    # coupes plus bas.
    forbidden_combinations: list[tuple[int, list[str]]] | None = None,
) -> WeekAssignmentResult:
    """Étage 2 : une semaine par séance (domaine ~n_weeks, pas ~n_weeks*30)."""
    model = cp_model.CpModel()
    max_week = max(0, weeks - 1)
    week_var: dict[str, cp_model.IntVar] = {
        s.id: model.new_int_var(0, max_week, f"wk_{s.id}") for s in sessions
    }
    session_index = {s.id: s for s in sessions}
    # `LinearExpr` et non `IntVar` : certaines pénalités sont pondérées
    # directement (`var * poids`) au lieu de passer par une variable
    # intermédiaire — moins de variables pour le même modèle.
    objective_terms: list[cp_model.LinearExpr] = []

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

    config_dir = Path(__file__).resolve().parents[3] / "data" / "config"
    teacher_order_rules = load_course_teacher_orders(config_dir)
    min_week_rules = load_course_min_week_rules(config_dir)
    if min_week_rules:
        by_key = {(r.course_code, r.semestre): r for r in min_week_rules}
        for s in sessions:
            rule = by_key.get((s.course_code, s.semestre))
            if rule is not None and 0 < rule.min_week <= max_week:
                model.add(week_var[s.id] >= rule.min_week)

    # -- Borne de FIN par cours (cf. `CourseMaxWeekRule`, ex. WRA507D qui doit
    # se terminer « environ en janvier ») --
    max_week_rules = load_course_max_week_rules(config_dir)
    if max_week_rules:
        by_key_max = {(r.course_code, r.semestre): r for r in max_week_rules}
        for s in sessions:
            rule = by_key_max.get((s.course_code, s.semestre))
            if rule is not None and 0 <= rule.max_week < max_week:
                model.add(week_var[s.id] <= rule.max_week)

    # -- Coupes : interdire ce que l'étage 3 a PROUVÉ infaisable --
    #
    # C'est la boucle de retour qui manquait à l'architecture. L'étage 2 décide
    # d'une répartition en semaines à partir de comptages par ressource
    # (créneaux d'une cohorte, créneaux d'un enseignant) ; l'étage 3, lui, doit
    # ensuite trouver un horaire RÉEL où ces ressources ne se chevauchent pas et
    # où chaque enseignant tombe sur ses propres créneaux. Les deux ne sont pas
    # équivalents : mesuré le 26/08/2026, 8 semaines sur 24 étaient prouvées
    # infaisables en 0,1 s alors qu'AUCUNE ressource n'y dépassait son plafond.
    # Exemple isolé : la cohorte BUT3-DEV-FC seule tient, Barthélémy Tomasina
    # seul tient, mais pas les deux — ses blocs de 3h, cantonnés au mercredi et
    # au jeudi matin, repoussent les autres séances vers des jours où les
    # enseignants partagés avec les CREACOM-FC sont déjà pris.
    #
    # Aucun réglage ne corrige ça : plafond 22 ou 23, marge physique de 0 à 4,
    # pénalité d'inconfort — tous mesurés sur 3 graines, tous dans le bruit
    # (4,3 à 6,3 semaines en échec, pour une variance de 3 à 6 à configuration
    # identique). Ce n'est pas un paramètre à trouver, c'est une information
    # qui ne remonte pas.
    #
    # Une coupe dit exactement : « ces séances-là, toutes ensemble dans cette
    # semaine-là, c'est impossible — trouve autre chose ». Elle est VALIDE par
    # construction (l'étage 3 l'a prouvé, pas supposé) et n'exclut jamais une
    # solution réalisable. C'est une décomposition de Benders logique, le
    # remède standard pour ce genre d'architecture à deux étages.
    for numero, (semaine_ko, ids_ko) in enumerate(forbidden_combinations or []):
        presents = [sid for sid in ids_ko if sid in week_var]
        if len(presents) < 2:
            continue
        indicateurs = []
        for i, sid in enumerate(presents):
            ind = model.new_bool_var(f"coupe{numero}_{i}")
            model.add(week_var[sid] == semaine_ko).only_enforce_if(ind)
            model.add(week_var[sid] != semaine_ko).only_enforce_if(ind.Not())
            indicateurs.append(ind)
        model.add(sum(indicateurs) <= len(presents) - 1)

    # -- Fenêtres de dates civiles par séance (cf. `SessionDateWindowRule`) --
    # BUG RÉEL (25/08/2026) : ces fenêtres n'étaient posées QUE dans le modèle
    # joint (`cpsat.py::_build_hard_model`), jamais dans le solveur décomposé —
    # qui est pourtant le mode utilisé pour les runs réels (`--decomposed`).
    # Elles étaient donc documentées « dures » dans le README et
    # `contraintes/00_INDEX.md` tout en n'ayant AUCUN effet : sur le run
    # `odd26`, la visite à la BU (WR100BU TD n°1, à faire « entre le 1er et le
    # 15 septembre ») était placée du 21 au 25 septembre, et le TD n°3 (« avant
    # le 15 octobre ») jusqu'au 3 décembre.
    #
    # Ici on ne borne que la SEMAINE : l'étage 3 affine ensuite au grain du
    # jour, la fenêtre pouvant commencer ou finir en milieu de semaine.
    if calendar is not None:
        for rule in _session_date_windows(config_dir):
            start_date = date.fromisoformat(rule.start_date) if rule.start_date else None
            end_date = date.fromisoformat(rule.end_date) if rule.end_date else None
            only_dates = {date.fromisoformat(d) for d in rule.only_dates}
            allowed_weeks_rule = sorted({
                rel
                for rel in range(weeks)
                for day in range(DAYS_PER_WEEK)
                if (d := calendar.week_day_to_date(week_offset + rel, day)) is not None
                and d not in calendar.blocked_dates
                and d not in calendar.holidays
                and (not only_dates or d in only_dates)
                and (start_date is None or d >= start_date)
                and (end_date is None or d <= end_date)
            })
            targets = [
                s
                for s in sessions
                if s.course_code == rule.course_code
                and s.semestre == rule.semestre
                and (rule.session_type is None or s.session_type == rule.session_type)
                and (not rule.sequence_orders or s.sequence_order in rule.sequence_orders)
            ]
            if not targets:
                continue
            if not allowed_weeks_rule:
                warnings.warn(
                    f"{rule.course_code} : la fenêtre {rule.start_date}..{rule.end_date} "
                    "ne contient aucune semaine de l'horizon — contrainte ignorée.",
                    stacklevel=2,
                )
                continue
            for s in targets:
                model.add_allowed_assignments([week_var[s.id]], [[w] for w in allowed_weeks_rule])

    # -- Séquence pédagogique (par groupe brut) : semaine(N) <= semaine(N+1) --
    #
    # Séances du MÊME type (TD-TD, TP-TP) exemptées quand aucune progression
    # de contenu n'est déclarée pour ce cours (retour utilisateur 27/08/2026,
    # Kyllian Bresson : « TD n°3 avant TD n°1, ce n'est pas une erreur »
    # — vérifié : `progression.json::definie=false` pour 7 des 8 cours
    # concernés sur le run réel, donc `sequence_order` n'y est qu'un numéro
    # généré à l'ingestion, jamais un ordre de contenu voulu). Seul un
    # changement de TYPE (CM -> TD/TP, ou TD/TP -> CM si le CM arrive en fin
    # de séquence) reste une vraie dépendance structurelle — contenu
    # introduit avant sa pratique — et reste donc bloqué dans tous les cas.
    cours_avec_progression = _cours_avec_progression_declaree(Path(__file__).resolve().parents[3])
    by_group_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        if s.sequence_order is None:
            continue
        for gid in s.group_ids:
            by_group_course[(s.course_code, s.semestre, gid)].append(s)
    for (course_code, semestre, _gid), group_sessions in by_group_course.items():
        progression_declaree = (course_code, semestre) in cours_avec_progression
        ordered = sorted(group_sessions, key=lambda s: s.sequence_order or 0)
        for prev, nxt in zip(ordered, ordered[1:]):
            if not progression_declaree and prev.session_type == nxt.session_type:
                continue
            if (prev.sequence_order or 0) < (nxt.sequence_order or 0):
                model.add(week_var[prev.id] <= week_var[nxt.id])

    # -- Ordre pédagogique VU PAR L'ÉTUDIANT (CM promo <-> TD/TP sous-groupe) --
    # La boucle ci-dessus ne relie que les séances du même `group_id` brut ;
    # un CM (groupe `promo`) et les TD/TP qui l'encadrent dans
    # `progression.json` ne partagent aucun groupe, donc aucune relation
    # d'ordre. Cf. `cohort_sequence_pairs` pour le bug mesuré (790 paires hors
    # ordre sur le run `odd26`).
    #
    # MOU et GRADUÉ, pas dur : la version dure de cette même barrière a été
    # essayée le 05/08/2026 et rendait 5 semaines infaisables sur BUT1-S1 réel
    # (cf. `constraints.py::add_pedagogical_sequence_constraints`). La
    # pénalité vaut `poids × nombre de semaines de retard`, pas un booléen :
    # un CM une semaine trop tard coûte beaucoup moins qu'un CM cinq semaines
    # trop tard, ce qui donne à CP-SAT un gradient à descendre — un booléen
    # tout-ou-rien lui laisse au contraire toutes les violations équivalentes
    # (c'est précisément ce qui a fait échouer le relevé de poids du
    # 12/08/2026 sur l'ordonnancement inter-matières, cf. plus bas).
    # L'étage 3 finit le travail en dur À L'INTÉRIEUR de chaque semaine.
    if cohort_order_weight > 0:
        for idx, (before, after) in enumerate(cohort_sequence_pairs(sessions, groups)):
            if before not in week_var or after not in week_var:
                continue
            late = model.new_int_var(0, max_week, f"cohordwk_{idx}")
            model.add_max_equality(late, [0, week_var[before] - week_var[after]])
            objective_terms.append(late * cohort_order_weight)

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

    # -- Ordonnancement inter-matières (molle : moyenne par groupe brut ET
    #    chevauchement strict par cohorte réelle, cf. plus bas) --
    cohorts_for_order = build_student_cohorts(groups) if groups else {}
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

            # Critère STRICT « A entièrement fini avant que B commence », par
            # COHORTE réelle et en pénalité GRADUÉE (poids × nombre de semaines
            # de chevauchement), en plus du critère "moyenne" ci-dessus.
            #
            # Pourquoi les deux : la moyenne seule est satisfaite dès que le
            # barycentre de A précède celui de B, ce qui laissait 89/89
            # relations violées au sens strict sur le run `odd26` (WR102/WR101 :
            # A = semaines 3→19, B = semaines 1→13 — la moyenne passe, l'étudiant
            # voit pourtant les deux modules entrelacés tout le semestre).
            # Demande utilisateur du 25/08/2026 : « des matières qui devaient
            # être finies pour commencer ». Molle et graduée, jamais dure :
            # une séparation totale de deux modules de 30+ séances chacun n'est
            # pas toujours physiquement possible dans l'horizon, et un
            # chevauchement de 2 semaines vaut infiniment mieux que 15.
            if strict_ordonnancement_weight > 0 and cohorts_for_order:
                for cohort_ids in cohorts_for_order.values():
                    s_ids = [i for i in source_ids if cohort_ids.intersection(session_index[i].group_ids)]
                    t_ids = [i for i in target_ids if cohort_ids.intersection(session_index[i].group_ids)]
                    if not s_ids or not t_ids:
                        continue
                    ord_idx += 1
                    safe = f"{ord_idx}"
                    # `before` : max(A) doit rester < min(B) ; `after` : l'inverse.
                    first_ids, last_ids = (t_ids, s_ids) if position == "before" else (s_ids, t_ids)
                    late = model.new_int_var(0, max_week, f"ordstrict_max_{safe}")
                    early = model.new_int_var(0, max_week, f"ordstrict_min_{safe}")
                    model.add_max_equality(late, [week_var[i] for i in last_ids])
                    model.add_min_equality(early, [week_var[i] for i in first_ids])
                    overlap = model.new_int_var(0, max_week + 1, f"ordstrict_ov_{safe}")
                    model.add_max_equality(overlap, [0, late - early + 1])
                    objective_terms.append(overlap * strict_ordonnancement_weight)

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
                    # Plafond DUR ci-dessus, INCONFORT mou ci-dessous.
                    #
                    # Diagnostic du 26/08/2026 : aucune cohorte ne dépasse 69 %
                    # d'occupation sur le semestre — la capacité globale n'a
                    # jamais été le problème. Les échecs sont LOCAUX : l'étage 2
                    # remplissait certaines semaines jusqu'au dernier créneau
                    # (270 séances en semaine 12, deux cohortes pile à leur
                    # limite physique en semaine 15) pendant que d'autres
                    # restaient presque vides. Une semaine remplie à ras bord ne
                    # laisse plus à l'étage 3 la moindre liberté pour entrelacer
                    # cohortes et enseignants : elle devient infaisable sans
                    # qu'aucune ressource ne soit individuellement saturée.
                    #
                    # Le plafond dur seul ne peut pas exprimer ça — il autorise
                    # tout jusqu'à la limite, sans préférence. D'où cette
                    # pénalité graduée sur les derniers créneaux : remplir la
                    # 21e case d'une semaine coûte, remplir la 23e coûte trois
                    # fois plus. L'étage 2 étale donc de lui-même quand il le
                    # peut, et n'entasse que lorsqu'il n'a pas le choix.
                    #
                    # Élargir la marge DURE avait été essayé et mesuré nuisible
                    # (marge 2 -> 3 -> 4 : 4, 5 puis 6 semaines en échec) :
                    # retirer de la capacité contraint l'étage 2 au lieu de le
                    # guider. Une préférence molle, elle, ne retire rien.
                    if comfort_weight > 0 and cap_w > comfort_margin:
                        confort = cap_w - comfort_margin
                        trop = model.new_int_var(0, cap_w, f"confort_{safe_key}_w{w}")
                        model.add_max_equality(trop, [0, sum(terms) - confort])
                        objective_terms.append(trop * comfort_weight)

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
    # Le jeudi après-midi est réservé aux PAC : une séance de FORMATION
    # INITIALE ne peut jamais y être placée (`add_thursday_afternoon_pac_lock`),
    # une séance FC si.
    #
    # Bug réel trouvé le 25/08/2026 en diagnostiquant une semaine prouvée
    # INFEASIBLE en 0,1 s : ce retrait était décidé par un test ANNUEL — « cet
    # enseignant a-t-il au moins une séance FC dans tout le semestre ? ». AHA
    # (Amine Haraoubia) en a une seule ; il gardait donc le jeudi après-midi
    # dans le calcul de capacité de TOUTES ses semaines, y compris celles où il
    # n'a que des séances FI. En semaine 16 (11-15 janvier), l'étage 2 le
    # créditait de 24 créneaux (30 moins son mercredi indisponible) et lui en
    # assignait 22 — alors que ses 22 séances de cette semaine, toutes FI, ne
    # disposaient en réalité que de 21 créneaux. Infaisable d'exactement un
    # créneau, et aucune quantité de temps de calcul ne pouvait le rattraper.
    #
    # Corrigé en posant DEUX plafonds au lieu d'un test approximatif :
    #   - toutes les séances de l'enseignant  <= capacité JEUDI PM INCLUS ;
    #   - ses seules séances FI               <= capacité JEUDI PM EXCLU.
    # Exact quelle que soit la répartition FI/FC réelle de la semaine, et sans
    # jamais sous-estimer la capacité d'un enseignant réellement mixte.
    availability_by_week = _teacher_available_slots_by_week(
        teacher_availability, weeks, calendar, week_offset, set()
    )
    availability_by_week_no_thursday_pm = _teacher_available_slots_by_week(
        teacher_availability, weeks, calendar, week_offset, set(by_teacher)
    )
    # Capacité physique par défaut (fériés + jeudi PAC), pour les enseignants
    # SANS entrée de disponibilité déclarée : sans ça ils gardaient le plafond
    # nominal (26) même une semaine à 4 jours ouvrables.
    def _default_teacher_slots(w: int, *, thursday_pm: bool) -> int:
        slots = SLOTS_PER_WEEK
        thursday_open = True
        if calendar is not None:
            for day in range(DAYS_PER_WEEK):
                d = calendar.week_day_to_date(week_offset + w, day)
                if d is None or d in calendar.blocked_dates or d in calendar.holidays:
                    slots -= SLOTS_PER_DAY
                    if day == 3:
                        thursday_open = False
        if not thursday_pm and thursday_open:
            slots -= 3
        return max(0, slots)

    for teacher_code, teacher_sessions in by_teacher.items():
        fi_sessions = [s for s in teacher_sessions if "FC" not in s.parcours]
        for w in range(weeks):
            terms = []
            fi_terms = []
            for s in teacher_sessions:
                ind = model.new_bool_var(f"tcapwk_{teacher_code}_{s.id}_w{w}")
                model.add(week_var[s.id] == w).only_enforce_if(ind)
                model.add(week_var[s.id] != w).only_enforce_if(ind.Not())
                duration = max(1, s.duration_slots)
                term = ind * duration if duration != 1 else ind
                terms.append(term)
                if s in fi_sessions:
                    fi_terms.append(term)
            if not terms:
                continue
            # Même marge que le plafond de cohorte ci-dessus : un enseignant
            # rempli EXACTEMENT à sa disponibilité physique (ex. JLE 20/21 en
            # semaine 8, 3 créneaux interdits + 1 jour d'absence) ne laisse
            # aucune liberté d'entrelacement à l'étage 3, qui doit en plus
            # respecter les cohortes.
            phys = availability_by_week.get((teacher_code, w))
            if phys is None:
                phys = _default_teacher_slots(w, thursday_pm=True)
            model.add(sum(terms) <= min(teacher_weekly_cap_slots, max(1, phys - physical_margin)))

            # Second plafond, sur les seules séances FI : elles n'ont pas accès
            # au jeudi après-midi (cf. le commentaire sur `availability_by_week`).
            if fi_terms:
                phys_fi = availability_by_week_no_thursday_pm.get((teacher_code, w))
                if phys_fi is None:
                    phys_fi = _default_teacher_slots(w, thursday_pm=False)
                if phys_fi < phys:
                    model.add(
                        sum(fi_terms)
                        <= min(teacher_weekly_cap_slots, max(1, phys_fi - physical_margin))
                    )

    # -- SAE : semaine entièrement bloquée pour un parcours -> exclue pour ses cours classiques --
    if blocked_by_parcours:
        fully_blocked_weeks: dict[str, set[int]] = defaultdict(set)
        for (parcours, w), count in blocked_days_count_by_parcours_week.items():
            if count >= DAYS_PER_WEEK:
                fully_blocked_weeks[parcours].add(w)
        for s in sessions:
            if s.is_unplaced_sae:
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
            if s.is_unplaced_sae:
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
            if s.is_unplaced_sae:
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
    #
    # La semaine visée par une séance vient de son rang dans la progression
    # COMPLÈTE du cours (`sequence_order`), pas de son rang parmi les seules
    # séances de son type. La version par type était une cause DIRECTE du
    # désordre CM/TD/TP mesuré sur le run `odd26` : les 3 CM de WR106 étaient
    # étalés sur tout le semestre (cibles ~1/6, ~1/2, ~5/6 de l'horizon) et ses
    # 7 TP aussi (mêmes cibles) — le lissage poussait donc activement le CM
    # d'ordre 9 vers le milieu du semestre et le TP d'ordre 5 au même endroit,
    # en contradiction avec l'ordre pédagogique que l'étage 2 essayait par
    # ailleurs de faire respecter. Aligner les deux objectifs supprime la
    # contradiction au lieu de la compenser à coups de poids.
    #
    # Une séance sans `sequence_order` garde le comportement précédent (rang
    # dans son propre bucket) : rien à déduire d'une progression absente.
    if spread_weight > 0:
        course_ranks: dict[tuple[str, str], dict[int, int]] = {}
        for s in sessions:
            if s.sequence_order is None:
                continue
            course_ranks.setdefault((s.course_code, s.semestre), {})[s.sequence_order] = 0
        for orders in course_ranks.values():
            for rank, order in enumerate(sorted(orders)):
                orders[order] = rank

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
                ranks = course_ranks.get((s.course_code, s.semestre))
                if ranks and s.sequence_order is not None:
                    position, total = ranks[s.sequence_order], len(ranks)
                else:
                    position, total = index, n
                target = (
                    min(int((position + 0.5) * max_week / total), max_week)
                    if total and max_week
                    else 0
                )
                diff = model.new_int_var(-max_week, max_week, f"wspr_d_{s.id}")
                model.add(diff == week_var[s.id] - target)
                abs_diff = model.new_int_var(0, max_week, f"wspr_a_{s.id}")
                model.add_abs_equality(abs_diff, diff)
                weighted = model.new_int_var(0, max(1, max_week * spread_weight), f"wspr_w_{s.id}")
                model.add(weighted == abs_diff * spread_weight)
                objective_terms.append(weighted)

    # -- Regroupement mensuel des interventions d'un enseignant (molle) --
    # ARA (« regrouper ses cours sur une ou deux semaines successives par
    # mois », contrainte géographique) et JHU (« condenser les interventions »,
    # basée à Paris). BUG RÉEL (25/08/2026) : cet objectif n'existait QUE dans
    # le modèle joint, jamais en `--decomposed` — le mode réellement utilisé.
    # Mesuré sur le run `odd26` : ARA intervenait 15 semaines distinctes, JHU
    # 14, pour une demande de 1 à 2 semaines par mois (~10 au plus sur la
    # période). C'est pourtant une décision d'AFFECTATION DE SEMAINE, donc
    # exactement le rôle de cet étage.
    if teacher_clustering_weight > 0 and teacher_availability and calendar is not None:
        objective_terms.extend(
            add_teacher_monthly_clustering_penalties(
                model, sessions, None, teacher_availability, calendar,
                week_offset, weeks, teacher_clustering_weight, week_vars=week_var,
            )
        )

    # -- Ordre souple entre enseignants d'un même module (molle) --
    # Ex. WRA505C : ALO au début de la ressource, AFR à la fin. Même constat
    # que ci-dessus — objectif absent du mode `--decomposed`. Comparé ici sur
    # les SEMAINES plutôt que sur les créneaux absolus : c'est le même critère
    # de position moyenne, à la granularité de cet étage.
    if teacher_order_rules:
        objective_terms.extend(
            add_course_teacher_order_penalties(model, sessions, week_var, teacher_order_rules)
        )

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
        if s.is_unplaced_sae:
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
    # Répartition des CM sur la semaine plutôt que concentrés sur un seul jour
    # (retour utilisateur 27/08/2026, en regardant le run réel : « pour les
    # S1 c'est juste impossible ils ont des journées entières de CM » — une
    # journée BUT1 vue en production : 6 CM d'affilée, 5 matières
    # différentes). 0 = désactivé (comportement d'avant ce correctif), pour
    # ne rien changer au run principal tant que ce n'est pas explicitement
    # demandé — cf. `scripts/polish_run.py`, qui l'active pour sa passe de
    # rééquilibrage ciblée.
    cm_spread_weight: int = 0,
    cm_spread_threshold: int = 2,
    # Regroupement de deux cours sur les mêmes journées (l'inverse du terme
    # ci-dessus) — ex. BUT3-DEV-FC, WRA507D + WSA501D : présence limitée à
    # l'IUT, autant remplir la journée plutôt que fragmenter. Vide/poids nul
    # = désactivé.
    course_grouping_pairs: list[tuple[str, str]] | None = None,
    course_grouping_weight: int = 0,
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
    # Ordre pédagogique VU PAR L'ÉTUDIANT (CM promo vs TD/TP sous-groupe) : la
    # ligne au-dessus n'ordonne que les séances du même `group_id` brut, donc
    # jamais un CM face aux TD/TP qui l'entourent. Ici, dur — les deux séances
    # sont dans la même semaine, les ordonner ne coûte quasiment rien ; la
    # relation INTER-semaines est portée en pénalité graduée par l'étage 2
    # (`assign_weeks`). Cf. `cohort_sequence_pairs`.
    add_cohort_sequence_constraints(model, week_sessions, session_starts, groups)
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

    # Fenêtres de dates par séance, au grain du JOUR (l'étage 2 n'a borné que
    # la semaine) — cf. le commentaire dans `assign_weeks`.
    add_session_date_window_constraints(
        model,
        week_sessions,
        session_starts,
        list(_session_date_windows(Path(__file__).resolve().parents[3] / "data" / "config")),
        sliced_calendar,
        0,
        num_weeks,
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

    if cm_spread_weight > 0:
        objective_terms += add_cm_spread_penalties(
            model, week_sessions, session_starts, groups, num_weeks, cm_spread_weight, cm_spread_threshold
        )
    if course_grouping_weight > 0 and course_grouping_pairs and num_weeks == 1:
        # `add_course_grouping_penalties` suppose un horizon LOCAL à une seule
        # semaine (cf. sa docstring) — jamais utilisé sur une régénération
        # jointe de plusieurs semaines.
        objective_terms += add_course_grouping_penalties(
            model, week_sessions, session_starts, course_grouping_pairs, course_grouping_weight
        )

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


def _build_sequence_neighbors(
    sessions: list[SessionToPlace],
    groups: list[Group] | None = None,
    *,
    # Désactivable (27/08/2026) pour `scripts/polish_run.py` : la 3e source
    # (ordonnancement ENTRE cours, cf. plus bas) est une contrainte SOUPLE
    # côté solveur (poids 400, léger dépassement toléré) — l'imposer comme
    # borne DURE lors d'une réparation ciblée peut combiner deux léger
    # chevauchements par ailleurs acceptables en une fenêtre [lo,hi]
    # IMPOSSIBLE (lo > hi), alors qu'aucune des deux relations, prise seule,
    # n'est en violation dure. Vrai dans tous les autres appelants (la
    # complétion automatique, qui POSE des séances neuves, n'a pas ce
    # problème : rien n'y a encore de chevauchement à combiner).
    include_ordonnancement: bool = True,
) -> dict[str, tuple[list[str], list[str]]]:
    """
    session_id -> (ids devant le précéder, ids devant le suivre), utilisé par
    `_movable_bounds` pour le rééquilibrage post-échec sans dupliquer
    l'ordonnancement de l'étage 2.

    Deux sources, exactement celles que l'étage 2 fait respecter :
    - le même (cours, semestre, groupe brut) — ordre pédagogique littéral ;
    - les paires inter-granularités vues par une même cohorte étudiante
      (`cohort_sequence_pairs`, ex. CM promo ↔ TD d'un sous-groupe) quand
      `groups` est fourni. Sans elles, le rééquilibrage pouvait déplacer un CM
      APRÈS les TD qu'il doit précéder, cassant après coup une garantie que
      l'étage 2 venait d'obtenir — exactement le patron du bug corrigé le
      12/08/2026 sur les évaluations (cf. `_eval_after_content_bounds`).
    """
    # Séances du MÊME type (TD-TD, TP-TP) exemptées quand aucune progression
    # de contenu n'est déclarée pour ce cours — même correctif et même
    # justification que `assign_weeks` ci-dessus (retour utilisateur
    # 27/08/2026, Kyllian Bresson), pour que les bornes de rééquilibrage/
    # placement manuel restent cohérentes avec ce que le solveur impose
    # réellement.
    cours_avec_progression = _cours_avec_progression_declaree(Path(__file__).resolve().parents[3])
    by_group_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        if s.sequence_order is None:
            continue
        for gid in s.group_ids:
            by_group_course[(s.course_code, s.semestre, gid)].append(s)

    neighbors: dict[str, tuple[list[str], list[str]]] = {s.id: ([], []) for s in sessions}
    for (course_code, semestre, _gid), group_sessions in by_group_course.items():
        progression_declaree = (course_code, semestre) in cours_avec_progression
        ordered = sorted(group_sessions, key=lambda s: s.sequence_order or 0)
        for prev, nxt in zip(ordered, ordered[1:]):
            if not progression_declaree and prev.session_type == nxt.session_type:
                continue
            if (prev.sequence_order or 0) < (nxt.sequence_order or 0):
                neighbors[nxt.id][0].append(prev.id)
                neighbors[prev.id][1].append(nxt.id)

    if groups:
        for before, after in cohort_sequence_pairs(sessions, groups):
            if before in neighbors and after in neighbors:
                neighbors[after][0].append(before)
                neighbors[before][1].append(after)

    # Troisième source, ajoutée le 27/08/2026 : l'ordonnancement ENTRE cours
    # différents (`metadata["ordonnancement"]`, ex. « WR101 doit être
    # entièrement fini avant que WR103 commence »). C'est la contrainte
    # DURE que le solveur applique dans `add_ordonnancement_constraints`, à
    # la granularité du groupe brut partagé — jusqu'ici ABSENTE de cette
    # fonction, alors que `_movable_bounds` et `_rebalance_failed_weeks` en
    # dépendent tous les deux, et que l'API (`_hard_constraint_context`,
    # placement manuel, complétion automatique) s'appuie sur `_movable_bounds`
    # pour borner les semaines admissibles.
    #
    # Conséquence mesurée sur le run réel du 26/08/2026 : le module de
    # complétion automatique a placé des séances de cours liés par cette
    # relation SANS EN AVOIR CONNAISSANCE — le chevauchement inter-matières
    # (`score_run::overlap`) est passé de 495 à 993 semaines cumulées après
    # complétion. Exactement le défaut initial signalé en tête de ce chantier
    # (« des exemples de matière qui devait être finie pour commencer »).
    #
    # Même sémantique que le solveur, par arêtes complètes entre les deux
    # côtés du groupe partagé (pas seulement les voisins immédiats) : la borne
    # calculée par `_movable_bounds` (min/max sur les voisins déjà placés)
    # donne alors exactement max(source) < min(target) — ou l'inverse pour
    # "after" — dès qu'AU MOINS UN élément de l'autre côté est déjà placé.
    #
    # `include_ordonnancement=False` (cf. paramètre) saute tout ce bloc :
    # trouvé le 27/08/2026 en réparant des violations sur un run réel où
    # `add_ordonnancement_constraints` n'est que SOUPLE côté solveur (léger
    # chevauchement toléré) — combiner ce chevauchement DÉJÀ TOLÉRÉ à une
    # borne SAME-COURSE (source 1) peut produire un [lo,hi] avec lo > hi,
    # une fenêtre RÉELLEMENT impossible, alors qu'aucune des deux relations
    # prise seule n'est en violation dure.
    if include_ordonnancement:
        by_course_key: dict[str, list[SessionToPlace]] = defaultdict(list)
        for s in sessions:
            by_course_key[f"{s.course_code}:{s.semestre}:{s.parcours}"].append(s)

        seen_ord_pairs: set[tuple[str, str, str]] = set()
        for s in sessions:
            for raw in s.metadata.get("ordonnancement") or []:
                position = str(raw.get("position", ""))
                target_code = str(raw.get("target_course_code", ""))
                if position not in ("before", "after") or not target_code:
                    continue
                semestre = str(raw.get("semestre", s.semestre))
                source_key = f"{s.course_code}:{semestre}:{s.parcours}"
                target_key = f"{target_code}:{semestre}:{s.parcours}"
                pair_key = (position, source_key, target_key)
                if pair_key in seen_ord_pairs:
                    continue
                seen_ord_pairs.add(pair_key)

                source_sessions = by_course_key.get(source_key, [])
                target_sessions = by_course_key.get(target_key, [])
                if not source_sessions or not target_sessions:
                    continue

                # Comparaison PAR GROUPE BRUT PARTAGÉ, comme le solveur : sans
                # groupe commun, la relation ne borne rien ici (repli global du
                # solveur non répliqué — l'API n'a pas besoin d'aller jusque-là).
                src_by_group: dict[str, list[str]] = defaultdict(list)
                for ss in source_sessions:
                    for gid in ss.group_ids:
                        src_by_group[gid].append(ss.id)
                tgt_by_group: dict[str, list[str]] = defaultdict(list)
                for ts in target_sessions:
                    for gid in ts.group_ids:
                        tgt_by_group[gid].append(ts.id)

                for gid in set(src_by_group) & set(tgt_by_group):
                    src_ids = src_by_group[gid]
                    tgt_ids = tgt_by_group[gid]
                    if position == "before":
                        for sid in src_ids:
                            neighbors[sid][1].extend(tgt_ids)
                        for tid in tgt_ids:
                            neighbors[tid][0].extend(src_ids)
                    else:  # "after" : toute séance source après toute séance cible
                        for sid in src_ids:
                            neighbors[sid][0].extend(tgt_ids)
                        for tid in tgt_ids:
                            neighbors[tid][1].extend(src_ids)

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


def _date_window_weeks_by_session(
    sessions: list[SessionToPlace],
    calendar: AcademicCalendar | None,
    week_offset: int,
    weeks: int,
    config_dir: Path,
) -> dict[str, set[int]]:
    """
    session_id -> semaines admissibles au titre de sa fenêtre de dates civiles
    (`SessionDateWindowRule`), pour que le RÉÉQUILIBRAGE ne déplace jamais une
    séance hors de sa fenêtre.

    L'étage 2 pose bien la contrainte sur `week_var`, mais
    `_rebalance_failed_weeks` déplace ensuite des séances d'une semaine à
    l'autre en dehors de tout modèle CP-SAT : sans cette borne il défaisait
    silencieusement la garantie, et l'étage 3 ne pouvait plus rien rattraper
    (la fenêtre ne couvre aucun jour de la nouvelle semaine, la contrainte est
    alors ignorée avec un avertissement). Même patron que
    `_eval_after_content_bounds`, corrigé pour la même raison.
    """
    if calendar is None:
        return {}
    result: dict[str, set[int]] = {}
    for rule in _session_date_windows(config_dir):
        start = date.fromisoformat(rule.start_date) if rule.start_date else None
        end = date.fromisoformat(rule.end_date) if rule.end_date else None
        only = {date.fromisoformat(d) for d in rule.only_dates}
        allowed = {
            rel
            for rel in range(weeks)
            for day in range(DAYS_PER_WEEK)
            if (d := calendar.week_day_to_date(week_offset + rel, day)) is not None
            and d not in calendar.blocked_dates
            and d not in calendar.holidays
            and (not only or d in only)
            and (start is None or d >= start)
            and (end is None or d <= end)
        }
        if not allowed:
            continue
        for session in sessions:
            if session.course_code != rule.course_code or session.semestre != rule.semestre:
                continue
            if rule.session_type is not None and session.session_type != rule.session_type:
                continue
            if rule.sequence_orders and session.sequence_order not in rule.sequence_orders:
                continue
            previous = result.get(session.id)
            result[session.id] = allowed if previous is None else (previous & allowed)
    return result


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
    # Symétrique de `fc_min_week` ci-dessus, jamais lu ici avant le 27/08/2026 :
    # trouvé en auditant une recherche `solve_until_ok.py --fi-max-week 18`
    # (retour utilisateur : « les FI doivent finir le 1er février ») —
    # `assign_weeks` respecte bien la borne pour son affectation initiale,
    # mais une séance FI strandée dans une semaine PROUVÉE infaisable par
    # l'étage 3 pouvait ensuite être rééquilibrée ICI vers n'importe quelle
    # semaine libre, y compris au-delà de `fi_max_week` (133 séances FI en
    # semaine 19 constatées sur un run réel, alors que `assign_weeks` seul
    # n'en avait laissé passer aucune). Même mécanisme de fuite que
    # `allowed_weeks_by_parcours` (FC) ci-dessus, côté FI cette fois.
    fi_max_week: int | None = None,
    eval_min_week: dict[str, int] | None = None,
    content_max_week: dict[str, int] | None = None,
    # cf. `_date_window_weeks_by_session` : sans cette borne, le rééquilibrage
    # peut sortir une séance de sa fenêtre de dates, et plus rien ne l'y
    # ramène.
    date_window_weeks: dict[str, set[int]] | None = None,
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
    neighbors = _build_sequence_neighbors(all_sessions, list(group_by_id.values()))

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
        if fi_max_week is not None and "FC" not in session.parcours and target_w > fi_max_week:
            return False  # après la fin de semestre FI (cf. assign_weeks::fi_max_week)
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
        allowed_window = (date_window_weeks or {}).get(session.id)
        if allowed_window is not None and target_w not in allowed_window:
            return False  # hors de la fenêtre de dates civiles de la séance (cf. _date_window_weeks_by_session)
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
            # Les séances SAE non planifiées par le solveur ont une semaine
            # imposée par le calendrier réel — jamais rééquilibrées, sous peine
            # de casser la sanctuarisation. Une SAE que le solveur place bien
            # (`solver_scheduled_sae`, ex. WSA501D) est déplaçable comme les
            # autres séances.
            [s for s in sessions_by_week[w] if not s.is_unplaced_sae],
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
    long_budget_seeds: int = 8,
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
        attempts = tuple(
            (long_budget, random_seed + 5000 * i) for i in range(max(1, long_budget_seeds))
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


def _cuts_from_failed_weeks(
    failed_weeks: list[int],
    sessions_by_week: dict[int, list[SessionToPlace]],
    week_offset: int,
    *,
    calendar: AcademicCalendar,
    teacher_availability: list[TeacherAvailability] | None,
    groups: list[Group],
    student_presences: list[StudentPresence] | None,
    duos: list[TeacherDuo] | None,
    blocked_by_parcours: dict[str, set[tuple[int, int]]] | None,
    blocked_by_group: dict[str, set[tuple[int, int]]] | None,
    planning_event_blocked: dict[str, set[tuple[int, int, int]]] | None,
) -> list[tuple[int, list[str]]]:
    """Transforme des semaines en échec en coupes exploitables par l'étage 2.

    Deux précautions qui font toute la valeur des coupes :

    1. **Ne couper que le PROUVÉ.** On rejoue la semaine avec un budget court
       et on ne retient que `INFEASIBLE`. Une semaine `UNKNOWN` n'a rien
       démontré : l'interdire écarterait peut-être la bonne solution.
    2. **Couper le plus PETIT sous-ensemble possible.** Interdire les 250
       séances d'une semaine n'apprend presque rien — l'étage 2 déplace une
       séance et recommence. On cherche donc la cohorte responsable et on ne
       coupe qu'elle : la coupe est alors beaucoup plus contraignante, donc
       beaucoup plus informative.
    """
    from cal_iut.solver.resources import build_student_cohorts

    cohorts = build_student_cohorts(groups) if groups else {}
    cuts: list[tuple[int, list[str]]] = []

    for w in sorted(failed_weeks):
        sess = sessions_by_week.get(w) or []
        if len(sess) < 2:
            continue

        def _local2(source):
            out = {k: {(0, d) for (wk, d) in v if wk == w} for k, v in (source or {}).items()}
            return {k: v for k, v in out.items() if v} or None

        def _local3(source):
            out = {k: {(0, d, sl) for (wk, d, sl) in v if wk == w} for k, v in (source or {}).items()}
            return {k: v for k, v in out.items() if v} or None

        def _essai(sous_ensemble: list[SessionToPlace], budget: float = 12.0) -> str:
            statut, _ = solve_week_detail(
                sous_ensemble, week_offset + w,
                teacher_availability=teacher_availability, calendar=calendar,
                student_presences=student_presences, groups=groups,
                blocked_days_by_parcours_week=_local2(blocked_by_parcours),
                blocked_days_by_group_week=_local2(blocked_by_group),
                duos=duos, time_limit_seconds=budget, num_workers=4, random_seed=2027,
                planning_event_blocked_local=_local3(planning_event_blocked),
                stop_at_first_solution=True,
            )
            return statut

        if _essai(sess) != "INFEASIBLE":
            continue  # pas prouvé : rien à couper

        # Réduction : une seule cohorte suffit-elle à rendre la semaine
        # impossible ? Si oui, la coupe ne porte que sur ses séances.
        coupe = [s.id for s in sess]
        for ids in cohorts.values():
            mine = [s for s in sess if ids.intersection(s.group_ids)]
            if len(mine) < 2 or len(mine) >= len(sess):
                continue
            if _essai(mine, budget=5.0) == "INFEASIBLE":
                coupe = [s.id for s in mine]
                break
        cuts.append((w, coupe))
    return cuts


def _tag_scheduled_sae(
    session: SessionToPlace,
    scheduled: set[tuple[str, str]],
) -> SessionToPlace:
    """
    Marque une SAE que le solveur doit placer lui-même, pour que
    `SessionToPlace.is_unplaced_sae` la traite ensuite comme une séance
    ordinaire (soumise à la sanctuarisation des AUTRES SAE de son parcours,
    rééquilibrable, comptée dans les plafonds).

    Copie plutôt que mutation : `sessions` est la liste d'entrée de l'appelant,
    qui peut la réutiliser après la résolution (l'API la garde en mémoire entre
    deux runs).
    """
    if not session.course_code.upper().startswith("WS"):
        return session
    if (session.course_code.upper(), session.semestre) not in scheduled:
        return session
    return replace_metadata(session, solver_scheduled_sae=True)


def replace_metadata(session: SessionToPlace, **extra: object) -> SessionToPlace:
    return session.model_copy(update={"metadata": {**session.metadata, **extra}})


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
    # HISTORIQUE, à lire avant de retoucher cette valeur.
    #
    # 14/08/2026 : relevé 22 -> 23, puis annulé le jour même (§62, mesuré sur 5
    # runs : le relevé GLOBAL dégradait la fiabilité). `assign_weeks` et
    # `SolverConfig` sont revenus à 22 — mais PAS cette valeur-ci, qui écrase
    # la leur et est la seule qui compte pour un run complet. Tous les runs
    # depuis tournaient donc à 23 sans que personne ne le sache, y compris le
    # run de référence `odd26`, qui était complet.
    #
    # 25/08/2026 : aligné à 22 par cohérence avec la décision documentée.
    # 26/08/2026 : ANNULÉ après mesure. Onze runs consécutifs à 22 n'ont produit
    # AUCUN emploi du temps complet (85 séances manquantes au mieux), et une
    # comparaison à réglages égaux donne :
    #
    #     plafond 22 : 4 semaines infaisables   |   plafond 23 : 3
    #     marge physique 3 : 5                  |   marge physique 4 : 6
    #     sans les objectifs ajoutés le 25/08 : 4 (identique à 22 — ils sont
    #                                              hors de cause)
    #
    # Le seul levier qui améliore la faisabilité est la capacité. Revenir à 22
    # revient à préférer un planning INEXISTANT à un planning où certaines
    # semaines comptent 1h30 de plus — arbitrage que Kyllian Bresson a déjà
    # tranché explicitement (§61.1 : « les étudiants peuvent faire 1h30 de plus
    # par semaine de manière exceptionnelle »).
    #
    # 23 est donc rétabli, mais ce N'EST PAS un choix neutre : il autorise
    # 34h30 hebdomadaires au lieu des 33h de la règle. Repasser à 22 est une
    # décision d'une ligne, à prendre en connaissance de son coût.
    fi_cap_slots: int = FI_WEEKLY_CAP_SLOTS,
    fc_cap_slots: int = FC_WEEKLY_CAP_SLOTS,
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
    # Budget du DERNIER RECOURS (cf. plus bas) : chaque semaine encore en échec
    # après tout le reste est retentée seule, à pleine puissance CP-SAT, sur
    # `last_resort_seeds` graines de `last_resort_seconds` chacune. Une
    # tentative qui RÉUSSIT s'arrête presque tout de suite
    # (`stop_at_first_solution`) ; seules celles qui échouent consomment leur
    # budget entier — d'où un coût pire cas de
    # `semaines_en_échec × graines × secondes`, soit jusqu'à 40 minutes par
    # semaine aux valeurs par défaut.
    #
    # Paramétrables depuis le 25/08/2026 pour `scripts/solve_until_ok.py` :
    # quand on relance en boucle sur des graines différentes, mieux vaut dix
    # runs courts qu'un run qui s'acharne — la variance de graine domine
    # largement le budget (même constat qu'en §58 à l'échelle de la semaine).
    # Les défauts restent les valeurs éprouvées, un run manuel ne change donc
    # pas de comportement.
    last_resort_seconds: float | None = None,
    last_resort_seeds: int = 8,
    # Nombre de tours de la boucle de retour étage 3 -> étage 2 (coupes de
    # Benders logiques, cf. `_cuts_from_failed_weeks`). 0 = comportement
    # d'avant le 26/08/2026 : l'étage 2 décide une fois, sans jamais apprendre
    # de ses échecs.
    benders_rounds: int = 3,
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
    # Les SAE sont normalement définies par leurs enseignants : on ne garde que
    # leurs dates pour sanctuariser les cours classiques. Exception explicite,
    # déclarée dans `course_scheduling_rules.yaml::solver_scheduled_sae` (ex.
    # WSA501D, sans aucune date officielle) — cf. `load_solver_scheduled_sae`.
    solver_scheduled_sae = load_solver_scheduled_sae(
        Path(__file__).resolve().parents[3] / "data" / "config"
    )
    unlocked = [
        _tag_scheduled_sae(s, solver_scheduled_sae)
        for s in unlocked
        if not s.course_code.upper().startswith("WS")
        or (s.course_code.upper(), s.semestre) in solver_scheduled_sae
    ]
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
                long_budget_seeds=last_resort_seeds,
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

    # ------------------------------------------------------------------
    # Boucle de retour étage 3 -> étage 2 (coupes de Benders logiques)
    # ------------------------------------------------------------------
    # Chaque semaine que l'étage 3 déclare INFEASIBLE est une information dure
    # que l'étage 2 n'avait pas. On la lui rend sous forme de coupe et on lui
    # redemande une répartition — plutôt que de laisser le rééquilibrage
    # déplacer des séances au jugé, sans jamais comprendre pourquoi.
    #
    # Seules les semaines PROUVÉES infaisables produisent une coupe : une
    # semaine simplement trop lente (`UNKNOWN`) n'a rien démontré, l'interdire
    # écarterait peut-être une solution valable.
    #
    # On garde le MEILLEUR état rencontré, jamais le dernier. Une coupe est
    # valide — elle n'écarte aucune solution réalisable — mais rien ne garantit
    # que la répartition SUIVANTE soit plus facile à réaliser : l'étage 2
    # optimise un proxy, pas la faisabilité réelle. Sans ce garde-fou, un bon
    # résultat pourrait être écrasé par un moins bon, exactement le piège
    # corrigé le 12/08/2026 sur la boucle de tentatives (cf. docs/DATA.md).
    coupes: list[tuple[int, list[str]]] = []
    meilleur: tuple[int, dict[str, int], dict[int, dict[str, int]], list[int]] | None = None

    def _seances_manquantes() -> int:
        # Compte de SÉANCES non placées — pas de semaines en échec. Mesuré le
        # 26/08/2026 : une coupe peut faire passer 10 semaines en échec à 7
        # tout en concentrant tellement de séances dans ces 7 semaines que le
        # nombre RÉEL de séances non placées augmente (2100 -> 1712 sur un run
        # réel). Compter les semaines aurait gardé ce résultat comme
        # "meilleur" alors qu'il est nettement pire — exactement le piège déjà
        # documenté pour `RunScore` (cf. scripts/solve_until_ok.py, correctif
        # du 12/08/2026) : ce qui compte n'est jamais "combien de conteneurs
        # ont un problème", mais "combien d'heures d'enseignement manquent".
        return sum(len(sessions_by_week.get(w, ())) for w in failed_weeks)

    def _memoriser_si_meilleur() -> None:
        nonlocal meilleur
        manquantes = _seances_manquantes()
        if meilleur is None or manquantes < meilleur[0]:
            meilleur = (
                manquantes,
                dict(week_by_session),
                {w: dict(t) for w, t in local_times_by_week.items()},
                list(failed_weeks),
            )

    if benders_rounds > 0:
        _memoriser_si_meilleur()

    for tour in range(max(0, benders_rounds)):
        if not failed_weeks:
            break
        nouvelles = _cuts_from_failed_weeks(
            failed_weeks, sessions_by_week, week_offset, calendar=calendar,
            teacher_availability=teacher_availability, groups=groups,
            student_presences=student_presences, duos=duos,
            blocked_by_parcours=blocked_by_parcours, blocked_by_group=blocked_by_group,
            planning_event_blocked=planning_event_blocked,
        )
        if not nouvelles:
            break  # aucune semaine prouvée : les coupes n'ont rien à apprendre
        coupes.extend(nouvelles)

        relance = assign_weeks(
            unlocked, groups, weeks,
            duos=duos, blocked_by_parcours=blocked_by_parcours,
            blocked_by_group=blocked_by_group, student_presences=student_presences,
            teacher_availability=teacher_availability, calendar=calendar,
            week_offset=week_offset, teacher_weekly_cap_slots=teacher_weekly_cap_slots,
            fi_cap_slots=stage2_fi_cap, fc_cap_slots=stage2_fc_cap,
            time_limit_seconds=week_assignment_time_limit,
            num_workers=num_workers, random_seed=random_seed + 1000 * (tour + 1),
            fi_max_week=fi_max_week, fc_min_week=fc_min_week,
            cap_exceptions=cap_exceptions, physical_margin=physical_margin,
            spread_weight=spread_weight, forbidden_combinations=coupes,
        )
        if relance.status not in ("OPTIMAL", "FEASIBLE"):
            break  # les coupes rendent l'étage 2 infaisable : on garde l'existant

        # Nouvelle répartition. Ne re-résoudre QUE les semaines dont le contenu
        # a réellement changé : une coupe ne déplace en général qu'une poignée
        # de séances, et un étage 3 complet sur 24 semaines est ce qui coûte
        # l'essentiel du temps d'un run. Une semaine au contenu identique garde
        # son horaire déjà calculé — il reste valide, rien de ce qui la
        # concerne n'a bougé.
        avant = {w: {x.id for x in ss} for w, ss in sessions_by_week.items()}

        sessions_by_week.clear()
        week_by_session.clear()
        week_by_session.update(relance.week_by_session)
        for s in unlocked:
            sessions_by_week[week_by_session[s.id]].append(s)

        apres = {w: {x.id for x in ss} for w, ss in sessions_by_week.items()}
        changees = sorted(
            w for w in set(avant) | set(apres)
            if avant.get(w, set()) != apres.get(w, set())
        )
        for w in changees:
            local_times_by_week.pop(w, None)
            if w in failed_weeks:
                failed_weeks.remove(w)
        # Une semaine devenue vide n'est plus un échec : il n'y a rien à y placer.
        for w in list(failed_weeks):
            if not apres.get(w):
                failed_weeks.remove(w)

        if not changees:
            break  # l'étage 2 rend la même chose : les coupes n'apportent plus rien
        _solve_weeks(changees, seed_bump=7_000 * (tour + 1))
        _memoriser_si_meilleur()

    # Restauration du meilleur état : la dernière répartition essayée n'est pas
    # forcément la meilleure (cf. commentaire ci-dessus). Comparaison sur le
    # même critère que `_memoriser_si_meilleur` : des SÉANCES manquantes, pas
    # des semaines en échec.
    if meilleur is not None and _seances_manquantes() > meilleur[0]:
        _, best_weeks, best_times, best_failed = meilleur
        week_by_session.clear()
        week_by_session.update(best_weeks)
        sessions_by_week.clear()
        for s in unlocked:
            sessions_by_week[week_by_session[s.id]].append(s)
        local_times_by_week.clear()
        local_times_by_week.update(best_times)
        failed_weeks[:] = best_failed

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
        # Fenêtres de dates civiles : mêmes bornes pour le rééquilibrage que
        # pour l'étage 2, sinon il les casse (cf. `_date_window_weeks_by_session`).
        date_window_weeks = _date_window_weeks_by_session(
            unlocked, calendar, week_offset, weeks,
            Path(__file__).resolve().parents[3] / "data" / "config",
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
                fc_min_week=fc_min_week,
                fi_max_week=fi_max_week,
                eval_min_week=eval_min_week,
                content_max_week=content_max_week,
                date_window_weeks=date_window_weeks,
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
        last_resort_budget = (
            last_resort_seconds
            if last_resort_seconds is not None
            else max(week_detail_time_limit * 3, 300.0)
        )
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
            fi_max_week=fi_max_week,
            cap_exceptions=cap_exceptions,
            # Les fenêtres de dates restent, elles, TOUJOURS respectées : ce
            # dernier recours ne lève que les bornes éval/contenu (compromis
            # explicite §61), pas une contrainte dure de calendrier.
            date_window_weeks=date_window_weeks,
            # Volontairement PAS de eval_min_week/content_max_week ici, cf.
            # commentaire ci-dessus.
        )
        if touched:
            _solve_weeks(sorted(touched), seed_bump=950_000)
            if failed_weeks:
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
