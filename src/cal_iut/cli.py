"""Point d'entrée CLI."""

import argparse
import json
import sys
from pathlib import Path

from cal_iut.ingestion.config_loader import (
    load_groups,
    load_objective_weights,
    load_room_assignment_rules,
    load_rooms,
    load_teacher_availability,
    load_teacher_duos,
)
from cal_iut.ingestion.fetch import fetch_all_exports_sync, save_exports
from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR, SEMESTRE_GROUPS, run_ingestion
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver
from cal_iut.solver.quality import compute_quality
from cal_iut.solver.rooms import assign_rooms, parse_room_rules


def _default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "config"


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "generated"


def cmd_fetch(args: argparse.Namespace) -> int:
    output = Path(args.output)
    maquette, progression = fetch_all_exports_sync()
    save_exports(output, maquette, progression)
    print(f"Exports saved to {output}")
    print(f"  maquette: {len(maquette)} matières")
    print(f"  progression: {len(progression)} matières")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    config_dir = Path(args.config_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    maquette = progression = None
    if args.from_cache:
        cache = Path(args.from_cache)
        maquette = json.loads((cache / "maquette.json").read_text(encoding="utf-8"))
        progression = json.loads((cache / "progression.json").read_text(encoding="utf-8"))

    result = run_ingestion(
        config_dir,
        maquette=maquette,
        progression=progression,
        parcours=args.parcours,
        semestre=args.semestre,
        semestre_group=getattr(args, "semestre_group", None),
    )

    courses_path = output_dir / "courses.json"
    sessions_path = output_dir / "sessions.json"
    stats_path = output_dir / "stats.json"

    courses_path.write_text(
        json.dumps([c.model_dump() for c in result.courses], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sessions_path.write_text(
        json.dumps([s.model_dump() for s in result.sessions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stats_path.write_text(
        json.dumps(result.stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Ingestion complete.")
    for key, value in result.stats.items():
        print(f"  {key}: {value}")
    print(f"\nOutput:\n  {courses_path}\n  {sessions_path}\n  {stats_path}")
    return 0


def _load_sessions(path: Path, args: argparse.Namespace) -> list[SessionToPlace]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    sessions = [SessionToPlace.model_validate(s) for s in raw]
    if args.limit:
        sessions = sessions[: args.limit]
    if args.course:
        sessions = [s for s in sessions if s.course_code == args.course]
    return sessions


def cmd_solve(args: argparse.Namespace) -> int:
    sessions_path = Path(args.sessions)
    if not sessions_path.exists():
        print(f"Sessions file not found: {sessions_path}", file=sys.stderr)
        print("Run: cal-iut ingest --parcours BUT1 --semestre S1", file=sys.stderr)
        return 1

    config_dir = Path(args.config_dir)
    sessions = _load_sessions(sessions_path, args)
    weights = load_objective_weights(config_dir)
    teacher_avail = load_teacher_availability(config_dir)

    from cal_iut.ingestion.constraints_loader import load_all_constraints, merge_teacher_availability

    project_root = config_dir.parents[1]
    bundle = load_all_constraints(project_root)
    teacher_avail = merge_teacher_availability(teacher_avail, bundle.teachers)

    groups = load_groups(config_dir)
    duos = load_teacher_duos(config_dir)
    solver = TimetableSolver(
        SolverConfig(
            weeks=args.weeks,
            gap_weight=args.gap_weight or weights.get("gap_penalty", 100),
            optimize_gaps=not args.no_gaps,
            enforce_ordonnancement=not args.no_ordonnancement,
            time_limit_seconds=args.time_limit,
            num_workers=args.num_workers,
            data_root=project_root,
            fi_max_week=getattr(args, "fi_max_week", None),
        )
    )
    semestre_group = getattr(args, "semestre_group", None)
    if semestre_group:
        semestre = SEMESTRE_GROUP_ANCHOR[semestre_group]
        found = {s.semestre for s in sessions}
        unexpected = found - SEMESTRE_GROUPS[semestre_group]
        if unexpected:
            print(
                f"Attention : --semestre-group={semestre_group} attendu {SEMESTRE_GROUPS[semestre_group]}, "
                f"mais sessions.json contient aussi {unexpected} (ré-ingérer avec --semestre-group={semestre_group} ?)",
                file=sys.stderr,
            )
    else:
        semestre = sessions[0].semestre if sessions else None

    hints = None
    if args.warm_start:
        warm_path = Path(args.warm_start)
        if warm_path.exists():
            warm_raw = json.loads(warm_path.read_text(encoding="utf-8"))
            warm_placements = warm_raw.get("placements", warm_raw) if isinstance(warm_raw, dict) else warm_raw
            slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
            hints = {
                p["session_id"]: p["week"] * slots_per_week + p["day"] * SLOTS_PER_DAY + p["slot"]
                for p in warm_placements
            }
            print(f"Warm-start: {len(hints)} hints loaded from {warm_path}")
        else:
            print(f"Warm-start file not found, ignoring: {warm_path}", file=sys.stderr)

    if args.decomposed:
        solve_fn = solver.solve_decomposed
    elif args.legacy_weighted:
        solve_fn = solver.solve
    else:
        solve_fn = solver.solve_tiered
    result = solve_fn(
        sessions,
        teacher_avail,
        calendar=bundle.calendar,
        student_presences=bundle.student_presences,
        semestre=semestre,
        groups=groups,
        hints=hints,
        duos=duos,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sessions_by_id = {s.id: s for s in sessions}
    placements = result.placements
    room_data: list[dict[str, object]] = []

    if not args.no_rooms and result.status in ("OPTIMAL", "FEASIBLE"):
        rooms = load_rooms(config_dir)
        rules = parse_room_rules(load_room_assignment_rules(config_dir))
        with_rooms = assign_rooms(placements, sessions_by_id, rooms, groups, rules, duos)
        room_data = [
            {
                "session_id": p.session_id,
                "week": p.week,
                "day": p.day,
                "slot": p.slot,
                "course_code": p.course_code,
                "group_ids": p.group_ids,
                "teacher_codes": p.teacher_codes,
                "room_id": p.room_id,
                "room_label": p.room_label,
            }
            for p in with_rooms
        ]
    else:
        room_data = [
            {
                "session_id": p.session_id,
                "week": p.week,
                "day": p.day,
                "slot": p.slot,
                "course_code": p.course_code,
                "group_ids": p.group_ids,
                "teacher_codes": p.teacher_codes,
            }
            for p in placements
        ]

    quality = None
    if result.status in ("OPTIMAL", "FEASIBLE"):
        quality = compute_quality(placements, sessions_by_id)

    payload = {
        "status": result.status,
        "objective_value": result.objective_value,
        "gap_penalty": result.gap_penalty,
        "tier_values": result.tier_values,
        "placements": room_data,
        "quality": quality.__dict__ if quality else None,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Solver status: {result.status}")
    print(f"  Placed: {len(result.placements)} sessions")
    print(f"  Objective: {result.objective_value}")
    if quality:
        print(f"  Gaps: {quality.total_gaps}")
        print(f"  Isolated days: {quality.isolated_days}")
    print(f"  Output: {output_path}")
    return 0 if result.status in ("OPTIMAL", "FEASIBLE") else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "cal_iut.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from cal_iut.export.formatter import build_export_rows, to_csv, to_json
    from cal_iut.models.session import SessionToPlace
    from cal_iut.solver.rooms import PlacedSessionWithRoom

    timetable_path = Path(args.timetable)
    sessions_path = Path(args.sessions)
    if not timetable_path.exists():
        print(f"Not found: {timetable_path}", file=sys.stderr)
        return 1

    raw = json.loads(timetable_path.read_text(encoding="utf-8"))
    placements_raw = raw.get("placements", raw) if isinstance(raw, dict) else raw

    sessions_by_id: dict[str, SessionToPlace] = {}
    if sessions_path.exists():
        for s in json.loads(sessions_path.read_text(encoding="utf-8")):
            sessions_by_id[s["id"]] = SessionToPlace.model_validate(s)

    if args.format == "html":
        from cal_iut.export.html_view import build_and_render
        from cal_iut.ingestion.config_loader import load_groups, load_rooms, load_teacher_availability
        from cal_iut.ingestion.constraints_loader import load_all_constraints, merge_teacher_availability
        from cal_iut.ingestion.planning_loader import (
            load_mmi_planning_for_semestres,
            planning_events_as_week_days,
            sae_windows_as_week_days,
        )

        config_dir = Path(args.config_dir)
        project_root = config_dir.parents[1]
        groups = load_groups(config_dir)
        rooms = load_rooms(config_dir)
        sessions_list = list(sessions_by_id.values())
        semestre = sessions_list[0].semestre if sessions_list else None

        bundle = load_all_constraints(project_root)
        teacher_avail = merge_teacher_availability(load_teacher_availability(config_dir), bundle.teachers)

        sae_days_by_course = None
        planning_events = None
        if semestre:
            week_offset = 0
            from cal_iut.calendar.academic import semester_week_offset

            week_offset = semester_week_offset(bundle.calendar, semestre)
            n_weeks = (max((p["week"] for p in placements_raw), default=-1)) + 1
            # cf. docs/DATA.md §37 : `semestre` peut n'être que l'ancre d'un
            # groupe multi-parcours — charger tous les semestres réels présents.
            real_semestres = sorted({s.semestre for s in sessions_list}) or [semestre]
            planning = load_mmi_planning_for_semestres(project_root, real_semestres)
            sae_days_by_course = sae_windows_as_week_days(
                planning, bundle.calendar.date_to_week_day, week_offset, n_weeks
            )
            planning_events = planning_events_as_week_days(
                planning, bundle.calendar.date_to_week_day_any, week_offset, n_weeks
            )

        html = build_and_render(
            raw,
            sessions_list,
            groups,
            calendar=bundle.calendar,
            semestre=semestre,
            teacher_availability=teacher_avail,
            sae_days_by_course=sae_days_by_course,
            rooms=rooms,
            planning_events=planning_events,
        )
        output = Path(args.output)
        output.write_text(html, encoding="utf-8")
        print(f"Exported HTML timetable -> {output}")
        return 0

    placements = [
        PlacedSessionWithRoom(
            session_id=p["session_id"],
            week=p["week"],
            day=p["day"],
            slot=p["slot"],
            course_code=p["course_code"],
            group_ids=p.get("group_ids", []),
            teacher_codes=p.get("teacher_codes", []),
            room_id=p.get("room_id"),
            room_label=p.get("room_label"),
        )
        for p in placements_raw
    ]

    rows = build_export_rows(placements, sessions_by_id)
    output = Path(args.output)

    if args.format == "csv":
        output.write_text(to_csv(rows), encoding="utf-8-sig")
    else:
        output.write_text(json.dumps(to_json(rows), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Exported {len(rows)} rows -> {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Générateur d'emplois du temps IUT MMI Troyes")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_parser = sub.add_parser("fetch", help="Télécharger les exports JSON")
    fetch_parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[2] / "data" / "exports"),
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    ingest_parser = sub.add_parser("ingest", help="Fusionner et normaliser les données")
    ingest_parser.add_argument("--config-dir", default=str(_default_config_dir()))
    ingest_parser.add_argument("--output-dir", default=str(_default_output_dir()))
    ingest_parser.add_argument("--parcours", default=None, help="Ex: BUT1, BUT2-DEV-FI")
    ingest_parser.add_argument("--semestre", default=None, help="Ex: S1")
    ingest_parser.add_argument("--from-cache", default=None, help="Dossier avec maquette.json")
    ingest_parser.add_argument(
        "--semestre-group",
        choices=["odd", "even"],
        default=None,
        help=(
            "Run global multi-parcours : ingère TOUS les parcours pour un groupe de "
            "semestres concurrents (odd=S1+S3+S5, even=S2+S4+S6) au lieu d'un seul "
            "parcours/semestre — prioritaire sur --parcours/--semestre si fourni."
        ),
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    solve_parser = sub.add_parser("solve", help="Lancer le solveur CP-SAT")
    solve_parser.add_argument("--config-dir", default=str(_default_config_dir()))
    solve_parser.add_argument("--sessions", default=str(_default_output_dir() / "sessions.json"))
    solve_parser.add_argument(
        "--weeks",
        type=int,
        default=None,
        help="Par défaut (non fourni) : calculé depuis le calendrier réel jusqu'au 1er février 2027 (S2) pour S1/S3/S5",
    )
    solve_parser.add_argument(
        "--fi-max-week",
        type=int,
        default=None,
        help=(
            "Mode --decomposed uniquement : borne les parcours FI (non-FC) à cette "
            "semaine-index (incluse), permet à --weeks d'étendre l'horizon pour les "
            "seuls parcours FC (retour utilisateur 06/08/2026, cf. docs/DATA.md §33). "
            "Non fourni = comportement inchangé, tous les parcours bornés à --weeks."
        ),
    )
    solve_parser.add_argument(
        "--time-limit",
        type=int,
        default=900,
        help="900s par défaut : nécessaire empiriquement pour un run complet BUT1-S1 (cf. docs/DATA.md §12.3)",
    )
    solve_parser.add_argument("--num-workers", type=int, default=8)
    solve_parser.add_argument(
        "--legacy-weighted",
        action="store_true",
        help=(
            "Utilise l'ancien mode somme pondérée (solve()) au lieu du mode par "
            "défaut en paliers lexicographiques (solve_tiered()) — filet de "
            "sécurité, cf. docs/DATA.md §12.3 pour le comparatif chiffré."
        ),
    )
    solve_parser.add_argument(
        "--decomposed",
        action="store_true",
        help=(
            "Utilise le solveur décomposé (ordre -> semaine -> jour/créneau, "
            "solve_decomposed()) au lieu du mode paliers — recommandé pour un "
            "run BUT1-S1 complet (plus fiable, ~1400 séances) là où le modèle "
            "joint peut ne pas converger dans le budget de temps ; cf. "
            "docs/DATA.md §14 pour l'architecture et le comparatif chiffré. "
            "Prioritaire sur --legacy-weighted si les deux sont fournis."
        ),
    )
    solve_parser.add_argument(
        "--warm-start",
        default=None,
        help="timetable.json d'un run précédent, utilisé comme point de départ (accélère sans changer les règles)",
    )
    solve_parser.add_argument("--gap-weight", type=int, default=None)
    solve_parser.add_argument("--no-gaps", action="store_true", help="Désactiver objectif trous")
    solve_parser.add_argument("--no-ordonnancement", action="store_true")
    solve_parser.add_argument("--no-rooms", action="store_true")
    solve_parser.add_argument("--limit", type=int, default=None)
    solve_parser.add_argument("--course", default=None)
    solve_parser.add_argument("--output", default=str(_default_output_dir() / "timetable.json"))
    solve_parser.add_argument(
        "--semestre-group",
        choices=["odd", "even"],
        default=None,
        help=(
            "Résout un run global multi-parcours (odd=S1+S3+S5, even=S2+S4+S6) — "
            "`--sessions` doit provenir d'un `cal-iut ingest --semestre-group <même valeur>`. "
            "Résout l'horizon/calendrier depuis le semestre ancre du groupe (S1 pour odd, "
            "S2 pour even) puisque les 3 semestres d'un même groupe partagent le même axe "
            "temporel par construction (cf. SEMESTRE_GROUPS)."
        ),
    )
    solve_parser.set_defaults(func=cmd_solve)

    serve_parser = sub.add_parser("serve", help="Démarrer l'API FastAPI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.set_defaults(func=cmd_serve)

    export_parser = sub.add_parser("export", help="Exporter le planning CSV/JSON/HTML")
    export_parser.add_argument("--timetable", default=str(_default_output_dir() / "timetable.json"))
    export_parser.add_argument("--sessions", default=str(_default_output_dir() / "sessions.json"))
    export_parser.add_argument("--config-dir", default=str(_default_config_dir()))
    export_parser.add_argument("--format", choices=["csv", "json", "html"], default="csv")
    export_parser.add_argument("--output", default=str(_default_output_dir() / "export.csv"))
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
