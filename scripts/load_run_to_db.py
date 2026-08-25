"""Charge un timetable.json résolu dans SQLite pour `cal-iut serve`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cal_iut.db.load_run import load_run_from_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Importe un timetable.json en base")
    parser.add_argument(
        "timetable",
        type=Path,
        nargs="?",
        default=ROOT / "data" / "timetable_odd_fresh.json",
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
        print("Sur main ce fichier n'existe pas — faites: git checkout feature/sync-laptop-run")
        return 1
    try:
        run = load_run_from_json(args.timetable, semestre_group=args.semestre_group)
    except ValueError as exc:
        print(exc)
        return 1
    print(f"Run #{run.id} chargé ({run.weeks} semaines, semestre={run.semestre}).")
    print("Lancez: cal-iut serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
