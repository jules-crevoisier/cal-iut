"""Présence des alternants FC : vérifiée par le solveur, oubliée partout ailleurs.

Trouvé le 27/08/2026 en auditant un run complété : 76 séances FC placées alors
que les étudiants étaient en entreprise. Le solveur impose cette règle comme
contrainte DURE (`add_student_presence_constraints`) ; le glisser-déposer, les
suggestions et la complétion automatique — tous construits sur
`_hard_constraint_context` — n'en avaient AUCUNE connaissance.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.ingestion.constraints_loader import StudentPresence
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

# Un alternant présent à l'IUT seulement le mercredi (semaines 10 à 20) — une
# fenêtre étroite, pour que le test distingue clairement présent/absent.
_PRESENCE = StudentPresence(
    parcours_keys=["BUT2-CREACOM-FC"],
    presence_dates={date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 18)},  # mercredis
)


def _seance_fc(sid: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WRA312M", course_name="T", semestre="S3",
        parcours="BUT2-CREACOM-FC", annee="BUT2", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but2-creacom-fc-td"], teacher_codes=["MRI"],
    )


@pytest.fixture
def client():
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "groups": etat.groups, "rooms": etat.rooms,
        "calendar": etat.calendar, "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability, "teacher_duos": etat.teacher_duos,
        "corrections": etat.corrections, "courses": etat.courses,
        "config_dir": etat.config_dir, "student_presences": etat.student_presences,
    }

    manquante = _seance_fc("manquante")
    ancre = _seance_fc("ancre")  # place tel quel : établit l'horizon (voir plus bas)
    etat.sessions = [manquante, ancre]
    etat.sessions_by_id = {manquante.id: manquante, ancre.id: ancre}
    # `_hard_constraint_context` déduit son horizon du planning DÉJÀ posé
    # (`max(p.week for p in state.timetable) + 1`) : sans une séance ancrée
    # loin dans le semestre, l'horizon resterait nul et aucune borne ne
    # s'appliquerait — pas un défaut du correctif, un artefact de ce fixture
    # isolé (en production, des centaines de séances couvrent déjà tout le
    # semestre avant que la complétion ne s'exécute).
    etat.timetable = [PlacedSessionWithRoom(
        session_id="ancre", week=22, day=0, slot=0, course_code="WRA312M",
        group_ids=["but2-creacom-fc-td"], teacher_codes=["MRI"],
    )]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.config_dir = ROOT / "data" / "config"
    etat.student_presences = [_PRESENCE]

    yield TestClient(app)

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_aucun_creneau_propose_ne_tombe_hors_semaine_de_presence(client):
    """Sans ce contrôle, un alternant se verrait proposer un cours un jour où
    il est en entreprise — l'écran « À placer » ne le distinguerait pas d'un
    créneau réellement valable."""
    corps = client.get("/placements/manquante/creneaux-libres?maximum=30").json()
    assert corps["creneaux"], "aucun créneau proposé — la fenêtre de présence est-elle trop étroite ?"
    for c in corps["creneaux"]:
        jour = date.fromisoformat(c["date"])
        assert jour in _PRESENCE.presence_dates, (
            f"{jour} proposé alors que l'étudiant est en entreprise ce jour-là"
        )


def test_placer_hors_presence_est_refuse_meme_en_forcant(client):
    """Jamais contournable — même traitement que le verrou PAC ou l'ordre
    pédagogique : aucune bonne raison ponctuelle ne justifie de programmer un
    cours pendant que l'étudiant est en entreprise."""
    etat = get_state()
    semaine, jour = etat.calendar.date_to_week_day(date(2026, 11, 5))  # jeudi, hors présence
    reponse = client.post("/placements/manquante/placer", json={
        "week": semaine, "day": jour, "slot": 1, "force": True,
    })
    assert reponse.status_code == 409, "un jour hors présence doit rester refusé même avec force=True"
    assert any(
        "institutionnellement" in m.lower() for m in reponse.json()["detail"]["hard_conflicts"]
    ), reponse.json()


def test_placer_pendant_la_presence_est_accepte(client):
    """Le contrôle ne doit pas être trop large : les vrais jours de présence
    restent utilisables."""
    etat = get_state()
    semaine, jour = etat.calendar.date_to_week_day(date(2026, 11, 4))  # mercredi de présence
    reponse = client.post("/placements/manquante/placer", json={
        "week": semaine, "day": jour, "slot": 1,
    })
    assert reponse.status_code == 200, reponse.text


def test_un_parcours_non_fc_n_est_jamais_restreint(client):
    """La règle ne doit toucher QUE les parcours FC déclarés — un parcours FI
    ne doit jamais se retrouver bridé par erreur.

    Comparé à une référence SANS aucune présence FC déclarée plutôt qu'à un
    ensemble de jours attendus codé en dur : BUT1 a ses propres événements
    institutionnels réels (rentrée, SAE), qui doivent rester identiques que
    `student_presences` contienne ou non une entrée FC — seule l'ISOLATION
    entre les deux mécanismes est ce qui doit être vérifié ici.
    """
    from cal_iut.api.main import _hard_constraint_context

    fi = SessionToPlace(
        id="fi", course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["MRI"],
    )
    etat = get_state()
    etat.sessions = etat.sessions + [fi]
    etat.sessions_by_id[fi.id] = fi

    etat.student_presences = [_PRESENCE]
    avec_presence_fc, _ = _hard_constraint_context(etat, fi)

    etat.student_presences = []
    sans_presence_fc, _ = _hard_constraint_context(etat, fi)

    assert avec_presence_fc == sans_presence_fc, (
        "la déclaration de présence FC d'un AUTRE parcours modifie les blocages d'un FI"
    )
