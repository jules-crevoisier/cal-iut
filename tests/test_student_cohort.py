"""Un étudiant ne peut pas avoir CM + TD + TP au même créneau."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from cal_iut.ingestion.config_loader import load_groups
from cal_iut.ingestion.merge import merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.models.group_scope import expand_group_filter
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver
from cal_iut.solver.resources import build_student_cohorts

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "exports"
CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


def test_cohort_maps_tp_a_to_promo_td_tp() -> None:
    groups = load_groups(CONFIG)
    cohorts = build_student_cohorts(groups)
    cohort = cohorts["student:but1-tp-a"]
    assert cohort == {"but1-tp-a", "but1-td-ab", "but1-promo"}


def test_no_student_overlap_on_subset() -> None:
    """Sous-ensemble BUT1 S1 : aucune collision pour un étudiant TP A."""
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    courses = merge_exports(maquette, progression)
    groups = load_groups(CONFIG)
    sessions = expand_all_sessions(courses, groups, parcours="BUT1", semestre="S1")
    # Limite pour un test rapide mais représentatif
    codes = {"WR101", "WR105", "WR107", "WR116", "WR104", "WR108"}
    subset = [s for s in sessions if s.course_code in codes]

    result = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=False,
            optimize_spread=False,
            enforce_sae_windows=False,
            enforce_ordonnancement=False,
            time_limit_seconds=90,
        )
    ).solve(subset, groups=groups)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    scope = expand_group_filter("but1-tp-a", groups)
    by_time: dict[tuple[int, int, int], list[str]] = defaultdict(list)
    for p in result.placements:
        if not scope.intersection(p.group_ids):
            continue
        by_time[(p.week, p.day, p.slot)].append(p.session_id)

    conflicts = {k: v for k, v in by_time.items() if len(v) > 1}
    assert conflicts == {}, f"Collisions étudiant TP A: {conflicts}"


def test_cm_covers_all_td_groups_s1() -> None:
    """Rappel métier : un CM S1 occupe toute la promo, donc les 4 groupes TD
    (AB/CD/EF/GH) en même temps, au même endroit. Vérifié structurellement :
    un CM ne génère qu'une seule séance (group_ids=[promo]), et cette séance
    fait partie de la cohorte de chacun des 4 TD — donc par construction,
    aucun TD/TP ne peut être placé en parallèle d'un CM (NoOverlap partagé)."""
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    courses = merge_exports(maquette, progression)
    groups = load_groups(CONFIG)
    sessions = expand_all_sessions(courses, groups, parcours="BUT1", semestre="S1")

    cm_sessions = [s for s in sessions if s.session_type.value == "CM"]
    assert cm_sessions, "le jeu de données réel S1 doit contenir des CM"
    for cm in cm_sessions:
        assert cm.group_ids == ["but1-promo"], (
            f"{cm.id}: un CM doit générer une séance unique ciblant le groupe "
            f"promo, pas {cm.group_ids}"
        )

    cohorts = build_student_cohorts(groups)
    td_ids = ["but1-td-ab", "but1-td-cd", "but1-td-ef", "but1-td-gh"]
    for td_id in td_ids:
        matching = [cohort for cohort in cohorts.values() if td_id in cohort]
        assert matching, f"{td_id} n'apparaît dans aucune cohorte étudiante"
        for cohort in matching:
            assert "but1-promo" in cohort, (
                f"{td_id}: le groupe promo (cible des CM) est absent de sa "
                f"cohorte {cohort} — un CM ne bloquerait pas ce TD"
            )
