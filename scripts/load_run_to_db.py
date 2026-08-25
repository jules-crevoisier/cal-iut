"""Charge un timetable.json résolu dans SQLite pour `cal-iut serve`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cal_iut.db.repository import PlanningRepository


def load_run(timetable_path: Path, semestre_group: str | None = None) -> int:
    raw = json.loads(timetable_path.read_text(encoding="utf-8"))
    placements = raw.get("placements", raw)
    if not placements:
        print("Fichier vide ou sans placements.")
        return 1

    semestre = raw.get("semestre") or (semestre_group.upper() if semestre_group else "ODD")
    parcours = raw.get("parcours") or "MMI"
    weeks = int(raw.get("weeks") or (max(int(p["week"]) for p in placements) + 1))

    repo = PlanningRepository()
    run = repo.save_run(
        parcours=parcours,
        semestre=semestre,
        status=str(raw.get("status") or "FEASIBLE"),
        objective_value=raw.get("objective_value"),
        gap_penalty=int(raw.get("gap_penalty") or 0),
        weeks=weeks,
        solver_placements=placements,
        current_placements=placements,
    )
    print(f"Run #{run.id} chargé ({len(placements)} séances, semestre={semestre}).")
    print("Lancez: cal-iut serve")
    return 0


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Importe un timetable.json en base")
    parser.add_argument(
        "timetable",
        type=Path,
        nargs="?",
        default=root / "data" / "timetable_odd_fresh.json",
    )
    parser.add_argument(
        "--semestre-group",
        choices=["odd", "even"],
        default="odd",
        help="Sentinel ODD/EVEN si absent du JSON (défaut: odd)",
    )
    args = parser.parse_args()
    if not args.timetable.exists():
        print(f"Introuvable: {args.timetable}")
        return 1
    return load_run(args.timetable, semestre_group=args.semestre_group)


if __name__ == "__main__":
    raise SystemExit(main())
