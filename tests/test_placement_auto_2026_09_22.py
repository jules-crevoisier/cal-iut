"""Salle exclue du placement AUTOMATIQUE — retour utilisateur 22/09/2026 :
« supprimer la BU du placement automatique des salles car elle est utilisée
pour un seul module, celui de Valérie Mariot ». La BU (« BU / A.123 » dans
Celcat) doit rester choisissable À LA MAIN et garder l'affectation qu'elle a
déjà, mais ne plus jamais être proposée seule par le solveur ou par la
résolution automatique de salle (placement/déplacement/création sans
`room_id` explicite).

Solution générique demandée (« tout configurable depuis l'interface, pas de
correctif de code ») : `Room.placement_auto` (défaut `True`), modifiable
depuis `rooms.yaml`, depuis les salles créées en interface, et depuis
l'interface elle-même (`PATCH /rooms/{room_id}`, admin) sans redéploiement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups, load_rooms
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.cpsat import PlacedSession
from cal_iut.solver.rooms import (
    PlacedSessionWithRoom,
    assign_rooms,
    find_room_for_slot,
    parse_room_rules,
)

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

client = TestClient(app)


# ==========================================================================
# 1. Modèle + chargement (rooms.yaml, overlay salles perso)
# ==========================================================================


def test_room_placement_auto_defaut_a_true() -> None:
    """Rétrocompatible : une salle qui ne déclare rien reste proposable au
    placement automatique, comme avant l'ajout du champ."""
    salle = Room(id="x", label="X", capacity=10, room_type=RoomType.STANDARD)
    assert salle.placement_auto is True


def test_load_rooms_lit_placement_auto_false_depuis_le_yaml(tmp_path) -> None:
    (tmp_path / "rooms.yaml").write_text(
        "rooms:\n"
        "  - id: bu\n"
        "    label: BU / A.123\n"
        "    capacity: 30\n"
        "    room_type: standard\n"
        "    placement_auto: false\n"
        "  - id: h101\n"
        "    label: H.101\n"
        "    capacity: 35\n"
        "    room_type: standard\n"
        "room_assignment_rules: []\n",
        encoding="utf-8",
    )
    salles = {r.id: r for r in load_rooms(tmp_path)}
    assert salles["bu"].placement_auto is False
    # Absent du YAML = True (rétrocompat) — rien à ajouter pour les salles
    # existantes de `rooms.yaml`.
    assert salles["h101"].placement_auto is True


@pytest.fixture
def overlay_isole(tmp_path, monkeypatch):
    """Bascule `custom_rooms._path()` vers un fichier temporaire, pour ne
    jamais toucher au vrai `data/state/custom_rooms.json` du dépôt."""
    from cal_iut.api import custom_rooms

    chemin = tmp_path / "custom_rooms.json"
    monkeypatch.setattr(custom_rooms, "_path", lambda: chemin)
    return custom_rooms


def test_custom_room_sans_placement_auto_reste_true(overlay_isole) -> None:
    """Salle créée avant l'ajout du champ (ancien format, simple liste) —
    ne doit jamais devenir invisible du placement automatique par surprise."""
    overlay_isole._path().write_text(
        json.dumps([{"id": "amphi-x", "label": "Amphi X", "capacity": 50, "room_type": "standard"}]),
        encoding="utf-8",
    )
    salles = overlay_isole.load_custom_rooms()
    assert salles[0].placement_auto is True


def test_add_custom_room_persiste_placement_auto_false(overlay_isole) -> None:
    salle = Room(id="bu", label="BU / A.123", capacity=30, room_type=RoomType.STANDARD, placement_auto=False)
    overlay_isole.add_custom_room(salle)
    relue = overlay_isole.load_custom_rooms()
    assert relue[0].placement_auto is False


def test_set_room_override_sur_une_salle_perso_modifie_directement_son_enregistrement(overlay_isole) -> None:
    salle = Room(id="amphi-x", label="Amphi X", capacity=50, room_type=RoomType.STANDARD)
    overlay_isole.add_custom_room(salle)
    overlay_isole.set_room_override("amphi-x", placement_auto=False)
    assert overlay_isole.load_custom_rooms()[0].placement_auto is False
    # Pas d'entrée `overrides` dupliquée pour une salle perso déjà modifiée
    # sur son propre enregistrement.
    assert "amphi-x" not in overlay_isole.load_overrides()


def test_set_room_override_sur_une_salle_du_batiment_va_dans_overrides(overlay_isole) -> None:
    """`bu` n'existe QUE dans `rooms.yaml` (pas de fiche perso) — la
    surcharge doit survivre sans jamais réécrire `rooms.yaml`."""
    overlay_isole.set_room_override("bu", placement_auto=False)
    assert overlay_isole.load_overrides()["bu"]["placement_auto"] is False
    assert overlay_isole.load_custom_rooms() == []  # rooms.yaml intouché


