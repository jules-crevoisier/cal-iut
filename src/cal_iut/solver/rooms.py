"""Affectation des salles post-placement temporel."""

import fnmatch
from collections import defaultdict
from dataclasses import dataclass

from cal_iut.models.entities import Group, Room, RoomType, TeacherDuo
from cal_iut.solver.cpsat import PlacedSession


@dataclass
class RoomAssignmentRule:
    session_types: list[str]
    course_code_patterns: list[str]
    preferred_room_types: list[RoomType]
    fallback_room_types: list[RoomType]
    same_room_for_course: bool = False
    is_eval: bool | None = None  # None = indifférent ; True/False = filtre strict


@dataclass
class PlacedSessionWithRoom(PlacedSession):
    room_id: str | None = None
    room_label: str | None = None


def parse_room_rules(raw_rules: list[dict[str, object]]) -> list[RoomAssignmentRule]:
    rules: list[RoomAssignmentRule] = []
    for raw in raw_rules:
        raw_is_eval = raw.get("is_eval")
        rules.append(
            RoomAssignmentRule(
                session_types=[str(t) for t in raw.get("session_types", [])],
                course_code_patterns=[str(p) for p in raw.get("course_code_patterns", [])],
                preferred_room_types=[RoomType(t) for t in raw.get("preferred_room_types", [])],
                fallback_room_types=[RoomType(t) for t in raw.get("fallback_room_types", [])],
                same_room_for_course=bool(raw.get("same_room_for_course", False)),
                is_eval=None if raw_is_eval is None else bool(raw_is_eval),
            )
        )
    return rules


def _time_index(placement: PlacedSession) -> int:
    from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    return placement.week * slots_per_week + placement.day * SLOTS_PER_DAY + placement.slot


def _occupied_indices(placement: PlacedSession, duration: int) -> list[int]:
    """
    Créneaux temporels occupés par un placement — plusieurs pour une séance
    "double" (`duration_slots>1`, ex. TP collé en bloc de 3h) : le solveur
    garantit déjà (`add_duration_domain_constraints`) que ce bloc tient sur
    UNE seule journée, donc ce range consécutif ne déborde jamais dessus.
    """
    base = _time_index(placement)
    return list(range(base, base + max(1, duration)))


def _sort_key(placement: PlacedSession) -> tuple[int, str]:
    # `session_id` en clé secondaire : sans ça, deux séances au même horaire
    # sont ordonnées arbitrairement par le solveur CP-SAT (ordre non garanti
    # d'un run à l'autre), ce qui peut faire varier l'affectation de salle à
    # qualité de solution identique — nuit à la prévisibilité recherchée.
    return (_time_index(placement), placement.session_id)


def _match_rule(
    rule: RoomAssignmentRule,
    course_code: str,
    session_type: str,
    is_eval: bool,
) -> bool:
    type_ok = not rule.session_types or session_type in rule.session_types
    pattern_ok = not rule.course_code_patterns or any(
        fnmatch.fnmatch(course_code, pattern) for pattern in rule.course_code_patterns
    )
    eval_ok = rule.is_eval is None or rule.is_eval == is_eval
    return type_ok and pattern_ok and eval_ok


def _find_matching_rule(
    rules: list[RoomAssignmentRule],
    course_code: str,
    session_type: str,
    is_eval: bool = False,
) -> RoomAssignmentRule | None:
    matched = [r for r in rules if _match_rule(r, course_code, session_type, is_eval)]
    if not matched:
        return None
    return matched[-1]


def _room_priority(
    room: Room,
    preferred: list[RoomType],
    fallback: list[RoomType],
) -> int:
    if room.room_type in preferred:
        return preferred.index(room.room_type)
    if room.room_type in fallback:
        return len(preferred) + fallback.index(room.room_type)
    return 100


