"""Codes enseignants validés et page `/legacy` échappée (audit 29/09/2026, P1-8).

Avant : `teacher_codes` n'était que `strip().upper()` à la création d'une
séance personnalisée ou d'un évènement. Un compte `edit` pouvait enregistrer
`<IMG SRC=X ONERROR=...>`, que le gabarit `/legacy` réinjectait tel quel via
`innerHTML` chez tout admin qui l'ouvrait.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import _enseignants_valides, app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.export.html_view import build_and_render, render_html
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom
from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
MALVEILLANT = "<IMG SRC=X ONERROR=&#X61;LERT(1)>"
SEMAINE = 10


def _seance(sid: str, enseignants: list[str], **meta) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Cours existant", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM, sequence_order=1,
        group_ids=["but1-promo"], teacher_codes=enseignants, duration_slots=1, metadata=meta,
    )


def _place(s: SessionToPlace, day: int = 0, slot: int = 0) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=SEMAINE, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
    )


@pytest.fixture
def monter(db_isole):
    etat = get_state()
    champs = (
        "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar", "current_run_id",
        "teacher_availability", "teacher_duos", "corrections", "courses", "config_dir",
    )
    ancien = {c: getattr(etat, c) for c in champs}

    def _monter(seances: list[SessionToPlace]) -> TestClient:
        etat.sessions = list(seances)
        etat.sessions_by_id = {s.id: s for s in seances}
        etat.timetable = [_place(s, day=i) for i, s in enumerate(seances)]
        etat.groups = GROUPES
        etat.rooms = []
        etat.calendar = build_default_calendar_2026_2027()
        etat.current_run_id = None
        etat.teacher_availability = []
        etat.teacher_duos = []
        etat.corrections = []
        etat.courses = []
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        creer_compte_actif_et_connecter(client)
        return client

    yield _monter
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_creer_une_seance_avec_un_enseignant_inconnu_est_refuse(monter):
    client = monter([_seance("a", ["KBR"])])
    r = client.post("/placements/personnalisees", json={
        "course_code": "WR101", "session_type": "TD", "group_ids": ["but1-promo"],
        "teacher_codes": [MALVEILLANT], "week": SEMAINE, "day": 2, "slot": 1,
    })
    assert r.status_code == 422, r.text
    assert "inconnu" in r.text
    assert [s.id for s in get_state().sessions] == ["a"]


def test_creer_un_evenement_avec_un_enseignant_inconnu_est_refuse(monter):
    client = monter([_seance("a", ["KBR"])])
    r = client.post("/placements/evenements", json={
        "libelle": "Réunion", "semestre": "S1", "group_ids": ["but1-promo"],
        "teacher_codes": ["ZZZ"], "duration_slots": 1, "week": SEMAINE, "day": 2, "slot": 1,
    })
    assert r.status_code == 422, r.text
    assert "ZZZ" in r.text
    assert len(get_state().timetable) == 1


def test_modifier_une_seance_creee_avec_un_enseignant_inconnu_est_refuse(monter):
    perso = _seance("perso", ["KBR"], custom_session=True)
    client = monter([perso])
    r = client.patch("/placements/personnalisees/perso", json={"teacher_codes": [MALVEILLANT]})
    assert r.status_code == 422, r.text
    assert get_state().sessions_by_id["perso"].teacher_codes == ["KBR"]
    assert get_state().timetable[0].teacher_codes == ["KBR"]


def test_un_enseignant_declare_sans_seance_est_accepte(monter):
    """APH figure dans la liste des enseignants déclarés (proposée par
    l'écran « Nouvelle séance ») sans avoir encore de séance."""
    monter([_seance("a", ["KBR"])])
    assert _enseignants_valides(get_state(), [" aph ", "kbr", ""]) == ["APH", "KBR"]


# ── Gabarit `/legacy` ────────────────────────────────────────────────────────


def _page_avec(code: str) -> str:
    s = _seance("x", [code])
    s.course_name = "<b>gras</b>"
    timetable = {
        "status": "OPTIMAL", "objective_value": 0, "quality": None,
        "placements": [{
            "session_id": "x", "week": 0, "day": 0, "slot": 0, "course_code": "WR101",
            "group_ids": ["but1-promo"], "teacher_codes": [code], "room_label": "<i>H.101</i>",
        }],
    }
    return build_and_render(timetable, [s], GROUPES, calendar=build_default_calendar_2026_2027(), semestre="S1")


def test_le_payload_ne_peut_pas_fermer_sa_balise_script_meme_en_majuscules():
    page = render_html({"rows": [], "x": "</SCRIPT><SCRIPT>ALERT(1)</SCRIPT>"})
    donnees = page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in donnees
    assert json.loads(donnees)["x"] == "</SCRIPT><SCRIPT>ALERT(1)</SCRIPT>"


def test_le_gabarit_echappe_les_champs_libres_injectes_en_html():
    gabarit = (ROOT / "src" / "cal_iut" / "export" / "templates" / "timetable.html").read_text(encoding="utf-8")
    assert "function esc(" in gabarit
    for attendu in ("${esc(r.te.join(', '))}", "${esc(r.c)}", "${esc(r.r || '—')}", "${esc(teacherNames || '—')}",
                    "esc(e.reason)", "${esc(c.name)}", "${esc(c.detail)}", "${esc(t.name)}"):
        assert attendu in gabarit, attendu


def test_la_page_legacy_n_execute_pas_un_code_enseignant_malveillant(tmp_path):
    from test_export_html_runtime import _node_env

    env = _node_env()
    if env is None:
        pytest.skip("node + jsdom indisponibles (npm install --no-save jsdom)")
    page = tmp_path / "legacy.html"
    page.write_text(_page_avec(MALVEILLANT), encoding="utf-8")
    script = r"""
      const { JSDOM } = require('jsdom');
      const html = require('fs').readFileSync(process.argv[1], 'utf8');
      const dom = new JSDOM(html, {
        runScripts: 'dangerously', url: 'https://example.test/p.html#vue=prof&prof=' + encodeURIComponent(process.argv[2]),
        beforeParse(w) {
          w.print = () => {};
          w.matchMedia = (q) => ({ media: q, matches: false, addEventListener() {}, removeEventListener() {} });
        },
      });
      const doc = dom.window.document;
      console.log(JSON.stringify({
        img: doc.querySelectorAll('img').length,
        b: [...doc.querySelectorAll('b')].some(e => e.textContent === 'gras'),
        i: [...doc.querySelectorAll('i')].some(e => e.textContent === 'H.101'),
        texte: doc.body.textContent.includes(process.argv[2]),
      }));
    """
    proc = subprocess.run(
        ["node", "-e", script, str(page), MALVEILLANT],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    resultat = json.loads(proc.stdout.strip().splitlines()[-1])
    assert resultat == {"img": 0, "b": False, "i": False, "texte": True}
