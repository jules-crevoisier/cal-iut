"""PATCH d'une séance de maquette : enseignant(s), type, durée, salle,
position, évaluation.

Même pile de conflits que `move_session` / `placer_seance`. `force` ne
lève que les conflits de ressources ; PAC / SAE / indispo enseignant
restent bloquants.
"""

from __future__ import annotations

from fastapi import HTTPException

from cal_iut.api.schemas import ChangeRoomRequest, MoveSessionRequest, PlacementResponse
from cal_iut.api.session_overrides import upsert_overlay
from cal_iut.api.state import get_state
from cal_iut.api.validation import validate_move
from cal_iut.models.entities import SessionType


def codes_enseignants_connus(state: object) -> set[str]:
    codes: set[str] = set()
    for seance in getattr(state, "sessions", []) or []:
        codes.update(seance.teacher_codes or [])
    for cours in getattr(state, "courses", []) or []:
        lead = getattr(cours, "lead", None)
        if lead is not None and getattr(lead, "code", None):
            codes.add(lead.code)
        for bloc in getattr(cours, "profs", []) or []:
            prof = getattr(bloc, "teacher", None)
            if prof is not None and getattr(prof, "code", None):
                codes.add(prof.code)
    for dispo in getattr(state, "teacher_availability", []) or []:
        code = getattr(dispo, "teacher_code", None)
        if code:
            codes.add(code)
    return codes


