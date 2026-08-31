"""Export HTML autonome : calendrier interactif (vue groupe/enseignant, contraintes).

Internalise dans le projet la vue de démonstration (calendrier + vérifications
automatiques) : `cal-iut export --format html` régénère ce fichier à partir
d'un `timetable.json` déjà résolu, sans dépendance externe (auto-contenu,
thème clair/sombre). Inclut : vue groupe (TD 2 colonnes TP), vue enseignant,
et un tableau de bord « Contraintes » qui affiche chaque règle (enseignant ou
solveur) et son verdict recalculé depuis la sortie brute du solveur.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from cal_iut.calendar.academic import (
    AcademicCalendar,
    build_default_calendar_2026_2027,
    semester_week_offset,
    week_status,
)
from cal_iut.ingestion.constraints_loader import allowed_week_days_for_parcours
from cal_iut.solver.decomposed import FC_WEEKLY_CAP_SLOTS, FI_WEEKLY_CAP_SLOTS, _cours_avec_progression_declaree
from cal_iut.models.entities import Group, Room, TeacherAvailability
from cal_iut.models.group_scope import expand_group_filter, resolve_tp_ids_for_td
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.constraints import sae_blocked_days_by_parcours

TEMPLATE_PATH = Path(__file__).parent / "templates" / "timetable.html"

DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]

# Dates institutionnelles confirmées (cahier des charges §6) — informatif,
# affiché tel quel dans l'onglet Contraintes, jamais utilisé pour bloquer le
# solveur (ça, c'est le rôle d'AcademicCalendar).
INSTITUTIONAL_EVENTS = [
    {"label": "Pause pédagogique (Toussaint)", "start": "2026-10-26", "end": "2026-10-30", "kind": "vacances"},
    {"label": "Pause pédagogique (fin d'année)", "start": "2026-12-21", "end": "2027-01-01", "kind": "vacances"},
    {"label": "Pause pédagogique (hiver)", "start": "2027-02-22", "end": "2027-02-26", "kind": "vacances"},
    {"label": "Pause pédagogique (printemps)", "start": "2027-04-19", "end": "2027-04-30", "kind": "vacances"},
    {"label": "Pause pédagogique (Ascension)", "start": "2027-05-06", "end": "2027-05-07", "kind": "vacances"},
    {"label": "Armistice", "start": "2026-11-11", "end": "2026-11-11", "kind": "ferie"},
    {"label": "Lundi de Pâques", "start": "2027-03-29", "end": "2027-03-29", "kind": "ferie"},
    {"label": "Fête du Travail", "start": "2027-05-01", "end": "2027-05-01", "kind": "ferie"},
    {"label": "Ascension", "start": "2027-05-06", "end": "2027-05-06", "kind": "ferie"},
    {"label": "Lundi de Pentecôte", "start": "2027-05-17", "end": "2027-05-17", "kind": "ferie"},
    {"label": "Rentrée BUT3-FC/ALT", "start": "2026-08-31", "end": "2026-08-31", "kind": "rentree"},
    {"label": "Rentrée BUT1 (S1)", "start": "2026-09-02", "end": "2026-09-02", "kind": "rentree"},
    {"label": "Rentrée BUT2-FI", "start": "2026-09-02", "end": "2026-09-02", "kind": "rentree"},
    {"label": "Rentrée BUT3-FI", "start": "2026-09-02", "end": "2026-09-02", "kind": "rentree"},
    {"label": "Rentrée BUT2-FC/ALT", "start": "2026-09-14", "end": "2026-09-14", "kind": "rentree"},
    {"label": "Semaine d'intégration BUT1 (accueil, pas de cours classique)", "start": "2026-09-02", "end": "2026-09-04", "kind": "special"},
    {"label": "Vrai démarrage des enseignements S1", "start": "2026-09-07", "end": "2026-09-07", "kind": "special"},
    {"label": "Fin des cours S4-FI / S6-FI (avant stages)", "start": "2027-04-09", "end": "2027-04-09", "kind": "special"},
    {"label": "Début des stages S4-FI / S6-FI", "start": "2027-04-12", "end": "2027-04-12", "kind": "special"},
    {"label": "Fin des cours (toutes promos)", "start": "2027-06-30", "end": "2027-06-30", "kind": "special"},
]


def _group_maps(groups: list[Group]) -> tuple[dict, dict, dict, dict, dict]:
    labels: dict[str, str] = {}
    kinds: dict[str, str] = {}
    cohorts: dict[str, list[str]] = {}
    tp_pairs: dict[str, list[str]] = {}
    is_fc: dict[str, bool] = {}

    for g in groups:
        labels[g.id] = g.label
        kinds[g.id] = g.kind
        cohorts[g.id] = sorted(expand_group_filter(g.id, groups))
        is_fc[g.id] = "FC" in g.parcours
        if g.kind == "td":
            tp_ids = resolve_tp_ids_for_td(g, groups)
            if tp_ids:
                pair = [tp_ids[0], tp_ids[1] if len(tp_ids) > 1 else tp_ids[0]]
                tp_pairs[g.id] = pair

    return labels, kinds, cohorts, tp_pairs, is_fc


def _teacher_names(sessions: list[SessionToPlace]) -> dict[str, str]:
    names: dict[str, str] = {}
    for s in sessions:
        for t in s.teachers:
            if t.code and t.code not in names:
                full = f"{t.prenom} {t.nom}".strip()
                names[t.code] = full or t.code
    return names


def _teacher_payload(
    teacher_availability: list[TeacherAvailability],
    sessions_by_id: dict[str, SessionToPlace],
    placements: list[dict],
    teacher_names: dict[str, str],
    calendar: AcademicCalendar | None,
    week_offset: int,
    sae_supervisor_dates: dict[str, set] | None = None,
) -> list[dict]:
    by_teacher: dict[str, list[dict]] = defaultdict(list)
    for p in placements:
        for code in p["teacher_codes"]:
            by_teacher[code].append(p)
    sae_supervisor_dates = sae_supervisor_dates or {}

    result: list[dict] = []
    for t in teacher_availability:
        placed = by_teacher.get(t.teacher_code, [])
        forbidden_slots = set(tuple(x) for x in t.forbidden_slots)
        forbidden_dates_raw = t.metadata.get("forbidden_dates") or []
        forbidden_dates = {date.fromisoformat(str(d)) for d in forbidden_dates_raw}
        # Dates ajoutées à `forbidden_dates` UNIQUEMENT parce que cet
        # enseignant encadre une SAE ce jour-là (cf.
        # `augment_teacher_availability_with_sae_supervision`, docs/DATA.md
        # §48.2/§49) — à distinguer d'une VRAIE indisponibilité déclarée par
        # l'enseignant : en mode mou (`--no-sae-supervisor-hard`, le réglage
        # utilisé pour un run complet), le solveur les traite comme une
        # préférence, pas un interdit, donc en violer certaines est un
        # compromis ATTENDU, pas une anomalie à traiter au même titre qu'une
        # vraie indisponibilité (retour utilisateur 11/08/2026 : "152
        # contrainte non respectée, ce n'est pas possible" — diagnostic réel :
        # 115/152 étaient EXACTEMENT ce compromis, 0 vraie violation de
        # disponibilité déclarée, cf. docs/DATA.md §59).
        sae_dates_this_teacher = sae_supervisor_dates.get(t.teacher_code, set())

        recurring_violations = []
        date_violations = []
        for p in placed:
            if (p["day"], p["slot"]) in forbidden_slots:
                recurring_violations.append(
                    {"week": p["week"], "day": p["day"], "slot": p["slot"], "course_code": p["course_code"]}
                )
            if calendar is not None and forbidden_dates:
                d = calendar.week_day_to_date(week_offset + p["week"], p["day"])
                if d in forbidden_dates:
                    date_violations.append(
                        {
                            "date": d.isoformat(),
                            "course_code": p["course_code"],
                            "reason": "sae_supervision" if d in sae_dates_this_teacher else "declared",
                        }
                    )

        has_constraint = bool(forbidden_slots or forbidden_dates or t.notes)
        if not has_constraint and not placed:
            continue

        n_violations = len(recurring_violations) + len(date_violations)
        result.append(
            {
                "code": t.teacher_code,
                "name": teacher_names.get(t.teacher_code, t.teacher_code),
                "rawIndisponibilites": t.metadata.get("raw_indisponibilites") or "",
                "rawDisponibilites": t.metadata.get("raw_disponibilites") or "",
                "rawContraintes": t.metadata.get("raw_contraintes") or "",
                "forbiddenSlots": [[d, s] for d, s in sorted(forbidden_slots)],
                "forbiddenDates": sorted(d.isoformat() for d in forbidden_dates),
                "nPlaced": len(placed),
                "violations": recurring_violations + date_violations,
                "hasConstraint": has_constraint,
            }
        )

    result.sort(key=lambda r: r["name"])
    return result


@lru_cache(maxsize=1)
def _cap_exceptions() -> dict[tuple[str, int], int]:
    """Dérogations au plafond hebdomadaire, résolues en (parcours, semaine)."""
    from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
    from cal_iut.ingestion.config_loader import load_weekly_cap_exceptions
    from cal_iut.solver.decomposed import weekly_cap_exceptions_by_parcours_week

    calendar = build_default_calendar_2026_2027()
    config = Path(__file__).resolve().parents[3] / "data" / "config"
    return weekly_cap_exceptions_by_parcours_week(
        load_weekly_cap_exceptions(config), calendar, semester_week_offset(calendar, "S1")
    )


def _parcours_of(group_id: str, groups: list[Group]) -> str:
    for g in groups:
        if g.id == group_id:
            return g.parcours
    return ""


@lru_cache(maxsize=1)
def _solver_scheduled_sae() -> frozenset[tuple[str, str]]:
    """cf. `config_loader.load_solver_scheduled_sae` — mis en cache : appelé
    une fois par placement lors de la vérification des règles."""
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    return frozenset(
        load_solver_scheduled_sae(Path(__file__).resolve().parents[3] / "data" / "config")
    )


def _rule_checks(
    sessions_by_id: dict[str, SessionToPlace],
    placements: list[dict],
    groups: list[Group],
    cohorts: dict[str, list[str]],
    kinds: dict[str, str],
    is_fc: dict[str, bool],
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None,
    rooms: list[Room] | None = None,
    tier_values: dict[str, int] | None = None,
    calendar: AcademicCalendar | None = None,
    week_offset: int = 0,
    teacher_availability: list[TeacherAvailability] | None = None,
    sae_supervisor_dates: dict[str, set] | None = None,
) -> list[dict]:
    checks: list[dict] = []
    SLOTS_PER_DAY_LOCAL = 6

    # -- Capacité salle vs effectif de la cohorte (ex. CM = toute la promo) --
    # Un CM doit contenir tous les étudiants de la promo (rappel utilisateur) :
    # ça n'a de sens que si la salle affectée peut physiquement tous les
    # accueillir. Réutilise `_headcount_for_groups` (même calcul que
    # l'affectation de salle réelle, cf. solver/rooms.py) pour ne jamais
    # vérifier une règle différente de celle réellement appliquée.
    if rooms:
        from cal_iut.solver.rooms import _headcount_for_groups

        room_by_id = {r.id: r for r in rooms}
        over_capacity = []
        for p in placements:
            room = room_by_id.get(p.get("room_id"))
            if room is None:
                continue
            needed = _headcount_for_groups(p["group_ids"], groups)
            if needed > room.capacity:
                over_capacity.append((p["session_id"], p.get("room_label") or room.label, needed, room.capacity))
        checks.append(
            {
                "id": "room_capacity",
                "label": "Capacité de la salle suffisante pour la cohorte (ex. CM = toute la promo)",
                "status": "pass" if not over_capacity else "fail",
                "detail": (
                    "Aucune séance au-dessus de la capacité de sa salle."
                    if not over_capacity
                    else (
                        f"{len(over_capacity)} séance(s) où l'effectif dépasse la capacité de la "
                        f"salle affectée (ex. {over_capacity[0][0]} : {over_capacity[0][2]} "
                        f"étudiants attendus, {over_capacity[0][1]} ne contient que "
                        f"{over_capacity[0][3]} places) — donnée à confirmer (effectif de "
                        "cohorte ou capacité de salle probablement à corriger)."
                    )
                ),
            }
        )

    # -- Plafond horaire hebdomadaire --
    leaf_groups = [gid for gid, k in kinds.items() if k in ("tp", "promo")]
    # TD sans TP résolu (rare) : traité comme feuille aussi
    td_without_tp = [gid for gid, k in kinds.items() if k == "td" and gid not in cohorts]
    over_cap = []
    for gid in leaf_groups + td_without_tp:
        cohort = set(cohorts.get(gid, [gid]))
        weekly = defaultdict(int)
        seen = set()
        for p in placements:
            if not cohort.intersection(p["group_ids"]):
                continue
            key = (p["week"], p["day"], p["slot"])
            if key in seen:
                continue
            seen.add(key)
            # Une séance "double" (ex. TP collé en bloc de 3h) compte pour
            # `duration_slots` créneaux, pas 1 — même calcul que la contrainte
            # dure du solveur (`add_weekly_hour_cap_constraints`).
            session = sessions_by_id.get(p["session_id"])
            weekly[p["week"]] += max(1, getattr(session, "duration_slots", 1))
        # SOURCE UNIQUE partagée avec le solveur : vérifier un plafond que le
        # solveur n'applique pas produit des « violations » inexplicables — ce
        # qui est arrivé pendant dix jours (cf. le commentaire sur
        # `FI_WEEKLY_CAP_SLOTS`).
        cap = FC_WEEKLY_CAP_SLOTS if is_fc.get(gid) else FI_WEEKLY_CAP_SLOTS
        # Les dérogations CIBLÉES au plafond (`weekly_cap_exceptions`) sont des
        # décisions documentées, pas des violations : sans les lire, ce contrôle
        # signalait « 8 cohortes au-dessus du plafond » alors que la seule
        # semaine concernée avait été explicitement autorisée. Un contrôle qui
        # crie à tort finit ignoré — et c'est ainsi qu'une vraie violation passe.
        for semaine, charge in weekly.items():
            plafond = max(cap, _cap_exceptions().get((_parcours_of(gid, groups), semaine), 0))
            if charge > plafond:
                over_cap.append((gid, charge, plafond))
                break
    checks.append(
        {
            "id": "weekly_cap",
            "label": "Plafond horaire hebdomadaire (33h FI / ~35h FC)",
            "status": "pass" if not over_cap else "fail",
            "detail": (
                "Aucune cohorte au-dessus de son plafond (22 créneaux FI / 23 FC)."
                if not over_cap
                else f"{len(over_cap)} cohorte(s) au-dessus du plafond : {over_cap[:5]}"
            ),
        }
    )

    # -- Jeudi après-midi (PAC) pour la FI --
    thursday_hits = [
        p for p in placements
        if p["day"] == 3 and p["slot"] >= 3
        and not any(is_fc.get(g) for g in p["group_ids"] if g in is_fc)
    ]
    checks.append(
        {
            "id": "thursday_pac",
            "label": "Jeudi après-midi réservé aux PAC (formation initiale)",
            "status": "pass" if not thursday_hits else "fail",
            "detail": (
                "0 séance classique placée jeudi après-midi pour la FI."
                if not thursday_hits
                else f"{len(thursday_hits)} séance(s) FI placées jeudi après-midi."
            ),
        }
    )

    # -- Sanctuarisation SAE --
    if sae_days_by_course:
        blocked_by_parcours = sae_blocked_days_by_parcours(list(sessions_by_id.values()), sae_days_by_course)
        sae_hits = []
        for p in placements:
            s = sessions_by_id.get(p["session_id"])
            # Une SAE que le solveur place lui-même (`solver_scheduled_sae`,
            # ex. WSA501D) est soumise à la sanctuarisation des AUTRES SAE de
            # son parcours, exactement comme un cours classique — la relire
            # depuis la config plutôt que de se fier au préfixe "WS".
            if s is None or (
                s.course_code.upper().startswith("WS")
                and (s.course_code.upper(), s.semestre) not in _solver_scheduled_sae()
            ):
                continue
            if (p["week"], p["day"]) in blocked_by_parcours.get(s.parcours, set()):
                sae_hits.append(p)
        checks.append(
            {
                "id": "sae_sanctuarization",
                "label": "Sanctuarisation SAE (jour SAE ⇒ pas de cours classique ce jour)",
                "status": "pass" if not sae_hits else "fail",
                "detail": (
                    "0 cours classique placé un jour réservé à une SAE."
                    if not sae_hits
                    else f"{len(sae_hits)} cours classique(s) placés un jour SAE."
                ),
            }
        )

    # -- Éval -> salle A.018 --
    eval_rows = [p for p in placements if sessions_by_id.get(p["session_id"]) and sessions_by_id[p["session_id"]].is_eval]
    # Ne se prononce que si des salles ont RÉELLEMENT été affectées : sur un run
    # incomplet, `cal-iut solve` n'attribue aucune salle, et ce contrôle
    # déclarait alors « 16/16 évaluations hors A.018 » — un faux échec qui
    # détourne l'attention du vrai problème (le run incomplet lui-même).
    if eval_rows and any(p.get("room_label") for p in placements):
        eval_bad = [p for p in eval_rows if not (p.get("room_label") or "").startswith("A.018")]
        checks.append(
            {
                "id": "eval_room",
                "label": "Toute évaluation en salle A.018",
                "status": "pass" if not eval_bad else "fail",
                "detail": (
                    f"{len(eval_rows)} évaluation(s), toutes en A.018."
                    if not eval_bad
                    else f"{len(eval_bad)}/{len(eval_rows)} évaluations hors A.018."
                ),
            }
        )

    # -- Semaine d'intégration, tous les FI (semaine-index 0) --
    # Généralisé le 11/08/2026 (retour utilisateur) de "S1 uniquement" à tous
    # les parcours FI — cf. `solver/constraints.py::add_s1_integration_week_lock`.
    week0_hits = [
        p for p in placements
        if p["week"] == 0
        and sessions_by_id.get(p["session_id"])
        and "FC" not in sessions_by_id[p["session_id"]].parcours
    ]
    checks.append(
        {
            "id": "s1_integration_lock",
            "label": "Semaine d'intégration FI sans cours classique (BUT1/BUT2-DEV-FI/BUT3-DEV-FI)",
            "status": "pass" if not week0_hits else "fail",
            "detail": (
                "0 séance FI en semaine-index 0 (semaine d'intégration)."
                if not week0_hits
                else f"{len(week0_hits)} séance(s) FI placées en semaine d'intégration."
            ),
        }
    )

    # -- Ordre pédagogique (dur) --
    # Reproduit EXACTEMENT les deux contraintes du solveur (cf. §10
    # docs/DATA.md) — ne pas vérifier plus strict que ce qui est réellement
    # garanti, sous peine de faux "échecs" :
    #  1) ordre par `group_id` littéral (TD/TP propres à un sous-groupe, CM
    #     entre eux) — volontairement PAS synchronisé entre sous-groupes à
    #     chaque étape intermédiaire ;
    #  2) barrière dure ciblée : une éval doit suivre le dernier contenu de
    #     CHAQUE cohorte réelle (feuille de `build_student_cohorts`).
    slots_per_week = 30
    t_of = {p["session_id"]: p["week"] * slots_per_week + p["day"] * 6 + p["slot"] for p in placements}

    by_group_course: dict[tuple[str, str], list[SessionToPlace]] = defaultdict(list)
    for sid, s in sessions_by_id.items():
        if sid not in t_of or s.sequence_order is None:
            continue
        for gid in s.group_ids:
            by_group_course[(s.course_code, gid)].append(s)

    # Séances du MÊME type (TD-TD, TP-TP) exemptées quand aucune progression
    # de contenu n'est déclarée pour ce cours — même correctif que le
    # solveur (`decomposed.py::assign_weeks`/`_build_sequence_neighbors`,
    # retour utilisateur 27/08/2026, Kyllian Bresson : « TD n°3 avant TD
    # n°1, ce n'est pas une erreur »). Un rapport qui signale plus strict
    # que ce que le solveur applique réellement n'aiderait personne.
    cours_avec_progression = _cours_avec_progression_declaree(Path(__file__).resolve().parents[3])

    seq_violations = 0
    seq_checked = 0
    for key, sess_list in by_group_course.items():
        ordered = sorted(sess_list, key=lambda s: s.sequence_order or 0)
        for a, b in zip(ordered, ordered[1:]):
            if (a.sequence_order or 0) == (b.sequence_order or 0):
                continue
            if a.session_type == b.session_type and (a.course_code, a.semestre) not in cours_avec_progression:
                continue
            seq_checked += 1
            if not (t_of[a.id] < t_of[b.id]):
                seq_violations += 1

    from cal_iut.solver.resources import build_student_cohorts

    leaf_cohorts = build_student_cohorts(groups)
    by_course_sessions: dict[str, list[SessionToPlace]] = defaultdict(list)
    for sid, s in sessions_by_id.items():
        if sid in t_of and s.sequence_order is not None:
            by_course_sessions[s.course_code].append(s)

    eval_after_violations = 0
    eval_checked = 0
    for course_sessions in by_course_sessions.values():
        evals = [s for s in course_sessions if s.is_eval]
        non_evals = [s for s in course_sessions if not s.is_eval]
        if not evals or not non_evals:
            continue
        for cohort_ids in leaf_cohorts.values():
            cohort_non_evals = [s for s in non_evals if cohort_ids.intersection(s.group_ids)]
            if not cohort_non_evals:
                continue
            last = max(cohort_non_evals, key=lambda s: s.sequence_order or 0)
            for e in evals:
                if (last.sequence_order or 0) >= (e.sequence_order or 0):
                    continue
                eval_checked += 1
                if not (t_of[last.id] < t_of[e.id]):
                    eval_after_violations += 1

    checks.append(
        {
            "id": "pedagogical_order",
            "label": "Ordre pédagogique CM→TD→TP respecté (progression.json)",
            "status": "pass" if seq_violations == 0 else "fail",
            "detail": f"{seq_violations}/{seq_checked} séances hors ordre (doit être 0, contrainte dure).",
        }
    )
    checks.append(
        {
            "id": "eval_after_content",
            "label": "Évaluation placée après tout le contenu du module",
            "status": "pass" if eval_after_violations == 0 else "fail",
            "detail": f"{eval_after_violations}/{eval_checked} évaluations placées avant la fin du contenu (doit être 0).",
        }
    )

    # -- Ordre pédagogique VU PAR L'ÉTUDIANT (CM promo <-> TD/TP sous-groupe) --
    # Le contrôle `pedagogical_order` ci-dessus ne compare que des séances du
    # même `group_id` brut : il ne voyait donc PAS un CM programmé après les TD
    # qu'il doit précéder (790 paires hors ordre sur le run `odd26`, alors que
    # `pedagogical_order` était au vert). Cf.
    # `solver/constraints.py::cohort_sequence_pairs`.
    from cal_iut.solver.constraints import cohort_sequence_pairs

    placed_sessions = [s for sid, s in sessions_by_id.items() if sid in t_of]
    cohort_pairs = cohort_sequence_pairs(placed_sessions, groups)
    cohort_violations = [
        (before, after) for before, after in cohort_pairs if not (t_of[before] < t_of[after])
    ]
    checks.append(
        {
            "id": "cohort_pedagogical_order",
            "label": "Ordre pédagogique vu par l'étudiant (CM avant les TD/TP qui le suivent)",
            "status": "pass" if not cohort_violations else "fail",
            "detail": (
                f"{len(cohort_violations)}/{len(cohort_pairs)} paires hors ordre "
                "toutes granularités confondues (CM promo vs TD/TP de sous-groupe)."
                + (
                    f" Ex. {cohort_violations[0][0]} devrait précéder {cohort_violations[0][1]}."
                    if cohort_violations
                    else ""
                )
            ),
        }
    )

    # -- Bornes de fin par cours (`max_week_rules`) --
    from cal_iut.ingestion.config_loader import load_course_max_week_rules

    max_week_rules = load_course_max_week_rules(Path(__file__).resolve().parents[3] / "data" / "config")
    if max_week_rules:
        by_key_max = {(r.course_code, r.semestre): r for r in max_week_rules}
        late_by_course: dict[str, tuple[int, int]] = {}
        for p_row in placements:
            sess = sessions_by_id.get(p_row["session_id"])
            if sess is None:
                continue
            rule = by_key_max.get((sess.course_code, sess.semestre))
            if rule is None or p_row["week"] <= rule.max_week:
                continue
            current = late_by_course.get(sess.course_code)
            worst = max(current[0], p_row["week"]) if current else p_row["week"]
            late_by_course[sess.course_code] = (worst, rule.max_week)
        checks.append(
            {
                "id": "course_max_week",
                "label": "Bornes de fin de module respectées (max_week_rules)",
                "status": "pass" if not late_by_course else "fail",
                "detail": (
                    f"{len(max_week_rules)} borne(s) déclarée(s), toutes respectées."
                    if not late_by_course
                    else "; ".join(
                        f"{code} déborde en semaine-index {worst} (borne {limit})"
                        for code, (worst, limit) in sorted(late_by_course.items())
                    )
                ),
            }
        )

    # -- Fenêtres de dates civiles par séance --
    # Règle documentée « dure » depuis le 10/08/2026 mais jamais vérifiée, et
    # jamais appliquée en mode `--decomposed` avant le 25/08/2026 : sur le run
    # `odd26`, la visite à la BU (WR100BU TD n°1, fenêtre 1-15 septembre) était
    # placée du 21 au 25 septembre sans que rien ne le signale.
    from cal_iut.ingestion.config_loader import load_session_date_windows

    date_rules = load_session_date_windows(Path(__file__).resolve().parents[3] / "data" / "config")
    if date_rules and calendar is not None:
        window_violations: list[str] = []
        window_checked = 0
        for rule in date_rules:
            start = date.fromisoformat(rule.start_date) if rule.start_date else None
            end = date.fromisoformat(rule.end_date) if rule.end_date else None
            only = {date.fromisoformat(d) for d in rule.only_dates}
            for p_row in placements:
                sess = sessions_by_id.get(p_row["session_id"])
                if sess is None or sess.course_code != rule.course_code or sess.semestre != rule.semestre:
                    continue
                if rule.session_type is not None and sess.session_type != rule.session_type:
                    continue
                if rule.sequence_orders and sess.sequence_order not in rule.sequence_orders:
                    continue
                placed = calendar.week_day_to_date(week_offset + p_row["week"], p_row["day"])
                if placed is None:
                    continue
                window_checked += 1
                if (
                    (only and placed not in only)
                    or (start is not None and placed < start)
                    or (end is not None and placed > end)
                ):
                    window_violations.append(f"{p_row['session_id']} le {placed.isoformat()}")
        checks.append(
            {
                "id": "session_date_windows",
                "label": "Fenêtres de dates imposées à une séance précise",
                "status": "pass" if not window_violations else "fail",
                "detail": (
                    f"{window_checked} séance(s) sous fenêtre, toutes dans leur fenêtre."
                    if not window_violations
                    else f"{len(window_violations)}/{window_checked} hors fenêtre : "
                    + ", ".join(window_violations[:4])
                ),
            }
        )

    # -- SAE que le solveur doit placer lui-même --
    scheduled_sae = _solver_scheduled_sae()
    if scheduled_sae:
        details = []
        all_ok = True
        for code, semestre in sorted(scheduled_sae):
            due = [
                s for s in sessions_by_id.values()
                if s.course_code.upper() == code and s.semestre == semestre
            ]
            done = [s for s in due if s.id in t_of]
            if len(done) != len(due) or not due:
                all_ok = False
            details.append(f"{code} ({semestre}) : {len(done)}/{len(due)} séances placées")
        checks.append(
            {
                "id": "sae_solver_scheduled",
                "label": "SAE planifiées par le solveur (solver_scheduled_sae)",
                "status": "pass" if all_ok else "fail",
                "detail": " ; ".join(details),
            }
        )

    # -- Ordonnancement inter-matières (moyenne par groupe) --
    # `solve_tiered` (mode par défaut, cf. docs/DATA.md §12.3) minimise
    # d'abord CE critère puis le VERROUILLE à sa valeur atteinte avant de
    # continuer : `tier_values["ordonnancement"]` est donc le vrai minimum
    # trouvé, pas un compromis pondéré — une violation dans ce mode est un
    # vrai défaut ("fail"). En mode somme pondérée historique (ou si le mode
    # réel n'est pas connu ici, `tier_values` absent), une violation reste
    # attendue par construction (poids fini, pas une garantie) : "info" pour
    # éviter le faux-échec documenté en §10.3. 0 violation reste "pass" dans
    # tous les cas.
    ord_relations = set()
    for s in sessions_by_id.values():
        for o in s.metadata.get("ordonnancement") or []:
            pos = str(o.get("position", ""))
            target = str(o.get("target_course_code", ""))
            if pos in ("before", "after") and target:
                ord_relations.add((s.course_code, pos, target))

    by_group_course_t: dict[tuple[str, str], list[int]] = defaultdict(list)
    for sid, s in sessions_by_id.items():
        if sid not in t_of:
            continue
        for gid in s.group_ids:
            by_group_course_t[(s.course_code, gid)].append(t_of[sid])

    ord_viol = 0
    ord_total = 0
    for code, pos, target in ord_relations:
        groups_a = {g for (c, g) in by_group_course_t if c == code}
        groups_b = {g for (c, g) in by_group_course_t if c == target}
        for gid in groups_a & groups_b:
            ta = by_group_course_t[(code, gid)]
            tb = by_group_course_t[(target, gid)]
            mean_a = sum(ta) / len(ta)
            mean_b = sum(tb) / len(tb)
            ord_total += 1
            ok = mean_a < mean_b if pos == "before" else mean_a > mean_b
            if not ok:
                ord_viol += 1
    if ord_total:
        tiered_run = tier_values is not None and "ordonnancement" in tier_values
        if ord_viol == 0:
            status, detail = "pass", f"0/{ord_total} relations non respectées."
        elif tiered_run:
            status = "fail"
            detail = (
                f"{ord_viol}/{ord_total} relations non respectées — mode paliers : "
                "c'est le vrai minimum atteint et verrouillé (palier 1), pas un "
                "compromis pondéré. Anomalie réelle à examiner."
            )
        else:
            status = "info"
            detail = (
                f"{ord_viol}/{ord_total} relations non respectées — mode somme "
                "pondérée (ou mode inconnu) : molle par défaut (poids 400), pas "
                "une garantie ; passer en mode paliers (`solve_tiered`) pour un "
                "vrai minimum."
            )
        checks.append(
            {
                "id": "ordonnancement",
                "label": "Ordonnancement inter-matières (before/after)",
                "status": status,
                "detail": detail,
            }
        )

        # -- Critère STRICT : « A entièrement fini avant que B commence » --
        # Le critère "moyenne" ci-dessus se satisfait d'un simple décalage des
        # barycentres : sur le run `odd26` il était à 13/89 alors que le
        # critère strict, lui, était à 89/89 (aucun module n'était réellement
        # terminé avant le démarrage du suivant — retour utilisateur du
        # 25/08/2026 : « des matières qui devaient être finies pour
        # commencer »). Rapporté séparément, en semaines de chevauchement,
        # parce que c'est une pénalité MOLLE et graduée côté solveur
        # (`assign_weeks::strict_ordonnancement_weight`) : le chiffre à
        # surveiller est l'ampleur du chevauchement, pas seulement son
        # existence.
        slots_per_week_local = slots_per_week
        strict_viol: list[tuple[str, str, str, int]] = []
        strict_total = 0
        for code, pos, target in sorted(ord_relations):
            groups_a = {g for (c, g) in by_group_course_t if c == code}
            groups_b = {g for (c, g) in by_group_course_t if c == target}
            for gid in sorted(groups_a & groups_b):
                ta = by_group_course_t[(code, gid)]
                tb = by_group_course_t[(target, gid)]
                first, last = (tb, ta) if pos == "before" else (ta, tb)
                strict_total += 1
                overlap_slots = max(last) - min(first) + 1
                if overlap_slots > 0:
                    strict_viol.append((code, pos, target, overlap_slots // slots_per_week_local + 1))
        if strict_total:
            worst = max((v[3] for v in strict_viol), default=0)
            mean_overlap = round(sum(v[3] for v in strict_viol) / len(strict_viol), 1) if strict_viol else 0
            checks.append(
                {
                    "id": "ordonnancement_strict",
                    "label": "Module terminé avant le démarrage du suivant (critère strict)",
                    "status": "pass" if not strict_viol else "info",
                    "detail": (
                        f"0/{strict_total} couple(s) en chevauchement."
                        if not strict_viol
                        else (
                            f"{len(strict_viol)}/{strict_total} couple(s) (matière, groupe) en "
                            f"chevauchement — {mean_overlap} semaine(s) en moyenne, {worst} au pire. "
                            "Objectif MOU gradué : une séparation totale de deux modules étalés sur "
                            "tout le semestre n'est pas toujours physiquement possible, le chiffre "
                            "à faire baisser est l'ampleur du chevauchement."
                        )
                    ),
                }
            )

    # -- Regroupement mensuel des interventions (ARA, JHU) --
    # Règle demandée par les enseignants eux-mêmes (contrainte géographique) et
    # jamais vérifiée jusqu'au 26/08/2026 : sur le run `odd26`, ARA intervenait
    # 15 semaines distinctes et JHU 14, pour une demande de 1 à 2 semaines par
    # mois. Objectif MOU côté solveur, donc « info » et non « fail » — mais le
    # chiffre doit être visible.
    if teacher_availability and calendar is not None:
        vises = {
            a.teacher_code: a.monthly_cluster_max_weeks
            for a in teacher_availability
            if a.monthly_cluster_max_weeks
        }
        if vises:
            semaines_par_prof: dict[str, set[int]] = defaultdict(set)
            for p_row in placements:
                for code in p_row["teacher_codes"]:
                    if code in vises:
                        semaines_par_prof[code].add(p_row["week"])
            # Nombre de mois civils couverts par l'horizon : le maximum demandé
            # est mensuel, il faut donc le multiplier pour obtenir la cible.
            mois = {
                (m.year, m.month)
                for m in calendar.teaching_mondays[week_offset : week_offset + 24]
            }
            lignes = []
            depassements = 0
            for code, maxi in sorted(vises.items()):
                utilisees = len(semaines_par_prof.get(code, set()))
                cible = maxi * max(1, len(mois))
                lignes.append(f"{code} : {utilisees} semaine(s) pour ~{cible} visée(s)")
                if utilisees > cible:
                    depassements += 1
            checks.append({
                "id": "teacher_monthly_clustering",
                "label": "Regroupement mensuel des interventions (1 à 2 semaines/mois)",
                "status": "pass" if not depassements else "info",
                "detail": " ; ".join(lignes),
            })

    # -- Ordre entre enseignants d'un même module (WRA505C : ALO puis AFR) --
    from cal_iut.ingestion.config_loader import load_course_teacher_orders

    order_rules = load_course_teacher_orders(Path(__file__).resolve().parents[3] / "data" / "config")
    if order_rules:
        semaines: dict[tuple[str, str], list[int]] = defaultdict(list)
        for p_row in placements:
            sess = sessions_by_id.get(p_row["session_id"])
            if sess is None:
                continue
            for code in p_row["teacher_codes"]:
                semaines[(sess.course_code, code)].append(p_row["week"])
        anomalies, verifies = [], 0
        for rule in order_rules:
            for avant, apres in zip(rule.teacher_order, rule.teacher_order[1:]):
                a = semaines.get((rule.course_code, avant), [])
                b = semaines.get((rule.course_code, apres), [])
                if not a or not b:
                    continue
                verifies += 1
                moy_a, moy_b = sum(a) / len(a), sum(b) / len(b)
                if moy_a >= moy_b:
                    anomalies.append(
                        f"{rule.course_code} : {avant} (semaine moy. {moy_a:.1f}) devrait "
                        f"précéder {apres} ({moy_b:.1f})"
                    )
        if verifies:
            checks.append({
                "id": "course_teacher_order",
                "label": "Ordre entre enseignants d'un module (ex. WRA505C : ALO puis AFR)",
                "status": "pass" if not anomalies else "info",
                "detail": (
                    f"{verifies} relation(s) vérifiée(s), toutes respectées."
                    if not anomalies
                    else " ; ".join(anomalies)
                ),
            })

    # -- Alternants : aucun cours hors semaine de présence IUT --
    # Contrainte DURE côté solveur, jamais vérifiée sur le résultat : une séance
    # FC placée une semaine où les étudiants sont en entreprise est un défaut
    # invisible jusqu'à ce qu'ils ne viennent pas.
    if calendar is not None:
        from cal_iut.ingestion.constraints_loader import load_alternance_presence_json

        presences = load_alternance_presence_json(
            Path(__file__).resolve().parents[3]
            / "contraintes"
            / "03_calendrier_alternance_officiel.json"
        )
        jours_presence: dict[str, set[tuple[int, int]]] = {}
        for presence in presences:
            if not presence.presence_dates:
                continue
            jours = allowed_week_days_for_parcours(presence, calendar, week_offset, 30)
            for key in presence.parcours_keys:
                jours_presence[key] = jours
        hors_presence = []
        verifies_fc = 0
        for p_row in placements:
            sess = sessions_by_id.get(p_row["session_id"])
            if sess is None or "FC" not in sess.parcours:
                continue
            jours = jours_presence.get(sess.parcours)
            if jours is None:
                continue
            verifies_fc += 1
            if (p_row["week"], p_row["day"]) not in jours:
                hors_presence.append(p_row["session_id"])
        if verifies_fc:
            checks.append({
                "id": "alternance_presence",
                "label": "Cours des alternants uniquement les semaines de présence IUT",
                "status": "pass" if not hors_presence else "fail",
                "detail": (
                    f"{verifies_fc} séance(s) FC, toutes une semaine de présence."
                    if not hors_presence
                    else f"{len(hors_presence)}/{verifies_fc} séance(s) FC placées alors que les "
                    f"étudiants sont en entreprise (ex. {hors_presence[0]})."
                ),
            })

    # -- Indisponibilités enseignant réellement respectées --
    # Contrainte DURE côté solveur, mais son verdict n'existait que dans
    # l'onglet Enseignant (une ligne par enseignant) — jamais en synthèse. Un
    # tableau de bord qui n'affiche pas le total d'une règle dure laisse ses
    # violations passer inaperçues.
    if teacher_availability and calendar is not None:
        violations: list[str] = []
        verifiees = 0
        for avail in teacher_availability:
            interdits = {tuple(x) for x in (avail.forbidden_slots or [])}
            autorises = {tuple(x) for x in (avail.allowed_slots or [])}
            dates_interdites = set((avail.metadata or {}).get("forbidden_dates") or [])
            dates_autorisees = set(avail.allowed_dates or [])
            if not (interdits or autorises or dates_interdites or dates_autorisees):
                continue
            for p_row in placements:
                if avail.teacher_code not in p_row["teacher_codes"]:
                    continue
                verifiees += 1
                jour, creneau = p_row["day"], p_row["slot"]
                quand = calendar.week_day_to_date(week_offset + p_row["week"], jour)
                iso = quand.isoformat() if quand else ""
                # Une date bloquée UNIQUEMENT parce que l'enseignant encadre une
                # SAE ce jour-là est une préférence en mode mou, pas un interdit :
                # elle a son propre indicateur (`sae_supervisor`), on ne la
                # compte pas ici.
                supervision = set(
                    (sae_supervisor_dates or {}).get(avail.teacher_code, set())
                )
                sae_ce_jour = quand is not None and quand in supervision
                if (jour, creneau) in interdits:
                    violations.append(f"{avail.teacher_code} le {iso} créneau {creneau}")
                elif autorises and (jour, creneau) not in autorises:
                    violations.append(f"{avail.teacher_code} hors liste blanche, {iso}")
                elif iso in dates_interdites and not sae_ce_jour:
                    violations.append(f"{avail.teacher_code} le {iso} (date déclarée)")
                elif dates_autorisees and iso not in dates_autorisees:
                    violations.append(f"{avail.teacher_code} hors dates de venue, {iso}")
        if verifiees:
            checks.append({
                "id": "teacher_availability",
                "label": "Indisponibilités et listes blanches enseignant respectées",
                "status": "pass" if not violations else "fail",
                "detail": (
                    f"{verifiees} séance(s) vérifiée(s), aucune sur un créneau interdit."
                    if not violations
                    else f"{len(violations)}/{verifiees} séance(s) sur un créneau interdit "
                    f"(ex. {violations[0]})."
                ),
            })

    # -- Une salle n'accueille jamais deux cours en même temps --
    # Règle si évidente qu'elle n'avait AUCUN contrôle : le tableau de bord
    # vérifiait la CAPACITÉ des salles, jamais leur OCCUPATION. Un bug réel a
    # survécu à cause de cette absence — la branche « salle de duo » de
    # `rooms.py` prenait sa salle sans regarder si elle était libre, et le run
    # `odd26` envoyait 4 fois deux groupes dans la même pièce (H.007, H.008,
    # H.201, H.203). Corrigé le 26/08/2026, trouvé par exploration.
    if rooms:
        occupation: dict[tuple[str, int], str] = {}
        collisions: list[str] = []
        for p_row in placements:
            salle = p_row.get("room_id")
            if not salle:
                continue
            sess = sessions_by_id.get(p_row["session_id"])
            duree = max(1, getattr(sess, "duration_slots", 1))
            base = t_of.get(p_row["session_id"])
            if base is None:
                continue
            for t in range(base, base + duree):
                cle = (salle, t)
                autre = occupation.get(cle)
                if autre is not None:
                    collisions.append(
                        f"{p_row.get('room_label') or salle} : {p_row['session_id']} et {autre}"
                    )
                else:
                    occupation[cle] = p_row["session_id"]
        avec_salle = sum(1 for p_row in placements if p_row.get("room_id"))
        if avec_salle:
            checks.append({
                "id": "room_double_booking",
                "label": "Une salle n'accueille jamais deux cours en même temps",
                "status": "pass" if not collisions else "fail",
                "detail": (
                    f"{avec_salle} séance(s) avec salle, aucune collision."
                    if not collisions
                    else f"{len(collisions)} collision(s) de salle : "
                    + " ; ".join(collisions[:3])
                ),
            })

    # -- Duos synchronisés sur une salle rare --
    from cal_iut.ingestion.config_loader import load_teacher_duos
    from cal_iut.solver.constraints import duo_episode_pairs

    duos = load_teacher_duos(Path(__file__).resolve().parents[3] / "data" / "config")
    if duos:
        paires = duo_episode_pairs(list(sessions_by_id.values()), duos)
        desynchronisees = [
            (a, b)
            for a, b in paires
            if a in t_of and b in t_of and t_of[a] != t_of[b]
        ]
        verifiables = [(a, b) for a, b in paires if a in t_of and b in t_of]
        if verifiables:
            checks.append({
                "id": "duo_rare_room",
                "label": "Duos co-animés au même créneau (salle rare dédoublée)",
                "status": "pass" if not desynchronisees else "fail",
                "detail": (
                    f"{len(verifiables)} épisode(s) de duo, tous synchronisés."
                    if not desynchronisees
                    else f"{len(desynchronisees)}/{len(verifiables)} épisode(s) désynchronisés "
                    f"(ex. {desynchronisees[0][0]} vs {desynchronisees[0][1]})."
                ),
            })

    # -- Blocs de 3h / 4h30 restés d'un seul tenant --
    blocs = [s for s in sessions_by_id.values() if s.duration_slots > 1 and s.id in t_of]
    if blocs:
        # Un bloc ne doit jamais déborder sur le jour suivant : il démarre donc
        # au plus tard au créneau `6 - durée`.
        deborde = [
            s.id for s in blocs
            if (t_of[s.id] % SLOTS_PER_DAY_LOCAL) + s.duration_slots > SLOTS_PER_DAY_LOCAL
        ]
        checks.append({
            "id": "double_sessions",
            "label": "Blocs de 3h / 4h30 d'un seul tenant dans la journée",
            "status": "pass" if not deborde else "fail",
            "detail": (
                f"{len(blocs)} bloc(s) long(s), tous entiers dans leur journée."
                if not deborde
                else f"{len(deborde)}/{len(blocs)} bloc(s) débordent sur le jour suivant "
                f"(ex. {deborde[0]})."
            ),
        })

    return checks


def _room_catalog(rooms: list[Room], rows: list[dict]) -> list[dict]:
    usage = defaultdict(int)
    for r in rows:
        if r["r"]:
            usage[r["r"]] += 1
    catalog = []
    for room in rooms:
        catalog.append(
            {
                "id": room.id,
                "label": room.label,
                "capacity": room.capacity,
                "type": room.room_type.value,
                "equipment": list(room.equipment),
                "nSessions": usage.get(room.label, 0),
            }
        )
    catalog.sort(key=lambda r: r["label"])
    return catalog


def _course_catalog(sessions: list[SessionToPlace], rows: list[dict]) -> list[dict]:
    by_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        by_course[(s.course_code, s.semestre, s.parcours)].append(s)

    placed_count: dict[str, int] = defaultdict(int)
    for r in rows:
        placed_count[r["c"]] += 1

    catalog = []
    for (code, semestre, parcours), sess_list in by_course.items():
        # Pondéré par `duration_slots` (pas 1 par séance) : un bloc "double"
        # (ex. TP collé en 3h = 2×1h30, cf. docs/DATA.md §15.2) doit continuer
        # à compter pour 2 séances dans la progression, comme avant sa fusion
        # à l'ingestion — sinon le nombre affiché sous-estime le volume réel
        # (retour utilisateur : "on décompte 2 séance de tp dans la
        # progression").
        by_type_count: dict[str, int] = defaultdict(int)
        seen_ids: set[str] = set()
        teachers: set[str] = set()
        for s in sess_list:
            teachers.update(s.teacher_codes)
            if s.id in seen_ids:
                continue
            seen_ids.add(s.id)
            by_type_count[s.session_type.value] += max(1, s.duration_slots)
        n_eval = sum(1 for s in sess_list if s.is_eval)
        ordonnancement = []
        for s in sess_list:
            for o in s.metadata.get("ordonnancement") or []:
                entry = (str(o.get("position", "")), str(o.get("target_course_code", "")))
                if entry not in ordonnancement:
                    ordonnancement.append(entry)
        catalog.append(
            {
                "code": code,
                "name": sess_list[0].course_name,
                "semestre": semestre,
                "parcours": parcours,
                "nCM": by_type_count.get("CM", 0),
                "nTD": by_type_count.get("TD", 0),
                "nTP": by_type_count.get("TP", 0),
                "nEval": n_eval,
                "progressionDefined": any(s.sequence_order is not None for s in sess_list),
                "teachers": sorted(teachers),
                "ordonnancement": [{"position": p, "target": t} for p, t in ordonnancement],
                "nPlaced": placed_count.get(code, 0),
            }
        )
    catalog.sort(key=lambda c: c["code"])
    return catalog


def _sae_rows(
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None,
    sessions: list[SessionToPlace],
) -> list[dict[str, object]]:
    """
    Jours SAE (semaine, jour) par parcours, pour affichage — les séances SAE
    elles-mêmes ne sont plus planifiées par l'algorithme (retour utilisateur,
    cf. docs/DATA.md §15.1), donc absentes de `payload.rows` ; seules leurs
    dates calendaires réelles servent ici à informer l'utilisateur que la
    journée est réservée au projet, pas vide.
    """
    if not sae_days_by_course:
        return []

    # code -> (nom, {parcours...}) déduit de n'importe quelle séance WS de ce
    # code (même non planifiée, `sessions` contient toujours la liste complète
    # issue de l'ingestion).
    info_by_code: dict[str, tuple[str, set[str]]] = {}
    for s in sessions:
        if s.course_code not in sae_days_by_course:
            continue
        name, parcours_set = info_by_code.get(s.course_code, (s.course_name, set()))
        parcours_set.add(s.parcours)
        info_by_code[s.course_code] = (name, parcours_set)

    by_key: dict[tuple[int, int, str], set[str]] = defaultdict(set)
    for code, days in sae_days_by_course.items():
        _, parcours_set = info_by_code.get(code, (code, set()))
        for parcours in parcours_set:
            for week, day in days:
                by_key[(week, day, parcours)].add(code)

    return [
        {"w": week, "d": day, "p": parcours, "codes": sorted(codes)}
        for (week, day, parcours), codes in sorted(by_key.items())
    ]


def _holiday_rows(calendar: AcademicCalendar | None, week_offset: int, weeks: int) -> list[dict[str, object]]:
    """
    Jours fériés / pauses pédagogiques (`INSTITUTIONAL_EVENTS`, kind ferie ou
    vacances), localisés (semaine, jour) dans la grille — retour utilisateur :
    "affiche aussi dans l'interface les jours fériés". Utilise `date_to_week_
    day_any` (pas `date_to_week_day`) car ces dates sont par définition NON
    enseignables : la version normale renverrait toujours `None` pour elles.
    """
    if calendar is None or weeks <= 0:
        return []
    rows: list[dict[str, object]] = []
    for ev in INSTITUTIONAL_EVENTS:
        if ev["kind"] not in ("ferie", "vacances"):
            continue
        start = date.fromisoformat(str(ev["start"]))
        end = date.fromisoformat(str(ev["end"]))
        d = start
        while d <= end:
            mapped = calendar.date_to_week_day_any(d)
            if mapped is not None:
                abs_week, day = mapped
                rel = abs_week - week_offset
                if 0 <= rel < weeks:
                    rows.append({"w": rel, "d": day, "kind": ev["kind"], "label": ev["label"]})
            d += timedelta(days=1)
    return rows


def build_payload(
    timetable: dict[str, object],
    sessions: list[SessionToPlace],
    groups: list[Group],
    *,
    calendar: AcademicCalendar | None = None,
    semestre: str | None = None,
    default_group: str | None = None,
    teacher_availability: list[TeacherAvailability] | None = None,
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None = None,
    rooms: list[Room] | None = None,
    planning_events: list[dict[str, object]] | None = None,
    planning_event_slots: list[dict[str, object]] | None = None,
    exceptions: list[dict[str, object]] | None = None,
    teacher_contacts: dict[str, str] | None = None,
    sae_supervisor_dates: dict[str, set] | None = None,
) -> dict[str, object]:
    """Construit le payload JSON embarqué dans la page HTML."""
    sessions_by_id = {s.id: s for s in sessions}
    placements = timetable.get("placements", [])

    relevant_parcours = {sessions_by_id[p["session_id"]].parcours for p in placements if p["session_id"] in sessions_by_id}
    scoped_groups = [g for g in groups if g.parcours in relevant_parcours] or groups

    # Ne pas proposer dans l'interface un groupe qui n'a AUCUNE séance : les
    # cohortes à groupe unique (BUT2-CREACOM-FC, BUT3-CREACOM-FC,
    # BUT3-DEV-FC) déclarent un groupe TP qui reste nécessaire côté solveur
    # (il porte la définition de la cohorte pour le plafond hebdomadaire),
    # mais dont toutes les séances sont émises en TD sur le groupe TD —
    # l'afficher ferait apparaître deux entrées pour les mêmes étudiants,
    # dont une systématiquement vide.
    groups_with_sessions = {gid for p in placements for gid in p["group_ids"]}
    visible_groups = [g for g in scoped_groups if g.kind == "promo" or g.id in groups_with_sessions]
    if visible_groups:
        scoped_groups = visible_groups

    labels, kinds, cohorts, tp_pairs, is_fc = _group_maps(scoped_groups)

    # Libellé de salle relu depuis la CONFIG COURANTE (`rooms.yaml`) plutôt
    # que depuis celui figé dans le placement au moment de l'affectation —
    # sinon renommer une salle dans la config n'a aucun effet tant qu'on n'a
    # pas relancé une affectation complète (trouvé le 28/08/2026 en retirant
    # le suffixe « (Évaluation) » du libellé d'A.018 : la config était à
    # jour, l'écran affichait toujours l'ancien libellé stocké). Repli sur le
    # libellé stocké si la salle a disparu de la config entre-temps.
    room_labels_by_id = {r.id: r.label for r in (rooms or [])}

    rows = []
    for p in placements:
        session = sessions_by_id.get(p["session_id"])
        if session is None:
            continue
        rows.append(
            {
                "id": p["session_id"],
                "w": p["week"],
                "d": p["day"],
                "s": p["slot"],
                "c": p["course_code"],
                "n": session.course_name,
                "t": session.session_type.value,
                "g": p["group_ids"],
                "te": p["teacher_codes"],
                "r": room_labels_by_id.get(p.get("room_id") or "") or p.get("room_label") or "",
                "ev": bool(session.is_eval),
                "dur": max(1, session.duration_slots),
                "locked": bool(session.locked),
                # Séance ajoutée depuis l'interface (`api/custom_sessions.py`,
                # retour utilisateur 31/08/2026) — distincte d'une séance de
                # la maquette : c'est CE drapeau qui autorise le bouton
                # modifier/supprimer en Vue Promo, jamais affiché sur une
                # séance de la maquette.
                "custom": bool(session.metadata.get("custom_session")),
            }
        )

    n_weeks = (max((r["w"] for r in rows), default=-1)) + 1

    week_labels: list[str] = []
    week_rows: list[dict[str, object]] = []
    week_status_rows: list[dict[str, object]] = []
    week_offset = 0
    if calendar is not None and semestre is not None:
        week_offset = semester_week_offset(calendar, semestre)
        for i in range(n_weeks):
            label = calendar.department_week_label(week_offset + i)
            week_labels.append(label or f"Semaine {i + 1}")
        # Séquence continue (y compris semaines bloquées/vacances) pour que
        # l'interface les affiche au lieu de sauter silencieusement dessus.
        week_rows = calendar.full_week_range(week_offset, n_weeks)
        # Semaine passée/en cours/future (retour utilisateur : pas d'édition
        # manuelle possible sur une semaine déjà vécue) — même calcul que
        # côté API (`week_status`), exposé ici pour le rendu initial sans
        # aller-retour réseau.
        week_status_rows = [
            {"week": i, "status": week_status(calendar, semestre, i)} for i in range(n_weeks)
        ]

    # Date ISO du lundi de chaque semaine-solveur — indispensable pour produire
    # un vrai fichier .ics par enseignant (un événement daté, pas un "semaine
    # 7"). Reconstruite depuis `week_rows`, qui contient déjà la correspondance
    # index solveur -> lundi réel, plutôt qu'en la recalculant à part.
    week_dates: list[str] = [""] * n_weeks
    for row in week_rows:
        idx = row.get("weekIndex")
        if isinstance(idx, int) and 0 <= idx < n_weeks:
            week_dates[idx] = str(row.get("monday") or "")

    default_gid = default_group
    if default_gid is None:
        tp_first = next((g.id for g in scoped_groups if g.kind == "tp"), None)
        default_gid = tp_first or (scoped_groups[0].id if scoped_groups else None)

    teacher_names = _teacher_names(sessions)
    teachers_payload = (
        _teacher_payload(
            teacher_availability, sessions_by_id, placements, teacher_names, calendar, week_offset,
            sae_supervisor_dates,
        )
        if teacher_availability
        else []
    )
    # Toujours exposer un libellé pour chaque code enseignant vu dans les séances,
    # même sans contrainte déclarée (utile pour la vue Enseignant).
    all_teacher_codes = sorted({code for p in placements for code in p["teacher_codes"]})
    teacher_labels = {code: teacher_names.get(code, code) for code in all_teacher_codes}

    rule_checks = _rule_checks(
        sessions_by_id,
        placements,
        scoped_groups,
        cohorts,
        kinds,
        is_fc,
        sae_days_by_course,
        rooms,
        timetable.get("tier_values") if isinstance(timetable.get("tier_values"), dict) else None,
        calendar,
        week_offset,
        teacher_availability,
        sae_supervisor_dates,
    )
    group_parcours = {g.id: g.parcours for g in scoped_groups}
    sae_rows = _sae_rows(sae_days_by_course, sessions)
    holiday_rows = _holiday_rows(calendar, week_offset, n_weeks)
    event_rows = [e for e in (planning_events or []) if 0 <= int(e.get("w", -1)) < n_weeks]
    event_slot_rows = [e for e in (planning_event_slots or []) if 0 <= int(e.get("w", -1)) < n_weeks]

    # Séances absentes du planning. Calculées ICI, par différence, plutôt que
    # laissées implicites : sans cette liste, une séance non placée
    # disparaissait de toutes les vues et de tous les compteurs — le planning
    # avait l'air complet alors qu'il manquait des heures d'enseignement
    # (cf. docs/DATA.md §66). Le pire des trois états possibles : pire qu'un
    # échec visible, et pire qu'un placement imparfait.
    placees = {p["session_id"] for p in placements}
    # Exclut les SAE non planifiées par le solveur (préfixe "WS", sauf celles
    # de `solver_scheduled_sae`, ex. WSA501D) — MÊME filtre que l'audit
    # (`resultat.seances_non_placees`, la référence de confiance de cette
    # nuit) et `score_run`. Bug réel trouvé le 27/08/2026 (retour
    # utilisateur : « j'ai 1121 à placer pas 426 ») : cette liste-ci, comme
    # `/placements/manquantes` côté API, comptait encore les 695 séances SAE
    # dont la semaine vient du calendrier réel, jamais du solveur — jamais
    # censées être placées à la main, et donc jamais des « manquantes » au
    # sens où l'audit (et l'utilisateur) l'entendent.
    scheduled_sae = _solver_scheduled_sae()
    non_placees = [
        {
            "id": s.id,
            "code": s.course_code,
            "nom": s.course_name,
            "type": str(getattr(s.session_type, "value", s.session_type)),
            "parcours": s.parcours,
            "groupes": [labels.get(g, g) for g in (s.group_ids or [])],
            "profs": [teacher_labels.get(c, c) for c in (s.teacher_codes or [])],
        }
        for s in sessions
        if s.id not in placees
        and s.parcours in relevant_parcours
        and (not s.course_code.upper().startswith("WS") or (s.course_code.upper(), s.semestre) in scheduled_sae)
    ]
    non_placees.sort(key=lambda m: (m["parcours"], m["code"]))

    return {
        "status": timetable.get("status"),
        "seancesNonPlacees": non_placees,
        "objective": timetable.get("objective_value"),
        "quality": timetable.get("quality"),
        "groupLabels": labels,
        "groupKind": kinds,
        "groupCohort": cohorts,
        "groupTpPair": tp_pairs,
        "groupIsFc": is_fc,
        "groupParcours": group_parcours,
        "weekLabels": week_labels,
        "weekDates": week_dates,
        "weekRows": week_rows,
        "weekStatus": week_status_rows,
        "defaultGroup": default_gid,
        "rows": rows,
        "saeRows": sae_rows,
        "holidayRows": holiday_rows,
        "eventRows": event_rows,
        "eventSlotRows": event_slot_rows,
        "exceptions": exceptions or [],
        "teachers": teachers_payload,
        "teacherLabels": teacher_labels,
        # Adresses mail saisies à la main (cf. `teacher_contacts.yaml`) : aucun
        # fichier source officiel ne les porte. Vide = le brouillon s'ouvre sans
        # destinataire, à compléter.
        "teacherEmails": teacher_contacts or {},
        # Paramètre `t` des liens personnels — PUBLIC depuis le 28/08/2026
        # (`api/auth.py::verify_personal_link_param` : sa seule présence
        # suffit, plus de jeton signé). Gardé au format `code` simple ici
        # (plutôt que de construire l'URL entièrement côté client à partir
        # du seul `code`) pour que `buildLink({..., t: payload.
        # teacherTokens[code]})` reste inchangé côté front — un dict qui
        # associe trivialement chaque code à lui-même, mais garde la même
        # forme qu'avant (facilite un retour à un vrai jeton signé plus tard
        # si besoin, sans retoucher le front).
        "teacherTokens": {code: code for code in teacher_labels},
        # Même chose pour le lien personnel d'un GROUPE d'étudiants
        # (`GroupeView.tsx`) — n'existait pas du tout jusqu'ici (la demande
        # initiale ne portait explicitement que sur les profs), bug réel
        # trouvé le 28/08/2026 : un lien de groupe ouvert en navigation
        # privée tombait sur "Aucun planning résolu" faute de TOUT paramètre
        # `t` pour ce type de lien (ça "marchait" en navigation normale
        # seulement parce qu'une session admin traînait déjà en cookie,
        # masquant le trou).
        "groupTokens": {gid: gid for gid in labels},
        "ruleChecks": rule_checks,
        "institutionalCalendar": INSTITUTIONAL_EVENTS,
        "rooms": _room_catalog(rooms, rows) if rooms else [],
        "courses": _course_catalog(sessions, rows),
    }


def render_html(
    payload: dict[str, object],
    *,
    title: str = "Planning généré — cal-iut",
    heading: str = "Planning généré",
    subheading: str = "Sortie du solveur CP-SAT cal-iut.",
    footer: str = (
        "Généré par <span class=\"mono\">cal-iut export --format html</span> "
        "(OR-Tools CP-SAT) à partir des exports maquette/progression MMI et du "
        "calendrier académique. Les vérifications sont recalculées côté serveur "
        "à partir de la sortie brute du solveur, pas de valeurs pré-écrites."
    ),
) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload_json = json.dumps(payload, ensure_ascii=False)
    if "</script" in payload_json.lower():
        payload_json = payload_json.replace("</script", "<\\/script")

    return (
        template.replace("__TITLE__", title)
        .replace("__HEADING__", heading)
        .replace("__SUBHEADING__", subheading)
        .replace("__FOOTER__", footer)
        .replace("__PAYLOAD__", payload_json)
    )


def build_and_render(
    timetable: dict[str, object],
    sessions: list[SessionToPlace],
    groups: list[Group],
    *,
    calendar: AcademicCalendar | None = None,
    semestre: str | None = None,
    teacher_availability: list[TeacherAvailability] | None = None,
    sae_days_by_course: dict[str, set[tuple[int, int]]] | None = None,
    rooms: list[Room] | None = None,
    planning_events: list[dict[str, object]] | None = None,
    planning_event_slots: list[dict[str, object]] | None = None,
    exceptions: list[dict[str, object]] | None = None,
    teacher_contacts: dict[str, str] | None = None,
    sae_supervisor_dates: dict[str, set] | None = None,
    **render_kwargs: object,
) -> str:
    calendar = calendar or build_default_calendar_2026_2027()
    if sae_supervisor_dates is None and teacher_availability:
        # Auto-chargé si non fourni (même donnée que le solveur/l'API,
        # jamais réestimée) — sinon `export --format html` distinguait moins
        # bien les compromis SAE mous que `/app-state` (cf. docs/DATA.md §59).
        from cal_iut.ingestion.planning_loader import (
            load_mmi_planning_for_semestres,
            sae_supervisor_dates_by_teacher,
        )

        real_semestres = sorted({s.semestre for s in sessions}) or ([semestre] if semestre else [])
        planning = load_mmi_planning_for_semestres(Path(__file__).resolve().parents[3], real_semestres)
        sae_supervisor_dates = sae_supervisor_dates_by_teacher(planning)
    payload = build_payload(
        timetable,
        sessions,
        groups,
        calendar=calendar,
        semestre=semestre,
        teacher_availability=teacher_availability,
        sae_days_by_course=sae_days_by_course,
        rooms=rooms,
        planning_events=planning_events,
        planning_event_slots=planning_event_slots,
        exceptions=exceptions,
        teacher_contacts=teacher_contacts,
        sae_supervisor_dates=sae_supervisor_dates,
    )
    return render_html(payload, **render_kwargs)  # type: ignore[arg-type]
