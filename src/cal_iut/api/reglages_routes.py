"""Réglages du quotidien modifiables depuis l'interface (lot 6, 16/11/2026).
Routes réservées aux administrateurs.

Deux réglages : les salles réservées par des tiers et les indisponibilités
datées des enseignants. Ce qui est saisi va dans le volume persistant
(`ingestion/reglages.py`), s'applique tout de suite au planning en service
(affectation des salles, contrôle des déplacements) et sera lu par la
prochaine génération. Rien n'est déplacé : une séance déjà placée sur un
créneau devenu indisponible reste où elle est, c'est à l'administrateur de
la déplacer.
"""

from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cal_iut.api import accounts, revision
from cal_iut.api import state as etats
from cal_iut.ingestion import reglages
from cal_iut.ingestion.config_loader import (
    load_groups,
    load_room_assignment_rules,
    load_room_reservations,
    load_rooms,
)
from cal_iut.models.entities import RoomType
from cal_iut.models.timetable import TimeSlot

router = APIRouter(prefix="/reglages", dependencies=[Depends(accounts.require_role("admin"))])


class ReservationRequest(BaseModel):
    salle: str
    date: str
    slots: list[int] = Field(default_factory=list)
    motif: str = ""


class IndisponibiliteRequest(BaseModel):
    teacher_code: str
    date: str
    slots: list[int] = Field(default_factory=list)
    motif: str = ""


def _config():
    return etats.etat_principal().config_dir


def _livrees(fichier: str, cle: str) -> list[dict]:
    chemin = _config() / fichier
    if not chemin.exists():
        return []
    return (yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}).get(cle) or []


def _reservations() -> list[dict]:
    salles = {r.id: r.label for r in etats.etat_principal().rooms}
    sortie = []
    for e in reglages.reservations(_config(), _livrees("salles_reservees.yaml", "reservations")):
        salle = str(e.get("salle"))
        sortie.append({
            "cle": e["cle"], "origine": e["origine"], "salle": salle,
            "salle_libelle": salles.get(salle, salle), "date": str(e.get("date")),
            "slots": reglages._creneaux(e.get("slots")), "motif": str(e.get("motif") or ""),
            "demande_par": str(e.get("demande_par") or ""),
        })
    return sorted(sortie, key=lambda e: (e["date"], e["salle"]))


def _indisponibilites() -> list[dict]:
    retirees = reglages.indisponibilites_retirees(_config())
    sortie = []
    for enseignant in _livrees("teacher_availability.yaml", "teachers"):
        code = str(enseignant.get("teacher_code"))
        for regle in enseignant.get("forbidden_date_slots") or []:
            cle = reglages.cle_indisponibilite(code, regle)
            if cle in retirees:
                continue
            sortie.append({
                "cle": cle, "origine": "livree", "teacher_code": code, "date": str(regle.get("date")),
                "slots": reglages._creneaux(regle.get("slots")), "motif": str(regle.get("note") or ""),
                "demande_par": "",
            })
    for ajout in reglages.indisponibilites_ajoutees(_config()):
        sortie.append({
            "cle": ajout["id"], "origine": "ajoutee", "teacher_code": str(ajout.get("teacher_code")),
            "date": str(ajout.get("date")), "slots": reglages._creneaux(ajout.get("slots")),
            "motif": str(ajout.get("motif") or ""), "demande_par": str(ajout.get("demande_par") or ""),
        })
    return sorted(sortie, key=lambda e: (e["date"], e["teacher_code"]))


class SemaineTypeRequest(BaseModel):
    # La semaine voulue, en entier : les cases (jour 0-4, créneau 0-5) où
    # l'enseignant n'est pas disponible.
    indisponibles: list[tuple[int, int]] = Field(default_factory=list)
    motif: str = ""


_JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
_TOUTES = {(j, c) for j in range(5) for c in range(len(TimeSlot))}


def _semaines_d_origine() -> dict[str, dict]:
    """La semaine type de chaque enseignant AVANT ce que l'écran y change :
    le fichier livré et la feuille des contraintes. `liste_blanche` : ses
    disponibilités sont déclarées comme une liste de créneaux possibles."""
    from cal_iut.ingestion.config_loader import load_teacher_availability
    from cal_iut.ingestion.constraints_loader import load_all_constraints, merge_teacher_availability

    config = _config()
    fusion = merge_teacher_availability(
        load_teacher_availability(config, sans_semaine_type=True), load_all_constraints(config.parents[1]).teachers
    )
    sortie = {}
    for t in fusion:
        interdits = {tuple(c) for c in t.forbidden_slots}
        hors_liste = (_TOUTES - {tuple(c) for c in t.allowed_slots}) if t.allowed_slots else set()
        sortie[t.teacher_code] = {"interdits": interdits, "hors_liste": hors_liste}
    return sortie