def appliquer_patch_seance(
    session_id: str,
    *,
    teacher_codes: list[str] | None = None,
    session_type: str | None = None,
    duration_slots: int | None = None,
    week: int | None = None,
    day: int | None = None,
    slot: int | None = None,
    room_id: str | None = None,
    is_eval: bool | None = None,
    force: bool = False,
) -> PlacementResponse:
    from cal_iut.api.main import _to_placement, changer_salle, move_session

    identite = (
        teacher_codes is not None
        or session_type is not None
        or duration_slots is not None
        or is_eval is not None
    )
    position = week is not None or day is not None or slot is not None
    if not identite and not position and room_id is None:
        raise HTTPException(400, "Au moins un champ à modifier (enseignant, type, durée, salle, semaine ou évaluation).")
    if duration_slots is not None and duration_slots not in (1, 2):
        raise HTTPException(400, "La durée n'accepte que 1 (1h30) ou 2 (3h).")

    state = get_state()
    session = state.sessions_by_id.get(session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")

    if teacher_codes is not None:
        connus = codes_enseignants_connus(state)
        inconnus = [c for c in teacher_codes if c not in connus]
        if inconnus:
            raise HTTPException(400, f"Enseignant inconnu : {', '.join(inconnus)}")

    nouveau_type: SessionType | None = None
    if session_type is not None:
        try:
            nouveau_type = SessionType(session_type)
        except ValueError as exc:
            raise HTTPException(400, f"Type de séance invalide : {session_type}") from exc

    snapshot_teachers = list(session.teacher_codes)
    snapshot_type = session.session_type
    snapshot_duree = session.duration_slots
    snapshot_eval = session.is_eval
    placement = next((p for p in state.timetable if p.session_id == session_id), None)
    snapshot_placement_teachers = list(placement.teacher_codes) if placement is not None else []

    if teacher_codes is not None:
        session.teacher_codes = list(teacher_codes)
        if placement is not None:
            placement.teacher_codes = list(teacher_codes)
    if nouveau_type is not None:
        session.session_type = nouveau_type
    if duration_slots is not None:
        session.duration_slots = duration_slots
    if is_eval is not None:
        session.is_eval = is_eval

    def restaurer() -> None:
        session.teacher_codes = snapshot_teachers
        session.session_type = snapshot_type
        session.duration_slots = snapshot_duree
        session.is_eval = snapshot_eval
        if placement is not None:
            placement.teacher_codes = snapshot_placement_teachers

    deplace = False
    if placement is not None and position:
        cible_week = placement.week if week is None else week
        cible_day = placement.day if day is None else day
        cible_slot = placement.slot if slot is None else slot
        deplace = (cible_week, cible_day, cible_slot) != (placement.week, placement.day, placement.slot)
        if deplace:
            try:
                move_session(
                    session_id,
                    MoveSessionRequest(
                        week=cible_week,
                        day=cible_day,
                        slot=cible_slot,
                        room_id=room_id or None,
                        force=force,
                    ),
                )
            except HTTPException as exc:
                restaurer()
                raise _conflit_structure(exc) from exc
            except Exception:
                restaurer()
                raise

    if placement is not None and identite and not deplace:
        try:
            _controler_placement(state, session, placement, force)
        except HTTPException:
            restaurer()
            raise
        except Exception:
            restaurer()
            raise

    if room_id is not None and (not deplace or not room_id.strip()):
        try:
            changer_salle(session_id, ChangeRoomRequest(room_id=room_id, force=force))
        except HTTPException as exc:
            restaurer()
            raise _conflit_structure(exc) from exc
        except Exception:
            restaurer()
            raise

    overlay: dict[str, object] = {}
    if teacher_codes is not None:
        overlay["teacher_codes"] = list(teacher_codes)
    if nouveau_type is not None:
        overlay["session_type"] = nouveau_type.value
    if duration_slots is not None:
        overlay["duration_slots"] = duration_slots
    if is_eval is not None:
        overlay["is_eval"] = is_eval
    if overlay:
        upsert_overlay(session_id, overlay)

    placement_final = next((p for p in state.timetable if p.session_id == session_id), None)
    if placement_final is None:
        raise HTTPException(404, "No timetable")
    return _to_placement(placement_final, state.sessions_by_id)


def _conflit_structure(exc: HTTPException) -> HTTPException:
    """`move_session` lève parfois un 409 dont le detail est une CHAÎNE
    (verrou de semaine courante). Le frontend n'offre « Enregistrer quand
    même » que si `hard_conflicts` est une liste."""
    if exc.status_code != 409 or not isinstance(exc.detail, str):
        return exc
    return HTTPException(
        409,
        detail={
            "message": "Conflit",
            "hard_conflicts": [exc.detail],
            "soft_warnings": [],
            "suggestions": [],
            "suggestions_note": None,
        },
    )


def _controler_placement(state: object, session: object, placement: object, force: bool) -> None:
    from cal_iut.api.main import (
        _as_placed,
        _build_conflict_map,
        _hard_constraint_context,
        _institutional_violations,
        _libelle_jour_ferme,
        _pedagogical_order_violations,
        _teacher_availability_violations,
    )

    extra_blocked, extra_blocked_pedago, allowed_weeks = _hard_constraint_context(state, session)
    duree = max(1, int(session.duration_slots or 1))
    institutional: list[str] = []
    indispo: list[str] = []
    for offset in range(duree):
        sl = placement.slot + offset
        institutional += _institutional_violations(
            placement.week,
            placement.day,
            sl,
            extra_blocked,
            _libelle_jour_ferme(state, session.semestre, placement.week, placement.day),
        )
        indispo += _teacher_availability_violations(state, session, placement.week, placement.day, sl)
    blocking = institutional + indispo
    if blocking:
        raise HTTPException(
            409,
            detail={
                "message": "Modification impossible",
                "hard_conflicts": blocking,
                "blocking_conflicts": blocking,
                "soft_warnings": [],
                "suggestions": [],
                "suggestions_note": None,
            },
        )
    pedago = _pedagogical_order_violations(
        placement.week, placement.day, placement.slot, extra_blocked_pedago, allowed_weeks
    )
    if pedago and not force:
        raise HTTPException(
            409,
            detail={
                "message": "Conflit",
                "hard_conflicts": pedago,
                "soft_warnings": [],
                "suggestions": [],
                "suggestions_note": None,
            },
        )
    room_id = getattr(placement, "room_id", None)
    validation = validate_move(
        session.id,
        placement.week,
        placement.day,
        placement.slot,
        _as_placed(state.timetable),
        list(placement.group_ids),
        list(session.teacher_codes),
        room_id,
        sessions_by_id=state.sessions_by_id,
        groups=state.groups,
        conflicting_room_ids=_build_conflict_map(state.rooms).get(room_id, set()) if room_id else None,
    )
    if not validation.valid and not force:
        raise HTTPException(
            409,
            detail={
                "message": "Conflit",
                "hard_conflicts": validation.hard_conflicts,
                "soft_warnings": validation.soft_warnings,
                "suggestions": [],
                "suggestions_note": None,
            },
        )
