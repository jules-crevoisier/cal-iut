"""Validation des déplacements manuels (contraintes dures)."""

from dataclasses import dataclass

from cal_iut.calendar.academic import AcademicCalendar, semester_week_offset, week_status
from cal_iut.models.entities import Group, TeacherAvailability
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.cpsat import PlacedSession


@dataclass
class ValidationResult:
    valid: bool
    hard_conflicts: list[str]
    soft_warnings: list[str]


def _duration_of(session_id: str, sessions_by_id: dict[str, object] | None) -> int:
    if not sessions_by_id:
        return 1
    return max(1, int(getattr(sessions_by_id.get(session_id), "duration_slots", 1) or 1))


def _cohort_conflict(
    group_ids: list[str],
    other_group_ids: list[str],
    groups: list[Group] | None,
) -> bool:
    """Ces deux séances sont-elles vues par les MÊMES étudiants ?

    Comparer les `group_ids` bruts ne suffit pas : un CM porte le groupe
    `promo` et un TD un sous-groupe, ils n'ont donc aucun identifiant commun
    alors que ce sont les mêmes étudiants. C'est la notion de COHORTE que le
    solveur utilise déjà (`build_student_cohorts`), et qui manquait ici.
    """
    if _overlap(group_ids, other_group_ids):
        return True
    if not groups:
        return False
    from cal_iut.solver.resources import build_student_cohorts

    for cohort_ids in build_student_cohorts(groups).values():
        if cohort_ids.intersection(group_ids) and cohort_ids.intersection(other_group_ids):
            return True
    return False


def validate_move(
    session_id: str,
    week: int,
    day: int,
    slot: int,
    timetable: list[PlacedSession],
    group_ids: list[str],
    teacher_codes: list[str],
    room_id: str | None = None,
    sessions_by_id: dict[str, object] | None = None,
    groups: list[Group] | None = None,
    # Salles combinées (retour utilisateur 28/08/2026, cf.
    # `solver/rooms.py::_build_conflict_map`) : occuper "h007_h008" doit
    # aussi ressortir en conflit pour "h007"/"h008" pris individuellement,
    # et réciproquement. Vide/absent = comportement d'avant, inchangé.
    conflicting_room_ids: set[str] | None = None,
    # Séances à IGNORER dans l'occupation, en plus de `session_id`. Sert à
    # l'échange de deux séances (`POST /placements/echanger`) : chacune doit
    # être jugée sur la place LIBÉRÉE par l'autre. Sans cela, tout échange
    # entre deux séances du même groupe serait refusé, chacune voyant l'autre
    # exactement là où elle veut aller.
    ignore_session_ids: set[str] | None = None,
) -> ValidationResult:
    """
    Vérifie qu'un déplacement manuel ne crée pas de conflit dur.

    Deux défauts corrigés le 26/08/2026, trouvés en explorant ce module :

    1. **La durée était ignorée.** La comparaison portait sur le créneau de
       DÉPART uniquement : un bloc de 3h occupant les créneaux 3 et 4 restait
       invisible pour qui déposait une séance sur le créneau 4. L'interface
       répondait « OK » et deux cours se superposaient.
    2. **La cohorte était ignorée.** `group_ids` bruts : déposer un TD sur le
       créneau du CM de sa propre promotion ne levait aucun conflit, alors que
       ce sont les mêmes étudiants.

    `sessions_by_id` et `groups` sont facultatifs pour ne pas casser les
    appelants existants, mais les deux vérifications ci-dessus n'ont lieu que
    s'ils sont fournis — l'API les passe systématiquement.
    """
    hard: list[str] = []
    soft: list[str] = []

    if day < 0 or day >= DAYS_PER_WEEK:
        hard.append("Jour invalide (lundi–vendredi uniquement)")
    if slot < 0 or slot >= SLOTS_PER_DAY:
        hard.append("Créneau invalide")

    duration = _duration_of(session_id, sessions_by_id)
    if slot + duration > SLOTS_PER_DAY:
        hard.append(
            f"La séance dure {duration} créneaux et déborderait sur le jour suivant"
        )

    debut = _time_index(week, day, slot)
    occupes = set(range(debut, debut + duration))

    a_ignorer = {session_id} | (ignore_session_ids or set())
    for placement in timetable:
        if placement.session_id in a_ignorer:
            continue
        autre_debut = _time_index(placement.week, placement.day, placement.slot)
        autre_duree = _duration_of(placement.session_id, sessions_by_id)
        if occupes.isdisjoint(range(autre_debut, autre_debut + autre_duree)):
            continue

        quand = (
            f"sem. {placement.week + 1}, {_day_name(placement.day)} "
            f"{_slot_label(placement.slot)}"
        )
        if _cohort_conflict(group_ids, placement.group_ids, groups):
            hard.append(f"Conflit groupe : {placement.course_code} ({quand})")

        if _overlap(teacher_codes, placement.teacher_codes):
            hard.append(
                f"Conflit enseignant : {placement.course_code} "
                f"({', '.join(placement.teacher_codes)})"
            )

        if room_id and getattr(placement, "room_id", None) in ({room_id} | (conflicting_room_ids or set())):
            hard.append(f"Conflit salle : {placement.course_code} occupe déjà cette salle")

    if slot == 2 and day >= 0:
        soft.append("Créneau 11h–12h30 : attention à la pause déjeuner suivante")

    return ValidationResult(valid=len(hard) == 0, hard_conflicts=hard, soft_warnings=soft)


