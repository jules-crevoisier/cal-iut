"""API publique v1, en lecture seule — `/api/v1/...`.

Demande utilisateur (29/09/2026) : « une api entière pour exposer les
données et faire en sorte de limiter les connexions au serveur ». Jusqu'ici
un client externe (appli d'un collègue, script, agenda maison) n'avait que
`/app-state` — un bloc de 590 Ko aux clés abrégées (`w`, `d`, `s`, `c`...)
pensé pour l'écran React, pas pour être relu par quelqu'un d'autre — ou les
flux `.ics`.

Principes :

- MÊME authentification que le reste (`api/main.py::require_auth`, préfixe
  `/api` protégé) : cookie de compte, clé `Authorization: Bearer caliut_…`,
  ou lien personnel `?t=…`. Sans compte actif, la variante publique : pas
  d'adresse mail d'enseignant (cf. `_CLES_PRIVEES_PAYLOAD`).
- AUCUNE logique métier dupliquée : tout est relu depuis le payload de
  `/app-state` (mis en mémoire par révision, `main.payload_app_state`) et
  les fonctions existantes (`_filter_timetable`, `_to_placement`,
  `_date_iso`, calendrier...). Une règle corrigée là-bas l'est ici aussi.
- Chaque réponse porte un ETag dérivé de la révision de l'état
  (`api/revision.py`) : un client qui renvoie `If-None-Match` reçoit un 304
  vide tant que rien n'a changé, sans que le serveur ne recalcule quoi que
  ce soit. `GET /api/v1/version` est fait pour être sondé.
- Noms de champs en français, dates ISO (`AAAA-MM-JJ`), horaires lisibles
  (`"08:00"`) EN PLUS des index jour/créneau/semaine que manipulent les
  autres routes — un client n'a jamais à recalculer une date lui-même.

Trois numérotations de semaines coexistent dans le projet, d'où des noms
explicites : `semaine` = index SOLVEUR (0, 1, 2... sans trou, celui des
autres routes), `numero` = « Semaine N » du département, `semaine_iso` =
semaine calendaire ISO.

Complément du 29/09/2026 (« niveau API on est bon ? on peut exposer toutes
les infos et documenter ») : tout ce que montrent les écrans est lisible ici
— séances non placées, « À traiter », doublons, contraintes, charges,
modifications manuelles, tâches, calendrier, état Celcat (admin). Les vues
que le frontend CALCULE lui-même (« À traiter », annuaires) sont portées dans
`api/v1_vues.py`. Droits : ceux de l'écran correspondant — doublons réservés
au rôle `edit` (comme `GET /controles/doublons`), Celcat à `admin`. Jamais de
compte, d'adresse de compte (`cree_par` d'une tâche), de clé, de secret ni de
chemin disque. Schéma OpenAPI limité à v1 : `/api/v1/openapi.json`, page
interactive `/api/v1/docs` (mêmes droits que le reste de v1).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from cal_iut.api import accounts, cache_http, limiteur, reference, revision
from cal_iut.api import v1_vues as vues
from cal_iut.api.reference import ManquesV1

# Plafond de débit de l'API v1 (audit du 29/09/2026, P1-3 : le limiteur ne
# couvrait que l'authentification). Large : l'interface web ne sonde que
# `/version` (toutes les 30 s par onglet), un client bien écrit fait de même
# avec `If-None-Match`. Il ne freine qu'un script qui boucle sans pause. Par
# COMPTE (cookie ou clé API) — derrière un proxy mal réglé, tout le monde
# partagerait une IP ; par IP pour un lien public, qui ne lit que `/version`
# (quelques octets, déjà en cache) — d'où un plafond bien plus large : toute
# une salle d'étudiants derrière la même adresse sonde toutes les 3 min.
LIMITE_V1 = (600, 60.0)
LIMITE_V1_LIEN_PUBLIC = (3000, 60.0)


def _limiter_v1(request: Request) -> None:
    user = getattr(request.state, "user", None)
    if user is not None:
        qui, limite = f"compte:{user.id}", LIMITE_V1
    else:
        qui, limite = f"ip:{limiteur.ip_cliente(request)}", LIMITE_V1_LIEN_PUBLIC
    try:
        limiteur.limiteur.verifier(f"api-v1:{qui}", *limite)
    except HTTPException as exc:
        raise HTTPException(
            429,
            f"Trop de requêtes sur l'API v1 (plus de {limite[0]} par minute). "
            "Sondez `/api/v1/version` avec `If-None-Match` plutôt que les données.",
            headers=exc.headers,
        ) from None


_REPONSES_COMMUNES: dict[int | str, dict] = {
    304: {"description": "Rien n'a changé depuis l'ETag envoyé dans `If-None-Match` (corps vide)."},
    401: {"description": "Ni cookie de compte ni clé `Authorization: Bearer caliut_…` valide."},
    403: {"description": "Compte en attente d'activation, ou rôle insuffisant pour cet endpoint."},
    429: {"description": "Plafond de débit dépassé (en-tête `Retry-After`)."},
}

router = APIRouter(prefix="/api/v1", dependencies=[Depends(_limiter_v1)], responses=_REPONSES_COMMUNES)

_TAGS_ETAT = ["v1 · état"]
_TAGS_REFERENTIEL = ["v1 · référentiel"]
_TAGS_SEANCES = ["v1 · séances"]
_TAGS_SALLES = ["v1 · salles"]
_TAGS_CALENDRIER = ["v1 · calendrier"]
_TAGS_CONTROLES = ["v1 · contrôles"]
_TAGS_SUIVI = ["v1 · suivi"]
_TAGS_STATISTIQUES = ["v1 · statistiques"]
_TAGS_ADMIN = ["v1 · administration"]
_TAGS_SAE = ["v1 · SAE"]

# Descriptions des sections de la doc interactive (`/api/v1/docs`).
OPENAPI_TAGS = [
    {"name": "v1 · état", "description": "Révision de l'état (à sonder) et export complet en un appel."},
    {"name": "v1 · référentiel", "description": "Semaines, créneaux, enseignants, groupes, cours, parcours."},
    {"name": "v1 · séances", "description": "Séances placées (filtrables) et séances restant à placer."},
    {"name": "v1 · salles", "description": "Catalogue des salles et salles libres à un créneau."},
    {"name": "v1 · SAE", "description": "Situations d'apprentissage et d'évaluation : maquette, encadrants, "
     "jours réservés, séances placées et non placées."},
    {"name": "v1 · calendrier", "description": "Jours fériés, vacances, évènements, jours SAE, réservations de salles."},
    {"name": "v1 · contrôles", "description": "Écran « À traiter », doublons, contraintes et leur verdict, données à compléter."},
    {"name": "v1 · suivi", "description": "Modifications manuelles depuis la génération, tâches de l'équipe."},
    {"name": "v1 · statistiques", "description": "Charges : heures par enseignant, groupe, cours, parcours ; occupation des salles."},
    {"name": "v1 · administration", "description": "État de la synchronisation Celcat (comptes admin)."},
]


def _exemple(contenu: object) -> dict[int | str, dict]:
    """Exemple de réponse 200 affiché dans la doc interactive."""
    return {200: {"content": {"application/json": {"example": contenu}}}}

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")


def est_sae(code: str) -> bool:
    """Une SAE = un code de module `WS…` — même règle que le solveur, l'audit,
    `/placements/manquantes` et le payload de l'écran (`startswith("WS")`)."""
    return (code or "").upper().startswith("WS")


def _journees_sae_par_parcours() -> dict[str | None, dict[str, list[str]]]:
    """parcours → {date ISO → codes des SAE} : les journées SAE, dépliées des
    PÉRIODES SAE (`ics_feed.periodes_sae`, la source des évènements journée
    entière des flux .ics). Clé `None` : SAE dont le parcours est introuvable,
    qui concerne alors tous les parcours (même règle que le .ics)."""
    sortie: dict[str | None, dict[str, list[str]]] = {}
    for periode in _config_sae()["periodes"]:
        jours = sortie.setdefault(periode["parcours"], {})
        for jour in periode["jours"]:
            codes = jours.setdefault(jour.isoformat(), [])
            if periode["code"] not in codes:
                codes.append(periode["code"])
    return sortie


def _dans_journee_sae(journees: dict, parcours: str, date_iso: str | None) -> bool:
    return bool(date_iso) and (date_iso in journees.get(parcours, {}) or date_iso in journees.get(None, {}))

# Cache dédié : une entrée par (chemin, paramètres, variante) — plus de
# combinaisons possibles que les routes historiques, d'où une borne à part.
_cache_v1 = cache_http.CacheParRevision(taille_max=512)


# ── Modèles de réponse ──────────────────────────────────────────────────


class VersionV1(BaseModel):
    revision: int = Field(description="Entier croissant, avance à chaque modification visible.")
    modifie_le: str = Field(description="Horodatage ISO 8601 (UTC) de la dernière avance.")


class JourV1(BaseModel):
    index: int
    nom: str


class CreneauV1(BaseModel):
    index: int
    debut: str
    fin: str
    libelle: str


class CreneauxV1(BaseModel):
    jours: list[JourV1]
    creneaux: list[CreneauV1]


class SemaineV1(BaseModel):
    semaine: int | None = Field(description="Index solveur ; `null` pour une semaine bloquée (vacances).")
    numero: int = Field(description="Numéro « Semaine N » du département.")
    semaine_iso: int
    lundi: str
    libelle: str
    bloquee: bool
    statut: Literal["passee", "en_cours", "future"]


class EnseignantV1(BaseModel):
    code: str
    nom: str
    email: str | None = Field(default=None, description="Uniquement pour un compte connecté.")
    nb_seances: int


class GroupeV1(BaseModel):
    id: str
    libelle: str
    parcours: str
    annee: str
    type: str = Field(description="`promo`, `td` ou `tp`.")
    groupes_lies: list[str] = Field(description="TP d'un TD, ou TD parent d'un TP (sans la promo).")
    cohorte: list[str] = Field(description="Tous les groupes dont les séances concernent ce groupe.")


class SalleV1(BaseModel):
    id: str
    libelle: str
    capacite: int
    type: str
    equipements: list[str]
    placement_auto: bool
    fusionne: list[str] = Field(description="Salles recouvertes si c'est une salle fusionnée, vide sinon.")
    nb_seances: int


class OrdonnancementV1(BaseModel):
    position: str = Field(description="Position relative déclarée dans la maquette : `before`, `same` ou `after`.")
    cible: str = Field(description="Code du cours de référence.")


class CoursV1(BaseModel):
    code: str
    nom: str
    semestre: str
    parcours: str
    nb_cm: int
    nb_td: int
    nb_tp: int
    nb_evaluations: int
    nb_placees: int
    enseignants: list[str]
    progression_definie: bool = Field(description="Vrai si la maquette fixe un ordre des séances (`ordre`).")
    sae: bool = Field(description="Situation d'apprentissage et d'évaluation (code `WS…`), cf. `/api/v1/sae`.")
    ordonnancement: list[OrdonnancementV1] = Field(description="Contraintes d'ordre entre ce cours et d'autres.")


class ParcoursV1(BaseModel):
    id: str
    annee: int | None
    semestres: list[str]
    groupes: list[str]


class SeanceV1(BaseModel):
    id: str
    cours_code: str
    cours_nom: str
    type: str
    parcours: str
    semestre: str
    groupes: list[str]
    groupes_libelles: list[str]
    enseignants: list[str]
    enseignants_noms: list[str]
    salle_id: str | None
    salle_libelle: str | None
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    jour_nom: str
    creneau: int
    duree_creneaux: int
    debut: str
    fin: str
    horaire_libre: bool = Field(description="Vrai si `debut`/`fin` viennent d'un horaire hors des 6 créneaux.")
    evaluation: bool
    verrouillee: bool
    personnalisee: bool
    evenement: bool = Field(description="Évènement hors maquette (réunion, conférence…) créé depuis l'interface.")
    sae: bool = Field(description="Séance d'une SAE (code `WS…`).")
    dans_journee_sae: bool | None = Field(
        default=None,
        description="Pour une séance de SAE : tombe-t-elle sur une journée SAE de son parcours ? "
        "`null` pour une séance qui n'est pas une SAE. Cf. `/api/v1/sae`.",
    )


class SeancesV1(BaseModel):
    total: int
    decalage: int
    limite: int | None
    seances: list[SeanceV1]


class OccupationV1(BaseModel):
    salle_id: str
    motif: Literal["seance", "reservation", "salle_liee"]
    seance_id: str | None = None
    cours_code: str | None = None
    detail: str | None = None


class SallesLibresV1(BaseModel):
    semaine: int
    jour: int
    creneau: int
    date: str | None
    libres: list[SalleV1]
    occupees: list[OccupationV1]


class EnseignantDetailV1(EnseignantV1):
    cours: list[str]


class EtapeProgressionV1(BaseModel):
    seance_id: str
    ordre: int | None = Field(description="Rang dans la progression de la maquette (`null` si non défini).")
    type: str
    semestre: str
    parcours: str
    groupes: list[str]
    enseignants: list[str]
    duree_creneaux: int
    evaluation: bool
    placee: bool
    semaine: int | None
    date: str | None
    debut: str | None


class CoursDetailV1(BaseModel):
    code: str
    nom: str
    declinaisons: list[CoursV1]
    progression: list[EtapeProgressionV1] = Field(
        description="Toutes les séances de la maquette, dans l'ordre pédagogique, placées ou non."
    )


class SeanceNonPlaceeV1(BaseModel):
    id: str
    cours_code: str
    cours_nom: str
    type: str
    semestre: str
    parcours: str
    annee: str
    duree_creneaux: int
    duree_libelle: str
    groupes: list[str]
    groupes_libelles: list[str]
    enseignants: list[str]
    enseignants_noms: list[str]
    ordre: int | None = Field(description="Rang dans la progression de la maquette.")
    semaines_possibles: list[int] = Field(description="Index solveur des semaines où l'ordre pédagogique l'autorise.")
    raison: str = Field(description="Pourquoi elle n'a pas pu être placée, en clair.")
    placee_provisoirement: bool = Field(
        description="Posée en forçant l'ordre pédagogique, en attente de validation (`semaine_actuelle`…)."
    )
    semaine_actuelle: int | None = None
    jour_actuel: int | None = None
    creneau_actuel: int | None = None
    sae: bool = Field(default=False, description="Séance d'une SAE (code `WS…`).")
    statut: Literal["a_placer", "en_attente_validation", "hors_solveur"] = Field(
        default="a_placer",
        description="`hors_solveur` : séance de SAE que la génération ne place pas (organisée par ses "
        "enseignants sur les jours réservés) — listée seulement avec `inclure_sae=true`.",
    )


class SeancesNonPlaceesV1(BaseModel):
    total: int = Field(description="Séances listées (après filtres).")
    total_a_placer: int = Field(description="Toutes les séances de la maquette.")
    total_placees: int
    par_parcours: dict[str, int]
    resume: str
    seances: list[SeanceNonPlaceeV1]


class NatureATraiterV1(BaseModel):
    id: Literal["non-placee", "sans-salle", "doublon", "regle", "contrainte", "sae-hors-journee", "compromis-sae", "trouee"]
    titre: str
    gravite: Literal["a_corriger", "a_revoir"]
    aide: str
    nombre: int = Field(description="Occurrences de cette nature (après filtres).")


class PointATraiterV1(BaseModel):
    nature: str
    gravite: Literal["a_corriger", "a_revoir"]
    cle: str = Field(description="Identifiant stable du point (d'une révision à l'autre).")
    titre: str
    detail: str
    semaine: int | None = Field(description="Index solveur ; `null` pour un point sans semaine (non placée, règle).")
    numero_semaine: int | None
    date: str | None
    jour: int | None
    jour_nom: str | None
    creneau: int | None
    debut: str | None
    parcours: list[str]
    enseignants: list[str] = Field(description="Codes enseignants (jamais des noms).")
    nombre: int = Field(description="Occurrences regroupées sur ce point (« ×5 » à l'écran).")
    seance_id: str | None = None
    seances: list[str] = Field(default_factory=list, description="Séances en conflit (doublons).")
    groupe: str | None = None
    regle: str | None = None
    motif: str | None = None
    type_doublon: Literal["salle", "enseignant"] | None = None


