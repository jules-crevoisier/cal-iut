"""Schémas API FastAPI."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str


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


class ChangeRoomRequest(BaseModel):
    """Changement de salle SEULE, à créneau inchangé (`PATCH /placements/
    {id}/salle`) — retour utilisateur 28/08/2026 : « on va vouloir sur la vue
    promo modifier uniquement les salles »."""

    room_id: str
    force: bool = False


class CreateRoomRequest(BaseModel):
    """Salle ajoutée à la main (`POST /rooms`) — retour utilisateur
    28/08/2026 : « il se peut que l'on utilise des salles autres que dans le
    bâtiment ». L'`id` n'est pas demandé : il est dérivé du libellé côté
    serveur, une personne qui ajoute « Amphi Descartes » n'a pas à inventer
    un identifiant technique."""

    label: str = Field(min_length=1, max_length=80)
    capacity: int = Field(default=30, ge=1, le=1000)


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
    # Absent jusqu'au 27/08/2026 (retour utilisateur : « je vois des cours
    # WSA501D... mais ils ne sont pas en groupe de 3h ») — la Vue Semaine
    # (`TdWeekGrid.tsx`, la vue par défaut) construit sa grille depuis CETTE
    # réponse, pas depuis `/app-state` (qui, lui, porte déjà `dur`) : sans ce
    # champ, une séance de 3h (`duration_slots=2`, ex. WSA501D) n'occupait
    # visuellement qu'UN seul créneau de 1h30, jamais les deux.
    duration_slots: int = 1


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


class SeanceAPlacerResponse(BaseModel):
    """Une séance que le solveur n'a pas réussi à placer.

    Elle existe dans les séances à placer mais n'apparaît nulle part dans le
    planning : sans cet inventaire, elle disparaît purement et simplement — le
    planning a l'air complet alors qu'il manque des heures. Les libellés sont
    en clair : la personne qui reprendra ce travail l'an prochain n'a pas à
    savoir ce qu'est un `session_id`.
    """

    session_id: str
    course_code: str
    course_name: str
    session_type: str
    semestre: str
    parcours: str
    annee: str
    duration_slots: int
    duree_libelle: str
    group_ids: list[str]
    groupes_libelles: list[str]
    teacher_codes: list[str]
    enseignants_libelles: list[str]
    sequence_order: int | None = None
    semaines_possibles: list[int] = []
    raison: str = ""
    # Placée en forçant l'ordre pédagogique, pas encore validée — reste
    # listée ici plutôt que de disparaître silencieusement une fois posée
    # (retour utilisateur 28/08/2026 : « il faut le laisser dans la liste
    # pour peut-être revenir en arrière »). `None` = jamais placée du tout ;
    # rempli seulement si `placee_provisoirement` est vrai.
    placee_provisoirement: bool = False
    semaine_actuelle: int | None = None
    jour_actuel: int | None = None
    slot_actuel: int | None = None


class SeancesAPlacerResponse(BaseModel):
    total_a_placer: int
    total_placees: int
    manquantes: list[SeanceAPlacerResponse]
    par_parcours: dict[str, int] = {}
    resume: str = ""


class CreneauLibreResponse(BaseModel):
    week: int
    day: int
    slot: int
    label: str
    date: str = ""
    salle_label: str | None = None
    # Ce qui rend ce créneau meilleur ou moins bon qu'un autre, en clair.
    remarques: list[str] = []


class CreneauxLibresResponse(BaseModel):
    session_id: str
    creneaux: list[CreneauLibreResponse]
    note: str | None = None


class SeancePlaceeAutoResponse(BaseModel):
    session_id: str
    course_code: str
    week: int
    day: int
    slot: int
    date: str = ""


class SeanceRefuseeResponse(BaseModel):
    session_id: str
    course_code: str
    raison: str


class CompletionResponse(BaseModel):
    """Résultat du remplissage automatique du reliquat.

    Le rapport dit toujours ce qui n'a PAS pu être fait, et pourquoi. Un
    remplissage qui annoncerait seulement ses succès laisserait croire le
    planning complet — exactement le défaut qu'il est censé corriger.
    """

    placees: list[SeancePlaceeAutoResponse] = []
    refusees: list[SeanceRefuseeResponse] = []
    resume: str = ""


class TeacherMailPreviewResponse(BaseModel):
    """Une ligne de l'annuaire d'envoi — `email=None` : pas d'adresse connue
    dans `teacher_contacts.yaml`, cet enseignant ne peut pas être sélectionné
    à l'envoi (affiché quand même, pour que l'absence soit visible plutôt que
    silencieuse)."""

    code: str
    name: str
    email: str | None = None
    sent_at: str | None = None
    # Première ouverture détectée via le pixel de suivi. `None` ne prouve
    # PAS que le mail n'a pas été lu : beaucoup de clients mail bloquent
    # les images distantes par défaut (cf. `api/mailer.py::PIXEL_GIF`).
    opened_at: str | None = None


class TeacherMailPreviewListResponse(BaseModel):
    configured: bool
    teachers: list[TeacherMailPreviewResponse] = []


class SendTeacherMailsRequest(BaseModel):
    codes: list[str]


class TeacherMailSendResultResponse(BaseModel):
    code: str
    ok: bool
    error: str | None = None


class SendTeacherMailsResponse(BaseModel):
    results: list[TeacherMailSendResultResponse] = []


class ForcagePedagogiqueResponse(BaseModel):
    """Retour de `POST /placements/{id}/valider` — `etait_en_attente=False` =
    no-op (rien à valider, déjà validé ou jamais forcé)."""

    session_id: str
    etait_en_attente: bool


class CelcatEntreeResponse(BaseModel):
    session_id: str
    course_code: str
    semaine: int
    jour: int
    heure_debut: str
    heure_fin: str
    salle: str | None = None
    groupe: str = ""
    action: str  # "creer" | "modifier" | "inchangee" | "bloquee"
    bloquants: list[str] = []


class CelcatPlanResponse(BaseModel):
    """État de préparation de la saisie Celcat, SANS rien y avoir envoyé."""

    semaines: list[int] = []
    a_creer: int = 0
    a_modifier: int = 0
    a_supprimer: int = 0
    inchangees: int = 0
    bloquees: int = 0
    resume: str = ""
    # Motif -> nombre de séances concernées : c'est ce qui dit quoi
    # compléter dans `data/config/celcat.yaml` avant de pouvoir lancer.
    motifs_blocage: dict[str, int] = {}
    entrees: list[CelcatEntreeResponse] = []
    # Le pilote réel est-il utilisable (Playwright installé, URL renseignée) ?
    pilote_pret: bool = False
    pilote_message: str = ""
