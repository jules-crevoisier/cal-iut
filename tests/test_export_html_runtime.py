"""L'export HTML doit s'exécuter sans erreur, pas seulement contenir le bon texte.

`tests/test_html_export.py` vérifie la PRÉSENCE de chaînes dans le HTML produit.
Il ne peut pas voir qu'une erreur JavaScript au chargement rend la page
entièrement blanche — c'est exactement ce qui s'est produit le 10/08/2026
(`ReferenceError: Cannot access 'DATE_FMT' before initialization`) : tout ce que
les tests cherchaient était bien là, et aucune vue ne s'affichait.

Ce test charge donc la page dans un vrai DOM via `scripts/check_export_html.js`
(node + jsdom). Il est SAUTÉ si node ou jsdom manquent, pour ne pas imposer une
chaîne JavaScript à qui ne fait que du Python — mais il tourne dès que
l'environnement de développement complet est disponible.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.export.html_view import build_and_render
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.ingestion.merge import merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "contraintes"
CONFIG = ROOT / "data" / "config"
CHECKER = ROOT / "scripts" / "check_export_html.js"


def _node_env() -> dict[str, str] | None:
    """Environnement où `require('jsdom')` fonctionne, ou None si indisponible."""
    if shutil.which("node") is None:
        return None
    candidates = [
        os.environ.get("NODE_PATH"),
        str(Path.home() / "node_modules"),
        str(ROOT / "node_modules"),
        str(ROOT / "frontend" / "node_modules"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        env = {**os.environ, "NODE_PATH": candidate}
        probe = subprocess.run(
            ["node", "-e", "require('jsdom')"],
            capture_output=True, env=env, cwd=ROOT,
        )
        if probe.returncode == 0:
            return env
    return None


def _render_sample() -> str:
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    courses = merge_exports(maquette, progression)
    groups = load_groups(CONFIG)
    sessions = expand_all_sessions(courses, groups, parcours="BUT1", semestre="S1")
    subset = [s for s in sessions if s.course_code in ("WR108", "WR101")]

    result = TimetableSolver(
        SolverConfig(
            weeks=16, time_limit_seconds=30,
            optimize_gaps=False, optimize_spread=False, optimize_midday_fill=False,
            optimize_eval_clustering=False, enforce_sae_windows=False,
            enforce_sae_sanctuarization=False, enforce_student_cohort=False,
        )
    ).solve(subset)

    timetable = {
        "status": result.status,
        "objective_value": result.objective_value,
        "quality": None,
        "placements": [
            {
                "session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
                "course_code": p.course_code, "group_ids": p.group_ids,
                "teacher_codes": p.teacher_codes, "room_label": "H.101",
            }
            for p in result.placements
        ],
    }
    return build_and_render(
        timetable, subset, groups,
        calendar=build_default_calendar_2026_2027(), semestre="S1",
    )


def test_exported_page_runs_without_javascript_error(tmp_path: Path) -> None:
    env = _node_env()
    if env is None:
        pytest.skip("node + jsdom indisponibles (npm install --no-save jsdom)")

    page = tmp_path / "planning.html"
    page.write_text(_render_sample(), encoding="utf-8")

    proc = subprocess.run(
        ["node", str(CHECKER), str(page)],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    assert proc.returncode == 0, (
        "La page exportée lève une erreur au chargement ou n'expose pas les liens "
        f"enseignants :\n{proc.stdout}\n{proc.stderr}"
    )
