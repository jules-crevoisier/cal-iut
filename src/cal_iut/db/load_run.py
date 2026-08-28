"""Import d'un timetable.json résolu vers SQLite."""

from __future__ import annotations

import json
from pathlib import Path

from cal_iut.db.models import PlanningRun
from cal_iut.db.repository import PlanningRepository
from cal_iut.db.session import DEFAULT_DB, get_db, init_db


def load_run_from_json(
    timetable_path: Path,
    db_path: Path | None = None,
    semestre_group: str | None = "odd",
) -> PlanningRun:
    """
    Charge les placements d'un run déjà résolu dans la base locale.

    @param timetable_path - JSON exporté (ex. data/timetable_odd_fresh.json)
    @param db_path - SQLite cible (défaut data/state/cal-iut.db)
    @param semestre_group - Sentinel ODD/EVEN si absent du fichier
    @returns Le PlanningRun créé
    @raises ValueError si le fichier est vide ou sans placements
    """
    raw = json.loads(timetable_path.read_text(encoding="utf-8"))
    placements = raw.get("placements")
    if not isinstance(placements, list) or not placements:
        raise ValueError(
            f"Aucun placement dans {timetable_path} — "
            f"vérifiez la branche git (feature/sync-laptop-run) et relancez git pull."
        )

    semestre = raw.get("semestre") or (
        semestre_group.upper() if semestre_group else "ODD"
    )
    parcours = raw.get("parcours") or "MMI"
    weeks = int(raw.get("weeks") or (max(int(p["week"]) for p in placements) + 1))

    path = db_path or DEFAULT_DB
    init_db(path)
    db = get_db(path)
    try:
        repo = PlanningRepository(db)
        return repo.save_run(
            parcours=str(parcours),
            semestre=str(semestre),
            status=str(raw.get("status") or "FEASIBLE"),
            objective_value=raw.get("objective_value"),
            gap_penalty=int(raw.get("gap_penalty") or 0),
            weeks=weeks,
            solver_placements=placements,
            current_placements=placements,
        )
    finally:
        db.close()
