"""État application + accès base de données."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from pathlib import Path

from cal_iut.calendar.academic import AcademicCalendar, build_default_calendar_2026_2027
from cal_iut.db.repository import PlanningRepository
from cal_iut.db.session import get_db, init_db_une_fois
from cal_iut.ingestion.constraints_loader import StudentPresence
from cal_iut.models.entities import Course, Group, Room, TeacherAvailability, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom, RoomAssignmentRule

# `data/state/` (pas `data/` directement) — sépare ce qui doit PERSISTER
# entre déploiements (cette base, cf. `data/state/.secret_key`, `mailer.py`,
# `forced_pending.py`) de `data/config/`, qui doit au contraire se mettre à
# jour à CHAQUE déploiement. Trouvé le 28/08/2026 : le volume Docker montait
# `/app/data` en entier, donc `data/config/teacher_contacts.yaml` restait
# figé sur son contenu du tout premier déploiement — aucune mise à jour
# ultérieure de la config ne pouvait plus jamais atteindre le conteneur
# (retour utilisateur : « on a les mails de tous les prof [...] alors que »
# le site déployé affichait encore "mail inconnu"). Cf. Dockerfile.
DB_PATH = Path(__file__).resolve().parents[3] / "data" / "state" / "cal-iut.db"


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
    # Erreur de la dernière restauration du planning au démarrage
    # (`main._try_restore_latest`) — `None` si elle a réussi. Lue par
    # `/health` (audit du 29/09/2026, P1-6) : un serveur qui démarre avec un
    # planning vide parce que la config ne se relit plus doit se voir.
    restauration_erreur: str | None = None


_state = AppState()

# ── Deux groupes de semestres chargés ensemble (16/11/2026) ────────────
#
# L'appli sert S1/S3/S5 (« odd ») et S2/S4/S6 (« even ») en même temps dès
# que les deux ont un planning en service. Chaque groupe garde SON état
# complet (séances, placements, run, semaines comptées depuis le début de
# SON semestre) : tout le code qui raisonne sur un seul semestre reste
# juste, il suffit de lui donner le bon état.
#
# `_state` reste l'état principal : celui du semestre en cours, servi à
# toute lecture qui ne demande rien (flux .ics, Celcat, tâches de fond).
# Les autres groupes sont dans `_secondaires`, et une requête en choisit un
# avec l'en-tête `X-Semestre-Groupe` (cf. `GroupeDeLaRequete`).
_secondaires: dict[str, AppState] = {}
_groupe_demande: ContextVar[str | None] = ContextVar("cal_iut_groupe_demande", default=None)

# Ce qui appartient à UN groupe. Tout le reste d'`AppState` (salles,
# groupes, calendrier, disponibilités, poids…) est commun, cf.
# `synchroniser_le_commun`.
CHAMPS_PAR_GROUPE = frozenset({
    "courses", "sessions", "sessions_by_id", "timetable", "corrections",
    "filter_parcours", "filter_semestre", "semestre_group", "current_run_id",
    "last_status", "last_objective_value", "last_gap_penalty", "restauration_erreur",
})


def get_state() -> AppState:
    demande = _groupe_demande.get()
    if demande:
        secondaire = _secondaires.get(demande)
        if secondaire is not None:
            return secondaire
    return _state


def etat_principal() -> AppState:
    return _state


def groupe_actif() -> str:
    """Le groupe secondaire que sert la requête en cours, « "" » pour l'état
    principal. Entre dans la clé de tous les caches par révision : la même
    lecture ne donne pas la même réponse d'un groupe à l'autre."""
    demande = _groupe_demande.get()
    return demande if demande and demande in _secondaires else ""


def etats_charges() -> list[AppState]:
    """L'état principal d'abord, puis les autres groupes en service."""
    return [_state, *_secondaires.values()]


def groupes_charges() -> list[str]:
    """Les groupes de semestres en service, celui du semestre en cours
    d'abord. Vide pour un planning historique d'un seul parcours."""
    principal = [_state.semestre_group] if _state.semestre_group else []
    return [*principal, *_secondaires]


def definir_secondaires(etats: dict[str, AppState]) -> None:
    _secondaires.clear()
    _secondaires.update(etats)


@contextmanager
def pour_le_groupe(groupe: str | None) -> Iterator[None]:
    """Sert `get_state()` depuis l'état de ce groupe le temps du bloc. Un
    groupe inconnu, ou celui de l'état principal, laisse l'état principal."""
    jeton = _groupe_demande.set((groupe or "").strip().lower() or None)
    try:
        yield
    finally:
        _groupe_demande.reset(jeton)


def synchroniser_le_commun(source: AppState | None = None) -> None:
    """Recopie ce qui est commun (salles, groupes, calendrier…) de `source`
    vers les autres états. Une écriture remplace ces listes sur l'état qui
    l'a reçue (`state.rooms = …`) ; sans cela, l'autre groupe garderait
    l'ancienne."""
    if not _secondaires:
        return
    source = source or get_state()
    for etat in etats_charges():
        if etat is source:
            continue
        for champ in fields(AppState):
            if champ.name not in CHAMPS_PAR_GROUPE:
                setattr(etat, champ.name, getattr(source, champ.name))


def get_repo() -> PlanningRepository:
    # Schéma préparé UNE fois par chemin (audit du 29/09/2026, P1-9) — avant,
    # chaque appel recréait un moteur et rejouait `create_all`. Le chemin
    # peut changer en cours de route (tests, `state.db_path`) : chaque
    # nouveau chemin est préparé à son premier usage.
    init_db_une_fois(_state.db_path)
    return PlanningRepository(get_db(_state.db_path))
