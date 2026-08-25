"""
Bug réel du 12/08/2026, retour utilisateur (« ça c'est critique ») : sur un
run FEASIBLE 2389/2389, 10 évaluations se retrouvaient placées AVANT le
dernier contenu de leur cohorte — alors que l'étage 2 (`assign_weeks`)
respecte bien `week_var[dernier_contenu] <= week_var[éval]` comme contrainte
dure. Diagnostiqué avec les données réelles : les 10 violations étaient
TOUTES entre semaines différentes (jamais au sein d'une même semaine, que
l'étage 3 protège déjà via `_add_eval_after_cohort_content_constraints`) —
la garantie de l'étage 2 était donc respectée à sa sortie, puis cassée PAR
`_rebalance_failed_weeks`, qui déplace des séances d'une semaine à l'autre
sans connaître cette relation cohorte↔éval (seul `_movable_bounds`, borné au
même group_id brut, la contredit involontairement dès qu'une éval "promo"
et le dernier contenu d'un TP précis — deux group_id différents — sont
déplacés indépendamment). Cf. docs/DATA.md §60.
"""

from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import _eval_after_content_bounds, _rebalance_failed_weeks


def _session(sid: str, group_id: str, seq: int, is_eval: bool = False) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code="WRTEST",
        course_name="Test",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=seq,
        is_eval=is_eval,
        group_ids=[group_id],
        teacher_codes=["T1"],
    )


def test_eval_after_content_bounds_matches_the_real_bug_pattern() -> None:
    """
    Reproduit exactement le cas réel (WR110/WR301D) : une éval "promo"
    (seq=17) partagée par toute la promo, dont le dernier contenu pertinent
    pour la cohorte TP-A est une séance TP (seq=15, groupe DIFFÉRENT de la
    promo) déjà placée en semaine 13 par l'étage 2, tandis que l'éval,
    elle, est en semaine 12 — VIOLATION (éval avant le contenu). Vérifie que
    `_eval_after_content_bounds` calcule bien `eval_min_week[éval] = 13`
    (pas moins) et `content_max_week[dernier_tp] = 12` (le plafond réel de
    l'éval telle que déjà placée par l'étage 2).
    """
    tp = Group(id="but1-tp-a", label="TP A", parcours="BUT1", annee="BUT1", kind="tp", headcount=15)
    td = Group(id="but1-td-ab", label="TD AB", parcours="BUT1", annee="BUT1", kind="td", headcount=30, tp_groups=["a"])
    promo = Group(id="but1-promo", label="Promo", parcours="BUT1", annee="BUT1", kind="promo", headcount=60)

    content = _session("content", "but1-tp-a", seq=15)
    evaluation = _session("eval", "but1-promo", seq=17, is_eval=True)

    week_by_session = {"content": 13, "eval": 12}  # état (buggé) observé sur le run réel

    eval_min_week, content_max_week = _eval_after_content_bounds(
        [content, evaluation], [tp, td, promo], week_by_session
    )

    assert eval_min_week.get("eval") == 13
    assert content_max_week.get("content") == 12


def test_eval_after_content_bounds_ignores_sessions_without_a_placed_week() -> None:
    """Une séance pas encore placée (absente de `week_by_session`, ex. verrouillée
    ou en cours de rééquilibrage) ne doit jamais produire de borne bidon."""
    tp = Group(id="but1-tp-a", label="TP A", parcours="BUT1", annee="BUT1", kind="tp", headcount=15)
    promo = Group(id="but1-promo", label="Promo", parcours="BUT1", annee="BUT1", kind="promo", headcount=60)

    content = _session("content", "but1-tp-a", seq=15)
    evaluation = _session("eval", "but1-promo", seq=17, is_eval=True)

    eval_min_week, content_max_week = _eval_after_content_bounds([content, evaluation], [tp, promo], {})

    assert "eval" not in eval_min_week
    assert "content" not in content_max_week


def test_rebalance_never_moves_an_eval_before_its_content_lower_bound() -> None:
    """Niveau `_rebalance_failed_weeks` : l'éval (semaine 3 en échec) ne doit
    jamais être rééquilibrée vers une semaine < son `eval_min_week`, même si
    c'est la semaine la plus proche/la moins chargée."""
    evaluation = _session("eval", "g1", seq=17, is_eval=True)
    filler = _session("filler", "g1", seq=1)  # occupe la semaine 3 pour forcer l'échec

    sessions_by_week = {0: [], 1: [], 2: [filler, evaluation], 3: []}
    week_by_session = {"filler": 2, "eval": 2}
    session_by_id = {"filler": filler, "eval": evaluation}
    groups = [Group(id="g1", label="G1", parcours="BUT1", annee="BUT1", kind="td", headcount=10)]

    touched = _rebalance_failed_weeks(
        [2],
        sessions_by_week,
        week_by_session,
        session_by_id,
        weeks=4,
        duos=None,
        cohorts={"g1": {"g1"}},
        group_by_id={"g1": groups[0]},
        teacher_weekly_cap_slots=1,  # force un déplacement (2 séances, plafond à 1)
        fi_cap_slots=30,
        fc_cap_slots=30,
        eval_min_week={"eval": 2},
    )

    assert touched
    assert week_by_session["eval"] >= 2, "l'éval ne doit jamais être déplacée avant son contenu"
    # C'est bien `filler` qui a dû bouger, pas `eval`.
    assert week_by_session["filler"] != 2 or week_by_session["eval"] != 2


def test_rebalance_never_moves_content_after_its_eval_upper_bound() -> None:
    """Symétrique : le dernier contenu (semaine 1 en échec) ne doit jamais
    être rééquilibré vers une semaine > son `content_max_week`."""
    content = _session("content", "g1", seq=15)
    filler = _session("filler", "g1", seq=1)

    sessions_by_week = {0: [], 1: [filler, content], 2: [], 3: []}
    week_by_session = {"filler": 1, "content": 1}
    session_by_id = {"filler": filler, "content": content}
    groups = [Group(id="g1", label="G1", parcours="BUT1", annee="BUT1", kind="td", headcount=10)]

    touched = _rebalance_failed_weeks(
        [1],
        sessions_by_week,
        week_by_session,
        session_by_id,
        weeks=4,
        duos=None,
        cohorts={"g1": {"g1"}},
        group_by_id={"g1": groups[0]},
        teacher_weekly_cap_slots=1,
        fi_cap_slots=30,
        fc_cap_slots=30,
        content_max_week={"content": 1},
    )

    assert touched
    assert week_by_session["content"] <= 1, "le contenu ne doit jamais être déplacé après son éval"


def test_rebalance_without_eval_bounds_is_unaffected() -> None:
    """Non-régression : `eval_min_week`/`content_max_week=None` (défaut)
    laisse le comportement historique intact."""
    s1, s2 = _session("S1", "g1", seq=1), _session("S2", "g1", seq=2)
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
    )
    assert touched