def _consecutive_runs(
    sorted_placements: list[PlacedSession],
    sessions_by_id: dict[str, object],
) -> list[list[PlacedSession]]:
    """
    Regroupe les séances qui s'ENCHAÎNENT sans interruption le même jour pour
    un même (cours, type, groupe, enseignant) — cf. `assign_rooms`, qui leur
    réserve une salle unique. Une éval n'est jamais regroupée (salle dédiée
    A.018 via sa propre règle).
    """
    def key(p: PlacedSession) -> tuple:
        session = sessions_by_id.get(p.session_id)
        st = getattr(session, "session_type", None)
        return (
            p.course_code,
            st.value if st else "",
            tuple(sorted(p.group_ids)),
            tuple(sorted(p.teacher_codes)),
            p.week,
            p.day,
        )

    by_key: dict[tuple, list[PlacedSession]] = defaultdict(list)
    for p in sorted_placements:
        if bool(getattr(sessions_by_id.get(p.session_id), "is_eval", False)):
            by_key[("__eval__", p.session_id)].append(p)
        else:
            by_key[key(p)].append(p)

    runs: list[list[PlacedSession]] = []
    for group in by_key.values():
        group.sort(key=lambda p: p.slot)
        current = [group[0]]
        for prev, nxt in zip(group, group[1:]):
            duration = max(1, getattr(sessions_by_id.get(prev.session_id), "duration_slots", 1))
            if nxt.slot == prev.slot + duration:
                current.append(nxt)
            else:
                runs.append(current)
                current = [nxt]
        runs.append(current)

    runs.sort(key=lambda g: _sort_key(g[0]))
    return runs


def _headcount_for_groups(group_ids: list[str], groups: list[Group]) -> int:
    """
    30 = repli neutre historique (aucun `group_id` fourni). Étendu le
    11/08/2026 : un `group_id` NON reconnu (aucun des `group_ids` fournis
    n'existe dans `groups`) tombait sur `max()` d'un générateur vide ->
    `ValueError`, qui faisait 500er `/app-state` EN ENTIER (donc les 4 vues
    lecture seule + `/legacy`) pour une seule séance mal résolue — trouvé en
    conditions réelles : `_try_restore_latest` (API) ré-ingère en LIVE
    (`run_ingestion` sans cache, contrairement au CLI `--from-cache`) au
    redémarrage du serveur, donc peut légitimement dater d'un instant où le
    fetch amont différait de celui utilisé pour calculer le planning stocké
    en base — un vrai risque de désync, pas une faute de frappe locale.
    """
    group_map = {g.id: g for g in groups}
    if not group_ids:
        return 30
    known = [group_map[gid].headcount for gid in group_ids if gid in group_map]
    return max(known) if known else 30


def _duo_room_overrides(
    placements: list[PlacedSession],
    sessions_by_id: dict[str, object],
    duos: list[TeacherDuo],
    rooms: list[Room],
) -> dict[str, Room]:
    """
    session_id -> salle forcée pour les séances de duo synchronisé (cf.
    `add_duo_synchronized_rare_room_constraints`, qui garantit déjà qu'elles
    démarrent au même instant) : le 1er enseignant du duo va systématiquement
    dans `rare_rooms[0]` (ex. H.017), le 2e dans `rare_rooms[1]` (H.022) —
    affectation déterministe, pas soumise à la logique générique par priorité.
    """
    if not duos:
        return {}
    room_by_id = {r.id: r for r in rooms}
    overrides: dict[str, Room] = {}

    for duo in duos:
        t1, t2 = duo.teacher_codes
        room1 = room_by_id.get(duo.rare_rooms[0])
        room2 = room_by_id.get(duo.rare_rooms[1])
        if room1 is None or room2 is None:
            continue
        for course_code in duo.course_codes:
            by_time: dict[int, dict[str, str]] = defaultdict(dict)
            for p in placements:
                session = sessions_by_id.get(p.session_id)
                if session is None or getattr(session, "course_code", None) != course_code:
                    continue
                session_type = getattr(session, "session_type", None)
                st_value = session_type.value if session_type else None
                if st_value not in duo.session_types:
                    continue
                teacher_codes = getattr(session, "teacher_codes", [])
                if t1 in teacher_codes:
                    by_time[_time_index(p)]["t1"] = p.session_id
                elif t2 in teacher_codes:
                    by_time[_time_index(p)]["t2"] = p.session_id
            for slots in by_time.values():
                if "t1" in slots:
                    overrides[slots["t1"]] = room1
                if "t2" in slots:
                    overrides[slots["t2"]] = room2
    return overrides


