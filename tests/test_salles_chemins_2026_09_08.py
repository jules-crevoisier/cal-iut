"""Les DEUX autres chemins qui posent une salle, et que rien ne couvrait.

Retour utilisateur 08/09/2026 : « peux-tu mettre des vrais tests là-dessus,
ça fait je ne sais pas combien de temps que ça casse » — dit après qu'un
changement de salle a répondu 200 sans rien changer.

`PATCH /placements/{id}/salle` est testé depuis le 28/08
(`test_changer_salle_2026_08_28.py`). Mais une salle peut être posée par
deux autres routes, et aucune n'était vérifiée sur ce point :

1. `PATCH /placements/personnalisees/{id}` — la salle n'y est lue QUE si
   `week`, `day` et `slot` sont fournis tous les trois, parce que le
   `room_id` n'est transmis qu'à l'intérieur du repositionnement. Envoyer le
   seul `room_id` rendait donc **200 avec l'ancienne salle** : la réponse
   affirme le succès d'une action qui n'a pas eu lieu. Constaté en
   production en corrigeant la salle de « Présentation des services ».

2. `POST /placements/{id}/placer` — pose au planning une séance qui n'y
   était pas (colonne « À placer »). Un `room_id` inconnu y retombait
   silencieusement sur `None` : la séance était placée SANS salle, sans que
   rien ne le signale.

Ces deux défauts sont de la même famille que ceux de la veille sur le
worker Celcat : une opération qui échoue en annonçant qu'elle a réussi. Un
utilisateur ne peut pas s'en apercevoir autrement qu'en revenant vérifier à
la main — donc, en pratique, jamais.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

client = TestClient(app)

# Semaine lointaine : `_check_move_editable` refuse une semaine passée ou en
# cours, ce qui ferait échouer ces tests pour une raison sans rapport.
SEMAINE = 12


def _seance(sid: str, *, personnalisee: bool = False) -> SessionToPlace:
    s = SessionToPlace(
        id=sid,
        course_code=f"WR{sid}",
        course_name="Test",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=["but1-td-ab"],
        teacher_codes=["KBR"],
    )
    if personnalisee:
        s.metadata["custom_session"] = True
    return s


@pytest.fixture
def etat():
    etat = get_state()
    ancien = {
        k: getattr(etat, k)
        for k in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "config_dir", "student_presences",
            "corrections", "courses", "teacher_duos", "semestre_group",
        )
    }
    # `perso` est AU PLANNING (on lui changera la salle) ; `a_placer` ne l'est
    # pas encore (colonne « À placer »).
    perso = _seance("perso", personnalisee=True)
    a_placer = _seance("a_placer")
    etat.sessions = [perso, a_placer]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="perso", week=SEMAINE, day=0, slot=0, course_code="WRperso",
            group_ids=["but1-td-ab"], teacher_codes=["KBR"],
            room_id="h101", room_label="H.101",
        )
    ]
    etat.rooms = [
        Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h103", label="H.103", capacity=30, room_type=RoomType.STANDARD),
    ]
    etat.groups = GROUPES
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.config_dir = ROOT / "data" / "config"
    etat.student_presences = []
    etat.corrections = []
    etat.courses = []
    etat.teacher_duos = []
    etat.semestre_group = "odd"
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


@pytest.fixture(autouse=True)
def _connecte(db_isole):
    creer_compte_actif_et_connecter(client, role="admin")
    yield


# ==========================================================================
# 1. Séance personnalisée : changer la SEULE salle
# ==========================================================================


def test_changer_la_seule_salle_d_une_seance_personnalisee(etat) -> None:
    """Le cas constaté en production : `room_id` seul, sans repositionner.

    C'est la forme naturelle de la demande (« mets-la en A.018 »), et elle
    répondait 200 en gardant l'ancienne salle."""
    reponse = client.patch("/placements/personnalisees/perso", json={"room_id": "h103"})

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "h103", (
        "la salle demandée doit être appliquée, ou l'appel doit échouer — "
        "jamais rendre 200 en gardant l'ancienne"
    )
    assert get_state().timetable[0].room_id == "h103", "l'état doit refléter la réponse"


def test_changer_la_salle_sans_deplacer_ne_bouge_pas_le_creneau(etat) -> None:
    """Corollaire indispensable : honorer `room_id` seul ne doit pas
    devenir un prétexte à déplacer la séance."""
    client.patch("/placements/personnalisees/perso", json={"room_id": "h103"})

    place = get_state().timetable[0]
    assert (place.week, place.day, place.slot) == (SEMAINE, 0, 0)


def test_salle_inconnue_sur_une_seance_personnalisee_est_refusee(etat) -> None:
    """Un identifiant de salle qui n'existe pas est une erreur d'appel, pas
    une raison de retirer la salle en silence."""
    reponse = client.patch("/placements/personnalisees/perso", json={"room_id": "fantome"})

    assert reponse.status_code in (400, 404), reponse.text
    assert get_state().timetable[0].room_id == "h101", "la salle d'origine doit être intacte"


def test_repositionner_avec_une_salle_marche_toujours(etat) -> None:
    """Non-régression : le chemin qui fonctionnait — position + salle — ne
    doit pas être cassé par la correction du chemin « salle seule »."""
    reponse = client.patch(
        "/placements/personnalisees/perso",
        json={"week": SEMAINE, "day": 1, "slot": 2, "room_id": "h103"},
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["week"], corps["day"], corps["slot"]) == (SEMAINE, 1, 2)
    assert corps["room_id"] == "h103"


# ==========================================================================
# 2. « À placer » : poser une séance AVEC sa salle
# ==========================================================================


def test_placer_une_seance_honore_la_salle_demandee(etat) -> None:
    reponse = client.post(
        "/placements/a_placer/placer",
        json={"week": SEMAINE, "day": 1, "slot": 1, "room_id": "h103"},
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "h103"
    pose = next(p for p in get_state().timetable if p.session_id == "a_placer")
    assert pose.room_id == "h103"


def test_placer_avec_une_salle_inconnue_est_refuse(etat) -> None:
    """Sans ça, la séance est posée SANS salle et rien ne le dit : une salle
    manquante ne se voit qu'en rouvrant le planning — donc trop tard."""
    reponse = client.post(
        "/placements/a_placer/placer",
        json={"week": SEMAINE, "day": 1, "slot": 1, "room_id": "fantome"},
    )

    assert reponse.status_code in (400, 404), reponse.text
    assert not any(p.session_id == "a_placer" for p in get_state().timetable), (
        "un placement refusé ne doit rien laisser au planning"
    )


def test_placer_sans_salle_reste_possible(etat) -> None:
    """Retour utilisateur du 29/08/2026 : « s'il n'y a pas la salle de CM
    disponible il faut laisser la salle vide, elle sera rentrée par la
    suite ». Refuser une salle INCONNUE ne doit pas interdire l'ABSENCE de
    salle."""
    reponse = client.post(
        "/placements/a_placer/placer", json={"week": SEMAINE, "day": 1, "slot": 1}
    )

    assert reponse.status_code == 200, reponse.text