class ATraiterV1(BaseModel):
    total: int = Field(description="Occurrences, tous points confondus (après filtres).")
    a_corriger: int
    a_revoir: int
    doublons_inclus: bool = Field(description="Faux pour un compte en lecture seule (doublons réservés au rôle `edit`).")
    natures: list[NatureATraiterV1]
    points: list[PointATraiterV1]


class DoublonSeanceV1(BaseModel):
    seance_id: str
    cours_code: str
    groupes: list[str]
    salle: str | None
    enseignants: list[str]


class DoublonV1(BaseModel):
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    jour_nom: str
    creneau: int
    debut: str
    fin: str
    type: Literal["salle", "enseignant"]
    ressource: str = Field(description="Nom de l'enseignant, ou salle(s) — « H.201 / H.203 » pour deux salles liées.")
    seances: list[DoublonSeanceV1]


class DoublonsV1(BaseModel):
    total: int
    doublons: list[DoublonV1]


class RegleV1(BaseModel):
    id: str
    libelle: str
    statut: Literal["respectee", "echec"]
    detail: str


class EcartV1(BaseModel):
    nature: Literal["indisponibilite", "compromis_sae"] = Field(
        description="`indisponibilite` = indisponibilité déclarée non respectée ; `compromis_sae` = l'enseignant "
        "encadre une SAE le même jour (compromis accepté)."
    )
    motif: str | None = Field(description="`creneau_interdit`, `hors_liste_blanche`, `date_declaree`, "
                                          "`encadrement_sae` ou `hors_dates_de_venue`.")
    cours_code: str
    semaine: int | None
    numero_semaine: int | None
    date: str | None
    jour: int | None
    creneau: int | None = Field(description="Renseigné pour un créneau récurrent interdit, `null` pour une date.")


class CreneauInterditV1(BaseModel):
    jour: int
    creneau: int


class ExceptionV1(BaseModel):
    id: int
    type: str = Field(description="`absence_enseignant` ou `salle_indisponible`.")
    date: str
    enseignant: str | None
    salle_id: str | None
    creneaux: list[int] | None = Field(description="`null` = journée entière.")
    motif: str | None


class ContraintesEnseignantV1(BaseModel):
    code: str
    nom: str
    contrainte_declaree: bool
    indisponibilites: str = Field(description="Texte déclaré par l'enseignant, tel quel.")
    disponibilites: str
    remarques: str
    creneaux_interdits: list[CreneauInterditV1]
    dates_interdites: list[str]
    nb_seances: int
    verdict: Literal["ecarts", "compromis_sae", "respectee", "aucune"] = Field(
        description="Même verdict que l'écran Contraintes : `ecarts` dès qu'une indisponibilité n'est pas "
        "respectée, `compromis_sae` s'il n'y a que des compromis SAE, `respectee`, ou `aucune` contrainte."
    )
    nb_ecarts: int
    nb_compromis_sae: int
    ecarts: list[EcartV1]
    exceptions: list[ExceptionV1] = Field(description="Absences ponctuelles saisies dans l'appli.")


class ContraintesV1(BaseModel):
    regles: list[RegleV1]
    enseignants: list[ContraintesEnseignantV1]
    exceptions: list[ExceptionV1] = Field(description="Absences d'enseignants et salles indisponibles (actives).")


class ChargeEnseignantV1(BaseModel):
    code: str
    nom: str
    heures_semaine: float | None = Field(description="Heures de la semaine demandée (`null` sans `semaine=`).")
    heures_semestre: float
    heures_par_semaine: dict[int, float] = Field(description="Index solveur → heures (semaines non vides).")
    nb_seances: int
    nb_matieres: int
    nb_non_placees: int
    contrainte: Literal["aucune", "respectee", "compromis_sae", "ecarts"]
    nb_ecarts: int


class ChargeGroupeV1(BaseModel):
    id: str
    libelle: str
    parcours: str
    type: str
    fc: bool
    heures_semaine: float | None
    heures_semestre: float
    heures_par_semaine: dict[int, float]


class ChargeCoursV1(BaseModel):
    code: str
    nom: str
    parcours: str
    semestre: str
    prevues: int = Field(description="Séances prévues par la maquette (CM + TD + TP + évaluations).")
    placees: int
    non_placees: int
    heures_semaine: float | None
    heures_placees: float
    heures_par_semaine: dict[int, float]
    enseignants: list[str]


class ChargeSalleV1(BaseModel):
    id: str
    libelle: str
    capacite: int
    type: str
    placement_auto: bool
    creneaux_occupes: int | None = Field(description="Créneaux occupés de la semaine demandée, sur 30.")
    taux: float | None = Field(description="`creneaux_occupes / 30`, de 0 à 1.")
    creneaux_par_semaine: dict[int, int]
    seances_semestre: int


class ChargeParcoursV1(BaseModel):
    id: str
    nb_seances: int
    heures_semaine: float | None
    heures_semestre: float
    heures_par_semaine: dict[int, float]


class ChargesV1(BaseModel):
    semaine: int | None
    heures_par_creneau: float = Field(description="Un créneau = 1,5 h (un bloc de 3 h compte 2 créneaux).")
    creneaux_par_semaine: int
    enseignants: list[ChargeEnseignantV1]
    groupes: list[ChargeGroupeV1]
    cours: list[ChargeCoursV1]
    salles: list[ChargeSalleV1]
    parcours: list[ChargeParcoursV1]


class PositionV1(BaseModel):
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    jour_nom: str
    creneau: int
    debut: str


class ModificationV1(BaseModel):
    seance_id: str
    cours_code: str
    cours_nom: str
    generation: PositionV1 = Field(description="Où la génération automatique l'avait placée.")
    actuelle: PositionV1 = Field(description="Où elle est aujourd'hui.")
    verrouillee: bool


class ModificationsV1(BaseModel):
    total_suivies: int = Field(description="Séances issues de la génération, déplacées ou non.")
    nb_modifiees: int
    modifications: list[ModificationV1]


class TacheV1(BaseModel):
    id: int
    titre: str
    description: str | None
    colonne: str = Field(description="`a_faire`, `en_cours` ou `fait`.")
    ordre: float
    enseignant: str | None = Field(description="Code de l'enseignant concerné, s'il y en a un.")
    concerne: str | None = Field(description="À qui la carte est attribuée (prénom libre).")
    categorie: Literal["edt", "plateforme"]
    priorite: Literal["normale", "urgente"]
    date_debut: str | None
    date_fin: str | None
    cree_le: str
    maj_le: str
    fait_le: str | None


class JourSansCoursV1(BaseModel):
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    type: Literal["ferie", "vacances"]
    libelle: str


class EvenementJourV1(BaseModel):
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    libelles: list[str]


class EvenementCreneauV1(BaseModel):
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    creneau: int
    debut: str
    fin: str
    libelle: str
    parcours: list[str]
    salle: str | None


class JourSaeV1(BaseModel):
    semaine: int
    numero_semaine: int | None
    date: str | None
    jour: int
    parcours: str
    cours: list[str]


class ReservationSalleV1(BaseModel):
    salle_id: str
    date: str
    semaine: int | None
    jour: int | None
    creneaux: list[int]
    motif: str


class PeriodeInstitutionnelleV1(BaseModel):
    libelle: str
    debut: str
    fin: str
    type: str = Field(description="`vacances`, `ferie`, `rentree` ou `special`.")


class CalendrierV1(BaseModel):
    jours_sans_cours: list[JourSansCoursV1] = Field(description="Jours fériés et de vacances tombant en semaine de cours.")
    evenements_jour: list[EvenementJourV1] = Field(description="Évènements du planning du département, à la journée.")
    evenements_creneau: list[EvenementCreneauV1] = Field(description="Évènements du planning, sur un créneau.")
    jours_sae: list[JourSaeV1] = Field(description="Jours réservés aux SAE, par parcours.")
    reservations_salles: list[ReservationSalleV1] = Field(description="Salles réservées par des tiers.")
    periodes_institutionnelles: list[PeriodeInstitutionnelleV1] = Field(
        description="Calendrier de l'université (non filtré par semaine)."
    )


class CelcatCompteursV1(BaseModel):
    creees: int
    modifiees: int
    supprimees: int
    bloquees: int


class CelcatFileV1(BaseModel):
    en_attente: int
    par_action: dict[str, int]
    dernier_passage_le: str | None
    age_secondes: float | None
    reussis: int
    echecs: int
    ignores: int
    differes: int = Field(description="Jobs qui attendent qu'une semaine soit ouverte dans Celcat.")
    resume: str


class CelcatEtatV1(BaseModel):
    saisie_active: bool
    worker_actif: bool = Field(description="Le worker est-il en marche (pas en pause volontaire) ?")
    worker_ok: bool = Field(description="Le worker a-t-il donné signe de vie récemment ?")
    semaines_validees: list[int] = Field(description="Numérotation de l'onglet Celcat (pas l'index solveur).")
    semaines_lancees: list[int]
    semaines_passees: list[int]
    semaines_completes: list[int]
    semaines_creation_autorisee: list[int]
    valide_le: str | None
    dernier_job_lance_le: str | None
    derniere_ecriture_celcat: str | None = Field(description="Dernière écriture réellement faite dans Celcat.")
    compteurs: CelcatCompteursV1
    file: CelcatFileV1


class JourSaeReserveV1(BaseModel):
    date: str
    semaine: int | None = Field(description="Index solveur (`null` hors de l'année affichée).")
    numero_semaine: int | None
    jour: int | None
    groupes: list[str] = Field(description="TD concernés si la SAE ne réserve le jour qu'à une partie de la "
                                           "promo (libellés courts, ex. `AB`) ; vide = tout le parcours.")


class PhaseEncadrementV1(BaseModel):
    debut: str
    fin: str
    sauf: list[str] = Field(description="Dates retirées de la phase.")
    note: str | None


class EncadrantSaeV1(BaseModel):
    code: str
    nom: str
    phases: list[PhaseEncadrementV1] = Field(
        description="Fenêtres déclarées dans `sae_teacher_phases.yaml` ; vide = tous les jours de la SAE."
    )
    jours: list[str] = Field(
        description="Jours où l'enseignant est compté comme encadrant (moins disponible pour un autre cours)."
    )


class SeanceSaeV1(SeanceV1):
    journee_sae: str | None = Field(description="Identifiant de la journée SAE (`parcours|date`) où elle tombe.")
    exception: bool = Field(description="Hors journée SAE, mais c'est déclaré (cf. `motif_exception`).")
    motif_exception: str | None
    anomalie: bool = Field(description="Hors journée SAE sans exception déclarée : à vérifier.")


class SaeV1(BaseModel):
    code: str
    intitule: str
    parcours: str
    semestre: str
    annee: str
    planifiee_par_solveur: bool = Field(
        description="Vrai pour les rares SAE que la génération place elle-même (`solver_scheduled_sae`, ex. "
        "WSA501D). Sinon la SAE est organisée par ses enseignants sur ses jours réservés."
    )
    commentaire_edt: str | None = Field(description="Commentaire de la maquette à l'attention de l'EDT.")
    nb_cm: int
    nb_td: int
    nb_tp: int
    nb_evaluations: int
    nb_seances_maquette: int
    nb_placees: int
    nb_non_placees: int
    enseignants: list[str] = Field(description="Enseignants de la maquette (codes).")
    enseignants_noms: list[str]
    encadrants: list[EncadrantSaeV1] = Field(description="Référents déclarés au calendrier des SAE.")
    jours_reserves: list[JourSaeReserveV1] = Field(
        description="Jours réservés à la SAE : aucun cours classique du parcours n'y est placé."
    )
    nb_dans_journee_sae: int
    nb_exceptions: int = Field(description="Placées hors journée SAE, exception déclarée.")
    nb_anomalies: int = Field(description="Placées hors journée SAE sans exception déclarée.")
    seances: list[SeanceSaeV1] = Field(description="Cours de la SAE placés au planning.")
    non_placees: list[SeanceNonPlaceeV1] = Field(description="Cours de la maquette absents du planning.")


class SaesV1(BaseModel):
    total: int = Field(description="SAE listées (une par code, semestre et parcours).")
    nb_seances_maquette: int
    nb_placees: int
    nb_non_placees: int
    nb_dans_journee_sae: int
    nb_exceptions: int
    nb_anomalies: int
    anomalies: list[SeanceSaeV1] = Field(description="Cours de SAE placés hors journée SAE sans exception déclarée.")
    sae: list[SaeV1]


class SaeJourneeRefV1(BaseModel):
    code: str
    intitule: str
    origine: Literal["calendrier_officiel", "correction_locale"] = Field(
        description="`calendrier_officiel` : fichier DATES SAE de l'établissement "
        "(`contraintes/09_dates_sae.json`) ; `correction_locale` : ajoutée par `sae_corrections.yaml`."
    )
    motif: str | None = Field(description="Motif de la correction locale.")


class EncadrantJourneeV1(BaseModel):
    code: str
    nom: str
    sae: str


class PeriodeSaeV1(BaseModel):
    id: str = Field(description="`code-date_debut` — l'UID de l'évènement dans les flux .ics.")
    code: str
    intitule: str | None = Field(description="Intitulé du module dans la maquette.")
    libelle: str
    titre: str = Field(description="Titre de l'évènement .ics (« SAE WS502D (AB) »).")
    description: str = Field(description="Description de l'évènement .ics.")
    parcours: str | None = Field(description="`null` : parcours introuvable, la SAE concerne tous les parcours.")
    groupes: list[str] = Field(description="TD concernés (libellés courts) ; vide = tout le parcours.")
    date_debut: str = Field(description="Premier jour, inclus.")
    date_fin: str = Field(description="Dernier jour, inclus.")
    jours: list[str] = Field(description="Jours réellement réservés (le week-end ne coupe pas une période).")
    nb_jours: int
    semaines: list[int] = Field(description="Index solveur des semaines couvertes (connues).")
    numeros_semaine: list[int] = Field(description="« Semaine N » du département des semaines couvertes.")


class JourneeSaeV1(BaseModel):
    id: str = Field(description="`parcours|date`.")
    date: str
    semaine: int | None
    numero_semaine: int | None
    jour: int
    jour_nom: str
    parcours: str | None = Field(description="`null` : parcours introuvable, la SAE concerne tous les parcours.")
    groupes: list[str] = Field(description="TD concernés (libellés courts) si la SAE ne réserve le jour qu'à une "
                                           "partie de la promo ; vide = tout le parcours.")
    journee_entiere: bool = Field(description="Toujours vrai : une journée SAE bloque les 6 créneaux.")
    creneaux: list[int]
    sae: list[SaeJourneeRefV1]
    encadrants: list[EncadrantJourneeV1] = Field(description="Enseignants attendus sur la SAE ce jour-là.")
    seances: list[SeanceV1] = Field(description="Cours de SAE du parcours effectivement placés ce jour-là.")


class JourneesSaeV1(BaseModel):
    total: int
    par_parcours: dict[str, int]
    journees: list[JourneeSaeV1]


class SaeDetailV1(BaseModel):
    code: str
    intitule: str
    declinaisons: list[SaeV1]


class ExportSaeV1(BaseModel):
    periodes: list[PeriodeSaeV1] = Field(description="Semaines de projet SAÉ (évènements journée entière des .ics).")
    journees: list[JourneeSaeV1] = Field(description="Une ligne par jour SAE et par parcours.")
    cours: list[SaeV1] = Field(description="Cours de SAE (maquette, placés, non placés), cf. `/api/v1/sae`.")


