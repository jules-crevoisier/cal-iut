"""Tests des règles §2/§3 du cahier des charges : plafond horaire hebdo,
verrou PAC du jeudi après-midi, zones à éviter (lundi 8h / vendredi 17h)."""

from __future__ import annotations

from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import WeekDay
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver


def _td_session(
    idx: int,
    *,
    parcours: str = "TEST-FI",
    group_id: str = "g-tp",
    teacher: str = "T1",
    course_code: str = "WRX",
    session_type: SessionType = SessionType.TD,
) -> SessionToPlace:
    return SessionToPlace(
        id=f"s{idx}",
        course_code=course_code,
        course_name="Test",
        semestre="S1",
        parcours=parcours,
        annee="TEST",
        session_type=session_type,
        sequence_order=idx,
        group_ids=[group_id],
        teacher_codes=[teacher],
    )


def _base_config(**overrides) -> SolverConfig:
    defaults = dict(
        weeks=1,
        optimize_gaps=False,
        optimize_spread=False,
        optimize_avoid_zones=False,
        optimize_midday_fill=False,
        optimize_eval_clustering=False,
        enforce_sae_windows=False,
        enforce_sae_sanctuarization=False,
        enforce_ordonnancement=False,
        enforce_calendar=False,
        enforce_weekly_hour_cap=False,
        enforce_thursday_pac_lock=False,
        enforce_s1_integration_week_lock=False,
        # Comme les 2 lignes SAE ci-dessus : évite qu'un test isolé sur une
        # contrainte précise (sessions synthétiques "WRX") soit
        # silencieusement affecté par les VRAIES données de planning S1
        # auto-chargées par défaut (cf. `add_planning_event_block_constraints`,
        # régression trouvée sur `test_thursday_afternoon_locked_for_fi` :
        # un créneau réel bloqué en semaine 0/1 suffisait à faire passer un
        # test à la limite de capacité en INFEASIBLE).
        enforce_planning_events=False,
        time_limit_seconds=20,
    )
    defaults.update(overrides)
    return SolverConfig(**defaults)


def test_weekly_hour_cap_blocks_23rd_fi_session() -> None:
    """
    FI : 33h/semaine = 22 créneaux max, un 23e doit être infaisable.

    Un relevé GLOBAL à 23 a été essayé le 14/08/2026 (autorisation de
    Kyllian Bresson pour débloquer un cas réel, WR106) puis ANNULÉ le même
    jour : mesuré sur un run complet réel que le relevé global pousse
    l'étage 2 à exploiter la marge PARTOUT (61 paires cohorte/semaine
    poussées à la nouvelle limite au lieu de 14), dégradant la fiabilité du
    run entier au lieu de la seule semaine visée. Remplacé par une
    dérogation CIBLÉE (`WeeklyCapException`, `cap_exceptions`, testée dans
    `test_weekly_cap_exceptions.py`) — la valeur par défaut reste 22. Cf.
    docs/DATA.md §61.1/§62.
    """
    groups = [Group(id="g-tp", label="TP", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20)]
    sessions = [_td_session(i) for i in range(23)]

    result = TimetableSolver(_base_config(enforce_weekly_hour_cap=True)).solve(sessions, groups=groups)
    assert result.status == "INFEASIBLE"


def test_weekly_hour_cap_allows_22_fi_sessions() -> None:
    groups = [Group(id="g-tp", label="TP", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20)]
    sessions = [_td_session(i) for i in range(22)]

    result = TimetableSolver(_base_config(enforce_weekly_hour_cap=True)).solve(sessions, groups=groups)
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_weekly_hour_cap_relaxed_for_fc() -> None:
    """FC : plafond à 23 créneaux (~35h) au lieu de 22 pour la FI."""
    groups = [Group(id="g-tp-fc", label="TP FC", parcours="TEST-FC", annee="TEST", kind="tp", headcount=15)]
    sessions = [_td_session(i, parcours="TEST-FC", group_id="g-tp-fc") for i in range(23)]

    result = TimetableSolver(_base_config(enforce_weekly_hour_cap=True)).solve(sessions, groups=groups)
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_thursday_afternoon_locked_for_fi() -> None:
    """27 séances (1 même prof) tiennent dans les 27 créneaux non-jeudi-après-midi d'une semaine."""
    sessions = [_td_session(i, group_id=f"g{i}") for i in range(27)]

    result = TimetableSolver(_base_config(enforce_thursday_pac_lock=True)).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    for p in result.placements:
        assert not (p.day == WeekDay.THURSDAY and p.slot in (3, 4, 5))


