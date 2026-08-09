"""Entités métier : cours, groupes, enseignants, salles."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SessionType(StrEnum):
    CM = "CM"
    TD = "TD"
    TP = "TP"
    PTUT = "PTUT"


class RoomType(StrEnum):
    """Types de salles réels, bâtiment H (IUT Troyes, dédié MMI)."""

    AMPHI = "amphi"  # H.018 — CM uniquement
    STANDARD = "standard"  # TD banalisées (H.101/104/105/111, H.007+H.008, H.201+H.203)
    TP_STANDARD = "tp_standard"  # TP classiques (H.005/006/007/008)
    TD_DESIGN = "td_design"  # H.009 — évier/peinture, priorité ALO/GLE
    TP_MAC = "tp_mac"  # H.016 — 6 postes Apple, pas de fenêtres, dernier recours
    STUDIO_AV = "studio_av"  # H.017 (+H.022 fantôme) — audiovisuel/duos synchronisés
    TP_ANGLAIS = "tp_anglais"  # H.103 — salle attitrée Thomas Pavie, tous parcours
    TP_VR_RESEAUX = "tp_vr_reseaux"  # H.205 — baie serveurs, VR, débordement H.201/203
    RESERVE = "reserve"  # H.001 — exclue des cours (usage BDE)
    EVALUATION = "evaluation"  # A.018 — salle d'évaluation dédiée, toute séance is_eval
    # Anciens types génériques conservés pour compat / règles héritées
    LABO_DEV = "labo_dev"
    STUDIO_CREA = "studio_crea"


class OrdonnancementPosition(StrEnum):
    BEFORE = "before"
    AFTER = "after"
    SAME = "same"


class Teacher(BaseModel):
    code: str
    nom: str
    prenom: str


class TeacherBlock(BaseModel):
    """Répartition horaire d'un enseignant sur une matière."""

    teacher: Teacher
    block: str
    cm: float = 0
    td: float = 0
    tp: float = 0
    ptut: float = 0
    nb_gp_td: int = Field(default=1, alias="nbGpTd")
    nb_gp_tp: int = Field(default=1, alias="nbGpTp")

    model_config = {"populate_by_name": True}


class Group(BaseModel):
    """Groupe d'étudiants (TD ou TP)."""

    id: str
    label: str
    parcours: str
    annee: str
    kind: str  # "td" | "tp" | "promo"
    tp_groups: list[str] = Field(default_factory=list)
    headcount: int = 30


class Room(BaseModel):
    id: str
    label: str
    capacity: int
    room_type: RoomType
    equipment: list[str] = Field(default_factory=list)


class SchedulingConstraint(BaseModel):
    """Contrainte d'ordonnancement inter-matières."""

    position: OrdonnancementPosition
    target_course_code: str
    target_course_name: str
    semestre: str


class Course(BaseModel):
    """Matière fusionnée maquette + progression."""

    code: str
    name: str
    semestre: str
    parcours: str
    annee: str
    filiere: str | None = None
    mode: str | None = None  # FI | FC
    codelement: str | None = None
    vet: str | None = None
    lead: Teacher
    profs: list[TeacherBlock]
    volumes: dict[str, float]
    groupes_td: int
    groupes_tp: int
    progression_defined: bool
    seance_sequence: list[dict[str, object]]
    ordonnancement: list[SchedulingConstraint]
    commentaire_edt: str | None = None
    bloque: bool = False
    hors_service: bool = False


class TeacherAvailability(BaseModel):
    """Disponibilités d'un enseignant (config externe + CSV contraintes)."""

    teacher_code: str
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list)
    preferred_slots: list[tuple[int, int]] = Field(default_factory=list)
    preferred_days: list[int] = Field(default_factory=list)
    max_afternoons_per_week: int | None = None
    notes: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DoubleSessionRule(BaseModel):
    """
    Déclare qu'un couple (cours, type de séance) doit être fusionné par paires
    consécutives (ordre pédagogique) en un seul bloc de plusieurs créneaux —
    ex. TP WR110 : 2×1h30 collées = 1 bloc de 3h (retour utilisateur : "les TP
    doivent être de 3h, il faut donc 2 séances de 1h30 collées" — annoncé
    comme récurrent sur d'autres cours/TP, d'où un mécanisme générique plutôt
    qu'un correctif ad hoc sur WR110 seul). Fusion faite à l'ingestion
    (`ingestion/normalize.py::_merge_double_sessions`) : le solveur ne voit
    plus qu'UNE séance avec `duration_slots=slots_per_session`.

    `pair_from` détermine depuis quelle extrémité la liste (triée par ordre
    pédagogique croissant) des séances de ce type est appariée par paires
    consécutives :
    - "start" (défaut) : paire (1ère, 2e), (3e, 4e)... reliquat impair en fin
      de liste (ex. TD WR104 : 5 séances -> 2 blocs de 3h + 1 séance seule).
    - "end" : paire depuis la fin, reliquat impair en DÉBUT de liste — pour
      viser spécifiquement les dernières occurrences sans toucher aux
      premières (ex. CM WR106 : CM1/CM2/CM3, seuls CM2+CM3 — l'éval de fin de
      semestre — doivent être collés en bloc de 3h ; CM1 doit rester seul).

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/double_sessions.yaml`.
    """

    course_code: str
    session_type: SessionType
    slots_per_session: int = 2
    pair_from: Literal["start", "end"] = "start"
    note: str | None = None


