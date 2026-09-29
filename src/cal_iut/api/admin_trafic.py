"""Routes d'administration de l'anti-aspiration (29/09/2026) : trafic par
IP et liste de blocage. Rôle admin uniquement ; sous `/admin`, donc
protégées par `require_auth` (`_PROTECTED_PREFIXES`) ET par
`require_role("admin")` sur chaque route.

Les routes de blocage fonctionnent même en mode `off` : on peut préparer
la liste avant d'activer quoi que ce soit (elle ne s'applique qu'à partir
de `observe`). Le trafic, lui, n'est compté qu'à partir de `observe`.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from cal_iut.api import accounts
from cal_iut.api import anti_aspiration as aa
from cal_iut.api.schemas import (
    BlocageCreateRequest,
    BlocageListResponse,
    BlocageResponse,
    TraficResponse,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(accounts.require_role("admin"))])

_RESUME_VIDE = {"requetes": 0, "depassements": 0, "refus_403": 0, "refus_acces": 0, "clients": 0}


def _emails(ids: set[int]) -> dict[int, str]:
    """Adresse des comptes vus dans le tableau (au plus `limite` lectures)."""
    if not ids:
        return {}
    from cal_iut.api.state import get_state
    from cal_iut.db.accounts_repository import AccountRepository
    from cal_iut.db.session import get_db

    repo = AccountRepository(get_db(get_state().db_path))
    resultat = {}
    for i in ids:
        user = repo.get_by_id(i)
        if user is not None:
            resultat[i] = user.email
    return resultat


@router.get("/trafic", response_model=TraficResponse)
def admin_trafic(
    fenetre: Literal["15min", "1h", "24h"] = "1h", limite: int = Query(50, ge=1, le=500),
) -> TraficResponse:
    etat = aa.etat_public()
    comptage_actif = etat["protections"]["actives"] or etat["mode"] != "off"
    instantane = (
        aa.trafic.instantane(aa.FENETRES[fenetre], limite=limite)
        if comptage_actif
        else {"resume": dict(_RESUME_VIDE), "clients": []}
    )
    actifs = aa.blocages.lister()
    emails = _emails({c["compte_id"] for c in instantane["clients"] if c.get("compte_id") is not None})
    clients = []
    for c in instantane["clients"]:
        b = aa.blocages.correspondance(c["ip"], c["user_agent"], inclure_debit=True)
        clients.append({**c, "compte_email": emails.get(c.get("compte_id")), "blocage_id": b.id if b else None})
    return TraficResponse(
        mode=etat["mode"],
        variable=etat["variable"],
        comptage_actif=comptage_actif,
        fenetre=fenetre,
        genere_le=datetime.now(UTC).isoformat(timespec="seconds"),
        protections=etat["protections"],
        budgets=etat["budgets"],
        bannissement=etat["bannissement"],
        exemptes=etat["exemptes"],
        resume={**instantane["resume"], "ip_bloquees": sum(1 for b in actifs if b.type in ("ip", "cidr"))},
        clients=clients,
    )


def _reponse(b: aa.Blocage) -> BlocageResponse:
    return BlocageResponse(**b.__dict__)


@router.get("/blocages", response_model=BlocageListResponse)
def admin_lister_blocages() -> BlocageListResponse:
    return BlocageListResponse(mode=aa.mode(), blocages=[_reponse(b) for b in aa.blocages.lister()])


def _vise_soi(type_: str, valeur: str, request: Request) -> bool:
    ip, adresse = aa._ip_normalisee(request.client.host if request.client else "")
    if type_ == "ip":
        return ip == valeur
    if type_ == "cidr":
        reseau = ipaddress.ip_network(valeur)
        return adresse is not None and adresse.version == reseau.version and adresse in reseau
    return valeur.lower() in (request.headers.get("user-agent") or "").lower()


@router.post("/blocages", response_model=BlocageResponse, status_code=201)
def admin_ajouter_blocage(body: BlocageCreateRequest, request: Request) -> BlocageResponse | JSONResponse:
    # Corps d'erreur `{"message": ...}` à plat, même convention que
    # `/admin/users` (cf. `api/main.py::admin_update_user`).
    try:
        valeur = aa.valider_cible(body.type, body.valeur)
        duree_s = aa.lire_duree(body.duree) if body.duree else None
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})

    # Garde-fou : bloquer sa propre IP (ou son navigateur) coupe l'accès à
    # l'écran même qui permettrait de se débloquer.
    if not body.forcer and _vise_soi(body.type, valeur, request):
        return JSONResponse(
            status_code=409,
            content={
                "message": "Ce blocage vous viserait vous-même (votre adresse ou votre navigateur). "
                "Confirmez avec « forcer » si c'est bien voulu."
            },
        )

    user = request.state.user  # posé par `require_auth`, toujours présent ici
    return _reponse(aa.blocages.ajouter(body.type, valeur, body.motif, user.email, duree_s))


@router.delete("/blocages/{blocage_id}", response_model=None)
def admin_retirer_blocage(blocage_id: str) -> dict | JSONResponse:
    retire = aa.blocages.retirer(blocage_id)
    if retire is None:
        return JSONResponse(status_code=404, content={"message": "Blocage introuvable."})
    # Une IP débloquée repart d'un compteur de refus nul : sinon son premier
    # dépassement la rebannirait aussitôt.
    if retire.type == "ip":
        aa.trafic.oublier_refus(retire.valeur)
    return {"ok": True}
