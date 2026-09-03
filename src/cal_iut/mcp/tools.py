"""Outils inspect / plan / apply — fonctions pures, sans protocole MCP.

`plan` ne persiste rien. `apply` n'écrit que si confirm=true, ops non vide,
plan_id concordant s'il est fourni, et aucun item `blocked`.
`force` uniquement si l'item du plan est `forceable` et que l'humain a
posé `force=true` après confirmation. Jamais sur `blocking_conflicts`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from cal_iut.api.state import get_state
from cal_iut.mcp import journal as mcp_journal
from cal_iut.mcp.auth import get_mcp_principal

_REFUS_LECTURE = "Permissions insuffisantes : lecture seule."

_JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
_CRENEAUX = [
    "8h–9h30",
    "9h30–11h",
    "11h–12h30",
    "14h–15h30",
    "15h30–17h",
    "17h–18h30",
]


def inspect(
    teacher_code: str | None = None,
    course_code: str | None = None,
    course_codes: list[str] | None = None,
    session_type: str | None = None,
) -> dict[str, Any]:
    historique = mcp_journal.lire()
    if not teacher_code and not course_code and not course_codes and not session_type:
        return {"index": _index(), "journal": historique}
    seances = _sessions_filtrees(teacher_code, course_code, course_codes, session_type)
    return {
        "sessions": seances,
        "catalog": _catalogue(seances),
        "journal": historique,
    }


def plan(
    teacher_code: str | None = None,
    course_code: str | None = None,
    course_codes: list[str] | None = None,
    session_type: str | None = None,
    op: str | None = None,
    duration_slots: int | None = None,
    slot: int | None = None,
    ops: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refus = _refus_si_lecture_seule()
    if refus is not None:
        return refus
    if ops is not None:
        items = [_evaluer_item(dict(item)) for item in ops]
        return {"plan_id": _plan_id(items), "items": items}

    catalogue = _sessions_filtrees(teacher_code, course_code, course_codes, session_type)
    items: list[dict[str, Any]] = []
    action = op or ("unplace" if duration_slots is None and slot is None else "reshape")
    for seance in catalogue:
        if action == "unplace" and not seance["placed"]:
            continue
        brut: dict[str, Any] = {"session_id": seance["session_id"], "op": action}
        if duration_slots is not None:
            brut["duration_slots"] = duration_slots
        if slot is not None:
            brut["slot"] = slot
        items.append(_evaluer_item(brut))
    return {"plan_id": _plan_id(items), "items": items}


def apply(
    confirm: bool = False,
    ops: list[dict[str, Any]] | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    refus = _refus_si_lecture_seule()
    if refus is not None:
        return refus
    items = list(ops or [])
    if not confirm or not items:
        return {"ok": False, "forced": False}
    if any(item.get("status") == "blocked" for item in items):
        return {"ok": False, "forced": False}
    if plan_id is not None and plan_id != _plan_id(items):
        return {"ok": False, "forced": False}

    from fastapi import HTTPException

    force_utilise = False
    try:
        for item in items:
            if _veut_force(item):
                force_utilise = True
            _executer_item(item)
    except HTTPException as exc:
        return {"ok": False, "forced": False, "error": _fmt_http(exc)}

    mcp_journal.append(_entree_journal(plan_id or _plan_id(items), force_utilise, items))
    return {"ok": True, "forced": force_utilise}


def _refus_si_lecture_seule() -> dict[str, Any] | None:
    """Hors HTTP (tests unitaires) il n'y a pas de principal : ne pas refuser.
    En requête MCP, `read_only` ne peut ni planifier ni appliquer."""
    principal = get_mcp_principal()
    if principal is None:
        return None
    from cal_iut.api.accounts import ROLE_ORDER

    if ROLE_ORDER.get(principal.role, -1) < ROLE_ORDER["edit"]:
        return {"ok": False, "error": _REFUS_LECTURE}
    return None


def _entree_journal(plan_id: str, force_utilise: bool, items: list[dict[str, Any]]) -> dict[str, Any]:
    entree: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "plan_id": plan_id,
        "forced": force_utilise,
        "ops": [_journal_op(item) for item in items],
    }
    principal = get_mcp_principal()
    if principal is not None and principal.via == "user_key" and principal.email:
        entree["email"] = principal.email
    return entree


def _plan_id(items: list[dict[str, Any]]) -> str:
    canon = json.dumps(items, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _veut_force(item: dict[str, Any]) -> bool:
    return bool(item.get("force")) and bool(item.get("forceable")) and item.get("status") != "blocked"


def _journal_op(item: dict[str, Any]) -> dict[str, Any]:
    garde = (
        "op", "session_id", "session_b", "week", "day", "slot", "room_id",
        "duration_slots", "session_type", "teacher_codes", "is_eval",
        "course_code", "group_ids", "force",
    )
    return {cle: item[cle] for cle in garde if cle in item}


def _fmt_http(exc: object) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail or exc)


# --- inspect -----------------------------------------------------------------

def _index() -> dict[str, Any]:
    state = get_state()
    codes_cours = sorted({s.course_code for s in state.sessions})
    codes_prof = sorted({c for s in state.sessions for c in (s.teacher_codes or [])})
    cal = getattr(state, "calendar", None)
    return {
        "n_sessions": len(state.sessions),
        "n_placed": len(state.timetable),
        "course_codes": codes_cours,
        "teacher_codes": codes_prof,
        "n_weeks": getattr(cal, "weeks", 0) or 0,
        "hint": "Passer teacher_code ou course_code pour les séances et le catalogue.",
    }


def _sessions_filtrees(
    teacher_code: str | None,
    course_code: str | None,
    course_codes: list[str] | None,
    session_type: str | None,
) -> list[dict[str, Any]]:
    state = get_state()
    places = {p.session_id: p for p in state.timetable}
    seances = []
    for seance in state.sessions:
        if teacher_code and teacher_code.upper() not in {c.upper() for c in seance.teacher_codes}:
            continue
        if course_code and seance.course_code != course_code:
            continue
        if course_codes and seance.course_code not in course_codes:
            continue
        if session_type and str(getattr(seance.session_type, "value", seance.session_type)) != session_type:
            continue
        pose = places.get(seance.id)
        seances.append({
            "session_id": seance.id,
            "course_code": seance.course_code,
            "session_type": str(getattr(seance.session_type, "value", seance.session_type)),
            "teacher_codes": list(seance.teacher_codes),
            "teachers": [{"code": c, "label": _etiquette_enseignant(state, c)} for c in seance.teacher_codes],
            "group_ids": list(seance.group_ids or []),
            "duration_slots": seance.duration_slots,
            "is_eval": bool(getattr(seance, "is_eval", False)),
            "placed": pose is not None,
            "week": pose.week if pose else None,
            "day": pose.day if pose else None,
            "slot": pose.slot if pose else None,
            "room_id": getattr(pose, "room_id", None) if pose else None,
            "room_label": getattr(pose, "room_label", None) if pose else None,
        })
    return seances


def _etiquette_enseignant(state: object, code: str) -> str:
    for cours in getattr(state, "courses", []) or []:
        lead = getattr(cours, "lead", None)
        if lead is not None and getattr(lead, "code", None) == code:
            return _nom_prof(lead) or code
        for bloc in getattr(cours, "profs", []) or []:
            prof = getattr(bloc, "teacher", None)
            if prof is not None and getattr(prof, "code", None) == code:
                return _nom_prof(prof) or code
    return code


def _nom_prof(prof: object) -> str:
    prenom = str(getattr(prof, "prenom", "") or "").strip()
    nom = str(getattr(prof, "nom", "") or "").strip()
    return f"{prenom} {nom}".strip()


def _catalogue(seances: list[dict[str, Any]]) -> dict[str, Any]:
    state = get_state()
    codes_prof = sorted({c for s in seances for c in s.get("teacher_codes") or []})
    ids_groupes = {g for s in seances for g in s.get("group_ids") or []}
    cal = getattr(state, "calendar", None)
    semaines = []
    if cal is not None:
        for i in range(getattr(cal, "weeks", 0) or 0):
            label = cal.department_week_label(i) or f"Semaine {i + 1}"
            semaines.append({"index": i, "label": label})
    salles = [
        {
            "id": r.id,
            "label": r.label,
            "capacity": r.capacity,
            "room_type": str(getattr(r.room_type, "value", r.room_type)),
        }
        for r in (state.rooms or [])
    ]
    groupes = [
        {"id": g.id, "label": g.label, "kind": g.kind, "parcours": g.parcours}
        for g in (state.groups or [])
        if not ids_groupes or g.id in ids_groupes
    ]
    non_placees = [s for s in seances if not s.get("placed")]
    dispos = []
    for d in getattr(state, "teacher_availability", []) or []:
        if d.teacher_code not in codes_prof:
            continue
        dispos.append({
            "teacher_code": d.teacher_code,
            "forbidden_slots": [list(x) for x in (d.forbidden_slots or [])],
            "preferred_slots": [list(x) for x in (d.preferred_slots or [])],
            "notes": d.notes,
        })
    return {
        "teachers": [{"code": c, "label": _etiquette_enseignant(state, c)} for c in codes_prof],
        "rooms": salles,
        "groups": groupes,
        "weeks": semaines,
        "days": [{"index": i, "label": n} for i, n in enumerate(_JOURS)],
        "slots": [{"index": i, "label": n} for i, n in enumerate(_CRENEAUX)],
        "unplaced": [{"session_id": s["session_id"], "course_code": s["course_code"]} for s in non_placees],
        "constraints": {"teacher_availability": dispos},
    }


# --- plan evaluation ---------------------------------------------------------

def _evaluer_item(item: dict[str, Any]) -> dict[str, Any]:
    action = str(item.get("op") or "")
    try:
        if action == "unplace":
            return _evaluer_unplace(item)
        if action == "place":
            return _evaluer_place(item)
        if action == "move":
            return _evaluer_move(item)
        if action == "swap":
            return _evaluer_swap(item)
        if action == "salle":
            return _evaluer_salle(item)
        if action == "seance":
            return _evaluer_seance(item)
        if action == "reshape":
            return _evaluer_reshape(item)
        if action == "custom_create":
            return _evaluer_custom_create(item)
        if action == "custom_patch":
            return _evaluer_custom_patch(item)
        if action == "custom_delete":
            return _evaluer_custom_delete(item)
    except Exception as exc:  # noqa: BLE001 — un item illisible reste un plan, pas un crash
        return _marquer(item, [str(exc)], [str(exc)], [])
    return _marquer(item, [f"Opération inconnue : {action}"], [f"Opération inconnue : {action}"], [])


def _marquer(
    item: dict[str, Any],
    blocking: list[str],
    hard: list[str],
    soft: list[str],
) -> dict[str, Any]:
    blocking = list(dict.fromkeys(blocking))
    hard = list(dict.fromkeys(hard))
    soft = list(dict.fromkeys(soft))
    item["blocking_conflicts"] = blocking
    item["hard_conflicts"] = hard
    item["warnings"] = soft
    if blocking:
        item["status"] = "blocked"
        item["forceable"] = False
        item["reason"] = blocking[0]
    elif hard:
        item["status"] = "ok"
        item["forceable"] = True
        item["reason"] = hard[0]
    else:
        item["status"] = "ok"
        item["forceable"] = False
        if "reason" in item:
            del item["reason"]
    return item


def _evaluer_unplace(item: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    sid = str(item.get("session_id") or "")
    if sid not in state.sessions_by_id:
        return _marquer(item, [f"Séance {sid} inconnue"], [f"Séance {sid} inconnue"], [])
    return _marquer(item, [], [], [])


def _evaluer_place(item: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    sid = str(item.get("session_id") or "")
    session = state.sessions_by_id.get(sid)
    if session is None:
        return _marquer(item, [f"Séance {sid} inconnue"], [f"Séance {sid} inconnue"], [])
    if any(p.session_id == sid for p in state.timetable):
        msg = "Cette séance est déjà au planning"
        return _marquer(item, [msg], [msg], [])
    manquants = [c for c in ("week", "day", "slot") if item.get(c) is None]
    if manquants:
        msg = f"Champs manquants : {', '.join(manquants)}"
        return _marquer(item, [msg], [msg], [])
    return _analyser_creneau(
        item, session, int(item["week"]), int(item["day"]), int(item["slot"]),
        item.get("room_id"),
    )


def _evaluer_move(item: dict[str, Any]) -> dict[str, Any]:
    from cal_iut.api.main import validate_placement
    from cal_iut.api.schemas import MoveSessionRequest
    from fastapi import HTTPException

    sid = str(item.get("session_id") or "")
    manquants = [c for c in ("week", "day", "slot") if item.get(c) is None]
    if manquants:
        msg = f"Champs manquants : {', '.join(manquants)}"
        return _marquer(item, [msg], [msg], [])
    try:
        resp = validate_placement(
            sid,
            MoveSessionRequest(
                week=int(item["week"]),
                day=int(item["day"]),
                slot=int(item["slot"]),
                room_id=item.get("room_id"),
                force=False,
            ),
        )
    except HTTPException as exc:
        return _depuis_http(item, exc)
    return _marquer(item, list(resp.blocking_conflicts or []), list(resp.hard_conflicts or []), list(resp.soft_warnings or []))


def _evaluer_swap(item: dict[str, Any]) -> dict[str, Any]:
    from cal_iut.api.main import _controler_echange, _find_placement

    state = get_state()
    sid_a = str(item.get("session_id") or "")
    sid_b = str(item.get("session_b") or "")
    if not sid_b or sid_a == sid_b:
        msg = "Échange : session_b obligatoire et distinct"
        return _marquer(item, [msg], [msg], [])
    from fastapi import HTTPException

    try:
        a = _find_placement(state, sid_a)
        b = _find_placement(state, sid_b)
    except HTTPException as exc:
        return _depuis_http(item, exc)
    seance_a = state.sessions_by_id.get(sid_a)
    seance_b = state.sessions_by_id.get(sid_b)
    pos_a = (a.week, a.day, a.slot)
    pos_b = (b.week, b.day, b.slot)
    a.week, a.day, a.slot = pos_b
    b.week, b.day, b.slot = pos_a
    try:
        durs, bloquants, doux = _controler_echange(
            state,
            [(a, seance_a, getattr(a, "room_id", None)), (b, seance_b, getattr(b, "room_id", None))],
            {sid_a, sid_b},
            False,
        )
    except HTTPException as exc:
        a.week, a.day, a.slot = pos_a
        b.week, b.day, b.slot = pos_b
        return _depuis_http(item, exc)
    a.week, a.day, a.slot = pos_a
    b.week, b.day, b.slot = pos_b
    return _marquer(item, list(bloquants), list(durs), list(doux))


def _evaluer_salle(item: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    sid = str(item.get("session_id") or "")
    room_id = str(item.get("room_id") or "")
    if sid not in {p.session_id for p in state.timetable}:
        msg = f"Séance {sid} absente du planning"
        return _marquer(item, [msg], [msg], [])
    if room_id and not any(r.id == room_id for r in state.rooms):
        msg = f"Salle {room_id} inconnue"
        return _marquer(item, [msg], [msg], [])
    return _marquer(item, [], [], [])


def _evaluer_seance(item: dict[str, Any]) -> dict[str, Any]:
    from cal_iut.api.session_patch import codes_enseignants_connus

    state = get_state()
    sid = str(item.get("session_id") or "")
    session = state.sessions_by_id.get(sid)
    if session is None:
        return _marquer(item, [f"Séance {sid} inconnue"], [f"Séance {sid} inconnue"], [])
    duree = item.get("duration_slots")
    if duree is not None and int(duree) not in (1, 2):
        msg = "La durée n'accepte que 1 (1h30) ou 2 (3h)."
        return _marquer(item, [msg], [msg], [])
    teachers = item.get("teacher_codes")
    if teachers is not None:
        inconnus = [c for c in teachers if c not in codes_enseignants_connus(state)]
        if inconnus:
            msg = f"Enseignant inconnu : {', '.join(inconnus)}"
            return _marquer(item, [msg], [msg], [])
    is_eval = item.get("is_eval")
    type_seance = item.get("session_type") or str(getattr(session.session_type, "value", session.session_type))
    if is_eval is True and str(type_seance).upper() != "CM":
        msg = "is_eval n'est autorisé que sur un CM"
        return _marquer(item, [msg], [msg], [])
    if item.get("week") is not None or item.get("day") is not None or item.get("slot") is not None:
        pose = next((p for p in state.timetable if p.session_id == sid), None)
        if pose is None:
            msg = "Séance non placée : pas de déplacement via seance"
            return _marquer(item, [msg], [msg], [])
        week = pose.week if item.get("week") is None else int(item["week"])
        day = pose.day if item.get("day") is None else int(item["day"])
        slot = pose.slot if item.get("slot") is None else int(item["slot"])
        evalue = _evaluer_move({**item, "op": "move", "week": week, "day": day, "slot": slot})
        evalue["op"] = "seance"
        return evalue
    return _marquer(item, [], [], [])


def _evaluer_reshape(item: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    sid = str(item.get("session_id") or "")
    pose = next((p for p in state.timetable if p.session_id == sid), None)
    if pose is None:
        return _marquer(item, [], [], [])
    if item.get("slot") is not None and int(item["slot"]) != pose.slot:
        evalue = _evaluer_move({
            **item,
            "op": "move",
            "week": pose.week,
            "day": pose.day,
            "slot": int(item["slot"]),
        })
        evalue["op"] = "reshape"
        return evalue
    duree = item.get("duration_slots")
    if duree is not None and int(duree) not in (1, 2):
        msg = "La durée n'accepte que 1 (1h30) ou 2 (3h)."
        return _marquer(item, [msg], [msg], [])
    return _marquer(item, [], [], [])


def _evaluer_custom_create(item: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    code = str(item.get("course_code") or "")
    cours = next((c for c in (state.courses or []) if c.code == code), None)
    if cours is None:
        msg = f"Matière inconnue : {code}"
        return _marquer(item, [msg], [msg], [])
    groupes = list(item.get("group_ids") or [])
    if not groupes:
        msg = "group_ids obligatoire"
        return _marquer(item, [msg], [msg], [])
    connus = {g.id for g in state.groups}
    inconnus = [g for g in groupes if g not in connus]
    if inconnus:
        msg = f"Groupe(s) inconnu(s) : {', '.join(inconnus)}"
        return _marquer(item, [msg], [msg], [])
    manquants = [c for c in ("week", "day", "slot") if item.get(c) is None]
    if manquants:
        msg = f"Champs manquants : {', '.join(manquants)}"
        return _marquer(item, [msg], [msg], [])
    faux = SimpleNamespace(
        id="mcp-preview",
        teacher_codes=list(item.get("teacher_codes") or []),
        semestre=cours.semestre,
        parcours=cours.parcours,
        annee=cours.annee,
        duration_slots=int(item.get("duration_slots") or 1),
        group_ids=groupes,
        course_code=cours.code,
        locked=False,
    )
    return _analyser_creneau(
        item, faux, int(item["week"]), int(item["day"]), int(item["slot"]),
        item.get("room_id"), session_id="mcp-preview",
    )


def _evaluer_custom_patch(item: dict[str, Any]) -> dict[str, Any]:
    state = get_state()
    sid = str(item.get("session_id") or "")
    seance = state.sessions_by_id.get(sid)
    if seance is None or not (seance.metadata or {}).get("custom_session"):
        msg = f"Aucune séance personnalisée « {sid} »"
        return _marquer(item, [msg], [msg], [])
    return _marquer(item, [], [], [])


def _evaluer_custom_delete(item: dict[str, Any]) -> dict[str, Any]:
    return _evaluer_custom_patch(item)


def _analyser_creneau(
    item: dict[str, Any],
    session: object,
    week: int,
    day: int,
    slot: int,
    room_id: str | None,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    from cal_iut.api.main import (
        _as_placed,
        _build_conflict_map,
        _conflits_deplacement,
        _is_duo_synced,
        _resolve_room,
        _DUO_SYNC_NOTE,
    )
    from cal_iut.api.validation import validate_move
    from cal_iut.calendar.academic import week_status

    state = get_state()
    sid = session_id or getattr(session, "id", "")
    blocking: list[str] = []
    hard: list[str] = []
    soft: list[str] = []

    statut = week_status(state.calendar, session.semestre, week)
    if statut != "future":
        hard.append(f"Semaine {week + 1} non modifiable (statut : {statut})")

    if _is_duo_synced(session, state.teacher_duos):
        hard.append(_DUO_SYNC_NOTE)

    # Même point d'entrée que le côté HTTP (`api/main.py::_conflits_deplacement`)
    # — un seul endroit décide de ce qui est institutionnel (jamais
    # contournable) vs force-able (ordre pédagogique, indisponibilité
    # enseignant), pour éviter que les deux surfaces divergent en silence.
    institutional, pedago = _conflits_deplacement(state, session, week, day, slot)
    blocking.extend(institutional)
    hard.extend(institutional)
    hard.extend(pedago)

    if room_id:
        salle = next((r for r in state.rooms if r.id == room_id), None)
        salle_id = getattr(salle, "id", None)
    else:
        salle = _resolve_room(state, session, week, day, slot, None)
        salle_id = getattr(salle, "id", None)

    validation = validate_move(
        sid, week, day, slot, _as_placed(state.timetable),
        list(session.group_ids or []), list(session.teacher_codes or []),
        salle_id,
        sessions_by_id=state.sessions_by_id, groups=state.groups,
        conflicting_room_ids=_build_conflict_map(state.rooms).get(salle_id, set()) if salle_id else None,
    )
    if not validation.valid:
        hard.extend(validation.hard_conflicts)
        soft.extend(validation.soft_warnings)
    return _marquer(item, blocking, hard, soft)


def _depuis_http(item: dict[str, Any], exc: object) -> dict[str, Any]:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        blocking = list(detail.get("blocking_conflicts") or [])
        hard = list(detail.get("hard_conflicts") or [])
        soft = list(detail.get("soft_warnings") or [])
        if not hard and not blocking:
            hard = [str(detail.get("message") or detail)]
        return _marquer(item, blocking, hard, soft)
    msg = str(detail or exc)
    return _marquer(item, [], [msg], [])


# --- apply -------------------------------------------------------------------

def _executer_item(item: dict[str, Any]) -> None:
    action = str(item.get("op") or "")
    sid = str(item.get("session_id") or "")
    force = _veut_force(item)

    if action == "unplace":
        # Même chemin que POST /placements/{id}/deposer : noter le placement
        # retiré + file Celcat `delete` si la saisie est armée.
        from cal_iut.api.main import deposer_placement
        deposer_placement(sid)
        return

    if action == "place":
        from cal_iut.api.main import placer_seance
        from cal_iut.api.schemas import MoveSessionRequest
        placer_seance(sid, MoveSessionRequest(
            week=int(item["week"]), day=int(item["day"]), slot=int(item["slot"]),
            room_id=item.get("room_id"), force=force,
        ))
        return

    if action == "move":
        from cal_iut.api.main import move_session
        from cal_iut.api.schemas import MoveSessionRequest
        move_session(sid, MoveSessionRequest(
            week=int(item["week"]), day=int(item["day"]), slot=int(item["slot"]),
            room_id=item.get("room_id"), force=force,
        ))
        return

    if action == "swap":
        from cal_iut.api.main import echanger_placements
        from cal_iut.api.schemas import EchangeRequest
        echanger_placements(EchangeRequest(
            session_a=sid, session_b=str(item["session_b"]), force=force,
        ))
        return

    if action == "salle":
        from cal_iut.api.main import changer_salle
        from cal_iut.api.schemas import ChangeRoomRequest
        changer_salle(sid, ChangeRoomRequest(room_id=str(item.get("room_id") or ""), force=force))
        return

    if action == "seance":
        from cal_iut.api.session_patch import appliquer_patch_seance
        appliquer_patch_seance(
            sid,
            teacher_codes=item.get("teacher_codes"),
            session_type=item.get("session_type"),
            duration_slots=int(item["duration_slots"]) if item.get("duration_slots") is not None else None,
            week=int(item["week"]) if item.get("week") is not None else None,
            day=int(item["day"]) if item.get("day") is not None else None,
            slot=int(item["slot"]) if item.get("slot") is not None else None,
            room_id=item.get("room_id"),
            is_eval=item.get("is_eval"),
            force=force,
        )
        return

    if action == "custom_create":
        from cal_iut.api.main import creer_seance_personnalisee
        from cal_iut.api.schemas import CreerSeanceRequest
        resultat = creer_seance_personnalisee(CreerSeanceRequest(
            course_code=str(item["course_code"]),
            session_type=str(item.get("session_type") or "TD"),
            group_ids=list(item["group_ids"]),
            teacher_codes=list(item.get("teacher_codes") or []),
            duration_slots=int(item.get("duration_slots") or 1),
            is_eval=bool(item.get("is_eval") or False),
            week=int(item["week"]),
            day=int(item["day"]),
            slot=int(item["slot"]),
            room_id=item.get("room_id"),
            force=force,
        ))
        item["session_id"] = resultat.session_id
        return

    if action == "custom_patch":
        from cal_iut.api.main import modifier_seance_personnalisee
        from cal_iut.api.schemas import ModifierSeancePersonnaliseeRequest
        modifier_seance_personnalisee(sid, ModifierSeancePersonnaliseeRequest(
            session_type=item.get("session_type"),
            group_ids=item.get("group_ids"),
            teacher_codes=item.get("teacher_codes"),
            duration_slots=item.get("duration_slots"),
            is_eval=item.get("is_eval"),
            week=item.get("week"),
            day=item.get("day"),
            slot=item.get("slot"),
            room_id=item.get("room_id"),
            force=force,
        ))
        return

    if action == "custom_delete":
        from cal_iut.api.main import supprimer_seance_personnalisee
        supprimer_seance_personnalisee(sid)
        return

    from cal_iut.api.deposer import deposer_seance
    from cal_iut.api.session_patch import appliquer_patch_seance

    if action == "reshape" or item.get("duration_slots") is not None or item.get("slot") is not None:
        duree = item.get("duration_slots")
        if duree is not None:
            appliquer_patch_seance(sid, duration_slots=int(duree), force=force)
        cible_slot = item.get("slot")
        if cible_slot is not None:
            _deplacer_slot(sid, int(cible_slot), force=force)
        return

    raise KeyError(action)


def _deplacer_slot(session_id: str, slot: int, *, force: bool = False) -> None:
    from cal_iut.api.main import _find_placement, get_state, move_session
    from cal_iut.api.schemas import MoveSessionRequest

    match = _find_placement(get_state(), session_id)
    if match.slot == slot:
        return
    move_session(
        session_id,
        MoveSessionRequest(week=match.week, day=match.day, slot=slot, force=force),
    )
