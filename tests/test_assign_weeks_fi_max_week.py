"""
Horizon étendu réservé aux alternants (retour utilisateur, 06/08/2026 :
"j'étends l'horizon... oui mais que les parcours alternance") — cf.
`decomposed.py::assign_weeks`, paramètre `fi_max_week`.
"""

from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import assign_weeks


def _sessions(parcours: str, count: int) -> list[SessionToPlace]:
    return [
        SessionToPlace(
            id=f"S{i}",
            course_code="WRTEST",
            course_name="Test",
            semestre="S5",
            parcours=parcours,
            annee="BUT3",
            session_type=SessionType.TD,
            sequence_order=i,
            group_ids=["g1"],
            teacher_codes=["ZZZ"],
        )
        for i in range(count)
    ]


def test_fi_capped_at_fi_max_week_becomes_infeasible_when_too_many_sessions() -> None:
    """
    20 séances FI, plafond enseignant à 1 créneau/semaine : il faut 20
    semaines distinctes. `fi_max_week=18` ne laisse que 19 semaines (0-18)
    aux parcours FI même si l'horizon global `weeks=24` en propose 24 —
    doit donc échouer.
    """
    sessions = _sessions("BUT3-DEV-FI", 20)
    result = assign_weeks(
        sessions,
        groups=[],
        weeks=24,
        teacher_weekly_cap_slots=1,
        fi_max_week=18,
        time_limit_seconds=10,
    )
    assert result.status not in ("OPTIMAL", "FEASIBLE")


def test_fc_uses_extended_horizon_beyond_fi_max_week() -> None:
    """Les mêmes 20 séances, mais en parcours FC : `fi_max_week` ne les
    concerne pas, les 24 semaines de `weeks` sont utilisables — doit réussir,
    et au moins une séance doit effectivement atterrir après `fi_max_week`."""
    sessions = _sessions("BUT3-DEV-FC", 20)
    result = assign_weeks(
        sessions,
        groups=[],
        weeks=24,
        teacher_weekly_cap_slots=1,
        fi_max_week=18,
        time_limit_seconds=10,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert max(result.week_by_session.values()) > 18


def test_fc_and_fi_together_only_fi_is_capped() -> None:
    """Mélange réaliste (comme le run Groupe A) : les séances FI restent
    toutes <= fi_max_week, les séances FC peuvent dépasser."""
    fi_sessions = _sessions("BUT3-DEV-FI", 5)
    for s in fi_sessions:
        s.teacher_codes = ["FITEACH"]
        s.teachers = []
    fc_sessions = _sessions("BUT3-DEV-FC", 20)
    for s in fc_sessions:
        s.id = "FC-" + s.id
        s.teacher_codes = ["FCTEACH"]

    result = assign_weeks(
        fi_sessions + fc_sessions,
        groups=[],
        weeks=24,
        teacher_weekly_cap_slots=1,
        fi_max_week=18,
        time_limit_seconds=15,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    fi_ids = {s.id for s in fi_sessions}
    fc_ids = {s.id for s in fc_sessions}
    assert all(result.week_by_session[i] <= 18 for i in fi_ids)
    assert max(result.week_by_session[i] for i in fc_ids) > 18
