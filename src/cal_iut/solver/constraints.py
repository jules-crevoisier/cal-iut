"""Contraintes dures : ordonnancement, progression, dispos, calendrier."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import AcademicCalendar
from cal_iut.ingestion.constraints_loader import StudentPresence, allowed_week_days_for_parcours
from cal_iut.models.entities import CourseMinWeekRule, Group, OrdonnancementPosition, TeacherAvailability, TeacherDuo
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY, TimeSlot, WeekDay


def _sessions_by_course(sessions: list[SessionToPlace]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for session in sessions:
        key = f"{session.course_code}:{session.semestre}:{session.parcours}"
        index.setdefault(key, []).append(session.id)
    return index


def _group_session_ids(
    session_ids: list[str],
    session_index: dict[str, SessionToPlace],
) -> dict[str, list[str]]:
    by_group: dict[str, list[str]] = defaultdict(list)
    for sid in session_ids:
        for gid in session_index[sid].group_ids:
            by_group[gid].append(sid)
    return by_group


def add_ordonnancement_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    horizon: int,
    *,
    soft: bool = False,
    weight: int = 80,
    strict_mean: bool = True,
) -> list[cp_model.IntVar]:
    """
    Before / after / same entre matières, évalué **par groupe étudiant réel**
    (le même groupe brut, ex. but1-tp-a, doit voir la source avant/après la cible),
    et non sur l'ensemble de la matière tous groupes confondus.

    La version "toute la matière" (max(source) < min(target) sur TOUTES les
    séances, tous groupes) est presque toujours violée dès que le cours est
    étalé sur le semestre (objectif spread) : il suffit qu'un seul groupe finisse
    tard pour bloquer tous les autres. Par groupe, la contrainte reste fidèle à
    l'intention pédagogique ("ce groupe doit finir A avant de commencer B") tout
    en restant satisfiable.

    En soft=True (cohortes étudiantes) : comparaison de la position MOYENNE
    (produit croisé, pas de division) plutôt que max/min stricts. Deux modes :
    - `strict_mean=True` (par défaut) : contrainte DURE — l'ordonnancement est
      jugé pédagogiquement essentiel (retour utilisateur explicite), on
      accepte un temps de calcul plus long plutôt qu'une violation silencieuse.
    - `strict_mean=False` : pénalité molle (poids `weight`), utile en secours
      si la version dure s'avère infaisable sur un jeu de données donné.
    """
    by_course = _sessions_by_course(sessions)
    session_index = {s.id: s for s in sessions}
    seen_pairs: set[tuple[str, str, str]] = set()
    penalties: list[cp_model.IntVar] = []

    for session in sessions:
        ordonnancement = session.metadata.get("ordonnancement") or []
        for raw in ordonnancement:
            position = str(raw.get("position", ""))
            target_code = str(raw.get("target_course_code", ""))
            semestre = str(raw.get("semestre", session.semestre))
            if not target_code:
                continue

            source_key = f"{session.course_code}:{semestre}:{session.parcours}"
            target_key = f"{target_code}:{semestre}:{session.parcours}"
            pair_key = (position, source_key, target_key)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            source_ids = by_course.get(source_key, [])
            target_ids = by_course.get(target_key, [])
            if not source_ids or not target_ids:
                continue

            if position == OrdonnancementPosition.SAME.value:
                if soft:
                    penalties.extend(
                        _soft_link_same_course_sessions(
                            model, source_ids, target_ids, session_starts, session_index, weight
                        )
                    )
                else:
                    _link_same_course_sessions(
                        model, source_ids, target_ids, session_starts, session_index
                    )
                continue

            source_by_group = _group_session_ids(source_ids, session_index)
            target_by_group = _group_session_ids(target_ids, session_index)
            common_groups = sorted(set(source_by_group) & set(target_by_group))
            if not common_groups:
                # Pas de groupe brut partagé (rare) : repli sur la comparaison globale.
                common_groups = ["__all__"]
                source_by_group = {"__all__": source_ids}
                target_by_group = {"__all__": target_ids}

            for gid in common_groups:
                s_ids = source_by_group[gid]
                t_ids = target_by_group[gid]
                s_starts = [session_starts[sid] for sid in s_ids]
                t_starts = [session_starts[sid] for sid in t_ids]
                safe = f"{position}_{source_key}_{target_key}_{gid}".replace(":", "_").replace("-", "_")

                if not soft:
                    # Mode dur (petits tests / pas de cohortes) : séparation stricte
                    # max(A) < min(B) reste adapté quand le semestre n'est pas saturé.
                    if position == OrdonnancementPosition.BEFORE.value:
                        max_source = model.new_int_var(0, horizon - 1, f"max_src_{safe}")
                        min_target = model.new_int_var(0, horizon - 1, f"min_tgt_{safe}")
                        model.add_max_equality(max_source, s_starts)
                        model.add_min_equality(min_target, t_starts)
                        model.add(max_source < min_target)
                    elif position == OrdonnancementPosition.AFTER.value:
                        min_source = model.new_int_var(0, horizon - 1, f"min_src_{safe}")
                        max_target = model.new_int_var(0, horizon - 1, f"max_tgt_{safe}")
                        model.add_min_equality(min_source, s_starts)
                        model.add_max_equality(max_target, t_starts)
                        model.add(min_source > max_target)
                    continue

                # Cohortes réelles, semestre chargé : comparer la position
                # MOYENNE des séances plutôt que max<min. Un cours étalé sur
                # tout le semestre (objectif "spread") rend max<min quasi
                # impossible à satisfaire même par groupe ; la moyenne capture
                # "A se déroule globalement avant B" sans exiger une
                # séparation totale, ce qui reste satisfiable en pratique.
                # Comparaison par produit croisé pour éviter la division :
                # sum(A)/len(A) < sum(B)/len(B)  <=>  sum(A)*len(B) < sum(B)*len(A)
                sum_source = cp_model.LinearExpr.sum(s_starts)
                sum_target = cp_model.LinearExpr.sum(t_starts)
                lhs = sum_source * len(t_ids)
                rhs = sum_target * len(s_ids)

                if strict_mean:
                    if position == OrdonnancementPosition.BEFORE.value:
                        model.add(lhs < rhs)
                    else:
                        model.add(lhs > rhs)
                    continue

                ok = model.new_bool_var(f"ord_ok_{safe}")
                if position == OrdonnancementPosition.BEFORE.value:
                    model.add(lhs < rhs).only_enforce_if(ok)
                else:  # AFTER
                    model.add(lhs > rhs).only_enforce_if(ok)
                pen = model.new_int_var(0, weight, f"ord_pen_{safe}")
                model.add(pen == 0).only_enforce_if(ok)
                model.add(pen == weight).only_enforce_if(ok.Not())
                penalties.append(pen)

    return penalties


def _link_same_course_sessions(
    model: cp_model.CpModel,
    source_ids: list[str],
    target_ids: list[str],
    session_starts: dict[str, cp_model.IntVar],
    session_index: dict[str, SessionToPlace],
) -> None:
    source_by_order = _index_by_sequence(source_ids, session_index)
    target_by_order = _index_by_sequence(target_ids, session_index)
    for order, source_sid in source_by_order.items():
        target_sid = target_by_order.get(order)
        if target_sid:
            model.add(session_starts[source_sid] == session_starts[target_sid])


def _soft_link_same_course_sessions(
    model: cp_model.CpModel,
    source_ids: list[str],
    target_ids: list[str],
    session_starts: dict[str, cp_model.IntVar],
    session_index: dict[str, SessionToPlace],
    weight: int,
) -> list[cp_model.IntVar]:
    penalties: list[cp_model.IntVar] = []
    source_by_order = _index_by_sequence(source_ids, session_index)
    target_by_order = _index_by_sequence(target_ids, session_index)
    for order, source_sid in source_by_order.items():
        target_sid = target_by_order.get(order)
        if not target_sid:
            continue
        ok = model.new_bool_var(f"same_ok_{source_sid}_{target_sid}")
        model.add(session_starts[source_sid] == session_starts[target_sid]).only_enforce_if(ok)
        pen = model.new_int_var(0, weight, f"same_pen_{source_sid}_{target_sid}")
        model.add(pen == 0).only_enforce_if(ok)
        model.add(pen == weight).only_enforce_if(ok.Not())
        penalties.append(pen)
    return penalties


def _index_by_sequence(
    session_ids: list[str],
    session_index: dict[str, SessionToPlace],
) -> dict[int, str]:
    result: dict[int, str] = {}
    for sid in session_ids:
        session = session_index[sid]
        if session.sequence_order is not None and sid not in result.values():
            # une séance représentative par ordre (CM promo) — pour TD/TP plusieurs groupes
            key = session.sequence_order
            if key not in result:
                result[key] = sid
    return result


def add_pedagogical_sequence_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    groups: list[Group] | None = None,
) -> None:
    """
    Ordre pédagogique : séance ordre N avant séance ordre N+1 au sein d'un même
    `group_id` brut (TD/TP propres à un sous-groupe, ou séances "promo" entre
    elles) — cette partie reste per-groupe littéral, volontairement souple :
    forcer une synchronisation stricte de TOUS les sous-groupes à CHAQUE étape
    intermédiaire (ex. un CM en milieu de module) rend le problème combinatoire
    bien plus dur pour un gain pédagogique marginal (un léger différentiel de
    rythme entre 2 TP n'a rien de grave).

    Bug corrigé séparément (barrière ciblée, cf. `_eval_after_cohort_content_constraints`) :
    une évaluation partagée (tag "promo") n'était comparée qu'aux autres
    séances déjà taguées "promo", jamais au TD/TP d'un sous-groupe précis —
    elle pouvait donc être programmée AVANT que la plupart des groupes n'aient
    reçu le contenu qui la précède (ex. WR106 : éval en semaine 3 alors que le
    dernier TP la précédant n'a lieu qu'en semaine 18 pour 7 groupes sur 8).
    Contrairement au reste de la séquence, une évaluation est un vrai
    impératif académique (impossible d'évaluer un contenu non enseigné) : elle
    seule justifie une contrainte dure par cohorte.

    Tentative testée et abandonnée (05/08/2026, retour Kyllian Bresson :
    "les CM doivent être faits quand tous les groupes ont eu le même nombre
    de TD et TP") : étendre cette barrière à CHAQUE CM (pas seulement les
    évals), dans les deux sens (avant ET après). Implémenté et vérifié
    correct sur un cas synthétique, mais testé sur BUT1-S1 réel (1380
    séances) : `PARTIAL_WEEKS_FAILED` sur 5 semaines après ~50 min (contre
    un run fiable jusque-là) — dégradation de fiabilité confirmée, pas un bug.
    Décision utilisateur explicite : revenir à la version molle ci-dessus
    plutôt qu'investir sur la fiabilité ou passer en version pondérée — le
    différentiel de rythme reste jugé acceptable en pratique.
    """
    by_group_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for session in sessions:
        if session.sequence_order is None:
            continue
        for gid in session.group_ids:
            by_group_course[(session.course_code, session.semestre, gid)].append(session)

    for key, group_sessions in by_group_course.items():
        ordered = sorted(group_sessions, key=lambda s: s.sequence_order or 0)
        for prev, nxt in zip(ordered, ordered[1:]):
            if (prev.sequence_order or 0) < (nxt.sequence_order or 0):
                model.add(session_starts[prev.id] < session_starts[nxt.id])

    if groups:
        _add_eval_after_cohort_content_constraints(model, sessions, session_starts, groups)


def _add_eval_after_cohort_content_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    groups: list[Group],
) -> None:
    """Une éval (is_eval) doit suivre le DERNIER contenu de CHAQUE cohorte réelle."""
    from cal_iut.solver.resources import build_student_cohorts

    cohorts = build_student_cohorts(groups)

    by_course: dict[tuple[str, str], list[SessionToPlace]] = defaultdict(list)
    for s in sessions:
        if s.sequence_order is not None:
            by_course[(s.course_code, s.semestre)].append(s)

    for course_sessions in by_course.values():
        evals = [s for s in course_sessions if s.is_eval]
        if not evals:
            continue
        non_evals = [s for s in course_sessions if not s.is_eval]
        if not non_evals:
            continue

        for cohort_ids in cohorts.values():
            cohort_non_evals = [s for s in non_evals if cohort_ids.intersection(s.group_ids)]
            if not cohort_non_evals:
                continue
            last = max(cohort_non_evals, key=lambda s: s.sequence_order or 0)
            for e in evals:
                if (last.sequence_order or 0) < (e.sequence_order or 0):
                    model.add(session_starts[last.id] < session_starts[e.id])


def add_group_sync_penalties(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weeks: int,
    weight: int = 50,
) -> list[cp_model.IntVar]:
    """
    Encourage la synchronisation des groupes (même semaine pour un même ordre).
    Soft : évite l'infaisabilité quand un prof a peu de créneaux libres.
    """
    if weight <= 0:
        return []

    buckets: dict[tuple[str, str, int, str], list[str]] = defaultdict(list)
    for session in sessions:
        if session.sequence_order is None:
            continue
        if session.session_type.value == "CM":
            continue
        key = (
            session.course_code,
            session.semestre,
            session.sequence_order,
            session.session_type.value,
        )
        buckets[key].append(session.id)

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    max_week = max(0, weeks - 1)
    penalties: list[cp_model.IntVar] = []

    for bucket_idx, session_ids in enumerate(buckets.values()):
        if len(session_ids) < 2:
            continue
        week_vars: list[cp_model.IntVar] = []
        for sid in session_ids:
            week_var = model.new_int_var(0, max_week, f"sync_w_{bucket_idx}_{sid}")
            model.add_division_equality(week_var, session_starts[sid], slots_per_week)
            week_vars.append(week_var)

        min_w = model.new_int_var(0, max_week, f"sync_min_{bucket_idx}")
        max_w = model.new_int_var(0, max_week, f"sync_max_{bucket_idx}")
        model.add_min_equality(min_w, week_vars)
        model.add_max_equality(max_w, week_vars)
        span = model.new_int_var(0, max_week, f"sync_span_{bucket_idx}")
        model.add(span == max_w - min_w)
        weighted = model.new_int_var(0, max_week * weight, f"sync_pen_{bucket_idx}")
        model.add(weighted == span * weight)
        penalties.append(weighted)

    return penalties


def add_eval_clustering_penalties(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weeks: int,
    weight: int = 30,
) -> list[cp_model.IntVar]:
    """
    Regroupe les évaluations (is_eval) d'un même parcours/semestre sur une même
    semaine ("semaine de partiels"), sans les pousser plus tôt : seul l'écart
    (span) entre la 1ère et la dernière éval est pénalisé, peu importe où il se
    situe dans le semestre. Si un module finit tard, son éval peut légitimement
    tomber tard — seul le fait d'être ISOLÉE des autres évals est pénalisé.
    """
    if weight <= 0:
        return []

    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for session in sessions:
        if not session.is_eval:
            continue
        buckets[(session.semestre, session.parcours)].append(session.id)

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    max_week = max(0, weeks - 1)
    penalties: list[cp_model.IntVar] = []

    for bucket_idx, session_ids in enumerate(buckets.values()):
        if len(session_ids) < 2:
            continue
        week_vars: list[cp_model.IntVar] = []
        for sid in session_ids:
            week_var = model.new_int_var(0, max_week, f"eval_w_{bucket_idx}_{sid}")
            model.add_division_equality(week_var, session_starts[sid], slots_per_week)
            week_vars.append(week_var)

        min_w = model.new_int_var(0, max_week, f"eval_min_{bucket_idx}")
        max_w = model.new_int_var(0, max_week, f"eval_max_{bucket_idx}")
        model.add_min_equality(min_w, week_vars)
        model.add_max_equality(max_w, week_vars)
        span = model.new_int_var(0, max_week, f"eval_span_{bucket_idx}")
        model.add(span == max_w - min_w)
        weighted = model.new_int_var(0, max_week * weight, f"eval_pen_{bucket_idx}")
        model.add(weighted == span * weight)
        penalties.append(weighted)

    return penalties


def add_s1_integration_week_lock(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
) -> None:
    """
    Semaine d'intégration BUT1 (mer. 2 → ven. 4 septembre 2026, "semaine 2" côté
    département = semaine-index 0 du solveur pour S1) : aucun cours classique ni
    SAE, uniquement de l'accueil administratif. Le vrai démarrage des
    enseignements S1 est le lundi 7 septembre 2026 (semaine-index 1).
    """
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    for session in sessions:
        if session.semestre != "S1":
            continue
        start = session_starts[session.id]
        for t in range(slots_per_week):
            model.add(start != t)


def add_course_min_week_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    rules: list[CourseMinWeekRule],
    weeks: int,
) -> None:
    """
    Interdit à un cours de démarrer avant `rule.min_week` (cf.
    `CourseMinWeekRule`) — ex. WR119/PPP S1 ne doit pas commencer dès la
    rentrée (retour utilisateur, cf. course_scheduling_rules.yaml).
    """
    if not rules:
        return
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    by_key = {(r.course_code, r.semestre): r for r in rules}
    for session in sessions:
        rule = by_key.get((session.course_code, session.semestre))
        if rule is None or rule.min_week <= 0:
            continue
        min_week = min(rule.min_week, weeks)
        start = session_starts[session.id]
        model.add(start >= min_week * slots_per_week)


def add_planning_event_block_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    blocked_slots: set[tuple[int, int, int]],
    weeks: int,
) -> None:
    """
    Interdit tout cours classique sur un créneau précis occupé par un
    événement du planning officiel avec horaire explicite (ex. "9h30 Echange
    IA", "17h / 18H30 Présentation des services aux nouveaux étudiants" —
    retour utilisateur : ces créneaux étaient affichés mais pas réellement
    bloqués). `blocked_slots` = sortie de `planning_loader.py::
    planning_event_blocked_slots` : (semaine relative, jour, slot). Grain du
    créneau (pas du jour entier comme la sanctuarisation SAE ou les jours
    fériés) — utilise `_forbid_slot_for_duration` pour qu'une séance "double"
    ne puisse pas non plus chevaucher ce créneau.
    """
    if not blocked_slots:
        return
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    horizon = weeks * slots_per_week
    absolute: set[int] = set()
    for week, day, slot in blocked_slots:
        if not (0 <= week < weeks):
            continue
        t = week * slots_per_week + day * SLOTS_PER_DAY + slot
        if 0 <= t < horizon:
            absolute.add(t)
    if not absolute:
        return
    for session in sessions:
        duration = max(1, session.duration_slots)
        start = session_starts[session.id]
        for t in absolute:
            _forbid_slot_for_duration(model, start, t, duration)


# Créneaux réellement collés dans le temps : matin (8h-12h30, slots 0-2) et
# après-midi (14h-18h30, slots 3-5) — SÉPARÉS par la pause méridienne
# (12h30-14h00, entre les slots 2 et 3). Une séance "double" ne doit jamais
# chevaucher cette pause : ce ne serait plus une séance collée mais deux
# séances distinctes avec une pause au milieu.
_CONTIGUOUS_SLOT_RUNS: tuple[tuple[int, ...], ...] = ((0, 1, 2), (3, 4, 5))


def _valid_duration_starts(duration: int) -> set[int]:
    """Slots de départ (0..SLOTS_PER_DAY-1) où un bloc de `duration` créneaux
    tient entièrement dans UN SEUL des runs collés (`_CONTIGUOUS_SLOT_RUNS`),
    sans déborder ni sur la pause méridienne ni sur le jour suivant."""
    return {s for run in _CONTIGUOUS_SLOT_RUNS for s in run if s + duration - 1 <= run[-1]}


def add_duration_domain_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weeks: int,
) -> None:
    """
    Séance "double" (`duration_slots>1`, ex. TP collé en bloc de 3h = 2×1h30,
    cf. `data/config/double_sessions.yaml`) : interdit tout `start` qui la
    ferait déborder sur le jour suivant OU chevaucher la pause méridienne — un
    bloc de N créneaux ne peut démarrer que dans un run collé qui le contient
    entièrement (cf. `_valid_duration_starts`).

    Condition préalable à la correction de toutes les fonctions qui
    raisonnent "créneau bloqué en milieu de journée -> ce `start` précis est
    interdit" (jeudi PAC, dispos ponctuelles enseignant) : une fois qu'un bloc
    ne peut plus jamais chevaucher deux journées ni la pause méridienne, il
    suffit d'étendre ces fonctions à interdire aussi les `start` immédiatement
    AVANT le créneau bloqué (cf. `_forbid_slot_for_duration`) sans risquer de
    forbid un `start` en réalité situé dans un autre run.
    """
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    horizon = weeks * slots_per_week
    starts_cache: dict[int, set[int]] = {}
    for session in sessions:
        duration = max(1, session.duration_slots)
        if duration <= 1:
            continue
        valid_starts = starts_cache.setdefault(duration, _valid_duration_starts(duration))
        start = session_starts[session.id]
        for t in range(horizon):
            if t % SLOTS_PER_DAY not in valid_starts:
                model.add(start != t)


def _forbid_slot_for_duration(
    model: cp_model.CpModel,
    start: cp_model.IntVar,
    t: int,
    duration: int,
) -> None:
    """
    Interdit à une séance de durée `duration` d'occuper le créneau absolu
    `t` : interdit tout `start` dont l'occupation [start, start+duration)
    couvre `t`, càd `start` in [t-duration+1, t]. Ne franchit jamais une
    frontière de jour par construction : un `start` la veille de `t` violerait
    déjà `add_duration_domain_constraints` (donc `model.add(start != ...)`
    reste correct même sans filtrer explicitement le jour ici).
    """
    for k in range(duration):
        candidate = t - k
        if candidate >= 0:
            model.add(start != candidate)


def add_blocked_calendar_constraints(
    model: cp_model.CpModel,
    session_starts: dict[str, cp_model.IntVar],
    calendar: AcademicCalendar,
    weeks: int,
) -> None:
    """Interdit les créneaux sur jours fériés / pauses pédagogiques."""
    blocked = calendar.blocked_time_indices(weeks)
    if not blocked:
        return
    for start in session_starts.values():
        for t in blocked:
            if 0 <= t < weeks * DAYS_PER_WEEK * SLOTS_PER_DAY:
                model.add(start != t)


def add_sae_window_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    sae_days_by_course: dict[str, set[tuple[int, int]]],
    weeks: int,
) -> list[cp_model.IntVar]:
    """
    SAE = projets / évals multi-jours (planning officiel Excel).

    Soft : pousse les séances des cours WSAxxx / WSxxx vers leurs fenêtres SAE.
    """
    if not sae_days_by_course:
        return []

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    penalties: list[cp_model.IntVar] = []

    for session in sessions:
        preferred = sae_days_by_course.get(session.course_code)
        if not preferred:
            continue

        preferred_times: list[int] = []
        for week, day in preferred:
            if 0 <= week < weeks:
                base = week * slots_per_week + day * SLOTS_PER_DAY
                preferred_times.extend(range(base, base + SLOTS_PER_DAY))

        if not preferred_times:
            continue

        start = session_starts[session.id]
        in_window = model.new_bool_var(f"sae_in_{session.id}")
        model.add_allowed_assignments([start], [[t] for t in preferred_times]).only_enforce_if(in_window)
        pen = model.new_int_var(0, 40, f"sae_pen_{session.id}")
        model.add(pen == 40).only_enforce_if(in_window.Not())
        model.add(pen == 0).only_enforce_if(in_window)
        penalties.append(pen)

    return penalties


def sae_blocked_days_by_parcours(
    sessions: list[SessionToPlace],
    sae_days_by_course: dict[str, set[tuple[int, int]]],
) -> dict[str, set[tuple[int, int]]]:
    """Union des jours SAE (week, day) par parcours, déduits des séances SAE réelles."""
    blocked: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for session in sessions:
        days = sae_days_by_course.get(session.course_code)
        if not days:
            continue
        blocked[session.parcours] |= days
    return dict(blocked)


def add_sae_sanctuarization_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    blocked_by_parcours: dict[str, set[tuple[int, int]]],
    weeks: int,
) -> None:
    """
    Sanctuarisation SAE (cahier des charges §8, contrainte dure) : si un jour est
    alloué à une SAE pour un parcours, aucune ressource classique (WR/WRA) ne peut
    être placée ce jour-là pour ce même parcours -> la journée est 100% dédiée au
    projet. Les séances SAE elles-mêmes (codes WS/WSA) ne sont pas concernées —
    et ne sont d'ailleurs plus planifiées du tout par l'algorithme (retour
    utilisateur : une SAE est définie par les enseignants eux-mêmes, seules ses
    dates calendaires réelles servent ici à bloquer les cours classiques).

    `blocked_by_parcours` : précalculé par l'appelant via
    `sae_blocked_days_by_parcours` sur la liste COMPLÈTE des séances (WSxxx
    incluses, avant qu'elles ne soient retirées de la planification) — cette
    fonction ne dérive plus rien elle-même à partir de `sessions`, pour ne pas
    dépendre de la présence d'une séance SAE dans le lot passé ici.
    """
    if not blocked_by_parcours:
        return

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    horizon = weeks * slots_per_week

    for session in sessions:
        if session.course_code.upper().startswith("WS"):
            continue
        blocked_days = blocked_by_parcours.get(session.parcours)
        if not blocked_days:
            continue

        start = session_starts[session.id]
        for week, day in blocked_days:
            if not (0 <= week < weeks):
                continue
            base = week * slots_per_week + day * SLOTS_PER_DAY
            for slot in range(SLOTS_PER_DAY):
                t = base + slot
                if 0 <= t < horizon:
                    model.add(start != t)


def add_student_presence_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    presences: list[StudentPresence],
    calendar: AcademicCalendar,
    week_offset: int,
    weeks: int,
) -> None:
    """Pour les parcours FC : n'autoriser que les jours de présence alternance."""
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    presence_by_parcours: dict[str, StudentPresence] = {}
    for presence in presences:
        for key in presence.parcours_keys:
            presence_by_parcours[key] = presence

    for session in sessions:
        presence = presence_by_parcours.get(session.parcours)
        if not presence or not presence.presence_dates:
            continue
        # Ne s'applique qu'aux parcours FC
        if "FC" not in session.parcours:
            continue

        allowed = allowed_week_days_for_parcours(presence, calendar, week_offset, weeks)
        if not allowed:
            continue

        allowed_times: list[int] = []
        for week, day in allowed:
            base = week * slots_per_week + day * SLOTS_PER_DAY
            allowed_times.extend(range(base, base + SLOTS_PER_DAY))

        if not allowed_times:
            continue

        model.add_allowed_assignments([session_starts[session.id]], [[t] for t in allowed_times])


def add_teacher_availability_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    availability: list[TeacherAvailability],
    weeks: int,
    calendar: AcademicCalendar | None = None,
    week_offset: int = 0,
) -> None:
    """Interdit créneaux récurrents + dates absolues d'indisponibilité."""
    avail_by_code = {a.teacher_code: a for a in availability}
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    horizon = weeks * slots_per_week

    for session in sessions:
        duration = max(1, session.duration_slots)
        for teacher_code in session.teacher_codes:
            teacher_avail = avail_by_code.get(teacher_code)
            if not teacher_avail:
                continue

            for week in range(weeks):
                for day, slot in teacher_avail.forbidden_slots:
                    forbidden_time = week * slots_per_week + day * SLOTS_PER_DAY + slot
                    if 0 <= forbidden_time < horizon:
                        _forbid_slot_for_duration(model, session_starts[session.id], forbidden_time, duration)

            # Dates absolues (CSV enseignants)
            forbidden_dates_raw = teacher_avail.metadata.get("forbidden_dates") or []
            if calendar and forbidden_dates_raw:
                for raw in forbidden_dates_raw:
                    d = date.fromisoformat(str(raw))
                    mapped = calendar.date_to_week_day(d)
                    if mapped is None:
                        continue
                    abs_week, day = mapped
                    rel = abs_week - week_offset
                    if 0 <= rel < weeks:
                        base = rel * slots_per_week + day * SLOTS_PER_DAY
                        for slot in range(SLOTS_PER_DAY):
                            model.add(session_starts[session.id] != base + slot)


def _is_fc_parcours(parcours: str) -> bool:
    return "FC" in parcours


def add_thursday_afternoon_pac_lock(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weeks: int,
) -> None:
    """
    Jeudi après-midi (14h00-18h30) verrouillé pour la Formation Initiale (S1/S2 et
    parcours *-FI de S3 à S6) : réservé aux PAC (Pratique Artistique et Culturelle),
    placées manuellement, jamais par le solveur.

    Les parcours FC (alternance) ne sont pas concernés : ce créneau reste
    disponible pour eux (stratégique car salles/équipements moins sollicités).
    """
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    afternoon_slots = (
        TimeSlot.SLOT_14_1530.value,
        TimeSlot.SLOT_1530_17.value,
        TimeSlot.SLOT_17_1830.value,
    )
    forbidden: set[int] = set()
    for week in range(weeks):
        base = week * slots_per_week + WeekDay.THURSDAY.value * SLOTS_PER_DAY
        forbidden.update(base + slot for slot in afternoon_slots)

    for session in sessions:
        if _is_fc_parcours(session.parcours):
            continue
        start = session_starts[session.id]
        duration = max(1, session.duration_slots)
        for t in forbidden:
            _forbid_slot_for_duration(model, start, t, duration)


def add_weekly_hour_cap_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    groups: list[Group],
    weeks: int,
    *,
    fi_cap_slots: int = 22,
    fc_cap_slots: int = 23,
) -> None:
    """
    Contrainte dure de volume horaire hebdomadaire par étudiant (cahier des charges §3).

    - FI (formation initiale) : max 33h/semaine = 22 créneaux de 1h30 (strict).
    - FC (alternants)         : objectif ~35h/semaine = 23 créneaux de 1h30 max
      (les séances PTUT servent de variable d'ajustement en amont, côté ingestion).

    S'applique par cohorte étudiante réelle (CM promo + TD + TP), pas par group_id
    brut, pour ne pas sous-compter la charge d'un étudiant qui suit les trois.
    """
    if not groups:
        return

    from cal_iut.solver.resources import build_student_cohorts

    cohorts = build_student_cohorts(groups)
    if not cohorts:
        return

    group_by_id = {g.id: g for g in groups}
    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    max_week = max(0, weeks - 1)

    session_week_var: dict[str, cp_model.IntVar] = {}
    week_indicator_cache: dict[tuple[str, int], cp_model.IntVar] = {}

    def week_indicator(session_id: str, week: int) -> cp_model.IntVar:
        cache_key = (session_id, week)
        cached = week_indicator_cache.get(cache_key)
        if cached is not None:
            return cached

        week_var = session_week_var.get(session_id)
        if week_var is None:
            week_var = model.new_int_var(0, max_week, f"capwk_{session_id}")
            model.add_division_equality(week_var, session_starts[session_id], slots_per_week)
            session_week_var[session_id] = week_var

        indicator = model.new_bool_var(f"capin_{session_id}_w{week}")
        model.add(week_var == week).only_enforce_if(indicator)
        model.add(week_var != week).only_enforce_if(indicator.Not())
        week_indicator_cache[cache_key] = indicator
        return indicator

    for resource_key, cohort_ids in cohorts.items():
        cohort_sessions = [s for s in sessions if cohort_ids.intersection(s.group_ids)]
        if not cohort_sessions:
            continue

        parcours_sample = next(
            (group_by_id[gid].parcours for gid in cohort_ids if gid in group_by_id),
            "",
        )
        cap = fc_cap_slots if _is_fc_parcours(parcours_sample) else fi_cap_slots

        for week in range(weeks):
            terms = []
            for session in cohort_sessions:
                indicator = week_indicator(session.id, week)
                duration = max(1, session.duration_slots)
                terms.append(indicator * duration if duration != 1 else indicator)
            if terms:
                safe_key = resource_key.replace(":", "_")
                model.add(sum(terms) <= cap).with_name(f"weekcap_{safe_key}_w{week}")


