"""Audit de la configuration métier (`data/config/*.yaml`).

Famille de bugs visée : **une règle qui pointe dans le vide**. Un code de cours
mal orthographié, un semestre qui ne correspond pas, un trigramme d'enseignant
qui n'intervient pas sur le module — rien ne lève d'erreur, la règle est
simplement ignorée et personne ne s'en aperçoit. C'est d'autant plus insidieux
que ces fichiers sont exactement ceux qu'un nouvel utilisateur va éditer.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

from cal_iut.audit.report import AuditReport, Finding, Severity
from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.ingestion.config_loader import (
    load_course_max_week_rules,
    load_course_min_week_rules,
    load_course_teacher_orders,
    load_double_sessions,
    load_groups,
    load_sae_teacher_phases,
    load_session_date_windows,
    load_solver_scheduled_sae,
    load_teacher_distributions,
    load_teacher_duos,
    load_weekly_cap_exceptions,
)
from cal_iut.models.entities import Course


def _course_index(courses: list[Course]) -> dict[tuple[str, str], Course]:
    return {(c.code.upper(), c.semestre): c for c in courses}


def _known_courses(index: dict[tuple[str, str], Course]) -> str:
    codes = sorted({code for code, _ in index})
    return ", ".join(codes[:12]) + (f" … ({len(codes)} au total)" if len(codes) > 12 else "")


def _missing_course(
    report: AuditReport,
    index: dict[tuple[str, str], Course],
    code: str,
    semestre: str,
    *,
    ou: str,
    regle: str,
) -> bool:
    """Retourne True si le cours est introuvable (et signale)."""
    if (code.upper(), semestre) in index:
        return False
    same_code = sorted({sem for c, sem in index if c == code.upper()})
    if same_code:
        report.add(Finding(
            Severity.ERREUR,
            "config.mauvais_semestre",
            f"{regle} : le cours {code} existe, mais pas en {semestre}.",
            quoi_faire=f"Corriger `semestre` en {' ou '.join(same_code)}.",
            ou=ou,
        ))
    else:
        report.add(Finding(
            Severity.ERREUR,
            "config.cours_inexistant",
            f"{regle} : aucun cours {code} ({semestre}) dans la maquette — règle sans effet.",
            quoi_faire=(
                "Vérifier l'orthographe du code. Une règle qui ne correspond à aucun "
                "cours est silencieusement ignorée par le solveur."
            ),
            ou=ou,
            details=[f"Codes connus : {_known_courses(index)}"],
        ))
    return True


def audit_config(
    config_dir: Path,
    courses: list[Course],
    calendar: AcademicCalendar,
    report: AuditReport,
) -> None:
    index = _course_index(courses)
    yaml_ref = "data/config/course_scheduling_rules.yaml"

    # --- Démarrage minimum / borne de fin ---
    min_rules = load_course_min_week_rules(config_dir)
    max_rules = load_course_max_week_rules(config_dir)
    for rule in min_rules:
        _missing_course(report, index, rule.course_code, rule.semestre,
                        ou=f"{yaml_ref} > min_week_rules", regle="min_week_rules")
    for rule in max_rules:
        _missing_course(report, index, rule.course_code, rule.semestre,
                        ou=f"{yaml_ref} > max_week_rules", regle="max_week_rules")

    mins = {(r.course_code.upper(), r.semestre): r.min_week for r in min_rules}
    for rule in max_rules:
        low = mins.get((rule.course_code.upper(), rule.semestre))
        if low is not None and low > rule.max_week:
            report.add(Finding(
                Severity.ERREUR,
                "config.fenetre_semaine_vide",
                f"{rule.course_code} : min_week={low} dépasse max_week={rule.max_week} — "
                "aucune semaine possible, le solveur sera infaisable.",
                quoi_faire="Élargir la fenêtre : min_week doit rester <= max_week.",
                ou=yaml_ref,
            ))
    if min_rules or max_rules:
        report.ok("config.bornes_semaine",
                  f"{len(min_rules)} borne(s) de début et {len(max_rules)} de fin vérifiées")

    # --- Fenêtres de dates par séance ---
    windows = load_session_date_windows(config_dir)
    teachable = {
        d
        for w in range(len(calendar.teaching_mondays))
        for day in range(5)
        if (d := calendar.week_day_to_date(w, day)) is not None
        and d not in calendar.blocked_dates
        and d not in calendar.holidays
    }
    for rule in windows:
        ou = f"{yaml_ref} > session_date_windows > {rule.course_code}"
        if _missing_course(report, index, rule.course_code, rule.semestre,
                           ou=ou, regle="session_date_windows"):
            continue
        course = index[(rule.course_code.upper(), rule.semestre)]
        if rule.only_dates:
            hors = [d for d in rule.only_dates if date.fromisoformat(d) not in teachable]
            if hors:
                report.add(Finding(
                    Severity.ERREUR,
                    "config.dates_hors_calendrier",
                    f"{rule.course_code} : {len(hors)}/{len(rule.only_dates)} date(s) listée(s) "
                    "tombent un jour fermé (vacances, férié, hors année) — inutilisables.",
                    quoi_faire="Retirer ces dates ou corriger le calendrier IUT.",
                    ou=ou,
                    details=hors,
                ))
        else:
            start = date.fromisoformat(rule.start_date) if rule.start_date else None
            end = date.fromisoformat(rule.end_date) if rule.end_date else None
            if start and end and start > end:
                report.add(Finding(
                    Severity.ERREUR, "config.fenetre_inversee",
                    f"{rule.course_code} : début ({rule.start_date}) après fin ({rule.end_date}).",
                    quoi_faire="Intervertir `debut` et `fin`.", ou=ou))
                continue
            jours = [d for d in teachable
                     if (start is None or d >= start) and (end is None or d <= end)]
            if not jours:
                report.add(Finding(
                    Severity.ERREUR, "config.fenetre_vide",
                    f"{rule.course_code} : la fenêtre {rule.start_date}..{rule.end_date} ne "
                    "contient aucun jour enseignable — la contrainte sera ignorée.",
                    quoi_faire="Élargir la fenêtre ou vérifier le calendrier IUT.", ou=ou))
                continue
            # Volume à caser dans la fenêtre, par cohorte.
            visees = [e for e in course.seance_sequence
                      if (rule.session_type is None
                          or str(e.get("type")) == rule.session_type.value)
                      and (not rule.sequence_orders
                           or int(e.get("ordre", 0)) in rule.sequence_orders)]
            if visees and len(visees) > len(jours) * 6:
                report.add(Finding(
                    Severity.ALERTE, "config.fenetre_trop_serree",
                    f"{rule.course_code} : {len(visees)} séance(s) visée(s) pour seulement "
                    f"{len(jours) * 6} créneaux dans la fenêtre.",
                    quoi_faire="Élargir la fenêtre, ou réduire les séances visées.", ou=ou))
    if windows:
        report.ok("config.fenetres_dates", f"{len(windows)} fenêtre(s) de dates vérifiées")

    # --- Blocs de séances collées ---
    for rule in load_double_sessions(config_dir):
        matches = [c for c in courses if c.code.upper() == rule.course_code.upper()]
        if not matches:
            report.add(Finding(
                Severity.ERREUR, "config.cours_inexistant",
                f"double_sessions : aucun cours {rule.course_code} — règle sans effet.",
                quoi_faire="Vérifier l'orthographe du code.",
                ou="data/config/double_sessions.yaml"))
            continue
        for course in matches:
            volume = int(course.volumes.get(rule.session_type.value.lower(), 0) or 0)
            if volume == 0:
                report.add(Finding(
                    Severity.ALERTE, "config.bloc_sans_volume",
                    f"{rule.course_code} : aucun {rule.session_type.value} au volume, "
                    "la règle de bloc ne s'appliquera à rien.",
                    quoi_faire="Vérifier le `session_type` de la règle.",
                    ou="data/config/double_sessions.yaml"))
            elif rule.max_blocks is None and volume % rule.slots_per_session:
                reste = volume % rule.slots_per_session
                report.add(Finding(
                    Severity.INFO, "config.bloc_reliquat",
                    f"{rule.course_code} : {volume} {rule.session_type.value} en blocs de "
                    f"{rule.slots_per_session} laissent {reste} séance(s) seule(s) de 1h30.",
                    quoi_faire=(
                        "Comportement voulu par défaut (on n'invente pas de créneau). "
                        "Si ces séances doivent aussi être longues, ajuster le volume "
                        "maquette ou `slots_per_session`."),
                    ou="data/config/double_sessions.yaml"))

    # --- Ordre / répartition entre enseignants d'un module ---
    for rule in load_course_teacher_orders(config_dir):
        ou = f"{yaml_ref} > teacher_order_rules > {rule.course_code}"
        if _missing_course(report, index, rule.course_code, rule.semestre,
                           ou=ou, regle="teacher_order_rules"):
            continue
        course = index[(rule.course_code.upper(), rule.semestre)]
        connus = {b.teacher.code.upper() for b in course.profs} | {course.lead.code.upper()}
        inconnus = [c for c in rule.teacher_order if c.upper() not in connus]
        if inconnus:
            report.add(Finding(
                Severity.ERREUR, "config.enseignant_hors_module",
                f"{rule.course_code} : {', '.join(inconnus)} n'intervient pas sur ce module — "
                "l'ordre demandé ne s'appliquera pas.",
                quoi_faire=f"Enseignants réels du module : {', '.join(sorted(connus))}.",
                ou=ou))

    for rule in load_teacher_distributions(config_dir):
        ou = f"{yaml_ref} > teacher_distribution > {rule.course_code}"
        if _missing_course(report, index, rule.course_code, rule.semestre,
                           ou=ou, regle="teacher_distribution"):
            continue
        course = index[(rule.course_code.upper(), rule.semestre)]
        connus = {b.teacher.code.upper() for b in course.profs} | {course.lead.code.upper()}
        inconnus = [c for c in rule.teacher_order if c.upper() not in connus]
        if inconnus:
            report.add(Finding(
                Severity.ERREUR, "config.enseignant_hors_module",
                f"{rule.course_code} : {', '.join(inconnus)} n'intervient pas sur ce module.",
                quoi_faire=f"Enseignants réels du module : {', '.join(sorted(connus))}.", ou=ou))
        if rule.mode == "alterne" and len(course.profs) < 2:
            report.add(Finding(
                Severity.ALERTE, "config.alternance_inutile",
                f"{rule.course_code} : un seul enseignant, l'alternance n'a rien à alterner.",
                quoi_faire="Retirer la règle, ou vérifier la maquette du module.", ou=ou))

    # --- SAE planifiées par le solveur ---
    for code, semestre in sorted(load_solver_scheduled_sae(config_dir)):
        if _missing_course(report, index, code, semestre,
                           ou=f"{yaml_ref} > solver_scheduled_sae", regle="solver_scheduled_sae"):
            continue
        if not code.upper().startswith("WS"):
            report.add(Finding(
                Severity.ALERTE, "config.sae_attendue",
                f"solver_scheduled_sae : {code} n'est pas une SAE (code sans préfixe WS) — "
                "cette liste ne sert qu'à réintégrer des SAE normalement exclues.",
                quoi_faire="Retirer l'entrée : un cours classique est déjà planifié.",
                ou=yaml_ref))

    # --- Phases enseignants d'une SAE ---
    for phase in load_sae_teacher_phases(config_dir):
        ou = f"data/config/sae_teacher_phases.yaml > {phase.course_code} > {phase.teacher_code}"
        debut, fin = date.fromisoformat(phase.debut), date.fromisoformat(phase.fin)
        if debut > fin:
            report.add(Finding(
                Severity.ERREUR, "config.phase_inversee",
                f"{phase.course_code}/{phase.teacher_code} : début après fin.",
                quoi_faire="Intervertir `debut` et `fin`.", ou=ou))
        ouvrables = [d for d in teachable if debut <= d <= fin]
        if not ouvrables:
            report.add(Finding(
                Severity.ALERTE, "config.phase_fermee",
                f"{phase.course_code}/{phase.teacher_code} : la phase {phase.debut}..{phase.fin} "
                "ne contient aucun jour d'ouverture de l'IUT.",
                quoi_faire=(
                    "Vérifier les dates : une phase entièrement en vacances libère "
                    "l'enseignant sans jamais le mobiliser."),
                ou=ou))
        hors = [d for d in phase.exclure if date.fromisoformat(d) < debut or date.fromisoformat(d) > fin]
        if hors:
            report.add(Finding(
                Severity.ALERTE, "config.exclusion_hors_phase",
                f"{phase.course_code}/{phase.teacher_code} : {len(hors)} date(s) exclue(s) hors "
                "de la phase — sans effet.",
                quoi_faire="Retirer ces dates, ou élargir la phase.", ou=ou, details=hors))

    # --- Dérogations au plafond hebdomadaire ---
    # Un audit ne doit JAMAIS planter sur une configuration incomplète : c'est
    # précisément la situation qu'il est censé diagnostiquer.
    try:
        parcours_connus = {g.parcours for g in load_groups(config_dir)}
    except (FileNotFoundError, KeyError) as exc:
        report.add(Finding(
            Severity.ERREUR, "config.groupes_illisibles",
            f"data/config/groups.yaml est absent ou illisible ({exc.__class__.__name__}) : "
            "les groupes étudiants sont indispensables au solveur.",
            quoi_faire="Restaurer `data/config/groups.yaml` depuis le dépôt.",
            ou=str(config_dir / "groups.yaml")))
        parcours_connus = set()
    lundis = {m.isoformat() for m in calendar.teaching_mondays}
    for exc in load_weekly_cap_exceptions(config_dir):
        ou = f"{yaml_ref} > weekly_cap_exceptions"
        if exc.parcours not in parcours_connus:
            report.add(Finding(
                Severity.ERREUR, "config.parcours_inconnu",
                f"weekly_cap_exceptions : parcours « {exc.parcours} » inconnu — sans effet.",
                quoi_faire=f"Parcours connus : {', '.join(sorted(parcours_connus))}.", ou=ou))
        if exc.week_monday not in lundis:
            report.add(Finding(
                Severity.ERREUR, "config.semaine_inconnue",
                f"weekly_cap_exceptions : {exc.week_monday} n'est pas un lundi de semaine "
                "enseignable — la dérogation ne s'appliquera à aucune semaine.",
                quoi_faire="Utiliser le LUNDI d'une semaine de cours (cf. calendrier IUT).",
                ou=ou))

    # --- Duos salle rare ---
    try:
        duos = load_teacher_duos(config_dir)
    except (FileNotFoundError, KeyError):
        duos = []
    for duo in duos:
        for code in duo.course_codes:
            if not any(c.code.upper() == code.upper() for c in courses):
                report.add(Finding(
                    Severity.ERREUR, "config.cours_inexistant",
                    f"teacher_duos : aucun cours {code} — duo sans effet.",
                    quoi_faire="Vérifier l'orthographe du code.",
                    ou="data/config/teacher_duos.yaml"))
    # Deux duos qui partagent les MÊMES salles rares se sérialisent entre eux :
    # voulu quand c'est la même paire physique, coûteux quand c'est une erreur.
    par_salles: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for duo in duos:
        if duo.rare_rooms:
            par_salles[tuple(sorted(duo.rare_rooms))].append("+".join(duo.teacher_codes))
    for salles, duos_ in sorted(par_salles.items()):
        if len(duos_) > 2:
            report.add(Finding(
                Severity.ALERTE, "config.duos_serialises",
                f"{len(duos_)} duos partagent les salles {', '.join(salles)} : ils ne pourront "
                "jamais co-animer en même temps.",
                quoi_faire=(
                    "Vérifier que c'est bien la même paire de salles physiques. Sinon, "
                    "donner à chaque duo sa propre paire (cf. le bug du 11/08/2026)."),
                ou="data/config/teacher_duos.yaml", details=duos_))

    report.ok("config.references", "toutes les règles pointent vers un cours et un enseignant réels")
