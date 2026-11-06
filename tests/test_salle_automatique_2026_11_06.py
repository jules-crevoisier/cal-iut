"""« Automatique » dans le menu des salles (tâche 33) et lecture Celcat de toutes
les salles configurées (tâche 23) : recherche d'une salle libre, continuité avec
les séances voisines, capacité vérifiée, « Sans salle » + message sinon.
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

# Semaine volontairement lointaine : `_check_move_editable` refuse toute
# semaine passée/en cours, ce qui ferait échouer ces tests pour une raison
# sans rapport avec ce qu'ils vérifient.
SEMAINE = 12


def _seance(sid: str, groupe: str, prof: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=f"WR{sid}", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=[groupe], teacher_codes=[prof],
    )


@pytest.fixture
def etat():
    etat = get_state()
    ancien = {k: getattr(etat, k) for k in (
        "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
        "current_run_id", "teacher_availability", "config_dir", "student_presences",
        "corrections", "courses", "teacher_duos", "semestre_group",
    )}
    a = _seance("a", "but1-td-ab", "KBR")
    b = _seance("b", "but1-td-cd", "ALO")
    c = _seance("c", "but1-td-ab", "KBR")
    etat.sessions = [a, b, c]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    # `a` et `b` au MÊME créneau, dans deux salles différentes.
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a", week=SEMAINE, day=0, slot=0, course_code="WRa",
                               group_ids=["but1-td-ab"], teacher_codes=["KBR"],
                               room_id="h101", room_label="H.101"),
        PlacedSessionWithRoom(session_id="b", week=SEMAINE, day=0, slot=0, course_code="WRb",
                               group_ids=["but1-td-cd"], teacher_codes=["ALO"],
                               room_id="h102", room_label="H.102"),
        # Séance voisine de `a` (même groupe, créneau suivant) en H.103.
        PlacedSessionWithRoom(session_id="c", week=SEMAINE, day=0, slot=1, course_code="WRc",
                               group_ids=["but1-td-ab"], teacher_codes=["KBR"],
                               room_id="h103", room_label="H.103"),
    ]
    etat.rooms = [
        Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h102", label="H.102", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h103", label="H.103", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h104", label="H.104", capacity=30, room_type=RoomType.STANDARD),
        # Volontairement trop petite : sert aux tests d'avertissement de
        # capacité (un TD BUT1 = 30 étudiants).
        Room(id="h006", label="H.006", capacity=15, room_type=RoomType.STANDARD),
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
    # role="admin" : `test_creer_une_salle_puis_l_affecter` etc. exercent
    # `POST /rooms`, désormais `Depends(accounts.require_role("admin"))`
    # (ex-`require_admin_session`) — admin couvre aussi les routes `edit`
    # utilisées par le reste du fichier (`ROLE_ORDER`, `accounts.py`).
    creer_compte_actif_et_connecter(client, role="admin")
    yield


def test_automatique_prefere_la_salle_de_la_seance_voisine(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "__auto__"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    # H.103 est celle de la séance d'à côté (même groupe) : continuité.
    assert corps["room_id"] == "h103"
    assert corps["salle_message"] is None


def test_automatique_evite_une_salle_prise_dans_celcat(etat, monkeypatch) -> None:
    from cal_iut.api import occupations_externes
    from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

    base = SEMAINE * DAYS_PER_WEEK * SLOTS_PER_DAY
    monkeypatch.setattr(occupations_externes, "reservations_effectives", lambda _s: {"h103": {base}})
    corps = client.patch("/placements/a/salle", json={"room_id": "__auto__"}).json()
    assert corps["room_id"] not in ("h103", "h102")


def test_automatique_sans_salle_assez_grande_donne_sans_salle_et_un_message(etat) -> None:
    etat.rooms = [r for r in etat.rooms if r.id in ("h102", "h006")]  # prise / trop petite
    reponse = client.patch("/placements/a/salle", json={"room_id": "__auto__"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["room_id"] is None
    assert "Aucune salle" in corps["salle_message"]


def test_sans_salle_reste_distinct_d_automatique(etat) -> None:
    corps = client.patch("/placements/a/salle", json={"room_id": ""}).json()
    assert corps["room_id"] is None
    assert corps["salle_message"] is None


def test_toutes_les_salles_configurees_sont_lues_dans_celcat() -> None:
    from cal_iut.celcat import occupations as occ

    ressources = occ.ressources_depuis_config(occ.ConfigOccupations(), ROOT / "data" / "config")
    codes = {r.code for r in ressources if r.type == "salle"}
    assert {"c001", "b002", "e201", "e212"} <= codes


def test_une_salle_sans_entree_celcat_est_lue_avec_son_libelle(tmp_path) -> None:
    import shutil

    from cal_iut.celcat import occupations as occ

    for f in (ROOT / "data" / "config").iterdir():
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    rooms = (tmp_path / "rooms.yaml").read_text(encoding="utf-8")
    rooms = rooms.replace("\nroom_assignment_rules:", """
  - id: z999
    label: Z.999
    capacity: 20
    room_type: standard
    equipment: []

room_assignment_rules:""", 1)
    (tmp_path / "rooms.yaml").write_text(rooms, encoding="utf-8")
    ressources = occ.ressources_depuis_config(occ.ConfigOccupations(), tmp_path)
    nouvelle = next(r for r in ressources if r.code == "z999")
    assert nouvelle.celcat == "Z.999"
