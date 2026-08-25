"""Tests du pipeline d'ingestion."""

import json
from pathlib import Path

import pytest

from cal_iut.ingestion.config_loader import load_groups
from cal_iut.ingestion.merge import merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.ingestion.pipeline import run_ingestion

# Exports officiels figés par `scripts/build_contraintes.py` — même copie que
# celle dont tous les `contraintes/*.json` sont dérivés (`ingestion/fetch.py`
# la préfère aussi). `data/exports/` est gitignoré : les tests ne peuvent pas
# en dépendre.
FIXTURES = Path(__file__).resolve().parents[1] / "contraintes"
CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


@pytest.fixture(scope="module")
def exports() -> tuple[list[dict], list[dict]]:
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    return maquette, progression


def test_merge_exports_count(exports: tuple[list[dict], list[dict]]) -> None:
    maquette, progression = exports
    courses = merge_exports(maquette, progression)
    assert len(courses) >= 182


def test_merge_wr108_has_progression(exports: tuple[list[dict], list[dict]]) -> None:
    courses = merge_exports(*exports)
    wr108 = next(c for c in courses if c.code == "WR108" and c.parcours == "BUT1")
    assert wr108.progression_defined
    assert len(wr108.seance_sequence) == 14
    assert len(wr108.ordonnancement) == 2


def test_expand_but1_s1_sessions(exports: tuple[list[dict], list[dict]]) -> None:
    courses = merge_exports(*exports)
    groups = load_groups(CONFIG)
    sessions = expand_all_sessions(courses, groups, parcours="BUT1", semestre="S1")
    assert len(sessions) > 100
    cm_sessions = [s for s in sessions if s.session_type.value == "CM"]
    tp_sessions = [s for s in sessions if s.session_type.value == "TP"]
    assert len(cm_sessions) > 0
    assert len(tp_sessions) > len(cm_sessions)


def test_wr108_expansion_per_group(exports: tuple[list[dict], list[dict]]) -> None:
    courses = merge_exports(*exports)
    groups = load_groups(CONFIG)
    wr108 = next(c for c in courses if c.code == "WR108" and c.semestre == "S1")
    from cal_iut.ingestion.normalize import expand_course_to_sessions

    sessions = expand_course_to_sessions(wr108, groups)
    tp_count = sum(1 for s in sessions if s.session_type.value == "TP")
    assert tp_count == 8 * 8


def test_wr110_teacher_per_tp_group(exports: tuple[list[dict], list[dict]]) -> None:
    courses = merge_exports(*exports)
    groups = load_groups(CONFIG)
    wr110 = next(c for c in courses if c.code == "WR110" and c.semestre == "S1")
    from cal_iut.ingestion.normalize import expand_course_to_sessions

    sessions = expand_course_to_sessions(wr110, groups)
    tp_sessions = [s for s in sessions if s.session_type.value == "TP"]
    multi_teacher = {s.group_ids[0]: s.teacher_codes[0] for s in tp_sessions[:16]}
    assert len(set(multi_teacher.values())) > 1


def test_run_ingestion_from_cache(exports: tuple[list[dict], list[dict]]) -> None:
    maquette, progression = exports
    result = run_ingestion(
        CONFIG,
        maquette=maquette,
        progression=progression,
        parcours="BUT1",
        semestre="S1",
    )
    assert result.stats["sessions_total"] > 0
