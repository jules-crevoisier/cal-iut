"""Verdict par enseignant et règle globale : même source de vérité
(signalement du 29/09/2026).

La règle globale « Indisponibilités et listes blanches » était en échec sur
37 séances (ex. JBA hors liste blanche) alors que chaque enseignant, pris un
par un (payload `/app-state`, onglet Contraintes), affichait « respectée » :
le verdict individuel ne regardait pas les listes blanches
(`allowed_slots`/`allowed_dates`).
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.export.html_view import build_payload
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType, TeacherAvailability
from cal_iut.models.session import SessionToPlace

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
CALENDRIER = build_default_calendar_2026_2027()
SEMAINE = 10


def _seance(sid: str, prof: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR" + sid, course_name="Cours", semestre="S1", parcours="BUT1", annee="BUT1",
        session_type=SessionType.TD, group_ids=["but1-td-ab"], teacher_codes=[prof], duration_slots=1,
    )


def _payload(disponibilites: list[TeacherAvailability], poses: list[tuple[str, str, int, int]]):
    seances = [_seance(sid, prof) for sid, prof, _, _ in poses]
    timetable = {
        "status": "OPTIMAL", "objective_value": 0, "quality": None,
        "placements": [
            {"session_id": sid, "week": SEMAINE, "day": jour, "slot": creneau, "course_code": "WR" + sid,
             "group_ids": ["but1-td-ab"], "teacher_codes": [prof], "room_label": "H.101"}
            for sid, prof, jour, creneau in poses
        ],
    }
    return build_payload(
        timetable, seances, GROUPES, calendar=CALENDRIER, semestre="S1", teacher_availability=disponibilites,
    )


def _date(jour: int) -> str:
    from cal_iut.calendar.academic import semester_week_offset

    return CALENDRIER.week_day_to_date(semester_week_offset(CALENDRIER, "S1") + SEMAINE, jour).isoformat()


def test_une_seance_hors_liste_blanche_compte_dans_le_verdict_de_l_enseignant_et_dans_la_regle():
    disponibilites = [
        # Disponible seulement le mardi, créneaux 0 et 1 : la séance du lundi est hors liste.
        TeacherAvailability(teacher_code="JBA", allowed_slots=[(1, 0), (1, 1)]),
        # Vacataire : ne vient que le mercredi de cette semaine-là.
        TeacherAvailability(teacher_code="VAC", allowed_dates=[_date(2)]),
        # Respecte sa liste blanche.
        TeacherAvailability(teacher_code="OKK", allowed_slots=[(3, 0)]),
    ]
    payload = _payload(disponibilites, [
        ("A", "JBA", 0, 0), ("B", "JBA", 1, 1), ("C", "VAC", 4, 2), ("D", "VAC", 2, 0), ("E", "OKK", 3, 0),
    ])
    par_code = {t["code"]: t for t in payload["teachers"]}

    jba = par_code["JBA"]
    assert jba["hasConstraint"] is True
    assert jba["violations"] == [{
        "week": SEMAINE, "day": 0, "slot": 0, "course_code": "WRA", "reason": "declared", "motif": "hors_liste_blanche",
    }]
    vac = par_code["VAC"]
    assert vac["hasConstraint"] is True
    assert vac["violations"] == [{
        "date": _date(4), "course_code": "WRC", "reason": "declared", "motif": "hors_dates_de_venue",
    }]
    assert par_code["OKK"]["violations"] == []

    regle = next(c for c in payload["ruleChecks"] if c["id"] == "teacher_availability")
    assert regle["status"] == "fail"
    assert regle["detail"].startswith("2/5 ")
    # Même compte des deux côtés : une vraie violation par séance fautive.
    vraies = sum(
        1 for t in payload["teachers"] for v in t["violations"] if v.get("reason") != "sae_supervision"
    )
    assert vraies == 2


def test_le_compromis_d_encadrement_sae_reste_hors_de_la_regle_globale():
    quand = _date(0)
    disponibilites = [TeacherAvailability(teacher_code="SAE", metadata={"forbidden_dates": [quand]})]
    seances = [_seance("A", "SAE")]
    timetable = {
        "status": "OPTIMAL", "objective_value": 0, "quality": None,
        "placements": [{"session_id": "A", "week": SEMAINE, "day": 0, "slot": 0, "course_code": "WRA",
                        "group_ids": ["but1-td-ab"], "teacher_codes": ["SAE"], "room_label": "H.101"}],
    }
    from datetime import date

    payload = build_payload(
        timetable, seances, GROUPES, calendar=CALENDRIER, semestre="S1", teacher_availability=disponibilites,
        sae_supervisor_dates={"SAE": {date.fromisoformat(quand)}},
    )
    (sae,) = [t for t in payload["teachers"] if t["code"] == "SAE"]
    assert [v["reason"] for v in sae["violations"]] == ["sae_supervision"]
    regle = next(c for c in payload["ruleChecks"] if c["id"] == "teacher_availability")
    assert regle["status"] == "pass"
