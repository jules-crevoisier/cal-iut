"""Expansion des matières en séances atomiques à placer."""

from cal_iut.models.entities import (
    Course,
    DoubleSessionRule,
    Group,
    SessionType,
    Teacher,
    TeacherBlock,
    TeacherDuo,
)
from cal_iut.models.session import SessionToPlace


def _groups_for_parcours(groups: list[Group], parcours: str) -> list[Group]:
    return [g for g in groups if g.parcours == parcours]


def _td_group_ids(groups: list[Group], parcours: str, count: int) -> list[str]:
    td_groups = [g for g in _groups_for_parcours(groups, parcours) if g.kind == "td"]
    if td_groups:
        return [g.id for g in td_groups[:count]]

    return [f"{parcours.lower()}-td-{i + 1}" for i in range(count)]


def _tp_group_ids(groups: list[Group], parcours: str, count: int) -> list[str]:
    tp_groups = [g for g in _groups_for_parcours(groups, parcours) if g.kind == "tp"]
    if tp_groups:
        return [g.id for g in tp_groups[:count]]

    return [f"{parcours.lower()}-tp-{i + 1}" for i in range(count)]


def _promo_group_id(groups: list[Group], parcours: str) -> str:
    promo = next((g for g in _groups_for_parcours(groups, parcours) if g.kind == "promo"), None)
    if promo:
        return promo.id
    return f"{parcours.lower()}-promo"


# Ordre de passation CONFIRMÉ pour un cours en co-animation séquentielle sur
# groupe unique (cf. `_teacher_for_group` : sinon l'ordre de la maquette
# fait foi, qui ne reflète pas forcément l'ordre pédagogique réel). Donnée
# jamais devinée : WRA505C — retour utilisateur (06/08/2026) : "la
# progression de cette ressource impose de commencer essentiellement avec
# les créneaux d'Ariane Loizon (ALO) au début, pour basculer sur les
# créneaux d'Anthony Froli (AFR) sur la fin du module" — alors que la
# maquette source liste AFR avant ALO (ALO est pourtant le lead).
_KNOWN_TEACHING_ORDER: dict[str, list[str]] = {
    "WRA505C": ["ALO", "AFR"],
}


def _blocks_for_type(course: Course, session_type: SessionType) -> list[TeacherBlock]:
    field = session_type.value.lower()
    blocks = [b for b in course.profs if getattr(b, field, 0) and getattr(b, field, 0) > 0]

    order = _KNOWN_TEACHING_ORDER.get(course.code)
    if order:
        rank = {code: i for i, code in enumerate(order)}
        blocks = sorted(blocks, key=lambda b: rank.get(b.teacher.code, len(order)))

    return blocks


def _teachers_for_type(course: Course, session_type: SessionType) -> list[Teacher]:
    blocks = _blocks_for_type(course, session_type)
    if not blocks:
        return [course.lead]
    return [b.teacher for b in blocks]


def _duo_teacher_for_group(
    course: Course,
    session_type: SessionType,
    group_id: str,
    duos: list[TeacherDuo] | None,
) -> Teacher | None:
    """
    Cf. `TeacherDuo.group_overrides` : force l'affectation groupe -> enseignant
    pour un cours en duo synchronisé, en écrasant le curseur séquentiel par
    défaut (cf. `_teacher_for_group`) qui produirait des épisodes co-animés
    "boiteux" (retour utilisateur, TP WR110). Donnée jamais devinée, déclarée
    explicitement dans `data/config/teacher_duos.yaml`.
    """
    if not duos:
        return None
    for duo in duos:
        if course.code not in duo.course_codes or not duo.group_overrides:
            continue
        if session_type.value not in duo.session_types:
            continue
        for teacher_code, letters in duo.group_overrides.items():
            suffixes = {f"-{session_type.value.lower()}-{str(letter).lower()}" for letter in letters}
            if not any(group_id.lower().endswith(suffix) for suffix in suffixes):
                continue
            for block in course.profs:
                if block.teacher.code == teacher_code:
                    return block.teacher
            if course.lead.code == teacher_code:
                return course.lead
    return None