def _time_index(week: int, day: int, slot: int) -> int:
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    return week * slots_per_week + day * SLOTS_PER_DAY + slot


def _overlap(a: list[str], b: list[str]) -> bool:
    return bool(set(a) & set(b))


def _day_name(day: int) -> str:
    names = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")
    return names[day] if 0 <= day < len(names) else "?"


def _slot_label(slot: int) -> str:
    labels = ("8h-9h30", "9h30-11h", "11h-12h30", "14h-15h30", "15h30-17h", "17h-18h30")
    return labels[slot] if 0 <= slot < len(labels) else "?"


@dataclass
class SlotSuggestion:
    week: int
    day: int
    slot: int
    label: str  # ex. "Semaine 5 — Mardi 9h30-11h"


def _teacher_free_at(
    teacher_codes: list[str],
    week: int,
    day: int,
    slot: int,
    d,
    teacher_availability: list[TeacherAvailability],
    calendar: AcademicCalendar | None = None,
    week_offset: int = 0,
) -> bool:
    """
    Recoupe TOUTES les indispos DÉCLARÉES d'un enseignant — les quatre
    mécanismes du solveur (`solver/constraints.py::add_teacher_availability_constraints`),
    répliqués ici en pure lecture plutôt qu'en contrainte CP-SAT :

    1. `forbidden_slots` (récurrent, jour/créneau) ;
    2. `metadata["forbidden_dates"]` (dates absolues — y compris la
       supervision SAE, cf. `augment_teacher_availability_with_sae_supervision`
       appliqué une fois au démarrage de l'API, retour utilisateur 11/08/2026) ;
    3. `allowed_slots`/`allowed_dates` (liste blanche DURE — jusqu'ici
       manquante ici : un enseignant comme VBU ou MNI restait "libre" aux yeux
       du glisser-déposer en dehors de ses jours déclarés) ;
    4. `week_parity_rules` (indisponibilité une semaine sur deux, ex. TCA).

    Retour utilisateur (11/08/2026) : "vérifie bien toutes les contraintes
    avant que ça s'effectue" — avant ce correctif, seuls 1 et 2 étaient
    couverts, et uniquement pour FILTRER les suggestions, jamais pour bloquer
    un glisser-déposer brut (cf. `api/main.py::_teacher_availability_violations`,
    qui réutilise cette même fonction pour un blocage RÉEL, non contournable).
    """
    from cal_iut.solver.constraints import _week_parity

    by_code = {a.teacher_code: a for a in teacher_availability}
    for code in teacher_codes:
        avail = by_code.get(code)
        if not avail:
            continue
        if (day, slot) in (avail.forbidden_slots or []):
            return False
        forbidden_dates = avail.metadata.get("forbidden_dates") or []
        if d is not None and d.isoformat() in forbidden_dates:
            return False

        # Date ET horaire précis (`TeacherDateSlotRule`) : le cinquième
        # mécanisme, ajouté le 26/08/2026. Répliqué ici comme les quatre autres
        # — la validation manuelle ne doit jamais être plus permissive que le
        # solveur.
        if d is not None:
            iso = d.isoformat()
            for regle in getattr(avail, "forbidden_date_slots", []) or []:
                if regle.date == iso and slot in regle.slots:
                    return False
        if avail.allowed_slots and (day, slot) not in {tuple(p) for p in avail.allowed_slots}:
            return False
        if avail.allowed_dates and (d is None or d.isoformat() not in set(avail.allowed_dates)):
            return False
        if avail.week_parity_rules and calendar is not None:
            parity = _week_parity(calendar, week_offset, week, avail.parity_reference)
            if parity is not None:
                for rule in avail.week_parity_rules:
                    if rule.parity == parity and rule.day == day and slot in rule.slots:
                        return False
    return True


