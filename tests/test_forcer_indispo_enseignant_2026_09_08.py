"""Changer d'enseignant sur place doit rester FORÇABLE malgré une indispo.

Signalé le 08/09/2026, capture d'écran à l'appui : la fenêtre « Modifier la
séance » refusait le changement avec

    Impossible (non forçable) :
    Enseignant indisponible à ce créneau (RDE) …

    Forçable :
    Enseignant indisponible à ce créneau (RDE) …

Le MÊME motif dans les deux colonnes, et aucun bouton pour forcer.

LE CHEMIN EN CAUSE. `session_patch.py` a deux branches : si la position
change, il délègue à `move_session`, qui classe correctement. Sinon — donc
quand on change SEULEMENT l'enseignant, le type ou la durée — il passe par
`_controler_placement`, qui rangeait `institutional + indispo` dans les
bloquants et levait l'erreur QUEL QUE SOIT `force`.

Or la classification de référence (`main.py::_hard_constraint_context`) dit
l'inverse depuis le 03/09/2026 : seul le verrou institutionnel (jeudi PAC,
jour SAE sanctuarisé, férié) est non contournable ; l'ordre pédagogique ET
l'indisponibilité enseignant sont forçables. La docstring de
`_teacher_availability_violations` le dit noir sur blanc, retour de Kyllian
Bresson à l'appui : « des fois ils acceptent de faire cours quand même
haha ».

Ce chemin était donc le seul de l'application à traiter une indispo comme un
verrou définitif — et c'est celui qu'on emprunte chaque fois qu'on réaffecte
un cours à un autre enseignant sans le déplacer.

LE DOUBLON D'AFFICHAGE est un second défaut, indépendant : par contrat
`blocking_conflicts` est un SOUS-ENSEMBLE de `hard_conflicts`
(cf. `schemas.ValidationResponse`), et l'écran listait `hard_conflicts` en
entier sous « Forçable ». Tout motif bloquant apparaissait donc deux fois,
pas seulement celui-ci. Corrigé côté interface
(`placement.ts::texteContraintes`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import (
    Course,
    Room,
    RoomType,
    SessionType,
    Teacher,
    TeacherAvailability,
    TeacherBlock,
)
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10
# La séance est posée LÀ, et JSA y est déclaré indisponible.
JOUR, CRENEAU = 1, 2


def _seance() -> SessionToPlace:
    return SessionToPlace(
        id="a",
        course_code="WR101",
        course_name="Cours existant",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=1,
        group_ids=["but1-td-ab"],
        teacher_codes=["MRI"],
        duration_slots=1,
    )


def _cours() -> Course:
    mri = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    jsa = Teacher(code="JSA", nom="Sanson", prenom="Jean")
    return Course(
        code="WR101",
        name="Cours existant",
        semestre="S1",
        parcours="BUT1",
        annee="BUT1",
        lead=mri,
        profs=[
            TeacherBlock(teacher=mri, block="1", td=17, nbGpTd=1, nbGpTp=1),
            TeacherBlock(teacher=jsa, block="1", td=0, nbGpTd=1, nbGpTp=1),
        ],
        volumes={"cm": 0, "td": 17, "tp": 0},
        groupes_td=1,
        groupes_tp=1,
        progression_defined=False,
        seance_sequence=[],
        ordonnancement=[],
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

    s = _seance()
    etat.sessions = [s]
    etat.sessions_by_id = {s.id: s}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="a", week=SEMAINE, day=JOUR, slot=CRENEAU,
            course_code="WR101", group_ids=["but1-td-ab"], teacher_codes=["MRI"],
        )
    ]
    etat.groups = GROUPES
    etat.rooms = [Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD)]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    # Jean Sanson a déclaré ne pas être disponible sur ce créneau.
    etat.teacher_availability = [
        TeacherAvailability(teacher_code="JSA", forbidden_slots=[(JOUR, CRENEAU)])
    ]
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = [_cours()]
    etat.config_dir = ROOT / "data" / "config"

    c = TestClient(app)
    creer_compte_actif_et_connecter(c)
    yield c

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _affecter_jsa(client, **extra):
    """Change l'enseignant SANS déplacer la séance — la branche
    `_controler_placement`, celle de la capture d'écran."""
    return client.patch("/placements/a/seance", json={"teacher_codes": ["JSA"], **extra})


def test_l_indispo_est_signalee_mais_jamais_bloquante(client) -> None:
    """Elle doit apparaître dans `hard_conflicts` — la taire serait pire que
    la bloquer — et JAMAIS dans `blocking_conflicts`, qui est précisément ce
    qui prive l'écran du bouton « Forcer »."""
    reponse = _affecter_jsa(client)

    assert reponse.status_code == 409, reponse.text
    detail = reponse.json()["detail"]
    assert any("Enseignant indisponible" in m for m in detail["hard_conflicts"]), (
        "la contrainte doit rester signalée"
    )
    assert not any("Enseignant indisponible" in m for m in detail.get("blocking_conflicts", [])), (
        "une indispo enseignant n'est PAS un verrou définitif (cf. "
        "_teacher_availability_violations : « des fois ils acceptent »)"
    )


def test_forcer_applique_vraiment_le_changement(client) -> None:
    """L'effet recherché, et le seul qui compte pour l'utilisateur : quand on
    force, l'enseignant change pour de bon."""
    assert _affecter_jsa(client).status_code == 409

    reponse = _affecter_jsa(client, force=True)

    assert reponse.status_code == 200, reponse.text
    assert get_state().sessions_by_id["a"].teacher_codes == ["JSA"]


def test_un_verrou_institutionnel_reste_non_forcable(client, monkeypatch) -> None:
    """Le garde-fou de ce correctif. Rendre l'indispo forçable ne doit pas
    ouvrir la porte au jeudi PAC ni aux jours SAE sanctuarisés : ceux-là
    restent bloquants, `force` ou pas."""
    from cal_iut.api import main as api_main

    motif = "Jeudi PAC : créneau sanctuarisé."
    monkeypatch.setattr(api_main, "_institutional_violations", lambda *a, **k: [motif])

    refus = _affecter_jsa(client)
    forcage = _affecter_jsa(client, force=True)

    assert refus.status_code == 409
    assert motif in refus.json()["detail"]["blocking_conflicts"]
    assert forcage.status_code == 409, "un verrou institutionnel ne se force jamais"
    assert get_state().sessions_by_id["a"].teacher_codes == ["MRI"], (
        "rien ne doit être appliqué quand le verrou tient"
    )


def test_sans_conflit_le_changement_passe_sans_force(client) -> None:
    """Non-régression : réaffecter à un enseignant DISPONIBLE ne doit pas se
    mettre à exiger `force`."""
    etat = get_state()
    etat.sessions_by_id["a"].teacher_codes = ["JSA"]
    etat.timetable[0].teacher_codes = ["JSA"]

    reponse = client.patch("/placements/a/seance", json={"teacher_codes": ["MRI"]})

    assert reponse.status_code == 200, reponse.text
    assert get_state().sessions_by_id["a"].teacher_codes == ["MRI"]