class TeacherCorrection(BaseModel):
    """
    Corrige l'enseignant d'un cours après fusion maquette+progression —
    `data/exports/maquette.json` est récupéré depuis une source distante
    (mmi23x02.mmi-troyes.fr, cf. `ingestion/fetch.py`) et donc écrasé à
    chaque `cal-iut fetch` : une correction déclarée ici (`ingestion/
    merge.py::apply_teacher_corrections`) SURVIT à un re-fetch, contrairement
    à un edit direct du JSON récupéré.

    `correct_teacher_code` doit déjà exister ailleurs dans le jeu de données
    (nom/prénom résolus par recoupement, jamais ressaisis à la main ici —
    évite un risque de faute de frappe sur l'identité).

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/course_corrections.yaml`.
    """

    course_code: str
    semestre: str
    parcours: str
    wrong_teacher_code: str
    correct_teacher_code: str
    note: str | None = None


class CourseMinWeekRule(BaseModel):
    """
    Interdit à un cours de démarrer avant la semaine-index `min_week` du
    solveur — ex. WR119 (PPP S1) ne doit pas commencer dès la rentrée (retour
    utilisateur, Kyllian Bresson, 04/08/2026) : "je préfère qu'ils aient le
    temps de passer quelques semaines à l'IUT avant que l'on aborde avec eux
    le PPP S1". `min_week` compte depuis le vrai démarrage des enseignements
    (semaine-index 1 pour S1, après la semaine d'intégration bloquée en
    semaine-index 0), pas depuis le tout début de l'année.

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/course_scheduling_rules.yaml`.
    """

    course_code: str
    semestre: str
    min_week: int
    note: str | None = None


class TeacherDuo(BaseModel):
    """
    Duo d'enseignants co-animant en simultané sur une salle rare dédoublée
    (ex. Studio H.017 + H.022 "hack Celcat") — cf.
    `distribution_modes.duo_synchronise_salle_rare` dans
    contraintes/01_regles_generales.json. Données jamais devinées : toujours
    saisies explicitement dans `data/config/teacher_duos.yaml`.
    """

    teacher_codes: tuple[str, str]
    course_codes: list[str]
    # Confirmé par l'utilisateur : seules les séances de TP sont synchronisées
    # (le Studio H.017/H.022 sert au tournage/montage en TP ; les TD peuvent
    # avoir lieu en salle classique, indépendamment pour chaque enseignant).
    session_types: list[str] = Field(default_factory=lambda: ["TP"])
    rare_rooms: tuple[str, str] = ("h017", "h022")
    # Force l'affectation groupe TP -> enseignant pour ce duo, en écrasant la
    # logique par défaut (curseur séquentiel sur les blocs `profs` de la
    # maquette, cf. `ingestion/normalize.py::_teacher_for_group`) — celle-ci
    # donne des paires synchronisées "boiteuses" (ex. KBR+KNG sur TD AB/CD
    # affectés A,B puis C,D => épisodes co-animés A&C puis B&D, qui ne
    # correspond à aucun regroupement TD naturel). Retour utilisateur
    # (Kyllian Bresson, TP WR110) : préférer un épisode co-animé "A&B" (visuel
    # cohérent avec TD AB), donc KBR=A,C / KNG=B,D plutôt que KBR=A,B / KNG=C,D
    # — clé = code enseignant, valeur = lettres de groupe TP (ex. ["A","C"]).
    group_overrides: dict[str, list[str]] | None = None
    note: str | None = None
