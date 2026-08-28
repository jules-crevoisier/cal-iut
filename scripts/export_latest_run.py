"""Exporte le dernier run SQLite vers un timetable.json portable."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def export_latest_run(db_path: Path, output: Path) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, created_at, status, parcours, semestre, objective_value, gap_penalty, weeks "
        "FROM planning_runs ORDER BY id DESC LIMIT 1"
    )
    run = cur.fetchone()
    if not run:
        print("Aucun run en base.")
        return 1

    cur.execute(
        """
        SELECT session_id, week, day, slot, course_code, room_id, room_label, locked
        FROM current_placements WHERE run_id = ?
        """,
        (run["id"],),
    )
    placements = [dict(row) for row in cur.fetchall()]
    payload = {
        "status": run["status"],
        "objective_value": run["objective_value"],
        "gap_penalty": run["gap_penalty"] or 0,
        "tier_values": None,
        "placements": placements,
        "run_id": run["id"],
        "created_at": run["created_at"],
        "parcours": run["parcours"],
        "semestre": run["semestre"],
        "weeks": run["weeks"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Run #{run['id']} ({run['status']}, {len(placements)} séances) -> {output}"
    )
    conn.close()
    return 0


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Exporte le dernier run DB en JSON")
    parser.add_argument("--db", type=Path, default=root / "data" / "state" / "cal-iut.db")
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "timetable_odd_fresh.json",
    )
    args = parser.parse_args()
    return export_latest_run(args.db, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