def test_thursday_afternoon_lock_infeasible_on_28th_fi_session() -> None:
    sessions = [_td_session(i, group_id=f"g{i}") for i in range(28)]

    result = TimetableSolver(_base_config(enforce_thursday_pac_lock=True)).solve(sessions)
    assert result.status == "INFEASIBLE"


def test_thursday_afternoon_not_locked_for_fc() -> None:
    """Les alternants (FC) peuvent avoir cours le jeudi après-midi."""
    sessions = [_td_session(i, parcours="TEST-FC", group_id=f"g{i}") for i in range(28)]

    result = TimetableSolver(_base_config(enforce_thursday_pac_lock=True)).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_avoid_zone_soft_penalty_prefers_other_slots() -> None:
    """Lundi 8h et vendredi 17h : dernier recours, évités dès qu'une alternative existe."""
    sessions = [_td_session(0, group_id="g0")]

    result = TimetableSolver(_base_config(optimize_avoid_zones=True, avoid_zone_weight=15)).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    p = result.placements[0]
    assert not (p.day == WeekDay.MONDAY and p.slot == 0)
    assert not (p.day == WeekDay.FRIDAY and p.slot == 5)


def test_midday_fill_prefers_slots_near_lunch_break() -> None:
    """Remplissage : les créneaux 11h-12h30 / 14h-15h30 (collés à la pause) sont préférés."""
    sessions = [_td_session(0, group_id="g0")]

    result = TimetableSolver(_base_config(optimize_midday_fill=True, midday_fill_weight=8)).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.placements[0].slot in (2, 3)


def test_s1_integration_week_forbidden_real_courses_start_week_index_1() -> None:
    """Semaine d'intégration BUT1 (semaine-index 0 pour S1) : aucune séance classique."""
    sessions = [_td_session(0, group_id="g0")]  # semestre="S1" par défaut

    result = TimetableSolver(
        _base_config(weeks=2, enforce_s1_integration_week_lock=True)
    ).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.placements[0].week == 1


def test_integration_week_lock_applies_to_all_fi_semestres() -> None:
    """
    Généralisé le 11/08/2026 (retour utilisateur) : le verrou de la semaine
    d'intégration ne concerne plus seulement BUT1/S1 — BUT2-DEV-FI (S3) et
    BUT3-DEV-FI (S5) démarrent aussi en semaine universitaire 3, pas avant.
    """
    sessions = [_td_session(0, group_id="g0", parcours="TEST-FI")]
    sessions[0].semestre = "S3"

    result = TimetableSolver(
        _base_config(weeks=2, enforce_s1_integration_week_lock=True)
    ).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.placements[0].week == 1


def test_integration_week_lock_not_applied_to_fc_parcours() -> None:
    """Les parcours FC démarrent à leur propre date de rentrée (souvent hors
    semaine-index 0) — le tampon "semaine 3" ne les concerne pas, seul le
    blocage exact de leur rentrée s'applique (cf.
    `planning_event_blocked_slots_by_parcours`)."""
    sessions = [_td_session(0, group_id="g0", parcours="TEST-DEV-FC")]
    sessions[0].semestre = "S3"

    result = TimetableSolver(
        _base_config(weeks=2, enforce_s1_integration_week_lock=True)
    ).solve(sessions)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    # Pas de contrainte pour un parcours FC : la semaine 0 reste autorisée.
    assert result.placements[0].week in (0, 1)


