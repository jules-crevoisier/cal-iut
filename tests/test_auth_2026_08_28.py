"""Le paramètre d'accès des liens personnels (`?t=<code>`).

Historique (tout dans la même journée) : un jeton HMAC signé d'abord (retour
utilisateur, choisi explicitement : « jeton secret par lien (Recommandé) »),
réservé aux profs — jamais implémenté pour les groupes, ce qui cassait
"Aucun planning résolu" sur un vrai lien de groupe ouvert en navigation
privée (fonctionnait par accident en navigation normale, une session admin
traînant déjà en cookie). Retour utilisateur final, après explication du
compromis : « pour les lien groupe et prof on s'en fiche on veut qu'il soit
public » — `t` n'est donc plus vérifié cryptographiquement, sa seule
présence suffit désormais, pour les deux types de lien.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api import auth
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


@pytest.fixture(autouse=True)
def _sans_session():
    """Repart d'un client SANS cookie avant chaque test. Le `TestClient` est
    partagé par le module et conserve les cookies : un test qui se connecte
    laissait sa session active pour les suivants, si bien qu'un test censé
    vérifier l'accès PUBLIC recevait en réalité le payload admin — il
    passait isolément et échouait dans la suite complète. Chaque test
    déclare donc désormais son authentification lui-même."""
    client.cookies.clear()
    yield
    client.cookies.clear()


def test_une_valeur_non_vide_authentifie() -> None:
    assert auth.verify_personal_link_param("KBR") is True
    assert auth.verify_personal_link_param("but1-td-ab") is True
    assert auth.verify_personal_link_param("n'importe quoi") is True


def test_valeur_vide_ou_absente_est_refusee() -> None:
    assert auth.verify_personal_link_param("") is False
    assert auth.verify_personal_link_param(None) is False


def test_un_lien_avec_n_importe_quel_code_traverse_le_mot_de_passe() -> None:
    """Bout en bout, sans login préalable : `?t=<code>` suffit à passer le
    middleware `require_auth` sur une route protégée — peu importe le code."""
    reponse = client.get("/meta?t=KBR")
    assert reponse.status_code == 200, reponse.text


def test_sans_parametre_t_c_est_bloque() -> None:
    reponse = client.get("/meta")
    assert reponse.status_code == 401


@pytest.fixture
def etat_avec_seance():
    """État minimal, monté à la main (même schéma que
    `test_ordre_meme_semaine_2026_08_27.py`) — exerce le VRAI chemin de
    production (`GET /app-state` -> `build_payload`)."""
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


def test_app_state_expose_le_code_en_clair_pour_profs_et_groupes(etat_avec_seance) -> None:
    """Le vrai producteur du payload (`html_view.build_payload`, via le vrai
    endpoint `/app-state`) — `teacherTokens`/`groupTokens` associent
    maintenant chaque code à lui-même, plus un jeton signé."""
    reponse = client.post("/auth/login", json={"password": "test-password"})
    assert reponse.status_code == 200
    corps = client.get("/app-state").json()
    assert corps["teacherTokens"]["KBR"] == "KBR"
    assert corps["groupTokens"]["but1-td-ab"] == "but1-td-ab"


# --------------------------------------------------------------------------
# Données personnelles hors du payload public — retour utilisateur
# 28/08/2026 : « on veut cacher les données personnelles, il faut juste que
# les liens des profs et des parcours soient simples d'accès sans mot de
# passe ».
# --------------------------------------------------------------------------


def test_un_lien_public_n_expose_ni_mails_ni_contraintes(etat_avec_seance) -> None:
    corps = client.get("/app-state?t=KBR").json()
    assert corps["teacherEmails"] == {}
    assert corps["teachers"] == []
    # Données d'administration, jamais affichées en lecture seule.
    assert corps["seancesNonPlacees"] == []
    assert corps["ruleChecks"] == []
    assert corps["exceptions"] == []


def test_un_lien_public_garde_de_quoi_afficher_le_planning(etat_avec_seance) -> None:
    """Le filtrage ne doit pas casser ce que la page perso affiche vraiment :
    séances, noms d'enseignants, semaines, groupes."""
    corps = client.get("/app-state?t=KBR").json()
    assert corps["rows"], "les séances doivent rester"
    assert corps["teacherLabels"], "les noms restent : ils figurent sur tout emploi du temps"
    assert corps["weekRows"] and corps["groupLabels"]
    assert corps["teacherTokens"] and corps["groupTokens"]


def test_une_session_admin_recoit_le_payload_complet(etat_avec_seance, monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr"},
    )
    assert client.post("/auth/login", json={"password": "test-password"}).status_code == 200
    corps = client.get("/app-state").json()
    assert corps["teacherEmails"] == {"KBR": "kyllian.bresson@univ-reims.fr"}
