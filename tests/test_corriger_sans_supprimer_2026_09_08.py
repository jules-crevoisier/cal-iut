"""Pouvoir corriger SANS supprimer, quand quelqu'un travaille dans Celcat.

Situation du 08/09/2026 : Kyllian Bresson corrige Celcat à la main pendant
que Jules regarde la comparaison. Son raisonnement :

    « théoriquement on ne doit plus toucher à cette semaine, mais si on
      vérifie avant, on va tomber sur "il n'y a plus rien à faire", et au
      pire on finira et avancera son travail, non ? »

IL A RAISON POUR DEUX TIERS. Un `ecart` et une `absente_celcat` sont
auto-limitants : si Kyllian a déjà corrigé, la comparaison rend
« identique » et aucun job n'est enfilé. Au pire on refait ce qui est déjà
fait, ce qui ne coûte rien.

LA SUPPRESSION, ELLE, NE L'EST PAS. Un évènement « en trop » peut l'être
pour deux raisons indiscernables : c'est un vrai doublon, ou notre
rapprochement l'a raté (groupe nommé autrement, salle inconnue, module hors
catalogue). Sur les neuf « en trop » de la semaine 1, quatre portaient des
`event_id` en 1953xxx, très supérieurs aux autres — donc créés à l'instant,
et sur les matières mêmes que Kyllian était en train de corriger. Les
supprimer aurait défait son travail, et une suppression ne se rattrape pas.

D'où ce mode : pousser les modifications et les créations, laisser les
suppressions de côté. C'est le geste qui donne raison à Jules sans lui faire
courir le seul risque irréversible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import instantane
from cal_iut.celcat.file_attente import lister, vider
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, Room, RoomType, SessionType, Teacher, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE, INDICE = 1, 3
GROUPE_CELCAT = "BUT MMI S1 TD AB"


def _cours() -> Course:
    mri = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    return Course(
        code="WR101", name="Cours", semestre="S1", parcours="BUT1", annee="BUT1", lead=mri,
        profs=[TeacherBlock(teacher=mri, block="1", td=17, nbGpTd=1, nbGpTp=1)],
        volumes={"cm": 0, "td": 17, "tp": 0}, groupes_td=1, groupes_tp=1,
        progression_defined=False, seance_sequence=[], ordonnancement=[],
    )


@pytest.fixture
def client(db_isole):
    etat = get_state()
    champs = (
        "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
        "current_run_id", "teacher_availability", "teacher_duos", "corrections",
        "courses", "config_dir",
    )
    ancien = {c: getattr(etat, c) for c in champs}

    s = SessionToPlace(
        id="s-a-corriger", course_code="WR101", course_name="Cours", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD, sequence_order=1,
        group_ids=["but1-td-ab"], teacher_codes=["MRI"], duration_slots=1,
    )
    etat.sessions = [s]
    etat.sessions_by_id = {s.id: s}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id=s.id, week=SEMAINE, day=0, slot=0, course_code="WR101",
            group_ids=["but1-td-ab"], teacher_codes=["MRI"],
            room_id="h101", room_label="H.101",
        )
    ]
    etat.groups = GROUPES
    etat.rooms = [Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD)]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = [_cours()]
    etat.config_dir = ROOT / "data" / "config"

    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="admin")
    c.patch("/celcat/saisie", json={"active": True})
    vider()

    # Celcat : la séance est là mais dans la mauvaise salle (un ÉCART), et un
    # évènement inconnu de cal-iut traîne à côté (un EN TROP).
    instantane.enregistrer(
        [
            {
                "event_id": 1931666, "groupe": GROUPE_CELCAT, "jour": 0,
                "heure_debut": "08:00", "heure_fin": "09:30", "salle": "H.007",
                "categorie": "[TD]", "module": "WR101", "semaine": INDICE,
            },
            {
                "event_id": 1953811, "groupe": GROUPE_CELCAT, "jour": 0,
                "heure_debut": "11:00", "heure_fin": "12:30", "salle": "H.101",
                "categorie": "[TD]", "module": "WR101", "semaine": INDICE,
            },
        ],
        groupes=[GROUPE_CELCAT],
    )
    yield c

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_par_defaut_les_suppressions_partent(client) -> None:
    """Non-régression : le bouton existant ne change pas de comportement."""
    reponse = client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}")

    assert reponse.status_code == 200, reponse.text
    actions = [j["action"] for j in lister()]
    assert "delete" in actions, actions
    assert reponse.json()["suppressions"] == 1


def test_sans_supprimer_les_modifications_partent_quand_meme(client) -> None:
    """Le geste demandé : avancer le travail sans rien détruire."""
    reponse = client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}&supprimer=false")

    assert reponse.status_code == 200, reponse.text
    jobs = lister()
    assert [j["action"] for j in jobs] == ["update"], jobs
    corps = reponse.json()
    assert corps["modifications"] == 1
    assert corps["suppressions"] == 0


def test_sans_supprimer_le_compte_rendu_dit_ce_qui_a_ete_epargne(client) -> None:
    """Une suppression écartée en silence se lirait « il n'y en avait pas » :
    l'écran doit dire qu'elles ont été laissées de côté, et combien."""
    corps = client.post(
        f"/celcat/comparaison/corriger?semaine={SEMAINE}&supprimer=false"
    ).json()

    assert corps["suppressions_ignorees"] == 1
    assert "suppression" in corps["message"].lower()


def test_sans_supprimer_ne_cree_pas_non_plus_de_doublon(client) -> None:
    """Le garde-fou : écarter les suppressions ne doit pas transformer un
    « en trop » en autre chose. Il est simplement laissé tel quel."""
    client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}&supprimer=false")

    assert all(j["action"] != "create" for j in lister()), lister()


def test_la_resynchronisation_sait_aussi_epargner_les_suppressions(client) -> None:
    """Le geste complet et sûr : purger les jobs aveugles, reconstruire ce qui
    diverge, sans rien détruire.

    Sans cette option, « Repartir de la comparaison » restait inutilisable
    tant que quelqu'un travaillait dans Celcat — alors que c'est précisément
    le moment où la file est le plus encombrée de jobs périmés.
    """
    reponse = client.post(
        f"/celcat/file/resynchroniser?semaines={SEMAINE}&supprimer=false"
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["suppressions"] == 0
    assert corps["suppressions_ignorees"] == 1
    assert all(j["action"] != "delete" for j in lister()), lister()
    assert "suppression" in corps["message"].lower()
