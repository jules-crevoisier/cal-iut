"""Fonctions objectif : trous intra-journée + front-loading sur le semestre."""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY, TimeSlot, WeekDay

# Fraction de l'horizon utilisée comme fenêtre de compaction (cf. §12
# docs/DATA.md, 3e itération) : réutilise EXACTEMENT la structure de la
# version "étalement uniforme" (proportionnelle par cours, ce qui échelonne
# naturellement la contention entre matières différentes plutôt que de les
# faire toutes concourir sur les mêmes premières semaines).
#
# Mise à jour (retour utilisateur, chantier S1) : 0.6 compressait les séances
# dans les ~60% premiers de l'horizon (semaines 2-11 pleines, 12-19 vides sur
# BUT1-S1 réel) — trop agressif, un vrai "lissage" est demandé sur tout
# l'horizon S1 plutôt qu'une compaction artificielle. Défaut relevé à 1.0
# (= la 1ère itération historique, étalement proportionnel sur 100% de
# l'horizon, déjà validée tractable ~15min FEASIBLE) ; reste réglable via
# `SolverConfig.spread_frontload_fraction` si un compromis intermédiaire est
# souhaité plus tard.
DEFAULT_FRONTLOAD_FRACTION = 1.0


def add_semester_spread_penalties(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    horizon: int,
    weight: int,
    frontload_fraction: float = DEFAULT_FRONTLOAD_FRACTION,
) -> list[cp_model.LinearExprT]:
    """
    Étalement/densification (cahier des charges §5, "objective_function"
    priorité 1) : place les séances proportionnellement (par cours) sur
    `frontload_fraction` de l'horizon S1 — répartit la charge sur tout
    l'horizon disponible par défaut (1.0) plutôt que de la compresser
    artificiellement sur son début, tout en gardant chaque cours étalé de
    façon échelonnée (pas de compétition frontale entre matières).

    Historique de cette fonction (cf. docs/DATA.md §11.2/§12 pour le détail) :
    1. `target = (i+0.5)/n * horizon` (étalement uniforme, fraction=1.0) —
       fiable pour le solveur (FEASIBLE en ~15 min).
    2. `minimize(Σ start_i)` (pure, sans cible) — sémantiquement correct mais
       intraitable empiriquement (`UNKNOWN` à 20 et 40 min).
    3. Cible précoce à espacement FIXE (`target = (i+0.5) * 6 créneaux`) —
       toujours `UNKNOWN` à 15 min : en poussant CHAQUE cours vers les mêmes
       toutes premières semaines, ça crée une compétition frontale entre
       matières différentes pour les mêmes créneaux, plus dur à satisfaire que
       l'étalement (qui échelonnait naturellement cette compétition dans le
       temps).
    4. Compression à `frontload_fraction=0.6` — plus dense/précoce que (1),
       mais jugée trop agressive à l'usage (cf. note ci-dessus) ; le paramètre
       reste disponible si un compromis entre (1) et (4) est voulu.
    """
    if weight <= 0 or horizon <= 1:
        return []

    buckets: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for session in sessions:
        for gid in session.group_ids:
            key = (session.course_code, session.session_type.value, gid)
            buckets[key].append(session)

    effective_horizon = max(1, int(horizon * frontload_fraction))
    penalties: list[cp_model.IntVar] = []
    for (course, stype, gid), group in buckets.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda s: (s.sequence_order, s.id))
        n = len(ordered)
        for index, session in enumerate(ordered):
            target = min(int((index + 0.5) * (effective_horizon - 1) / n), horizon - 1)
            start = session_starts[session.id]
            diff = model.new_int_var(-horizon, horizon, f"spr_d_{course}_{stype}_{gid}_{index}")
            model.add(diff == start - target)
            abs_diff = model.new_int_var(0, horizon, f"spr_a_{course}_{stype}_{gid}_{index}")
            model.add_abs_equality(abs_diff, diff)
            weighted = model.new_int_var(0, horizon * weight, f"spr_w_{course}_{stype}_{gid}_{index}")
            model.add(weighted == abs_diff * weight)
            penalties.append(weighted)

    return penalties


