"""Tests de l'export HTML autonome (calendrier + vue TD 2 colonnes TP)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.export.html_view import build_and_render, build_payload
from cal_iut.ingestion.config_loader import load_groups, load_rooms
from cal_iut.ingestion.merge import merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.models.entities import TeacherAvailability
from cal_iut.solver.cpsat import SolverConfig, TimetableSolver

# Exports officiels figés par `scripts/build_contraintes.py` — même copie que
# celle dont tous les `contraintes/*.json` sont dérivés (`ingestion/fetch.py`
# la préfère aussi). `data/exports/` est gitignoré : les tests ne peuvent pas
# en dépendre.
FIXTURES = Path(__file__).resolve().parents[1] / "contraintes"
CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


def _but1_wr108_solved():
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    courses = merge_exports(maquette, progression)
    groups = load_groups(CONFIG)
    sessions = expand_all_sessions(courses, groups, parcours="BUT1", semestre="S1")
    subset = [s for s in sessions if s.course_code == "WR108"]

    result = TimetableSolver(
        SolverConfig(
            weeks=16,
            optimize_gaps=False,
            enforce_sae_windows=False,
            enforce_sae_sanctuarization=False,
            optimize_spread=False,
            optimize_midday_fill=False,
            optimize_eval_clustering=False,
            enforce_student_cohort=False,
        )
    ).solve(subset)

    timetable = {
        "status": result.status,
        "objective_value": result.objective_value,
        "quality": None,
        "placements": [
            {
                "session_id": p.session_id,
                "week": p.week,
                "day": p.day,
                "slot": p.slot,
                "course_code": p.course_code,
                "group_ids": p.group_ids,
                "teacher_codes": p.teacher_codes,
                "room_label": None,
            }
            for p in result.placements
        ],
    }
    return timetable, subset, groups


def test_build_payload_has_td_tp_pair_and_week_labels() -> None:
    timetable, subset, groups = _but1_wr108_solved()
    calendar = build_default_calendar_2026_2027()

    payload = build_payload(timetable, subset, groups, calendar=calendar, semestre="S1")

    assert payload["status"] in ("OPTIMAL", "FEASIBLE")
    assert len(payload["rows"]) == len(subset)
    assert payload["groupTpPair"]["but1-td-ab"] == ["but1-tp-a", "but1-tp-b"]
    assert payload["groupKind"]["but1-tp-a"] == "tp"
    # cohorte réelle d'un TP : lui-même + son TD + le CM promo
    assert set(payload["groupCohort"]["but1-tp-a"]) == {"but1-tp-a", "but1-td-ab", "but1-promo"}
    # semaine-index 0 -> "Semaine 2 (...)" (rentrée), pas "Semaine 1"
    assert payload["weekLabels"][0].startswith("Semaine 2")
    assert payload["weekLabels"][1].startswith("Semaine 3")


def test_render_html_embeds_payload_and_is_self_contained() -> None:
    timetable, subset, groups = _but1_wr108_solved()
    html = build_and_render(timetable, subset, groups, semestre="S1")

    assert "<title>" in html
    assert "id=\"data\" type=\"application/json\"" in html
    assert "WR108" in html
    # pas de chargement externe (CDN, police) — seule une URI de namespace SVG
    # (xmlns) peut légitimement contenir "http://". Depuis la Vue Semaine
    # (édition manuelle : glisser-déposer, exceptions, régénération ciblée),
    # la page appelle bien `fetch()`, mais UNIQUEMENT vers l'API du même
    # serveur en chemin relatif (`/placements/...`, `/exceptions`,
    # `/regen/...`) — jamais un domaine externe.
    assert "<script src=" not in html
    assert "<link " not in html
    fetch_targets = re.findall(r"fetch\(\s*['\"]([^'\"]+)", html)
    assert fetch_targets, "la Vue Semaine doit appeler l'API (déplacement/régénération)"
    assert all(t.startswith("/") for t in fetch_targets), f"fetch() doit rester relatif au même serveur : {fetch_targets}"


def test_build_payload_includes_rule_checks_and_institutional_calendar() -> None:
    timetable, subset, groups = _but1_wr108_solved()
    calendar = build_default_calendar_2026_2027()

    payload = build_payload(timetable, subset, groups, calendar=calendar, semestre="S1")

    rule_ids = {c["id"] for c in payload["ruleChecks"]}
    assert {"weekly_cap", "thursday_pac", "eval_room", "s1_integration_lock", "pedagogical_order"} <= rule_ids
    for check in payload["ruleChecks"]:
        assert check["status"] in ("pass", "fail", "info")

    assert len(payload["institutionalCalendar"]) > 0
    assert all(ev["kind"] in ("vacances", "ferie", "rentree", "special") for ev in payload["institutionalCalendar"])


def test_build_payload_includes_rooms_and_course_catalog() -> None:
    timetable, subset, groups = _but1_wr108_solved()
    calendar = build_default_calendar_2026_2027()
    rooms = load_rooms(CONFIG)

    payload = build_payload(timetable, subset, groups, calendar=calendar, semestre="S1", rooms=rooms)

    assert payload["rooms"], "le catalogue de salles doit être peuplé"
    assert any(r["label"] == "H.009 (Design)" for r in payload["rooms"])

    assert payload["courses"], "le catalogue de cours doit contenir WR108"
    wr108 = next(c for c in payload["courses"] if c["code"] == "WR108")
    assert wr108["nTP"] > 0
    assert wr108["parcours"] == "BUT1"

    # groupParcours doit couvrir tous les groupes exposés au frontend
    assert payload["groupParcours"]["but1-tp-a"] == "BUT1"


def test_teacher_constraint_violation_is_detected() -> None:
    """Une contrainte enseignante délibérément en conflit avec le planning doit être signalée."""
    timetable, subset, groups = _but1_wr108_solved()
    calendar = build_default_calendar_2026_2027()

    placements = timetable["placements"]
    assert placements
    conflicting = placements[0]
    teacher_code = conflicting["teacher_codes"][0]

    teacher_avail = [
        TeacherAvailability(
            teacher_code=teacher_code,
            forbidden_slots=[(conflicting["day"], conflicting["slot"])],
            metadata={"raw_indisponibilites": "test conflit délibéré"},
        ),
        TeacherAvailability(teacher_code="NOBODY", forbidden_slots=[(0, 0)]),
    ]

    payload = build_payload(
        timetable, subset, groups, calendar=calendar, semestre="S1", teacher_availability=teacher_avail
    )

    by_code = {t["code"]: t for t in payload["teachers"]}
    assert by_code[teacher_code]["violations"], "la violation délibérée doit être détectée"
    # Enseignant sans aucune séance placée : présent dans le payload mais 0 violation
    if "NOBODY" in by_code:
        assert by_code["NOBODY"]["nPlaced"] == 0


def test_sae_supervision_violation_is_tagged_differently_from_declared() -> None:
    """
    Retour utilisateur 11/08/2026 : "152 contrainte non respecté ce n'est
    pas possible" — diagnostic réel : 115/152 étaient des compromis MOUS
    acceptés (référent SAE ce jour-là, `--no-sae-supervisor-hard`), pas de
    vraies violations. `reason` distingue les deux au lieu de tout confondre
    sous "violation" (cf. docs/DATA.md §59).
    """
    from datetime import date

    timetable, subset, groups = _but1_wr108_solved()
    calendar = build_default_calendar_2026_2027()
    placements = timetable["placements"]
    conflicting = placements[0]
    teacher_code = conflicting["teacher_codes"][0]
    conflict_date = calendar.week_day_to_date(conflicting["week"], conflicting["day"])
    assert conflict_date is not None

    teacher_avail = [
        TeacherAvailability(
            teacher_code=teacher_code,
            metadata={"forbidden_dates": [conflict_date.isoformat()]},
        ),
    ]

    payload = build_payload(
        timetable, subset, groups, calendar=calendar, semestre="S1", teacher_availability=teacher_avail,
        sae_supervisor_dates={teacher_code: {conflict_date}},
    )
    by_code = {t["code"]: t for t in payload["teachers"]}
    violations = by_code[teacher_code]["violations"]
    assert violations
    assert all(v["reason"] == "sae_supervision" for v in violations)

    # Sans `sae_supervisor_dates` (ou avec une date différente) : reste "declared".
    payload_no_sae = build_payload(
        timetable, subset, groups, calendar=calendar, semestre="S1", teacher_availability=teacher_avail,
    )
    by_code_no_sae = {t["code"]: t for t in payload_no_sae["teachers"]}
    assert all(v["reason"] == "declared" for v in by_code_no_sae[teacher_code]["violations"])


def _render_full() -> tuple[str, dict]:
    """HTML complet + payload décodé, avec un vrai calendrier (sans lui,
    `weekDates` serait vide et l'export .ics ne pourrait pas être daté)."""
    timetable, subset, groups = _but1_wr108_solved()
    html = build_and_render(
        timetable, subset, groups,
        calendar=build_default_calendar_2026_2027(), semestre="S1",
    )
    raw = re.search(
        r'<script id="data" type="application/json">(.*?)</script>', html, re.S
    ).group(1)
    return html, json.loads(raw)


def test_export_generates_a_shareable_link_and_ics_per_teacher():
    """
    Retour utilisateur (10/08/2026) : « il faut faire en sorte de générer des
    liens par prof pour pouvoir leur donner leur planning ». Le lien vit dans
    le FRAGMENT d'URL, jamais envoyé au serveur : il fonctionne donc aussi sur
    le fichier ouvert en local (file://), pas seulement sur l'app servie.
    """
    html, payload = _render_full()

    # Routage par fragment + mode enseignant en lecture seule.
    assert "location.hash" in html
    assert "teacher-mode" in html

    # Annuaire des liens + copie en masse + export agenda.
    assert 'id="teacherLinksTable"' in html
    assert 'id="copyAllLinksBtn"' in html
    assert "BEGIN:VCALENDAR" in html
    assert "text/calendar" in html

    # Les vraies dates de chaque semaine sont exposées : sans elles, un .ics
    # ne contiendrait que des « semaine 7 » inutilisables dans un agenda.
    dates = [d for d in payload["weekDates"] if d]
    assert dates, "weekDates vide alors qu'un calendrier a été fourni"
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
    # Ce sont bien des lundis, et ils sont strictement croissants.
    parsed = [date.fromisoformat(d) for d in dates]
    assert all(d.weekday() == 0 for d in parsed)
    assert parsed == sorted(parsed)


def test_print_stylesheet_hides_the_editing_chrome():
    """Un enseignant imprime son planning : les contrôles ne doivent pas sortir."""
    html, _ = _render_full()
    printblock = html.split("@media print")[1].split("</style>")[0]
    for hidden in (".tabbar", ".controls", ".no-print"):
        assert hidden in printblock
