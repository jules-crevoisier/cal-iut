"""Audit ARITHMÉTIQUE de faisabilité, avant de lancer le solveur.

Famille de bugs visée : **l'impossibilité prouvée**. Une semaine déclarée
`INFEASIBLE` en 0,1 s n'est pas un problème de temps de calcul, c'est un compte
qui ne tombe pas juste. Le solveur finit par le découvrir, mais après des heures
de rééquilibrage — et sans jamais dire pourquoi.

Les trois comptes vérifiés ici correspondent aux trois causes réellement
rencontrées sur ce projet :

1. **Volume total vs jours de présence** — BUT3-CREACOM-FC ne tenait pas dans
   l'horizon par défaut (173 créneaux pour 168 disponibles).
2. **Volume d'un enseignant vs ses disponibilités déclarées** — un vacataire qui
   ne vient que 10 jours ne peut pas porter 40 séances.
3. **Jeudi après-midi réservé aux PAC** — AHA, 22 séances de formation initiale
   dans une semaine qui ne lui en offrait que 21. C'est ce compte-là, faux d'une
   unité, qui a coûté deux heures de calcul le 25/08/2026.

Tout est calculé sans CP-SAT : ce sont des bornes supérieures, donc un
dépassement signalé ici est une impossibilité CERTAINE, jamais une supposition.
L'inverse n'est pas vrai — passer cet audit ne garantit pas la faisabilité.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from cal_iut.audit.report import AuditReport, Finding, Severity
from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.ingestion.constraints_loader import StudentPresence, allowed_week_days_for_parcours
from cal_iut.models.entities import Group, TeacherAvailability
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

THURSDAY = 3
AFTERNOON_SLOTS = (3, 4, 5)


def _open_days(calendar: AcademicCalendar, week_offset: int, weeks: int) -> list[tuple[int, int, date]]:
    out: list[tuple[int, int, date]] = []
    for rel in range(weeks):
        for day in range(DAYS_PER_WEEK):
            d = calendar.week_day_to_date(week_offset + rel, day)
            if d is None or d in calendar.blocked_dates or d in calendar.holidays:
                continue
            out.append((rel, day, d))
    return out


def _teacher_open_slots(
    avail: TeacherAvailability | None,
    days: list[tuple[int, int, date]],
    *,
    exclude_thursday_pm: bool,
) -> int:
    """Borne SUPÉRIEURE du nombre de créneaux ouverts à un enseignant."""
    if avail is None:
        total = len(days) * SLOTS_PER_DAY
        if exclude_thursday_pm:
            total -= sum(len(AFTERNOON_SLOTS) for _, day, _ in days if day == THURSDAY)
        return total

    forbidden_slots = {tuple(p) for p in (avail.forbidden_slots or [])}
    allowed_slots = {tuple(p) for p in (avail.allowed_slots or [])}
    forbidden_dates = set((avail.metadata or {}).get("forbidden_dates") or [])
    allowed_dates = set(avail.allowed_dates or [])

    total = 0
    for _, day, d in days:
        iso = d.isoformat()
        if iso in forbidden_dates:
            continue
        if allowed_dates and iso not in allowed_dates:
            continue
        for slot in range(SLOTS_PER_DAY):
            if allowed_slots and (day, slot) not in allowed_slots:
                continue
            if (day, slot) in forbidden_slots:
                continue
            if exclude_thursday_pm and day == THURSDAY and slot in AFTERNOON_SLOTS:
                continue
            total += 1
    return total


def audit_capacity(
    sessions: list[SessionToPlace],
    groups: list[Group],
    availability: list[TeacherAvailability],
    presences: list[StudentPresence],
    calendar: AcademicCalendar,
    week_offset: int,
    weeks: int,
    report: AuditReport,
    *,
    fi_max_week: int | None = None,
) -> None:
    days = _open_days(calendar, week_offset, weeks)
    avail_by_code = {a.teacher_code: a for a in availability}

    # ------------------------------------------------------------------
    # 1. Volume d'un parcours vs jours où ses étudiants sont là
    # ------------------------------------------------------------------
    presence_by_parcours: dict[str, StudentPresence] = {}
    for p in presences:
        for key in p.parcours_keys:
            presence_by_parcours[key] = p

    charge_par_parcours: dict[str, int] = defaultdict(int)
    for s in sessions:
        charge_par_parcours[s.parcours] += max(1, s.duration_slots)

    # Un CM vu par toute la promo ne coûte qu'une fois à la cohorte : on
    # raisonne par COHORTE (ce que vit un étudiant), pas en cumulé.
    from cal_iut.solver.resources import build_student_cohorts

    cohorts = build_student_cohorts(groups)
    parcours_by_group = {g.id: g.parcours for g in groups}
    for key, cohort_ids in sorted(cohorts.items()):
        mine = [s for s in sessions if cohort_ids.intersection(s.group_ids)]
        if not mine:
            continue
        parcours = next((parcours_by_group[g] for g in cohort_ids if g in parcours_by_group), "")
        besoin = sum(max(1, s.duration_slots) for s in mine)

        jours = days
        presence = presence_by_parcours.get(parcours)
        if presence and presence.presence_dates:
            ouverts = allowed_week_days_for_parcours(presence, calendar, week_offset, weeks)
            jours = [(rel, day, d) for rel, day, d in days if (rel, day) in ouverts]
        is_fc = "FC" in parcours
        if fi_max_week is not None and not is_fc:
            jours = [(rel, day, d) for rel, day, d in jours if rel <= fi_max_week]
        capacite = len(jours) * SLOTS_PER_DAY
        if not is_fc:
            capacite -= sum(len(AFTERNOON_SLOTS) for _, day, _ in jours if day == THURSDAY)

        if besoin > capacite:
            report.add(Finding(
                Severity.ERREUR,
                "capacite.cohorte_impossible",
                f"{key} ({parcours}) : {besoin} créneaux à placer pour {capacite} disponibles "
                f"sur {len(jours)} jours de présence — impossible par construction.",
                quoi_faire=(
                    "Étendre l'horizon (`--weeks`), lever la borne `--fi-max-week`, ou "
                    "réduire le volume du parcours. Ce n'est pas un réglage de solveur : "
                    "le compte ne tombe pas."),
                ou="maquette + calendrier de présence",
            ))
        elif besoin > capacite * 0.9:
            report.add(Finding(
                Severity.ALERTE,
                "capacite.cohorte_saturee",
                f"{key} ({parcours}) : {besoin}/{capacite} créneaux ({besoin * 100 // capacite} %) "
                "— très peu de marge, le solveur risque d'échouer sur certaines semaines.",
                quoi_faire="Prévoir une marge : étendre l'horizon si c'est possible.",
                ou="maquette + calendrier de présence",
            ))

    # ------------------------------------------------------------------
    # 2. Volume d'un enseignant vs ses disponibilités sur l'année
    # ------------------------------------------------------------------
    charge_prof: dict[str, int] = defaultdict(int)
    charge_prof_fi: dict[str, int] = defaultdict(int)
    for s in sessions:
        duree = max(1, s.duration_slots)
        for code in s.teacher_codes:
            charge_prof[code] += duree
            if "FC" not in s.parcours:
                charge_prof_fi[code] += duree

    for code, besoin in sorted(charge_prof.items()):
        avail = avail_by_code.get(code)
        capacite = _teacher_open_slots(avail, days, exclude_thursday_pm=False)
        if besoin > capacite:
            report.add(Finding(
                Severity.ERREUR,
                "capacite.enseignant_impossible",
                f"{code} : {besoin} créneaux à assurer pour {capacite} créneaux déclarés "
                "disponibles sur toute l'année.",
                quoi_faire=(
                    "Élargir ses disponibilités dans le CSV, ou redistribuer une partie de "
                    "son volume dans la maquette."),
                ou="contraintes/05_enseignants_contraintes.json",
            ))
        elif capacite and besoin > capacite * 0.75:
            report.add(Finding(
                Severity.ALERTE,
                "capacite.enseignant_sature",
                f"{code} : {besoin}/{capacite} créneaux ({besoin * 100 // capacite} %) de ses "
                "disponibilités déclarées.",
                quoi_faire=(
                    "Marge faible : ses séances devront tomber presque exactement sur ses "
                    "créneaux libres, ce qui contraint fortement tout le reste."),
                ou="contraintes/05_enseignants_contraintes.json",
            ))

    # ------------------------------------------------------------------
    # 3. Le compte qui a coûté deux heures : jeudi après-midi réservé aux PAC
    # ------------------------------------------------------------------
    for code, besoin_fi in sorted(charge_prof_fi.items()):
        if not besoin_fi:
            continue
        avail = avail_by_code.get(code)
        capacite_fi = _teacher_open_slots(avail, days, exclude_thursday_pm=True)
        if besoin_fi > capacite_fi:
            report.add(Finding(
                Severity.ERREUR,
                "capacite.jeudi_pac_impossible",
                f"{code} : {besoin_fi} créneaux de FORMATION INITIALE pour {capacite_fi} "
                "créneaux disponibles hors jeudi après-midi (réservé aux PAC).",
                quoi_faire=(
                    "Le jeudi après-midi ne compte pas pour la formation initiale. Élargir "
                    "ses disponibilités, ou basculer une partie de son volume en FC."),
                ou="contraintes/05_enseignants_contraintes.json",
            ))

    report.ok(
        "capacite",
        f"{len(cohorts)} cohorte(s) et {len(charge_prof)} enseignant(s) vérifiés "
        f"sur {len(days)} jours ouvrables",
    )


def audit_salles_rares(
    sessions: list[SessionToPlace],
    groups: list[Group],
    rooms: list,
    report: AuditReport,
) -> None:
    """Combien de séances exigent une GRANDE salle, pour combien de grandes salles ?

    Angle mort structurel trouvé le 26/08/2026 en explorant `rooms.py` par tests
    de propriété : **le solveur ne modélise pas les salles du tout**. Elles sont
    attribuées gloutonnement APRÈS coup. Rien ne l'empêche donc de programmer au
    même créneau deux CM de promotions différentes qui ont chacun besoin d'un
    amphi — alors que le bâtiment n'en compte qu'un (H.018, 150 places ; la
    suivante fait 36). L'affectation retombe alors sur une salle trop petite,
    silencieusement (cf. le dernier recours de `rooms.py::_pick`).

    Ce contrôle mesure la marge AVANT de résoudre : combien de cohortes ne
    tiennent que dans une grande salle, et combien de grandes salles existent.
    """
    if not rooms:
        return
    standard_max = max(
        (r.capacity for r in rooms if r.room_type.value not in ("amphi", "evaluation")),
        default=0,
    )
    grandes = [r for r in rooms if r.capacity > standard_max]
    if not grandes:
        return

    from cal_iut.solver.rooms import _headcount_for_groups

    exigeantes: dict[str, int] = {}
    for session in sessions:
        besoin = _headcount_for_groups(session.group_ids, groups)
        if besoin > standard_max:
            exigeantes[session.parcours] = exigeantes.get(session.parcours, 0) + 1

    # La salle d'ÉVALUATION est réservée aux `is_eval` par `rooms.yaml` :
    # l'utiliser pour un cours ordinaire est déjà un repli dégradé, elle ne
    # compte donc pas dans la capacité courante.
    ordinaires = [r for r in grandes if r.room_type.value != "evaluation"]
    detail = [f"{parcours} : {n} séance(s)" for parcours, n in sorted(exigeantes.items())]
    inventaire = ", ".join(f"{r.label} ({r.capacity} pl.)" for r in grandes)

    if len(exigeantes) > len(ordinaires):
        report.add(Finding(
            Severity.ALERTE,
            "capacite.salles_rares",
            f"{len(exigeantes)} parcours ont des séances qui ne tiennent que dans une "
            f"grande salle, pour {len(ordinaires)} salle(s) ordinaire(s) assez grande(s) "
            f"— inventaire complet : {inventaire}.",
            quoi_faire=(
                "Le solveur ne connaît PAS les salles : rien ne l'empêche de programmer "
                "deux de ces séances au même créneau. L'affectation retombera alors sur "
                "la salle d'évaluation, voire sur une salle trop petite — silencieusement. "
                "Surveiller le contrôle `room_capacity` après chaque run, et vérifier "
                "qu'aucune évaluation ne tombe en même temps qu'un grand CM."),
            ou="data/config/rooms.yaml",
            details=detail,
        ))
    elif len(exigeantes) == len(ordinaires):
        report.add(Finding(
            Severity.ALERTE,
            "capacite.salles_rares_sans_marge",
            f"{len(exigeantes)} parcours exigent une grande salle pour exactement "
            f"{len(ordinaires)} salle(s) ordinaire(s) disponible(s) : aucune marge.",
            quoi_faire=(
                "Tient tant que ces séances ne sont jamais simultanées — ce que le "
                "solveur ne garantit PAS, n'ayant aucune connaissance des salles. "
                "Vérifier `room_capacity` à chaque run."),
            ou="data/config/rooms.yaml",
            details=detail,
        ))
    else:
        report.ok("capacite.salles_rares",
                  f"{len(ordinaires)} salle(s) ordinaire(s) assez grande(s) pour "
                  f"{len(exigeantes)} parcours exigeant")


def audit_weekly_capacity(
    sessions_by_week: dict[int, list[SessionToPlace]],
    availability: list[TeacherAvailability],
    calendar: AcademicCalendar,
    week_offset: int,
    report: AuditReport,
) -> None:
    """Même compte, semaine par semaine, sur une affectation DÉJÀ décidée.

    Sert à expliquer un `PARTIAL_WEEKS_FAILED` : c'est la version « après coup »
    de l'audit ci-dessus, celle qui nomme la semaine et l'enseignant fautifs au
    lieu de laisser lire `INFEASIBLE`.
    """
    avail_by_code = {a.teacher_code: a for a in availability}
    for w, sess in sorted(sessions_by_week.items()):
        days = [
            (0, day, d)
            for day in range(DAYS_PER_WEEK)
            if (d := calendar.week_day_to_date(week_offset + w, day)) is not None
            and d not in calendar.blocked_dates
            and d not in calendar.holidays
        ]
        if not days:
            continue
        charge: dict[str, int] = defaultdict(int)
        charge_fi: dict[str, int] = defaultdict(int)
        for s in sess:
            duree = max(1, s.duration_slots)
            for code in s.teacher_codes:
                charge[code] += duree
                if "FC" not in s.parcours:
                    charge_fi[code] += duree
        for code, besoin in sorted(charge.items()):
            avail = avail_by_code.get(code)
            capacite = _teacher_open_slots(avail, days, exclude_thursday_pm=False)
            capacite_fi = _teacher_open_slots(avail, days, exclude_thursday_pm=True)
            if besoin > capacite:
                report.add(Finding(
                    Severity.ERREUR, "capacite.semaine_enseignant",
                    f"Semaine {w} ({days[0][2]}) : {code} a {besoin} créneaux pour "
                    f"{capacite} disponibles — cette semaine est prouvée infaisable.",
                    quoi_faire="Déplacer des séances de cet enseignant vers une autre semaine.",
                    ou=f"semaine {w}"))
            elif charge_fi.get(code, 0) > capacite_fi:
                report.add(Finding(
                    Severity.ERREUR, "capacite.semaine_jeudi_pac",
                    f"Semaine {w} ({days[0][2]}) : {code} a {charge_fi[code]} créneaux de "
                    f"formation initiale pour {capacite_fi} disponibles hors jeudi après-midi.",
                    quoi_faire=(
                        "Le jeudi après-midi est réservé aux PAC : il ne compte pas pour la "
                        "FI. Déplacer des séances FI de cet enseignant."),
                    ou=f"semaine {w}"))