def test_sae_sanctuarization_blocks_classic_course_on_sae_day() -> None:
    """Un jour alloué à une SAE interdit tout cours classique ce jour, ce parcours.

    La séance WS999 elle-même n'est plus planifiée par l'algorithme (retour
    utilisateur : une SAE est définie par les enseignants eux-mêmes) — elle
    n'a donc pas de session_starts propre. `sae_blocked_days_by_parcours`
    dérive le blocage par match sur `course_code`, il faut donc bien passer
    une vraie séance WS999 dans le lot d'entrée pour que le mécanisme se
    déclenche (sinon le test est vide de sens, cf. historique de ce fichier).
    """
    sae_days = {"WS999": {(0, 1)}}  # semaine 0, mardi, réservé à la SAE WS999
    sae_session = _td_session(99, group_id="g-promo", course_code="WS999", session_type=SessionType.PTUT)
    classic_sessions = [_td_session(i, group_id=f"g{i}") for i in range(3)]

    result = TimetableSolver(
        _base_config(weeks=1, enforce_sae_sanctuarization=True)
    ).solve(classic_sessions + [sae_session], sae_days_by_course=sae_days)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    placed_ids = {p.session_id for p in result.placements}
    assert sae_session.id not in placed_ids, "la séance WS n'est plus planifiée par l'algorithme"
    assert len(result.placements) == len(classic_sessions)
    for p in result.placements:
        assert not (p.week == 0 and p.day == 1)


def test_ordonnancement_hard_mode_available_when_requested() -> None:
    """Ordonnancement jugé essentiel (retour utilisateur), mais dur PAR DÉFAUT s'est
    révélé infaisable sur données réelles combiné à la sanctuarisation SAE complète
    (cf. docs/DATA.md §11-12) — le mode dur reste disponible via `ordonnancement_hard=True`
    explicite, mais le défaut est une molle à poids élevé (400)."""
    groups = [
        Group(id="promo", label="Promo", parcours="TEST-FI", annee="TEST", kind="promo", headcount=40),
        Group(id="tp-a", label="TP A", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20),
        Group(id="tp-b", label="TP B", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20),
    ]

    def _course_sessions(code: str, group_id: str, ordonnancement=None):
        return [
            SessionToPlace(
                id=f"{code}-{group_id}-{i}", course_code=code, course_name=code, semestre="S1",
                parcours="TEST-FI", annee="TEST", session_type=SessionType.TP, sequence_order=i,
                group_ids=[group_id], teacher_codes=[f"T-{code}-{group_id}"],
                metadata={"ordonnancement": ordonnancement or []},
            )
            for i in range(1, 3)
        ]

    ord_meta = [{"position": "before", "target_course_code": "WRB", "semestre": "S1"}]
    sessions = (
        _course_sessions("WRA", "tp-a", ord_meta)
        + _course_sessions("WRA", "tp-b", ord_meta)
        + _course_sessions("WRB", "tp-a")
        + _course_sessions("WRB", "tp-b")
    )

    result = TimetableSolver(
        _base_config(weeks=8, enforce_ordonnancement=True, ordonnancement_hard=True)
    ).solve(sessions, groups=groups)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    by_id = {p.session_id: p for p in result.placements}
    t = lambda p: p.week * 30 + p.day * 6 + p.slot
    for gid in ("tp-a", "tp-b"):
        mean_a = sum(t(by_id[f"WRA-{gid}-{i}"]) for i in (1, 2)) / 2
        mean_b = sum(t(by_id[f"WRB-{gid}-{i}"]) for i in (1, 2)) / 2
        assert mean_a < mean_b


def test_ordonnancement_default_is_soft_high_weight() -> None:
    """Défaut réel : molle à poids 400 (pas dur) — satisfaite sur un cas simple,
    mais ne bloque jamais le solveur si un vrai conflit existe ailleurs."""
    groups = [
        Group(id="promo", label="Promo", parcours="TEST-FI", annee="TEST", kind="promo", headcount=40),
        Group(id="tp-a", label="TP A", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20),
        Group(id="tp-b", label="TP B", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20),
    ]

    def _course_sessions(code: str, group_id: str, ordonnancement=None):
        return [
            SessionToPlace(
                id=f"{code}-{group_id}-{i}", course_code=code, course_name=code, semestre="S1",
                parcours="TEST-FI", annee="TEST", session_type=SessionType.TP, sequence_order=i,
                group_ids=[group_id], teacher_codes=[f"T-{code}-{group_id}"],
                metadata={"ordonnancement": ordonnancement or []},
            )
            for i in range(1, 3)
        ]

    ord_meta = [{"position": "before", "target_course_code": "WRB", "semestre": "S1"}]
    sessions = (
        _course_sessions("WRA", "tp-a", ord_meta)
        + _course_sessions("WRA", "tp-b", ord_meta)
        + _course_sessions("WRB", "tp-a")
        + _course_sessions("WRB", "tp-b")
    )

    cfg = _base_config(weeks=8, enforce_ordonnancement=True)
    assert cfg.ordonnancement_hard is False
    assert cfg.ordonnancement_weight == 400

    result = TimetableSolver(cfg).solve(sessions, groups=groups)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    by_id = {p.session_id: p for p in result.placements}
    t = lambda p: p.week * 30 + p.day * 6 + p.slot
    for gid in ("tp-a", "tp-b"):
        mean_a = sum(t(by_id[f"WRA-{gid}-{i}"]) for i in (1, 2)) / 2
        mean_b = sum(t(by_id[f"WRB-{gid}-{i}"]) for i in (1, 2)) / 2
        assert mean_a < mean_b


