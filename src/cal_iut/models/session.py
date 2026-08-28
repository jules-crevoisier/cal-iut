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

    @property
    def is_unplaced_sae(self) -> bool:
        """
        Séance de SAE que le solveur ne place PAS (le cas par défaut) : une SAE
        est organisée par ses enseignants, seules ses dates officielles servent
        à sanctuariser les cours classiques du parcours.

        Exception déclarée dans
        `data/config/course_scheduling_rules.yaml::solver_scheduled_sae` (ex.
        WSA501D, sans aucune date au fichier officiel) : ces séances-là sont
        marquées `metadata["solver_scheduled_sae"] = True` par
        `solve_decomposed` et redeviennent des séances ordinaires — soumises,
        comme les autres, à la sanctuarisation des jours des AUTRES SAE de leur
        parcours. Sans ce drapeau, le test « le code commence par WS » les en
        exemptait à tort.
        """
        if not self.course_code.upper().startswith("WS"):
            return False
        return not bool(self.metadata.get("solver_scheduled_sae"))
