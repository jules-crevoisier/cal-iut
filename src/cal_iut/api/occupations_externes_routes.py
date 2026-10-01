"""Écran Celcat → « Occupations hors MMI » (01/10/2026) — routes admin.

`GET /celcat/occupations-externes` : le dernier relevé déposé par le
sidecar (date, ressources surveillées, nombre par ressource, liste, séances
déjà placées en conflit). `POST /celcat/occupations-externes/rafraichir` :
« Relire maintenant », une DEMANDE que le sidecar honore à son prochain
passage — même mécanisme que la relecture de l'instantané. L'API ne lit
jamais Celcat elle-même (cf. `celcat/instantane.py`).

Pour un client de l'API : `GET /api/v1/occupations-externes` (compte actif,
lecture seule, ETag) — cf. `api/v1.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cal_iut.api import accounts
from cal_iut.api import occupations_externes as oe
from cal_iut.celcat import occupations as occ

router = APIRouter(prefix="/celcat", dependencies=[Depends(accounts.require_role("admin"))])


@router.get("/occupations-externes")
def occupations_externes_admin() -> dict:
    from cal_iut.api.state import get_state

    return oe.pour_admin(get_state())


@router.post("/occupations-externes/rafraichir")
def occupations_externes_rafraichir() -> dict:
    occ.demander()
    return {
        "demande": True,
        "message": "Relecture demandée — le sidecar la fera à son prochain passage (moins d'une minute, "
                   "puis le temps de lire Celcat).",
    }
