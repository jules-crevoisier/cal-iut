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
        "teacher_duos": etat.teacher_duos, "semestre_group": etat.semestre_group,
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
    etat.semestre_group = "odd"
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
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html=None: "msg_123")
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

    def _send(to, subject, text, html=None):
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


# --------------------------------------------------------------------------
# Contenu intelligent du mail — retour utilisateur 28/08/2026 : rappel des
# semestres couverts + alerte "séances à placer" quand elle s'applique.
# --------------------------------------------------------------------------


def _capturer_corps(monkeypatch) -> list[tuple[str, str | None]]:
    """`[(texte, html), ...]` — capture les DEUX versions envoyées à
    `send_email`, pour vérifier que l'alerte "à placer" existe aussi comme
    un vrai encart visuel côté HTML, pas seulement comme texte brut."""
    corps_captures: list[tuple[str, str | None]] = []

    def _send(to, subject, text, html=None):
        corps_captures.append((text, html))
        return "msg_ok"

    monkeypatch.setattr(mailer, "send_email", _send)
    monkeypatch.setattr(mailer, "personal_link", lambda code: "https://example.test/#vue=prof")
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr"},
    )
    return corps_captures


def test_le_mail_rappelle_les_semestres_couverts(etat_avec_seance, session_admin, monkeypatch) -> None:
    corps_captures = _capturer_corps(monkeypatch)
    client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})
    texte, _html = corps_captures[0]
    assert "S1, S3 et S5" in texte


def test_alerte_seances_a_placer_absente_si_tout_est_place(etat_avec_seance, session_admin, monkeypatch) -> None:
    corps_captures = _capturer_corps(monkeypatch)
    client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})
    texte, html = corps_captures[0]
    assert "à placer" not in texte
    assert "référent" not in texte
    assert "référent" not in (html or "")


def test_alerte_seances_a_placer_presente_si_pertinente(etat_avec_seance, session_admin, monkeypatch) -> None:
    """Ajoute une 2e séance pour KBR jamais placée (absente de
    `etat.timetable`, contrairement à `s1`) — même signal que l'écran
    « À placer » réel."""
    etat = get_state()
    manquante = SessionToPlace(
        id="s2", course_code="WR102", course_name="T2", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-cd"], teacher_codes=["KBR"],
    )
    etat.sessions = etat.sessions + [manquante]
    etat.sessions_by_id["s2"] = manquante

    corps_captures = _capturer_corps(monkeypatch)
    client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})
    texte, html = corps_captures[0]
    assert "n'ont pas encore pu être placées" in texte
    assert "référent" in texte
    # Le HTML doit porter un VRAI encart visuel (fond coloré), pas juste le
    # même texte sans forme — retour utilisateur : « pour que cela soit bien
    # lu dans le mail ».
    assert html is not None
    assert "référent" in html
    assert "background" in html


# --------------------------------------------------------------------------
# Aperçu avant envoi + suivi d'ouverture — retour utilisateur 28/08/2026.
# --------------------------------------------------------------------------


def test_l_apercu_rend_le_mail_reel(etat_avec_seance, session_admin, monkeypatch) -> None:
    """L'aperçu doit passer par la MÊME fonction que l'envoi : un aperçu
    calculé autrement finirait par diverger de ce qui part vraiment, ce qui
    est pire que pas d'aperçu."""
    monkeypatch.setenv("CAL_IUT_PUBLIC_URL", "https://exemple.test")
    corps = client.get("/mail/teacher-links/apercu/KBR").json()
    assert corps["subject"] == "Votre emploi du temps MMI"
    assert "Bonjour" in corps["text"]
    assert "https://exemple.test" in corps["text"]
    # Le pixel n'existe QUE dans la version HTML (un texte brut ne peut pas
    # porter d'image, et une URL nue y serait visible et inutile).
    assert "/mail/pixel/KBR.gif" in corps["html"]
    assert "/mail/pixel/" not in corps["text"]


def test_l_apercu_exige_une_session_admin(etat_avec_seance) -> None:
    assert client.get("/mail/teacher-links/apercu/KBR?t=KBR").status_code == 401


def test_le_pixel_est_accessible_sans_authentification(etat_avec_seance) -> None:
    """Indispensable : c'est le client mail de l'enseignant qui le charge,
    il ne peut présenter ni session ni lien perso."""
    reponse = client.get("/mail/pixel/KBR.gif")
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "image/gif"
    assert reponse.content[:6] == b"GIF89a"


def test_le_pixel_repond_200_meme_pour_un_code_inconnu(etat_avec_seance) -> None:
    """Une erreur afficherait une icône d'image cassée dans le mail d'un
    enseignant, pour un problème qui ne le concerne pas."""
    assert client.get("/mail/pixel/CODE-INEXISTANT.gif").status_code == 200


def test_l_ouverture_est_journalisee_puis_remontee(etat_avec_seance, session_admin, monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kyllian.bresson@univ-reims.fr"},
    )
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html=None: "msg_1")
    monkeypatch.setattr(mailer, "personal_link", lambda code: "https://exemple.test/#vue=prof")
    client.post("/mail/teacher-links/send", json={"codes": ["KBR"]})

    avant = next(t for t in client.get("/mail/teacher-links").json()["teachers"] if t["code"] == "KBR")
    assert avant["sent_at"] and avant["opened_at"] is None

    client.get("/mail/pixel/KBR.gif")
    apres = next(t for t in client.get("/mail/teacher-links").json()["teachers"] if t["code"] == "KBR")
    assert apres["opened_at"], "l'ouverture doit remonter dans l'annuaire d'envoi"


def test_une_ouverture_sans_envoi_prealable_est_ignoree(etat_avec_seance, session_admin) -> None:
    """Sinon une URL de pixel bricolée pourrait fabriquer de fausses
    ouvertures pour des enseignants jamais contactés."""
    client.get("/mail/pixel/KBR.gif")
    ligne = next(t for t in client.get("/mail/teacher-links").json()["teachers"] if t["code"] == "KBR")
    assert ligne["sent_at"] is None
    assert ligne["opened_at"] is None
