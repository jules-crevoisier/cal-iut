"""
Bug réel corrigé (27/08/2026, retour utilisateur : "les FI doivent finir
leur semestre le 1er février") — `assign_weeks` respecte bien `fi_max_week`
pour son affectation initiale, mais `_rebalance_failed_weeks` (le filet de
secours qui déplace une séance strandée dans une semaine PROUVÉE infaisable
par l'étage 3) n'en avait aucune connaissance : une séance FI pouvait être
rééquilibrée vers n'importe quelle semaine libre, y compris au-delà de la
date de fin de semestre. Constaté sur un run réel : 133 séances FI en
semaine 19 (`fi_max_week=18`) après une recherche `solve_until_ok.py
--fi-max-week 18`, alors qu'`assign_weeks` seul n'en avait laissé passer
aucune. Cf. decomposed.py.
"""

from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import _rebalance_failed_weeks


def _session(sid: str, parcours: str = "BUT1") -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code="CRSFI",
        course_name="Cours FI",
        semestre="S1",
        parcours=parcours,
        annee="BUT1",
        session_type=SessionType.TD,
        group_ids=["g1"],
        teacher_codes=["T1"],
    )


def test_rebalance_never_moves_an_fi_session_past_fi_max_week() -> None:
    s1, s2 = _session("S1"), _session("S2")
    # Semaine 0 en échec (plafond enseignant à 1/semaine, 2 séances dessus) :
    # une des deux doit bouger. Semaine 1 est la plus proche (donc la
    # candidate naturelle sans le correctif) mais dépasse `fi_max_week=0` —
    # seule la semaine 2... non plus, elle aussi > fi_max_week. Ici
    # fi_max_week=1 : semaine 1 reste autorisée, semaine 2 ne l'est plus.
    sessions_by_week = {0: [s1, s2], 1: [], 2: []}
    week_by_session = {"S1": 0, "S2": 0}
    session_by_id = {"S1": s1, "S2": s2}
    groups = [Group(id="g1", label="G1", parcours="BUT1", annee="BUT1", kind="td", headcount=10)]

    touched = _rebalance_failed_weeks(
        [0],
        sessions_by_week,
        week_by_session,
        session_by_id,
        weeks=3,
        duos=None,
        cohorts={"g1": {"g1"}},
        group_by_id={"g1": groups[0]},
        teacher_weekly_cap_slots=1,
        fi_cap_slots=30,
        fc_cap_slots=30,
        fi_max_week=1,
    )

    assert touched  # un déplacement a bien eu lieu
    weeks_used = {week_by_session["S1"], week_by_session["S2"]}
    assert 2 not in weeks_used, "ne doit jamais dépasser fi_max_week pour une séance FI"
    assert weeks_used == {0, 1}


def test_rebalance_leaves_fc_sessions_unbounded_by_fi_max_week() -> None:
    """`fi_max_week` ne doit JAMAIS brider un parcours FC — seul le "FC" dans
    `session.parcours` détermine l'exemption, symétrique de `fc_min_week`."""
    s1, s2 = _session("S1", parcours="TEST-FC"), _session("S2", parcours="TEST-FC")
    sessions_by_week = {0: [s1, s2], 1: [], 2: []}
    week_by_session = {"S1": 0, "S2": 0}
    session_by_id = {"S1": s1, "S2": s2}
    groups = [Group(id="g1", label="G1", parcours="TEST-FC", annee="BUT3", kind="td", headcount=10)]

    touched = _rebalance_failed_weeks(
        [0],
        sessions_by_week,
        week_by_session,
        session_by_id,
        weeks=3,
        duos=None,
        cohorts={"g1": {"g1"}},
        group_by_id={"g1": groups[0]},
        teacher_weekly_cap_slots=1,
        fi_cap_slots=30,
        fc_cap_slots=30,
        fi_max_week=0,  # bornerait un FI à la semaine 0 uniquement
    )

    assert touched
    weeks_used = {week_by_session["S1"], week_by_session["S2"]}
    assert 1 in weeks_used, "un parcours FC doit rester libre au-delà de fi_max_week"


def test_rebalance_without_fi_max_week_is_unaffected() -> None:
    """`fi_max_week=None` (comportement historique) : aucune restriction
    supplémentaire, même pour un parcours FI."""
    s1, s2 = _session("S1"), _session("S2")
    sessions_by_week = {0: [s1, s2], 1: [], 2: []}
    week_by_session = {"S1": 0, "S2": 0}
    session_by_id = {"S1": s1, "S2": s2}
    groups = [Group(id="g1", label="G1", parcours="BUT1", annee="BUT1", kind="td", headcount=10)]

    touched = _rebalance_failed_weeks(
        [0],
        sessions_by_week,
        week_by_session,
        session_by_id,
        weeks=3,
        duos=None,
        cohorts={"g1": {"g1"}},
        group_by_id={"g1": groups[0]},
        teacher_weekly_cap_slots=1,
        fi_cap_slots=30,
        fc_cap_slots=30,
        fi_max_week=None,
    )
    assert touched
    weeks_used = {week_by_session["S1"], week_by_session["S2"]}
    assert 1 in weeks_used  # la semaine la plus proche, sans restriction