def add_intra_day_gap_penalties(
    model: cp_model.CpModel,
    session_starts: dict[str, cp_model.IntVar],
    group_sessions: dict[str, list[str]],
    weeks: int,
    gap_weight: int,
) -> list[cp_model.IntVar]:
    """
    Pénalise les trous dans une journée : span - count pour chaque groupe/semaine/jour.
    Retourne les variables de pénalité pondérées.
    """
    if gap_weight <= 0:
        return []

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    weighted_penalties: list[cp_model.IntVar] = []

    for group_id, session_ids in group_sessions.items():
        if len(session_ids) < 2:
            continue

        for week in range(weeks):
            for day in range(DAYS_PER_WEEK):
                day_base = week * slots_per_week + day * SLOTS_PER_DAY

                on_day: dict[str, cp_model.IntVar] = {}
                slot_vars: dict[str, cp_model.IntVar] = {}

                for sid in session_ids:
                    on_day[sid] = model.new_bool_var(f"on_{group_id}_{sid}_w{week}_d{day}")
                    slot_vars[sid] = model.new_int_var(0, SLOTS_PER_DAY - 1, f"slot_{sid}_w{week}_d{day}")

                    start = session_starts[sid]
                    _link_on_day(model, start, day_base, on_day[sid], slot_vars[sid])

                count_on_day = model.new_int_var(0, len(session_ids), f"cnt_{group_id}_w{week}_d{day}")
                model.add(count_on_day == sum(on_day[sid] for sid in session_ids))

                has_multiple = model.new_bool_var(f"multi_{group_id}_w{week}_d{day}")
                model.add(count_on_day >= 2).only_enforce_if(has_multiple)
                model.add(count_on_day <= 1).only_enforce_if(has_multiple.Not())

                min_slot = model.new_int_var(0, SLOTS_PER_DAY - 1, f"min_{group_id}_w{week}_d{day}")
                max_slot = model.new_int_var(0, SLOTS_PER_DAY - 1, f"max_{group_id}_w{week}_d{day}")

                for sid in session_ids:
                    model.add(min_slot <= slot_vars[sid]).only_enforce_if(on_day[sid])
                    model.add(max_slot >= slot_vars[sid]).only_enforce_if(on_day[sid])

                span = model.new_int_var(0, SLOTS_PER_DAY, f"span_{group_id}_w{week}_d{day}")
                model.add(span == max_slot - min_slot + 1).only_enforce_if(has_multiple)
                model.add(span == 0).only_enforce_if(has_multiple.Not())

                gap = model.new_int_var(0, SLOTS_PER_DAY, f"gap_{group_id}_w{week}_d{day}")
                model.add(gap == span - count_on_day).only_enforce_if(has_multiple)
                model.add(gap == 0).only_enforce_if(has_multiple.Not())

                weighted = model.new_int_var(0, SLOTS_PER_DAY * gap_weight, f"wgap_{group_id}_w{week}_d{day}")
                model.add(weighted == gap * gap_weight)
                weighted_penalties.append(weighted)

    return weighted_penalties


def add_avoid_zone_penalties(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weight: int,
) -> list[cp_model.IntVar]:
    """
    Pénalise les "zones à éviter, dernier recours" (cahier des charges §2) :
    lundi 8h00-9h30 (laisser le temps aux étudiants non-locaux d'arriver) et
    vendredi 17h00-18h30 (partir tôt en fin de semaine). Pas interdit dans
    l'absolu, juste déconseillé -> pénalité molle plutôt que contrainte dure.
    """
    if weight <= 0:
        return []

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    monday_first_slot = WeekDay.MONDAY.value * SLOTS_PER_DAY + TimeSlot.SLOT_08_0930.value
    friday_last_slot = WeekDay.FRIDAY.value * SLOTS_PER_DAY + TimeSlot.SLOT_17_1830.value

    penalties: list[cp_model.IntVar] = []
    for session in sessions:
        start = session_starts[session.id]
        slot_in_week = model.new_int_var(0, slots_per_week - 1, f"avoid_siw_{session.id}")
        model.add_modulo_equality(slot_in_week, start, slots_per_week)

        is_monday_early = model.new_bool_var(f"avoid_mon_{session.id}")
        model.add(slot_in_week == monday_first_slot).only_enforce_if(is_monday_early)
        model.add(slot_in_week != monday_first_slot).only_enforce_if(is_monday_early.Not())

        is_friday_late = model.new_bool_var(f"avoid_fri_{session.id}")
        model.add(slot_in_week == friday_last_slot).only_enforce_if(is_friday_late)
        model.add(slot_in_week != friday_last_slot).only_enforce_if(is_friday_late.Not())

        in_avoid_zone = model.new_bool_var(f"avoid_{session.id}")
        model.add_max_equality(in_avoid_zone, [is_monday_early, is_friday_late])

        pen = model.new_int_var(0, weight, f"avoid_pen_{session.id}")
        model.add(pen == weight).only_enforce_if(in_avoid_zone)
        model.add(pen == 0).only_enforce_if(in_avoid_zone.Not())
        penalties.append(pen)

    return penalties


