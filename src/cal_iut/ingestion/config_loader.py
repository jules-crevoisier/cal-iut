"""Chargement des fichiers de configuration YAML."""

from pathlib import Path

import yaml

from cal_iut.models.entities import (
    CourseMaxWeekRule,
    CourseMinWeekRule,
    CourseTeacherOrderRule,
    DoubleSessionRule,
    Group,
    Room,
    RoomType,
    SaeTeacherPhase,
    SessionDateWindowRule,
    SessionType,
    TeacherAvailability,
    TeacherCorrection,
    TeacherDistributionRule,
    TeacherDuo,
    WeeklyCapException,
)


def load_yaml(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_rooms(config_dir: Path) -> list[Room]:
    data = load_yaml(config_dir / "rooms.yaml")
    return [
        Room(
            id=item["id"],
            label=item["label"],
            capacity=item["capacity"],
            room_type=RoomType(item["room_type"]),
            equipment=item.get("equipment", []),
            combines=item.get("combines", []),
        )
        for item in data.get("rooms", [])
    ]


def load_room_assignment_rules(config_dir: Path) -> list[dict[str, object]]:
    data = load_yaml(config_dir / "rooms.yaml")
    return list(data.get("room_assignment_rules", []))


def load_groups(config_dir: Path) -> list[Group]:
    data = load_yaml(config_dir / "groups.yaml")
    groups: list[Group] = []

    for parcours, promo in data.get("promotions", {}).items():
        annee = parcours.split("-")[0]

        promo_group = promo.get("promo_group")
        if promo_group:
            groups.append(
                Group(
                    id=promo_group["id"],
                    label=promo_group["label"],
                    parcours=parcours,
                    annee=annee,
                    kind="promo",
                    headcount=promo_group.get("headcount", 240),
                )
            )

        for td in promo.get("td_groups", []):
            groups.append(
                Group(
                    id=td["id"],
                    label=td["label"],
                    parcours=parcours,
                    annee=annee,
                    kind="td",
                    tp_groups=[str(g) for g in td.get("tp_groups", [])],
                    headcount=td.get("headcount", 30),
                )
            )

        for tp in promo.get("tp_groups", []):
            groups.append(
                Group(
                    id=tp["id"],
                    label=tp["label"],
                    parcours=parcours,
                    annee=annee,
                    kind="tp",
                    headcount=tp.get("headcount", 30),
                )
            )

    return groups


def load_teacher_availability(config_dir: Path) -> list[TeacherAvailability]:
    data = load_yaml(config_dir / "teacher_availability.yaml")
    return [TeacherAvailability.model_validate(item) for item in data.get("teachers", [])]


def load_room_reservations(
    config_dir: Path, calendar, week_offset: int = 0
) -> dict[str, set[int]]:
    """Salles réservées par des tiers -> index de créneaux occupés.

    Le solveur ne modélise pas les salles (cf. docs/DATA.md §65.5) : elles sont
    attribuées après coup. Une salle prise par la Direction se déclare donc
    ici, et l'attribution n'en dispose plus — elle ne déplace aucun cours,
    elle force seulement à en trouver une autre.

    Retourne `{room_id: {index de créneau absolu}}`, dans le même repère que
    `solver/rooms.py::_time_index`, prêt à pré-remplir `room_schedule`.
    """
    from datetime import date as _date

    from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

    chemin = config_dir / "salles_reservees.yaml"
    if not chemin.exists() or calendar is None:
        return {}
    data = load_yaml(chemin) or {}
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    reserve: dict[str, set[int]] = {}
    for entree in data.get("reservations", []) or []:
        mapped = calendar.date_to_week_day_any(_date.fromisoformat(str(entree["date"])))
        if mapped is None:
            continue
        rel = mapped[0] - week_offset
        if rel < 0:
            continue
        base = rel * slots_per_week + mapped[1] * SLOTS_PER_DAY
        cible = reserve.setdefault(str(entree["salle"]), set())
        for slot in entree.get("slots", []) or []:
            if 0 <= int(slot) < SLOTS_PER_DAY:
                cible.add(base + int(slot))
    return reserve


def load_objective_weights(config_dir: Path) -> dict[str, int]:
    data = load_yaml(config_dir / "teacher_availability.yaml")
    weights = data.get("objective_weights", {})
    return {str(k): int(v) for k, v in weights.items()}


def load_teacher_duos(config_dir: Path) -> list[TeacherDuo]:
    """Duos co-animant en simultané sur une salle rare (cf. teacher_duos.yaml)."""
    path = config_dir / "teacher_duos.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    duos: list[TeacherDuo] = []
    for item in data.get("duos", []):
        codes = item.get("teacher_codes") or []
        if len(codes) != 2:
            continue
        kwargs: dict[str, object] = {
            "teacher_codes": (str(codes[0]), str(codes[1])),
            "course_codes": [str(c) for c in item.get("course_codes", [])],
            "note": item.get("note"),
        }
        if item.get("rare_rooms"):
            kwargs["rare_rooms"] = tuple(str(r) for r in item["rare_rooms"])
        if item.get("group_overrides"):
            kwargs["group_overrides"] = {
                str(code): [str(letter) for letter in letters]
                for code, letters in item["group_overrides"].items()
            }
        duos.append(TeacherDuo.model_validate(kwargs))
    return duos


def load_seances_annulees(config_dir: Path) -> set[str]:
    """Identifiants des séances qui n'auront pas lieu (cf.
    `seances_annulees.yaml`).

    Rendu comme un ENSEMBLE d'identifiants : le retrait se fait à
    l'ingestion (`pipeline.retirer_seances_annulees`), donc avant que
    quiconque — solveur, inventaire « À placer », API — ne les voie. Une
    séance seulement dépointée du planning redeviendrait « à placer » et
    reviendrait au redémarrage suivant.

    `motif` est OBLIGATOIRE : dans un an, une annulation sans justification
    est soit supprimée à tort, soit conservée à tort.
    """
    path = config_dir / "seances_annulees.yaml"
    if not path.exists():
        return set()
    data = load_yaml(path) or {}
    annulees: set[str] = set()
    for item in data.get("annulees") or []:
        session_id = str(item.get("session_id") or "").strip()
        if not session_id:
            raise ValueError(
                f"{path.name} : une entrée sans `session_id` — elle donnerait une "
                "annulation qu'on croit faite et qui ne l'est pas."
            )
        if not str(item.get("motif") or "").strip():
            raise ValueError(f"{path.name} : `{session_id}` sans `motif`.")
        annulees.add(session_id)
    return annulees


def load_double_sessions(config_dir: Path) -> list[DoubleSessionRule]:
    """Règles de fusion de séances collées (cf. double_sessions.yaml)."""
    path = config_dir / "double_sessions.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    rules: list[DoubleSessionRule] = []
    for item in data.get("rules", []):
        rules.append(
            DoubleSessionRule(
                course_code=str(item["course_code"]),
                session_type=SessionType(str(item["session_type"])),
                slots_per_session=int(item.get("slots_per_session", 2)),
                pair_from=str(item.get("pair_from", "start")),
                max_blocks=(int(item["max_blocks"]) if item.get("max_blocks") else None),
                note=item.get("note"),
            )
        )
    return rules


def load_session_date_windows(config_dir: Path) -> list[SessionDateWindowRule]:
    """Fenêtres de dates par séance (cf. course_scheduling_rules.yaml)."""
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    rules: list[SessionDateWindowRule] = []
    for item in data.get("session_date_windows", []):
        session_type = item.get("session_type")
        rules.append(
            SessionDateWindowRule(
                course_code=str(item["course_code"]),
                semestre=str(item["semestre"]),
                session_type=SessionType(str(session_type)) if session_type else None,
                sequence_orders=[int(o) for o in item.get("sequence_orders", [])],
                start_date=(str(item["debut"]) if item.get("debut") else None),
                end_date=(str(item["fin"]) if item.get("fin") else None),
                only_dates=[str(d) for d in item.get("dates", [])],
                note=item.get("note"),
            )
        )
    return rules


def load_course_teacher_orders(config_dir: Path) -> list[CourseTeacherOrderRule]:
    """Ordre souple entre enseignants d'un module (cf. course_scheduling_rules.yaml)."""
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    rules: list[CourseTeacherOrderRule] = []
    for item in data.get("teacher_order_rules", []):
        codes = [str(c) for c in item.get("teacher_order", [])]
        if len(codes) < 2:
            continue
        rules.append(
            CourseTeacherOrderRule(
                course_code=str(item["course_code"]),
                semestre=str(item["semestre"]),
                teacher_order=codes,
                weight=int(item.get("weight", 200)),
                note=item.get("note"),
            )
        )
    return rules


def load_course_corrections(config_dir: Path) -> list[TeacherCorrection]:
    """Corrections manuelles d'enseignant post-fusion (cf. course_corrections.yaml)."""
    path = config_dir / "course_corrections.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    corrections: list[TeacherCorrection] = []
    for item in data.get("teacher_corrections", []):
        corrections.append(
            TeacherCorrection(
                course_code=str(item["course_code"]),
                semestre=str(item["semestre"]),
                parcours=str(item["parcours"]),
                wrong_teacher_code=str(item["wrong_teacher_code"]),
                correct_teacher_code=str(item["correct_teacher_code"]),
                note=item.get("note"),
            )
        )
    return corrections


def load_additional_courses(config_dir: Path) -> list[dict[str, object]]:
    """
    Lignes "maquette" manuelles, absentes de l'export distant (cf.
    `additional_courses.yaml`) — retournées telles quelles, prêtes à être
    injectées dans la liste `maquette` avant `merge_exports` (cf.
    `ingestion/pipeline.py`), donc traitées à l'identique d'une vraie ligne
    de l'export distant, survivent à un re-fetch.
    """
    path = config_dir / "additional_courses.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    return list(data.get("courses", []))


def load_teacher_contacts(config_dir: Path) -> dict[str, str]:
    """
    Adresses mail par trigramme (cf. `teacher_contacts.yaml`) — alimente le
    bouton « Écrire » de l'annuaire de liens dans l'export HTML.

    Aucun fichier source officiel ne porte les adresses mail : ce fichier est
    saisi à la main et n'est jamais écrasé par une régénération. Absent ou vide
    est un cas NORMAL, pas une erreur : le brouillon s'ouvre alors sans
    destinataire.
    """
    path = config_dir / "teacher_contacts.yaml"
    if not path.exists():
        return {}
    data = load_yaml(path) or {}
    contacts = data.get("contacts") or {}
    return {str(code): str(mail) for code, mail in contacts.items() if mail}


def load_course_min_week_rules(config_dir: Path) -> list[CourseMinWeekRule]:
    """Contraintes de démarrage minimum par cours (cf. course_scheduling_rules.yaml)."""
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    rules: list[CourseMinWeekRule] = []
    for item in data.get("min_week_rules", []):
        rules.append(
            CourseMinWeekRule(
                course_code=str(item["course_code"]),
                semestre=str(item["semestre"]),
                min_week=int(item["min_week"]),
                note=item.get("note"),
            )
        )
    return rules


def load_course_max_week_rules(config_dir: Path) -> list[CourseMaxWeekRule]:
    """Bornes de FIN par cours (cf. course_scheduling_rules.yaml, `max_week_rules`)."""
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    return [
        CourseMaxWeekRule(
            course_code=str(item["course_code"]),
            semestre=str(item["semestre"]),
            max_week=int(item["max_week"]),
            note=item.get("note"),
        )
        for item in data.get("max_week_rules", [])
    ]


def load_solver_scheduled_sae(config_dir: Path) -> set[tuple[str, str]]:
    """
    (code_matiere, semestre) des SAE que le SOLVEUR doit placer lui-même, au
    lieu de les laisser aux enseignants.

    Par défaut, toute séance dont le code commence par "WS" est retirée de la
    planification : une SAE est définie par ses enseignants, seules ses dates
    calendaires servent à sanctuariser les cours classiques (cf.
    `solve_decomposed`). Certaines SAE n'ont pourtant AUCUNE date dans le
    fichier officiel et doivent bien apparaître à l'emploi du temps — cas de
    WSA501D (BUT3-DEV-FC), `dates_indeterminees: true` dans
    `contraintes/09_dates_sae.json`, demandée explicitement par l'utilisateur
    le 25/08/2026.

    Liste EXPLICITE et non déduite de l'absence de dates : une SAE sans date
    est le plus souvent une donnée manquante à réclamer, pas une invitation à
    la planifier d'office.
    """
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return set()
    data = load_yaml(path) or {}
    return {
        (str(item["course_code"]).upper(), str(item["semestre"]))
        for item in data.get("solver_scheduled_sae", [])
    }


def is_solver_scheduled(course_code: str, semestre: str, scheduled: set[tuple[str, str]]) -> bool:
    """Une séance doit-elle rester dans la planification malgré son préfixe WS ?"""
    return (course_code.upper(), semestre) in scheduled


def load_teacher_distributions(config_dir: Path) -> list[TeacherDistributionRule]:
    """Répartition des séances d'un module entre ses enseignants (cf.
    `course_scheduling_rules.yaml::teacher_distribution`)."""
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    rules: list[TeacherDistributionRule] = []
    for item in data.get("teacher_distribution", []):
        session_type = item.get("session_type")
        rules.append(
            TeacherDistributionRule(
                course_code=str(item["course_code"]),
                semestre=str(item["semestre"]),
                mode=str(item.get("mode", "alterne")),
                session_type=SessionType(str(session_type)) if session_type else None,
                teacher_order=[str(c).upper() for c in item.get("teacher_order", [])],
                note=item.get("note"),
            )
        )
    return rules


def load_sae_teacher_phases(config_dir: Path) -> list[SaeTeacherPhase]:
    """Répartition des jours d'une SAE entre ses enseignants (cf.
    `sae_teacher_phases.yaml`, modèle `SaeTeacherPhase`)."""
    path = config_dir / "sae_teacher_phases.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    phases: list[SaeTeacherPhase] = []
    for entry in data.get("phases", []):
        for teacher in entry.get("teachers", []):
            phases.append(
                SaeTeacherPhase(
                    course_code=str(entry["course_code"]).upper(),
                    semestre=str(entry["semestre"]),
                    teacher_code=str(teacher["teacher_code"]).upper(),
                    debut=str(teacher["debut"]),
                    fin=str(teacher["fin"]),
                    exclure=[str(d) for d in teacher.get("exclure", [])],
                    note=teacher.get("note"),
                )
            )
    return phases


def load_weekly_cap_exceptions(config_dir: Path) -> list[WeeklyCapException]:
    """Dérogations ciblées au plafond horaire hebdomadaire (cf. course_scheduling_rules.yaml,
    `WeeklyCapException`, docs/DATA.md §62)."""
    path = config_dir / "course_scheduling_rules.yaml"
    if not path.exists():
        return []
    data = load_yaml(path) or {}
    exceptions: list[WeeklyCapException] = []
    for item in data.get("weekly_cap_exceptions", []):
        exceptions.append(
            WeeklyCapException(
                parcours=str(item["parcours"]),
                semestre=str(item["semestre"]),
                week_monday=str(item["week_monday"]),
                cap=int(item["cap"]),
                note=item.get("note"),
            )
        )
    return exceptions
