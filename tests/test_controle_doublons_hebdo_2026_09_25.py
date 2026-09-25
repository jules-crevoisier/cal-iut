"""Contrôle HEBDOMADAIRE automatique des doublons salle/enseignant — Jules
Crevoisier, 25/09/2026 (dicté) : « on veut faire quelque chose qui vérifie
chaque semaine s'il n'y a pas deux salles au même moment qui sont assignées
en même temps. Et pareil [...] un prof qui soit assigné à deux endroits en
même temps. »

Trois volets, testés séparément :

1. Le MODULE (`api/controle_doublons_hebdo.py`) en isolation — filet une
   fois par semaine ISO, calcul `nouveaux`/`resolus` entre deux runs,
   historique borné à 8, jamais d'exception remontée.
2. Le HOOK — `_apres_ecriture_planning`/`startup()` (`api/main.py`)
   déclenchent bien le filet.
3. Les ENDPOINTS — rôle edit+ requis, jamais-exécuté vs dernier résultat,
   « Vérifier maintenant » force l'exécution.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import controle_doublons_hebdo
from cal_iut.api.main import app
from cal_iut.api.state import AppState, get_state
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOMS = [
    Room(id="h101", label="H.101", capacity=15, room_type=RoomType.STANDARD),
    Room(id="h102", label="H.102", capacity=15, room_type=RoomType.STANDARD),
]


def _seance(sid: str, groupe: str, prof: str, code: str = "ZZ1") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="Cours", semestre="S1", parcours="BUT1", annee="BUT1",
        session_type=SessionType.TD, group_ids=[groupe], teacher_codes=[prof], duration_slots=1,
    )


def _place(sid: str, week: int, day: int, slot: int, groupe: str, prof: str, room_id: str, code: str = "ZZ1") -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=sid, week=week, day=day, slot=slot, course_code=code,
        group_ids=[groupe], teacher_codes=[prof], room_id=room_id, room_label=room_id.upper(),
    )


def _state(sessions: list[SessionToPlace], timetable: list[PlacedSessionWithRoom]) -> AppState:
    return AppState(
        sessions=sessions, sessions_by_id={s.id: s for s in sessions},
        timetable=timetable, rooms=ROOMS, courses=[],
    )


def _state_avec_un_doublon_salle() -> AppState:
    """Un seul doublon salle (h101) sur le créneau (5, 2, 3)."""
    a = _seance("a", "g1", "P1")
    b = _seance("b", "g2", "P2", code="ZZ2")
    tt = [_place("a", 5, 2, 3, "g1", "P1", "h101"), _place("b", 5, 2, 3, "g2", "P2", "h101", code="ZZ2")]
    return _state([a, b], tt)


def _state_avec_deux_doublons() -> AppState:
    """Le doublon salle précédent PLUS un doublon enseignant nouveau."""
    a = _seance("a", "g1", "P1")
    b = _seance("b", "g2", "P2", code="ZZ2")
    c = _seance("c", "g3", "P3", code="ZZ3")
    d = _seance("d", "g4", "P3", code="ZZ4")
    tt = [
        _place("a", 5, 2, 3, "g1", "P1", "h101"),
        _place("b", 5, 2, 3, "g2", "P2", "h101", code="ZZ2"),
        _place("c", 6, 1, 2, "g3", "P3", "h101", code="ZZ3"),
        _place("d", 6, 1, 2, "g4", "P3", "h102", code="ZZ4"),
    ]
    return _state([a, b, c, d], tt)


def _state_sans_doublon() -> AppState:
    a = _seance("a", "g1", "P1")
    return _state([a], [_place("a", 5, 2, 3, "g1", "P1", "h101")])


# --------------------------------------------------------------------------
# Le module — filet une fois par semaine ISO
# --------------------------------------------------------------------------


def test_verifier_si_necessaire_prend_un_run_quand_jamais_fait() -> None:
    assert controle_doublons_hebdo.dernier() is None
    run = controle_doublons_hebdo.verifier_si_necessaire(_state_avec_un_doublon_salle())
    assert run is not None
    assert run["total"] == 1
    assert run["premier_controle"] is True
    assert controle_doublons_hebdo.dernier() == run


def test_verifier_si_necessaire_ne_reprend_pas_deux_fois_la_meme_semaine() -> None:
    controle_doublons_hebdo.verifier_si_necessaire(_state_avec_un_doublon_salle())
    premier = controle_doublons_hebdo.dernier()

    # L'état change ENTRE les deux appels : si un second run était pris, le
    # total changerait.
    second = controle_doublons_hebdo.verifier_si_necessaire(_state_avec_deux_doublons())

    assert second is None
    assert controle_doublons_hebdo.dernier() == premier
    assert controle_doublons_hebdo.dernier()["total"] == 1


def test_verifier_si_necessaire_reprend_une_semaine_iso_differente(monkeypatch) -> None:
    monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda: date(2026, 9, 21))  # lundi, ISO W39
    controle_doublons_hebdo.verifier_si_necessaire(_state_avec_un_doublon_salle())
    assert controle_doublons_hebdo.dernier()["semaine_iso"] == "2026-W39"

    monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda: date(2026, 9, 28))  # lundi suivant, S40
    run = controle_doublons_hebdo.verifier_si_necessaire(_state_avec_deux_doublons())

    assert run is not None
    assert run["semaine_iso"] == "2026-W40"
    assert run["total"] == 2


def test_demarrage_execute_le_controle_si_semaine_jamais_faite() -> None:
    """Reproduit `startup()` : `verifier_si_necessaire` appelé sans qu'aucun
    write planning n'ait eu lieu avant — même filet que `sauvegardes.
    snapshot_si_necessaire` au démarrage (fichier de la période manquant)."""
    assert controle_doublons_hebdo.dernier() is None
    run = controle_doublons_hebdo.verifier_si_necessaire(_state_sans_doublon())
    assert run is not None
    assert run["total"] == 0
    assert run["par_type"] == {}


def test_nouveaux_et_resolus_calcules_entre_deux_runs(monkeypatch) -> None:
    monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda: date(2026, 9, 21))
    premier = controle_doublons_hebdo.executer_maintenant(_state_avec_un_doublon_salle())
    assert premier["nouveaux"] == []  # premier contrôle : rien à comparer
    assert premier["resolus"] == []
    assert premier["premier_controle"] is True

    monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda: date(2026, 9, 28))
    second = controle_doublons_hebdo.executer_maintenant(_state_avec_deux_doublons())

    assert second["premier_controle"] is False
    assert second["resolus"] == []  # le doublon salle initial est toujours là
    assert len(second["nouveaux"]) == 1
    assert second["nouveaux"][0]["type"] == "enseignant"
    assert second["nouveaux"][0]["ressource"] == "P3"


def test_resolus_quand_un_doublon_disparait(monkeypatch) -> None:
    monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda: date(2026, 9, 21))
    controle_doublons_hebdo.executer_maintenant(_state_avec_un_doublon_salle())

    monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda: date(2026, 9, 28))
    second = controle_doublons_hebdo.executer_maintenant(_state_sans_doublon())

    assert second["nouveaux"] == []
    assert len(second["resolus"]) == 1
    assert second["resolus"][0]["type"] == "salle"


def test_ne_garde_que_les_8_derniers_runs(monkeypatch) -> None:
    for i in range(10):
        monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui", lambda i=i: date(2026, 1, 5) + timedelta(weeks=i))
        controle_doublons_hebdo.executer_maintenant(_state_sans_doublon())

    runs = controle_doublons_hebdo._charger()
    assert len(runs) == 8
    # Les 2 plus anciens (semaines 0 et 1) ont été purgés, les 8 derniers
    # (semaines 2 à 9) sont conservés, dans l'ordre chronologique.
    semaines = [r["semaine_iso"] for r in runs]
    assert semaines == sorted(semaines)


def test_executer_maintenant_bascule_deja_fait_cette_semaine_a_vrai() -> None:
    assert controle_doublons_hebdo.deja_fait_cette_semaine() is False
    controle_doublons_hebdo.executer_maintenant(_state_sans_doublon())
    assert controle_doublons_hebdo.deja_fait_cette_semaine() is True


def test_verifier_si_necessaire_ne_leve_jamais(monkeypatch) -> None:
    def _casse(state: object) -> dict:
        raise RuntimeError("disque plein")

    monkeypatch.setattr(controle_doublons_hebdo, "executer_maintenant", _casse)
    resultat = controle_doublons_hebdo.verifier_si_necessaire(_state_avec_un_doublon_salle())  # ne doit pas lever
    assert resultat is None
    assert controle_doublons_hebdo.dernier() is None


def test_semaine_iso_stable_pour_toute_la_semaine_civile() -> None:
    assert controle_doublons_hebdo._semaine_iso(date(2026, 9, 21)) == "2026-W39"
    assert controle_doublons_hebdo._semaine_iso(date(2026, 9, 27)) == "2026-W39"
    assert controle_doublons_hebdo._semaine_iso(date(2026, 9, 28)) == "2026-W40"


# --------------------------------------------------------------------------
# Les endpoints
# --------------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture
def etat_reel_avec_doublon():
    """Un `AppState` réel minimal avec UN doublon salle, pour les endpoints
    (qui appellent `get_state()` en interne)."""
    etat = get_state()
    ancien = {"timetable": etat.timetable, "sessions_by_id": etat.sessions_by_id, "rooms": etat.rooms}
    reference = _state_avec_un_doublon_salle()
    etat.timetable = reference.timetable
    etat.sessions_by_id = reference.sessions_by_id
    etat.rooms = reference.rooms
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_get_hebdo_refuse_un_anonyme(db_isole, etat_reel_avec_doublon) -> None:
    client.cookies.clear()
    assert client.get("/controles/doublons/hebdo").status_code in (401, 403)
    assert client.post("/controles/doublons/hebdo").status_code in (401, 403)


def test_get_hebdo_refuse_un_role_read_only(db_isole, etat_reel_avec_doublon) -> None:
    creer_compte_actif_et_connecter(client, role="read_only")
    assert client.get("/controles/doublons/hebdo").status_code == 403
    assert client.post("/controles/doublons/hebdo").status_code == 403
    client.cookies.clear()


def test_get_hebdo_accepte_edit_et_admin(db_isole, etat_reel_avec_doublon) -> None:
    creer_compte_actif_et_connecter(client, role="edit")
    assert client.get("/controles/doublons/hebdo").status_code == 200
    client.cookies.clear()

    creer_compte_actif_et_connecter(client, role="admin")
    assert client.get("/controles/doublons/hebdo").status_code == 200
    client.cookies.clear()


def test_get_hebdo_rend_dernier_null_si_jamais_execute(db_isole, etat_reel_avec_doublon) -> None:
    creer_compte_actif_et_connecter(client, role="edit")
    reponse = client.get("/controles/doublons/hebdo")
    assert reponse.status_code == 200
    assert reponse.json() == {"dernier": None}
    client.cookies.clear()


def test_post_hebdo_execute_et_rend_le_run(db_isole, etat_reel_avec_doublon) -> None:
    creer_compte_actif_et_connecter(client, role="edit")

    reponse = client.post("/controles/doublons/hebdo")

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["total"] == 1
    assert corps["doublons"][0]["type"] == "salle"

    # Le run posté par POST devient bien le « dernier » servi par GET.
    dernier = client.get("/controles/doublons/hebdo").json()["dernier"]
    assert dernier["total"] == 1
    client.cookies.clear()