def add_teacher_weekly_hour_cap_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    weeks: int,
    *,
    cap_slots: int = 20,
) -> None:
    """
    Plafond hebdomadaire ENSEIGNANT, jumeau de `add_weekly_hour_cap_constraints`
    (qui plafonne par cohorte étudiante) mais indexé par `teacher_code`.

    Nécessaire uniquement pour une régénération jointe sur plusieurs semaines
    (`solve_week_detail(num_weeks>1)`, cf. plan "gestion manuelle du
    planning") : une fois qu'une séance peut changer de semaine, le plafond
    hebdo enseignant garanti par l'étage 2 (`assign_weeks`, cap 20 par
    défaut, decomposed.py) n'est plus automatiquement respecté — cette
    fonction le fait respecter localement, sur la portée régénérée.
    """
    teacher_codes = sorted({tc for s in sessions for tc in s.teacher_codes})
    if not teacher_codes:
        return

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    max_week = max(0, weeks - 1)

    session_week_var: dict[str, cp_model.IntVar] = {}
    week_indicator_cache: dict[tuple[str, int], cp_model.IntVar] = {}

    def week_indicator(session_id: str, week: int) -> cp_model.IntVar:
        cache_key = (session_id, week)
        cached = week_indicator_cache.get(cache_key)
        if cached is not None:
            return cached
        week_var = session_week_var.get(session_id)
        if week_var is None:
            week_var = model.new_int_var(0, max_week, f"tcapwk_{session_id}")
            model.add_division_equality(week_var, session_starts[session_id], slots_per_week)
            session_week_var[session_id] = week_var
        indicator = model.new_bool_var(f"tcapin_{session_id}_w{week}")
        model.add(week_var == week).only_enforce_if(indicator)
        model.add(week_var != week).only_enforce_if(indicator.Not())
        week_indicator_cache[cache_key] = indicator
        return indicator

    for teacher_code in teacher_codes:
        teacher_sessions = [s for s in sessions if teacher_code in s.teacher_codes]
        for week in range(weeks):
            terms = []
            for session in teacher_sessions:
                indicator = week_indicator(session.id, week)
                duration = max(1, session.duration_slots)
                terms.append(indicator * duration if duration != 1 else indicator)
            if terms:
                safe_key = teacher_code.replace(":", "_")
                model.add(sum(terms) <= cap_slots).with_name(f"teachercap_{safe_key}_w{week}")


