"""Tests solveur, salles et qualité."""

import json
from pathlib import Path

import pytest

from cal_iut.ingestion.config_loader import (
    load_groups,
    load_room_assignment_rules,
    load_rooms,
    load_teacher_duos,
)
from cal_iut.ingestion.merge import merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver
from cal_iut.solver.quality import compute_quality
from cal_iut.solver.rooms import assign_rooms, parse_room_rules

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "exports"
CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


@pytest.fixture(scope="module")
def but1_s1_sessions() -> list[SessionToPlace]:
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    courses = merge_exports(maquette, progression)
    groups = load_groups(CONFIG)
    raw = expand_all_sessions(courses, groups, parcours="BUT1", semestre="S1")
    return raw


def test_solve_wr108_with_gaps(but1_s1_sessions: list[SessionToPlace]) -> None:
    sessions = [s for s in but1_s1_sessions if s.course_code == "WR108"]
    solver = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=True,
            time_limit_seconds=60,
            enforce_sae_windows=False,
            optimize_spread=False,
            enforce_student_cohort=False,
        )
    )
    result = solver.solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.placements) == len(sessions)


def test_solve_but1_s1_fast(but1_s1_sessions: list[SessionToPlace]) -> None:
    solver = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=False,
            enforce_ordonnancement=False,
            time_limit_seconds=120,
            enforce_sae_windows=False,
            enforce_sae_sanctuarization=False,
            optimize_midday_fill=False,
            optimize_eval_clustering=False,
            optimize_spread=True,
            spread_weight=1,
            enforce_student_cohort=False,
        )
    )
    result = solver.solve(but1_s1_sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    # Les séances WS/WSA (SAE) ne sont plus planifiées par l'algorithme
    # (retour utilisateur : définies par les enseignants eux-mêmes) — seules
    # les séances classiques doivent apparaître dans le résultat.
    classic_sessions = [s for s in but1_s1_sessions if not s.course_code.upper().startswith("WS")]
    assert len(result.placements) == len(classic_sessions)
    assert all(not p.course_code.upper().startswith("WS") for p in result.placements)


def test_room_assignment(but1_s1_sessions: list[SessionToPlace]) -> None:
    sessions = [s for s in but1_s1_sessions if s.course_code == "WR108"]
    solver = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=False,
            enforce_sae_windows=False,
            optimize_spread=False,
            enforce_student_cohort=False,
        )
    )
    result = solver.solve(sessions)
    sessions_by_id = {s.id: s for s in sessions}
    groups = load_groups(CONFIG)
    rooms = load_rooms(CONFIG)
    rules = parse_room_rules(load_room_assignment_rules(CONFIG))
    assigned = assign_rooms(result.placements, sessions_by_id, rooms, groups, rules)
    with_room = [p for p in assigned if p.room_id]
    assert len(with_room) == len(assigned)


def test_assign_rooms_same_room_cache_does_not_double_book() -> None:
    """
    Bug réel corrigé (06/08/2026, trouvé en vérifiant le run Groupe A après
    les correctifs du jour) : la branche `same_room_for_course` (CM)
    affectait la salle en cache SANS jamais vérifier ni mettre à jour
    `room_schedule` — un second cours (parcours différent) pouvait
    légitimement récupérer la MÊME salle unique au MÊME créneau via le
    chemin normal, créant un vrai double-booking physique (amphi H.018
    partagé par un CM BUT1 et un CM BUT2-DEV-FI simultanés sur le run réel).
    """
    from cal_iut.models.entities import Group, Room, RoomType
    from cal_iut.solver.cpsat import PlacedSession
    from cal_iut.solver.rooms import RoomAssignmentRule

    rooms = [
        Room(id="amphi", label="Amphi", capacity=150, room_type=RoomType.AMPHI),
        Room(id="std1", label="Standard", capacity=40, room_type=RoomType.STANDARD),
    ]
    rules = [
        RoomAssignmentRule(
            session_types=["CM"],
            course_code_patterns=["*"],
            preferred_room_types=[RoomType.AMPHI],
            fallback_room_types=[RoomType.STANDARD],
            same_room_for_course=True,
        )
    ]
    groups = [Group(id="promoA", label="Promo A", parcours="X", annee="1", kind="promo", headcount=30)]

    def _cm(sid: str, code: str, parcours: str) -> SessionToPlace:
        return SessionToPlace(
            id=sid, course_code=code, course_name=code, semestre="S1", parcours=parcours,
            annee="1", session_type="CM", group_ids=["promoA"], teacher_codes=["T"],
        )

    sessions_by_id = {
        s.id: s for s in (_cm("A-CM-0", "CRSA", "X"), _cm("A-CM-1", "CRSA", "X"), _cm("B-CM-0", "CRSB", "Y"))
    }
    placements = [
        PlacedSession(session_id="A-CM-0", week=0, day=0, slot=0, course_code="CRSA", group_ids=["promoA"], teacher_codes=["T"]),
        # Même créneau que B-CM-0 : A-CM-1 passe par le cache "même salle que le 1er CM de CRSA".
        PlacedSession(session_id="A-CM-1", week=1, day=0, slot=0, course_code="CRSA", group_ids=["promoA"], teacher_codes=["T"]),
        PlacedSession(session_id="B-CM-0", week=1, day=0, slot=0, course_code="CRSB", group_ids=["promoA"], teacher_codes=["T"]),
    ]

    result = assign_rooms(placements, sessions_by_id, rooms, groups, rules)
    by_id = {p.session_id: p for p in result}
    assert by_id["A-CM-1"].room_id is not None
    assert by_id["B-CM-0"].room_id is not None
    assert by_id["A-CM-1"].room_id != by_id["B-CM-0"].room_id


