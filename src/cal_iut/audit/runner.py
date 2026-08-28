"""Orchestration de l'audit : charge les données une fois, lance chaque famille."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from cal_iut.audit.capacity_audit import (
    audit_capacity,
    audit_salles_rares,
    audit_weekly_capacity,
)
from cal_iut.audit.config_audit import audit_config
from cal_iut.audit.coverage_audit import audit_coverage, audit_solver_paths
from cal_iut.audit.data_audit import (
    audit_calendrier,
    audit_evenements_fixes,
    audit_generated_freshness,
    audit_maquette,
    audit_sae,
    audit_teacher_constraints,
)
from cal_iut.audit.report import AuditReport, Finding, Severity


def run_audit(
    project_root: Path,
    *,
    timetable_path: Path | None = None,
    weeks: int = 24,
    fi_max_week: int | None = 18,
    semestre_group: str = "odd",
) -> AuditReport:
    """Audit complet. Ne lance JAMAIS le solveur : tout est calculé ou relu."""
    from cal_iut.calendar.academic import semester_week_offset
    from cal_iut.ingestion.config_loader import (
        load_groups,
        load_solver_scheduled_sae,
        load_teacher_availability,
    )
    from cal_iut.ingestion.constraints_loader import (
        ConstraintsDataError,
        load_all_constraints,
        merge_teacher_availability,
    )
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR, SEMESTRE_GROUPS
    from cal_iut.models.session import SessionToPlace

    report = AuditReport()
    config_dir = project_root / "data" / "config"
    generated = project_root / "data" / "generated"

    # --- Chargement, en signalant proprement ce qui manque -----------------
    try:
        bundle = load_all_constraints(project_root)
    except (ConstraintsDataError, FileNotFoundError, json.JSONDecodeError) as exc:
        report.add(Finding(
            Severity.ERREUR, "chargement.contraintes",
            f"Impossible de charger les contraintes : {exc}",
            quoi_faire="Lancer `python scripts/build_contraintes.py` et vérifier les sources.",
            ou="contraintes/"))
        return report

    calendar = bundle.calendar
    groups = load_groups(config_dir)
    availability = merge_teacher_availability(load_teacher_availability(config_dir), bundle.teachers)
    scheduled_sae = load_solver_scheduled_sae(config_dir)

    audit_generated_freshness(project_root, report)
    audit_calendrier(calendar, report)
    audit_evenements_fixes(project_root, report)
    audit_teacher_constraints(availability, calendar, report)
    semestres = set(SEMESTRE_GROUPS.get(semestre_group, set()))
    audit_sae(project_root, report, scheduled_sae, semestres)

    sessions_path = generated / "sessions.json"
    if not sessions_path.exists():
        report.add(Finding(
            Severity.ALERTE, "chargement.sessions",
            "data/generated/sessions.json est absent : l'audit des volumes et de la capacité "
            "n'a pas pu être fait.",
            quoi_faire=f"Lancer `cal-iut ingest --semestre-group {semestre_group}`.",
            ou=str(sessions_path)))
        sessions: list[SessionToPlace] = []
    else:
        sessions = [
            SessionToPlace.model_validate(s)
            for s in json.loads(sessions_path.read_text(encoding="utf-8"))
        ]

    courses_path = generated / "courses.json"
    courses = []
    if courses_path.exists():
        from cal_iut.models.entities import Course

        courses = [
            Course.model_validate(c)
            for c in json.loads(courses_path.read_text(encoding="utf-8"))
        ]

    if courses:
        audit_config(config_dir, courses, calendar, report)
        if sessions:
            audit_maquette(courses, sessions, report, semestres)
    else:
        report.add(Finding(
            Severity.ALERTE, "chargement.courses",
            "data/generated/courses.json est absent : l'audit de configuration (règles qui "
            "pointent dans le vide) n'a pas pu être fait.",
            quoi_faire=f"Lancer `cal-iut ingest --semestre-group {semestre_group}`.",
            ou=str(courses_path)))

    if sessions:
        semestre = SEMESTRE_GROUP_ANCHOR.get(semestre_group, sessions[0].semestre)
        week_offset = semester_week_offset(calendar, semestre)
        a_placer = [
            s
            for s in sessions
            if not s.course_code.upper().startswith("WS")
            or (s.course_code.upper(), s.semestre) in scheduled_sae
        ]
        audit_capacity(
            a_placer, groups, availability, bundle.student_presences,
            calendar, week_offset, weeks, report, fi_max_week=fi_max_week,
        )
        from cal_iut.ingestion.config_loader import load_rooms

        audit_salles_rares(a_placer, groups, load_rooms(config_dir), report)

    audit_solver_paths(report, project_root)

    # --- Vérification d'un résultat existant -------------------------------
    checks_presents: set[str] | None = None
    if timetable_path is not None:
        checks_presents = _audit_timetable(
            project_root, timetable_path, sessions, groups, availability,
            calendar, semestre_group, weeks, report,
        )
    audit_coverage(report, checks_presents)
    return report


def _audit_timetable(
    project_root: Path,
    timetable_path: Path,
    sessions: list,
    groups: list,
    availability: list,
    calendar,
    semestre_group: str,
    weeks: int,
    report: AuditReport,
) -> set[str] | None:
    """Rejoue les contrôles du tableau de bord sur un run déjà produit."""
    from cal_iut.calendar.academic import semester_week_offset
    from cal_iut.export.html_view import build_payload
    from cal_iut.ingestion.config_loader import load_rooms
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR, SEMESTRE_GROUPS
    from cal_iut.ingestion.planning_loader import (
        load_mmi_planning_for_semestres,
        sae_supervisor_dates_by_teacher,
        sae_windows_as_week_days,
    )

    if not timetable_path.exists():
        report.add(Finding(
            Severity.ERREUR, "resultat.absent",
            f"{timetable_path} est introuvable.",
            quoi_faire="Lancer `cal-iut solve` avant d'auditer un résultat.",
            ou=str(timetable_path)))
        return None

    timetable = json.loads(timetable_path.read_text(encoding="utf-8"))
    placements = timetable.get("placements") or []
    statut = str(timetable.get("status", ""))
    if statut.startswith("PARTIAL_WEEKS_FAILED"):
        semaines = statut.split(":", 1)[1] if ":" in statut else "?"
        report.add(Finding(
            Severity.ERREUR, "resultat.incomplet",
            f"Le run analysé est INCOMPLET : semaine(s) en échec {semaines}.",
            quoi_faire=(
                "Relancer avec une autre graine (`--random-seed`) — le solveur n'est pas "
                "reproductible et une graine différente suffit souvent. "
                "`python scripts/solve_until_ok.py` automatise cette boucle."),
            ou=str(timetable_path)))
    elif not statut:
        report.add(Finding(
            Severity.ALERTE, "resultat.statut_inconnu",
            "Le fichier ne porte pas de statut de résolution.",
            quoi_faire="Vérifier qu'il provient bien de `cal-iut solve`.",
            ou=str(timetable_path)))

    placed_ids = {p["session_id"] for p in placements}
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    scheduled = load_solver_scheduled_sae(project_root / "data" / "config")
    manquantes = [
        s
        for s in sessions
        if s.id not in placed_ids
        and (
            not s.course_code.upper().startswith("WS")
            or (s.course_code.upper(), s.semestre) in scheduled
        )
    ]
    if manquantes:
        par_cours: dict[str, int] = defaultdict(int)
        for s in manquantes:
            par_cours[f"{s.course_code} ({s.semestre})"] += 1
        report.add(Finding(
            Severity.ERREUR, "resultat.seances_non_placees",
            f"{len(manquantes)} séance(s) ne figurent pas dans l'emploi du temps.",
            quoi_faire=(
                "Relancer avec une autre graine, traiter les erreurs de capacité "
                "ci-dessus, ou placer ces séances à la main depuis l'onglet "
                "« À placer » de l'application (`cal-iut serve`), qui ne propose "
                "que des créneaux déjà vérifiés."
            ),
            ou=str(timetable_path),
            details=[f"{k} : {v}" for k, v in sorted(par_cours.items(), key=lambda x: -x[1])]))
    else:
        report.ok("resultat.completude", "toutes les séances à placer figurent dans le résultat")

    if not placements:
        return None

    semestre = SEMESTRE_GROUP_ANCHOR.get(semestre_group, "S1")
    week_offset = semester_week_offset(calendar, semestre)
    real_semestres = sorted(SEMESTRE_GROUPS.get(semestre_group, {semestre}))
    planning = load_mmi_planning_for_semestres(project_root, real_semestres)
    sae_days = sae_windows_as_week_days(
        planning, calendar.date_to_week_day, week_offset, weeks
    )
    payload = build_payload(
        timetable, sessions, groups,
        calendar=calendar, semestre=semestre,
        teacher_availability=availability,
        sae_days_by_course=sae_days,
        rooms=load_rooms(project_root / "data" / "config"),
        sae_supervisor_dates=sae_supervisor_dates_by_teacher(
            planning, project_root / "data" / "config"
        ),
    )

    checks = payload.get("ruleChecks") or []
    for check in checks:
        statut_check = check.get("status")
        if statut_check == "pass":
            report.ok(f"resultat.{check['id']}", check["label"])
        elif statut_check == "fail":
            report.add(Finding(
                Severity.ERREUR, f"resultat.{check['id']}",
                f"{check['label']} : NON RESPECTÉ.",
                quoi_faire=check.get("detail", ""), ou=str(timetable_path)))
        else:
            report.add(Finding(
                Severity.INFO, f"resultat.{check['id']}",
                f"{check['label']} : {check.get('detail', '')}",
                ou=str(timetable_path)))

    # Explication des semaines en échec, quand il y en a.
    if statut.startswith("PARTIAL_WEEKS_FAILED"):
        by_week: dict[int, list] = defaultdict(list)
        by_id = {s.id: s for s in sessions}
        for p in placements:
            s = by_id.get(p["session_id"])
            if s is not None:
                by_week[p["week"]].append(s)
        audit_weekly_capacity(by_week, availability, calendar, week_offset, report)

    return {str(c["id"]) for c in checks}
