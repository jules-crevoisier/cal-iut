"""La file d'attente Celcat se reconstruit depuis la COMPARAISON.

Demande utilisateur 08/09/2026 : « c'est possible de virer tout ce qui n'est
pas nécessaire et repartir uniquement de la comparaison », « on veut
uniquement modifier ce qui ne va pas ».

CE QUI N'ALLAIT PAS. `executer_job_nuit` enfile une CRÉATION pour chaque
séance dont le journal ignore l'`event_id`, sans jamais regarder ce que
Celcat contient déjà. Le journal étant quasi vide (le worker n'avait jamais
rien écrit avant le 08/09/2026), cela a produit 409 créations pour les
semaines 1, 2 et 3 — alors que la comparaison, elle, dit exactement :

    identique      : 250   -> RIEN à faire
    ecart          :  21   -> modifier (l'évènement existe, on a son event_id)
    absente_celcat :  60   -> créer
    en_trop_celcat :  24   -> supprimer

Soit 105 jobs utiles au lieu de 491. Les ~350 créations superflues visaient
des cours que Celcat possède déjà : au mieux elles échouent, au pire elles
posent un doublon — `creer_manquants` n'ayant aucun garde-fou pour ça.

CE QUI CHANGE. Une resynchronisation qui, pour les semaines demandées,
retire les jobs existants et les reconstruit depuis la comparaison. La
comparaison devient la SOURCE UNIQUE de ce qu'il y a à faire, ce qui est
aussi la seule définition qui reste juste quand quelqu'un modifie Celcat à
la main : ce qui concorde n'engendre aucun job, quelle qu'en soit l'origine.

PORTÉE LIMITÉE AUX SEMAINES DEMANDÉES. Vider la file entière perdrait les
jobs des semaines qu'on ne reconstruit pas — un déplacement de séance en
semaine 12 n'a pas à disparaître parce qu'on resynchronise la semaine 1.
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
from cal_iut.celcat.file_attente import enfiler, lister, vider
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, Room, RoomType, SessionType, Teacher, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
# Semaine 1 du planning = indice 3 du masque Celcat (lundi 2026-09-07).
SEMAINE, INDICE = 1, 3
GROUPE_CELCAT = "BUT MMI S1 TD AB"
EVENT_ID = 1931709


def _seance(sid: str, code: str = "WR101") -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code=code,
        course_name="Cours",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=["but1-td-ab"],
        teacher_codes=["MRI"],
        duration_slots=1,
    )


def _cours(code: str = "WR101") -> Course:
    mri = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    return Course(
        code=code, name="Cours", semestre="S1", parcours="BUT1", annee="BUT1", lead=mri,
        profs=[TeacherBlock(teacher=mri, block="1", td=17, nbGpTd=1, nbGpTp=1)],
        volumes={"cm": 0, "td": 17, "tp": 0}, groupes_td=1, groupes_tp=1,
        progression_defined=False, seance_sequence=[], ordonnancement=[],
    )


def _evenement(*, event_id: int, heure: str, salle: str, module: str = "WR101") -> dict:
    """Un évènement tel que le sidecar le dépose dans l'instantané."""
    return {
        "event_id": event_id,
        "groupe": GROUPE_CELCAT,
        "jour": 0,
        "heure_debut": heure,
        "heure_fin": "09:30",
        "salle": salle,
        "categorie": "[TD]",
        "enseignant": "Riguet",
        "module": module,
        "semaine": INDICE,
        "protected": "N",
    }


@pytest.fixture
def client(db_isole):
    etat = get_state()
    champs = (
        "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
        "current_run_id", "teacher_availability", "teacher_duos", "corrections",
        "courses", "config_dir",
    )
    ancien = {c: getattr(etat, c) for c in champs}

    s = _seance("s-identique")
    etat.sessions = [s]
    etat.sessions_by_id = {s.id: s}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="s-identique", week=SEMAINE, day=0, slot=0,
            course_code="WR101", group_ids=["but1-td-ab"], teacher_codes=["MRI"],
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
    yield c

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _resync(client, semaines="1"):
    return client.post(f"/celcat/file/resynchroniser?semaines={semaines}")


def test_une_seance_identique_ne_produit_aucun_job(client) -> None:
    """LE cœur de la demande : « on veut uniquement modifier ce qui ne va
    pas ». Celcat a déjà cette séance, au bon créneau, dans la bonne salle —
    il n'y a rien à faire, et surtout rien à créer."""
    instantane.enregistrer(
        [_evenement(event_id=EVENT_ID, heure="08:00", salle="H.101")], groupes=[GROUPE_CELCAT]
    )
    enfiler({"action": "create", "session_id": "s-identique", "semaine": SEMAINE})

    reponse = _resync(client)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["total"] == 0, f"une séance identique ne doit rien engendrer : {corps}"
    assert lister() == [], "la création aveugle doit avoir été retirée"