def test_assign_rooms_picks_smallest_fitting_room() -> None:
    """
    "Best fit" (retour utilisateur 07/08/2026 : "pour les 3e année dev FC il
    faut les mettre dans la H.005 le plus souvent possible ou les petites
    salles car c'est uniquement un groupe de 8") — à type de salle égal, la
    plus PETITE salle qui convient encore l'emporte, au lieu de l'ordre de
    déclaration de `rooms.yaml`.
    """
    from cal_iut.models.entities import Group, Room, RoomType
    from cal_iut.solver.cpsat import PlacedSession
    from cal_iut.solver.rooms import RoomAssignmentRule

    rooms = [
        Room(id="grande", label="Grande", capacity=30, room_type=RoomType.TP_STANDARD),
        Room(id="petite", label="Petite", capacity=15, room_type=RoomType.TP_STANDARD),
    ]
    rules = [
        RoomAssignmentRule(
            session_types=["TD"], course_code_patterns=["*"],
            preferred_room_types=[RoomType.TP_STANDARD], fallback_room_types=[],
        )
    ]
    groups = [Group(id="petit", label="Petit", parcours="X", annee="3", kind="td", headcount=8)]
    session = SessionToPlace(
        id="S1", course_code="C", course_name="C", semestre="S5", parcours="X", annee="3",
        session_type="TD", group_ids=["petit"], teacher_codes=["T"],
    )
    placement = PlacedSession(
        session_id="S1", week=0, day=0, slot=0, course_code="C",
        group_ids=["petit"], teacher_codes=["T"],
    )

    assigned = assign_rooms([placement], {"S1": session}, rooms, groups, rules)
    assert assigned[0].room_id == "petite"


def test_assign_rooms_keeps_same_room_across_consecutive_slots() -> None:
    """
    Retour utilisateur (08/08/2026) : "c'est la même matière et le même prof à
    chaque heure consécutive, il faudrait donc que ce soit dans la même salle
    et qu'il n'y ait pas de changement" (constaté sur WRA507D/BTO réparti sur
    H.007, H.201 puis H.008 d'affilée). Une salle concurrente est ici LIBRE et
    tout aussi bien classée : sans réservation de la série entière, rien
    n'empêchait le solveur de changer de salle d'un créneau à l'autre.
    """
    from cal_iut.models.entities import Group, Room, RoomType
    from cal_iut.solver.cpsat import PlacedSession
    from cal_iut.solver.rooms import RoomAssignmentRule

    rooms = [
        Room(id="r1", label="R1", capacity=30, room_type=RoomType.STANDARD),
        Room(id="r2", label="R2", capacity=30, room_type=RoomType.STANDARD),
        Room(id="r3", label="R3", capacity=30, room_type=RoomType.STANDARD),
    ]
    rules = [
        RoomAssignmentRule(
            session_types=["TD"], course_code_patterns=["*"],
            preferred_room_types=[RoomType.STANDARD], fallback_room_types=[],
        )
    ]
    groups = [Group(id="g1", label="G1", parcours="X", annee="3", kind="td", headcount=20)]

    def _s(sid: str) -> SessionToPlace:
        return SessionToPlace(
            id=sid, course_code="WRA507D", course_name="C", semestre="S5", parcours="X",
            annee="3", session_type="TD", group_ids=["g1"], teacher_codes=["BTO"],
        )

    sessions = {f"S{i}": _s(f"S{i}") for i in range(3)}
    placements = [
        PlacedSession(
            session_id=f"S{i}", week=0, day=0, slot=i, course_code="WRA507D",
            group_ids=["g1"], teacher_codes=["BTO"],
        )
        for i in range(3)
    ]

    assigned = assign_rooms(placements, sessions, rooms, groups, rules)
    used = {p.room_id for p in assigned}
    assert len(used) == 1, f"la série consécutive doit tenir dans une seule salle, trouvé {used}"


