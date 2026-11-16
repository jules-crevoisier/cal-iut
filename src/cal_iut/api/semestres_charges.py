"""Les deux groupes de semestres servis ensemble (lot 3 du chantier
« Nouveau semestre depuis l'interface », décision de Jules du 16/11/2026 :
« Les deux semestres ensemble »).

Jusque-là, le serveur restaurait UN run : le dernier en service. Mettre en
service le semestre pair pendant que l'impair tournait aurait fait
disparaître l'automne de l'appli et des agendas. Ici, chaque groupe de
semestres qui a un planning en service est restauré dans SON état
(`api/state.py`) :

- l'état principal est celui du semestre EN COURS à la date du jour — pas
  celui du run le plus récent. C'est lui que lisent Celcat et les tâches de
  fond ;
- l'autre groupe est un état secondaire, que l'interface choisit avec le
  sélecteur impair / pair (en-tête `X-Semestre-Groupe`) ;
- les flux .ics réunissent les deux (`etats_pour_les_flux`).

Tant qu'un seul groupe est en service, rien ne change : même run restauré,
aucun état secondaire.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date

from cal_iut.api import state as etats
from cal_iut.api.state import AppState, get_repo
from cal_iut.calendar.academic import semester_week_offset
from cal_iut.db.models import PlanningRun

logger = logging.getLogger(__name__)

LIBELLES = {
    "odd": {"libelle": "Semestre impair", "semestres": ["S1", "S3", "S5"]},
    "even": {"libelle": "Semestre pair", "semestres": ["S2", "S4", "S6"]},
}
_ANCRES = {"odd": "S1", "even": "S2"}


def _groupe(run: PlanningRun) -> str | None:
    cle = (run.semestre or "").strip().lower()
    return cle if cle in LIBELLES else None


def runs_par_groupe() -> dict[str, PlanningRun]:
    """Le run en service de chaque groupe de semestres (le plus récent qui
    porte des placements)."""
    sortie: dict[str, PlanningRun] = {}
    for run, _nombre in get_repo().runs_en_service():
        groupe = _groupe(run)
        if groupe and groupe not in sortie:
            sortie[groupe] = run
    return sortie


def debut(groupe: str, calendrier: object) -> date | None:
    """Lundi de la première semaine du groupe."""
    lundis = calendrier.teaching_mondays
    indice = semester_week_offset(calendrier, _ANCRES[groupe])
    return lundis[indice] if 0 <= indice < len(lundis) else None


def groupe_en_cours(groupes: list[str], calendrier: object, aujourdhui: date) -> str:
    """Parmi `groupes`, celui dont le semestre est en cours : le dernier à
    avoir commencé. Avant tout début, le premier à commencer."""
    dates = {g: debut(g, calendrier) or date.max for g in groupes}
    commences = [g for g in groupes if dates[g] <= aujourdhui]
    if commences:
        return max(commences, key=lambda g: dates[g])
    return min(groupes, key=lambda g: dates[g])


def restaurer(state: AppState) -> None:
    """Relit le planning en service dans `state` (état principal), et les
    autres groupes de semestres dans des états secondaires."""
    from cal_iut.api import main as api

    etats.definir_secondaires({})
    try:
        runs = runs_par_groupe()
    except Exception:  # noqa: BLE001 — au pire, le comportement d'avant
        logger.exception("Lecture des plannings en service impossible, restauration du dernier run")
        runs = {}
    if len(runs) < 2:
        api._try_restore_latest(state)
        return

    principal = groupe_en_cours(list(runs), state.calendar, api._today())
    api._try_restore_latest(state, runs[principal])
    secondaires: dict[str, AppState] = {}
    for groupe, run in runs.items():
        if groupe == principal:
            continue
        # Copie de l'état principal où tout ce qui appartient à un groupe
        # repart de zéro ; le reste (salles, calendrier…) est partagé.
        vierge = AppState()
        a_part = dataclasses.replace(
            state, **{champ: getattr(vierge, champ) for champ in etats.CHAMPS_PAR_GROUPE}
        )
        api._try_restore_latest(a_part, run)
        secondaires[groupe] = a_part
    etats.definir_secondaires(secondaires)
    logger.info(
        "Deux groupes de semestres en service : %s (principal, run %s), %s",
        principal, runs[principal].id,
        ", ".join(f"{g} (run {runs[g].id})" for g in secondaires),
    )


def pour_payload() -> list[dict[str, object]]:
    """Les groupes entre lesquels l'interface peut basculer, celui du
    semestre en cours d'abord. Un seul, ou aucun : pas de sélecteur."""
    return [
        {"groupe": g, **LIBELLES[g], "principal": i == 0}
        for i, g in enumerate(etats.groupes_charges())
        if g in LIBELLES
    ]


def etats_pour_les_flux() -> list[AppState]:
    """Tous les états en service : un agenda (.ics) couvre l'année, pas
    seulement le semestre affiché."""
    return etats.etats_charges()
