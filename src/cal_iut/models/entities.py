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
    # Salle "fusion" virtuelle (H.007+H.008, H.201+H.203) — retour utilisateur
    # 28/08/2026 : deux salles collées, cloison ouvrable, réservables comme UNE
    # SEULE grande salle. `Room.combines` porte les salles individuelles
    # recouvertes ; cf. `solver/rooms.py::_build_conflict_map` pour le blocage
    # croisé (occuper la version fusionnée bloque chaque moitié, et
    # inversement — jamais l'inverse entre les deux moitiés elles-mêmes,
    # qui restent réservables indépendamment cloison fermée).
    COMBINED = "combined"
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
    # Salles individuelles recouvertes par CETTE salle si elle est une
    # fusion (`room_type == COMBINED`) — ex. h007_h008.combines = [h007, h008].
    # Vide sur une salle "normale". Cf. solver/rooms.py::_build_conflict_map.
    combines: list[str] = Field(default_factory=list)


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


class TeacherDateSlotRule(BaseModel):
    """Indisponibilité d'un enseignant à une DATE et un HORAIRE précis.

    Comble un manque réel (26/08/2026). Les quatre mécanismes existants sont
    soit récurrents (`forbidden_slots`, un créneau tous les jeudis), soit à la
    journée entière (`metadata["forbidden_dates"]`). Aucun ne savait dire
    « ce jeudi-là, de 9h30 à 12h30 ».

    Cas fondateur : la pré-rentrée BUT2 FC alternants du jeudi 3 septembre 2026,
    9h30-12h30, où Florent Libbrecht et Anthony Froli doivent être présents
    (demande de Kyllian Bresson). Bloquer leur journée entière les priverait de
    l'après-midi sans raison ; ne rien bloquer les laisserait programmables
    devant une autre promotion à cette heure-là — un blocage de parcours ne
    protège que les étudiants concernés, pas les enseignants.

    Donnée jamais devinée : toujours saisie explicitement dans
    `data/config/teacher_availability.yaml`.
    """

    date: str  # ISO (AAAA-MM-JJ)
    slots: list[int] = Field(default_factory=list)  # 0 = 8h-9h30 … 5 = 17h-18h30
    note: str | None = None


class TeacherAvailability(BaseModel):
    """Disponibilités d'un enseignant (config externe + JSON contraintes)."""

    teacher_code: str
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list)
    # ANNULE des (jour, créneau) autrement RECONDUITS depuis le JSON de
    # contraintes (`merge_teacher_availability` UNIT les deux sources — une
    # entrée YAML ne peut normalement que RESTREINDRE, jamais lever une
    # interdiction). Nécessaire quand la source brute (réponse d'enquête mal
    # analysée, ex. BTO : "mardi après-midi - mardi" lu comme un jour entier
    # en double, cf. teacher_availability.yaml) contredit une donnée plus
    # récente et plus fiable — sans ce champ, corriger l'enseignant en YAML
    # ne ferait qu'AJOUTER une contrainte de plus à celle, fausse, qui
    # persiste. Même logique de survie à la régénération que
    # `seances_annulees.yaml` : déclaré ici, ça ne revient jamais au prochain
    # `cal-iut fetch` + régénération de `contraintes/*.json`.
    cancelled_forbidden_slots: list[tuple[int, int]] = Field(default_factory=list)
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
    # Indisponibilités à une date ET un horaire précis (cf.
    # `TeacherDateSlotRule`) — le seul des cinq mécanismes qui sache dire
    # « ce jeudi-là, de 9h30 à 12h30 ».
    forbidden_date_slots: list[TeacherDateSlotRule] = Field(default_factory=list)
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