def test_assign_rooms_consecutive_run_never_double_books() -> None:
    """La réservation de série ne doit jamais primer sur la disponibilité :
    si l'unique salle est déjà prise au 2e créneau, la série se scinde plutôt
    que de créer un double-booking."""
    from cal_iut.models.entities import Group, Room, RoomType
    from cal_iut.solver.cpsat import PlacedSession
    from cal_iut.solver.rooms import RoomAssignmentRule

    rooms = [
        Room(id="r1", label="R1", capacity=30, room_type=RoomType.STANDARD),
        Room(id="r2", label="R2", capacity=30, room_type=RoomType.STANDARD),
    ]
    rules = [
        RoomAssignmentRule(
            session_types=["TD"], course_code_patterns=["*"],
            preferred_room_types=[RoomType.STANDARD], fallback_room_types=[],
        )
    ]
    groups = [
        Group(id="g1", label="G1", parcours="X", annee="3", kind="td", headcount=20),
        Group(id="g2", label="G2", parcours="Y", annee="3", kind="td", headcount=20),
    ]

    def _s(sid: str, code: str, gid: str) -> SessionToPlace:
        return SessionToPlace(
            id=sid, course_code=code, course_name=code, semestre="S5", parcours="X",
            annee="3", session_type="TD", group_ids=[gid], teacher_codes=["T" + gid],
        )

    sessions = {
        "A0": _s("A0", "CA", "g1"), "A1": _s("A1", "CA", "g1"),
        "B0": _s("B0", "CB", "g2"), "B1": _s("B1", "CB", "g2"),
        "C1": _s("C1", "CC", "g2"),
    }
    placements = [
        PlacedSession(session_id="A0", week=0, day=0, slot=0, course_code="CA", group_ids=["g1"], teacher_codes=["Tg1"]),
        PlacedSession(session_id="A1", week=0, day=0, slot=1, course_code="CA", group_ids=["g1"], teacher_codes=["Tg1"]),
        PlacedSession(session_id="B0", week=0, day=0, slot=0, course_code="CB", group_ids=["g2"], teacher_codes=["Tg2"]),
        PlacedSession(session_id="B1", week=0, day=0, slot=1, course_code="CB", group_ids=["g2"], teacher_codes=["Tg2"]),
    ]

    assigned = assign_rooms(placements, sessions, rooms, groups, rules)
    seen: dict[tuple, str] = {}
    for p in assigned:
        assert p.room_id is not None
        key = (p.room_id, p.week, p.day, p.slot)
        assert key not in seen, f"double-booking sur {key}"
        seen[key] = p.session_id


def test_assign_rooms_skips_too_small_room() -> None:
    """Le best-fit ne doit jamais sacrifier la capacité : un groupe de 20 ne
    tient pas dans la salle de 15, il prend la grande."""
    from cal_iut.models.entities import Group, Room, RoomType
    from cal_iut.solver.cpsat import PlacedSession
    from cal_iut.solver.rooms import RoomAssignmentRule

    rooms = [
        Room(id="grande", label="Grande", capacity=30, room_type=RoomType.TP_STANDARD),
        Room(id="petite", label="Petite", capacity=15, room_type=RoomType.TP_STANDARD),
    ]
    rules = [
        RoomAssignmentRule(
            session_types=["TD"], course_code_patterns=["*"],
            preferred_room_types=[RoomType.TP_STANDARD], fallback_room_types=[],
        )
    ]
    groups = [Group(id="gros", label="Gros", parcours="X", annee="3", kind="td", headcount=20)]
    session = SessionToPlace(
        id="S1", course_code="C", course_name="C", semestre="S5", parcours="X", annee="3",
        session_type="TD", group_ids=["gros"], teacher_codes=["T"],
    )
    placement = PlacedSession(
        session_id="S1", week=0, day=0, slot=0, course_code="C",
        group_ids=["gros"], teacher_codes=["T"],
    )

    assigned = assign_rooms([placement], {"S1": session}, rooms, groups, rules)
    assert assigned[0].room_id == "grande"


