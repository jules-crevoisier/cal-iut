"""Retour Kyllian Bresson 25/09/2026 : « une possibilité de vérification
après placement pour salles et enseignants en double. Car quand je déplace à
la main, même avec les vérifications je dois faire des doublons [...] Et
aussi pour H.201 et H.203, c'est en soi la même salle, donc il ne faut pas
deux modules différents en même temps dans ces deux salles, pareil pour
H.007 et H.008. »

Bug réel trouvé en explorant `api/validation.py::validate_move` : sa branche
de conflit de salle existe depuis longtemps, mais TOUS ses appelants réels
(`move_session`, `placer_seance`, `validate_placement`, `_controler_echange`,
`session_patch.py::_controler_placement`, `mcp/tools.py::_evaluer_placement`)
lui passaient `_as_placed(state.timetable)`, qui convertit
`PlacedSessionWithRoom` en `PlacedSession` — SANS champ `room_id` — avant de
le lui passer. `getattr(placement, "room_id", None)` valait donc toujours
`None`, et la branche « Conflit salle » ne se déclenchait JAMAIS en pratique,
quel que soit le déplacement demandé. Corrigé en passant `state.timetable`
TEL QUEL (superclasse structurelle de `PlacedSession`, déjà lue par
`getattr` en duck typing) à `validate_move`, plutôt qu'en réécrivant
`_as_placed`/`PlacedSession` (qui aurait fallu changer partout, y compris
pour `compute_quality`/`suggest_alternative_slots`, hors périmètre).

Ce module teste la conséquence côté API (ce qui remonte enfin), pas
`validate_move` lui-même (déjà couvert par `tests/test_validation_manuelle.
py::test_un_conflit_de_salle_est_toujours_signale`, qui montre que la
fonction PURE a toujours su lire un `room_id` — le trou était uniquement
dans ses appelants).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.api.validation import validate_move
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import Course, Room, RoomType, SessionType, Teacher, TeacherBlock
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import (
    PlacedSessionWithRoom,
    _build_conflict_map,
    build_manual_conflict_map,
)

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")

# Semaine/jour/créneau de référence, cohérents avec les autres tests de ce
# module (`10, 0, 0` : une semaine future, jamais verrouillée).
SEM, JOUR, SLOT = 10, 0, 0

ROOMS = [
    Room(id="h101", label="H.101", capacity=15, room_type=RoomType.STANDARD),
    Room(id="h201", label="H.201", capacity=35, room_type=RoomType.STANDARD),
    Room(id="h203", label="H.203", capacity=35, room_type=RoomType.STANDARD),
    Room(id="h201_h203", label="H.201-203", capacity=70, room_type=RoomType.COMBINED, combines=["h201", "h203"]),
    Room(id="h007", label="H.007", capacity=15, room_type=RoomType.TP_STANDARD),
    Room(id="h008", label="H.008", capacity=15, room_type=RoomType.TP_STANDARD),
    Room(id="h007_h008", label="H.007-008", capacity=30, room_type=RoomType.COMBINED, combines=["h007", "h008"]),
]


def _seance(sid: str, groupe: str = "but1-td-ab", prof: str = "MRI", code: str = "ZZDBL1") -> SessionToPlace:
    # Pas de `sequence_order` : ce module teste le conflit de RESSOURCE
    # (salle), pas l'ordre pédagogique — deux séances du même
    # `sequence_order` avec des matières différentes déclencheraient un
    # verrou institutionnel sans rapport (« ordre pédagogique »), qui
    # masquerait le conflit de salle qu'on veut isoler ici. `code` distinct
    # pour `occupante_h201`/`occupante_h008` : elles n'ont aucun rapport
    # pédagogique avec `manquante`, seulement une salle en commun.
    return SessionToPlace(
        id=sid, course_code=code, course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        group_ids=[groupe], teacher_codes=[prof], duration_slots=1,
    )


def _cours(code: str = "ZZDBL1") -> Course:
    prof = Teacher(code="MRI2", nom="Test", prenom="Prof")
    return Course(
        code=code, name="Culture numérique", semestre="S1", parcours="BUT1", annee="BUT1",
        lead=prof, profs=[TeacherBlock(teacher=prof, block="1", td=17, nbGpTd=1, nbGpTp=1)],
        volumes={"cm": 0, "td": 17, "tp": 0}, groupes_td=1, groupes_tp=1,
        progression_defined=False, seance_sequence=[], ordonnancement=[],
    )


def _place(session: SessionToPlace, week: int, day: int, slot: int, room_id: str, room_label: str) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=session.id, week=week, day=day, slot=slot,
        course_code=session.course_code, group_ids=list(session.group_ids),
        teacher_codes=list(session.teacher_codes), room_id=room_id, room_label=room_label,
    )


@pytest.fixture
def client(monkeypatch, db_isole):
    """Deux séances déjà posées à `(SEM, JOUR, SLOT)`, l'une en H.201 (occupe(e)
    par `occupante_h201`, autre groupe/prof pour ne PAS déclencher les
    conflits groupe/enseignant qu'on ne teste pas ici) — plus une séance
    `manquante` (même créneau, jamais placée) qu'on tente de poser/déplacer
    successivement dans H.201 (même salle), H.203 (salle physiquement liée)
    et H.101 (salle libre, doit passer)."""
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "groups": etat.groups, "rooms": etat.rooms,
        "calendar": etat.calendar, "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability, "teacher_duos": etat.teacher_duos,
        "corrections": etat.corrections, "courses": etat.courses,
        "config_dir": etat.config_dir,
    }

    occupante = _seance("occupante_h201", groupe="but2-dev-fi-td-ab", prof="AUTRE", code="WR999")
    manquante = _seance("manquante", groupe="but1-td-ab", prof="MRI")
    etat.sessions = [occupante, manquante]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [_place(occupante, SEM, JOUR, SLOT, "h201", "H.201")]
    etat.groups = GROUPES
    etat.rooms = ROOMS
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    etat.config_dir = ROOT / "data" / "config"

    client = TestClient(app)
    creer_compte_actif_et_connecter(client)
    yield client

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


# --------------------------------------------------------------------------
# `build_manual_conflict_map` — la classe d'équivalence des salles combinées
# --------------------------------------------------------------------------


def test_la_carte_du_solveur_garde_les_deux_parties_independantes():
    """`_build_conflict_map` (affectation AUTOMATIQUE du solveur) NE DOIT PAS
    changer : le hack duo synchronisé (`_duo_room_overrides`) réserve
    volontairement H.007 ET H.008 EN MÊME TEMPS pour deux enseignants d'un
    même duo — un vrai conflit ici casserait ce mécanisme en silence."""
    conflits = _build_conflict_map(ROOMS)
    assert "h203" not in conflits["h201"]
    assert "h201" not in conflits["h203"]
    assert conflits["h201"] == {"h201_h203"}


def test_la_carte_manuelle_ajoute_le_conflit_croise_entre_les_deux_parties():
    """`build_manual_conflict_map` (contrôles a posteriori) DOIT, elle,
    considérer H.201 et H.203 comme mutuellement en conflit — retour
    Kyllian Bresson 25/09/2026."""
    conflits = build_manual_conflict_map(ROOMS)
    assert conflits["h201"] == {"h203", "h201_h203"}
    assert conflits["h203"] == {"h201", "h201_h203"}
    assert conflits["h201_h203"] == {"h201", "h203"}
    # Classe d'équivalence identique pour les trois identifiants — c'est ce
    # que `api/doublons.py` utilise comme clé de regroupement.
    for salle in ("h201", "h203", "h201_h203"):
        assert {salle} | conflits[salle] == {"h201", "h203", "h201_h203"}


def test_une_salle_normale_sans_combines_reste_seule_dans_sa_classe():
    conflits = build_manual_conflict_map(ROOMS)
    assert conflits["h101"] == set()


# --------------------------------------------------------------------------
# `PATCH /placements/{id}` (move_session)
# --------------------------------------------------------------------------


def test_deplacer_dans_la_meme_salle_qu_une_autre_seance_est_refuse(client):
    reponse = client.post("/placements/manquante/placer", json={"week": SEM, "day": JOUR, "slot": SLOT + 2})
    assert reponse.status_code == 200, reponse.text

    reponse = client.patch(
        "/placements/manquante", json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h201"},
    )
    assert reponse.status_code == 409, reponse.text
    assert "salle" in reponse.json()["detail"]["hard_conflicts"][0].lower()


def test_deplacer_dans_h203_alors_que_h201_est_prise_est_refuse(client):
    """H.201 et H.203 : même salle physique — retour Kyllian Bresson
    25/09/2026, verbatim « il ne faut pas deux modules différents en même
    temps dans ces deux salles »."""
    client.post("/placements/manquante/placer", json={"week": SEM, "day": JOUR, "slot": SLOT + 2})

    reponse = client.patch(
        "/placements/manquante", json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h203"},
    )
    assert reponse.status_code == 409, reponse.text
    assert "salle" in reponse.json()["detail"]["hard_conflicts"][0].lower()


def test_le_conflit_de_salle_reste_forcable(client):
    """Même doctrine que le verrou de semaine : un conflit de RESSOURCE se
    force, jamais un verrou institutionnel."""
    client.post("/placements/manquante/placer", json={"week": SEM, "day": JOUR, "slot": SLOT + 2})

    reponse = client.patch(
        "/placements/manquante",
        json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h203", "force": True},
    )
    assert reponse.status_code == 200, reponse.text


def test_deplacer_dans_une_salle_libre_reste_accepte(client):
    """Pas de faux positif : H.101 n'a aucun lien avec H.201/H.203."""
    client.post("/placements/manquante/placer", json={"week": SEM, "day": JOUR, "slot": SLOT + 2})

    reponse = client.patch(
        "/placements/manquante", json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h101"},
    )
    assert reponse.status_code == 200, reponse.text


