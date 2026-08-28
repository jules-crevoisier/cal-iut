"""État application + accès base de données."""

from dataclasses import dataclass, field
from pathlib import Path

from cal_iut.calendar.academic import AcademicCalendar, build_default_calendar_2026_2027
from cal_iut.db.repository import PlanningRepository
from cal_iut.db.session import get_db, init_db
from cal_iut.ingestion.constraints_loader import StudentPresence
from cal_iut.models.entities import Course, Group, Room, TeacherAvailability, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom, RoomAssignmentRule

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "cal-iut.db"


@dataclass
class AppState:
    config_dir: Path = Path(".")
    db_path: Path = DB_PATH
    courses: list[Course] = field(default_factory=list)
    sessions: list[SessionToPlace] = field(default_factory=list)
    sessions_by_id: dict[str, SessionToPlace] = field(default_factory=dict)
    timetable: list[PlacedSessionWithRoom] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    room_rules: list[RoomAssignmentRule] = field(default_factory=list)
    # Salles réservées par des tiers (`data/config/salles_reservees.yaml`) —
    # {room_id: {index de créneau}}. Le solveur ne modélise pas les salles :
    # c'est l'attribution qui doit les éviter, jamais le modèle.
    room_reservations: dict[str, set[int]] = field(default_factory=dict)
    teacher_availability: list[TeacherAvailability] = field(default_factory=list)
    teacher_duos: list[TeacherDuo] = field(default_factory=list)
    calendar: AcademicCalendar = field(default_factory=build_default_calendar_2026_2027)
    student_presences: list[StudentPresence] = field(default_factory=list)
    objective_weights: dict[str, int] = field(default_factory=dict)
    corrections: list[dict[str, object]] = field(default_factory=list)
    filter_parcours: str | None = None
    filter_semestre: str | None = None
    # Run global multi-parcours (cf. ingestion/pipeline.py::SEMESTRE_GROUPS) :
    # "odd" (S1+S3+S5) ou "even" (S2+S4+S6), fixé par le dernier /ingest.
    semestre_group: str | None = None
    current_run_id: int | None = None
    # Dernier statut/objectif de résolution (`POST /solve`) — exposés par la
    # vraie interface web (`GET /`, cf. api/main.py) pour ne pas afficher
    # "CACHED"/None quand un run vient réellement de tourner.
    last_status: str | None = None
    last_objective_value: int | None = None
    last_gap_penalty: int = 0


_state = AppState()


def get_state() -> AppState:
    return _state


def get_repo() -> PlanningRepository:
    init_db(_state.db_path)
    return PlanningRepository(get_db(_state.db_path))
