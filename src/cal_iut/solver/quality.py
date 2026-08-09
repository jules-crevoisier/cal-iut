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

    by_group_week_day: dict[str, dict[tuple[int, int], list[int]]] = defaultdict(lambda: defaultdict(list))
    sessions_per_day: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for p in placements:
        for gid in p.group_ids:
            by_group_week_day[gid][(p.week, p.day)].append(p.slot)
            sessions_per_day[gid][p.day] += 1

    gaps_by_group: dict[str, int] = {}
    total_gaps = 0

    for gid, week_days in by_group_week_day.items():
        group_gaps = 0
        for slots in week_days.values():
            unique_slots = sorted(set(slots))
            if len(unique_slots) < 2:
                continue
            span = unique_slots[-1] - unique_slots[0] + 1
            group_gaps += span - len(unique_slots)
        gaps_by_group[gid] = group_gaps
        total_gaps += group_gaps

    isolated_days = sum(
        sum(1 for count in day_counts.values() if count == 1)
        for day_counts in sessions_per_day.values()
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
