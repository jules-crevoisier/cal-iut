"""Déposer une séance du planning sans la retirer du catalogue.

`DELETE /placements/{id}` reste réservé à l'annulation d'un forçage
pédagogique. Ici la séance rejoint « À placer » et peut être reposée.
"""

from __future__ import annotations

from fastapi import HTTPException

from cal_iut.api.state import get_repo, get_state


def deposer_seance(session_id: str) -> dict[str, object]:
    state = get_state()
    if session_id not in state.sessions_by_id:
        raise HTTPException(404, f"Session {session_id} not found")

    avant = len(state.timetable)
    state.timetable = [p for p in state.timetable if p.session_id != session_id]
    if state.current_run_id and avant != len(state.timetable):
        get_repo().remove_current_placement(session_id)
    return {"ok": True, "session_id": session_id, "deposee": True}