class CourseMaxWeekRule(BaseModel):
    """
    Symétrique de `CourseMinWeekRule` : interdit à un cours de DÉBORDER
    au-delà de la semaine-index `max_week` du solveur.

    Donnée jamais devinée. Cas fondateur (retour utilisateur du 25/08/2026) :
    WRA507D (BUT3-DEV-FC) s'étalait jusqu'au 8-12 mars 2027 sur le run
    `odd26`, alors que les ressources de ce parcours doivent se terminer
    « environ en janvier » — seule la SAE WSA501D a vocation à occuper les
    semaines de présence de février/mars.

    Contrainte DURE : contrairement au bornage global `fi_max_week` (qui vise
    un type de parcours), elle ne concerne qu'UN cours précis, ce qui la rend
    beaucoup moins susceptible de rendre l'instance infaisable — le volume
    déplacé reste petit et les autres cours du parcours gardent tout
    l'horizon.
    """

    course_code: str
    semestre: str
    max_week: int
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
    # Liste EXPLICITE de dates ISO admissibles, au lieu (ou en plus) d'une
    # plage continue. Nécessaire quand les jours autorisés sont épars et non
    # déductibles d'un intervalle — cas de la séance WRA505C que Ariane Loizon
    # veut animer EN MÊME TEMPS qu'une séance WS501D de Fabrice Meuzeret : les
    # jours possibles sont les jours de SAE WS501D qui sont aussi des jours de
    # présence IUT des alternants BUT3-CREACOM-FC, soit 6 dates isolées
    # réparties de fin novembre à début janvier.
    only_dates: list[str] = Field(default_factory=list)
    note: str | None = None


class TeacherDistributionRule(BaseModel):
    """
    Change la façon dont les séances d'un module sont RÉPARTIES entre ses
    enseignants, sans toucher aux volumes de la maquette.

    Par défaut (`sequentiel`, cf. `normalize.py::_teacher_for_group`), chaque
    enseignant prend un bloc CONTIGU : sur un module 17/17, le premier assure
    les 17 premières séances, le second les 17 dernières. C'est le bon modèle
    quand deux enseignants se relaient sur des parties distinctes du programme
    (WRA505C : Ariane Loizon au début, Anthony Froli à la fin).

    `alterne` fait tourner les enseignants séance après séance (A, B, A, B…)
    tout en respectant EXACTEMENT le volume de chacun : demandé le 25/08/2026
    pour WRA507D, où Jules Sabater vient de rejoindre Barthélémy Tomasina.
    Effet secondaire utile : un enseignant à disponibilité étroite (BTO n'est
    là que le mercredi et le jeudi matin) n'a plus à caser un bloc de 17
    séances consécutives dans une demi-période, mais une séance sur deux sur
    tout le semestre.

    Donnée jamais devinée : toujours saisie dans
    `data/config/course_scheduling_rules.yaml`.
    """

    course_code: str
    semestre: str
    mode: Literal["sequentiel", "alterne"] = "alterne"
    session_type: SessionType | None = None  # None = tous les types
    # Ordre de passage. Vide = ordre de la maquette (cf. `_blocks_for_type`).
    teacher_order: list[str] = Field(default_factory=list)
    note: str | None = None


class SaeTeacherPhase(BaseModel):
    """
    Fenêtre de dates pendant laquelle UN enseignant encadre effectivement une
    SAE — cf. `data/config/sae_teacher_phases.yaml`.

    Par défaut, tout enseignant listé sur une SAE est considéré indisponible
    sur TOUS les jours de cette SAE (`sae_supervisor_dates_by_teacher`). Sur une
    SAE longue où les enseignants se relaient, cette approximation coûte cher :
    Ariane Loizon se retrouvait bloquée sur les 22 jours de WS501D alors que son
    propre plan ne la fait intervenir qu'à partir de la mi-novembre.

    Déclarer des phases RESTREINT les jours retenus pour les enseignants cités ;
    un enseignant absent de la déclaration garde tous les jours (on ne libère
    jamais quelqu'un par omission).
    """

    course_code: str
    semestre: str
    teacher_code: str
    debut: str  # ISO, borne incluse
    fin: str  # ISO, borne incluse
    # Dates ISO retirées de la fenêtre : l'enseignant est bien sur la SAE
    # pendant la phase, sauf ces jours-là. Cas réel : Ariane Loizon anime,
    # sur un jour de WS501D, une séance de WRA505C avec les CREACOM pendant
    # que Fabrice Meuzeret tient les DEV — ce jour-là elle n'encadre donc pas
    # la SAE et doit rester plaçable.
    exclure: list[str] = Field(default_factory=list)
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
