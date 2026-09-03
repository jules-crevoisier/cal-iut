"""Hook post-écriture planning → file d'attente Celcat.

Ne doit jamais faire échouer une réponse HTTP de placement : toute
exception est avalée par `apres_ecriture_planning`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cal_iut.api.state import get_state
from cal_iut.celcat.etat import charger, live_actuel
from cal_iut.celcat.file_attente import (
    autoriser_suppression,
    enfiler,
    evenement_connu,
    retenir_evenement,
)
from cal_iut.celcat.lecture import EvenementCelcat
from cal_iut.celcat.logs import append as append_log
from cal_iut.celcat.mapping import SLOT_TIMES, libelle_groupe_celcat, load_celcat_config

_placement_retire: Any = None

_CHEMIN_GROUPES_CELCAT = (
    Path(__file__).resolve().parents[3] / "data" / "config" / "celcat_groupes.yaml"
)
_GROUPES_CELCAT: dict[str, int] | None = None


def _groupes_celcat() -> dict[str, int]:
    """IDs Celcat des groupes (`data/config/celcat_groupes.yaml`) — la même
    source que `ecriture.py::_groupes_connus`, lue ici en pure local (aucun
    appel RPC) pour porter un `group_id` sur chaque job de suppression, y
    compris quand l'événement Live n'a pas encore été vu par ce process."""
    global _GROUPES_CELCAT
    if _GROUPES_CELCAT is None:
        lus: dict[str, int] = {}
        if _CHEMIN_GROUPES_CELCAT.exists():
            data = yaml.safe_load(_CHEMIN_GROUPES_CELCAT.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                for cle, val in data.items():
                    try:
                        lus[str(cle)] = int(val)
                    except (TypeError, ValueError):
                        continue
        _GROUPES_CELCAT = lus
    return _GROUPES_CELCAT


def _group_id_celcat(session: Any) -> int | None:
    if session is None:
        return None
    semestre = str(getattr(session, "semestre", "") or "").strip()
    groupe_label = _libelle_groupe(session).strip()
    if not semestre or not groupe_label:
        return None
    nom = f"BUT MMI {semestre} {libelle_groupe_celcat(groupe_label)}"
    return _groupes_celcat().get(nom)


def noter_placement_retire(placement: Any) -> None:
    global _placement_retire
    _placement_retire = placement


def apres_ecriture_planning(session_id: str, action: str) -> None:
    try:
        _executer(session_id, action)
    except Exception:
        return


def _event_id_journal(row: dict[str, Any]) -> int | None:
    brut = row.get("event_id")
    if brut in (None, "", 0, "0"):
        return None
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def _placement_pour(session_id: str) -> Any:
    state = get_state()
    trouve = next((p for p in state.timetable if p.session_id == session_id), None)
    if trouve is not None:
        return trouve
    if getattr(_placement_retire, "session_id", None) == session_id:
        return _placement_retire
    return None


def _sans_code_celcat(session: Any) -> str | None:
    if session is None:
        return None
    state = get_state()
    cfg = load_celcat_config(state.config_dir)
    code = str(getattr(session, "course_code", "") or "").upper()
    if not code:
        return None
    if not cfg.modules.get(code):
        return f"{getattr(session, 'course_code', code)} sans code Celcat"
    return None


def _libelle_groupe(session: Any) -> str:
    state = get_state()
    labels = {g.id: g.label for g in state.groups}
    ids = list(getattr(session, "group_ids", None) or [])
    if not ids:
        return ""
    return str(labels.get(ids[0], ids[0]))


def _creneau(placement: Any) -> tuple[int, str]:
    slot = int(getattr(placement, "slot", 0) or 0)
    jour = int(getattr(placement, "day", 0) or 0) + 1
    heure = SLOT_TIMES[slot][0] if 0 <= slot < len(SLOT_TIMES) else ""
    return jour, heure


def correspond_live(session: Any, placement: Any, ev: EvenementCelcat) -> bool:
    code = str(getattr(session, "course_code", "") or "").strip().upper()
    if not code:
        return False
    nom = (ev.module_nom or "").upper()
    if not nom.startswith(code):
        return False
    groupe = _libelle_groupe(session).strip().upper()
    vu = ev.groupe_nom.strip().upper()
    if groupe and groupe not in vu and vu != groupe:
        return False
    jour, heure = _creneau(placement)
    if ev.jour and ev.jour != jour:
        return False
    if ev.heure_debut and heure and ev.heure_debut != heure:
        return False
    return True


def _trouver_evenement(event_id: int) -> EvenementCelcat | None:
    for ev in live_actuel():
        if ev.event_id == event_id:
            retenir_evenement(ev)
            return ev
    return evenement_connu(event_id)


def _executer(session_id: str, action: str) -> None:
    doc = charger()
    if not doc.get("saisie_active"):
        return

    state = get_state()
    session = state.sessions_by_id.get(session_id)
    motif = _sans_code_celcat(session)
    if motif:
        append_log(
            kind="blocked",
            motif=motif,
            session_id=session_id,
            course_code=getattr(session, "course_code", None),
        )
        try:
            from cal_iut.api import notifications

            notifications.signaler(
                "celcat_echec",
                f"{session_id} : {motif}",
            )
            notifications.envoyer_si_temps_ecoule()
        except Exception:  # noqa: BLE001
            pass
        return

    journal = doc.get("journal") or {}
    row = journal.get(session_id) if isinstance(journal, dict) else None
    event_id = _event_id_journal(row) if isinstance(row, dict) else None
    placement = _placement_pour(session_id)
    semaine = getattr(placement, "week", None)

    if action == "create":
        if event_id is None:
            job: dict[str, Any] = {"action": "create", "session_id": session_id}
            if semaine is not None:
                job["semaine"] = semaine
            enfiler(job)
        return

    if action == "update":
        if event_id is not None:
            job = {"action": "update", "session_id": session_id, "event_id": event_id}
            if semaine is not None:
                job["semaine"] = semaine
            enfiler(job)
            return
        job = {"action": "create", "session_id": session_id}
        if semaine is not None:
            job["semaine"] = semaine
        enfiler(job)
        return

    if action != "delete":
        return

    # Résolu depuis la config locale (jamais un appel RPC) : porté sur
    # CHAQUE job de suppression, y compris quand l'événement Live n'a pas
    # encore été vu par ce process — cf. `_group_id_celcat`.
    group_id = _group_id_celcat(session)

    if event_id is not None:
        ev = _trouver_evenement(event_id)
        if ev is not None and not autoriser_suppression(ev):
            return
        if group_id is None and ev is not None:
            group_id = ev.group_id
        job: dict[str, Any] = {"action": "delete", "session_id": session_id, "event_id": event_id}
        if group_id is not None:
            job["group_id"] = group_id
        if semaine is not None:
            job["semaine"] = semaine
        enfiler(job)
        return

    if session is None or placement is None:
        return
    hits = [ev for ev in live_actuel() if correspond_live(session, placement, ev)]
    if len(hits) != 1:
        return
    unique = hits[0]
    if not autoriser_suppression(unique):
        return
    job = {"action": "delete", "session_id": session_id, "event_id": unique.event_id}
    gid = group_id if group_id is not None else unique.group_id
    if gid is not None:
        job["group_id"] = gid
    if semaine is not None:
        job["semaine"] = semaine
    enfiler(job)
