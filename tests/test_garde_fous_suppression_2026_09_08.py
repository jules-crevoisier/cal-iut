"""Ne pas annoncer des protections qu'on n'applique pas, et refuser un relevé périmé.

Trouvé le 08/09/2026 par la vérification adverse du geste « Corriger », alors
que Kyllian Bresson modifiait Celcat à la main et que Jules se demandait s'il
pouvait pousser les corrections sans défaire son travail.

DEUX DÉFAUTS, tous deux du même genre : une sécurité qui a l'air d'exister.

1. UN GARDE-FOU MORT. `suppression.py` appelait `autoriser_suppression(ev)`
   sans l'argument `categorie`, si bien que la branche
   `if categorie == "celcat_en_plus": return False` ne s'exécutait jamais.
   Et le message d'erreur annonçait pourtant « garde-fou : jour férié,
   fantôme, protected=Y ou Celcat-en-plus ». Aucun appelant de production ne
   passe cet argument — seul un test le faisait.

   L'activer partout aurait refusé TOUTES les suppressions « en trop », donc
   supprimé la fonctionnalité demandée le 08/09/2026 (« et les suppressions ?
   — oui, comme le reste »). Le paramètre part donc, et le message dit
   désormais ce que le code fait vraiment. Une protection annoncée mais non
   appliquée est pire que pas de protection : elle fait cliquer en confiance.

2. UN RELEVÉ PÉRIMÉ PASSAIT. `corriger` ne testait que « existe-t-il un
   relevé », jamais « est-il encore valable ». Or la correction se calcule
   ENTIÈREMENT dessus : sur un relevé de trois heures, on pousse des
   modifications contre un Celcat qui a changé, et surtout on supprime des
   évènements d'après une photo périmée. Le 08/09/2026, Celcat est passé de
   1484 à 1470 évènements en une heure pendant que quelqu'un y travaillait.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import instantane
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, Room, RoomType, SessionType, Teacher, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE, INDICE = 1, 3
GROUPE = "BUT MMI S1 TD AB"


def _evenement(**extra) -> dict:
    return {
        "event_id": 1931666, "groupe": GROUPE, "jour": 0,
        "heure_debut": "08:00", "heure_fin": "09:30", "salle": "H.007",
        "categorie": "[TD]", "module": "WR101", "semaine": INDICE, **extra,
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

    mri = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    s = SessionToPlace(
        id="s-x", course_code="WR101", course_name="Cours", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD, sequence_order=1,
        group_ids=["but1-td-ab"], teacher_codes=["MRI"], duration_slots=1,
    )
    etat.sessions = [s]
    etat.sessions_by_id = {s.id: s}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="s-x", week=SEMAINE, day=0, slot=0, course_code="WR101",
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
    etat.courses = [
        Course(
            code="WR101", name="Cours", semestre="S1", parcours="BUT1", annee="BUT1", lead=mri,
            profs=[TeacherBlock(teacher=mri, block="1", td=17, nbGpTd=1, nbGpTp=1)],
            volumes={"cm": 0, "td": 17, "tp": 0}, groupes_td=1, groupes_tp=1,
            progression_defined=False, seance_sequence=[], ordonnancement=[],
        )
    ]
    etat.config_dir = ROOT / "data" / "config"

    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="admin")
    c.patch("/celcat/saisie", json={"active": True})
    yield c

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


# --------------------------------------------------------------------------
# 1. Le message ne doit plus annoncer un garde-fou qui n'existe pas.
# --------------------------------------------------------------------------


def test_le_message_de_refus_ne_promet_que_ce_qui_est_applique() -> None:
    """Le message annonçait « ou Celcat-en-plus » alors que cette branche ne
    s'exécutait jamais. Un refus qui décrit une protection absente donne
    confiance à tort.

    On lit le message RÉELLEMENT levé, pas le fichier source : une première
    version de ce test cherchait la chaîne dans tout le module et attrapait
    le commentaire qui explique justement la correction — vert ou rouge pour
    la mauvaise raison.
    """
    from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

    from cal_iut.celcat.suppression import SuppressionRefusee, supprimer_evenement

    protege = {
        "event_id": 5001, "day_of_week": 0, "start_time": "08:00", "end_time": "09:30",
        "evCatName": "[TD]", "event_cat_id": 4,
        "rooms": [{"id": 104105, "name": "H.105"}],
        "modules": [{"id": 601106, "name": "WR106"}],
        "groups": [{"id": 1661972, "name": "BUT MMI S1 TD AB"}],
        "weeks": "Y" + "N" * 53, "protected": "Y",
        "global_event": "N", "suspended": "N",
    }
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [protege]

    with pytest.raises(SuppressionRefusee) as refus:
        supprimer_evenement(page, 5001, group_id=1661972, methode="udlTimetables.save")

    message = str(refus.value)
    assert "Celcat-en-plus" not in message, (
        f"le refus ne doit pas promettre un garde-fou non appliqué : {message}"
    )
    assert "protected" in message, f"il doit nommer la raison réelle : {message}"


def test_les_garde_fous_reellement_appliques_le_restent() -> None:
    """Non-régression : férié, fantôme et protected=Y protègent toujours."""
    from cal_iut.celcat.file_attente import autoriser_suppression
    from cal_iut.celcat.lecture import evenement_depuis_rpc

    ferie = evenement_depuis_rpc(
        {"event_id": 1, "evCatName": "Jour férié", "start_time": "08:00"},
        group_id=1, groupe_nom="",
    )
    fantome = evenement_depuis_rpc({"event_id": 2}, group_id=1, groupe_nom="")
    protege = evenement_depuis_rpc(
        {"event_id": 3, "evCatName": "[TD]", "start_time": "08:00",
         "modules": [{"name": "WR101"}], "protected": "Y"},
        group_id=1, groupe_nom="",
    )
    normal = evenement_depuis_rpc(
        {"event_id": 4, "evCatName": "[TD]", "start_time": "08:00",
         "modules": [{"name": "WR101"}]},
        group_id=1, groupe_nom="",
    )

    assert autoriser_suppression(ferie) is False
    assert autoriser_suppression(fantome) is False
    assert autoriser_suppression(protege) is False
    assert autoriser_suppression(normal) is True, (
        "un cours ordinaire doit rester supprimable : c'est la fonctionnalité demandée"
    )


# --------------------------------------------------------------------------
# 2. Un relevé périmé ne doit pas servir de base à une correction.
# --------------------------------------------------------------------------


def test_un_releve_perime_refuse_la_correction(client) -> None:
    """La correction se calcule ENTIÈREMENT sur le relevé. Sur une photo de
    trois heures, on supprimerait des évènements d'après un Celcat qui a
    changé depuis."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    instantane.enregistrer([_evenement()], groupes=[GROUPE], releve_le=vieux)

    reponse = client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}")

    assert reponse.status_code == 409, reponse.text
    assert "rafra" in reponse.text.lower() or "périm" in reponse.text.lower()


def test_un_releve_frais_passe(client) -> None:
    """Non-régression : le cas normal ne doit pas se mettre à refuser."""
    instantane.enregistrer([_evenement()], groupes=[GROUPE])

    reponse = client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}")

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["modifications"] == 1


def test_la_resynchronisation_refuse_aussi_un_releve_perime(client) -> None:
    """Même raison : elle reconstruit la file entière depuis ce relevé."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    instantane.enregistrer([_evenement()], groupes=[GROUPE], releve_le=vieux)

    reponse = client.post(f"/celcat/file/resynchroniser?semaines={SEMAINE}")

    assert reponse.status_code == 409, reponse.text
