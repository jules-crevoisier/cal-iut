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


def _construire_etat_pour_completion(racine: Path):
    """Construit l'`AppState` utilisé par `cmd_completer` — MÊME assemblage
    que `api/main.py::startup()`, factorisé pour être testable sans lancer une
    complétion complète (potentiellement des dizaines de minutes).

    Historique (27/08/2026) : une première version de `cmd_completer`
    chargeait `teacher_availability.yaml` SEUL, sans le fusionner avec les
    contraintes réelles extraites du CSV établissement (`load_all_constraints`
    -> `merge_teacher_availability`) — elle ne voyait alors qu'une poignée
    d'indisponibilités illustratives au lieu des 23 enseignants réellement
    contraints. Trouvé en auditant un run complété par cette commande : 90
    séances placées sur des créneaux que l'enseignant avait pourtant
    explicitement déclarés indisponibles, silencieusement. Même défaut pour
    `student_presences` (semaines de présence IUT des alternants FC), absent
    de l'ancienne version.
    """
    from cal_iut.api.state import get_state
    from cal_iut.ingestion.config_loader import (
        load_groups,
        load_room_assignment_rules,
        load_room_reservations,
        load_rooms,
        load_teacher_availability,
        load_teacher_duos,
    )
    from cal_iut.ingestion.constraints_loader import (
        augment_teacher_availability_with_sae_supervision as _augment_sae,
    )
    from cal_iut.ingestion.constraints_loader import load_all_constraints, merge_teacher_availability
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUPS
    from cal_iut.ingestion.planning_loader import (
        load_mmi_planning_for_semestres,
        sae_supervisor_dates_by_teacher,
    )
    from cal_iut.solver.rooms import parse_room_rules

    config = racine / "data" / "config"
    bundle = load_all_constraints(racine)

    etat = get_state()
    etat.config_dir = config
    etat.groups = load_groups(config)
    etat.rooms = load_rooms(config)
    etat.room_rules = parse_room_rules(load_room_assignment_rules(config))
    etat.calendar = bundle.calendar
    etat.student_presences = bundle.student_presences
    etat.current_run_id = None
    etat.teacher_availability = merge_teacher_availability(load_teacher_availability(config), bundle.teachers)

    # Supervision SAE = très peu disponible ces jours-là pour un cours
    # classique (même mécanisme que `api/main.py::startup()`, docs/DATA.md
    # §48.2/§49) — sur TOUS les semestres connus, pas seulement celui du
    # fichier traité, par cohérence avec l'application.
    tous_semestres = sorted({s for grp in SEMESTRE_GROUPS.values() for s in grp})
    planning_tout = load_mmi_planning_for_semestres(racine, tous_semestres)
    dates_supervision = sae_supervisor_dates_by_teacher(planning_tout)
    etat.teacher_availability = _augment_sae(etat.teacher_availability, dates_supervision)
    etat.room_reservations = load_room_reservations(config, etat.calendar)
    etat.teacher_duos = load_teacher_duos(config)
    etat.corrections = []
    etat.courses = []
    return etat