def test_eval_session_forced_into_a018(but1_s1_sessions: list[SessionToPlace]) -> None:
    """Toute séance is_eval doit être affectée à la salle A.018, quel que soit le module."""
    eval_sessions = [s for s in but1_s1_sessions if s.is_eval]
    assert eval_sessions, "le jeu de données réel doit contenir au moins une éval"

    non_eval_sample = [
        s for s in but1_s1_sessions if s.course_code == "WR108" and not s.is_eval
    ][:6]
    sessions = eval_sessions[:4] + non_eval_sample

    solver = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=False,
            enforce_sae_windows=False,
            enforce_sae_sanctuarization=False,
            optimize_spread=False,
            optimize_midday_fill=False,
            optimize_eval_clustering=False,
            enforce_student_cohort=False,
        )
    )
    result = solver.solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    sessions_by_id = {s.id: s for s in sessions}
    groups = load_groups(CONFIG)
    rooms = load_rooms(CONFIG)
    rules = parse_room_rules(load_room_assignment_rules(CONFIG))
    assigned = assign_rooms(result.placements, sessions_by_id, rooms, groups, rules)

    for p in assigned:
        if sessions_by_id[p.session_id].is_eval:
            assert p.room_label == "A.018 (Évaluation)"


def test_solve_decomposed_on_real_subset(but1_s1_sessions: list[SessionToPlace]) -> None:
    """
    Solveur décomposé (ordre -> semaine -> jour/créneau, cf. docs/DATA.md
    §14) : sur un sous-ensemble réel incluant le duo WR110, doit converger
    bien plus vite que le modèle joint et respecter les mêmes règles dures
    (toutes les séances placées, pas de dépassement de plafond hebdo).
    """
    sessions = [s for s in but1_s1_sessions if s.course_code in {"WR108", "WR109", "WR110"}]
    groups = load_groups(CONFIG)
    duos = load_teacher_duos(CONFIG)

    solver = TimetableSolver(SolverConfig(enforce_sae_windows=False, enforce_sae_sanctuarization=False))
    result = solver.solve_decomposed(sessions, groups=groups, semestre="S1", duos=duos)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.placements) == len(sessions)

    # aucun chevauchement enseignant/cohorte dans le résultat assemblé
    by_time_teacher: dict[tuple[int, int, int, str], list[str]] = {}
    for p in result.placements:
        for tc in p.teacher_codes:
            key = (p.week, p.day, p.slot, tc)
            by_time_teacher.setdefault(key, []).append(p.session_id)
    conflicts = {k: v for k, v in by_time_teacher.items() if len(v) > 1}
    assert conflicts == {}, f"Conflits enseignant: {conflicts}"


