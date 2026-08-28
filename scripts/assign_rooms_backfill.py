"""Backfill des salles sur un timetable déjà généré.

Trouvé le 27/08/2026 : 75,5 % des séances du run chargé n'ont aucune salle
(`room_id` vide) — préexistant, pas causé par `polish_run.py`. Le solveur
CP-SAT ne modélise pas les salles du tout (`docs/DATA.md §65.5`) ;
l'affectation (`assign_rooms`, glouton) n'est appelée qu'à l'intérieur de
`cal-iut solve`/`completer`/`/regen/week` — jamais comme passe autonome sur
un fichier déjà écrit. Ce script rejoue cette même fonction, avec les mêmes
paramètres que `api/main.py`/`cli.py`, sur l'intégralité d'un timetable.json
existant.

Usage :
    python scripts/assign_rooms_backfill.py --timetable <in.json> --output <out.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cal_iut.cli import _construire_etat_pour_completion  # noqa: E402
from cal_iut.models.session import SessionToPlace  # noqa: E402
from cal_iut.solver.cpsat import PlacedSession  # noqa: E402
from cal_iut.solver.rooms import assign_rooms  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timetable", default=str(ROOT / "data" / "generated" / "timetable_final.json"))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    timetable_path = Path(args.timetable)
    output_path = Path(args.output) if args.output else timetable_path

    donnees = json.loads(timetable_path.read_text(encoding="utf-8"))
    placements_bruts = donnees.get("placements", [])

    sessions_path = ROOT / "data" / "generated" / "sessions.json"
    sessions = [SessionToPlace(**s) for s in json.loads(sessions_path.read_text(encoding="utf-8"))]
    sessions_by_id = {s.id: s for s in sessions}

    etat = _construire_etat_pour_completion(ROOT)

    # `PlacedSession`, jamais `PlacedSessionWithRoom` : `assign_rooms` décide
    # lui-même de la salle, une salle déjà posée dans le fichier ne doit pas
    # influencer son choix (sinon une salle en double-booking silencieux,
    # déjà écrite par erreur, se reconduirait telle quelle).
    placements = [
        PlacedSession(
            session_id=p["session_id"], week=p["week"], day=p["day"], slot=p["slot"],
            course_code=p["course_code"], group_ids=p["group_ids"], teacher_codes=p["teacher_codes"],
        )
        for p in placements_bruts
    ]

    avec_salle_avant = sum(1 for p in placements_bruts if p.get("room_id"))
    print(f"avant : {avec_salle_avant}/{len(placements_bruts)} séance(s) avec salle")

    with_rooms = assign_rooms(
        placements, sessions_by_id, etat.rooms, etat.groups, etat.room_rules,
        etat.teacher_duos, reserved=etat.room_reservations,
    )

    avec_salle_apres = sum(1 for p in with_rooms if p.room_id)
    print(f"après : {avec_salle_apres}/{len(with_rooms)} séance(s) avec salle")
    assert len(with_rooms) == len(placements_bruts), "le nombre de séances a changé — anormal"

    donnees["placements"] = [
        {
            "session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
            "course_code": p.course_code, "group_ids": p.group_ids, "teacher_codes": p.teacher_codes,
            "room_id": p.room_id, "room_label": p.room_label,
        }
        for p in with_rooms
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"écrit : {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
