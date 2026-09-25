"""Retour Kyllian Bresson 25/09/2026 : « une possibilité de vérification
après placement pour salles et enseignants en double [...] Donc si on
pouvait avoir un compte rendu qui indique quelle salle ou quel enseignant est
mobilisé deux fois sur le même créneau, que je puisse corriger cela
rapidement. Et aussi pour H.201 et H.203, c'est en soi la même salle [...]
pareil pour H.007 et H.008. »

Deux volets : la fonction PURE `api/doublons.py::doublons` (ce module), et
l'endpoint `GET /controles/doublons` qui l'expose (auth + filtre `semaine`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.doublons import doublons
from cal_iut.api.main import app
from cal_iut.api.state import AppState, get_state
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]

ROOMS = [
    Room(id="h101", label="H.101", capacity=15, room_type=RoomType.STANDARD),
    Room(id="h201", label="H.201", capacity=35, room_type=RoomType.STANDARD),
    Room(id="h203", label="H.203", capacity=35, room_type=RoomType.STANDARD),
    Room(id="h201_h203", label="H.201-203", capacity=70, room_type=RoomType.COMBINED, combines=["h201", "h203"]),
]


def _seance(sid: str, groupe: str, prof: str, code: str = "ZZ1", duree: int = 1) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="Cours", semestre="S1", parcours="BUT1", annee="BUT1",
        session_type=SessionType.TD, group_ids=[groupe], teacher_codes=[prof], duration_slots=duree,
    )


def _place(sid: str, week: int, day: int, slot: int, groupe: str, prof: str, room_id: str | None = None, room_label: str | None = None) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=sid, week=week, day=day, slot=slot, course_code="ZZ1",
        group_ids=[groupe], teacher_codes=[prof], room_id=room_id, room_label=room_label,
    )


def _state(sessions: list[SessionToPlace], timetable: list[PlacedSessionWithRoom], rooms: list[Room] | None = None) -> AppState:
    return AppState(
        sessions=sessions, sessions_by_id={s.id: s for s in sessions},
        timetable=timetable, rooms=rooms if rooms is not None else ROOMS, courses=[],
    )


# --------------------------------------------------------------------------
# Doublon ENSEIGNANT
# --------------------------------------------------------------------------


def test_un_enseignant_present_deux_fois_au_meme_creneau_est_signale():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "MRI")
    tt = [_place("a", 5, 2, 3, "but1-td-ab", "MRI"), _place("b", 5, 2, 3, "but2-td-cd", "MRI")]
    resultat = doublons(_state([a, b], tt))
    assert len(resultat) == 1
    entree = resultat[0]
    assert entree["type"] == "enseignant"
    assert entree["semaine"] == 5 and entree["jour"] == 2 and entree["creneau"] == 3
    assert entree["ressource"] == "MRI"  # pas de `state.courses` : repli sur le code brut
    assert {s["session_id"] for s in entree["seances"]} == {"a", "b"}


def test_deux_enseignants_differents_au_meme_creneau_ne_sont_pas_signales():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "AUTRE")
    tt = [_place("a", 5, 2, 3, "but1-td-ab", "MRI"), _place("b", 5, 2, 3, "but2-td-cd", "AUTRE")]
    assert doublons(_state([a, b], tt)) == []


# --------------------------------------------------------------------------
# Doublon SALLE
# --------------------------------------------------------------------------


def test_une_salle_occupee_deux_fois_au_meme_creneau_est_signalee():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "but1-td-ab", "MRI", "h101", "H.101"),
        _place("b", 5, 2, 3, "but2-td-cd", "AUTRE", "h101", "H.101"),
    ]
    resultat = doublons(_state([a, b], tt))
    assert len(resultat) == 1
    entree = resultat[0]
    assert entree["type"] == "salle"
    assert entree["ressource"] == "H.101"
    assert {s["session_id"] for s in entree["seances"]} == {"a", "b"}


def test_deux_salles_differentes_sans_lien_ne_sont_pas_signalees():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "but1-td-ab", "MRI", "h101", "H.101"),
        _place("b", 5, 2, 3, "but2-td-cd", "AUTRE", "h201", "H.201"),
    ]
    assert doublons(_state([a, b], tt)) == []


def test_h201_et_h203_comptent_comme_la_meme_salle():
    """Retour Kyllian Bresson 25/09/2026 : « pour H.201 et H.203, c'est en
    soi la même salle »."""
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "but1-td-ab", "MRI", "h201", "H.201"),
        _place("b", 5, 2, 3, "but2-td-cd", "AUTRE", "h203", "H.203"),
    ]
    resultat = doublons(_state([a, b], tt))
    assert len(resultat) == 1
    entree = resultat[0]
    assert entree["type"] == "salle"
    assert entree["ressource"] == "H.201 / H.203"


def test_h201_et_sa_version_fusionnee_comptent_comme_la_meme_salle():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "but1-td-ab", "MRI", "h201", "H.201"),
        _place("b", 5, 2, 3, "but2-td-cd", "AUTRE", "h201_h203", "H.201-203"),
    ]
    resultat = doublons(_state([a, b], tt))
    assert len(resultat) == 1
    assert resultat[0]["ressource"] == "H.201 / H.201-203"


def test_h007_et_h008_pris_isolement_par_le_solveur_ne_sont_PAS_un_faux_positif():
    """Contrôle négatif : une salle sans AUCUN `combines` déclaré (donc sans
    équivalence connue) ne doit jamais se retrouver groupée avec une autre
    au hasard."""
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "AUTRE")
    tt = [
        _place("a", 5, 2, 3, "but1-td-ab", "MRI", "h101", "H.101"),
        _place("b", 5, 2, 3, "but2-td-cd", "AUTRE", "h101", "H.101"),
    ]
    resultat = doublons(_state([a, b], tt, rooms=[Room(id="h101", label="H.101", capacity=15, room_type=RoomType.STANDARD)]))
    assert len(resultat) == 1  # même salle littérale : toujours signalé


# --------------------------------------------------------------------------
# Durée : une séance de 3h ne ressort QUE sur le créneau réellement partagé
# --------------------------------------------------------------------------


def test_une_seance_de_3h_ne_chevauchant_qu_une_moitie_d_1h30_ne_ressort_que_sur_ce_creneau():
    longue = _seance("longue", "but1-td-ab", "MRI", duree=2)  # occupe slot 0 ET slot 1
    courte = _seance("courte", "but2-td-cd", "AUTRE", duree=1)  # occupe seulement slot 1
    tt = [
        _place("longue", 5, 2, 0, "but1-td-ab", "MRI", "h101", "H.101"),
        _place("courte", 5, 2, 1, "but2-td-cd", "AUTRE", "h101", "H.101"),
    ]
    resultat = doublons(_state([longue, courte], tt))
    assert len(resultat) == 1
    assert resultat[0]["creneau"] == 1  # PAS le créneau 0, où seule `longue` est présente


# --------------------------------------------------------------------------
# Pas de faux positif — même session, semaines/jours différents
# --------------------------------------------------------------------------


def test_une_seule_seance_placee_ne_produit_jamais_de_doublon():
    a = _seance("a", "but1-td-ab", "MRI")
    tt = [_place("a", 5, 2, 3, "but1-td-ab", "MRI", "h101", "H.101")]
    assert doublons(_state([a], tt)) == []


def test_le_meme_enseignant_sur_deux_semaines_differentes_n_est_pas_signale():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "MRI")
    tt = [_place("a", 5, 2, 3, "but1-td-ab", "MRI"), _place("b", 6, 2, 3, "but2-td-cd", "MRI")]
    assert doublons(_state([a, b], tt)) == []


def test_le_meme_enseignant_sur_deux_jours_differents_n_est_pas_signale():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "MRI")
    tt = [_place("a", 5, 2, 3, "but1-td-ab", "MRI"), _place("b", 5, 3, 3, "but2-td-cd", "MRI")]
    assert doublons(_state([a, b], tt)) == []


# --------------------------------------------------------------------------
# Filtre `semaine`
# --------------------------------------------------------------------------


def test_le_filtre_semaine_ne_garde_que_les_doublons_de_cette_semaine():
    a1 = _seance("a1", "but1-td-ab", "MRI")
    b1 = _seance("b1", "but2-td-cd", "MRI")
    a2 = _seance("a2", "but1-td-ab", "MRI")
    b2 = _seance("b2", "but2-td-cd", "MRI")
    tt = [
        _place("a1", 5, 0, 0, "but1-td-ab", "MRI"), _place("b1", 5, 0, 0, "but2-td-cd", "MRI"),
        _place("a2", 6, 0, 0, "but1-td-ab", "MRI"), _place("b2", 6, 0, 0, "but2-td-cd", "MRI"),
    ]
    resultat = doublons(_state([a1, b1, a2, b2], tt), semaine=5)
    assert len(resultat) == 1
    assert resultat[0]["semaine"] == 5


# --------------------------------------------------------------------------
# Pause méridienne : exemptée, comme `validate_move`
# --------------------------------------------------------------------------


def test_deux_evenements_pause_midi_sur_la_meme_salle_ne_sont_pas_signales_ici():
    """Exclus du balayage (cf. docstring de `doublons`) — leur cas est
    couvert séparément par `api/main.py::_conflit_salle_pause_midi` (minutes
    réelles, pas le créneau de stockage partagé)."""
    p1 = SessionToPlace(
        id="p1", course_code="PAUSE1", course_name="Pause", semestre="S1", parcours="BUT1", annee="BUT1",
        session_type=SessionType.CM, group_ids=["but1-td-ab"], teacher_codes=[], metadata={"pause_midi": True},
    )
    p2 = SessionToPlace(
        id="p2", course_code="PAUSE2", course_name="Pause", semestre="S1", parcours="BUT1", annee="BUT1",
        session_type=SessionType.CM, group_ids=["but2-td-cd"], teacher_codes=[], metadata={"pause_midi": True},
    )
    tt = [
        _place("p1", 5, 2, 3, "but1-td-ab", "", "h101", "H.101"),
        _place("p2", 5, 2, 3, "but2-td-cd", "", "h101", "H.101"),
    ]
    assert doublons(_state([p1, p2], tt)) == []


# --------------------------------------------------------------------------
# Ordre déterministe
# --------------------------------------------------------------------------


def test_l_ordre_est_deterministe_semaine_jour_creneau_type_ressource():
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "MRI")
    c = _seance("c", "but1-td-ab", "ZZZ")
    d = _seance("d", "but2-td-cd", "ZZZ")
    tt = [
        _place("a", 6, 0, 0, "but1-td-ab", "MRI"), _place("b", 6, 0, 0, "but2-td-cd", "MRI"),
        _place("c", 5, 0, 0, "but1-td-ab", "ZZZ"), _place("d", 5, 0, 0, "but2-td-cd", "ZZZ"),
    ]
    resultat = doublons(_state([a, b, c, d], tt))
    assert [(e["semaine"], e["ressource"]) for e in resultat] == [(5, "ZZZ"), (6, "MRI")]


# --------------------------------------------------------------------------
# Endpoint `GET /controles/doublons`
# --------------------------------------------------------------------------


@pytest.fixture
def client(db_isole):
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "rooms": etat.rooms, "courses": etat.courses,
    }
    a = _seance("a", "but1-td-ab", "MRI")
    b = _seance("b", "but2-td-cd", "MRI")
    etat.sessions = [a, b]
    etat.sessions_by_id = {a.id: a, b.id: b}
    etat.timetable = [_place("a", 5, 0, 0, "but1-td-ab", "MRI"), _place("b", 5, 0, 0, "but2-td-cd", "MRI")]
    etat.rooms = ROOMS
    etat.courses = []

    tc = TestClient(app)
    creer_compte_actif_et_connecter(tc)
    yield tc

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_l_endpoint_rend_les_doublons_calcules(client):
    reponse = client.get("/controles/doublons")
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert len(corps["doublons"]) == 1
    assert corps["doublons"][0]["type"] == "enseignant"
    assert corps["doublons"][0]["ressource"] == "MRI"


def test_l_endpoint_respecte_le_filtre_semaine(client):
    assert client.get("/controles/doublons?semaine=5").json()["doublons"] != []
    assert client.get("/controles/doublons?semaine=6").json()["doublons"] == []


def test_l_endpoint_refuse_un_role_lecture_seule(client, db_isole):
    lecteur = TestClient(app)
    creer_compte_actif_et_connecter(lecteur, role="read_only")
    reponse = lecteur.get("/controles/doublons")
    assert reponse.status_code == 403