class ExportV1(BaseModel):
    revision: int
    modifie_le: str
    jours: list[JourV1]
    creneaux: list[CreneauV1]
    semaines: list[SemaineV1]
    parcours: list[ParcoursV1]
    groupes: list[GroupeV1]
    enseignants: list[EnseignantV1]
    salles: list[SalleV1]
    cours: list[CoursV1]
    seances: list[SeanceV1]
    seances_non_placees: list[SeanceNonPlaceeV1]
    contraintes: ContraintesV1
    calendrier: CalendrierV1
    modifications: list[ModificationV1]
    taches: list[TacheV1]
    sae: ExportSaeV1


# ── Outils communs ──────────────────────────────────────────────────────


def _main():
    # Import tardif : `api/main.py` importe ce module pour monter le routeur.
    from cal_iut.api import main

    return main


def _repondre(request: Request, construire, *, en_plus: tuple = ()) -> Response:
    """ETag + cache par (révision, chemin, paramètres, variante). `t` (lien
    personnel) est retiré de la clé : il ne change que la variante, déjà
    comptée à part — sans ça chaque lien perso aurait son propre cache.
    `en_plus` : ce qui change la réponse sans être dans l'URL (ex. le rôle,
    pour « À traiter » dont les doublons sont réservés au rôle `edit`)."""
    variante = _main().variante_lecture(request)
    parametres = tuple(sorted((k, v) for k, v in request.query_params.multi_items() if k != "t"))
    cle = ("v1", request.url.path, parametres, variante, *en_plus)
    return cache_http.repondre(
        request, _cache_v1, cle, lambda: cache_http.serialiser_json(construire(variante))
    )


def _payload() -> dict:
    return _main().payload_app_state()


def _creneaux() -> list[CreneauV1]:
    from cal_iut.export.formatter import SLOT_TIMES

    return [CreneauV1(index=i, debut=d, fin=f, libelle=f"{d}–{f}") for i, (d, f) in enumerate(SLOT_TIMES)]


def _jours() -> list[JourV1]:
    return [JourV1(index=i, nom=n) for i, n in enumerate(JOURS)]


_STATUTS = {"past": "passee", "current": "en_cours", "future": "future"}


def _semaines() -> list[SemaineV1]:
    """Relu depuis `weekRows`/`weekStatus` du payload — même calendrier, même
    statut que l'écran. Une semaine BLOQUÉE n'a pas d'index solveur, donc pas
    de statut calculé côté serveur : on le déduit de sa date."""
    from cal_iut.calendar.academic import department_week_number

    payload = _payload()
    statut_par_index = {int(r["week"]): r["status"] for r in payload.get("weekStatus") or []}
    aujourd_hui = date.today()  # noqa: DTZ011 — même date locale que `week_status`
    sortie = []
    for row in payload.get("weekRows") or []:
        lundi = date.fromisoformat(str(row["monday"]))
        index = row.get("weekIndex")
        statut = _STATUTS.get(statut_par_index.get(index, ""), None) if index is not None else None
        if statut is None:
            if lundi + timedelta(days=6) < aujourd_hui:
                statut = "passee"
            elif lundi <= aujourd_hui:
                statut = "en_cours"
            else:
                statut = "future"
        sortie.append(SemaineV1(
            semaine=index, numero=department_week_number(lundi), semaine_iso=lundi.isocalendar()[1],
            lundi=lundi.isoformat(), libelle=str(row.get("label") or ""), bloquee=bool(row.get("blocked")),
            statut=statut,
        ))
    return sortie


def _libelles_enseignants() -> dict[str, str]:
    return dict(_payload().get("teacherLabels") or {})


def _enseignants(variante: str) -> list[EnseignantV1]:
    state = _main().get_state()
    payload = _payload()
    emails = (payload.get("teacherEmails") or {}) if variante == "complet" else {}
    compte: dict[str, int] = {}
    for p in state.timetable:
        for code in p.teacher_codes or []:
            compte[code] = compte.get(code, 0) + 1
    libelles = _libelles_enseignants()
    codes = sorted(set(libelles) | set(compte))
    return [
        EnseignantV1(code=c, nom=libelles.get(c, c), email=emails.get(c) or None, nb_seances=compte.get(c, 0))
        for c in codes
    ]


def _groupes() -> list[GroupeV1]:
    """Mêmes groupes que `/meta` (un groupe sans aucune séance n'est pas
    proposé, cf. `get_meta`), avec leur cohorte résolue."""
    from cal_iut.models.group_scope import expand_group_filter, related_group_ids

    main = _main()
    state = main.get_state()
    meta = main._calculer_meta()
    par_id = {g.id: g for g in state.groups}
    sortie = []
    for gm in meta.groups:
        g = par_id.get(gm.id)
        sortie.append(GroupeV1(
            id=gm.id, libelle=gm.label, parcours=gm.parcours, annee=str(gm.annee or ""), type=gm.kind,
            groupes_lies=list(gm.related_ids or (related_group_ids(g, state.groups) if g else [])),
            cohorte=sorted(expand_group_filter(gm.id, state.groups)),
        ))
    return sortie


def _salles() -> list[SalleV1]:
    """Catalogue de salles du payload (`_room_catalog`) — même libellé, même
    drapeau `placement_auto`, mêmes fusions que l'écran."""
    state = _main().get_state()
    compte: dict[str, int] = {}
    for p in state.timetable:
        rid = getattr(p, "room_id", None)
        if rid:
            compte[rid] = compte.get(rid, 0) + 1
    return [
        SalleV1(
            id=r["id"], libelle=r["label"], capacite=int(r["capacity"]), type=str(r["type"]),
            equipements=list(r.get("equipment") or []), placement_auto=bool(r.get("placementAuto", True)),
            fusionne=list(r.get("combines") or []), nb_seances=compte.get(r["id"], 0),
        )
        for r in _payload().get("rooms") or []
    ]


def _cours() -> list[CoursV1]:
    return [
        CoursV1(
            code=c["code"], nom=c["name"], semestre=c["semestre"], parcours=c["parcours"],
            nb_cm=c["nCM"], nb_td=c["nTD"], nb_tp=c["nTP"], nb_evaluations=c["nEval"],
            nb_placees=c["nPlaced"], enseignants=list(c["teachers"]),
            progression_definie=bool(c.get("progressionDefined")), sae=est_sae(c["code"]),
            ordonnancement=[
                OrdonnancementV1(position=o["position"], cible=o["target"]) for o in c.get("ordonnancement") or []
            ],
        )
        for c in _payload().get("courses") or []
    ]


def _parcours() -> list[ParcoursV1]:
    main = _main()
    meta = main._calculer_meta()
    sortie = []
    for p in meta.parcours:
        annee = next((y for y in meta.years if p in y.parcours), None)
        sortie.append(ParcoursV1(
            id=p, annee=annee.id if annee else None, semestres=list(annee.semestres) if annee else [],
            groupes=[g.id for g in meta.groups if g.parcours == p],
        ))
    return sortie


def _seances(placements: list) -> list[SeanceV1]:
    """Une `SeanceV1` par placement — construite depuis `_to_placement`
    (même source que `/timetable`) + date réelle calculée sur le semestre
    PROPRE à chaque séance (`_date_iso`, même règle que les flux .ics)."""
    from cal_iut.calendar.academic import department_week_number
    from cal_iut.export.formatter import SLOT_TIMES

    main = _main()
    state = main.get_state()
    semestre_defaut = main._export_semestre(state)
    payload = _payload()
    libelles_groupes = payload.get("groupLabels") or {}
    noms = _libelles_enseignants()
    journees = _journees_sae_par_parcours()
    sortie = []
    for p in placements:
        pl = main._to_placement(p, state.sessions_by_id)
        s = state.sessions_by_id.get(p.session_id)
        semestre = (s.semestre if s else "") or semestre_defaut
        date_iso = main._date_iso(state, semestre, p.week, p.day) or None
        duree = max(1, pl.duration_slots)
        fin_slot = min(p.slot + duree - 1, len(SLOT_TIMES) - 1)
        debut = SLOT_TIMES[p.slot][0] if 0 <= p.slot < len(SLOT_TIMES) else ""
        fin = SLOT_TIMES[fin_slot][1] if 0 <= fin_slot < len(SLOT_TIMES) else debut
        horaire = (s.metadata.get("horaire") if s else None) or None
        if isinstance(horaire, dict) and horaire.get("debut") and horaire.get("fin"):
            debut, fin = str(horaire["debut"]), str(horaire["fin"])
        numero = None
        if date_iso:
            jour = date.fromisoformat(date_iso)
            numero = department_week_number(jour - timedelta(days=jour.weekday()))
        sortie.append(SeanceV1(
            id=pl.session_id, cours_code=pl.course_code, cours_nom=pl.course_name, type=pl.session_type,
            parcours=(s.parcours if s else ""), semestre=semestre,
            groupes=list(pl.group_ids), groupes_libelles=[libelles_groupes.get(g, g) for g in pl.group_ids],
            enseignants=list(pl.teacher_codes), enseignants_noms=[noms.get(c, c) for c in pl.teacher_codes],
            salle_id=pl.room_id, salle_libelle=pl.room_label,
            semaine=p.week, numero_semaine=numero, date=date_iso,
            jour=p.day, jour_nom=JOURS[p.day] if 0 <= p.day < len(JOURS) else "",
            creneau=p.slot, duree_creneaux=duree, debut=debut, fin=fin,
            horaire_libre=isinstance(horaire, dict) and bool(horaire.get("debut")),
            evaluation=pl.is_eval, verrouillee=pl.locked,
            personnalisee=bool(s and s.metadata.get("custom_session")),
            evenement=bool(s and s.metadata.get("evenement")), sae=est_sae(pl.course_code),
            dans_journee_sae=(
                _dans_journee_sae(journees, s.parcours if s else "", date_iso) if est_sae(pl.course_code) else None
            ),
        ))
    sortie.sort(key=lambda x: (x.date or "", x.debut, x.id))
    return sortie


def _placements_filtres(
    *,
    semaine: int | None = None,
    enseignant: str | None = None,
    groupe: str | None = None,
    salle: str | None = None,
    cours: str | None = None,
    parcours: str | None = None,
    sae: bool | None = None,
) -> list:
    """Filtres groupe/enseignant/salle/semaine : `_filter_timetable`, le même
    que `/timetable` — un groupe TD inclut donc ses TP et les CM de sa promo
    (`expand_group_filter`). Cours et parcours s'y ajoutent ici."""
    main = _main()
    state = main.get_state()
    if not state.timetable:
        raise HTTPException(404, "Aucun planning chargé.")
    placements = main._filter_timetable(state.timetable, groupe, enseignant, salle, semaine, state.groups)
    if cours:
        placements = [p for p in placements if p.course_code == cours]
    if parcours:
        placements = [
            p for p in placements
            if getattr(state.sessions_by_id.get(p.session_id), "parcours", None) == parcours
        ]
    if sae is not None:
        placements = [p for p in placements if est_sae(p.course_code) == sae]
    return placements


def _paginer(seances: list[SeanceV1], du: date | None, au: date | None, limite: int | None, decalage: int) -> SeancesV1:
    if du is not None:
        seances = [s for s in seances if s.date and s.date >= du.isoformat()]
    if au is not None:
        seances = [s for s in seances if s.date and s.date <= au.isoformat()]
    total = len(seances)
    page = seances[decalage: decalage + limite] if limite is not None else seances[decalage:]
    return SeancesV1(total=total, decalage=decalage, limite=limite, seances=page)


# Paramètres communs des listes de séances.
_Q_SEMAINE = Query(None, ge=0, description="Index solveur de la semaine (cf. `/api/v1/semaines`).")
_Q_DU = Query(None, description="Date ISO incluse (`AAAA-MM-JJ`).")
_Q_AU = Query(None, description="Date ISO incluse (`AAAA-MM-JJ`).")
_Q_LIMITE = Query(None, ge=1, le=10000, description="Nombre maximal de séances renvoyées.")
_Q_DECALAGE = Query(0, ge=0, description="Séances à sauter (pagination).")


# ── Routes ──────────────────────────────────────────────────────────────


@router.get("/version", response_model=VersionV1, tags=_TAGS_ETAT)
def version(request: Request) -> Response:
    """Révision courante de l'état — quelques octets, pensé pour le sondage.

    Ne relire les données (`/api/v1/export`, `/api/v1/seances`...) que
    lorsque `revision` a changé depuis le dernier sondage. Porte lui aussi un
    ETag : un sondage avec `If-None-Match` reçoit un 304 vide."""
    rev = revision.actuelle()
    return cache_http.repondre(
        request, _cache_v1, ("v1-version",),
        lambda: cache_http.serialiser_json(VersionV1(revision=rev.numero, modifie_le=rev.iso())),
    )


@router.get("/semaines", response_model=list[SemaineV1], tags=_TAGS_REFERENTIEL)
def semaines(request: Request) -> Response:
    """Toutes les semaines affichées, y compris les semaines bloquées."""
    return _repondre(request, lambda _v: _semaines())


@router.get("/creneaux", response_model=CreneauxV1, tags=_TAGS_REFERENTIEL)
def creneaux(request: Request) -> Response:
    """Les 5 jours et les 6 créneaux horaires de la grille."""
    return _repondre(request, lambda _v: CreneauxV1(jours=_jours(), creneaux=_creneaux()))


@router.get("/enseignants", response_model=list[EnseignantV1], tags=_TAGS_REFERENTIEL)
def enseignants(request: Request) -> Response:
    return _repondre(request, _enseignants)


def _enseignant(code: str, variante: str) -> EnseignantDetailV1:
    trouve = next((e for e in _enseignants(variante) if e.code == code), None)
    if trouve is None:
        raise HTTPException(404, f"Enseignant « {code} » inconnu.")
    cours = sorted({p.course_code for p in _placements_filtres(enseignant=code)})
    return EnseignantDetailV1(**trouve.model_dump(), cours=cours)


@router.get("/enseignants/{code}", response_model=EnseignantDetailV1, tags=_TAGS_REFERENTIEL)
def enseignant(code: str, request: Request) -> Response:
    return _repondre(request, lambda v: _enseignant(code, v))


@router.get("/enseignants/{code}/seances", response_model=SeancesV1, tags=_TAGS_SEANCES)
def seances_enseignant(
    code: str, request: Request, semaine: int | None = _Q_SEMAINE, du: date | None = _Q_DU,
    au: date | None = _Q_AU, limite: int | None = _Q_LIMITE, decalage: int = _Q_DECALAGE,
) -> Response:
    def _construire(variante: str) -> SeancesV1:
        _enseignant(code, variante)
        return _paginer(_seances(_placements_filtres(enseignant=code, semaine=semaine)), du, au, limite, decalage)

    return _repondre(request, _construire)


@router.get("/groupes", response_model=list[GroupeV1], tags=_TAGS_REFERENTIEL)
def groupes(request: Request) -> Response:
    return _repondre(request, lambda _v: _groupes())


def _groupe(groupe_id: str) -> GroupeV1:
    trouve = next((g for g in _groupes() if g.id == groupe_id), None)
    if trouve is None:
        raise HTTPException(404, f"Groupe « {groupe_id} » inconnu.")
    return trouve


@router.get("/groupes/{groupe_id}", response_model=GroupeV1, tags=_TAGS_REFERENTIEL)
def groupe(groupe_id: str, request: Request) -> Response:
    return _repondre(request, lambda _v: _groupe(groupe_id))


@router.get("/groupes/{groupe_id}/seances", response_model=SeancesV1, tags=_TAGS_SEANCES)
def seances_groupe(
    groupe_id: str, request: Request, semaine: int | None = _Q_SEMAINE, du: date | None = _Q_DU,
    au: date | None = _Q_AU, limite: int | None = _Q_LIMITE, decalage: int = _Q_DECALAGE,
) -> Response:
    def _construire(_v: str) -> SeancesV1:
        _groupe(groupe_id)
        return _paginer(_seances(_placements_filtres(groupe=groupe_id, semaine=semaine)), du, au, limite, decalage)

    return _repondre(request, _construire)