def _semaines_types() -> list[dict]:
    saisies = reglages.semaines_types(_config())
    origines = _semaines_d_origine()
    sortie = []
    for code in sorted(set(origines) | set(saisies)):
        origine = origines.get(code, {"interdits": set(), "hors_liste": set()})
        saisie = saisies.get(code, {})
        sortie.append({
            "teacher_code": code,
            "origine": [list(c) for c in sorted(origine["interdits"] | origine["hors_liste"])],
            # Cases que l'écran ne peut pas rendre disponibles.
            "fixes": [list(c) for c in sorted(origine["hors_liste"])],
            "bloques": saisie.get("bloques", []),
            "liberes": saisie.get("liberes", []),
            "motif": saisie.get("motif", ""),
            "demande_par": saisie.get("demande_par", ""),
        })
    return sortie


_TYPES_NON_CHOISIS = (RoomType.RESERVE, RoomType.COMBINED)


def _salles() -> list[dict]:
    """Toutes les salles, avec ce que l'écran a changé à celles du bâtiment."""
    origine = {r.id: r for r in load_rooms(_config(), d_origine=True)}
    saisies = reglages.salles(_config())
    sortie = []
    for r in etats.etat_principal().rooms:
        d_origine = origine.get(r.id)
        sortie.append({
            "id": r.id,
            "label": r.label,
            "capacite": r.capacity,
            "type": r.room_type.value,
            "placement_auto": r.placement_auto,
            "type_fixe": r.room_type in _TYPES_NON_CHOISIS,
            "ajoutee": d_origine is None,
            "origine": None if d_origine is None else {"capacite": d_origine.capacity, "type": d_origine.room_type.value},
            "modifiee": r.id in saisies,
        })
    return sorted(sortie, key=lambda s: s["label"].lower())


def _effectifs() -> list[dict]:
    origine = {g.id: g.headcount for g in load_groups(_config(), d_origine=True)}
    saisis = reglages.effectifs(_config())
    return [
        {
            "id": g.id,
            "label": g.label,
            "parcours": g.parcours,
            "kind": g.kind,
            "effectif": g.headcount,
            "origine": origine.get(g.id, g.headcount),
            "modifie": g.id in saisis,
        }
        for g in load_groups(_config())
    ]


def _recharger_salles_et_groupes() -> None:
    """Le planning en service suit sans redémarrage."""
    from cal_iut.api import custom_rooms

    principal = etats.etat_principal()
    salles = custom_rooms.merge_into(load_rooms(principal.config_dir))
    groupes = load_groups(principal.config_dir)
    from cal_iut.solver.rooms import parse_room_rules

    regles = parse_room_rules(load_room_assignment_rules(principal.config_dir))
    for etat in etats.etats_charges():
        etat.rooms = salles
        etat.groups = groupes
        etat.room_rules = regles
    revision.incrementer("reglages")


def _tout() -> dict:
    return {
        "creneaux": [s.label for s in TimeSlot],
        "jours": _JOURS,
        "salles_reservees": _reservations(),
        "indisponibilites": _indisponibilites(),
        "semaines_types": _semaines_types(),
        "salles": _salles(),
        "types_de_salle": [t.value for t in RoomType if t not in _TYPES_NON_CHOISIS],
        "effectifs": _effectifs(),
        "regles_salles": reglages.regles_salles(_config()),
    }


def _appliquer_en_direct(*, disponibilites: bool) -> None:
    """Le planning en service tient compte du réglage sans redémarrage."""
    from cal_iut.api import main as api

    principal = etats.etat_principal()
    if disponibilites:
        api.charger_disponibilites(principal)
    principal.room_reservations = load_room_reservations(principal.config_dir, principal.calendar)
    for etat in etats.etats_charges():
        if etat is not principal:
            etat.room_reservations = principal.room_reservations
            etat.teacher_availability = principal.teacher_availability
    revision.incrementer("reglages")


def _par(request: Request) -> str:
    return getattr(getattr(request.state, "user", None), "email", None) or "administrateur"