def duo_episode_pairs(
    sessions: list[SessionToPlace],
    duos: list[TeacherDuo],
) -> list[tuple[str, str]]:
    """
    Paires de séances synchronisées (une par épisode de co-animation), pour
    un duo d'enseignants sur une salle rare dédoublée : pour un même cours et
    un même `sequence_order`, chaque séance d'un enseignant du duo est
    appariée par POSITION avec une séance de l'autre (1er groupe de l'un avec
    le 1er groupe de l'autre, etc.) — jamais toutes fusionnées en un seul
    instant, un même enseignant pouvant avoir plusieurs groupes au même
    `sequence_order` (ex. `nbGpTp=2`), qui doivent rester à des instants
    différents (déjà garanti par le NoOverlap enseignant — les y forcer égaux
    serait contradictoire).

    Factorisé car utilisé à la fois par la contrainte dure temps-plein
    (`add_duo_synchronized_rare_room_constraints`) et par l'étage 2 du
    solveur décomposé (`solver/decomposed.py`, appariement au niveau semaine).
    """
    pairs: list[tuple[str, str]] = []
    for duo in duos:
        t1, t2 = duo.teacher_codes
        for course_code in duo.course_codes:
            by_order_t1: dict[int, list[str]] = defaultdict(list)
            by_order_t2: dict[int, list[str]] = defaultdict(list)
            for s in sessions:
                if s.course_code != course_code or s.sequence_order is None:
                    continue
                if s.session_type.value not in duo.session_types:
                    continue
                if t1 in s.teacher_codes:
                    by_order_t1[s.sequence_order].append(s.id)
                if t2 in s.teacher_codes:
                    by_order_t2[s.sequence_order].append(s.id)

            for order in sorted(set(by_order_t1) & set(by_order_t2)):
                # Tri par id (déterministe) : apparie le 1er groupe de t1 au
                # 1er groupe de t2, etc.
                ids1 = sorted(by_order_t1[order])
                ids2 = sorted(by_order_t2[order])
                pairs.extend(zip(ids1, ids2))
    return pairs


