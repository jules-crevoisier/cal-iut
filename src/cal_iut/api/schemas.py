"""Schémas API FastAPI."""

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    parcours: str | None = None
    semestre: str | None = None
    # Run global multi-parcours (cf. cli.py::SEMESTRE_GROUPS) : "odd" (S1+S3+S5)
    # ou "even" (S2+S4+S6), ingère TOUS les parcours pour ce groupe de
    # semestres concurrents — prioritaire sur parcours/semestre si fourni.
    semestre_group: str | None = None


class SolveRequest(BaseModel):
    parcours: str | None = None
    semestre: str | None = None
    # cf. IngestRequest.semestre_group — doit correspondre au groupe utilisé
    # au dernier /ingest pour donner un résultat cohérent.
    semestre_group: str | None = None
    weeks: int | None = None  # None = calculé depuis le calendrier (cf. default_horizon_weeks)
    optimize_gaps: bool = False
    gap_weight: int = 100
    assign_rooms: bool = True
    # Mode par défaut = résolution en paliers (cf. docs/DATA.md §12.3 : 0/204
    # violations d'ordonnancement et moins de trous que la somme pondérée sur
    # données réelles BUT1-S1, à budget de temps identique). L'ancien mode
    # reste disponible comme filet de sécurité.
    legacy_weighted: bool = False
    # Mode décomposé (ordre -> semaine -> jour/créneau, cf. docs/DATA.md §14) :
    # recommandé pour un run BUT1-S1 complet (~1400 séances), plus fiable que
    # le modèle joint (paliers ou somme pondérée) sur une instance de cette
    # taille. Prioritaire sur `legacy_weighted` si les deux sont à True.
    decomposed: bool = False


class MoveSessionRequest(BaseModel):
    week: int = Field(ge=0)
    day: int = Field(ge=0, le=4)
    slot: int = Field(ge=0, le=5)
    room_id: str | None = None
    lock: bool = False
    force: bool = False


class SlotSuggestionResponse(BaseModel):
    week: int
    day: int
    slot: int
    label: str


class ValidationResponse(BaseModel):
    valid: bool
    hard_conflicts: list[str]
    soft_warnings: list[str]
    suggestions: list[SlotSuggestionResponse] = Field(default_factory=list)
    suggestions_note: str | None = None


class GroupMeta(BaseModel):
    id: str
    label: str
    parcours: str
    kind: str
    related_ids: list[str] = Field(default_factory=list)
    annee: str | None = None


class RoomMeta(BaseModel):
    id: str
    label: str
    capacity: int
    room_type: str


class YearMeta(BaseModel):
    """Année scolaire = 2 semestres (1→S1/S2, 2→S3/S4, 3→S5/S6)."""

    id: int
    label: str
    semestres: list[str]
    parcours: list[str]


class MetaResponse(BaseModel):
    groups: list[GroupMeta]
    rooms: list[RoomMeta]
    parcours: list[str]
    semestres: list[str]
    years: list[YearMeta] = Field(default_factory=list)


class PlacementResponse(BaseModel):
    session_id: str
    week: int
    day: int
    slot: int
    course_code: str
    course_name: str
    session_type: str
    group_ids: list[str]
    teacher_codes: list[str]
    room_id: str | None = None
    room_label: str | None = None
    is_eval: bool = False
    locked: bool = False


class QualityResponse(BaseModel):
    total_gaps: int
    isolated_days: int
    eval_days_with_multiple: int
    unbalanced_groups: list[str]
    gaps_by_group: dict[str, int]


class TimetableResponse(BaseModel):
    status: str
    objective_value: int | None
    gap_penalty: int
    placements: list[PlacementResponse]
    quality: QualityResponse | None = None
    run_id: int | None = None


class DiffEntryResponse(BaseModel):
    session_id: str
    course_code: str
    solver_week: int
    solver_day: int
    solver_slot: int
    current_week: int
    current_day: int
    current_slot: int
    changed: bool
    locked: bool


class DiffResponse(BaseModel):
    run_id: int | None
    total: int
    changed_count: int
    entries: list[DiffEntryResponse]


class FeedbackAnalysisResponse(BaseModel):
    patterns: list[str]
    suggestions: dict[str, int]
    top_courses: list[dict[str, object]]
    top_teachers: list[dict[str, object]]
    total_corrections: int


class WeightsResponse(BaseModel):
    weights: dict[str, int]
    reason: str | None = None


class ExceptionCreateRequest(BaseModel):
    kind: str  # "teacher_absence" | "room_unavailable"
    exception_date: str  # ISO "YYYY-MM-DD"
    teacher_code: str | None = None
    room_id: str | None = None
    slots: list[int] | None = None  # None = journée entière
    reason: str | None = None


class ExceptionResponse(BaseModel):
    id: int
    kind: str
    exception_date: str
    teacher_code: str | None = None
    room_id: str | None = None
    slots: list[int] | None = None
    reason: str | None = None
    active: bool = True


class RegenRequest(BaseModel):
    week: int = Field(ge=0)
    extend_next: bool = False


class RegenResultResponse(BaseModel):
    status: str
    touched_weeks: list[int]
    placements: list[PlacementResponse]
    message: str = ""
