"""`POST /placements/{id}/validate` : une vérification À BLANC ne refuse pas.

Bug réel signalé le 29/08/2026 (« j'ai un petit bug en vue promo, quand je
drag and drop cela n'enregistre pas les changements ») : déplacer une séance
de la semaine EN COURS ne faisait rien du tout, sans conflit affiché ni
possibilité de forcer.

Cause : cet endpoint est un DRY-RUN — le frontend l'appelle avant tout
déplacement pour savoir quoi annoncer. Or il levait un HTTP 409 quand la
semaine n'était pas modifiable, au lieu de le RAPPORTER. Côté navigateur
(`utils/moveSession.ts::performMove`), un 409 sur la validation est une
exception : elle sort par le `catch`, affiche une discrète notice, et le
chemin « conflit -> modale -> forcer » n'est jamais atteint. Le verrou de
semaine étant justement contournable par forçage (retour utilisateur du
29/08 : « il faut que les séances soient modifiables à tout moment pour
l'instant en forçant »), la personne se retrouvait bloquée par un garde-fou
qu'elle avait explicitement le droit de lever.

Règle qui en découle, et que ces tests gardent : une vérification à blanc
DÉCRIT, elle n'interdit pas. Elle ne rend une erreur HTTP que si la question
elle-même n'a pas de sens (séance inconnue).
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

from conftest import creer_compte_actif_et_connecter

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

# Semaine 0 = semaine en cours dans le calendrier 2026-2027 au moment du
# bug ; semaine 10 = très en avant, donc librement modifiable.
SEMAINE_VERROUILLEE = 0
SEMAINE_LIBRE = 10


@pytest.fixture
def client(db_isole):
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "teacher_duos", "corrections",
            "courses", "config_dir",
        )
    }
    seance = SessionToPlace(
        id="seance", course_code="WR101", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["MRI"], duration_slots=1,
    )
    etat.sessions = [seance]
    etat.sessions_by_id = {seance.id: seance}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="seance", week=SEMAINE_LIBRE, day=0, slot=0, course_code="WR101",
            group_ids=["but1-td-ab"], teacher_codes=["MRI"],
        )
    ]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.config_dir = ROOT / "data" / "config"

    c = TestClient(app)
    creer_compte_actif_et_connecter(c)
    yield c

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _valider(client, **corps):
    return client.post(
        "/placements/seance/validate",
        json={"week": SEMAINE_LIBRE, "day": 1, "slot": 1, **corps},
    )


# --------------------------------------------------------------------------
# Le bug
# --------------------------------------------------------------------------


def test_une_semaine_verrouillee_est_rapportee_pas_levee_en_erreur(client) -> None:
    """LE test du bug : sans cela, le glisser-déposer ne fait rien du tout."""
    reponse = _valider(client, week=SEMAINE_VERROUILLEE)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["valid"] is False
    assert any("non modifiable" in c for c in corps["hard_conflicts"]), corps["hard_conflicts"]


def test_le_motif_dit_quelle_semaine_et_pourquoi(client) -> None:
    """Une modale qui dit seulement « conflit » ne permet pas de décider."""
    conflits = _valider(client, week=SEMAINE_VERROUILLEE).json()["hard_conflicts"]
    motif = next(c for c in conflits if "non modifiable" in c)
    assert "Semaine 1" in motif
    assert "current" in motif or "past" in motif


def test_la_semaine_source_verrouillee_compte_aussi(client) -> None:
    """Sortir une séance d'une semaine verrouillée est autant une réécriture
    du passé que d'en faire entrer une."""
    get_state().timetable[0].week = SEMAINE_VERROUILLEE
    conflits = _valider(client, week=SEMAINE_LIBRE).json()["hard_conflicts"]
    assert any("non modifiable" in c for c in conflits), conflits


def test_avec_force_le_verrou_de_semaine_ne_ressort_plus(client) -> None:
    """Une fois la personne prévenue et décidée, la vérification ne doit plus
    lui répéter l'obstacle qu'elle vient d'accepter."""
    conflits = _valider(client, week=SEMAINE_VERROUILLEE, force=True).json()["hard_conflicts"]
    assert not any("non modifiable" in c for c in conflits), conflits


def test_le_deplacement_reel_reste_refuse_sans_forcage(client) -> None:
    """Le garde-fou lui-même ne bouge pas : seule la PRÉVISUALISATION change
    de forme. Sans ce test, on pourrait « corriger » le bug en supprimant la
    protection."""
    reponse = client.patch(
        "/placements/seance", json={"week": SEMAINE_VERROUILLEE, "day": 1, "slot": 1}
    )
    assert reponse.status_code == 409
    assert "non modifiable" in reponse.text


def test_le_deplacement_reel_passe_avec_forcage(client) -> None:
    """Le bout de la chaîne : c'est ce que fait le bouton « Forcer le
    déplacement » de la modale. Sans lui, corriger la validation ne servirait
    à rien."""
    reponse = client.patch(
        "/placements/seance",
        json={"week": SEMAINE_VERROUILLEE, "day": 1, "slot": 1, "force": True},
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["week"] == SEMAINE_VERROUILLEE


# --------------------------------------------------------------------------
# Ce qui ne doit pas avoir changé
# --------------------------------------------------------------------------


def test_un_deplacement_ordinaire_reste_valide(client) -> None:
    corps = _valider(client).json()
    assert corps["valid"] is True
    assert corps["hard_conflicts"] == []


def test_une_seance_inconnue_reste_un_404(client) -> None:
    """La seule erreur HTTP que cet endpoint garde : la question n'a pas de
    sens, il n'y a rien à décrire."""
    reponse = client.post("/placements/fantome/validate", json={"week": 10, "day": 0, "slot": 0})
    assert reponse.status_code == 404
