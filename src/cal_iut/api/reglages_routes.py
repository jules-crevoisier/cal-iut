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
from cal_iut.ingestion.config_loader import load_room_reservations
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


def _tout() -> dict:
    return {
        "creneaux": [s.label for s in TimeSlot],
        "salles_reservees": _reservations(),
        "indisponibilites": _indisponibilites(),
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
