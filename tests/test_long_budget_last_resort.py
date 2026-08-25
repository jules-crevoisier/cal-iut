"""
Dernier recours (12/08/2026, retour utilisateur : run réel bloqué en
`PARTIAL_WEEKS_FAILED` sur plusieurs semaines) — `_solve_week_with_retry`
accepte un `long_budget` qui REMPLACE les 3 tentatives standard (budget
normal x2 seeds différentes + budget x3) par 8 tentatives continues à ce
budget, sur 8 seeds différentes, chacune s'arrêtant dès la PREMIÈRE solution
faisable (`stop_at_first_solution`, cf. `solve_week_detail`). Vérifié
empiriquement sur données réelles, en plusieurs temps : (1) semaine 12 (256
séances), fractionnée en 3 tentatives à budget standard -> UNKNOWN, 400s
continus sur LA MÊME seed -> FEASIBLE immédiat ; (2) 1 seule seed à budget
long insuffisante sur un run ultérieur -> 2 seeds ; (3) diagnostic explicite
demandé par l'utilisateur (« pourquoi ces séances ne sont pas placées, pas
assez de profs ? temps manquant ? ») sur les semaines 5/10/14 : chacune
résolue à 100% EN ISOLATION en 60s, aucun manque de ressource réel — la
seule variable en jeu est la graine CP-SAT ; (4) même 4 seeds encore
insuffisantes sur le run suivant -> 8 seeds, rendues abordables par
`stop_at_first_solution` (budget par tentative réduit en contrepartie côté
`solve_decomposed`, cf. son commentaire). Cf. docs/DATA.md §58.
"""

from cal_iut.solver.decomposed import _solve_week_with_retry


def test_long_budget_replaces_the_standard_retry_attempts(monkeypatch) -> None:
    calls: list[tuple[float, int, bool]] = []

    def fake_solve_week_detail(week_sessions, absolute_week, **kwargs):
        calls.append((kwargs["time_limit_seconds"], kwargs["random_seed"], kwargs["stop_at_first_solution"]))
        return "FEASIBLE", {}

    monkeypatch.setattr("cal_iut.solver.decomposed.solve_week_detail", fake_solve_week_detail)

    status_name, local_times = _solve_week_with_retry(
        [],
        0,
        0,
        teacher_availability=None,
        calendar=None,
        student_presences=None,
        groups=[],
        blocked_by_parcours=None,
        blocked_by_group=None,
        duos=None,
        week_detail_time_limit=90,
        num_workers=16,
        random_seed=2027,
        hints=None,
        long_budget=400.0,
    )

    # Une seule tentative EFFECTUÉE (la 1re a réussi, la 2e n'a pas lieu
    # d'être tentée) — au budget demandé (pas x3), pas les 3 tentatives
    # standard, et `stop_at_first_solution=True` (dernier recours : la
    # première solution faisable suffit, cf. `solve_week_detail`).
    assert calls == [(400.0, 2027, True)]
    assert status_name == "FEASIBLE"
    assert local_times == {}


def test_without_long_budget_stop_at_first_solution_is_false(monkeypatch) -> None:
    """Non-régression : en résolution normale (pas de dernier recours), on
    cherche la MEILLEURE semaine possible, jamais juste la première trouvée."""
    calls: list[bool] = []

    def fake_solve_week_detail(week_sessions, absolute_week, **kwargs):
        calls.append(kwargs["stop_at_first_solution"])
        return "FEASIBLE", {}

    monkeypatch.setattr("cal_iut.solver.decomposed.solve_week_detail", fake_solve_week_detail)

    _solve_week_with_retry(
        [],
        0,
        0,
        teacher_availability=None,
        calendar=None,
        student_presences=None,
        groups=[],
        blocked_by_parcours=None,
        blocked_by_group=None,
        duos=None,
        week_detail_time_limit=90,
        num_workers=16,
        random_seed=2027,
        hints=None,
    )

    assert calls == [False]


def test_long_budget_falls_back_to_further_seeds_if_earlier_ones_fail(monkeypatch) -> None:
    """Bug réel du 12/08/2026 (occurrences 2 et 3, cf. docstring de fichier) :
    une seule seed, puis deux, à budget long ne suffisent pas toujours —
    vérifie que TOUTES les seeds nécessaires sont tentées (jusqu'à 4) avant
    d'abandonner, dans l'ordre, en s'arrêtant dès qu'une réussit."""
    calls: list[tuple[float, int]] = []

    def fake_solve_week_detail(week_sessions, absolute_week, **kwargs):
        calls.append((kwargs["time_limit_seconds"], kwargs["random_seed"]))
        if kwargs["random_seed"] == 2027 + 5000 * 2:  # ne réussit qu'à la 3e tentative
            return "FEASIBLE", {}
        return "UNKNOWN", {}

    monkeypatch.setattr("cal_iut.solver.decomposed.solve_week_detail", fake_solve_week_detail)

    status_name, _ = _solve_week_with_retry(
        [],
        0,
        0,
        teacher_availability=None,
        calendar=None,
        student_presences=None,
        groups=[],
        blocked_by_parcours=None,
        blocked_by_group=None,
        duos=None,
        week_detail_time_limit=90,
        num_workers=16,
        random_seed=2027,
        hints=None,
        long_budget=400.0,
    )

    assert calls == [(400.0, 2027), (400.0, 7027), (400.0, 12027)]
    assert status_name == "FEASIBLE"


def test_long_budget_exhausts_all_eight_seeds_before_giving_up(monkeypatch) -> None:
    """Si aucune des 8 seeds ne réussit, les 8 doivent bien avoir été
    tentées (pas moins) avant que le statut d'échec final soit retourné."""
    calls: list[tuple[float, int]] = []

    def fake_solve_week_detail(week_sessions, absolute_week, **kwargs):
        calls.append((kwargs["time_limit_seconds"], kwargs["random_seed"]))
        return "UNKNOWN", {}

    monkeypatch.setattr("cal_iut.solver.decomposed.solve_week_detail", fake_solve_week_detail)

    status_name, _ = _solve_week_with_retry(
        [],
        0,
        0,
        teacher_availability=None,
        calendar=None,
        student_presences=None,
        groups=[],
        blocked_by_parcours=None,
        blocked_by_group=None,
        duos=None,
        week_detail_time_limit=90,
        num_workers=16,
        random_seed=2027,
        hints=None,
        long_budget=400.0,
    )

    assert calls == [(400.0, 2027 + 5000 * i) for i in range(8)]
    assert status_name == "UNKNOWN"


def test_without_long_budget_the_standard_three_attempts_still_apply(monkeypatch) -> None:
    """Non-régression : `long_budget=None` (défaut) laisse le comportement
    standard intact — 3 tentatives, budgets/seeds inchangés."""
    calls: list[tuple[float, int]] = []

    def fake_solve_week_detail(week_sessions, absolute_week, **kwargs):
        calls.append((kwargs["time_limit_seconds"], kwargs["random_seed"]))
        return "INFEASIBLE", {}  # force l'épuisement des 3 tentatives

    monkeypatch.setattr("cal_iut.solver.decomposed.solve_week_detail", fake_solve_week_detail)

    status_name, _ = _solve_week_with_retry(
        [],
        0,
        0,
        teacher_availability=None,
        calendar=None,
        student_presences=None,
        groups=[],
        blocked_by_parcours=None,
        blocked_by_group=None,
        duos=None,
        week_detail_time_limit=90,
        num_workers=16,
        random_seed=2027,
        hints=None,
    )

    assert calls == [(90, 2027), (90, 7027), (270, 11027)]
    assert status_name == "INFEASIBLE"