def assign_rooms(
    placements: list[PlacedSession],
    sessions_by_id: dict[str, object],
    rooms: list[Room],
    groups: list[Group],
    rules: list[RoomAssignmentRule],
    duos: list[TeacherDuo] | None = None,
    course_cm_room_seed: dict[str, str] | None = None,
) -> list[PlacedSessionWithRoom]:
    """
    Affecte les salles par placement glouton avec règles configurables.

    `course_cm_room_seed` : pré-remplit `course_cm_room` (règle
    `same_room_for_course`) avec la salle déjà utilisée par un cours HORS de
    `placements` — nécessaire pour une régénération partielle (1-2 semaines) :
    sans ça, un cours qui garde toujours la même salle de CM sur tout le
    semestre pourrait en changer juste pour la fenêtre régénérée.
    """
    duo_overrides = _duo_room_overrides(placements, sessions_by_id, duos or [], rooms)
    sorted_placements = sorted(placements, key=_sort_key)
    room_schedule: dict[str, set[int]] = {r.id: set() for r in rooms}
    course_cm_room: dict[str, str] = dict(course_cm_room_seed or {})
    results: list[PlacedSessionWithRoom] = []

    # Continuité de salle sur des créneaux CONSÉCUTIFS d'un même cours, pour
    # le même groupe et le même enseignant (retour utilisateur 08/08/2026 :
    # "c'est la même matière et le même prof à chaque heure consécutive, il
    # faudrait donc que ce soit dans la même salle et qu'il n'y ait pas de
    # changement" — constaté sur WRA507D/BTO réparti sur H.007, H.201 puis
    # H.008 d'affilée). Distinct de `same_room_for_course`, qui fige UNE salle
    # pour tout le semestre (réservé aux CM) : ici la salle n'est conservée
    # que tant que les séances s'enchaînent sans interruption dans la journée.
    #
    # La salle est RÉSERVÉE d'emblée pour toute la série dès sa 1re séance :
    # une simple reconduction séance par séance échouait dès qu'une autre
    # séance, traitée avant au même créneau, raflait la salle entre-temps
    # (40 ruptures sur 158 séries mesurées avec cette 1re approche).
    runs = _consecutive_runs(sorted_placements, sessions_by_id)
    run_of: dict[str, int] = {}
    run_slots: dict[int, list[int]] = {}
    run_head: dict[int, str] = {}
    for run_id, group in enumerate(runs):
        run_head[run_id] = group[0].session_id
        slots: list[int] = []
        for p in group:
            run_of[p.session_id] = run_id
            slots.extend(_occupied_indices(p, max(1, getattr(sessions_by_id.get(p.session_id), "duration_slots", 1))))
        run_slots[run_id] = slots
    run_room: dict[int, Room] = {}

    for placement in sorted_placements:
        session = sessions_by_id.get(placement.session_id)
        session_type = getattr(session, "session_type", None)
        st_value = session_type.value if session_type else "TP"
        is_eval = bool(getattr(session, "is_eval", False))
        course_code = placement.course_code

        duration = max(1, getattr(session, "duration_slots", 1))

        duo_room = duo_overrides.get(placement.session_id)
        if duo_room is not None:
            room_schedule[duo_room.id].update(_occupied_indices(placement, duration))
            results.append(_with_room(placement, duo_room))
            continue

        rule = _find_matching_rule(rules, course_code, st_value, is_eval)
        preferred = rule.preferred_room_types if rule else [RoomType.STANDARD]
        fallback = rule.fallback_room_types if rule else [RoomType.STANDARD, RoomType.AMPHI]
        same_room = rule.same_room_for_course if rule else False

        occupied = _occupied_indices(placement, duration)

        # Une éval ne réutilise jamais la salle de CM en cache : elle doit
        # passer par la règle dédiée (A.018), même si le CM normal du même
        # cours a déjà été placé ailleurs (ex. WR107 CM2 = évaluation).
        #
        # Bug réel corrigé (06/08/2026, trouvé en vérifiant le run Groupe A
        # après les correctifs du jour) : cette branche affectait la salle
        # en cache SANS jamais vérifier `room_schedule` ni le mettre à jour
        # — un 2e cours (parcours différent) pouvait légitimement récupérer
        # la MÊME salle au MÊME créneau via le chemin normal ci-dessous,
        # créant un vrai double-booking physique (ex. amphi H.018 partagé
        # par un CM BUT1 et un CM BUT2-DEV-FI simultanés). Retombe
        # maintenant sur la sélection normale (avec mise à jour de
        # `room_schedule`) si la salle habituelle du cours est déjà prise
        # à CE créneau précis, plutôt que de garantir "même salle" au prix
        # d'une double réservation.
        if same_room and st_value == "CM" and not is_eval and course_code in course_cm_room:
            room_id = course_cm_room[course_code]
            room = next((r for r in rooms if r.id == room_id), None)
            if room is not None and room_schedule[room.id].isdisjoint(occupied):
                room_schedule[room.id].update(occupied)
                results.append(_with_room(placement, room))
                continue

        needed = _headcount_for_groups(placement.group_ids, groups)

        # Séance faisant suite à une série déjà pourvue : la salle lui est
        # déjà réservée (cf. `run_room`), aucun changement possible.
        run_id = run_of.get(placement.session_id)
        if run_id is not None and run_id in run_room:
            results.append(_with_room(placement, run_room[run_id]))
            continue

        # H.018 (amphi) réservé idéalement aux CM : exclu du 1er passage pour
        # tout autre type de séance, quitte à retomber sur lui en tout
        # dernier recours (2e passage ci-dessous) plutôt que de laisser une
        # séance sans salle du tout.
        reserve_amphi = st_value != "CM"

        # Tri : type de salle préféré d'abord, PUIS la plus petite salle qui
        # convient encore ("best fit"). Retour utilisateur (07/08/2026) :
        # "pour les 3e année dev FC il faut les mettre dans la H.005 le plus
        # souvent possible ou les petites salles car c'est uniquement un
        # groupe de 8" — avant, à priorité de type égale l'ordre de
        # `rooms.yaml` décidait, ce qui pouvait placer un groupe de 8 dans une
        # salle de 30 alors qu'une salle de 15 était libre, et réciproquement
        # occuper inutilement les petites salles avec de gros groupes.
        # Tête d'une série de créneaux enchaînés : on cherche d'abord une salle
        # libre sur TOUTE la série, pour la lui réserver d'un bloc. À défaut,
        # on retombe sur le créneau seul (la série se scinde alors, faute de
        # salle disponible de bout en bout — jamais au prix d'un conflit).
        is_run_head = run_id is not None and run_head.get(run_id) == placement.session_id
        span = run_slots[run_id] if (is_run_head and len(run_slots[run_id]) > len(occupied)) else occupied

        def _pick(window: list[int]) -> list[Room]:
            fitting = sorted(
                [
                    r
                    for r in rooms
                    if r.capacity >= needed
                    and room_schedule[r.id].isdisjoint(window)
                    and not (reserve_amphi and r.room_type == RoomType.AMPHI)
                ],
                key=lambda r: (_room_priority(r, preferred, fallback), r.capacity),
            )
            if fitting:
                return fitting
            return sorted(
                [r for r in rooms if room_schedule[r.id].isdisjoint(window)],
                key=lambda r: (-r.capacity, _room_priority(r, preferred, fallback)),
            )

        candidates = _pick(span)
        if not candidates and span is not occupied:
            span = occupied
            candidates = _pick(span)

        if not candidates:
            results.append(PlacedSessionWithRoom(**placement.__dict__, room_id=None, room_label=None))
            continue

        chosen = candidates[0]
        room_schedule[chosen.id].update(span)
        if run_id is not None and span is not occupied:
            run_room[run_id] = chosen

        if same_room and st_value == "CM" and not is_eval:
            course_cm_room[course_code] = chosen.id

        results.append(_with_room(placement, chosen))

    return results