@router.get("")
def lire_reglages() -> dict:
    return _tout()


@router.post("/salles-reservees", status_code=201)
def reserver_une_salle(body: ReservationRequest, request: Request) -> dict:
    salle = body.salle.strip()
    if salle not in {r.id for r in etats.etat_principal().rooms}:
        raise HTTPException(422, "Salle inconnue.")
    try:
        reglages.ajouter(_config(), "salles_reservees", {**body.model_dump(), "salle": salle}, _par(request))
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _appliquer_en_direct(disponibilites=False)
    return _tout()


@router.post("/indisponibilites", status_code=201)
def noter_une_indisponibilite(body: IndisponibiliteRequest, request: Request) -> dict:
    code = body.teacher_code.strip()
    if not code or len(code) > 12 or not code.replace("_", "").isalnum():
        raise HTTPException(422, "Enseignant inconnu.")
    try:
        reglages.ajouter(
            _config(), "indisponibilites", {**body.model_dump(), "teacher_code": code}, _par(request)
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _appliquer_en_direct(disponibilites=True)
    return _tout()


def _retirer(nom: str, cle: str, origine: str) -> dict:
    if origine not in ("livree", "ajoutee"):
        raise HTTPException(422, "Origine inconnue.")
    if not reglages.retirer(_config(), nom, cle, livree=origine == "livree"):
        raise HTTPException(404, "Entrée introuvable, ou déjà retirée.")
    _appliquer_en_direct(disponibilites=nom == "indisponibilites")
    return _tout()


@router.delete("/salles-reservees")
def liberer_une_salle(cle: str, origine: str = "ajoutee") -> dict:
    if origine == "livree" and cle not in {r["cle"] for r in _reservations() if r["origine"] == "livree"}:
        raise HTTPException(404, "Entrée introuvable, ou déjà retirée.")
    return _retirer("salles_reservees", cle, origine)


@router.delete("/indisponibilites")
def retirer_une_indisponibilite(cle: str, origine: str = "ajoutee") -> dict:
    if origine == "livree" and cle not in {r["cle"] for r in _indisponibilites() if r["origine"] == "livree"}:
        raise HTTPException(404, "Entrée introuvable, ou déjà retirée.")
    return _retirer("indisponibilites", cle, origine)


def _code_enseignant(code: str) -> str:
    code = code.strip()
    if not code or len(code) > 12 or not code.replace("_", "").isalnum():
        raise HTTPException(422, "Enseignant inconnu.")
    return code


@router.put("/semaines-types/{code}")
def regler_la_semaine_type(code: str, body: SemaineTypeRequest, request: Request) -> dict:
    """La semaine type d'un enseignant : les créneaux où il n'est jamais
    disponible, quelle que soit la semaine. On envoie la semaine voulue en
    entier ; seul l'écart avec la semaine d'origine est retenu."""
    code = _code_enseignant(code)
    voulue = {(int(j), int(c)) for j, c in body.indisponibles}
    if not voulue <= _TOUTES:
        raise HTTPException(422, "Créneau inconnu.")
    origine = _semaines_d_origine().get(code, {"interdits": set(), "hors_liste": set()})
    if origine["hors_liste"] - voulue:
        raise HTTPException(
            422,
            "Les disponibilités de cet enseignant sont déclarées comme une liste de créneaux possibles : "
            "les autres créneaux ne peuvent pas être rendus disponibles depuis cet écran.",
        )
    avant = origine["interdits"] | origine["hors_liste"]
    try:
        reglages.definir_semaine_type(
            _config(), code, sorted(voulue - avant), sorted(origine["interdits"] - voulue), body.motif, _par(request)
        )
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _appliquer_en_direct(disponibilites=True)
    return _tout()


@router.delete("/semaines-types/{code}")
def revenir_a_la_semaine_d_origine(code: str, request: Request) -> dict:
    code = _code_enseignant(code)
    if code not in reglages.semaines_types(_config()):
        raise HTTPException(404, "Rien n'a été changé à la semaine type de cet enseignant.")
    reglages.definir_semaine_type(_config(), code, [], [], "", _par(request))
    _appliquer_en_direct(disponibilites=True)
    return _tout()


class SalleRequest(BaseModel):
    capacite: int = Field(ge=1, le=reglages.CAPACITE_MAXI)
    type: str
    placement_auto: bool | None = None


@router.put("/salles/{room_id}")
def regler_une_salle(room_id: str, body: SalleRequest, request: Request) -> dict:
    """Capacité, type et placement automatique d'une salle. Pour une salle
    du bâtiment, seul l'écart avec `rooms.yaml` est retenu ; une salle
    ajoutée depuis l'interface est modifiée dans son propre fichier."""
    from cal_iut.api import custom_rooms

    salle = next((r for r in etats.etat_principal().rooms if r.id == room_id), None)
    if salle is None:
        raise HTTPException(404, "Salle inconnue.")
    try:
        type_voulu = RoomType(body.type)
    except ValueError:
        raise HTTPException(422, "Type de salle inconnu.") from None
    if type_voulu != salle.room_type and (salle.room_type in _TYPES_NON_CHOISIS or type_voulu in _TYPES_NON_CHOISIS):
        raise HTTPException(422, "Le type de cette salle ne se change pas depuis cet écran.")
    origine = next((r for r in load_rooms(_config(), d_origine=True) if r.id == room_id), None)
    if origine is None:
        custom_rooms.completer_salle_personnalisee(room_id, capacity=body.capacite, room_type=type_voulu)
    else:
        ecart: dict[str, object] = {}
        if body.capacite != origine.capacity:
            ecart["capacity"] = body.capacite
        if type_voulu != origine.room_type:
            ecart["room_type"] = type_voulu.value
        reglages.definir_salle(_config(), room_id, ecart, _par(request))
    if body.placement_auto is not None and body.placement_auto != salle.placement_auto:
        custom_rooms.set_room_override(room_id, placement_auto=body.placement_auto)
    _recharger_salles_et_groupes()
    return _tout()


@router.delete("/salles/{room_id}")
def revenir_a_la_salle_d_origine(room_id: str, request: Request) -> dict:
    if room_id not in reglages.salles(_config()):
        raise HTTPException(404, "Rien n'a été changé à cette salle.")
    reglages.definir_salle(_config(), room_id, None, _par(request))
    _recharger_salles_et_groupes()
    return _tout()


class EffectifRequest(BaseModel):
    effectif: int = Field(ge=1, le=reglages.EFFECTIF_MAXI)


@router.put("/effectifs/{groupe_id}")
def regler_un_effectif(groupe_id: str, body: EffectifRequest, request: Request) -> dict:
    """Le nombre d'étudiants d'un groupe : il sert au choix des salles et
    au contrôle des capacités."""
    origine = {g.id: g.headcount for g in load_groups(_config(), d_origine=True)}
    if groupe_id not in origine:
        raise HTTPException(404, "Groupe inconnu.")
    reglages.definir_effectif(
        _config(), groupe_id, None if body.effectif == origine[groupe_id] else body.effectif, _par(request)
    )
    _recharger_salles_et_groupes()
    return _tout()


@router.delete("/effectifs/{groupe_id}")
def revenir_a_l_effectif_d_origine(groupe_id: str, request: Request) -> dict:
    if groupe_id not in reglages.effectifs(_config()):
        raise HTTPException(404, "Rien n'a été changé à l'effectif de ce groupe.")
    reglages.definir_effectif(_config(), groupe_id, None, _par(request))
    _recharger_salles_et_groupes()
    return _tout()


class RegleSalleRequest(BaseModel):
    course_code: str
    session_types: list[str] = Field(default_factory=list)
    type_prefere: str
    type_repli: str = ""


@router.post("/regles-salles", status_code=201)
def regler_la_salle_d_un_module(body: RegleSalleRequest, request: Request) -> dict:
    """« Ce module va dans ce type de salle » : la règle passe devant
    celles livrées avec l'application, pour les séances qu'elle vise."""
    choisis = {t.value for t in RoomType if t not in _TYPES_NON_CHOISIS}
    if body.type_prefere not in choisis or (body.type_repli and body.type_repli not in choisis):
        raise HTTPException(422, "Type de salle inconnu.")
    try:
        reglages.ajouter_regle_salle(_config(), body.model_dump(), _par(request))
    except reglages.ReglageInvalide as exc:
        raise HTTPException(422, str(exc)) from exc
    _recharger_salles_et_groupes()
    return _tout()


@router.delete("/regles-salles/{identifiant}")
def retirer_la_regle_de_salle(identifiant: str) -> dict:
    if not reglages.retirer_regle_salle(_config(), identifiant):
        raise HTTPException(404, "Règle introuvable.")
    _recharger_salles_et_groupes()
    return _tout()