def test_pedagogical_sequence_promo_eval_waits_for_every_group() -> None:
    """Bug corrigé : un CM/éval promo doit suivre le TP de CHAQUE sous-groupe,
    pas seulement les autres séances déjà taguées 'promo'."""
    groups = [
        Group(id="promo", label="Promo", parcours="TEST-FI", annee="TEST", kind="promo", headcount=40),
        Group(id="tp-a", label="TP A", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20),
        Group(id="tp-b", label="TP B", parcours="TEST-FI", annee="TEST", kind="tp", headcount=20),
    ]
    tp_a = SessionToPlace(
        id="tp-a-1", course_code="WRX", course_name="T", semestre="S1", parcours="TEST-FI",
        annee="TEST", session_type=SessionType.TP, sequence_order=1, group_ids=["tp-a"], teacher_codes=["T1"],
    )
    tp_b = SessionToPlace(
        id="tp-b-1", course_code="WRX", course_name="T", semestre="S1", parcours="TEST-FI",
        annee="TEST", session_type=SessionType.TP, sequence_order=1, group_ids=["tp-b"], teacher_codes=["T2"],
    )
    eval_cm = SessionToPlace(
        id="eval", course_code="WRX", course_name="T", semestre="S1", parcours="TEST-FI",
        annee="TEST", session_type=SessionType.CM, sequence_order=2, is_eval=True,
        group_ids=["promo"], teacher_codes=["T3"],
    )

    result = TimetableSolver(_base_config(weeks=4)).solve([tp_a, tp_b, eval_cm], groups=groups)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    by_id = {p.session_id: p for p in result.placements}
    t = lambda p: p.week * 30 + p.day * 6 + p.slot
    assert t(by_id["eval"]) > t(by_id["tp-a-1"])
    assert t(by_id["eval"]) > t(by_id["tp-b-1"])


def test_solve_accepts_warm_start_hints_without_breaking_constraints() -> None:
    """Le warm-start (hints) ne doit jamais casser une contrainte dure ni changer le statut."""
    sessions = [_td_session(i, group_id=f"g{i}") for i in range(5)]

    first = TimetableSolver(_base_config(weeks=4)).solve(sessions)
    assert first.status in ("OPTIMAL", "FEASIBLE")

    slots_per_week = 30
    hints = {p.session_id: p.week * slots_per_week + p.day * 6 + p.slot for p in first.placements}

    second = TimetableSolver(_base_config(weeks=4)).solve(sessions, hints=hints)
    assert second.status in ("OPTIMAL", "FEASIBLE")
    assert len(second.placements) == len(sessions)


def test_eval_clustering_pulls_evals_from_different_courses_into_same_week() -> None:
    """2 évals de cours différents, sans autre contrainte : se retrouvent la même semaine."""
    eval_a = SessionToPlace(
        id="eval-a", course_code="WRA", course_name="A", semestre="S1", parcours="TEST-FI",
        annee="TEST", session_type=SessionType.TD, sequence_order=1, is_eval=True,
        group_ids=["ga"], teacher_codes=["Ta"],
    )
    eval_b = SessionToPlace(
        id="eval-b", course_code="WRB", course_name="B", semestre="S1", parcours="TEST-FI",
        annee="TEST", session_type=SessionType.TD, sequence_order=1, is_eval=True,
        group_ids=["gb"], teacher_codes=["Tb"],
    )

    result = TimetableSolver(
        _base_config(weeks=4, optimize_eval_clustering=True, eval_clustering_weight=30)
    ).solve([eval_a, eval_b])
    assert result.status in ("OPTIMAL", "FEASIBLE")
    by_id = {p.session_id: p for p in result.placements}
    assert by_id["eval-a"].week == by_id["eval-b"].week
