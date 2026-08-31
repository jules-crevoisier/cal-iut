"""Changement de salle SEULE, à créneau inchangé (`PATCH /placements/{id}/
salle`) — retour utilisateur 28/08/2026 : « on va vouloir sur la vue promo
modifier uniquement les salles ».

Ce qui est réellement vérifié ici, au-delà du cas passant : que cet endpoint
ne refuse PAS pour des raisons sans rapport avec la salle. C'est toute sa
raison d'être face à `PATCH /placements/{id}` (qui sait déjà changer la
salle au passage, mais refait tous les contrôles de POSITION) — un conflit
groupe/enseignant préexistant, ou une séance posée à une position limite,
ne doit jamais empêcher de corriger sa salle.
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
    etat.sessions = [a, b]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    # `a` et `b` au MÊME créneau, dans deux salles différentes.
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a", week=SEMAINE, day=0, slot=0, course_code="WRa",
                               group_ids=["but1-td-ab"], teacher_codes=["KBR"],
                               room_id="h101", room_label="H.101"),
        PlacedSessionWithRoom(session_id="b", week=SEMAINE, day=0, slot=0, course_code="WRb",
                               group_ids=["but1-td-cd"], teacher_codes=["ALO"],
                               room_id="h102", room_label="H.102"),
    ]
    etat.rooms = [
        Room(id="h101", label="H.101", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h102", label="H.102", capacity=30, room_type=RoomType.STANDARD),
        Room(id="h103", label="H.103", capacity=30, room_type=RoomType.STANDARD),
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


def test_salle_inconnue_donne_un_404(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "fantome"})
    assert reponse.status_code == 404


def test_salle_libre_est_acceptee_et_ne_bouge_pas_le_creneau(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "h103"})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["room_id"] == "h103"
    assert corps["room_label"] == "H.103"
    # Le créneau doit être STRICTEMENT inchangé — c'est tout l'objet de cet
    # endpoint par rapport au déplacement classique.
    assert (corps["week"], corps["day"], corps["slot"]) == (SEMAINE, 0, 0)
    place = next(p for p in get_state().timetable if p.session_id == "a")
    assert (place.week, place.day, place.slot) == (SEMAINE, 0, 0)
    assert place.room_id == "h103"


def test_salle_occupee_au_meme_creneau_est_refusee(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "h102"})
    assert reponse.status_code == 409
    conflits = reponse.json()["detail"]["hard_conflicts"]
    assert any("salle" in c.lower() for c in conflits)


def test_salle_occupee_passe_en_forcant(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "h102", "force": True})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "h102"


def test_une_salle_libre_a_un_autre_creneau_ne_bloque_pas(etat) -> None:
    """`h102` est occupée par `b`, mais un AUTRE jour : aucun conflit."""
    etat.timetable[1].day = 2
    reponse = client.patch("/placements/a/salle", json={"room_id": "h102"})
    assert reponse.status_code == 200, reponse.text


def test_un_conflit_groupe_preexistant_ne_bloque_pas_le_changement_de_salle(etat) -> None:
    """LE cas qui justifie cet endpoint : `a` et `b` partagent le même
    groupe au même créneau (conflit groupe réel, préexistant). Corriger la
    SALLE de `a` ne doit pas être refusé pour ce motif — le conflit existait
    avant, il n'est ni créé ni aggravé par ce changement, et refuser
    laisserait une salle fausse impossible à corriger."""
    etat.timetable[1].group_ids = ["but1-td-ab"]
    etat.sessions_by_id["b"].group_ids = ["but1-td-ab"]

    reponse = client.patch("/placements/a/salle", json={"room_id": "h103"})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "h103"


# --------------------------------------------------------------------------
# Création d'une salle hors bâtiment (`POST /rooms`) — retour utilisateur
# 28/08/2026 : « il se peut que l'on utilise des salles autres que dans le
# bâtiment, il faut donc laisser la possibilité de créer une salle ».
# --------------------------------------------------------------------------


def test_creer_une_salle_puis_l_affecter(etat) -> None:
    reponse = client.post("/rooms", json={"label": "Amphi Descartes", "capacity": 120})
    assert reponse.status_code == 200, reponse.text
    salle = reponse.json()
    # Identifiant dérivé du libellé : la personne n'a pas à en inventer un.
    assert salle["id"] == "amphi-descartes"
    assert salle["capacity"] == 120

    # Immédiatement utilisable pour une affectation manuelle.
    maj = client.patch("/placements/a/salle", json={"room_id": salle["id"]})
    assert maj.status_code == 200, maj.text
    assert maj.json()["room_label"] == "Amphi Descartes"


def test_un_libelle_deja_pris_est_refuse(etat) -> None:
    """Insensible à la casse : « h.101 » et « H.101 » désignent la même
    salle pour un humain, en accepter deux créerait deux salles distinctes
    impossibles à distinguer dans la liste de choix."""
    reponse = client.post("/rooms", json={"label": "h.101", "capacity": 30})
    assert reponse.status_code == 409


def test_un_libelle_vide_est_refuse(etat) -> None:
    reponse = client.post("/rooms", json={"label": "   ", "capacity": 30})
    assert reponse.status_code == 400


def test_la_salle_creee_est_persistee(etat, tmp_path) -> None:
    """Persistée dans `data/state/` (volume Docker) et pas dans
    `data/config/rooms.yaml`, réécrit à chaque déploiement — sinon une salle
    créée en production disparaîtrait au redéploiement suivant."""
    from cal_iut.api import custom_rooms

    client.post("/rooms", json={"label": "Salle Externe", "capacity": 40})
    persistees = custom_rooms.load_custom_rooms()
    assert [r.label for r in persistees] == ["Salle Externe"]
    # Et re-fusionnée avec les salles du bâtiment au démarrage suivant.
    fusion = custom_rooms.merge_into(list(etat.rooms))
    assert any(r.id == "salle-externe" for r in fusion)


def test_aucun_endpoint_ne_reste_sans_protection() -> None:
    """Garde-fou de couverture d'authentification (`main.py::
    _verifier_couverture_auth`) : `POST /rooms` est resté accessible sans
    mot de passe parce qu'un endpoint dont le chemin ne commence par aucun
    préfixe connu devenait public EN SILENCE. Ce test fait échouer l'ajout
    d'un futur endpoint non classé, au lieu de laisser un trou passer
    inaperçu jusqu'à ce qu'un humain le remarque."""
    from cal_iut.api.main import _verifier_couverture_auth

    assert _verifier_couverture_auth() == []


# --------------------------------------------------------------------------
# Avertissement de capacité — retour utilisateur 28/08/2026 : « il faut
# mettre un warning quand l'on change de salle s'il y a un conflit ».
# --------------------------------------------------------------------------


def test_une_salle_trop_petite_declenche_un_avertissement(etat) -> None:
    """Signalé comme `soft_warnings` et non `hard_conflicts` : ce n'est pas
    une impossibilité (groupe partiellement absent, TP dédoublé...), mais ça
    ne doit jamais passer en silence."""
    reponse = client.patch("/placements/a/salle", json={"room_id": "h006"})
    assert reponse.status_code == 409
    detail = reponse.json()["detail"]
    assert detail["hard_conflicts"] == []  # la salle est LIBRE, rien d'occupé
    assert any("apacité" in w for w in detail["soft_warnings"])
    assert any("15" in w and "30" in w for w in detail["soft_warnings"]), detail["soft_warnings"]


def test_la_salle_trop_petite_reste_acceptable_en_forcant(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "h006", "force": True})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["room_id"] == "h006"


def test_une_salle_assez_grande_ne_declenche_aucun_avertissement(etat) -> None:
    reponse = client.patch("/placements/a/salle", json={"room_id": "h103"})
    assert reponse.status_code == 200, reponse.text


def test_occupation_et_capacite_sont_signalees_ensemble(etat) -> None:
    """Les deux problèmes à la fois doivent être montrés d'un coup — sinon
    on corrige l'un, on relance, et on découvre l'autre."""
    etat.timetable[1].room_id = "h006"  # `b` occupe la petite salle au même créneau
    reponse = client.patch("/placements/a/salle", json={"room_id": "h006"})
    assert reponse.status_code == 409
    detail = reponse.json()["detail"]
    assert detail["hard_conflicts"], "l'occupation doit être signalée"
    assert detail["soft_warnings"], "la capacité doit l'être aussi"
