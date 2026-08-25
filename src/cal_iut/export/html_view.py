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
from pathlib import Path

from cal_iut.calendar.academic import (
    AcademicCalendar,
    build_default_calendar_2026_2027,
    semester_week_offset,
    week_status,
)
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
    {"label": "VSS (S1) — Amphi GMP/GEII 9h30-11h", "start": "2026-09-17", "end": "2026-09-17", "kind": "special"},
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
) -> list[dict]:
    checks: list[dict] = []

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
        cap = 23 if is_fc.get(gid) else 22
        mx = max(weekly.values()) if weekly else 0
        if mx > cap:
            over_cap.append((gid, mx, cap))
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
            if s is None or s.course_code.upper().startswith("WS"):
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

    seq_violations = 0
    seq_checked = 0
    for key, sess_list in by_group_course.items():
        ordered = sorted(sess_list, key=lambda s: s.sequence_order or 0)
        for a, b in zip(ordered, ordered[1:]):
            if (a.sequence_order or 0) == (b.sequence_order or 0):
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
                "r": p.get("room_label") or "",
                "ev": bool(session.is_eval),
                "dur": max(1, session.duration_slots),
                "locked": bool(session.locked),
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
    )
    group_parcours = {g.id: g.parcours for g in scoped_groups}
    sae_rows = _sae_rows(sae_days_by_course, sessions)
    holiday_rows = _holiday_rows(calendar, week_offset, n_weeks)
    event_rows = [e for e in (planning_events or []) if 0 <= int(e.get("w", -1)) < n_weeks]
    event_slot_rows = [e for e in (planning_event_slots or []) if 0 <= int(e.get("w", -1)) < n_weeks]

    return {
        "status": timetable.get("status"),
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