def test_deplacer_une_seance_qui_quitte_sa_salle_ne_se_bloque_pas_elle_meme(client):
    """Pas de faux positif : `occupante_h201`, qu'on déplace hors de H.201,
    ne doit pas se voir refuser sa PROPRE ancienne place."""
    reponse = client.patch(
        "/placements/occupante_h201", json={"week": SEM, "day": JOUR, "slot": SLOT + 1, "room_id": "h201"},
    )
    assert reponse.status_code == 200, reponse.text


# --------------------------------------------------------------------------
# `POST /placements/{id}/placer`
# --------------------------------------------------------------------------


def test_placer_directement_dans_une_salle_deja_prise_est_refuse(client):
    reponse = client.post(
        "/placements/manquante/placer",
        json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h201"},
    )
    assert reponse.status_code == 409, reponse.text
    assert "salle" in reponse.json()["detail"]["hard_conflicts"][0].lower()


def test_placer_dans_h007_alors_que_h008_est_prise_est_refuse(client):
    etat = get_state()
    autre = _seance("occupante_h008", groupe="but2-dev-fi-td-ab", prof="AUTRE2", code="WR998")
    etat.sessions.append(autre)
    etat.sessions_by_id[autre.id] = autre
    etat.timetable.append(_place(autre, SEM, JOUR, SLOT + 1, "h008", "H.008"))

    reponse = client.post(
        "/placements/manquante/placer",
        json={"week": SEM, "day": JOUR, "slot": SLOT + 1, "room_id": "h007"},
    )
    assert reponse.status_code == 409, reponse.text
    assert "salle" in reponse.json()["detail"]["hard_conflicts"][0].lower()