@router.get("/salles", response_model=list[SalleV1], tags=_TAGS_SALLES)
def salles(request: Request) -> Response:
    return _repondre(request, lambda _v: _salles())


def _salles_libres(semaine: int, jour: int, creneau: int, capacite_min: int) -> SallesLibresV1:
    """Salles libres à un créneau : ni séance posée (y compris une séance de
    plusieurs créneaux commencée avant), ni réservation par un tiers
    (`salles_reservees.yaml`), ni salle LIÉE occupée.

    Salles liées : `build_manual_conflict_map`, la carte que le serveur
    applique lui-même à tout placement ou changement de salle manuel —
    H.007 occupée rend H.008 et H.007+H.008 indisponibles (retour Kyllian
    Bresson 25/09/2026 : « c'est en soi la même salle »). Une salle annoncée
    libre ici est donc une salle que le serveur acceptera vraiment."""
    from cal_iut.solver.rooms import build_manual_conflict_map

    main = _main()
    state = main.get_state()
    if not state.timetable:
        raise HTTPException(404, "Aucun planning chargé.")
    occupees: list[OccupationV1] = []
    occupe_directement: set[str] = set()
    for p in state.timetable:
        rid = getattr(p, "room_id", None)
        if not rid or p.week != semaine or p.day != jour:
            continue
        s = state.sessions_by_id.get(p.session_id)
        duree = max(1, getattr(s, "duration_slots", 1) or 1)
        if p.slot <= creneau < p.slot + duree:
            occupe_directement.add(rid)
            occupees.append(OccupationV1(salle_id=rid, motif="seance", seance_id=p.session_id, cours_code=p.course_code))

    semestre = main._export_semestre(state)
    date_iso = main._date_iso(state, semestre, semaine, jour) or None
    if date_iso:
        for resa in _payload().get("roomReservations") or []:
            if resa.get("date") == date_iso and creneau in (resa.get("slots") or []):
                rid = str(resa.get("salle"))
                occupe_directement.add(rid)
                occupees.append(OccupationV1(salle_id=rid, motif="reservation", detail=str(resa.get("motif") or "")))

    conflits = build_manual_conflict_map(state.rooms)
    for rid in sorted(occupe_directement):
        for liee in sorted(conflits.get(rid, set()) - occupe_directement):
            occupees.append(OccupationV1(salle_id=liee, motif="salle_liee", detail=rid))
    indisponibles = {o.salle_id for o in occupees}
    libres = [s for s in _salles() if s.id not in indisponibles and s.capacite >= capacite_min]
    libres.sort(key=lambda s: (s.capacite, s.libelle))
    return SallesLibresV1(semaine=semaine, jour=jour, creneau=creneau, date=date_iso, libres=libres, occupees=occupees)


@router.get("/salles/libres", response_model=SallesLibresV1, tags=_TAGS_SALLES)
def salles_libres(
    request: Request,
    semaine: int = Query(..., ge=0, description="Index solveur de la semaine."),
    jour: int = Query(..., ge=0, le=4, description="0 = lundi … 4 = vendredi."),
    creneau: int = Query(..., ge=0, le=5, description="0 = 08:00 … 5 = 17:00 (cf. `/api/v1/creneaux`)."),
    capacite_min: int = Query(0, ge=0),
) -> Response:
    """Salles libres à un créneau donné, triées par capacité croissante (la
    plus juste d'abord), et ce qui occupe les autres."""
    return _repondre(request, lambda _v: _salles_libres(semaine, jour, creneau, capacite_min))


def _salle(salle_id: str) -> SalleV1:
    trouvee = next((s for s in _salles() if s.id == salle_id), None)
    if trouvee is None:
        raise HTTPException(404, f"Salle « {salle_id} » inconnue.")
    return trouvee


@router.get("/salles/{salle_id}", response_model=SalleV1, tags=_TAGS_SALLES)
def salle(salle_id: str, request: Request) -> Response:
    return _repondre(request, lambda _v: _salle(salle_id))


@router.get("/salles/{salle_id}/seances", response_model=SeancesV1, tags=_TAGS_SEANCES)
def seances_salle(
    salle_id: str, request: Request, semaine: int | None = _Q_SEMAINE, du: date | None = _Q_DU,
    au: date | None = _Q_AU, limite: int | None = _Q_LIMITE, decalage: int = _Q_DECALAGE,
) -> Response:
    def _construire(_v: str) -> SeancesV1:
        _salle(salle_id)
        return _paginer(_seances(_placements_filtres(salle=salle_id, semaine=semaine)), du, au, limite, decalage)

    return _repondre(request, _construire)


@router.get("/cours", response_model=list[CoursV1], tags=_TAGS_REFERENTIEL)
def liste_cours(request: Request) -> Response:
    """Une entrée par (code, semestre, parcours) : un même module peut être
    décliné dans plusieurs parcours."""
    return _repondre(request, lambda _v: _cours())


def _progression(code: str) -> list[EtapeProgressionV1]:
    """Toutes les séances du cours dans la maquette (`state.sessions`), dans
    l'ordre pédagogique, avec leur placement s'il existe — ce que la Vue
    Cours montre comme « progression »."""
    from cal_iut.export.formatter import SLOT_TIMES

    main = _main()
    state = main.get_state()
    semestre_defaut = main._export_semestre(state)
    par_seance = {p.session_id: p for p in state.timetable}
    etapes = []
    for s in state.sessions:
        if s.course_code != code:
            continue
        p = par_seance.get(s.id)
        date_iso = main._date_iso(state, s.semestre or semestre_defaut, p.week, p.day) or None if p else None
        etapes.append(EtapeProgressionV1(
            seance_id=s.id, ordre=s.sequence_order, type=str(getattr(s.session_type, "value", s.session_type)),
            semestre=s.semestre, parcours=s.parcours, groupes=list(s.group_ids or []),
            enseignants=list(s.teacher_codes or []), duree_creneaux=max(1, s.duration_slots or 1),
            evaluation=bool(s.is_eval), placee=p is not None, semaine=p.week if p else None, date=date_iso,
            debut=SLOT_TIMES[p.slot][0] if p and 0 <= p.slot < len(SLOT_TIMES) else None,
        ))
    etapes.sort(key=lambda e: (e.parcours, e.semestre, e.ordre if e.ordre is not None else 10**6, e.type, e.seance_id))
    return etapes


def _un_cours(code: str) -> CoursDetailV1:
    declinaisons = [c for c in _cours() if c.code == code]
    if not declinaisons:
        raise HTTPException(404, f"Cours « {code} » inconnu.")
    return CoursDetailV1(code=code, nom=declinaisons[0].nom, declinaisons=declinaisons, progression=_progression(code))


@router.get("/cours/{code}", response_model=CoursDetailV1, tags=_TAGS_REFERENTIEL)
def un_cours(code: str, request: Request) -> Response:
    return _repondre(request, lambda _v: _un_cours(code))


@router.get("/cours/{code}/seances", response_model=SeancesV1, tags=_TAGS_SEANCES)
def seances_cours(
    code: str, request: Request, semaine: int | None = _Q_SEMAINE, du: date | None = _Q_DU,
    au: date | None = _Q_AU, limite: int | None = _Q_LIMITE, decalage: int = _Q_DECALAGE,
) -> Response:
    def _construire(_v: str) -> SeancesV1:
        _un_cours(code)
        return _paginer(_seances(_placements_filtres(cours=code, semaine=semaine)), du, au, limite, decalage)

    return _repondre(request, _construire)


@router.get("/parcours", response_model=list[ParcoursV1], tags=_TAGS_REFERENTIEL)
def liste_parcours(request: Request) -> Response:
    return _repondre(request, lambda _v: _parcours())


def _un_parcours(parcours_id: str) -> ParcoursV1:
    trouve = next((p for p in _parcours() if p.id == parcours_id), None)
    if trouve is None:
        raise HTTPException(404, f"Parcours « {parcours_id} » inconnu.")
    return trouve


@router.get("/parcours/{parcours_id}", response_model=ParcoursV1, tags=_TAGS_REFERENTIEL)
def un_parcours(parcours_id: str, request: Request) -> Response:
    return _repondre(request, lambda _v: _un_parcours(parcours_id))


@router.get("/parcours/{parcours_id}/seances", response_model=SeancesV1, tags=_TAGS_SEANCES)
def seances_parcours(
    parcours_id: str, request: Request, semaine: int | None = _Q_SEMAINE, du: date | None = _Q_DU,
    au: date | None = _Q_AU, limite: int | None = _Q_LIMITE, decalage: int = _Q_DECALAGE,
) -> Response:
    def _construire(_v: str) -> SeancesV1:
        _un_parcours(parcours_id)
        placements = _placements_filtres(parcours=parcours_id, semaine=semaine)
        return _paginer(_seances(placements), du, au, limite, decalage)

    return _repondre(request, _construire)


@router.get("/seances", response_model=SeancesV1, tags=_TAGS_SEANCES)
def seances(
    request: Request,
    semaine: int | None = _Q_SEMAINE,
    enseignant: str | None = Query(None, description="Code enseignant (ex. `KBR`)."),
    groupe: str | None = Query(
        None, description="Id de groupe — inclut les séances de la promo et du TD parent qui le concernent."
    ),
    salle: str | None = Query(None, description="Id de salle (ex. `h018`)."),
    cours: str | None = Query(None, description="Code du cours (ex. `WR101`)."),
    parcours: str | None = Query(None, description="Parcours (ex. `BUT2-DEV-FI`)."),
    sae: bool | None = Query(None, description="`true` : seulement les séances de SAE ; `false` : sans elles."),
    du: date | None = _Q_DU,
    au: date | None = _Q_AU,
    limite: int | None = _Q_LIMITE,
    decalage: int = _Q_DECALAGE,
) -> Response:
    """Séances placées, filtrables (tous les filtres se cumulent), triées par
    date puis heure de début."""

    def _construire(_v: str) -> SeancesV1:
        placements = _placements_filtres(
            semaine=semaine, enseignant=enseignant, groupe=groupe, salle=salle, cours=cours, parcours=parcours,
            sae=sae,
        )
        return _paginer(_seances(placements), du, au, limite, decalage)

    return _repondre(request, _construire)


# ── Repères de semaine communs aux vues calculées ───────────────────────


def _reperes() -> dict[int, tuple[date, int]]:
    """Index solveur → (lundi, « Semaine N »), depuis `weekDates` du payload."""
    from cal_iut.calendar.academic import department_week_number

    return {w: (lundi, department_week_number(lundi)) for w, lundi in vues.lundis(_payload()).items()}


def _quand(reperes: dict[int, tuple[date, int]], semaine: int | None, jour: int | None) -> dict:
    """`numero_semaine`, `date` et `jour_nom` d'un (semaine solveur, jour)."""
    repere = reperes.get(semaine) if semaine is not None else None
    return {
        "numero_semaine": repere[1] if repere else None,
        "date": (repere[0] + timedelta(days=jour)).isoformat() if repere and jour is not None else None,
        "jour_nom": JOURS[jour] if jour is not None and 0 <= jour < len(JOURS) else None,
    }


def _heure(creneau: int | None, borne: int = 0) -> str | None:
    from cal_iut.export.formatter import SLOT_TIMES

    return SLOT_TIMES[creneau][borne] if creneau is not None and 0 <= creneau < len(SLOT_TIMES) else None


def _role_au_moins(request: Request, minimum: str) -> bool:
    user = getattr(request.state, "user", None)
    return user is not None and accounts.ROLE_ORDER.get(user.role, -1) >= accounts.ROLE_ORDER[minimum]


# ── Séances non placées ─────────────────────────────────────────────────


def _depuis_manquante(m) -> SeanceNonPlaceeV1:
    """Une entrée de `GET /placements/manquantes`, au format v1."""
    return SeanceNonPlaceeV1(
        id=m.session_id, cours_code=m.course_code, cours_nom=m.course_name, type=m.session_type,
        semestre=m.semestre, parcours=m.parcours, annee=m.annee, duree_creneaux=m.duration_slots,
        duree_libelle=m.duree_libelle, groupes=list(m.group_ids), groupes_libelles=list(m.groupes_libelles),
        enseignants=list(m.teacher_codes), enseignants_noms=list(m.enseignants_libelles),
        ordre=m.sequence_order, semaines_possibles=list(m.semaines_possibles), raison=m.raison,
        placee_provisoirement=bool(m.placee_provisoirement), semaine_actuelle=m.semaine_actuelle,
        jour_actuel=m.jour_actuel, creneau_actuel=m.slot_actuel, sae=est_sae(m.course_code),
        statut="en_attente_validation" if m.placee_provisoirement else "a_placer",
    )


_RAISON_SAE_HORS_SOLVEUR = (
    "Cours de SAE organisé par ses enseignants sur les journées SAE du parcours : la génération ne le place "
    "pas (« + Nouvelle séance » pour le poser à la main)."
)
_RAISON_SAE_SOLVEUR = "SAE planifiée par la génération (`solver_scheduled_sae`), mais ce cours n'a pas été placé."


def _sae_non_placees_hors_liste(manquantes: dict) -> list[SeanceNonPlaceeV1]:
    """Cours de SAE absents du planning ET de `/placements/manquantes` (qui
    les écarte, retour utilisateur du 04/09/2026) — avec leur raison.
    `semaines_possibles` = semaines des journées SAE du parcours."""
    main = _main()
    state = main.get_state()
    places = {p.session_id for p in state.timetable}
    planifiees = _config_sae()["planifiees"]
    journees = _journees_sae_par_parcours()
    lundis = {w: r[0] for w, r in _reperes().items()}

    def _semaines(parcours_: str) -> list[int]:
        dates = [*journees.get(parcours_, {}), *journees.get(None, {})]
        return sorted({q[0] for d in dates if (q := vues.semaine_de_date(lundis, d))})

    libelle_groupe = {g.id: g.label for g in state.groups}
    noms = _libelles_enseignants()
    sortie = []
    for s in state.sessions:
        if not est_sae(s.course_code) or s.id in places or s.id in manquantes:
            continue
        par_solveur = (s.course_code.upper(), s.semestre) in planifiees
        duree = max(1, s.duration_slots or 1)
        sortie.append(SeanceNonPlaceeV1(
            id=s.id, cours_code=s.course_code, cours_nom=s.course_name,
            type=str(getattr(s.session_type, "value", s.session_type)), semestre=s.semestre, parcours=s.parcours,
            annee=s.annee, duree_creneaux=duree, duree_libelle=main._LIBELLES_DUREE.get(duree, "?"),
            groupes=list(s.group_ids or []), groupes_libelles=[libelle_groupe.get(g, g) for g in s.group_ids or []],
            enseignants=list(s.teacher_codes or []), enseignants_noms=[noms.get(c, c) for c in s.teacher_codes or []],
            ordre=s.sequence_order,
            semaines_possibles=_semaines(s.parcours),
            raison=_RAISON_SAE_SOLVEUR if par_solveur else _RAISON_SAE_HORS_SOLVEUR, placee_provisoirement=False,
            sae=True, statut="a_placer" if par_solveur else "hors_solveur",
        ))
    sortie.sort(key=lambda m: (m.parcours, m.cours_code, m.ordre or 0, m.id))
    return sortie


def _non_placees(
    *, parcours: str | None = None, cours: str | None = None, enseignant: str | None = None,
    semaine: int | None = None, inclure_sae: bool = False,
) -> SeancesNonPlaceesV1:
    """`GET /placements/manquantes` (panneau « À placer »), tel quel :
    calcul par DIFFÉRENCE maquette − planning, SAE hors solveur exclues —
    sauf `inclure_sae`, qui ajoute les cours de SAE non placés."""
    brut = _main().seances_manquantes()
    candidates = [_depuis_manquante(m) for m in brut.manquantes]
    if inclure_sae:
        candidates += _sae_non_placees_hors_liste({m.session_id for m in brut.manquantes})
    seances = []
    for m in candidates:
        if parcours and m.parcours != parcours:
            continue
        if cours and m.cours_code != cours:
            continue
        if enseignant and enseignant not in m.enseignants:
            continue
        if semaine is not None and semaine not in m.semaines_possibles:
            continue
        seances.append(m)
    par_parcours: dict[str, int] = {}
    for s in seances:
        par_parcours[s.parcours] = par_parcours.get(s.parcours, 0) + 1
    return SeancesNonPlaceesV1(
        total=len(seances), total_a_placer=brut.total_a_placer, total_placees=brut.total_placees,
        par_parcours=par_parcours, resume=brut.resume, seances=seances,
    )


