"""Écran « Nouveau semestre » — générer un emploi du temps complet depuis
l'interface (lot 2, 16/11/2026). Routes réservées aux administrateurs.

L'API ne calcule rien : elle crée la génération, lance l'ouvrier
(`generation/ouvrier.py`, processus détaché) et relit son état sur disque
(`generation/taches.py`). Le résultat est un BROUILLON : le planning en
service n'est pas modifié et rien ne part vers Celcat.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cal_iut.api import accounts
from cal_iut.generation import taches

router = APIRouter(prefix="/generations", dependencies=[Depends(accounts.require_role("admin"))])


class GenerationRequest(BaseModel):
    semestre_group: str = Field(description="« odd » (S1, S3, S5) ou « even » (S2, S4, S6)")
    tentatives: int | None = None
    heures: float | None = None
    weeks: int | None = None
    fi_max_week: int | None = None
    num_workers: int | None = None


def _resume(etat: dict) -> dict:
    """Ce que la liste affiche d'une génération (sans les constats ni la
    liste des séances non placées)."""
    resultat = etat.get("resultat") or {}
    return {
        "id": etat["id"],
        "statut": etat["statut"],
        "semestre_group": etat["parametres"]["semestre_group"],
        "cree_le": etat.get("cree_le"),
        "cree_par": etat.get("cree_par"),
        "termine_le": etat.get("termine_le"),
        "run_id": etat.get("run_id"),
        "placees": resultat.get("placees"),
        "a_placer": resultat.get("a_placer"),
        "non_placees": len(resultat.get("non_placees") or []) if resultat else None,
    }


def _detail(etat: dict) -> dict:
    actif = etat["statut"] in taches.STATUTS_ACTIFS
    return {
        **etat,
        # Une génération « en cours » qui ne bat plus attend sa reprise
        # (redémarrage du serveur pendant le calcul).
        "vivante": taches.est_vivante(etat) if actif else False,
        "annulation_demandee": actif and (taches.dossier(etat["id"]) / "annuler").exists(),
        "journal": taches.fin_du_journal(etat["id"]),
    }


@router.get("")
def lister_generations() -> dict:
    etats = taches.lister()
    active = next((e for e in etats if e["statut"] in taches.STATUTS_ACTIFS), None)
    return {
        "groupes": [
            {"cle": cle, **infos, "parametres": taches.parametres_par_defaut(cle)}
            for cle, infos in taches.GROUPES.items()
        ],
        "coeurs": taches.coeurs_disponibles(),
        "active": _detail(active) if active else None,
        "generations": [_resume(e) for e in etats],
    }


@router.post("", status_code=201)
def lancer_generation(body: GenerationRequest, request: Request) -> dict:
    demande = {cle: valeur for cle, valeur in body.model_dump().items() if valeur is not None}
    utilisateur = getattr(request.state, "user", None)
    par = getattr(utilisateur, "email", None) or "administrateur"
    try:
        etat = taches.creer(demande, par)
    except taches.GenerationDejaEnCours as exc:
        raise HTTPException(409, "Une génération est déjà en cours. Attendez sa fin ou annulez-la.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    taches.lancer(etat["id"])
    return _detail(etat)


@router.get("/{generation_id}")
def lire_generation(generation_id: str) -> dict:
    try:
        return _detail(taches.lire(generation_id))
    except taches.GenerationIntrouvable as exc:
        raise HTTPException(404, "Génération introuvable.") from exc


@router.post("/{generation_id}/annuler")
def annuler_generation(generation_id: str) -> dict:
    try:
        return _detail(taches.demander_annulation(generation_id))
    except taches.GenerationIntrouvable as exc:
        raise HTTPException(404, "Génération introuvable.") from exc