def add_edge_slot_penalties(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    early_late_weight: int,
    late_afternoon_weight: int,
) -> list[cp_model.IntVar]:
    """
    Pénalité molle N'IMPORTE QUEL JOUR (contrairement à `add_avoid_zone_penalties`,
    limitée à lundi 8h/vendredi 17h) — retour utilisateur (07/08/2026, pour
    la 3e année) : "évitant au max les cours de 8h et de 17h [...] si on
    peut les faire finir à 15h30 c'est bien". Deux paliers :
    `early_late_weight` (8h-9h30 et 17h-18h30, préférence forte) et
    `late_afternoon_weight` (15h30-17h, préférence plus faible — objectif
    secondaire "si on peut"). L'appelant filtre déjà `sessions` à la
    population concernée (ex. `session.annee == "BUT3"`) : ne change rien
    pour les autres années.
    """
    if early_late_weight <= 0 and late_afternoon_weight <= 0:
        return []

    penalties: list[cp_model.IntVar] = []
    for session in sessions:
        start = session_starts[session.id]
        slot_in_day = model.new_int_var(0, SLOTS_PER_DAY - 1, f"edge_sid_{session.id}")
        model.add_modulo_equality(slot_in_day, start, SLOTS_PER_DAY)

        if early_late_weight > 0:
            is_early = model.new_bool_var(f"edge_early_{session.id}")
            model.add(slot_in_day == TimeSlot.SLOT_08_0930.value).only_enforce_if(is_early)
            model.add(slot_in_day != TimeSlot.SLOT_08_0930.value).only_enforce_if(is_early.Not())

            is_late = model.new_bool_var(f"edge_late_{session.id}")
            model.add(slot_in_day == TimeSlot.SLOT_17_1830.value).only_enforce_if(is_late)
            model.add(slot_in_day != TimeSlot.SLOT_17_1830.value).only_enforce_if(is_late.Not())

            in_edge = model.new_bool_var(f"edge_{session.id}")
            model.add_max_equality(in_edge, [is_early, is_late])

            pen = model.new_int_var(0, early_late_weight, f"edge_pen_{session.id}")
            model.add(pen == early_late_weight).only_enforce_if(in_edge)
            model.add(pen == 0).only_enforce_if(in_edge.Not())
            penalties.append(pen)

        if late_afternoon_weight > 0:
            is_late_afternoon = model.new_bool_var(f"edge_1530_{session.id}")
            model.add(slot_in_day == TimeSlot.SLOT_1530_17.value).only_enforce_if(is_late_afternoon)
            model.add(slot_in_day != TimeSlot.SLOT_1530_17.value).only_enforce_if(is_late_afternoon.Not())

            pen2 = model.new_int_var(0, late_afternoon_weight, f"edge_pen2_{session.id}")
            model.add(pen2 == late_afternoon_weight).only_enforce_if(is_late_afternoon)
            model.add(pen2 == 0).only_enforce_if(is_late_afternoon.Not())
            penalties.append(pen2)

    return penalties


def add_midday_fill_penalties(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weight: int,
) -> list[cp_model.IntVar]:
    """
    Priorité de remplissage : les créneaux proches de la pause méridienne
    (11h-12h30 et 14h-15h30, juste avant/après la pause) sont préférés aux
    créneaux d'extrémité de journée (8h et 17h). Objectif molle demandée pour
    éviter d'étaler les cours vers les extrémités quand le centre est libre.

    Distance au centre par créneau : 08h=2, 09h30=1, 11h=0, 14h=0, 15h30=1, 17h=2.
    """
    if weight <= 0:
        return []

    # index slot -> distance (0 = adjacent à la pause, 2 = extrémité de journée)
    distance_table = [2, 1, 0, 0, 1, 2]
    max_distance = max(distance_table)

    penalties: list[cp_model.IntVar] = []
    for session in sessions:
        start = session_starts[session.id]
        slot_var = model.new_int_var(0, SLOTS_PER_DAY - 1, f"midday_slot_{session.id}")
        model.add_modulo_equality(slot_var, start, SLOTS_PER_DAY)

        distance = model.new_int_var(0, max_distance, f"midday_dist_{session.id}")
        model.add_element(slot_var, distance_table, distance)

        pen = model.new_int_var(0, max_distance * weight, f"midday_pen_{session.id}")
        model.add(pen == distance * weight)
        penalties.append(pen)

    return penalties


def _link_on_day(
    model: cp_model.CpModel,
    start: cp_model.IntVar,
    day_base: int,
    on_day: cp_model.IntVar,
    slot_var: cp_model.IntVar,
) -> None:
    """on_day <=> start in [day_base, day_base + SLOTS_PER_DAY - 1]."""
    day_end = day_base + SLOTS_PER_DAY - 1

    model.add(start >= day_base).only_enforce_if(on_day)
    model.add(start <= day_end).only_enforce_if(on_day)

    before = model.new_bool_var(f"before_{on_day.name}")
    after = model.new_bool_var(f"after_{on_day.name}")
    model.add(start <= day_base - 1).only_enforce_if(before)
    model.add(start >= day_end + 1).only_enforce_if(after)
    model.add_bool_or([before, after]).only_enforce_if(on_day.Not())

    model.add(slot_var == start - day_base).only_enforce_if(on_day)
    model.add(slot_var == 0).only_enforce_if(on_day.Not())