_EXEMPLE_NON_PLACEES = {
    "total": 1, "total_a_placer": 3101, "total_placees": 3100, "par_parcours": {"BUT2-DEV-FI": 1},
    "resume": "1 séance(s) sur 3101 restent à placer à la main. …",
    "seances": [{
        "id": "WR305-S3-TD-4-but2-dev-td", "cours_code": "WR305", "cours_nom": "Développement back",
        "type": "TD", "semestre": "S3", "parcours": "BUT2-DEV-FI", "annee": "BUT2", "duree_creneaux": 1,
        "duree_libelle": "1h30", "groupes": ["but2-dev-td"], "groupes_libelles": ["TD DEV"],
        "enseignants": ["KBR"], "enseignants_noms": ["KYLLIAN BRESSON"], "ordre": 4,
        "semaines_possibles": [6, 7, 8], "raison": "Aucun créneau commun libre pour le groupe et l'enseignant.",
        "placee_provisoirement": False, "semaine_actuelle": None, "jour_actuel": None, "creneau_actuel": None,
    }],
}


@router.get(
    "/seances/non-placees", response_model=SeancesNonPlaceesV1, tags=_TAGS_SEANCES,
    summary="Séances restant à placer", responses=_exemple(_EXEMPLE_NON_PLACEES),
)
def seances_non_placees(
    request: Request,
    parcours: str | None = Query(None, description="Parcours (ex. `BUT2-DEV-FI`)."),
    cours: str | None = Query(None, description="Code du cours."),
    enseignant: str | None = Query(None, description="Code enseignant."),
    semaine: int | None = Query(None, ge=0, description="Seulement celles qui peuvent aller dans cette semaine."),
    inclure_sae: bool = Query(
        False, description="Ajoute les cours de SAE non placés (`statut: hors_solveur`), que l'écran « À placer » "
        "n'affiche pas.",
    ),
) -> Response:
    """Séances de la maquette absentes du planning — le panneau « À placer »
    de la Vue Promo : type, groupes, enseignants, durée, semaines possibles
    et raison en clair. Les séances posées en forçant l'ordre pédagogique,
    pas encore validées, y restent (`placee_provisoirement`).

    Comme l'écran, les cours de SAE organisés par leurs enseignants n'y sont
    pas : `inclure_sae=true` les ajoute (`statut: hors_solveur`), ou voir
    `/api/v1/sae`."""
    return _repondre(request, lambda _v: _non_placees(
        parcours=parcours, cours=cours, enseignant=enseignant, semaine=semaine, inclure_sae=inclure_sae,
    ))


# ── Doublons ────────────────────────────────────────────────────────────


def _doublons(semaine: int | None) -> list[DoublonV1]:
    """`api/doublons.py::doublons`, le calcul de `GET /controles/doublons`."""
    from cal_iut.api import doublons as module_doublons

    reperes = _reperes()
    sortie = []
    for d in module_doublons.doublons(_main().get_state(), semaine):
        quand = _quand(reperes, d["semaine"], d["jour"])
        sortie.append(DoublonV1(
            semaine=d["semaine"], numero_semaine=quand["numero_semaine"], date=quand["date"], jour=d["jour"],
            jour_nom=quand["jour_nom"] or "", creneau=d["creneau"], debut=_heure(d["creneau"]) or "",
            fin=_heure(d["creneau"], 1) or "", type=d["type"], ressource=d["ressource"],
            seances=[
                DoublonSeanceV1(seance_id=s["session_id"], cours_code=s["course_code"], groupes=list(s["groupes"]),
                                salle=s.get("salle"), enseignants=list(s["enseignants"]))
                for s in d["seances"]
            ],
        ))
    return sortie


_EXEMPLE_DOUBLONS = {"total": 1, "doublons": [{
    "semaine": 5, "numero_semaine": 7, "date": "2026-10-06", "jour": 1, "jour_nom": "mardi", "creneau": 3,
    "debut": "14:00", "fin": "15:30", "type": "salle", "ressource": "H.201 / H.203",
    "seances": [
        {"seance_id": "WR101-S1-TD-3-but1-td-ab", "cours_code": "WR101", "groupes": ["but1-td-ab"],
         "salle": "H.201", "enseignants": ["TPA"]},
        {"seance_id": "WR205-S1-TD-2-but1-td-cd", "cours_code": "WR205", "groupes": ["but1-td-cd"],
         "salle": "H.203", "enseignants": ["MRI"]},
    ],
}]}


@router.get(
    "/controles/doublons", response_model=DoublonsV1, tags=_TAGS_CONTROLES,
    dependencies=[Depends(accounts.require_role("edit"))],
    summary="Doublons salle / enseignant (rôle edit)", responses=_exemple(_EXEMPLE_DOUBLONS),
)
def controles_doublons(request: Request, semaine: int | None = _Q_SEMAINE) -> Response:
    """Une salle ou un enseignant mobilisé par deux séances sur le même
    créneau. H.007/H.008/H.007-008 et H.201/H.203 comptent comme une seule
    salle. Réservé au rôle `edit` ou `admin`, comme dans l'appli."""
    def _construire(_v: str) -> DoublonsV1:
        liste = _doublons(semaine)
        return DoublonsV1(total=len(liste), doublons=liste)

    return _repondre(request, _construire)


# ── « À traiter » ───────────────────────────────────────────────────────


def _a_traiter(
    avec_doublons: bool, *, semaine: int | None = None, parcours: str | None = None,
    enseignant: str | None = None, gravite: str | None = None, nature: str | None = None,
) -> ATraiterV1:
    from cal_iut.api import doublons as module_doublons

    payload = _payload()
    points = vues.points_a_traiter(payload)
    if avec_doublons:
        points += vues.points_depuis_doublons(payload, module_doublons.doublons(_main().get_state(), None))
    # Cours de SAE hors journée SAE : LA liste de `/api/v1/sae` (`anomalies`).
    points += vues.points_depuis_sae(payload, [a.model_dump() for a in _saes().anomalies])
    points = vues.filtrer_points(
        points, semaine=semaine, parcours=parcours, enseignant=enseignant, gravite=gravite, nature=nature,
    )
    points = vues.trier_par_urgence(points, vues.statuts_semaines(payload))
    reperes = _reperes()
    sortie = []
    for p in points:
        quand = _quand(reperes, p["semaine"], p["jour"])
        sortie.append(PointATraiterV1(**p, **quand, debut=_heure(p["creneau"])))
    natures = [
        NatureATraiterV1(
            id=n["id"], titre=n["titre"], gravite=n["gravite"], aide=n["aide"],
            nombre=sum(p.nombre for p in sortie if p.nature == n["id"]),
        )
        for n in vues.NATURES
        if avec_doublons or n["id"] != "doublon"
    ]
    return ATraiterV1(
        total=sum(p.nombre for p in sortie),
        a_corriger=sum(p.nombre for p in sortie if p.gravite == "a_corriger"),
        a_revoir=sum(p.nombre for p in sortie if p.gravite == "a_revoir"),
        doublons_inclus=avec_doublons, natures=natures, points=sortie,
    )


_EXEMPLE_A_TRAITER = {
    "total": 3, "a_corriger": 2, "a_revoir": 1, "doublons_inclus": True,
    "natures": [
        {"id": "non-placee", "titre": "Séances non placées", "gravite": "a_corriger",
         "aide": "Des heures prévues sans aucun créneau. …", "nombre": 1},
        {"id": "trouee", "titre": "Journées trouées", "gravite": "a_revoir",
         "aide": "Au moins deux créneaux vides entre deux cours d'un même groupe dans la journée.", "nombre": 1},
    ],
    "points": [
        {"nature": "non-placee", "gravite": "a_corriger", "cle": "np|WR305|TD|TD DEV|KYLLIAN BRESSON",
         "titre": "WR305 — Développement back", "detail": "TD · TD DEV · KYLLIAN BRESSON", "semaine": None,
         "numero_semaine": None, "date": None, "jour": None, "jour_nom": None, "creneau": None, "debut": None,
         "parcours": ["BUT2-DEV-FI"], "enseignants": ["KBR"], "nombre": 1, "seances": []},
        {"nature": "sans-salle", "gravite": "a_corriger", "cle": "ss|WR118-S1-CM-3", "titre": "WR118 — Gestion de projet",
         "detail": "CM · Promo BUT1", "semaine": 5, "numero_semaine": 7, "date": "2026-10-06", "jour": 1,
         "jour_nom": "mardi", "creneau": 0, "debut": "08:00", "parcours": ["BUT1"], "enseignants": ["KBR"],
         "nombre": 1, "seance_id": "WR118-S1-CM-3", "seances": []},
    ],
}


@router.get(
    "/a-traiter", response_model=ATraiterV1, tags=_TAGS_CONTROLES,
    summary="Écran « À traiter »", responses=_exemple(_EXEMPLE_A_TRAITER),
)
def a_traiter(
    request: Request,
    semaine: int | None = Query(
        None, ge=0, description="Index solveur. Les points sans semaine (non placées, règles) restent inclus."
    ),
    parcours: str | None = Query(None, description="Parcours (ex. `BUT1`)."),
    enseignant: str | None = Query(None, description="Code enseignant."),
    gravite: Literal["a_corriger", "a_revoir"] | None = Query(None),
    nature: Literal[
        "non-placee", "sans-salle", "doublon", "regle", "contrainte", "sae-hors-journee", "compromis-sae", "trouee",
    ]
    | None = Query(None),
) -> Response:
    """Même contenu, mêmes catégories et même ordre que l'écran « À traiter » :
    séances non placées, sans salle, doublons, règles en échec,
    indisponibilités non respectées (`a_corriger`) ; encadrement SAE le même
    jour, journées trouées (`a_revoir`). Trié par urgence : sans semaine,
    semaine en cours, semaines à venir, puis semaines passées.

    Les doublons ne sont inclus que pour un compte `edit` ou `admin`
    (`doublons_inclus`), comme dans l'appli."""
    avec_doublons = _role_au_moins(request, "edit")
    return _repondre(
        request,
        lambda _v: _a_traiter(
            avec_doublons, semaine=semaine, parcours=parcours, enseignant=enseignant, gravite=gravite, nature=nature,
        ),
        en_plus=("doublons" if avec_doublons else "sans-doublons",),
    )


# ── Données de référence manquantes ─────────────────────────────────────

_EXEMPLE_MANQUES = {
    "revision": 1790000000000, "modifie_le": "2026-09-29T10:12:03+00:00", "total": 2,
    "par_gravite": {"bloque_celcat": 1, "bloque_envoi_liens": 1}, "par_famille": {"enseignant": 2},
    "manques": [
        {"id": "enseignant:JHU:code_celcat", "famille": "enseignant", "cle": "JHU", "libelle": "Jules Huet",
         "champ": "code_celcat", "champ_libelle": "Correspondance Celcat", "gravite": "bloque_celcat",
         "usage": "36 séances placées", "nb_seances": 36, "role_requis": "admin",
         "ou_completer": "Écran Celcat, ou ici pour un administrateur.", "ecran": {"vue": "celcat"}},
        {"id": "enseignant:MNI:email", "famille": "enseignant", "cle": "MNI", "libelle": "Marc Nino",
         "champ": "email", "champ_libelle": "Adresse mail", "gravite": "bloque_envoi_liens",
         "usage": "4 séances placées", "nb_seances": 4, "role_requis": "edit",
         "ou_completer": "Annuaire des enseignants, fiche de l'enseignant ou « À traiter ».",
         "ecran": {"vue": "prof", "prof": "MNI"}},
    ],
}


@router.get(
    "/manques", response_model=ManquesV1, tags=_TAGS_CONTROLES,
    summary="Données de référence à compléter", responses=_exemple(_EXEMPLE_MANQUES),
)
def manques(request: Request) -> Response:
    """Tout ce que l'appli signale comme manquant dans les données de
    référence : adresse mail ou nom d'un enseignant, correspondance Celcat
    d'un enseignant, d'une salle, d'une matière ou d'un groupe, type d'une
    salle ajoutée à la main, intitulé d'une matière, salle d'une séance
    placée. Même liste que l'écran « À traiter » (section « Données à
    compléter ») et `GET /reference/manques`.

    `gravite` : `bloque_celcat` (la séance ne peut pas être recopiée dans
    Celcat), `bloque_envoi_liens` (l'enseignant ne reçoit pas son lien
    personnel), `cosmetique`. `role_requis` : rôle qui peut compléter depuis
    l'appli (`null` = fichier de configuration, déploiement). Aucune valeur
    n'y figure — ni adresse, ni code Celcat : seulement ce qui manque."""
    return _repondre(request, lambda _v: reference.manques())


# ── Contraintes ─────────────────────────────────────────────────────────

_TYPES_EXCEPTION = {"teacher_absence": "absence_enseignant", "room_unavailable": "salle_indisponible"}


def _exceptions() -> list[ExceptionV1]:
    """Exceptions ACTIVES, telles que `/app-state` les sert (`ctx.exceptions`)."""
    return [
        ExceptionV1(
            id=int(e["id"]), type=_TYPES_EXCEPTION.get(e["kind"], e["kind"]), date=e["exception_date"],
            enseignant=e.get("teacher_code"), salle_id=e.get("room_id"), creneaux=e.get("slots"),
            motif=e.get("reason"),
        )
        for e in _payload().get("exceptions") or []
        if e.get("active", True)
    ]


def _ecarts(violations: list[dict], reperes: dict[int, tuple[date, int]]) -> list[EcartV1]:
    lundis = {w: r[0] for w, r in reperes.items()}
    sortie = []
    for v in violations:
        if v.get("date"):
            quand = vues.semaine_de_date(lundis, v["date"])
            semaine, jour, date_iso = (quand[0], quand[1], v["date"]) if quand else (None, None, v["date"])
        else:
            semaine, jour = v.get("week"), v.get("day")
            date_iso = _quand(reperes, semaine, jour)["date"]
        sortie.append(EcartV1(
            nature="compromis_sae" if v.get("reason") == "sae_supervision" else "indisponibilite",
            motif=v.get("motif"), cours_code=v["course_code"], semaine=semaine,
            numero_semaine=_quand(reperes, semaine, jour)["numero_semaine"], date=date_iso, jour=jour,
            creneau=v.get("slot"),
        ))
    return sortie


def _contraintes_enseignant(t: dict, reperes, exceptions: list[ExceptionV1]) -> ContraintesEnseignantV1:
    ecarts = _ecarts(t.get("violations") or [], reperes)
    compromis = sum(1 for e in ecarts if e.nature == "compromis_sae")
    declarees = len(ecarts) - compromis
    # `ContraintesView.tsx::verdict` : des écarts sans contrainte déclarée
    # (compromis SAE) restent visibles, contrairement à l'annuaire.
    verdict = "ecarts" if declarees else "compromis_sae" if compromis else "respectee" if t.get("hasConstraint") else "aucune"
    return ContraintesEnseignantV1(
        code=t["code"], nom=t.get("name") or t["code"], contrainte_declaree=bool(t.get("hasConstraint")),
        indisponibilites=t.get("rawIndisponibilites") or "", disponibilites=t.get("rawDisponibilites") or "",
        remarques=t.get("rawContraintes") or "",
        creneaux_interdits=[CreneauInterditV1(jour=d, creneau=s) for d, s in t.get("forbiddenSlots") or []],
        dates_interdites=list(t.get("forbiddenDates") or []), nb_seances=int(t.get("nPlaced") or 0),
        verdict=verdict, nb_ecarts=declarees, nb_compromis_sae=compromis, ecarts=ecarts,
        exceptions=[e for e in exceptions if e.enseignant == t["code"]],
    )


