"""Flux .ics abonnable (`/ics/prof/{code}.ics`, `/ics/groupe/{id}.ics`) —
retour utilisateur 28/08/2026 (relayé depuis Discord) : « pour le ics on
pourrait peut-être faire un lien qui s'update automatique ? ».
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

client = TestClient(app)


@pytest.fixture
def etat_avec_seances():
    """`but1-td-ab` (TD) + `but1-promo` (CM, sa cohorte) + une séance d'un
    AUTRE prof/groupe, pour vérifier que le flux ne mélange pas tout."""
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "groups": etat.groups, "rooms": etat.rooms,
        "calendar": etat.calendar, "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability,
        "config_dir": etat.config_dir, "student_presences": etat.student_presences,
        "corrections": etat.corrections, "courses": etat.courses,
        "teacher_duos": etat.teacher_duos,
    }
    td = SessionToPlace(
        id="td1", course_code="WR101", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["KBR"],
    )
    cm = SessionToPlace(
        id="cm1", course_code="WR102", course_name="Communication", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
        sequence_order=1, group_ids=["but1-promo"], teacher_codes=["ALO"],
    )
    autre = SessionToPlace(
        id="autre1", course_code="WR999", course_name="Autre cours", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-cd"], teacher_codes=["JSA"],
    )
    # Bloc de 3h ("2×1h30 collées", `double_sessions.yaml`) — retour
    # utilisateur 04/09/2026 : WSA501D affichait bien 9h30-12h30 dans la Vue
    # Promo (duration_slots=2), mais le flux .ics s'arrêtait à 11h.
    double = SessionToPlace(
        id="double1", course_code="WSA501D", course_name="SAE web", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["KBR"], duration_slots=2,
    )
    etat.sessions = [td, cm, autre, double]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="td1", week=0, day=0, slot=0,
                               course_code="WR101", group_ids=["but1-td-ab"], teacher_codes=["KBR"],
                               room_id="h001", room_label="H.001"),
        PlacedSessionWithRoom(session_id="cm1", week=0, day=1, slot=1,
                               course_code="WR102", group_ids=["but1-promo"], teacher_codes=["ALO"],
                               room_id="h018", room_label="H.018"),
        PlacedSessionWithRoom(session_id="autre1", week=0, day=2, slot=2,
                               course_code="WR999", group_ids=["but1-td-cd"], teacher_codes=["JSA"]),
        PlacedSessionWithRoom(session_id="double1", week=0, day=3, slot=1,
                               course_code="WSA501D", group_ids=["but1-td-ab"], teacher_codes=["KBR"],
                               room_id="h205", room_label="H.205"),
    ]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.config_dir = ROOT / "data" / "config"
    etat.student_presences = []
    etat.corrections = []
    etat.courses = []
    etat.teacher_duos = []
    yield
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_sans_t_c_est_bloque(etat_avec_seances) -> None:
    reponse = client.get("/ics/prof/KBR.ics")
    assert reponse.status_code == 401


def test_flux_prof_contient_bien_du_icalendar(etat_avec_seances) -> None:
    reponse = client.get("/ics/prof/KBR.ics?t=KBR")
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"].startswith("text/calendar")
    corps = reponse.text
    assert corps.startswith("BEGIN:VCALENDAR")
    assert corps.rstrip().endswith("END:VCALENDAR")
    assert "WR101" in corps
    assert "H.001" in corps
    # UID stable sur le session_id, pas sur semaine/jour/créneau — c'est ce
    # qui permet à un agenda de reconnaître le même événement après un
    # déplacement plutôt que d'en dupliquer un nouveau.
    assert "UID:prof-KBR-td1@cal-iut" in corps


def test_flux_annonce_un_rafraichissement_d_une_heure(etat_avec_seances) -> None:
    """Retour utilisateur (04/09/2026) : « en temps réel ou 1h max » — ramené
    de PT6H à PT1H, le maximum qu'on promet (un simple hint ICS, pas garanti
    par tous les agendas — cf. `ics_feed.py::build_ics`)."""
    corps = client.get("/ics/prof/KBR.ics?t=KBR").text
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT1H" in corps
    assert "X-PUBLISHED-TTL:PT1H" in corps
    assert "PT6H" not in corps


def test_flux_n_est_jamais_mis_en_cache_intermediaire(etat_avec_seances) -> None:
    """Le contenu est recalculé en direct sur `state.timetable` à chaque
    requête (rien n'est mis en cache côté serveur) — `no-store` empêche un
    proxy/CDN intermédiaire d'en garder une vieille copie."""
    reponse = client.get("/ics/prof/KBR.ics?t=KBR")
    assert "no-store" in reponse.headers.get("cache-control", "")


def test_flux_respecte_duration_slots_pour_un_bloc_de_3h(etat_avec_seances) -> None:
    """Retour utilisateur (04/09/2026, capture d'écran de la Vue Promo à
    l'appui) : « j'ai bien une séance à 11h to 12h30 » — un bloc de 3h
    (`duration_slots=2`, ex. WSA501D) se terminait sur l'heure de fin du
    SEUL créneau de départ, tronquant silencieusement la seconde moitié."""
    corps = client.get("/ics/prof/KBR.ics?t=KBR").text
    evenement = corps.split("UID:prof-KBR-double1@cal-iut")[1].split("END:VEVENT")[0]
    assert "DTSTART" in evenement and "T093000" in evenement.split("DTEND")[0]
    assert "T123000" in evenement.split("DTEND")[1], (
        "la fin doit couvrir les 2 créneaux (9h30-12h30), pas s'arrêter à 11h"
    )


def test_flux_prof_ne_contient_pas_les_seances_d_un_autre(etat_avec_seances) -> None:
    corps = client.get("/ics/prof/KBR.ics?t=KBR").text
    assert "WR999" not in corps


def test_flux_groupe_fusionne_la_cohorte(etat_avec_seances) -> None:
    """`but1-td-ab` doit inclure sa propre séance ET le CM de sa promo
    (`but1-promo`, fusionné via `expand_group_filter`, même mécanisme que
    `groupCohort` côté page perso) — mais pas les séances d'un autre TD."""
    corps = client.get("/ics/groupe/but1-td-ab.ics?t=but1-td-ab").text
    assert "WR101" in corps
    assert "WR102" in corps
    assert "WR999" not in corps


def test_flux_groupe_inconnu_donne_un_404(etat_avec_seances) -> None:
    reponse = client.get("/ics/groupe/inconnu.ics?t=inconnu")
    assert reponse.status_code == 404