def test_merge_into_applique_l_override_a_une_salle_du_batiment(overlay_isole) -> None:
    overlay_isole.set_room_override("bu", placement_auto=False)
    batiment = [Room(id="bu", label="BU / A.123", capacity=30, room_type=RoomType.STANDARD)]
    fusion = {r.id: r for r in overlay_isole.merge_into(batiment)}
    assert fusion["bu"].placement_auto is False
    # Le libellé/capacité du bâtiment restent la source de vérité.
    assert fusion["bu"].label == "BU / A.123"


def test_merge_into_sans_override_ne_change_rien(overlay_isole) -> None:
    batiment = [Room(id="h101", label="H.101", capacity=35, room_type=RoomType.STANDARD)]
    fusion = overlay_isole.merge_into(batiment)
    assert fusion[0].placement_auto is True


# ==========================================================================
# 2. Solveur — `assign_rooms` / `find_room_for_slot`
# ==========================================================================


def _seance(sid: str, code: str = "WR999", session_type: SessionType = SessionType.TD) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=session_type,
        sequence_order=1, group_ids=["but1-tp-a"], teacher_codes=["T1"],
    )


def _rooms_avec_bu(bu_auto: bool = False) -> list[Room]:
    return [
        # Meilleur "best fit" (plus petite salle qui convient) si elle était
        # éligible : c'est exactement ce que doit éviter le filtre.
        Room(id="bu", label="BU / A.123", capacity=15, room_type=RoomType.STANDARD, placement_auto=bu_auto),
        Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD),
    ]


def test_assign_rooms_n_affecte_jamais_bu_automatiquement_si_une_autre_salle_convient() -> None:
    placements = [PlacedSession(session_id="a", week=0, day=0, slot=0, course_code="WR999",
                                 group_ids=["but1-tp-a"], teacher_codes=["T1"])]
    sessions = {"a": _seance("a")}
    resultats = assign_rooms(placements, sessions, _rooms_avec_bu(), GROUPES, [])
    assert resultats[0].room_id == "h101", (
        f"BU choisie automatiquement alors que H.101 convenait : {resultats[0].room_id}"
    )


def test_assign_rooms_repli_vers_bu_reste_interdit_meme_sans_aucune_salle_qui_convient() -> None:
    """Le DERNIER recours (« plus grande salle libre, même insuffisante »)
    est encore un choix AUTOMATIQUE : `placement_auto=False` s'y applique
    aussi, la séance doit rester sans salle plutôt que d'y atterrir seule."""
    placements = [PlacedSession(session_id="a", week=0, day=0, slot=0, course_code="WR999",
                                 group_ids=["but1-tp-a"], teacher_codes=["T1"])]
    sessions = {"a": _seance("a")}
    resultats = assign_rooms(placements, sessions, [_rooms_avec_bu()[0]], GROUPES, [])
    assert resultats[0].room_id is None


def test_assign_rooms_avec_une_regle_qui_nomme_bu_explicitement_l_affecte_quand_meme() -> None:
    """« explicite bat le drapeau » : une règle `preferred_room_ids: [bu]`
    dédiée à un module continue de lui donner la BU."""
    regles = parse_room_rules([
        {
            "course_code_patterns": ["WR100BU"],
            "session_types": ["TD"],
            "preferred_room_types": ["standard"],
            "fallback_room_types": [],
            "preferred_room_ids": ["bu"],
        }
    ])
    placements = [PlacedSession(session_id="a", week=0, day=0, slot=0, course_code="WR100BU",
                                 group_ids=["but1-tp-a"], teacher_codes=["T1"])]
    sessions = {"a": _seance("a", code="WR100BU")}
    resultats = assign_rooms(placements, sessions, _rooms_avec_bu(), GROUPES, regles)
    assert resultats[0].room_id == "bu"


def test_assign_rooms_bu_deja_auto_true_reste_choisissable_normalement() -> None:
    """Non-régression : le filtre ne doit rien changer pour une salle dont
    `placement_auto` vaut `True` (comportement par défaut, best-fit normal)."""
    placements = [PlacedSession(session_id="a", week=0, day=0, slot=0, course_code="WR999",
                                 group_ids=["but1-tp-a"], teacher_codes=["T1"])]
    sessions = {"a": _seance("a")}
    resultats = assign_rooms(placements, sessions, _rooms_avec_bu(bu_auto=True), GROUPES, [])
    assert resultats[0].room_id == "bu"


