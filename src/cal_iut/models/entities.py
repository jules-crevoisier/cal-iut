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


class TeacherWeekParityRule(BaseModel):
    """
    Indisponibilité qui ne s'applique qu'une semaine sur deux — ex. Thomas
    Castellengo (TCA) : « semaines paires : mercredi pas dispo, jeudi max 17h ;
    semaines impaires : lundi, mardi, vendredi max 17h ».

    `parity` porte sur le numéro de semaine DÉPARTEMENT par défaut (semaine 1 =
    ISO 35 2026, cf. `calendar/academic.py::department_week_number`), la
    référence retenue par l'utilisateur le 10/08/2026. Basculable en numéro ISO
    via `TeacherAvailability.parity_reference` (`"iso"`) sans toucher au code :
    la contrainte lit cette valeur à la résolution.
    """

    parity: Literal["paire", "impaire"]
    day: int  # 0 = lundi
    slots: list[int] = Field(default_factory=list)


class TeacherAvailability(BaseModel):
    """Disponibilités d'un enseignant (config externe + JSON contraintes)."""

    teacher_code: str
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list)
    preferred_slots: list[tuple[int, int]] = Field(default_factory=list)
    preferred_days: list[int] = Field(default_factory=list)
    # Liste blanche DURE : hors de ces (jour, créneau), l'enseignant n'est pas
    # plaçable du tout. Vide = aucune liste blanche, seules les
    # `forbidden_slots` s'appliquent. Arbitrage utilisateur du 10/08/2026 :
    # « les jours non listés en DISPONIBILITÉS sont interdits » — sans ça, un
    # enseignant comme VBU (aucune indisponibilité déclarée, mais disponible
    # seulement lundi/mardi/mercredi) restait plaçable les 5 jours.
    allowed_slots: list[tuple[int, int]] = Field(default_factory=list)
    # Liste blanche DURE de dates ISO : l'enseignant n'est plaçable QUE ces
    # jours-là de toute l'année (cas des vacataires, ex. Marc Nino et ses 10
    # dates). Vide = aucune restriction de ce type.
    allowed_dates: list[str] = Field(default_factory=list)
    week_parity_rules: list[TeacherWeekParityRule] = Field(default_factory=list)
    parity_reference: Literal["departement", "iso"] = "departement"
    # Nombre maximal de semaines distinctes par mois civil où l'enseignant
    # intervient — objectif MOU (ex. ARA : « regrouper ses cours sur une ou
    # deux semaines successives par mois »). None = pas de regroupement demandé.
    monthly_cluster_max_weeks: int | None = None
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

    `max_blocks` borne le nombre de blocs formés (None = autant que possible) :
    ex. WRA308M, 6 TD dont seuls "les 3 derniers à la suite" forment un bloc de
    4h30 — sans cette borne, les 6 TD produiraient 2 blocs de 4h30.

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/double_sessions.yaml`.
    """

    course_code: str
    session_type: SessionType
    slots_per_session: int = 2
    pair_from: Literal["start", "end"] = "start"
    max_blocks: int | None = None
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


class SessionDateWindowRule(BaseModel):
    """
    Fenêtre de dates CIVILES imposée à certaines séances d'un cours, ciblées
    par leur numéro d'ordre pédagogique — ex. WR100BU (« Jeu de piste BU »,
    Valérie Mariot) : le TD n°1 est la visite à la BU, à faire entre le 1er et
    le 15 septembre 2026 ; les TD n°2 et 3 (salle informatique) entre la 3e
    semaine de septembre et le 15 octobre.

    Comble un manque réel : jusqu'ici aucun mécanisme ne permettait de borner
    une séance PRÉCISE dans le calendrier (seul `CourseMinWeekRule` existait,
    au grain du cours entier et sans borne haute). Arbitrage utilisateur du
    10/08/2026 : contrainte DURE.

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/course_scheduling_rules.yaml`.
    """

    course_code: str
    semestre: str
    session_type: SessionType | None = None
    # Numéros d'ordre pédagogique visés (1-indexés, cf.
    # `SessionToPlace.sequence_order`). Vide = toutes les séances du cours.
    sequence_orders: list[int] = Field(default_factory=list)
    start_date: str | None = None  # ISO, borne incluse
    end_date: str | None = None  # ISO, borne incluse
    note: str | None = None


class CourseTeacherOrderRule(BaseModel):
    """
    Ordre SOUPLE entre les enseignants d'un même module — ex. WRA505C (Ariane
    Loizon) : « commencer essentiellement avec les créneaux d'ALO au début de
    la ressource, plutôt ceux d'AFR à la fin ».

    Traduit en pénalité sur la position MOYENNE des séances de chaque
    enseignant (même technique que `add_ordonnancement_constraints` en mode
    mou) : chaque enseignant du couple doit se dérouler globalement avant le
    suivant, sans exiger une séparation stricte qui entrerait en conflit avec
    leurs indisponibilités propres.

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/course_scheduling_rules.yaml`.
    """

    course_code: str
    semestre: str
    teacher_order: list[str]
    weight: int = 200
    note: str | None = None


class WeeklyCapException(BaseModel):
    """
    Dérogation PONCTUELLE et CIBLÉE au plafond horaire hebdomadaire (§3, 22
    créneaux FI / 23 FC, `add_weekly_hour_cap_constraints`) — relève le
    plafond pour UN parcours et UNE semaine civile précise seulement (jamais
    la valeur par défaut, qui reste inchangée partout ailleurs).

    Introduite le 14/08/2026 : un premier essai avait relevé la valeur par
    défaut GLOBALEMENT (22 -> 23 partout, toutes semaines, tous parcours FI)
    pour débloquer un cas réel (WR106, 1 seul enseignant pour tout le
    module, dernier TP repoussé après l'éval faute d'un créneau de marge
    cohorte) — mesuré ensuite sur un run complet réel que ce relevé global
    pousse l'étage 2 à exploiter la marge PARTOUT (61 paires
    cohorte/semaine poussées à la nouvelle limite au lieu de 14),
    dégradant la fiabilité du run entier au lieu de la seule semaine visée.
    Remplacé par cette dérogation ciblée : `week_monday` (lundi de la
    semaine civile concernée, jamais un index solveur brut — cohérent avec
    `SessionDateWindowRule`) est résolu en semaine-index solveur au chargement
    (`weekly_cap_exceptions_by_parcours_week`, `decomposed.py`), et
    n'affecte QUE ce (parcours, semaine) précis, dans `assign_weeks` comme
    dans `_rebalance_failed_weeks` (même valeur des deux côtés).

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/course_scheduling_rules.yaml`, avec l'autorisation
    utilisateur citée dans `note`.
    """

    parcours: str
    semestre: str
    week_monday: str  # ISO, lundi de la semaine civile concernée
    cap: int
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
