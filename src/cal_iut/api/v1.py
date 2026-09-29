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
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from cal_iut.api import cache_http, revision

router = APIRouter(prefix="/api/v1")

_TAGS_ETAT = ["v1 · état"]
_TAGS_REFERENTIEL = ["v1 · référentiel"]
_TAGS_SEANCES = ["v1 · séances"]
_TAGS_SALLES = ["v1 · salles"]

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")

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


class CoursDetailV1(BaseModel):
    code: str
    nom: str
    declinaisons: list[CoursV1]


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


# ── Outils communs ──────────────────────────────────────────────────────


def _main():
    # Import tardif : `api/main.py` importe ce module pour monter le routeur.
    from cal_iut.api import main

    return main


def _repondre(request: Request, construire) -> Response:
    """ETag + cache par (révision, chemin, paramètres, variante). `t` (lien
    personnel) est retiré de la clé : il ne change que la variante, déjà
    comptée à part — sans ça chaque lien perso aurait son propre cache."""
    variante = _main().variante_lecture(request)
    parametres = tuple(sorted((k, v) for k, v in request.query_params.multi_items() if k != "t"))
    cle = ("v1", request.url.path, parametres, variante)
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


def _un_cours(code: str) -> CoursDetailV1:
    declinaisons = [c for c in _cours() if c.code == code]
    if not declinaisons:
        raise HTTPException(404, f"Cours « {code} » inconnu.")
    return CoursDetailV1(code=code, nom=declinaisons[0].nom, declinaisons=declinaisons)


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
        )
        return _paginer(_seances(placements), du, au, limite, decalage)

    return _repondre(request, _construire)


@router.get("/export", response_model=ExportV1, tags=_TAGS_ETAT)
def export(request: Request) -> Response:
    """Tout en un seul appel, pour un client qui synchronise tout d'un coup
    — à ne relire que quand `/api/v1/version` a changé (ou avec
    `If-None-Match`, qui répond 304 sinon)."""

    def _construire(variante: str) -> ExportV1:
        rev = revision.actuelle()
        state = _main().get_state()
        if not state.timetable:
            raise HTTPException(404, "Aucun planning chargé.")
        return ExportV1(
            revision=rev.numero, modifie_le=rev.iso(), jours=_jours(), creneaux=_creneaux(),
            semaines=_semaines(), parcours=_parcours(), groupes=_groupes(), enseignants=_enseignants(variante),
            salles=_salles(), cours=_cours(), seances=_seances(list(state.timetable)),
        )

    return _repondre(request, _construire)