_RANG_VERDICT = {"ecarts": 0, "compromis_sae": 1, "respectee": 2, "aucune": 3}


def _contraintes() -> ContraintesV1:
    payload = _payload()
    reperes = _reperes()
    exceptions = _exceptions()
    enseignants = [_contraintes_enseignant(t, reperes, exceptions) for t in payload.get("teachers") or []]
    enseignants.sort(key=lambda e: (_RANG_VERDICT[e.verdict], -e.nb_ecarts, vues.cle_fr(e.nom)))
    regles = [
        RegleV1(id=c["id"], libelle=c["label"], statut="respectee" if c.get("status") == "pass" else "echec",
                detail=c.get("detail") or "")
        for c in payload.get("ruleChecks") or []
    ]
    regles.sort(key=lambda r: r.statut == "respectee")
    return ContraintesV1(regles=regles, enseignants=enseignants, exceptions=exceptions)


_EXEMPLE_CONTRAINTES_ENSEIGNANT = {
    "code": "MRI", "nom": "MARINE RIGUET", "contrainte_declaree": True,
    "indisponibilites": "mercredi toute la journée", "disponibilites": "", "remarques": "",
    "creneaux_interdits": [{"jour": 2, "creneau": 0}, {"jour": 2, "creneau": 1}], "dates_interdites": [],
    "nb_seances": 96, "verdict": "compromis_sae", "nb_ecarts": 0, "nb_compromis_sae": 1,
    "ecarts": [{"nature": "compromis_sae", "motif": "encadrement_sae", "cours_code": "WR106", "semaine": 6,
                "numero_semaine": 8, "date": "2026-10-13", "jour": 1, "creneau": None}],
    "exceptions": [],
}
_EXEMPLE_CONTRAINTES = {
    "regles": [{"id": "capacite_salle", "libelle": "Capacité des salles", "statut": "respectee",
                "detail": "Toutes les salles accueillent leur effectif."}],
    "enseignants": [_EXEMPLE_CONTRAINTES_ENSEIGNANT],
    "exceptions": [{"id": 3, "type": "absence_enseignant", "date": "2026-10-14", "enseignant": "KBR",
                    "salle_id": None, "creneaux": None, "motif": "Jury"}],
}


@router.get(
    "/contraintes", response_model=ContraintesV1, tags=_TAGS_CONTROLES,
    summary="Règles globales et contraintes des enseignants", responses=_exemple(_EXEMPLE_CONTRAINTES),
)
def contraintes(request: Request) -> Response:
    """L'écran Contraintes : chaque règle institutionnelle avec son verdict
    (échecs d'abord), puis, par enseignant, la contrainte déclarée (texte
    tel quel, créneaux et dates interdits), le verdict recalculé sur le
    planning et le détail des écarts ; enfin les absences ponctuelles."""
    return _repondre(request, lambda _v: _contraintes())


@router.get(
    "/enseignants/{code}/contraintes", response_model=ContraintesEnseignantV1, tags=_TAGS_CONTROLES,
    summary="Contraintes d'un enseignant", responses=_exemple(_EXEMPLE_CONTRAINTES_ENSEIGNANT),
)
def contraintes_enseignant(code: str, request: Request) -> Response:
    """Même contenu qu'une ligne de `/api/v1/contraintes`. Un enseignant
    déclaré sans contrainte ni séance répond `verdict: "aucune"`."""
    def _construire(_v: str) -> ContraintesEnseignantV1:
        payload = _payload()
        t = next((x for x in payload.get("teachers") or [] if x["code"] == code), None)
        if t is None:
            if code not in (payload.get("teacherLabels") or {}):
                raise HTTPException(404, f"Enseignant « {code} » inconnu.")
            t = {"code": code, "name": payload["teacherLabels"][code]}
        return _contraintes_enseignant(t, _reperes(), _exceptions())

    return _repondre(request, _construire)


# ── Charges ─────────────────────────────────────────────────────────────


def _charges(semaine: int | None) -> ChargesV1:
    payload = _payload()
    return ChargesV1(
        semaine=semaine, heures_par_creneau=vues.HEURES_PAR_CRENEAU, creneaux_par_semaine=vues.CRENEAUX_SEMAINE,
        enseignants=[ChargeEnseignantV1(**x) for x in vues.charges_enseignants(payload, semaine)],
        groupes=[ChargeGroupeV1(**x) for x in vues.charges_groupes(payload, semaine)],
        cours=[ChargeCoursV1(**x) for x in vues.charges_cours(payload, semaine)],
        salles=[ChargeSalleV1(**x) for x in vues.charges_salles(payload, semaine)],
        parcours=[ChargeParcoursV1(**x) for x in vues.charges_parcours(payload, semaine)],
    )


_EXEMPLE_CHARGES = {
    "semaine": 5, "heures_par_creneau": 1.5, "creneaux_par_semaine": 30,
    "enseignants": [{"code": "KBR", "nom": "KYLLIAN BRESSON", "heures_semaine": 9.0, "heures_semestre": 229.5,
                     "heures_par_semaine": {"0": 7.5, "1": 9.0}, "nb_seances": 153, "nb_matieres": 3,
                     "nb_non_placees": 0, "contrainte": "respectee", "nb_ecarts": 0}],
    "groupes": [{"id": "but1-tp-a", "libelle": "TP A", "parcours": "BUT1", "type": "tp", "fc": False,
                 "heures_semaine": 27.0, "heures_semestre": 480.0, "heures_par_semaine": {"0": 25.5}}],
    "cours": [{"code": "WR101", "nom": "Anglais", "parcours": "BUT1", "semestre": "S1", "prevues": 62,
               "placees": 61, "non_placees": 1, "heures_semaine": 6.0, "heures_placees": 91.5,
               "heures_par_semaine": {"0": 6.0}, "enseignants": ["TPA"]}],
    "salles": [{"id": "h018", "libelle": "H.018 (Amphi MMI)", "capacite": 150, "type": "amphi",
                "placement_auto": True, "creneaux_occupes": 12, "taux": 0.4, "creneaux_par_semaine": {"0": 10},
                "seances_semestre": 70}],
    "parcours": [{"id": "BUT1", "nb_seances": 1180, "heures_semaine": 120.0, "heures_semestre": 1800.0,
                  "heures_par_semaine": {"0": 118.5}}],
}


@router.get(
    "/charges", response_model=ChargesV1, tags=_TAGS_STATISTIQUES,
    summary="Heures et occupation (annuaires)", responses=_exemple(_EXEMPLE_CHARGES),
)
def charges(
    request: Request,
    semaine: int | None = Query(None, ge=0, description="Index solveur : remplit `heures_semaine` / `creneaux_occupes`."),
) -> Response:
    """Les chiffres des annuaires (Vue Enseignant, TD / TP, Cours, Salle) :

    - enseignant : heures ADDITIONNÉES de ses séances (un bloc de 3 h = 3 h) ;
    - groupe : heures de ce que suit un étudiant du groupe (sa cohorte : CM de
      promo, TD parent, TP), chaque créneau compté UNE fois — deux TP jumelés
      en parallèle durent 1 h 30, pas 3 h ;
    - cours : volume placé face à la maquette ;
    - salle : créneaux occupés sur 30 par semaine, fusions et réservations
      comprises (même règle que « Salles libres ») ;
    - parcours : volume enseigné (somme des séances de ses groupes).

    `heures_par_semaine` donne toutes les semaines d'un coup : inutile
    d'appeler une fois par semaine."""
    return _repondre(request, lambda _v: _charges(semaine))


# ── Modifications manuelles ─────────────────────────────────────────────


def _modifications(semaine: int | None = None) -> ModificationsV1:
    """`GET /diff` (panneau « Modifications ») : séances dont la position
    actuelle diffère de celle de la génération automatique."""
    main = _main()
    state = main.get_state()
    diff = main._calculer_diff(None)
    semestre_defaut = main._export_semestre(state)
    reperes = _reperes()

    def _position(s, w: int, d: int, c: int) -> PositionV1:
        semestre = (s.semestre if s else "") or semestre_defaut
        date_iso = main._date_iso(state, semestre, w, d) or None
        return PositionV1(
            semaine=w, numero_semaine=_quand(reperes, w, d)["numero_semaine"], date=date_iso, jour=d,
            jour_nom=JOURS[d] if 0 <= d < len(JOURS) else "", creneau=c, debut=_heure(c) or "",
        )

    sortie = []
    for e in diff.entries:
        if semaine is not None and semaine not in (e.solver_week, e.current_week):
            continue
        s = state.sessions_by_id.get(e.session_id)
        sortie.append(ModificationV1(
            seance_id=e.session_id, cours_code=e.course_code, cours_nom=s.course_name if s else "",
            generation=_position(s, e.solver_week, e.solver_day, e.solver_slot),
            actuelle=_position(s, e.current_week, e.current_day, e.current_slot),
            verrouillee=e.locked,
        ))
    return ModificationsV1(total_suivies=diff.total, nb_modifiees=diff.changed_count, modifications=sortie)


_EXEMPLE_POSITION = {"semaine": 5, "numero_semaine": 7, "date": "2026-10-05", "jour": 0, "jour_nom": "lundi",
                     "creneau": 0, "debut": "08:00"}
_EXEMPLE_MODIFICATIONS = {"total_suivies": 3050, "nb_modifiees": 1, "modifications": [{
    "seance_id": "WR106-S1-TP-1-but1-tp-a", "cours_code": "WR106",
    "cours_nom": "Expression, communication et rhétorique", "generation": _EXEMPLE_POSITION,
    "actuelle": {**_EXEMPLE_POSITION, "jour": 2, "jour_nom": "mercredi", "date": "2026-10-07"},
    "verrouillee": True,
}]}


@router.get(
    "/modifications", response_model=ModificationsV1, tags=_TAGS_SUIVI,
    summary="Séances déplacées à la main", responses=_exemple(_EXEMPLE_MODIFICATIONS),
)
def modifications(
    request: Request,
    semaine: int | None = Query(None, ge=0, description="Semaine de départ OU d'arrivée (index solveur)."),
) -> Response:
    """Séances déplacées à la main depuis la dernière génération : où la
    génération les avait mises, où elles sont. Les séances créées depuis
    l'interface (hors génération) n'y figurent pas — cf. `personnalisee`
    dans `/api/v1/seances`."""
    return _repondre(request, lambda _v: _modifications(semaine))


# ── Tâches ──────────────────────────────────────────────────────────────


def _taches(colonne: str | None = None, categorie: str | None = None, enseignant: str | None = None) -> list[TacheV1]:
    """`GET /taches` (tableau de suivi), SANS `cree_par` : c'est l'adresse
    mail du compte qui a créé la carte."""
    sortie = []
    for r in _main().list_taches():
        if colonne and r.colonne != colonne:
            continue
        if categorie and r.categorie != categorie:
            continue
        if enseignant and r.enseignant_code != enseignant:
            continue
        sortie.append(TacheV1(
            id=r.id, titre=r.titre, description=r.description, colonne=r.colonne, ordre=r.ordre,
            enseignant=r.enseignant_code, concerne=r.concerne, categorie=r.categorie, priorite=r.priorite,
            date_debut=r.date_debut, date_fin=r.date_fin, cree_le=r.cree_le, maj_le=r.maj_le, fait_le=r.fait_le,
        ))
    return sortie


_EXEMPLE_TACHES = [{
    "id": 12, "titre": "Déplacer le TP de WR106 du groupe A", "description": "Salle Mac indisponible le 14/10.",
    "colonne": "en_cours", "ordre": 2.0, "enseignant": "MRI", "concerne": "Jules", "categorie": "edt",
    "priorite": "urgente", "date_debut": "2026-10-12", "date_fin": "2026-10-14",
    "cree_le": "2026-09-28T08:12:03", "maj_le": "2026-09-29T09:40:11", "fait_le": None,
}]


@router.get(
    "/taches", response_model=list[TacheV1], tags=_TAGS_SUIVI,
    summary="Tâches de suivi (tableau)", responses=_exemple(_EXEMPLE_TACHES),
)
def taches(
    request: Request,
    colonne: Literal["a_faire", "en_cours", "fait"] | None = Query(None),
    categorie: Literal["edt", "plateforme"] | None = Query(None),
    enseignant: str | None = Query(None, description="Code enseignant."),
) -> Response:
    """Les cartes du tableau de suivi de l'équipe (onglet Tâches). L'auteur
    d'une carte n'est pas exposé (c'est une adresse de compte)."""
    return _repondre(request, lambda _v: _taches(colonne, categorie, enseignant))


# ── Calendrier ──────────────────────────────────────────────────────────


def _calendrier(semaine: int | None = None) -> CalendrierV1:
    """Repères du calendrier tels que les grilles les affichent
    (`holidayRows`, `eventRows`, `eventSlotRows`, `saeRows`,
    `roomReservations`, `institutionalCalendar` du payload)."""
    payload = _payload()
    reperes = _reperes()
    lundis = {w: r[0] for w, r in reperes.items()}

    def garder(w: int | None) -> bool:
        return semaine is None or w == semaine

    def base(w: int, d: int) -> dict:
        q = _quand(reperes, w, d)
        return {"semaine": w, "numero_semaine": q["numero_semaine"], "date": q["date"], "jour": d}

    reservations = []
    for r in payload.get("roomReservations") or []:
        quand = vues.semaine_de_date(lundis, str(r.get("date")))
        if not garder(quand[0] if quand else None):
            continue
        reservations.append(ReservationSalleV1(
            salle_id=str(r.get("salle")), date=str(r.get("date")), semaine=quand[0] if quand else None,
            jour=quand[1] if quand else None, creneaux=[int(s) for s in r.get("slots") or []],
            motif=str(r.get("motif") or ""),
        ))
    return CalendrierV1(
        jours_sans_cours=[
            JourSansCoursV1(**base(h["w"], h["d"]), type=h["kind"], libelle=h["label"])
            for h in payload.get("holidayRows") or [] if garder(h["w"])
        ],
        evenements_jour=[
            EvenementJourV1(**base(e["w"], e["d"]), libelles=list(e.get("labels") or []))
            for e in payload.get("eventRows") or [] if garder(e["w"])
        ],
        evenements_creneau=[
            EvenementCreneauV1(
                **base(e["w"], e["d"]), creneau=e["s"], debut=_heure(e["s"]) or "", fin=_heure(e["s"], 1) or "",
                libelle=e["label"], parcours=list(e.get("parcours") or []), salle=e.get("room"),
            )
            for e in payload.get("eventSlotRows") or [] if garder(e["w"])
        ],
        jours_sae=[
            JourSaeV1(**base(s["w"], s["d"]), parcours=s["p"], cours=list(s.get("codes") or []))
            for s in payload.get("saeRows") or [] if garder(s["w"])
        ],
        reservations_salles=reservations,
        periodes_institutionnelles=[
            PeriodeInstitutionnelleV1(libelle=e["label"], debut=str(e["start"]), fin=str(e["end"]), type=e["kind"])
            for e in payload.get("institutionalCalendar") or []
        ],
    )


_EXEMPLE_CALENDRIER = {
    "jours_sans_cours": [{"semaine": 9, "numero_semaine": 11, "date": "2026-11-11", "jour": 2, "type": "ferie",
                          "libelle": "Armistice"}],
    "evenements_jour": [{"semaine": 3, "numero_semaine": 5, "date": "2026-09-24", "jour": 3,
                         "libelles": ["Journée d'intégration"]}],
    "evenements_creneau": [{"semaine": 4, "numero_semaine": 6, "date": "2026-10-01", "jour": 3, "creneau": 3,
                            "debut": "14:00", "fin": "15:30", "libelle": "Conférence métiers",
                            "parcours": ["BUT2-DEV-FI"], "salle": "H.018"}],
    "jours_sae": [{"semaine": 7, "numero_semaine": 9, "date": "2026-10-19", "jour": 0, "parcours": "BUT1",
                   "cours": ["WS101"]}],
    "reservations_salles": [{"salle_id": "h018", "date": "2026-10-06", "semaine": 5, "jour": 1, "creneaux": [2, 3],
                             "motif": "Besoin de la Direction"}],
    "periodes_institutionnelles": [{"libelle": "Vacances de la Toussaint", "debut": "2026-10-24",
                                    "fin": "2026-11-01", "type": "vacances"}],
}


