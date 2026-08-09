"""
Bug réel corrigé (07/08/2026, retour utilisateur : "pourquoi pour les S5 FC
créa et com la semaine 16 est une semaine de cours ?") — `_rebalance_failed_weeks`
pouvait déplacer une séance FC vers une semaine où les alternants ne sont
pas physiquement à l'IUT (une semaine "hors présence" est toujours vide,
donc maximalement attractive pour son critère `fits()` de plafond
enseignant/cohorte, qui ne vérifiait aucune présence). Cf. decomposed.py.
"""

from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import _rebalance_failed_weeks


def _session(sid: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code="CRSFC",
        course_name="Cours FC",
        semestre="S5",
        parcours="TEST-FC",
        annee="BUT3",
        session_type=SessionType.TD,
        group_ids=["g1"],
        teacher_codes=["T1"],
    )


def test_rebalance_never_moves_fc_session_into_a_non_presence_week() -> None:
    s1, s2 = _session("S1"), _session("S2")
    # Semaine 0 en échec (plafond enseignant à 1/semaine, 2 séances dessus) :
    # une des deux doit bouger. Semaine 1 est la plus proche (donc la
    # candidate naturelle sans le correctif) mais n'est PAS une semaine de
    # présence pour TEST-FC — seules 0 et 2 le sont.
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
        allowed_weeks_by_parcours={"TEST-FC": {0, 2}},
    )

    assert touched  # un déplacement a bien eu lieu
    weeks_used = {week_by_session["S1"], week_by_session["S2"]}
    assert 1 not in weeks_used, "ne doit jamais utiliser une semaine hors présence FC"
    assert weeks_used == {0, 2}


def test_rebalance_without_presence_data_is_unaffected() -> None:
    """`allowed_weeks_by_parcours=None` (comportement historique, ex. parcours
    FI ou run sans données de présence) : aucune restriction supplémentaire."""
    s1, s2 = _session("S1"), _session("S2")
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
        allowed_weeks_by_parcours=None,
    )
    assert touched
    weeks_used = {week_by_session["S1"], week_by_session["S2"]}
    assert 1 in weeks_used  # la semaine la plus proche, sans restriction
