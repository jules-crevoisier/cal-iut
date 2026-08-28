"""Export planning hors Celcat (JSON + CSV).

Deux défauts corrigés le 26/08/2026, trouvés en explorant ce module :

1. **Aucune date.** L'export ne portait qu'un numéro de semaine interne : pour
   savoir QUAND avait lieu un cours, il fallait refaire soi-même la conversion.
   Un emploi du temps sans date n'est pas exploitable.
2. **Un numéro de semaine différent de celui de l'interface.** La colonne
   `week` valait `index_solveur + 1`, alors que l'interface et l'export HTML
   affichent le numéro de semaine DÉPARTEMENT (semaine 1 = ISO 35). L'index
   solveur 0 sortait en « semaine 1 » côté CSV et « Semaine 2 » côté web : deux
   exports du même planning se contredisaient d'une semaine.
"""

import csv
import io
from dataclasses import dataclass

from cal_iut.calendar.academic import AcademicCalendar, department_week_number
from cal_iut.models.timetable import TimeSlot

DAY_LABELS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")


@dataclass
class ExportRow:
    session_id: str
    course_code: str
    course_name: str
    session_type: str
    semestre: str
    parcours: str
    # Numéro de semaine DÉPARTEMENT — le même que celui affiché partout
    # ailleurs (interface, export HTML, `department_week_label`).
    week: int
    # Index interne du solveur, conservé pour rapprocher un export d'un run.
    semaine_solveur: int
    date: str
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


def build_export_rows(
    placements: list[object],
    sessions_by_id: dict[str, object],
    calendar: AcademicCalendar | None = None,
    week_offset: int = 0,
) -> list[ExportRow]:
    """`calendar` est facultatif pour ne pas casser les appelants existants,
    mais sans lui l'export ne peut porter ni date ni numéro de semaine réel —
    les colonnes correspondantes restent alors vides plutôt que fausses."""
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
                week=_departement_week(calendar, week_offset, p.week),
                semaine_solveur=p.week,
                date=_date_iso(calendar, week_offset, p.week, p.day),
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
    # Trié sur la DATE quand elle est connue : trier sur le libellé de jour
    # rangeait « Jeudi » avant « Lundi » (ordre alphabétique), ce qui rendait
    # le CSV illisible pour qui l'ouvre dans un tableur.
    return sorted(
        rows,
        key=lambda r: (r.semaine_solveur, _day_order(r.day), r.time_start, r.course_code),
    )


def _day_order(label: str) -> int:
    return DAY_LABELS.index(label) if label in DAY_LABELS else len(DAY_LABELS)


def _departement_week(calendar: AcademicCalendar | None, week_offset: int, week: int) -> int:
    if calendar is None:
        return week + 1
    absolu = week_offset + week
    if 0 <= absolu < len(calendar.teaching_mondays):
        return department_week_number(calendar.teaching_mondays[absolu])
    return week + 1


def _date_iso(calendar: AcademicCalendar | None, week_offset: int, week: int, day: int) -> str:
    if calendar is None:
        return ""
    d = calendar.week_day_to_date(week_offset + week, day)
    return d.isoformat() if d else ""


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