# --------------------------------------------------------------------------
# `POST /placements/personnalisees` (création)
# --------------------------------------------------------------------------


def test_creer_une_seance_dans_une_salle_deja_prise_est_refuse(client):
    get_state().courses = [_cours("ZZDBL1")]
    reponse = client.post("/placements/personnalisees", json={
        "course_code": "ZZDBL1", "session_type": "TD",
        "group_ids": ["but1-td-cd"], "teacher_codes": ["MRI2"],
        "duration_slots": 1, "is_eval": False,
        "week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h201",
    })
    assert reponse.status_code == 409, reponse.text
    assert "salle" in reponse.json()["detail"]["hard_conflicts"][0].lower()


# --------------------------------------------------------------------------
# `POST /placements/{id}/validate` (dry-run)
# --------------------------------------------------------------------------


def test_le_dry_run_signale_le_conflit_de_salle_sans_rien_modifier(client):
    client.post("/placements/manquante/placer", json={"week": SEM, "day": JOUR, "slot": SLOT + 2})

    reponse = client.post(
        "/placements/manquante/validate", json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h201"},
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["valid"] is False
    assert any("salle" in c.lower() for c in corps["hard_conflicts"])
    # Forçable : jamais dans `blocking_conflicts` (même doctrine que le
    # verrou de semaine — cf. `ValidationResponse.blocking_conflicts`).
    assert corps["blocking_conflicts"] == []
    # Rien de modifié : c'est un dry-run.
    place = next(p for p in get_state().timetable if p.session_id == "manquante")
    assert (place.week, place.day, place.slot) == (SEM, JOUR, SLOT + 2)


def test_le_dry_run_ne_signale_rien_pour_une_salle_libre(client):
    client.post("/placements/manquante/placer", json={"week": SEM, "day": JOUR, "slot": SLOT + 2})

    reponse = client.post(
        "/placements/manquante/validate", json={"week": SEM, "day": JOUR, "slot": SLOT, "room_id": "h101"},
    )
    corps = reponse.json()
    assert corps["valid"] is True
    assert corps["hard_conflicts"] == []


# --------------------------------------------------------------------------
# Pause méridienne : exemption inchangée (`validate_move`, `_est_pause_midi`)
# --------------------------------------------------------------------------


def test_une_seance_normale_n_est_jamais_en_conflit_avec_un_evenement_pause_midi():
    """Un évènement `pause_midi` occupe le créneau de STOCKAGE (3) mais ne
    doit JAMAIS bloquer, ni être bloqué par, une séance normale sur ce même
    créneau — même salle y compris (`validate_move` les exempte
    complètement l'une de l'autre, cf. son docstring, retour Jules
    23/09/2026). Vérifié directement sur `validate_move` : le trou corrigé
    dans ce contrat (callers perdant `room_id`) ne touche QUE la branche
    « salle », jamais celle-ci."""
    pause = PlacedSessionWithRoom(
        session_id="pause", week=0, day=0, slot=3, course_code="PAUSE",
        group_ids=["but1-td-ab"], teacher_codes=[], room_id="h101", room_label="H.101",
    )
    sessions_by_id = {
        "pause": SessionToPlace(
            id="pause", course_code="PAUSE", course_name="Pause", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
            group_ids=["but1-td-ab"], teacher_codes=[], metadata={"pause_midi": True},
        ),
        "normale": SessionToPlace(
            id="normale", course_code="ZZDBL1", course_name="Culture numérique", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
            group_ids=["but1-td-ab"], teacher_codes=["MRI"],
        ),
    }
    resultat = validate_move(
        "normale", 0, 0, 3, [pause], ["but1-td-ab"], ["MRI"], room_id="h101",
        sessions_by_id=sessions_by_id, groups=GROUPES,
    )
    assert resultat.valid, resultat.hard_conflicts
