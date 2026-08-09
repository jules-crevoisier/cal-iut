"""Séance atomique à placer dans l'emploi du temps."""

from pydantic import BaseModel, Field

from cal_iut.models.entities import SessionType, Teacher
from cal_iut.models.timetable import TimeSlot, WeekDay


class SessionToPlace(BaseModel):
    """Unité élémentaire pour le solveur CP-SAT."""

    id: str
    course_code: str
    course_name: str
    semestre: str
    parcours: str
    annee: str
    session_type: SessionType
    sequence_order: int | None = None
    is_eval: bool = False
    group_ids: list[str]
    teacher_codes: list[str]
    teachers: list[Teacher] = Field(default_factory=list)
    duration_slots: int = 1
    locked: bool = False
    locked_day: WeekDay | None = None
    locked_slot: TimeSlot | None = None
    locked_room_id: str | None = None
    preferred_room_types: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