def cmd_completer(args: argparse.Namespace) -> int:
    """Poser les séances qu'un run a laissées de côté, sans lancer de serveur.

    Le solveur ne place pas tout : le reliquat bute sur des combinaisons
    infaisables *dans la semaine que l'étage 2 leur a assignée*, pas sur une
    impossibilité absolue — sur le run réel, la quasi-totalité de ces séances
    a un créneau parfaitement valable ailleurs dans le semestre
    (cf. docs/DATA.md §66).

    Même moteur que le bouton « Tout placer automatiquement » de l'application,
    utilisable en ligne de commande pour enchaîner génération et complétion
    dans un script.
    """
    import json as _json

    from cal_iut.api.main import app as _app
    from cal_iut.models.session import SessionToPlace
    from cal_iut.solver.rooms import PlacedSessionWithRoom

    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover - dépendance présente en pratique
        print("fastapi/httpx requis pour cette commande.")
        return 1

    racine = Path(__file__).resolve().parents[2]
    genere = racine / "data" / "generated"

    chemin = Path(args.timetable)
    if not chemin.exists():
        print(f"Emploi du temps introuvable : {chemin}")
        return 1
    fichier_seances = genere / "sessions.json"
    if not fichier_seances.exists():
        print("data/generated/sessions.json manquant — lancez d'abord `cal-iut ingest`.")
        return 1

    seances = [SessionToPlace(**s) for s in _json.loads(fichier_seances.read_text(encoding="utf-8"))]
    donnees = _json.loads(chemin.read_text(encoding="utf-8"))

    etat = _construire_etat_pour_completion(racine)
    etat.sessions = seances
    etat.sessions_by_id = {s.id: s for s in seances}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id=p["session_id"], week=p["week"], day=p["day"], slot=p["slot"],
            course_code=p["course_code"], group_ids=p["group_ids"],
            teacher_codes=p["teacher_codes"],
            room_id=p.get("room_id"), room_label=p.get("room_label"),
        )
        for p in donnees.get("placements", [])
    ]

    client = TestClient(_app)
    avant = len(etat.timetable)
    rapport = client.post("/placements/completer").json()

    print()
    print("COMPLÉTION DU PLANNING")
    print("=" * 70)
    print(f"  avant  : {avant} séances placées")
    print(f"  {rapport['resume']}")
    print(f"  après  : {len(etat.timetable)} séances placées sur {len(seances)}")

    if rapport["refusees"]:
        from collections import Counter

        print()
        print("  Restent à traiter à la main (onglet « À placer ») :")
        for motif, nombre in Counter(r["raison"] for r in rapport["refusees"]).most_common():
            print(f"    {nombre:4d}  {motif}")

    sortie = Path(args.output) if args.output else chemin
    donnees["placements"] = [
        {
            "session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
            "course_code": p.course_code, "group_ids": p.group_ids,
            "teacher_codes": p.teacher_codes,
            "room_id": p.room_id, "room_label": p.room_label,
        }
        for p in etat.timetable
    ]
    sortie.write_text(_json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"  écrit : {sortie}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Audit complet sans lancer le solveur (cf. `cal_iut.audit`)."""
    from cal_iut.audit import run_audit

    project_root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[2]
    timetable = Path(args.timetable) if args.timetable else None
    report = run_audit(
        project_root,
        timetable_path=timetable,
        weeks=args.weeks,
        fi_max_week=args.fi_max_week,
        semestre_group=args.semestre_group,
    )
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.to_text(show_ok=args.tout))
    # Code de sortie exploitable en CI : 1 dès qu'une erreur bloquante existe.
    return 1 if report.erreurs() else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """« Est-ce que tout est en place ? » — cf. `cal_iut.onboarding.doctor`."""
    from cal_iut.onboarding import run_doctor

    project_root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[2]
    checks, etapes = run_doctor(project_root)

    print()
    print("ÉTAT DE L'INSTALLATION")
    print("=" * 70)
    for c in checks:
        marque = "[OK]  " if c.ok else ("[KO]  " if c.bloquant else "[~]   ")
        print(f"{marque} {c.libelle:38s} {c.detail}")
        if not c.ok and c.action:
            print(f"       -> {c.action}")
    print()
    print("=" * 70)
    for ligne in etapes:
        print(ligne)
    print()
    return 0 if all(c.ok or not c.bloquant for c in checks) else 1


def cmd_regles(args: argparse.Namespace) -> int:
    """Liste en français les règles métier actuellement déclarées."""
    from cal_iut.onboarding import inventorier

    project_root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[2]
    inventaire = inventorier(project_root)
    if args.json:
        print(json.dumps(
            [
                {"categorie": r.categorie, "resume": r.resume, "raison": r.raison, "ou": r.ou}
                for r in inventaire.regles
            ],
            ensure_ascii=False, indent=2,
        ))
    else:
        print(inventaire.to_text())
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """Récupère maquette + progression officielles et montre ce qui change."""
    from cal_iut.onboarding import refresh_sources

    project_root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[2]
    depuis = Path(args.depuis) if args.depuis else None
    resumes, messages = refresh_sources(project_root, ecrire=args.ecrire, depuis_fichiers=depuis)

    print()
    for m in messages:
        print(m)
    if resumes:
        print()
        print("CE QUI CHANGE")
        print("=" * 70)
        for r in resumes:
            print(r.to_text())
    if any(m.startswith("ERREUR") for m in messages):
        return 1
    print()
    if args.ecrire:
        print("À FAIRE MAINTENANT :")
        print("  1. python scripts/build_contraintes.py    -> régénérer les contraintes")
        print("  2. cal-iut ingest --semestre-group odd    -> préparer les séances")
        print("  3. cal-iut audit                          -> vérifier avant de résoudre")
    print()
    return 0


