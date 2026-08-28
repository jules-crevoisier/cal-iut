"""Envoi automatique du lien perso par mail (`api/mailer.py`,
`POST /mail/teacher-links/send`) — retour utilisateur 28/08/2026 : « on veux
une fonctionnalité qui permet d'envoyer automatiquement un mail à chaque
prof avec leur lien ».

Ne fait JAMAIS de vrai appel réseau vers Resend : `mailer.send_email` est
monkeypatché partout ici — ces tests tournent sans `RESEND_API_KEY` ni accès
Internet, comme le reste de la suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import mailer
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
def etat_avec_seance():
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
    seance = SessionToPlace(
        id="s1", course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["KBR"],
    )
    etat.sessions = [seance]
    etat.sessions_by_id = {"s1": seance}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="s1", week=0, day=0, slot=0,
                               course_code="WR101", group_ids=["but1-td-ab"], teacher_codes=["KBR"]),
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


@pytest.fixture
def session_admin():
    """Connecte le client `TestClient` module-level avec une vraie session
    (mot de passe), nécessaire pour `require_admin_session`."""
    reponse = client.post("/auth/login", json={"password": "test-password"})
    assert reponse.status_code == 200
    yield
    client.post("/auth/logout")


def test_un_lien_perso_seul_est_refuse_sur_mail(etat_avec_seance) -> None:
    """Garde-fou supplémentaire (`require_admin_session`) : le paramètre `t`
    d'un lien personnel (public, cf. `api/auth.py`) passe `require_auth`
    mais ne doit PAS suffire ici, à la différence du reste de
    `_PROTECTED_PREFIXES` — sinon N'IMPORTE QUI avec un lien perso pourrait
    déclencher un envoi de mail en masse à tous les collègues."""
    reponse = client.get("/mail/teacher-links?t=KBR")
    assert reponse.status_code == 401


def test_sans_session_admin_c_est_refuse(etat_avec_seance) -> None:
    reponse = client.get("/mail/teacher-links")
    assert reponse.status_code == 401


def test_previsualisation_liste_les_profs_avec_et_sans_adresse(etat_avec_seance, session_admin, monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr"},
    )
    corps = client.get("/mail/teacher-links").json()
    assert corps["configured"] is False  # RESEND_API_KEY/CAL_IUT_PUBLIC_URL absents en test
    assert any(t["code"] == "KBR" and t["email"] == "kyllian.bresson@univ-reims.fr" for t in corps["teachers"])


def test_envoi_reussi_journalise_et_reapparait_comme_deja_envoye(etat_avec_seance, session_admin, monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr"},
    )
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text: "msg_123")
    monkeypatch.setattr(mailer, "personal_link", lambda code: "https://example.test/#vue=prof")

    reponse = client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})
    assert reponse.status_code == 200, reponse.text
    resultats = reponse.json()["results"]
    assert resultats == [{"code": "KBR", "ok": True, "error": None}]

    corps = client.get("/mail/teacher-links").json()
    ligne = next(t for t in corps["teachers"] if t["code"] == "KBR")
    assert ligne["sent_at"] is not None


def test_code_sans_adresse_connue_echoue_sans_appeler_l_envoi(etat_avec_seance, session_admin, monkeypatch) -> None:
    monkeypatch.setattr("cal_iut.ingestion.config_loader.load_teacher_contacts", lambda config_dir: {})
    appele = []
    monkeypatch.setattr(mailer, "send_email", lambda *a, **k: appele.append(1) or "x")

    reponse = client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})
    resultats = reponse.json()["results"]
    assert resultats == [{"code": "KBR", "ok": False, "error": "Aucune adresse connue pour ce trigramme."}]
    assert not appele


def test_resend_non_configure_donne_une_erreur_explicite_par_destinataire(etat_avec_seance, session_admin, monkeypatch) -> None:
    """Sans mock de `send_email`/`personal_link`, le vrai code s'exécute et
    doit lever `MailerNotConfigured` (ni `RESEND_API_KEY` ni
    `CAL_IUT_PUBLIC_URL` en environnement de test) — jamais un envoi
    silencieusement ignoré. Le lien personnel est construit AVANT l'appel
    Resend : c'est `CAL_IUT_PUBLIC_URL` qui manque en premier ici."""
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr"},
    )
    reponse = client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})
    resultats = reponse.json()["results"]
    assert resultats[0]["ok"] is False
    assert "non configuré" in resultats[0]["error"]


def test_un_echec_n_interrompt_pas_les_autres_envois(etat_avec_seance, session_admin, monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr", "XYZ": "xyz@example.test"},
    )

    def _send(to, subject, text):
        if to == "xyz@example.test":
            raise RuntimeError("panne réseau simulée")
        return "msg_ok"

    monkeypatch.setattr(mailer, "send_email", _send)
    monkeypatch.setattr(mailer, "personal_link", lambda code: "https://example.test/#vue=prof")

    reponse = client.post("/mail/teacher-links/send", json={"codes": ["KBR", "XYZ"]})
    resultats = {r["code"]: r for r in reponse.json()["results"]}
    assert resultats["KBR"]["ok"] is True
    assert resultats["XYZ"]["ok"] is False
    assert "panne réseau simulée" in resultats["XYZ"]["error"]