def find_room_for_slot(
    session: object,
    week: int,
    day: int,
    slot: int,
    timetable: list[PlacedSession],
    sessions_by_id: dict[str, object],
    rooms: list[Room],
    groups: list[Group],
    rules: list[RoomAssignmentRule],
    prefer_room_id: str | None = None,
) -> Room | None:
    """
    Trouve une salle libre et adaptée pour CETTE séance à UN (semaine, jour,
    créneau) donné — même logique de priorité que `assign_rooms` (type de
    salle préféré/fallback, capacité vs effectif), mais pour une requête
    ponctuelle (déplacement manuel) plutôt qu'un placement par lot.

    Retour utilisateur : "si on modifie [un créneau] il faut recalculer
    [la salle]" — un déplacement ne doit pas être bloqué juste parce que la
    salle D'ORIGINE n'est plus libre au nouveau créneau, si une autre salle
    adaptée l'est. `prefer_room_id`, si libre à ce créneau, est retenue
    directement (évite un changement de salle inutile quand l'ancienne
    convient encore) ; sinon, retombe sur la recherche par priorité.
    """
    from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

    slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
    duration = max(1, getattr(session, "duration_slots", 1))
    base = week * slots_per_week + day * SLOTS_PER_DAY + slot
    occupied_target = set(range(base, base + duration))

    room_schedule: dict[str, set[int]] = {r.id: set() for r in rooms}
    for p in timetable:
        if p.session_id == session.id:
            continue
        room_id = getattr(p, "room_id", None)
        if not room_id or room_id not in room_schedule:
            continue
        other = sessions_by_id.get(p.session_id)
        other_duration = max(1, getattr(other, "duration_slots", 1)) if other else 1
        p_base = p.week * slots_per_week + p.day * SLOTS_PER_DAY + p.slot
        room_schedule[room_id].update(range(p_base, p_base + other_duration))

    if prefer_room_id and prefer_room_id in room_schedule and room_schedule[prefer_room_id].isdisjoint(occupied_target):
        preferred_room = next((r for r in rooms if r.id == prefer_room_id), None)
        if preferred_room is not None:
            return preferred_room

    course_code = session.course_code
    session_type = getattr(session, "session_type", None)
    st_value = session_type.value if session_type else "TP"
    is_eval = bool(getattr(session, "is_eval", False))
    needed = _headcount_for_groups(getattr(session, "group_ids", []), groups)

    rule = _find_matching_rule(rules, course_code, st_value, is_eval)
    preferred = rule.preferred_room_types if rule else [RoomType.STANDARD]
    fallback = rule.fallback_room_types if rule else [RoomType.STANDARD, RoomType.AMPHI]
    reserve_amphi = st_value != "CM"

    candidates = sorted(
        [
            r for r in rooms
            if r.capacity >= needed
            and room_schedule[r.id].isdisjoint(occupied_target)
            and not (reserve_amphi and r.room_type == RoomType.AMPHI)
        ],
        key=lambda r: _room_priority(r, preferred, fallback),
    )
    if not candidates:
        candidates = sorted(
            [r for r in rooms if room_schedule[r.id].isdisjoint(occupied_target)],
            key=lambda r: (-r.capacity, _room_priority(r, preferred, fallback)),
        )
    return candidates[0] if candidates else None


def _with_room(placement: PlacedSession, room: Room) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=placement.session_id,
        week=placement.week,
        day=placement.day,
        slot=placement.slot,
        course_code=placement.course_code,
        group_ids=placement.group_ids,
        teacher_codes=placement.teacher_codes,
        room_id=room.id,
        room_label=room.label,
    )
