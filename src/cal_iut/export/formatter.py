"""Export planning hors Celcat (JSON + CSV)."""

import csv
import io
from dataclasses import dataclass

from cal_iut.models.timetable import TimeSlot, WeekDay


DAY_LABELS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")


@dataclass
class ExportRow:
    session_id: str
    course_code: str
    course_name: str
    session_type: str
    semestre: str
    parcours: str
    week: int
    day: str
    slot: str
    time_start: str
    time_end: str
    group_ids: str
    teacher_codes: str
    room_id: str | None
    room_label: str | None
    locked: bool
    is_eval: bool


SLOT_TIMES = [
    ("08:00", "09:30"),
    ("09:30", "11:00"),
    ("11:00", "12:30"),
    ("14:00", "15:30"),
    ("15:30", "17:00"),
    ("17:00", "18:30"),
]


def build_export_rows(placements: list[object], sessions_by_id: dict[str, object]) -> list[ExportRow]:
    rows: list[ExportRow] = []
    for p in placements:
        session = sessions_by_id.get(p.session_id)
        slot_idx = p.slot
        start, end = SLOT_TIMES[slot_idx] if 0 <= slot_idx < len(SLOT_TIMES) else ("?", "?")
        st = getattr(session, "session_type", None)
        session_type = st.value if st is not None else ""
        rows.append(
            ExportRow(
                session_id=p.session_id,
                course_code=p.course_code,
                course_name=getattr(session, "course_name", "") if session else "",
                session_type=session_type,
                semestre=getattr(session, "semestre", "") if session else "",
                parcours=getattr(session, "parcours", "") if session else "",
                week=p.week + 1,
                day=DAY_LABELS[p.day] if 0 <= p.day < 5 else "?",
                slot=TimeSlot(slot_idx).label if slot_idx < 6 else "?",
                time_start=start,
                time_end=end,
                group_ids=";".join(p.group_ids),
                teacher_codes=";".join(p.teacher_codes),
                room_id=getattr(p, "room_id", None),
                room_label=getattr(p, "room_label", None),
                locked=getattr(session, "locked", False) if session else False,
                is_eval=getattr(session, "is_eval", False) if session else False,
            )
        )
    return sorted(rows, key=lambda r: (r.week, r.day, r.time_start, r.course_code))


def to_csv(rows: list[ExportRow]) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    fieldnames = list(ExportRow.__dataclass_fields__.keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.__dict__)
    return buf.getvalue()


def to_json(rows: list[ExportRow]) -> list[dict[str, object]]:
    return [row.__dict__ for row in rows]