def _teacher_for_group(
    course: Course,
    session_type: SessionType,
    group_id: str,
    group_ids: list[str],
    duos: list[TeacherDuo] | None = None,
    occurrence_index: int = 0,
) -> Teacher:
    """
    Un enseignant par (groupe, occurrence dans la séquence de CE groupe) —
    ou l'override duo prioritaire, cf. `_duo_teacher_for_group`.

    Répartition par défaut : consomme `block.td`/`block.tp` (nombre RÉEL de
    créneaux que ce bloc délivre, tous groupes confondus — vérifié fiable
    sur les données réelles : la somme des blocs égale toujours
    `volumes[type] × nb_groupes`, contrairement à `nbGpTd`/`nbGpTp` qui peut
    être dégénéré, ex. WS104 où les 3 blocs revendiquent chacun la totalité
    des 4 groupes) dans l'ordre des blocs (cf. `_blocks_for_type` /
    `_KNOWN_TEACHING_ORDER`), en remplissant la grille (groupe, occurrence)
    GROUPE PAR GROUPE COMPLET avant de passer au suivant.

    Ça reproduit exactement l'ancien découpage "1 enseignant = 1
    sous-groupe entier" (ex. WR112 : chaque bloc couvre un multiple entier
    du nombre d'occurrences par groupe) ET couvre nativement le cas
    "groupe unique partagé chronologiquement entre 2 enseignants" (ex.
    WRA505C/506C/508C — retour utilisateur : "17 séances pour ALO et 17
    pour AFR" — bug réel corrigé le 06/08/2026 : l'ancien découpage par
    `nbGpTd`/`nbGpTp` affectait TOUJOURS le premier bloc de la liste à la
    totalité des séances d'un groupe unique, le second enseignant
    n'apparaissait alors JAMAIS dans le planning réel — confirmé sur 10
    cours réels du semestre impair, cf. docs/DATA.md §32).
    """
    override = _duo_teacher_for_group(course, session_type, group_id, duos)
    if override is not None:
        return override

    blocks = _blocks_for_type(course, session_type)
    if not blocks:
        return course.lead

    try:
        group_index = group_ids.index(group_id)
    except ValueError:
        return blocks[0].teacher

    per_group = course.volumes.get(session_type.value.lower(), 0)
    if per_group <= 0:
        return blocks[0].teacher

    flat_index = group_index * int(per_group) + occurrence_index

    cursor = 0
    for block in blocks:
        count = int(round(block.td if session_type == SessionType.TD else block.tp))
        if count <= 0:
            continue
        if flat_index < cursor + count:
            return block.teacher
        cursor += count

    return blocks[-1].teacher


def _teacher_codes(teachers: list[Teacher]) -> list[str]:
    return [t.code for t in teachers]


def _synthetic_sequence(course: Course) -> list[dict[str, object]]:
    """Génère une séquence CM→TD→TP quand progression absente."""
    sequence: list[dict[str, object]] = []
    order = 1
    for _ in range(int(course.volumes.get("cm", 0))):
        sequence.append({"ordre": order, "type": "CM", "eval": False})
        order += 1
    for _ in range(int(course.volumes.get("td", 0))):
        sequence.append({"ordre": order, "type": "TD", "eval": False})
        order += 1
    for _ in range(int(course.volumes.get("tp", 0))):
        sequence.append({"ordre": order, "type": "TP", "eval": False})
        order += 1
    return sequence


def _target_groups(
    course: Course,
    session_type: SessionType,
    groups: list[Group],
) -> list[str]:
    if session_type == SessionType.CM:
        return [_promo_group_id(groups, course.parcours)]

    if session_type == SessionType.TD:
        return _td_group_ids(groups, course.parcours, course.groupes_td)

    return _tp_group_ids(groups, course.parcours, course.groupes_tp)