def test_un_ecart_devient_une_modification_avec_le_vrai_event_id(client) -> None:
    """Jamais une création : créer poserait un doublon à côté de l'évènement
    existant. C'est exactement le risque des 350 créations superflues."""
    instantane.enregistrer(
        [_evenement(event_id=EVENT_ID, heure="08:00", salle="H.007")], groupes=[GROUPE_CELCAT]
    )

    reponse = _resync(client)

    assert reponse.status_code == 200, reponse.text
    jobs = lister()
    assert len(jobs) == 1, f"un seul job attendu, reçu {jobs}"
    assert jobs[0]["action"] == "update"
    assert jobs[0]["event_id"] == EVENT_ID
    assert reponse.json()["creations"] == 0


def test_une_seance_absente_devient_une_creation(client) -> None:
    """Non-régression : le filtre ne doit pas empêcher les VRAIES créations —
    60 séances manquent réellement dans Celcat."""
    # Relevé RÉEL sans cette séance : un relevé vide est désormais refusé
    # comme une absence de relevé (les deux mènent à créer tout le planning).
    # L'évènement témoin est posé sur une AUTRE semaine, sans quoi il
    # ressortirait lui-même « en trop » et ajouterait une suppression au lot.
    instantane.enregistrer(
        [
            {
                **_evenement(event_id=999999, heure="08:00", salle="H.101", module="WR999"),
                "semaine": INDICE + 10,
            }
        ],
        groupes=[GROUPE_CELCAT],
    )

    reponse = _resync(client)

    jobs = lister()
    assert reponse.status_code == 200, reponse.text
    assert len(jobs) == 1 and jobs[0]["action"] == "create", jobs
    assert reponse.json()["creations"] == 1


def test_la_resynchro_remplace_les_jobs_aveugles(client) -> None:
    """Le geste demandé : « virer tout ce qui n'est pas nécessaire ». Cinq
    créations enfilées à l'aveugle sur la semaine, une seule séance qui
    diverge réellement -> il ne doit rester qu'un job."""
    instantane.enregistrer(
        [_evenement(event_id=EVENT_ID, heure="08:00", salle="H.007")], groupes=[GROUPE_CELCAT]
    )
    for i in range(5):
        enfiler({"action": "create", "session_id": f"s-aveugle-{i}", "semaine": SEMAINE})

    reponse = _resync(client)

    assert reponse.status_code == 200, reponse.text
    jobs = lister()
    assert len(jobs) == 1, f"les jobs aveugles doivent disparaître, reste : {jobs}"
    assert jobs[0]["action"] == "update"
    assert reponse.json()["retires"] == 5


def test_la_resynchro_ne_touche_pas_les_autres_semaines(client) -> None:
    """Le garde-fou. Vider la file ENTIÈRE perdrait un déplacement de séance
    fait en semaine 12 — sans rapport avec la semaine qu'on reconstruit, et
    invisible pour celui qui l'avait demandé."""
    instantane.enregistrer(
        [_evenement(event_id=EVENT_ID, heure="08:00", salle="H.101")], groupes=[GROUPE_CELCAT]
    )
    enfiler({"action": "update", "session_id": "s-ailleurs", "event_id": 42, "semaine": 12})
    enfiler({"action": "create", "session_id": "s-identique", "semaine": SEMAINE})

    _resync(client)

    restants = lister()
    assert [j["session_id"] for j in restants] == ["s-ailleurs"], (
        f"seule la semaine resynchronisée doit être reconstruite, reste : {restants}"
    )


def test_sans_releve_la_resynchro_est_refusee(client) -> None:
    """Sans instantané, TOUTES les séances paraissent absentes de Celcat :
    resynchroniser créerait alors un doublon de tout le planning. Même
    garde-fou que « Corriger »."""
    reponse = _resync(client)

    assert reponse.status_code == 409
    assert "elev" in reponse.text.lower() or "afra" in reponse.text.lower()


def test_plusieurs_semaines_en_un_appel(client) -> None:
    """« repartir de la comparaison » vaut pour toutes les semaines
    validées, pas une par une."""
    instantane.enregistrer(
        [_evenement(event_id=EVENT_ID, heure="08:00", salle="H.101")], groupes=[GROUPE_CELCAT]
    )

    reponse = _resync(client, semaines="1,2,3")

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["semaines"] == [1, 2, 3]


def test_l_anonyme_ne_peut_pas_resynchroniser(db_isole) -> None:
    c = TestClient(app)
    c.cookies.clear()
    assert c.post("/celcat/file/resynchroniser?semaines=1").status_code in (401, 403)
