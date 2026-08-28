"""Le jeton d'accès personnel enseignant (`?t=<trigramme>.<hmac>`).

Bug réel trouvé le 28/08/2026 en vérifiant un lien avant un envoi par mail
(retour utilisateur : « ok on veux une fonctionnalité qui permet d'envoyer
automatiquement un mail à chaque prof avec leur lien ») : `html_view.py::
build_payload` ne mettait dans `teacherTokens[code]` que le hmac seul
(`make_teacher_token(code)`), jamais le trigramme devant le point attendu par
`verify_teacher_access_param` (qui en a besoin pour savoir À QUI le jeton
appartient). Résultat, invisible sans test dédié : chaque lien personnel
généré depuis le 28/08/2026 (date d'introduction du mot de passe partagé)
renvoyait sur l'écran de mot de passe au lieu du planning — `"." not in
value` faisait toujours échouer `verify_teacher_access_param`.
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


def test_le_format_code_point_jeton_authentifie() -> None:
    """Le format documenté (`<trigramme>.<hmac>`) doit réellement passer."""
    valeur = f"KBR.{auth.make_teacher_token('KBR')}"
    assert auth.verify_teacher_access_param(valeur) is True


def test_le_hmac_seul_sans_trigramme_est_refuse() -> None:
    """Exactement le bug du 28/08/2026 : sans le `code.` devant, jamais valide."""
    valeur = auth.make_teacher_token("KBR")
    assert auth.verify_teacher_access_param(valeur) is False


def test_un_lien_avec_le_bon_format_traverse_le_mot_de_passe() -> None:
    """Bout en bout, sans login préalable : `?t=<code>.<hmac>` doit suffire
    à passer le middleware `require_auth` sur une route protégée."""
    valeur = f"KBR.{auth.make_teacher_token('KBR')}"
    reponse = client.get(f"/meta?t={valeur}")
    assert reponse.status_code == 200, reponse.text


def test_un_lien_avec_seulement_le_hmac_est_bloque() -> None:
    """Reproduit exactement ce que le front envoyait avant le correctif."""
    valeur = auth.make_teacher_token("KBR")
    reponse = client.get(f"/meta?t={valeur}")
    assert reponse.status_code == 401


@pytest.fixture
def etat_avec_seance():
    """État minimal, monté à la main (même schéma que
    `test_ordre_meme_semaine_2026_08_27.py`) — exerce le VRAI chemin de
    production (`GET /app-state` -> `build_payload`), pas seulement les
    primitives `auth.py`, qui elles étaient déjà correctes avant ce
    correctif : le bug vivait dans la ligne qui les assemble."""
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


def test_app_state_produit_bien_le_format_complet(etat_avec_seance) -> None:
    """Le vrai producteur de la valeur (`html_view.build_payload`, via le
    vrai endpoint `/app-state`) — c'est LÀ que le bug vivait réellement."""
    reponse = client.post("/auth/login", json={"password": "test-password"})
    assert reponse.status_code == 200
    corps = client.get("/app-state").json()
    assert corps["teacherTokens"]["KBR"] == f"KBR.{auth.make_teacher_token('KBR')}"
