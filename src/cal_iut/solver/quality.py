"""Indicateurs de qualité du planning."""

from collections import defaultdict
from dataclasses import dataclass

from cal_iut.models.timetable import TimeSlot, WeekDay
from cal_iut.solver.cpsat import PlacedSession


@dataclass
class QualityReport:
    total_gaps: int
    gaps_by_group: dict[str, int]
    sessions_per_day: dict[str, dict[int, int]]
    isolated_days: int
    eval_days_with_multiple: int
    unbalanced_groups: list[str]


def compute_quality(
    placements: list[PlacedSession],
    sessions_by_id: dict[str, object],
) -> QualityReport:
    from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY

    by_group_week_day: dict[str, dict[tuple[int, int], set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    sessions_per_day: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    # Nombre de séances par JOURNÉE RÉELLE (semaine, jour), distinct de
    # `sessions_per_day` qui agrège par jour de la semaine sur tout le semestre
    # (utilisé, lui, pour l'équilibre lundi/mardi/… d'un groupe).
    sessions_by_real_day: dict[str, dict[tuple[int, int], int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for p in placements:
        session = sessions_by_id.get(p.session_id)
        duration = max(1, int(getattr(session, "duration_slots", 1) or 1))
        for gid in p.group_ids:
            # Une séance de 3h occupe DEUX créneaux : ne compter que celui de
            # départ faisait apparaître un trou fantôme juste après chaque bloc
            # long. Bug réel trouvé le 26/08/2026 : un bloc aux créneaux 3-4
            # suivi d'une séance au créneau 5 — donc sans aucune interruption —
            # était compté comme 1 trou. Le nombre de trous est la mesure de
            # qualité principale du projet ET l'entrée de la boucle de
            # réapprentissage des poids (`feedback/weights.py`) : le fausser
            # fausse les deux.
            by_group_week_day[gid][(p.week, p.day)].update(range(p.slot, p.slot + duration))
            sessions_per_day[gid][p.day] += 1
            sessions_by_real_day[gid][(p.week, p.day)] += 1

    gaps_by_group: dict[str, int] = {}
    total_gaps = 0

    for gid, week_days in by_group_week_day.items():
        group_gaps = 0
        for slots in week_days.values():
            occupes = sorted(slots)
            if len(occupes) < 2:
                continue
            span = occupes[-1] - occupes[0] + 1
            group_gaps += span - len(occupes)
        gaps_by_group[gid] = group_gaps
        total_gaps += group_gaps

    # Journée isolée = une JOURNÉE PRÉCISE où un groupe n'a qu'un seul cours,
    # et doit donc se déplacer pour 1h30. Comptait auparavant les (groupe, jour
    # de la semaine) n'ayant qu'une séance sur TOUT le semestre — condition
    # quasi jamais remplie, la mesure valait donc toujours 0 et n'a jamais rien
    # signalé. Bug réel trouvé le 26/08/2026.
    isolated_days = sum(
        sum(1 for count in jours.values() if count == 1)
        for jours in sessions_by_real_day.values()
    )

    eval_slots_by_group: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for p in placements:
        session = sessions_by_id.get(p.session_id)
        if session and getattr(session, "is_eval", False):
            for gid in p.group_ids:
                eval_slots_by_group[gid].append((p.week, p.day))

    eval_days_with_multiple = 0
    for slots in eval_slots_by_group.values():
        day_counts: dict[tuple[int, int], int] = defaultdict(int)
        for week, day in slots:
            day_counts[(week, day)] += 1
        eval_days_with_multiple += sum(1 for c in day_counts.values() if c > 1)

    unbalanced = [
        gid
        for gid, day_counts in sessions_per_day.items()
        if day_counts and (max(day_counts.values()) - min(day_counts.values()) > 5)
    ]

    return QualityReport(
        total_gaps=total_gaps,
        gaps_by_group=gaps_by_group,
        sessions_per_day={k: dict(v) for k, v in sessions_per_day.items()},
        isolated_days=isolated_days,
        eval_days_with_multiple=eval_days_with_multiple,
        unbalanced_groups=unbalanced,
    )


def format_slot_label(slot: int) -> str:
    return TimeSlot(slot).label


def format_day_label(day: int) -> str:
    return WeekDay(day).name.capitalize()