def cmd_annee(args: argparse.Namespace) -> int:
    """Déroule toute la chaîne, en s'arrêtant à la première étape qui coince.

    Une seule commande à retenir pour produire un emploi du temps complet. Chaque
    étape annonce ce qu'elle fait ; un échec dit quoi corriger plutôt que de
    laisser une trace Python.
    """
    import subprocess

    project_root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[2]
    py = sys.executable

    etapes: list[tuple[str, list[str]]] = []
    if not args.sans_build:
        etapes.append((
            "Régénérer les contraintes depuis les fichiers sources",
            [py, str(project_root / "scripts" / "build_contraintes.py")],
        ))
    etapes.append((
        "Préparer les séances à placer",
        [py, "-m", "cal_iut.cli", "ingest", "--semestre-group", args.semestre_group],
    ))
    etapes.append((
        "Vérifier les données avant de résoudre",
        [py, "-m", "cal_iut.cli", "audit", "--semestre-group", args.semestre_group],
    ))
    etapes.append((
        f"Construire l'emploi du temps (jusqu'à {args.runs} tentatives)",
        [py, str(project_root / "scripts" / "solve_until_ok.py"),
         "--max-runs", str(args.runs), "--max-hours", str(args.heures),
         "--semestre-group", args.semestre_group],
    ))

    for numero, (libelle, cmd) in enumerate(etapes, start=1):
        print()
        print("=" * 70)
        print(f"ÉTAPE {numero}/{len(etapes)} — {libelle}")
        print("=" * 70, flush=True)
        code = subprocess.call(cmd, cwd=project_root)
        if code != 0 and "audit" in cmd:
            # L'audit signale des problèmes de données : on s'arrête, mais en
            # expliquant que ce n'est pas une panne de l'outil.
            print()
            print("ARRÊT : l'audit a trouvé des erreurs bloquantes (voir ci-dessus).")
            print("Chaque ligne [ERREUR] dit quoi corriger. Corrigez, puis relancez")
            print("`cal-iut annee`. Pour passer outre volontairement : --sans-audit")
            if not args.sans_audit:
                return 1
        elif code != 0:
            print()
            print(f"ARRÊT : l'étape « {libelle} » a échoué.")
            print("Lancez `cal-iut doctor` pour savoir ce qui manque.")
            return code

    print()
    print("=" * 70)
    print("TERMINÉ. Emploi du temps dans data/generated/timetable_best.json")
    print("  - le visualiser      : cal-iut serve")
    print("  - l'envoyer par mail : cal-iut export --format html --output planning.html")
    print("  - le vérifier        : cal-iut audit --timetable data/generated/timetable_best.json")
    print("=" * 70)
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

    from cal_iut.ingestion.constraints_loader import (
        load_all_constraints,
        merge_teacher_availability,
    )

    project_root = config_dir.parents[1]
    bundle = load_all_constraints(project_root)
    teacher_avail = merge_teacher_availability(teacher_avail, bundle.teachers)

    groups = load_groups(config_dir)
    duos = load_teacher_duos(config_dir)
    solver_config_kwargs: dict[str, object] = dict(
        weeks=args.weeks,
        gap_weight=args.gap_weight or weights.get("gap_penalty", 100),
        optimize_gaps=not args.no_gaps,
        enforce_ordonnancement=not args.no_ordonnancement,
        time_limit_seconds=args.time_limit,
        num_workers=args.num_workers,
        data_root=project_root,
        fi_max_week=getattr(args, "fi_max_week", None),
        enforce_sae_supervisor_availability=not getattr(args, "no_sae_supervisor_hard", False),
    )
    if getattr(args, "random_seed", None) is not None:
        solver_config_kwargs["random_seed"] = args.random_seed
    if getattr(args, "last_resort_seconds", None) is not None:
        solver_config_kwargs["last_resort_seconds"] = args.last_resort_seconds
    if getattr(args, "last_resort_seeds", None) is not None:
        solver_config_kwargs["last_resort_seeds"] = args.last_resort_seeds
    if getattr(args, "benders_rounds", None) is not None:
        solver_config_kwargs["benders_rounds"] = args.benders_rounds
    if getattr(args, "spread_weight", None) is not None:
        solver_config_kwargs["spread_weight"] = args.spread_weight
    solver = TimetableSolver(SolverConfig(**solver_config_kwargs))
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
    solve_kwargs: dict[str, object] = dict(
        calendar=bundle.calendar,
        student_presences=bundle.student_presences,
        semestre=semestre,
        groups=groups,
        hints=hints,
        duos=duos,
    )
    if args.decomposed and getattr(args, "attempts", None) is not None:
        solve_kwargs["max_attempts"] = args.attempts
    result = solve_fn(sessions, teacher_avail, **solve_kwargs)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sessions_by_id = {s.id: s for s in sessions}
    placements = result.placements
    room_data: list[dict[str, object]] = []

    if not args.no_rooms and result.status in ("OPTIMAL", "FEASIBLE"):
        rooms = load_rooms(config_dir)
        rules = parse_room_rules(load_room_assignment_rules(config_dir))
        # Salles réservées par des tiers : le solveur ne modélise pas les
        # salles, l'attribution est le seul endroit où les honorer.
        from cal_iut.ingestion.config_loader import load_room_reservations

        reservees = load_room_reservations(config_dir, bundle.calendar)
        with_rooms = assign_rooms(
            placements, sessions_by_id, rooms, groups, rules, duos, reserved=reservees
        )
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