def suggest_alternative_slots(
    session_id: str,
    group_ids: list[str],
    teacher_codes: list[str],
    timetable: list[PlacedSession],
    calendar: AcademicCalendar,
    semestre: str,
    teacher_availability: list[TeacherAvailability] | None = None,
    room_id: str | None = None,
    search_from_week: int = 0,
    max_weeks: int = 6,
    max_suggestions: int = 3,
    extra_blocked: set[tuple[int, int, int]] | None = None,
    allowed_weeks: set[int] | None = None,
    # Sans ces deux-là, la suggestion est PLUS PERMISSIVE que le placement :
    # `validate_move` ignore alors la durée des séances et la cohorte
    # étudiante, exactement les deux défauts corrigés le 26/08/2026 côté
    # glisser-déposer (cf. docs/DATA.md §65.2). Mesuré sur le run réel :
    # 649 créneaux proposés sur 918 étaient refusés au moment de poser la
    # séance. Un outil qui propose ce qu'il refuse ensuite est pire
    # qu'inutile — il fait perdre confiance dans tout le reste.
    sessions_by_id: dict[str, object] | None = None,
    groups: list[object] | None = None,
) -> list[SlotSuggestion]:
    """
    Propose jusqu'à `max_suggestions` créneaux FUTURS où déplacer cette
    séance ne créerait aucun conflit dur connu — retour utilisateur : "il
    faudrait proposer des solutions" plutôt que de se contenter d'un refus
    sec sur conflit, "prendre en compte les contraintes et vérifier si
    c'est possible dans tous les autres parcours".

    Couvre : conflits groupe/enseignant/salle (`validate_move`, contre le
    planning COMPLET — tous les parcours actuellement chargés, pas
    seulement celui de la séance déplacée), indispos enseignant déclarées
    (récurrentes, dates précises, liste blanche, parité de semaine — cf.
    `_teacher_free_at`, les quatre mécanismes du solveur), jours fériés/
    bloqués du calendrier, le verrou "semaine passée/en cours" (`week_status`),
    et — via les
    paramètres `extra_blocked`/`allowed_weeks` assemblés par l'appelant
    (`api/main.py::_suggestions_for`, qui a accès à `state`) — le verrou
    jeudi PAC, les jours SAE sanctuarisés, les événements du planning
    officiel à horaire précis, et l'ordre pédagogique (une séance ne peut
    être suggérée que dans une semaine compatible avec ses voisines de
    séquence, mêmes bornes que `_movable_bounds`/la régénération ciblée).

    Ne couvre PAS (limite assumée) : capacité de salle vs effectif (la
    salle proposée est celle déjà utilisée par la séance, donc déjà connue
    compatible), synchronisation duo salle rare (gérée en amont : l'appelant
    ne propose aucune suggestion pour une séance dupliquée en duo, cf.
    `_is_duo_synced`). Une régénération de semaine (`POST /regen/week`)
    reste la voie fiable à 100 % dans ces deux cas.
    """
    week_offset = semester_week_offset(calendar, semestre)
    teacher_availability = teacher_availability or []
    suggestions: list[SlotSuggestion] = []

    for week in range(search_from_week, search_from_week + max_weeks):
        if allowed_weeks is not None and week not in allowed_weeks:
            continue
        if week_status(calendar, semestre, week) != "future":
            continue
        for day in range(DAYS_PER_WEEK):
            d = calendar.week_day_to_date(week_offset + week, day)
            if d is None or d in calendar.holidays or d in calendar.blocked_dates:
                continue
            for slot in range(SLOTS_PER_DAY):
                if len(suggestions) >= max_suggestions:
                    return suggestions
                if extra_blocked and (week, day, slot) in extra_blocked:
                    continue
                result = validate_move(
                    session_id, week, day, slot, timetable, group_ids, teacher_codes, room_id,
                    sessions_by_id=sessions_by_id, groups=groups,
                )
                if not result.valid:
                    continue
                if not _teacher_free_at(teacher_codes, week, day, slot, d, teacher_availability, calendar, week_offset):
                    continue
                suggestions.append(
                    SlotSuggestion(
                        week=week, day=day, slot=slot,
                        label=f"{calendar.department_week_label(week_offset + week) or f'Semaine {week + 1}'} — {_day_name(day)} {_slot_label(slot)}",
                    )
                )
    return suggestions