def add_duo_synchronized_rare_room_constraints(
    model: cp_model.CpModel,
    sessions: list[SessionToPlace],
    session_starts: dict[str, cp_model.IntVar],
    duos: list[TeacherDuo],
) -> None:
    """
    Duo d'enseignants co-animant en simultané sur une salle rare dédoublée
    (ex. Studio H.017+H.022, cf. `TeacherDuo` / `data/config/teacher_duos.yaml`) :

    (a) chaque paire de `duo_episode_pairs` démarre au MÊME instant
        (co-animation réelle) ;
    (b) deux épisodes synchronisés distincts (même duo ou duos différents) ne
        se chevauchent jamais : une seule paire de salles rare existe à la
        fois.

    L'affectation salle proprement dite (qui va en H.017 vs H.022) est faite
    par `solver/rooms.py::assign_rooms` (couche gloutonne post-placement) une
    fois cette synchronisation temporelle garantie ici.
    """
    if not duos:
        return

    from cal_iut.solver.resources import add_aliased_no_overlap

    durations = {s.id: max(1, s.duration_slots) for s in sessions}
    representative_ids: list[str] = []
    for sid1, sid2 in duo_episode_pairs(sessions, duos):
        model.add(session_starts[sid1] == session_starts[sid2])
        representative_ids.append(sid1)

    if len(representative_ids) >= 2:
        add_aliased_no_overlap(model, session_starts, representative_ids, "duo_rare_room", durations)