def _merge_double_sessions(
    sequence: list[dict[str, object]],
    rule: DoubleSessionRule,
) -> list[dict[str, object]]:
    """
    Fusionne par paires consécutives (ordre pédagogique croissant) les
    entrées du type ciblé par `rule`, pour former des blocs de
    `rule.slots_per_session` créneaux collés (ex. 2×1h30 = 1 bloc de 3h).
    L'entrée fusionnée garde l'`ordre` de la première moitié de sa paire et
    gagne un champ `duration_slots` ; les autres types d'entrées ne sont pas
    touchés.

    `rule.pair_from` détermine depuis quelle extrémité les paires sont
    formées — "start" (défaut) apparie (1,2),(3,4)... avec le reliquat impair
    en FIN de liste ; "end" apparie depuis la fin, reliquat en DÉBUT de liste
    (ex. WR106 : CM1/CM2/CM3, seuls CM2+CM3 doivent être collés pour l'éval
    de fin de semestre — CM1 doit rester une séance seule en tête, pas
    fusionnée avec CM2).

    Un reliquat qui ne fait pas un multiple de `slots_per_session` reste en
    séances simples de 1h30 plutôt que d'inventer un créneau supplémentaire
    (règle "donnée fraîche" du projet : on ne fusionne que ce qui colle
    exactement).

    `rule.max_blocks` limite le NOMBRE de blocs formés, les autres séances
    restant simples — ex. WRA308M (Marine Riguet) : 6 TD au total, mais seuls
    "les 3 derniers TD à la suite" doivent former un bloc de 4h30, les TD 1 à 3
    gardant leur format 1h30 (`pair_from: end`, `slots_per_session: 3`,
    `max_blocks: 1`). Sans cette borne, les 6 TD auraient formé 2 blocs de
    4h30, ce que personne n'a demandé.
    """
    target_type = rule.session_type.value
    size = max(1, rule.slots_per_session)
    others = [e for e in sequence if str(e.get("type")) != target_type]
    targets = sorted(
        (e for e in sequence if str(e.get("type")) == target_type),
        key=lambda e: e.get("ordre", 0),
    )

    def _merge_chunk(chunk: list[dict[str, object]]) -> dict[str, object]:
        head = dict(chunk[0])
        head["duration_slots"] = size
        head["eval"] = any(bool(e.get("eval")) for e in chunk)
        return head

    merged: list[dict[str, object]] = []
    blocks_left = rule.max_blocks if rule.max_blocks is not None else len(targets)

    if rule.pair_from == "end":
        # Les blocs se forment depuis la FIN : on ne garde donc que les
        # `blocks_left` derniers groupes de `size` séances, tout ce qui
        # précède restant en séances simples.
        keep = min(blocks_left, len(targets) // size)
        split = len(targets) - keep * size
        merged.extend(targets[:split])
        paired = targets[split:]
        for i in range(0, len(paired), size):
            merged.append(_merge_chunk(paired[i : i + size]))
    else:
        for i in range(0, len(targets), size):
            chunk = targets[i : i + size]
            if len(chunk) < size or blocks_left <= 0:
                merged.extend(chunk)
                continue
            merged.append(_merge_chunk(chunk))
            blocks_left -= 1

    return sorted(others + merged, key=lambda e: e.get("ordre", 0))


def expand_course_to_sessions(
    course: Course,
    groups: list[Group],
    *,
    include_hors_service: bool = False,
    double_session_rules: list[DoubleSessionRule] | None = None,
    duos: list[TeacherDuo] | None = None,
) -> list[SessionToPlace]:
    if course.hors_service and not include_hors_service:
        return []

    sequence = course.seance_sequence if course.progression_defined else _synthetic_sequence(course)
    if not sequence:
        return []

    for rule in double_session_rules or []:
        if rule.course_code == course.code:
            sequence = _merge_double_sessions(sequence, rule)

    td_ids = _td_group_ids(groups, course.parcours, course.groupes_td)
    tp_ids = _tp_group_ids(groups, course.parcours, course.groupes_tp)
    promo_id = _promo_group_id(groups, course.parcours)

    # Cohorte à GROUPE UNIQUE (1 seul TD et 1 seul TP déclarés dans la
    # maquette : BUT2-CREACOM-FC, BUT3-CREACOM-FC, BUT3-DEV-FC) — retour
    # utilisateur (07/08/2026) : "en FC 2e année il faut considérer tous les
    # cours comme des TD car c'est un même groupe, pareil pour les 3e année
    # créacom" (+ confirmé ensuite pour BUT3-DEV-FC : "tout est considéré
    # comme TD mais pour les salles on garde un petit effectif").
    #
    # Le découpage TD/TP n'a aucun sens quand les deux "groupes" sont la même
    # cohorte physique : ça produisait deux entrées distinctes dans
    # l'interface pour les mêmes étudiants, et faisait viser des salles TP
    # alors que le groupe ne se scinde jamais. Les séances TP sont donc
    # émises en TD sur le groupe TD unique. Dérivé de la maquette
    # (`groupes_td == groupes_tp == 1`) plutôt que codé en dur : un parcours
    # qui se scinde réellement (BUT1 4/8, BUT2-DEV-FI 2/4, BUT3-DEV-FI 1/2)
    # n'est jamais concerné.
    #
    # L'affectation d'enseignant reste calculée sur le type d'ORIGINE (les
    # volumes `block.tp` ne sont pas les mêmes que `block.td`, cf.
    # `_teacher_for_group`) : seuls le type émis et le groupe cible changent.
    single_group_cohort = course.groupes_td == 1 and course.groupes_tp == 1 and bool(td_ids)

    sessions: list[SessionToPlace] = []
    counters = {"CM": 0, "TD": 0, "TP": 0, "PTUT": 0}

    for entry in sequence:
        session_type = SessionType(str(entry["type"]))
        counters[session_type.value] += 1
        idx = counters[session_type.value]
        teachers = _teachers_for_type(course, session_type)

        if session_type == SessionType.CM:
            group_targets = [promo_id]
            session_id = f"{course.code}-{course.semestre}-{session_type.value}-{idx}"
            sessions.append(
                SessionToPlace(
                    id=session_id,
                    course_code=course.code,
                    course_name=course.name,
                    semestre=course.semestre,
                    parcours=course.parcours,
                    annee=course.annee,
                    session_type=session_type,
                    sequence_order=int(entry.get("ordre", idx)),
                    is_eval=bool(entry.get("eval")),
                    group_ids=group_targets,
                    teacher_codes=_teacher_codes(teachers),
                    teachers=teachers,
                    duration_slots=int(entry.get("duration_slots", 1)),
                    metadata={
                        "bloque_maquette": course.bloque,
                        "ordonnancement": [o.model_dump() for o in course.ordonnancement],
                        "commentaire_edt": course.commentaire_edt,
                    },
                )
            )
            continue

        target_ids = td_ids if session_type == SessionType.TD else tp_ids
        # cf. `single_group_cohort` : le TP d'une cohorte à groupe unique est
        # émis comme un TD sur le groupe TD unique (mêmes étudiants).
        emit_as_td = single_group_cohort and session_type == SessionType.TP
        emitted_type = SessionType.TD if emit_as_td else session_type
        for group_id in target_ids:
            teacher = _teacher_for_group(course, session_type, group_id, target_ids, duos, occurrence_index=idx - 1)
            # `session_id` garde le type d'origine : il doit rester unique
            # face aux vraies séances TD du même cours et du même index.
            session_id = f"{course.code}-{course.semestre}-{session_type.value}-{idx}-{group_id}"
            emitted_group_id = td_ids[0] if emit_as_td else group_id
            sessions.append(
                SessionToPlace(
                    id=session_id,
                    course_code=course.code,
                    course_name=course.name,
                    semestre=course.semestre,
                    parcours=course.parcours,
                    annee=course.annee,
                    session_type=emitted_type,
                    sequence_order=int(entry.get("ordre", idx)),
                    is_eval=bool(entry.get("eval")),
                    group_ids=[emitted_group_id],
                    teacher_codes=[teacher.code],
                    teachers=[teacher],
                    duration_slots=int(entry.get("duration_slots", 1)),
                    metadata={
                        "bloque_maquette": course.bloque,
                        "ordonnancement": [o.model_dump() for o in course.ordonnancement],
                        "commentaire_edt": course.commentaire_edt,
                    },
                )
            )

    return sessions


def expand_all_sessions(
    courses: list[Course],
    groups: list[Group],
    *,
    parcours: str | None = None,
    semestre: str | None = None,
    include_hors_service: bool = False,
    double_session_rules: list[DoubleSessionRule] | None = None,
    duos: list[TeacherDuo] | None = None,
) -> list[SessionToPlace]:
    sessions: list[SessionToPlace] = []
    for course in courses:
        if parcours and course.parcours != parcours:
            continue
        if semestre and course.semestre != semestre:
            continue
        if course.parcours == "admin":
            continue
        sessions.extend(
            expand_course_to_sessions(
                course,
                groups,
                include_hors_service=include_hors_service,
                double_session_rules=double_session_rules,
                duos=duos,
            )
        )
    return sessions
