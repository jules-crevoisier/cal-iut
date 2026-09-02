"""Job de nuit : pousser les semaines validées + scanner les extras Live."""

from __future__ import annotations

from typing import Any

from cal_iut.api.state import get_state
from cal_iut.celcat.etat import charger, live_actuel
from cal_iut.celcat.extras import enregistrer, lister as lister_extras
from cal_iut.celcat.file_attente import enfiler
from cal_iut.celcat.lecture import (
    EvenementCelcat,
    est_cours,
    est_fantome,
    est_ferie,
    evenement_depuis_rpc,
)
from cal_iut.celcat.ops import correspond_live


def _event_id(row: dict[str, Any]) -> int | None:
    brut = row.get("event_id")
    if brut in (None, "", 0, "0"):
        return None
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


def _group_ids_depuis_nom(nom: str) -> list[str]:
    if not nom.strip():
        return []
    state = get_state()
    cible = nom.strip().upper()
    for groupe in state.groups:
        label = str(getattr(groupe, "label", "") or "").strip()
        semestre = str(getattr(groupe, "semestre", "") or "").strip()
        compose = f"BUT MMI {semestre} {label}".strip().upper()
        if cible == compose or (label and label.upper() in cible):
            return [str(groupe.id)]
    return []


def _teacher_codes_depuis_nom(nom: str) -> list[str]:
    if not nom.strip():
        return []
    state = get_state()
    morceaux = nom.strip().upper()
    codes: list[str] = []
    for cours in state.courses:
        for bloc in getattr(cours, "profs", []) or []:
            prof = getattr(bloc, "teacher", None)
            if prof is None:
                continue
            nom_prof = f"{getattr(prof, 'nom', '')} {getattr(prof, 'prenom', '')}".upper()
            code = str(getattr(prof, "code", "") or "")
            if code and (getattr(prof, "nom", "").upper() in morceaux or morceaux in nom_prof):
                if code not in codes:
                    codes.append(code)
    return codes


def _code_depuis_ev(ev: EvenementCelcat) -> str:
    nom = (ev.module_nom or "").strip()
    if nom:
        return nom.split()[0]
    return (ev.module_code or "").strip()


def _evenements_depuis_page(page: Any) -> list[EvenementCelcat]:
    reponses = getattr(page, "reponses", None)
    if not isinstance(reponses, dict):
        return []
    bruts = reponses.get("udlTimetables.load")
    if not isinstance(bruts, list):
        return []
    evenements: list[EvenementCelcat] = []
    for brut in bruts:
        if not isinstance(brut, dict):
            continue
        groupes = brut.get("groups") if isinstance(brut.get("groups"), list) else []
        tete = groupes[0] if groupes and isinstance(groupes[0], dict) else {}
        gid = int(tete["id"]) if tete.get("id") is not None else 0
        gnom = str(tete.get("name") or "")
        evenements.append(evenement_depuis_rpc(brut, group_id=gid, groupe_nom=gnom))
    return evenements


def _a_un_match_caliut(ev: EvenementCelcat) -> bool:
    state = get_state()
    for placement in state.timetable:
        session = state.sessions_by_id.get(placement.session_id)
        if session is None:
            continue
        if correspond_live(session, placement, ev):
            return True
    return False


def _scanner_extras(page: Any, doc: dict[str, Any]) -> None:
    evenements = list(live_actuel())
    vus = {ev.event_id for ev in evenements}
    if page is not None:
        for ev in _evenements_depuis_page(page):
            if ev.event_id not in vus:
                evenements.append(ev)
                vus.add(ev.event_id)

    ignores = doc.get("ignores") if isinstance(doc.get("ignores"), dict) else {}
    existants = {str(x.get("id")): x for x in lister_extras()}

    for ev in evenements:
        if not est_cours(ev) or est_ferie(ev) or est_fantome(ev):
            continue
        extra_id = f"extra-{ev.event_id}"
        if extra_id in ignores or str(ev.event_id) in ignores:
            continue
        deja = existants.get(extra_id)
        if deja and deja.get("statut") in ("ignore", "ajoute"):
            continue
        if _a_un_match_caliut(ev):
            continue
        code = _code_depuis_ev(ev)
        group_ids = _group_ids_depuis_nom(ev.groupe_nom)
        teacher_codes = _teacher_codes_depuis_nom(ev.enseignant)
        semaine = ev.indice_semaine
        enregistrer(
            {
                "id": extra_id,
                "statut": "ouvert",
                "course_code": code,
                "module_nom": ev.module_nom,
                "libelle": ev.module_nom,
                "event_id": ev.event_id,
                "groupe": ev.groupe_nom,
                "group_ids": group_ids,
                "teacher_codes": teacher_codes,
                "jour": ev.jour,
                "heure_debut": ev.heure_debut,
                "heure_fin": ev.heure_fin,
                "salle": ev.salle,
                "enseignant": ev.enseignant,
                "semaine": semaine,
            }
        )


def executer_job_nuit(page: Any = None) -> None:
    from datetime import datetime, timezone

    from cal_iut.celcat.etat import sauver, semaines_celcat_passees

    doc = charger()
    if not doc.get("saisie_active"):
        return

    validees = {int(s) for s in (doc.get("semaines_validees") or [])}
    deja_lancees = {int(s) for s in (doc.get("semaines_lancees") or [])}
    passees = set(semaines_celcat_passees())
    semaines = validees - deja_lancees - passees
    state = get_state()
    journal = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}

    places = [p for p in state.timetable if p.week in semaines]
    ids_places = {p.session_id for p in places}

    for placement in places:
        row = journal.get(placement.session_id)
        eid = _event_id(row) if isinstance(row, dict) else None
        if eid is None:
            enfiler(
                {
                    "action": "create",
                    "session_id": placement.session_id,
                    "semaine": placement.week,
                }
            )
        else:
            enfiler(
                {
                    "action": "update",
                    "session_id": placement.session_id,
                    "event_id": eid,
                    "semaine": placement.week,
                }
            )

    for session_id, row in journal.items():
        if not isinstance(row, dict):
            continue
        try:
            sem = int(row.get("semaine", -1))
        except (TypeError, ValueError):
            continue
        if sem not in semaines or session_id in ids_places:
            continue
        eid = _event_id(row)
        if eid is None:
            continue
        enfiler(
            {
                "action": "delete",
                "session_id": session_id,
                "event_id": eid,
                "semaine": sem,
            }
        )

    _scanner_extras(page, doc)

    doc = charger()
    lancees = {int(s) for s in (doc.get("semaines_lancees") or [])}
    doc["semaines_lancees"] = sorted(lancees | semaines)
    doc["dernier_job"] = {"lance_le": datetime.now(timezone.utc).isoformat()}
    sauver(doc)