def _find_room(rooms, prefer_room_id=None, rules=None, session=None):
    return find_room_for_slot(
        session or _seance("a"), week=0, day=0, slot=0, timetable=[],
        sessions_by_id={"a": session or _seance("a")}, rooms=rooms, groups=GROUPES,
        rules=rules or [], prefer_room_id=prefer_room_id,
    )


def test_find_room_for_slot_sans_preference_ecarte_bu() -> None:
    salle = _find_room(_rooms_avec_bu())
    assert salle is not None and salle.id == "h101"


def test_find_room_for_slot_garde_bu_si_deja_affectee_et_encore_libre() -> None:
    """« stays assigned where it already is » — un déplacement qui garde la
    même salle ne doit pas la perdre juste parce qu'elle est hors auto."""
    salle = _find_room(_rooms_avec_bu(), prefer_room_id="bu")
    assert salle is not None and salle.id == "bu"


def test_find_room_for_slot_avec_regle_explicite_choisit_bu() -> None:
    regles = parse_room_rules([
        {
            "course_code_patterns": ["WR100BU"],
            "session_types": ["TD"],
            "preferred_room_types": [],
            "fallback_room_types": [],
            "preferred_room_ids": ["bu"],
        }
    ])
    session = _seance("a", code="WR100BU")
    salle = _find_room(_rooms_avec_bu(), rules=regles, session=session)
    assert salle is not None and salle.id == "bu"


# ==========================================================================
# 3. API — création, modification (admin), choix manuel préservé
# ==========================================================================


SEMAINE = 12


@pytest.fixture
def etat():
    etat = get_state()
    ancien = {k: getattr(etat, k) for k in (
        "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
        "current_run_id", "teacher_availability", "config_dir", "student_presences",
        "corrections", "courses", "teacher_duos", "semestre_group",
    )}
    a = SessionToPlace(
        id="a", course_code="WR999", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["KBR"],
    )
    etat.sessions = [a]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a", week=SEMAINE, day=0, slot=0, course_code="WR999",
                               group_ids=["but1-td-ab"], teacher_codes=["KBR"],
                               room_id="h101", room_label="H.101"),
    ]
    etat.rooms = [
        Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD),
        Room(id="bu", label="BU / A.123", capacity=30, room_type=RoomType.STANDARD, placement_auto=False),
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
def _connecte_admin(db_isole):
    creer_compte_actif_et_connecter(client, role="admin")
    yield


def test_choix_manuel_de_bu_reste_possible_via_changer_salle(etat) -> None:
    """Une salle hors placement automatique reste choisissable À LA MAIN."""
    reponse = client.patch("/placements/a/salle", json={"room_id": "bu"})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "bu"


def test_creer_salle_placement_auto_false_est_persiste(etat) -> None:
    reponse = client.post("/rooms", json={"label": "Salle dédiée", "capacity": 12, "placement_auto": False})
    assert reponse.status_code == 200, reponse.text
    salle = reponse.json()
    assert salle["placement_auto"] is False

    from cal_iut.api import custom_rooms

    persistee = next(r for r in custom_rooms.load_custom_rooms() if r.id == salle["id"])
    assert persistee.placement_auto is False


def test_creer_salle_placement_auto_est_coche_par_defaut(etat) -> None:
    reponse = client.post("/rooms", json={"label": "Salle Générique", "capacity": 20})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["placement_auto"] is True


def test_patch_rooms_modifie_placement_auto_d_une_salle_du_batiment(etat) -> None:
    reponse = client.patch("/rooms/h101", json={"placement_auto": False})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["placement_auto"] is False
    assert next(r for r in get_state().rooms if r.id == "h101").placement_auto is False

    from cal_iut.api import custom_rooms

    assert custom_rooms.load_overrides()["h101"]["placement_auto"] is False


def test_patch_rooms_salle_inconnue_404(etat) -> None:
    reponse = client.patch("/rooms/fantome", json={"placement_auto": False})
    assert reponse.status_code == 404


def test_patch_rooms_refuse_sans_authentification(etat) -> None:
    anonyme = TestClient(app)
    reponse = anonyme.patch("/rooms/h101", json={"placement_auto": False})
    assert reponse.status_code == 401


def test_patch_rooms_refuse_role_non_admin(etat) -> None:
    non_admin = TestClient(app)
    creer_compte_actif_et_connecter(non_admin, role="edit")
    reponse = non_admin.patch("/rooms/h101", json={"placement_auto": False})
    assert reponse.status_code == 403


def test_aucun_endpoint_ne_reste_sans_protection() -> None:
    """`PATCH /rooms/{room_id}` doit rester sous le préfixe protégé `/rooms`
    (cf. `main.py::_verifier_couverture_auth`) — même garde-fou que pour
    `POST /rooms` (28/08/2026)."""
    from cal_iut.api.main import _verifier_couverture_auth

    assert _verifier_couverture_auth() == []