def cmd_load_run(args: argparse.Namespace) -> int:
    from cal_iut.db.load_run import load_run_from_json

    timetable_path = Path(args.timetable)
    if not timetable_path.exists():
        print(f"Not found: {timetable_path}", file=sys.stderr)
        print(
            "Ce fichier n'est sur main que via feature/sync-laptop-run — "
            "faites: git checkout feature/sync-laptop-run && git pull",
            file=sys.stderr,
        )
        return 1
    try:
        run = load_run_from_json(
            timetable_path,
            semestre_group=args.semestre_group,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Run #{run.id} chargé (semestre={run.semestre}, {run.weeks} semaines).")
    print("Lancez: cal-iut serve")
    return 0


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
        from cal_iut.ingestion.config_loader import (
            load_groups,
            load_rooms,
            load_teacher_availability,
            load_teacher_contacts,
        )
        from cal_iut.ingestion.constraints_loader import (
            load_all_constraints,
            merge_teacher_availability,
        )
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

        contacts = load_teacher_contacts(config_dir)

        def _render(scoped_sessions, **overrides):
            return build_and_render(
                raw,
                scoped_sessions,
                groups,
                calendar=bundle.calendar,
                semestre=semestre,
                teacher_availability=teacher_avail,
                sae_days_by_course=sae_days_by_course,
                rooms=rooms,
                planning_events=planning_events,
                teacher_contacts=contacts,
                **overrides,
            )

        if args.per_teacher:
            # Un fichier autonome PAR enseignant (retour utilisateur 10/08/2026).
            # Chacun ne contient que les séances de l'intéressé : rien à
            # filtrer côté lecteur, et aucune donnée des autres promotions ne
            # circule — contrairement au fichier commun + lien, où tout le
            # planning voyage avec.
            out_dir = Path(args.per_teacher)
            out_dir.mkdir(parents=True, exist_ok=True)
            placed_codes = sorted({c for p in placements_raw for c in p["teacher_codes"]})
            written = 0
            for code in placed_codes:
                own = [s for s in sessions_list if code in s.teacher_codes]
                if not own:
                    continue
                path = out_dir / f"planning-{code}.html"
                path.write_text(
                    _render(
                        own,
                        heading=f"Planning de {code}",
                        subheading=(
                            "Vue personnelle en lecture seule — pour toute correction, "
                            "contactez le responsable des emplois du temps."
                        ),
                    ),
                    encoding="utf-8",
                )
                written += 1
            print(f"Exported {written} per-teacher HTML files -> {out_dir}")
            return 0

        output = Path(args.output)
        output.write_text(_render(sessions_list), encoding="utf-8")
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

    from cal_iut.calendar.academic import semester_week_offset
    from cal_iut.ingestion.constraints_loader import load_all_constraints as _load_cal

    _bundle = _load_cal(config_dir.parents[1])
    _semestre = sessions[0].semestre if sessions else "S1"
    rows = build_export_rows(
        placements, sessions_by_id,
        _bundle.calendar, semester_week_offset(_bundle.calendar, _semestre),
    )
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

    doctor_parser = sub.add_parser(
        "doctor", help="Vérifier que tout est en place et dire quoi faire ensuite"
    )
    doctor_parser.add_argument("--project-root", default=None)
    doctor_parser.set_defaults(func=cmd_doctor)

    refresh_parser = sub.add_parser(
        "refresh", help="Récupérer maquette + progression officielles et voir ce qui change"
    )
    refresh_parser.add_argument("--project-root", default=None)
    refresh_parser.add_argument(
        "--ecrire", action="store_true",
        help="Appliquer réellement (sans ce drapeau, rien n'est modifié)",
    )
    refresh_parser.add_argument(
        "--depuis", default=None,
        help="Dossier local contenant maquette.json et progression.json (au lieu du serveur)",
    )
    refresh_parser.set_defaults(func=cmd_refresh)

    regles_parser = sub.add_parser(
        "regles", help="Lister en français les règles métier actuellement déclarées"
    )
    regles_parser.add_argument("--project-root", default=None)
    regles_parser.add_argument("--json", action="store_true")
    regles_parser.set_defaults(func=cmd_regles)

    annee_parser = sub.add_parser(
        "annee", help="Tout dérouler : contraintes -> séances -> audit -> emploi du temps"
    )
    annee_parser.add_argument("--project-root", default=None)
    annee_parser.add_argument("--semestre-group", default="odd", choices=["odd", "even"])
    annee_parser.add_argument("--runs", type=int, default=6, help="Tentatives de résolution")
    annee_parser.add_argument("--heures", type=float, default=4.0, help="Budget horaire total")
    annee_parser.add_argument(
        "--sans-build", action="store_true",
        help="Ne pas régénérer les contraintes (si elles sont déjà à jour)",
    )
    annee_parser.add_argument(
        "--sans-audit", action="store_true",
        help="Continuer malgré les erreurs d'audit (déconseillé)",
    )
    annee_parser.set_defaults(func=cmd_annee)

    audit_parser = sub.add_parser(
        "audit",
        help="Vérifier données, configuration, capacité et résultat (ne résout rien)",
    )
    audit_parser.add_argument("--project-root", default=None)
    audit_parser.add_argument(
        "--timetable",
        default=None,
        help="Emploi du temps à vérifier en plus (ex. data/generated/timetable.json)",
    )
    audit_parser.add_argument("--weeks", type=int, default=24)
    audit_parser.add_argument("--fi-max-week", type=int, default=18)
    audit_parser.add_argument("--semestre-group", default="odd", choices=["odd", "even"])
    audit_parser.add_argument("--json", action="store_true", help="Sortie machine")
    audit_parser.add_argument(
        "--tout", action="store_true", help="Afficher aussi les contrôles passés"
    )
    audit_parser.set_defaults(func=cmd_audit)

    completer_parser = sub.add_parser(
        "completer",
        help="Placer les séances qu'un run a laissées de côté (sans serveur)",
    )
    completer_parser.add_argument(
        "--timetable",
        required=True,
        help="Emploi du temps à compléter (ex. data/generated/timetable.json)",
    )
    completer_parser.add_argument(
        "--output",
        default=None,
        help="Fichier de sortie (par défaut : réécrit le fichier d'entrée)",
    )
    completer_parser.set_defaults(func=cmd_completer)

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
    solve_parser.add_argument(
        "--num-workers",
        type=int,
        default=None,
        help=(
            "Parallélisme CP-SAT. Non fourni = nombre de processeurs logiques de "
            "la machine (détecté automatiquement). En mode --decomposed, ce budget "
            "est réparti entre les semaines résolues simultanément et les workers "
            "accordés à chacune."
        ),
    )
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
    solve_parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        help=(
            "Graine CP-SAT (défaut 2027). Deux graines différentes explorent des "
            "zones différentes de l'espace de recherche : c'est le levier le plus "
            "efficace quand un run échoue sur quelques semaines (cf. "
            "`_solve_week_with_retry`). Utilisé par `scripts/solve_until_ok.py` "
            "pour relancer jusqu'à obtenir un run complet."
        ),
    )
    solve_parser.add_argument(
        "--last-resort-seconds",
        type=float,
        default=None,
        help=(
            "Budget (s) de chaque tentative de DERNIER RECOURS sur une semaine "
            "en échec — défaut 300, 8 graines par semaine. L'abaisser fait "
            "échouer un run difficile plus vite, ce qui est préférable quand on "
            "relance en boucle (`scripts/solve_until_ok.py`)."
        ),
    )
    solve_parser.add_argument("--last-resort-seeds", type=int, default=None)
    solve_parser.add_argument(
        "--benders-rounds",
        type=int,
        default=None,
        help=(
            "Tours de la boucle de retour étage 3 -> étage 2 : chaque semaine "
            "PROUVÉE infaisable est réinjectée dans l'affectation des semaines "
            "comme interdiction explicite, puis on recommence. 0 désactive."
        ),
    )
    solve_parser.add_argument(
        "--attempts",
        type=int,
        default=None,
        help=(
            "Nombre de fois où TOUT le pipeline est relancé en interne si des "
            "semaines échouent (défaut 3). Mettre 1 quand on boucle déjà à "
            "l'extérieur (`scripts/solve_until_ok.py`) : la diversité de graines "
            "vient alors de la boucle, et chaque tentative est journalisée."
        ),
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
    solve_parser.add_argument(
        "--no-sae-supervisor-hard",
        action="store_true",
        help=(
            "Indisponibilité référent SAE (retour utilisateur 11/08/2026) en objectif MOU "
            "(pénalité, évitée si possible) au lieu de blocage dur. Par défaut, dur — mais "
            "confirmé empiriquement catastrophique en --decomposed sur un run complet réel "
            "(2 semaines en échec sans ce mécanisme -> 13 avec, cf. docs/DATA.md §49) : "
            "utiliser ce drapeau pour tout run --decomposed multi-semestres complet."
        ),
    )
    solve_parser.add_argument(
        "--spread-weight",
        type=int,
        default=None,
        help=(
            "Lissage étage 2 (--decomposed uniquement, cf. assign_weeks) : étale les séances "
            "d'un même cours/type/groupe sur l'horizon au lieu de les regrouper. Non fourni = "
            "défaut historique (2, calibré pour le modèle joint). Recommandé : 8 pour un run "
            "--decomposed multi-semestres complet — a résolu un blocage combinatoire sur 2 "
            "semaines (aucune ressource individuellement saturée) là où 2 échouait, cf. "
            "docs/DATA.md §49."
        ),
    )
    solve_parser.set_defaults(func=cmd_solve)

    load_run_parser = sub.add_parser(
        "load-run",
        help="Importer un timetable.json déjà résolu en base (pour cal-iut serve)",
    )
    load_run_parser.add_argument(
        "timetable",
        nargs="?",
        default=str(Path(__file__).resolve().parents[2] / "data" / "timetable_odd_fresh.json"),
    )
    load_run_parser.add_argument(
        "--semestre-group",
        choices=["odd", "even"],
        default="odd",
    )
    load_run_parser.set_defaults(func=cmd_load_run)

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
    export_parser.add_argument(
        "--per-teacher",
        metavar="DOSSIER",
        default=None,
        help=(
            "--format html uniquement : écrit un fichier HTML autonome par "
            "enseignant dans ce dossier (planning-XXX.html), ne contenant que "
            "ses propres séances. Alternative au fichier commun + liens "
            "personnels, quand on préfère ne rien faire circuler d'autre."
        ),
    )
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