def test_wr110_duo_synchronized_rare_room(but1_s1_sessions: list[SessionToPlace]) -> None:
    """
    Duo confirmé (data/config/teacher_duos.yaml) : KBR+KNG et FLI+VBU doivent
    co-animer leurs TP en simultané (même instant, appariés par groupe), sans
    jamais se chevaucher entre les deux duos ; H.017/H.022 affectées en
    conséquence par `assign_rooms`.
    """
    sessions = [s for s in but1_s1_sessions if s.course_code == "WR110"]
    groups = load_groups(CONFIG)
    duos = load_teacher_duos(CONFIG)
    assert duos, "data/config/teacher_duos.yaml doit déclarer au moins un duo"

    solver = TimetableSolver(
        SolverConfig(
            time_limit_seconds=90,
            optimize_gaps=False,
            enforce_sae_windows=False,
            enforce_sae_sanctuarization=False,
        )
    )
    result = solver.solve_tiered(sessions, groups=groups, semestre="S1", duos=duos)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.placements) == len(sessions)

    sessions_by_id = {s.id: s for s in sessions}
    t_of = {p.session_id: p.week * 30 + p.day * 6 + p.slot for p in result.placements}

    def tp_times(teacher: str) -> dict[int, list[int]]:
        by_order: dict[int, list[int]] = {}
        for s in sessions:
            if s.session_type.value != "TP" or teacher not in s.teacher_codes:
                continue
            by_order.setdefault(s.sequence_order or 0, []).append(t_of[s.id])
        return {order: sorted(times) for order, times in by_order.items()}

    kbr, kng = tp_times("KBR"), tp_times("KNG")
    fli, vbu = tp_times("FLI"), tp_times("VBU")
    assert kbr and kbr == kng, "KBR et KNG doivent être synchronisés (mêmes instants triés par groupe)"
    assert fli and fli == vbu, "FLI et VBU doivent être synchronisés (mêmes instants triés par groupe)"

    duo1_times = {t for times in kbr.values() for t in times}
    duo2_times = {t for times in fli.values() for t in times}
    assert not duo1_times & duo2_times, "les deux duos ne doivent jamais coïncider (une seule paire de salles rare)"

    rooms = load_rooms(CONFIG)
    rules = parse_room_rules(load_room_assignment_rules(CONFIG))
    with_rooms = assign_rooms(result.placements, sessions_by_id, rooms, groups, rules, duos)
    room_by_sid = {p.session_id: p.room_label for p in with_rooms}
    for s in sessions:
        if s.session_type.value != "TP":
            continue
        if "KBR" in s.teacher_codes or "FLI" in s.teacher_codes:
            assert room_by_sid[s.id] == "H.017 (Studio)"
        elif "KNG" in s.teacher_codes or "VBU" in s.teacher_codes:
            assert room_by_sid[s.id] == "H.022 (fantôme Studio)"


def test_solve_tiered_locks_priorities_in_order(
    but1_s1_sessions: list[SessionToPlace],
) -> None:
    """
    `solve_tiered` : ordonnancement (palier 1) puis densification (palier 2)
    puis confort (palier 3), chacun verrouillé avant le suivant. WR108/WR109
    ont une relation `before` réelle (cf. docs/DATA.md) donc le palier
    ordonnancement doit apparaître dans `tier_values`.
    """
    sessions = [s for s in but1_s1_sessions if s.course_code in {"WR108", "WR109"}]
    groups = load_groups(CONFIG)
    solver = TimetableSolver(
        SolverConfig(
            time_limit_seconds=60,
            optimize_gaps=False,
            enforce_sae_windows=False,
            enforce_sae_sanctuarization=False,
        )
    )
    result = solver.solve_tiered(sessions, groups=groups, semestre="S1")
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.placements) == len(sessions)
    assert result.tier_values is not None
    assert "ordonnancement" in result.tier_values
    assert "frontload" in result.tier_values


def test_but1_s1_placements_stay_before_february_2027(
    but1_s1_sessions: list[SessionToPlace],
) -> None:
    """
    Horizon calé sur le calendrier réel (cf. `default_horizon_weeks`) : aucune
    séance S1 ne doit être placée à une date >= 1er février 2027 (démarrage
    visé de S2). `weeks` n'est volontairement pas fourni ici pour exercer le
    calcul automatique, pas une valeur codée en dur dans le test.
    """
    from datetime import date

    from cal_iut.calendar.academic import build_default_calendar_2026_2027

    sessions = [s for s in but1_s1_sessions if s.course_code == "WR108"]
    solver = TimetableSolver(
        SolverConfig(
            optimize_gaps=False,
            enforce_sae_windows=False,
            optimize_spread=False,
            enforce_student_cohort=False,
        )
    )
    result = solver.solve(sessions, semestre="S1")
    assert result.status in ("OPTIMAL", "FEASIBLE")

    calendar = build_default_calendar_2026_2027()
    limit = date(2027, 2, 1)
    for p in result.placements:
        placed_date = calendar.week_day_to_date(p.week, p.day)
        assert placed_date is not None, f"{p.session_id}: semaine {p.week} hors calendrier"
        assert placed_date < limit, f"{p.session_id} placé le {placed_date} (>= 1er février 2027)"


def test_quality_metrics(but1_s1_sessions: list[SessionToPlace]) -> None:
    sessions = but1_s1_sessions[:80]
    solver = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=False,
            enforce_sae_windows=False,
            optimize_spread=False,
            enforce_student_cohort=False,
        )
    )
    result = solver.solve(sessions)
    sessions_by_id = {s.id: s for s in sessions}
    report = compute_quality(result.placements, sessions_by_id)
    assert report.total_gaps >= 0
    assert isinstance(report.gaps_by_group, dict)
