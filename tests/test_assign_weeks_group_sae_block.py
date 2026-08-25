"""
Bug réel du 12/08/2026, trouvé en diagnostiquant un run réel bloqué en
`PARTIAL_WEEKS_FAILED` — `assign_weeks` (étage 2) ne raisonnait le blocage
SAE qu'au niveau PARCOURS (`blocked_by_parcours`). Une SAE propre à UN SEUL
groupe (`blocked_by_group`, ex. WS502D pour le seul TD-AB) peut se COMBINER
avec le blocage parcours pour fermer TOUS les jours d'une semaine à ce
groupe précis, sans qu'aucun des deux blocages pris isolément ne le fasse —
l'étage 2 assignait alors quand même des séances à cette semaine, que
l'étage 3 prouvait ensuite INFEASIBLE en 0s (ex. réel : BUT3-DEV-FI bloqué
jeu/ven au niveau parcours, but3-dev-fi-td-ab bloqué mar/mer au niveau
groupe -> lundi seul restait ouvert, 6 créneaux pour 16 séances). Cf.
docs/DATA.md §58.
"""

from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import assign_weeks


def _sessions(parcours: str, group_id: str, count: int) -> list[SessionToPlace]:
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
            group_ids=[group_id],
            teacher_codes=["ZZZ"],
        )
        for i in range(count)
    ]


def test_combined_parcours_and_group_sae_block_excludes_the_week() -> None:
    """Parcours bloqué jeu+ven (2 jours), groupe bloqué mar+mer (2 jours
    différents) -> lundi seul reste ouvert (6 créneaux) pour ce groupe.
    Sans le correctif, l'étage 2 ne voit que les 2 jours parcours et croit
    la semaine 0 encore à moitié libre."""
    sessions = _sessions("BUT3-DEV-FI", "but3-dev-fi-td-ab", 10)
    result = assign_weeks(
        sessions,
        groups=[],
        weeks=5,
        teacher_weekly_cap_slots=26,
        blocked_by_parcours={"BUT3-DEV-FI": {(0, 3), (0, 4)}},
        blocked_by_group={"but3-dev-fi-td-ab": {(0, 1), (0, 2)}},
        time_limit_seconds=10,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert all(w != 0 for w in result.week_by_session.values()), (
        "semaine 0 entièrement fermée pour ce groupe (parcours + groupe combinés) "
        "-> ne doit jamais y être assignée"
    )


def test_parcours_block_alone_does_not_close_the_week() -> None:
    """Le même blocage parcours (jeu+ven, 2 jours) SEUL ne ferme pas la
    semaine — 3 jours restent ouverts. Non-régression : `blocked_by_group`
    ne doit pas durcir un cas qui n'était pas fermé avant. Horizon réduit à
    UNE semaine (0) : si elle était exclue par erreur, la résolution
    échouerait faute d'alternative — la pénalité molle d'évitement
    (semaine partiellement bloquée) ne peut sinon la faire éviter sans le
    prouver directement, cf. les 2 échecs corrigés dans ce fichier."""
    sessions = _sessions("BUT3-DEV-FI", "but3-dev-fi-td-ab", 10)
    result = assign_weeks(
        sessions,
        groups=[],
        weeks=1,
        teacher_weekly_cap_slots=26,
        blocked_by_parcours={"BUT3-DEV-FI": {(0, 3), (0, 4)}},
        time_limit_seconds=10,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_group_level_sae_block_reduces_the_cohort_weekly_cap() -> None:
    """
    Le VRAI mécanisme derrière le bug (cf. docstring de fichier) : le cas
    réel (semaine 16, 16 séances TD) ne fermait PAS entièrement la semaine
    (4 jours sur 5 seulement) — il ne restait qu'1 jour ouvert (6 créneaux),
    largement insuffisant pour 16 séances, mais toujours "ouvert" au sens du
    test ci-dessus. Le vrai correctif est que le plafond hebdomadaire de
    cohorte (`cap_w`) doit refléter la capacité physique RÉELLE du groupe
    (parcours + groupe combinés), pas seulement le blocage parcours seul.
    Ici : 2 jours bloqués parcours + 2 jours (différents) bloqués groupe ->
    1 seul jour ouvert (6 créneaux, marge 2 -> plafond 4) pour 10 séances TD
    -> la semaine 0 ne doit en admettre au plus que 4, le reste doit être
    étalé sur les 2 autres semaines de l'horizon.
    """
    td = Group(id="td1", label="TD1", parcours="BUT3-DEV-FI", annee="BUT3", kind="td", headcount=20)
    promo = Group(id="promo1", label="Promo", parcours="BUT3-DEV-FI", annee="BUT3", kind="promo", headcount=20)
    sessions = _sessions("BUT3-DEV-FI", "td1", 10)

    result = assign_weeks(
        sessions,
        groups=[td, promo],
        weeks=3,
        teacher_weekly_cap_slots=26,
        blocked_by_parcours={"BUT3-DEV-FI": {(0, 3), (0, 4)}},
        blocked_by_group={"td1": {(0, 1), (0, 2)}},
        time_limit_seconds=10,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    week0_count = sum(1 for w in result.week_by_session.values() if w == 0)
    assert week0_count <= 4, (
        f"semaine 0 (1 seul jour réellement ouvert, marge comprise -> plafond 4) "
        f"ne devrait pas admettre plus de 4 séances, en a reçu {week0_count}"
    )


def test_group_block_does_not_affect_a_different_group() -> None:
    """Le blocage groupe ne doit s'appliquer qu'aux séances de CE groupe,
    jamais à un autre groupe du même parcours. Horizon réduit à UNE semaine
    (0), même raison que le test précédent."""
    sessions = _sessions("BUT3-DEV-FI", "but3-dev-fi-td-cd", 10)
    result = assign_weeks(
        sessions,
        groups=[],
        weeks=1,
        teacher_weekly_cap_slots=26,
        blocked_by_parcours={"BUT3-DEV-FI": {(0, 3), (0, 4)}},
        blocked_by_group={"but3-dev-fi-td-ab": {(0, 1), (0, 2)}},  # un AUTRE groupe
        time_limit_seconds=10,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