@router.get(
    "/calendrier", response_model=CalendrierV1, tags=_TAGS_CALENDRIER,
    summary="Fériés, vacances, évènements, SAE, réservations", responses=_exemple(_EXEMPLE_CALENDRIER),
)
def calendrier(request: Request, semaine: int | None = _Q_SEMAINE) -> Response:
    """Tout ce que les grilles affichent en plus des séances : jours fériés
    et de vacances, évènements du planning du département (à la journée ou
    sur un créneau), jours réservés aux SAE, salles réservées par des tiers,
    et le calendrier de l'université."""
    return _repondre(request, lambda _v: _calendrier(semaine))


# ── SAE : journées et cours ─────────────────────────────────────────────


_memo_config_sae: tuple[int, dict] | None = None


def _config_sae() -> dict:
    """Configuration SAE, lue par les MÊMES fonctions que `/app-state`
    (`main._build_app_context`) : fenêtres du calendrier officiel + corrections
    locales, phases d'encadrement, SAE que la génération place elle-même.
    Relue une fois par révision (ces fichiers sont des sondes de révision)."""
    global _memo_config_sae
    numero = revision.actuelle().numero
    if _memo_config_sae is not None and _memo_config_sae[0] == numero:
        return _memo_config_sae[1]
    config = _lire_config_sae()
    _memo_config_sae = (numero, config)
    return config


def _lire_config_sae() -> dict:
    from cal_iut.api.ics_feed import periodes_sae
    from cal_iut.ingestion.config_loader import (
        load_sae_teacher_phases,
        load_solver_scheduled_sae,
        load_yaml,
    )
    from cal_iut.ingestion.planning_loader import PlanningBundle, sae_supervisor_dates_by_teacher

    main = _main()
    state = main.get_state()
    # MÊMES fenêtres que les flux .ics (tous semestres, corrections locales,
    # repli de parcours par les séances) : API et agendas ne divergent pas.
    fenetres, parcours_par_code = main.sources_fenetres_sae(state)
    # Jours d'encadrement de chaque référent, fenêtre par fenêtre : même
    # fonction que les compromis « Encadrement SAE » des contraintes.
    encadrement = [sae_supervisor_dates_by_teacher(PlanningBundle(sae_windows=[f]), state.config_dir) for f in fenetres]

    motifs_corrections: dict[tuple[str, str], str] = {}
    chemin = state.config_dir / "sae_corrections.yaml"
    if chemin.exists():
        for c in (load_yaml(chemin) or {}).get("corrections") or []:
            for d in c.get("ajouter") or []:
                motifs_corrections[(str(c.get("course_code")), str(d))] = " ".join(str(c.get("motif") or "").split())

    notes_solveur: dict[tuple[str, str], str] = {}
    regles = state.config_dir / "course_scheduling_rules.yaml"
    if regles.exists():
        for e in (load_yaml(regles) or {}).get("solver_scheduled_sae") or []:
            notes_solveur[(str(e["course_code"]).upper(), str(e["semestre"]))] = " ".join(str(e.get("note") or "").split())
    return {
        "periodes": periodes_sae(fenetres, parcours_par_code),
        "fenetres": fenetres, "encadrement": encadrement, "phases": load_sae_teacher_phases(state.config_dir),
        "corrections": motifs_corrections, "planifiees": load_solver_scheduled_sae(state.config_dir),
        "notes_solveur": notes_solveur,
    }


def _intitules_sae() -> dict[str, str]:
    sortie: dict[str, str] = {}
    for s in _main().get_state().sessions:
        if est_sae(s.course_code):
            sortie.setdefault(s.course_code, s.course_name)
    return sortie


def _commentaire_edt(sessions: list) -> str | None:
    """Commentaire de la maquette pour l'EDT (entités HTML décodées ;
    `UPDATE_OMEGA` est un marqueur technique, pas un commentaire)."""
    import html

    for s in sessions:
        brut = s.metadata.get("commentaire_edt")
        if brut and brut != "UPDATE_OMEGA":
            return html.unescape(str(brut)).strip() or None
    return None


def _seances_sae_placees() -> list[SeanceV1]:
    state = _main().get_state()
    return _seances([p for p in state.timetable if est_sae(p.course_code)])


def _id_journee(parcours: str | None, date_iso: str) -> str:
    return f"{parcours or 'tous'}|{date_iso}"


def _marquer(seance: SeanceV1, cfg: dict, journees: dict) -> SeanceSaeV1:
    """Journée SAE, exception déclarée ou anomalie d'un cours de SAE placé.

    Règle : un cours de SAE n'a lieu QUE sur une journée SAE de son parcours.
    Seule exception déclarée à ce jour : les SAE que la génération place
    elle-même (`solver_scheduled_sae`, ex. WSA501D, sans aucune date au
    calendrier officiel)."""
    journee = None
    if seance.dans_journee_sae and seance.date:
        cle = seance.parcours if seance.date in journees.get(seance.parcours, {}) else None
        journee = _id_journee(cle, seance.date)
    exception = not seance.dans_journee_sae and (seance.cours_code.upper(), seance.semestre) in cfg["planifiees"]
    motif = None
    if exception:
        note = cfg["notes_solveur"].get((seance.cours_code.upper(), seance.semestre)) or ""
        motif = "SAE placée par la génération (`solver_scheduled_sae`)" + (f" : {note}" if note else ".")
    return SeanceSaeV1(
        **seance.model_dump(), journee_sae=journee, exception=exception, motif_exception=motif,
        anomalie=not seance.dans_journee_sae and not exception,
    )


def _saes(parcours: str | None = None, semaine: int | None = None, code: str | None = None) -> SaesV1:
    """Une entrée par SAE (code, semestre, parcours) : maquette, encadrants,
    journées réservées, cours placés (marqués) et non placés."""
    main = _main()
    state = main.get_state()
    cfg = _config_sae()
    journees = _journees_sae_par_parcours()
    reperes = _reperes()
    noms = _libelles_enseignants()
    catalogue = {(c.code, c.semestre, c.parcours): c for c in _cours()}
    manquantes = {m.session_id: _depuis_manquante(m) for m in main.seances_manquantes().manquantes}
    hors_liste = {m.id: m for m in _sae_non_placees_hors_liste(set(manquantes))}
    places = {s.id: _marquer(s, cfg, journees) for s in _seances_sae_placees()}
    lundis = {w: r[0] for w, r in reperes.items()}

    groupes_maquette: dict[tuple[str, str, str], list] = {}
    for s in state.sessions:
        if est_sae(s.course_code) and (code is None or s.course_code == code):
            groupes_maquette.setdefault((s.course_code, s.semestre, s.parcours), []).append(s)

    sortie = []
    for (c, semestre, prc), sessions in sorted(groupes_maquette.items(), key=lambda kv: (vues.cle_parcours(kv[0][2]), kv[0][1], kv[0][0])):
        if parcours and prc != parcours:
            continue
        fenetres = [(f, enc) for f, enc in zip(cfg["fenetres"], cfg["encadrement"], strict=True) if c in f.course_codes]
        groupes_td = sorted({g for f, _e in fenetres for g in f.group_labels or []})
        dates_sae = sorted({
            d for cle in (prc, None) for d, codes in journees.get(cle, {}).items() if c in codes
        })
        jours = [(d, vues.semaine_de_date(lundis, d)) for d in dates_sae]
        seances = sorted((places[s.id] for s in sessions if s.id in places), key=lambda x: (x.date or "", x.debut, x.id))
        non_placees = [manquantes.get(s.id) or hors_liste.get(s.id) for s in sessions if s.id not in places]
        non_placees = [m for m in non_placees if m is not None]
        if semaine is not None:
            jours = [(d, q) for d, q in jours if q and q[0] == semaine]
            seances = [x for x in seances if x.semaine == semaine]
            if not jours and not seances:
                continue
        encadrants: dict[str, EncadrantSaeV1] = {}
        for f, enc in fenetres:
            for prof in f.teachers:
                phases = [
                    PhaseEncadrementV1(debut=ph.debut, fin=ph.fin, sauf=list(ph.exclure), note=ph.note)
                    for ph in cfg["phases"] if ph.course_code == c.upper() and ph.teacher_code == prof.upper()
                ]
                deja = encadrants.get(prof)
                dates = sorted({*(deja.jours if deja else []), *(d.isoformat() for d in enc.get(prof, set()))})
                encadrants[prof] = EncadrantSaeV1(code=prof, nom=noms.get(prof, prof), phases=phases, jours=dates)
        profs = sorted({t for s in sessions for t in s.teacher_codes or []})
        cat = catalogue.get((c, semestre, prc))
        sortie.append(SaeV1(
            code=c, intitule=sessions[0].course_name, parcours=prc, semestre=semestre, annee=sessions[0].annee,
            planifiee_par_solveur=(c.upper(), semestre) in cfg["planifiees"], commentaire_edt=_commentaire_edt(sessions),
            nb_cm=cat.nb_cm if cat else 0, nb_td=cat.nb_td if cat else 0, nb_tp=cat.nb_tp if cat else 0,
            nb_evaluations=cat.nb_evaluations if cat else 0, nb_seances_maquette=len(sessions),
            nb_placees=sum(1 for s in sessions if s.id in places), nb_non_placees=len(non_placees),
            enseignants=profs, enseignants_noms=[noms.get(x, x) for x in profs],
            encadrants=sorted(encadrants.values(), key=lambda e: e.code),
            jours_reserves=[
                JourSaeReserveV1(
                    date=d, semaine=q[0] if q else None, numero_semaine=_numero_semaine(d),
                    jour=date.fromisoformat(d).weekday(), groupes=groupes_td,
                )
                for d, q in jours
            ],
            nb_dans_journee_sae=sum(1 for x in seances if x.dans_journee_sae),
            nb_exceptions=sum(1 for x in seances if x.exception), nb_anomalies=sum(1 for x in seances if x.anomalie),
            seances=seances, non_placees=non_placees,
        ))
    anomalies = [x for e in sortie for x in e.seances if x.anomalie]
    return SaesV1(
        total=len(sortie), nb_seances_maquette=sum(e.nb_seances_maquette for e in sortie),
        nb_placees=sum(e.nb_placees for e in sortie), nb_non_placees=sum(e.nb_non_placees for e in sortie),
        nb_dans_journee_sae=sum(e.nb_dans_journee_sae for e in sortie),
        nb_exceptions=sum(e.nb_exceptions for e in sortie), nb_anomalies=len(anomalies),
        anomalies=anomalies, sae=sortie,
    )


def _numero_semaine(date_iso: str) -> int:
    from cal_iut.calendar.academic import department_week_number

    jour = date.fromisoformat(date_iso)
    return department_week_number(jour - timedelta(days=jour.weekday()))


def _periodes_sae(
    parcours: str | None = None, semaine: int | None = None, du: date | None = None, au: date | None = None,
    code: str | None = None,
) -> list[PeriodeSaeV1]:
    """Les semaines de projet SAÉ : `ics_feed.periodes_sae`, la fonction même
    qui produit les évènements journée entière des flux .ics. Filtre
    `parcours` comme un flux .ics : une SAE au parcours introuvable
    (`parcours: null`) concerne tous les parcours."""
    from cal_iut.api.ics_feed import description_periode_sae, titre_periode_sae

    intitules = _intitules_sae()
    lundis = {w: r[0] for w, r in _reperes().items()}
    sortie = []
    for p in _config_sae()["periodes"]:
        if parcours and p["parcours"] is not None and p["parcours"] != parcours:
            continue
        if code and p["code"] != code:
            continue
        if du and p["fin"] < du or au and p["debut"] > au:
            continue
        jours = [j.isoformat() for j in p["jours"]]
        semaines = sorted({q[0] for j in jours if (q := vues.semaine_de_date(lundis, j))})
        if semaine is not None and semaine not in semaines:
            continue
        sortie.append(PeriodeSaeV1(
            id=f"{p['code']}-{p['debut'].isoformat()}", code=p["code"], intitule=intitules.get(p["code"]),
            libelle=p["label"], titre=titre_periode_sae(p), description=description_periode_sae(p),
            parcours=p["parcours"], groupes=list(p["groupes"] or []), date_debut=p["debut"].isoformat(),
            date_fin=p["fin"].isoformat(), jours=jours, nb_jours=len(jours), semaines=semaines,
            numeros_semaine=sorted({_numero_semaine(j) for j in jours}),
        ))
    return sortie


def _journees_sae(
    parcours: str | None = None, semaine: int | None = None, du: date | None = None, au: date | None = None,
) -> JourneesSaeV1:
    """Journées SAE : les périodes SAE dépliées jour par jour, par parcours,
    avec leur origine, les encadrants attendus et les cours de SAE placés ce
    jour-là."""
    from cal_iut.export.formatter import SLOT_TIMES

    cfg = _config_sae()
    lundis = {w: r[0] for w, r in _reperes().items()}
    noms = _libelles_enseignants()
    intitules = _intitules_sae()
    groupes_par_code = {p["code"]: p["groupes"] or [] for p in cfg["periodes"]}
    places: dict[str, list[SeanceV1]] = {}
    for s in _seances_sae_placees():
        if s.date:
            places.setdefault(s.date, []).append(s)
    sortie = []
    par_parcours: dict[str, int] = {}
    for prc, jours in _journees_sae_par_parcours().items():
        if parcours and prc is not None and prc != parcours:
            continue
        for iso, codes in jours.items():
            q = vues.semaine_de_date(lundis, iso)
            if semaine is not None and (not q or q[0] != semaine):
                continue
            if (du and iso < du.isoformat()) or (au and iso > au.isoformat()):
                continue
            jour_date = date.fromisoformat(iso)
            refs, groupes, encadrants = [], set(), []
            for c in codes:
                motif = cfg["corrections"].get((c, iso))
                refs.append(SaeJourneeRefV1(
                    code=c, intitule=intitules.get(c, c),
                    origine="correction_locale" if motif is not None else "calendrier_officiel", motif=motif or None,
                ))
                groupes.update(groupes_par_code.get(c, []))
                for f, enc in zip(cfg["fenetres"], cfg["encadrement"], strict=True):
                    if c not in f.course_codes or jour_date not in f.dates:
                        continue
                    for prof in f.teachers:
                        if jour_date in enc.get(prof, set()) and not any(
                            e.code == prof and e.sae == c for e in encadrants
                        ):
                            encadrants.append(EncadrantJourneeV1(code=prof, nom=noms.get(prof, prof), sae=c))
            seances = [
                s for s in places.get(iso, [])
                if s.cours_code in codes or (prc is not None and s.parcours == prc)
            ]
            sortie.append(JourneeSaeV1(
                id=_id_journee(prc, iso), date=iso, semaine=q[0] if q else None, numero_semaine=_numero_semaine(iso),
                jour=jour_date.weekday(), jour_nom=JOURS[jour_date.weekday()] if jour_date.weekday() < 5 else "",
                parcours=prc, groupes=sorted(groupes), journee_entiere=True, creneaux=list(range(len(SLOT_TIMES))),
                sae=refs, encadrants=encadrants, seances=seances,
            ))
            cle = prc or "tous"
            par_parcours[cle] = par_parcours.get(cle, 0) + 1
    sortie.sort(key=lambda j: (j.date, vues.cle_parcours(j.parcours or "")))
    return JourneesSaeV1(total=len(sortie), par_parcours=par_parcours, journees=sortie)


_EXEMPLE_SEANCE_SAE = {
    "id": "WSA501D-S5-TD-3-but3-dev-fc", "cours_code": "WSA501D", "cours_nom": "Projet tuteuré",
    "type": "TD", "parcours": "BUT3-DEV-FC", "semestre": "S5", "groupes": ["but3-dev-fc"],
    "groupes_libelles": ["BUT3 DEV FC"], "enseignants": ["KBR"], "enseignants_noms": ["KYLLIAN BRESSON"],
    "salle_id": "h101", "salle_libelle": "H.101", "semaine": 6, "numero_semaine": 8, "date": "2026-10-13",
    "jour": 1, "jour_nom": "mardi", "creneau": 3, "duree_creneaux": 2, "debut": "14:00", "fin": "17:00",
    "horaire_libre": False, "evaluation": False, "verrouillee": False, "personnalisee": False,
    "evenement": False, "sae": True, "dans_journee_sae": False, "journee_sae": None, "exception": True,
    "motif_exception": "SAE placée par la génération (`solver_scheduled_sae`) : …", "anomalie": False,
}
_EXEMPLE_SAE = {
    "code": "WS101", "intitule": "Auditer une communication numérique", "parcours": "BUT1", "semestre": "S1",
    "annee": "BUT1", "planifiee_par_solveur": False, "commentaire_edt": None, "nb_cm": 1, "nb_td": 12,
    "nb_tp": 8, "nb_evaluations": 1, "nb_seances_maquette": 21, "nb_placees": 0, "nb_non_placees": 21,
    "enseignants": ["MRI"], "enseignants_noms": ["MARINE RIGUET"],
    "encadrants": [{"code": "MRI", "nom": "MARINE RIGUET", "phases": [], "jours": ["2026-10-19", "2026-10-20"]}],
    "jours_reserves": [{"date": "2026-10-19", "semaine": 7, "numero_semaine": 9, "jour": 0, "groupes": []}],
    "nb_dans_journee_sae": 0, "nb_exceptions": 0, "nb_anomalies": 0, "seances": [],
    "non_placees": [{"id": "WS101-S1-TD-1-but1-td-ab", "cours_code": "WS101", "type": "TD", "…": "…",
                     "sae": True, "statut": "hors_solveur", "raison": _RAISON_SAE_HORS_SOLVEUR}],
}
_EXEMPLE_SAES = {
    "total": 21, "nb_seances_maquette": 712, "nb_placees": 17, "nb_non_placees": 695, "nb_dans_journee_sae": 0,
    "nb_exceptions": 17, "nb_anomalies": 0, "anomalies": [], "sae": [_EXEMPLE_SAE],
}
_EXEMPLE_JOURNEES = {"total": 1, "par_parcours": {"BUT1": 1}, "journees": [{
    "id": "BUT1|2026-10-19", "date": "2026-10-19", "semaine": 7, "numero_semaine": 9, "jour": 0,
    "jour_nom": "lundi", "parcours": "BUT1", "groupes": [], "journee_entiere": True, "creneaux": [0, 1, 2, 3, 4, 5],
    "sae": [{"code": "WS101", "intitule": "Auditer une communication numérique", "origine": "calendrier_officiel",
             "motif": None}],
    "encadrants": [{"code": "MRI", "nom": "MARINE RIGUET", "sae": "WS101"}], "seances": [],
}]}


@router.get(
    "/sae", response_model=SaesV1, tags=_TAGS_SAE,
    summary="Cours de SAE : maquette, encadrants, placés, non placés", responses=_exemple(_EXEMPLE_SAES),
)
def liste_sae(
    request: Request,
    parcours: str | None = Query(None, description="Parcours (ex. `BUT1`)."),
    semaine: int | None = Query(
        None, ge=0, description="SAE ayant une journée réservée ou un cours placé cette semaine (listes réduites à "
        "cette semaine, sauf `non_placees`).",
    ),
) -> Response:
    """Une entrée par SAE (code `WS…`, semestre, parcours) : volumes de la
    maquette, enseignants, référents et leurs phases d'encadrement, journées
    réservées, cours placés et cours non placés (avec la raison).

    Règle : un cours de SAE n'a lieu QUE sur une journée SAE de son parcours.
    Chaque cours placé dit s'il y est (`dans_journee_sae`) ; hors journée,
    `exception` si c'est déclaré (SAE placée par la génération,
    `solver_scheduled_sae`), sinon `anomalie` — listées en tête (`anomalies`)."""
    return _repondre(request, lambda _v: _saes(parcours, semaine))


_Q_DU_PERIODE = Query(None, description="Périodes qui se terminent à partir de cette date (ISO).")
_Q_AU_PERIODE = Query(None, description="Périodes qui commencent au plus tard à cette date (ISO).")
_EXEMPLE_PERIODES = [{
    "id": "WS501D-2026-10-19", "code": "WS501D",
    "intitule": "Développer pour le web ou Concevoir un dispositif interactif", "libelle": "WS501D",
    "titre": "SAE WS501D", "description": "Semaine de projet/évaluation SAE — WS501D", "parcours": "BUT3-DEV-FI",
    "groupes": [], "date_debut": "2026-10-19", "date_fin": "2026-10-22",
    "jours": ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"], "nb_jours": 4, "semaines": [7],
    "numeros_semaine": [9],
}]


@router.get(
    "/sae/periodes", response_model=list[PeriodeSaeV1], tags=_TAGS_SAE,
    summary="Semaines de projet SAÉ (comme les .ics)", responses=_exemple(_EXEMPLE_PERIODES),
)
def sae_periodes(
    request: Request,
    parcours: str | None = Query(
        None, description="Parcours ; les SAE au parcours introuvable (`parcours: null`) sont toujours incluses."
    ),
    semaine: int | None = _Q_SEMAINE,
    du: date | None = _Q_DU_PERIODE,
    au: date | None = _Q_AU_PERIODE,
) -> Response:
    """Une entrée par période continue de jours SAE (le week-end ne coupe
    pas) : exactement les évènements journée entière « Semaine de
    projet/évaluation SAE — … » des flux .ics, même source, même découpage,
    même `id` (UID de l'évènement)."""
    return _repondre(request, lambda _v: _periodes_sae(parcours, semaine, du, au))


@router.get(
    "/sae/journees", response_model=JourneesSaeV1, tags=_TAGS_SAE,
    summary="Journées SAE (calendrier réservé)", responses=_exemple(_EXEMPLE_JOURNEES),
)
def journees_sae(
    request: Request,
    parcours: str | None = Query(None, description="Parcours (ex. `BUT1`)."),
    semaine: int | None = _Q_SEMAINE,
    du: date | None = _Q_DU,
    au: date | None = _Q_AU,
) -> Response:
    """Les journées réservées aux SAE, par parcours — le bandeau « SAE » de
    la Vue Promo : aucun cours classique du parcours n'y est placé. Pour
    chacune : SAE concernée(s) et d'où vient la journée (calendrier officiel
    ou correction locale), groupes concernés, encadrants attendus, et les
    cours de SAE effectivement placés ce jour-là."""
    return _repondre(request, lambda _v: _journees_sae(parcours, semaine, du, au))


@router.get(
    "/sae/{code}", response_model=SaeDetailV1, tags=_TAGS_SAE,
    summary="Une SAE", responses=_exemple({"code": "WS101", "intitule": "…", "declinaisons": [_EXEMPLE_SAE]}),
)
def une_sae(code: str, request: Request) -> Response:
    """Même contenu qu'une entrée de `/api/v1/sae`, pour chaque parcours où
    la SAE existe."""
    def _construire(_v: str) -> SaeDetailV1:
        declinaisons = _saes(code=code).sae
        if not declinaisons:
            raise HTTPException(404, f"SAE « {code} » inconnue.")
        return SaeDetailV1(code=code, intitule=declinaisons[0].intitule, declinaisons=declinaisons)

    return _repondre(request, _construire)


# ── Celcat (admin) ──────────────────────────────────────────────────────


def _celcat_etat() -> CelcatEtatV1:
    """`GET /celcat/etat` + `GET /celcat/file` — compteurs et dates seulement :
    ni identifiants, ni journal brut, ni chemin."""
    main = _main()
    etat = main._celcat_etat_public()
    file = main.celcat_file()
    return CelcatEtatV1(
        saisie_active=etat.saisie_active, worker_actif=etat.worker_actif, worker_ok=etat.worker_ok,
        semaines_validees=list(etat.semaines_validees), semaines_lancees=list(etat.semaines_lancees),
        semaines_passees=list(etat.semaines_passees), semaines_completes=list(etat.semaines_completes),
        semaines_creation_autorisee=list(etat.semaines_creation_autorisee), valide_le=etat.valide_le,
        dernier_job_lance_le=(etat.dernier_job or {}).get("lance_le"),
        derniere_ecriture_celcat=etat.derniere_ecriture_celcat,
        compteurs=CelcatCompteursV1(
            creees=etat.compteurs.created, modifiees=etat.compteurs.modified,
            supprimees=etat.compteurs.deleted, bloquees=etat.compteurs.blocked,
        ),
        file=CelcatFileV1(
            en_attente=file.en_attente, par_action=dict(file.par_action), dernier_passage_le=file.passe_le,
            age_secondes=file.age_secondes, reussis=file.reussis, echecs=file.echecs, ignores=file.ignores,
            differes=file.differes, resume=file.resume,
        ),
    )


_EXEMPLE_CELCAT = {
    "saisie_active": True, "worker_actif": True, "worker_ok": True, "semaines_validees": [1, 2, 3, 4, 5, 6],
    "semaines_lancees": [5, 6], "semaines_passees": [1, 2, 3, 4], "semaines_completes": [1, 2, 3, 4, 5],
    "semaines_creation_autorisee": [], "valide_le": "2026-09-28T17:02:11+00:00",
    "dernier_job_lance_le": "2026-09-29T02:00:04+00:00", "derniere_ecriture_celcat": "2026-09-29T09:31:40+00:00",
    "compteurs": {"creees": 812, "modifiees": 140, "supprimees": 12, "bloquees": 3},
    "file": {"en_attente": 2, "par_action": {"modifier": 2}, "dernier_passage_le": "2026-09-29T10:05:00+00:00",
             "age_secondes": 42.0, "reussis": 5, "echecs": 0, "ignores": 0, "differes": 2,
             "resume": "5 réussis, 2 en attente d'une semaine ouverte."},
}


@router.get(
    "/celcat/etat", response_model=CelcatEtatV1, tags=_TAGS_ADMIN,
    dependencies=[Depends(accounts.require_role("admin"))],
    summary="Synchronisation Celcat (admin)", responses=_exemple(_EXEMPLE_CELCAT),
)
def celcat_etat(request: Request) -> Response:
    """État de la saisie automatique dans Celcat et de sa file d'attente —
    réservé aux comptes `admin`, comme l'onglet Celcat.

    Le worker Celcat écrit sans passer par l'API : cet état ne suit PAS la
    révision. L'ETag est donc celui du CONTENU (le 304 marche quand même,
    mais la réponse est recalculée à chaque appel)."""
    corps = cache_http.serialiser_json(_celcat_etat())
    entree = cache_http.EntreeCache(etag=cache_http.etag_pour("v1-celcat", corps), corps=corps)
    return cache_http.servir(request, entree)


@router.get("/export", response_model=ExportV1, tags=_TAGS_ETAT)
def export(request: Request) -> Response:
    """Tout en un seul appel, pour un client qui synchronise tout d'un coup
    — à ne relire que quand `/api/v1/version` a changé (ou avec
    `If-None-Match`, qui répond 304 sinon).

    Contient toutes les DONNÉES (référentiel, séances placées et non placées,
    contraintes et absences, calendrier, modifications, tâches). Les vues
    CALCULÉES à partir d'elles (`/a-traiter`, `/charges`,
    `/controles/doublons`) et l'état Celcat restent à leurs endpoints : elles
    dépendent du rôle ou d'un paramètre, et se relisent en 304 de la même
    façon."""

    def _construire(variante: str) -> ExportV1:
        rev = revision.actuelle()
        state = _main().get_state()
        if not state.timetable:
            raise HTTPException(404, "Aucun planning chargé.")
        return ExportV1(
            revision=rev.numero, modifie_le=rev.iso(), jours=_jours(), creneaux=_creneaux(),
            semaines=_semaines(), parcours=_parcours(), groupes=_groupes(), enseignants=_enseignants(variante),
            salles=_salles(), cours=_cours(), seances=_seances(list(state.timetable)),
            seances_non_placees=_non_placees().seances, contraintes=_contraintes(), calendrier=_calendrier(),
            modifications=_modifications().modifications, taches=_taches(),
            sae=ExportSaeV1(periodes=_periodes_sae(), journees=_journees_sae().journees, cours=_saes().sae),
        )

    return _repondre(request, _construire)


# ── Documentation interactive (schéma limité à v1) ──────────────────────
#
# Le schéma de TOUTE l'appli (`/openapi.json`, `/docs`, `/redoc`) était
# public : la carte complète des ≈ 100 routes internes, sans compte (audit du
# 29/09/2026, P2-5). Il est désormais désactivé (`api/main.py`), et seul le
# schéma de v1 est servi — ICI, sous `/api/v1`, donc avec les mêmes droits
# que les données : compte actif (cookie) ou clé API. Un lien public `?t=`
# n'y a pas accès (`_LIEN_PERSO_CHEMINS`).

_schema_v1: bytes | None = None

DESCRIPTION_OPENAPI = """API **en lecture seule** de l'emploi du temps MMI (IUT de Troyes).

- **Authentification** : en-tête `Authorization: Bearer caliut_…` (clé créée dans
  *Menu du compte → Clé API*), ou session ouverte dans l'appli (ce navigateur).
  Besoin d'une clé sans compte dans l'appli ? Demandez à un administrateur un
  compte **« Accès API »** : il ne voit aucune donnée dans l'appli, crée ses clés,
  et ses clés lisent v1 avec les droits d'un compte lecture seule.
- **Sonder** `GET /api/v1/version` (avec `If-None-Match`) et ne relire les données
  que quand `revision` change ; toute réponse porte un ETag et répond `304` sans
  corps si rien n'a changé. `GET /api/v1/export` = tout en un appel.
- **Semaines** : `semaine` = index solveur (celui des paramètres `semaine=`),
  `numero_semaine` = « Semaine N » du département, `semaine_iso` = semaine ISO.
- Guide complet : `docs/API.md` du dépôt.
"""


def schema_openapi_v1() -> dict:
    """Schéma OpenAPI des seules routes `/api/v1` (hors pages de doc)."""
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title="cal-iut — API v1 (lecture)",
        version="1.1.0",
        description=DESCRIPTION_OPENAPI,
        routes=[r for r in router.routes if getattr(r, "include_in_schema", True)],
        tags=OPENAPI_TAGS,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "cleApi": {
            "type": "http", "scheme": "bearer", "bearerFormat": "caliut_…",
            "description": "Clé API du compte (menu du compte → Clé API). Elle hérite du rôle du compte ; "
            "celle d'un compte « Accès API » lit v1 comme un compte lecture seule.",
        },
    }
    schema["security"] = [{"cleApi": []}]
    return schema


@router.get("/openapi.json", include_in_schema=False)
def openapi_v1(request: Request) -> Response:
    global _schema_v1
    if _schema_v1 is None:
        _schema_v1 = cache_http.serialiser_json(schema_openapi_v1())
    entree = cache_http.EntreeCache(etag=cache_http.etag_pour("v1-openapi", _schema_v1), corps=_schema_v1)
    return cache_http.servir(request, entree)


@router.get("/docs", include_in_schema=False)
def docs_v1() -> Response:
    """Swagger UI de FastAPI. Ses fichiers JS/CSS viennent du CDN jsDelivr
    (défaut de FastAPI) : aucun paquet Python ne les embarque ici."""
    from fastapi.openapi.docs import get_swagger_ui_html

    return get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json",
        title="cal-iut — API v1",
        swagger_ui_parameters={"defaultModelsExpandDepth": 0, "docExpansion": "list", "tryItOutEnabled": True},
    )
