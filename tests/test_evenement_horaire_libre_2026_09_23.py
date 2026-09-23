"""Évènement à horaire libre — retour Jules 23/09/2026 (Kyllian Bresson) :
« Possible de m'ajouter une séance évènement en CM H.018 pour tout le monde
demain (jeudi) à 13h15 jusqu'à 14h. Présentation PAC [...] Sans mettre
d'enseignant. Histoire de l'afficher proprement. »

13h15-14h ne tombe dans AUCUN des six créneaux fixes (pause méridienne,
entre le créneau 2 — 11h-12h30 — et le créneau 3 — 14h-15h30). Décision de
Jules : afficher ce genre d'évènement dans la ligne "pause" de Vue Promo, à
son horaire réel, stocké en mémoire sur le créneau 3 (position de stockage
UNIQUEMENT, jamais affichée telle quelle).
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
from cal_iut.models.entities import Room, RoomType, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
SEMAINE = 10


def _seance(sid, groupe="but1-promo") -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Cours existant", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM, sequence_order=1,
        group_ids=[groupe], teacher_codes=[], duration_slots=1,
    )


def _place(s: SessionToPlace, day: int, slot: int, week: int = SEMAINE) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=s.id, week=week, day=day, slot=slot, course_code=s.course_code,
        group_ids=list(s.group_ids), teacher_codes=list(s.teacher_codes),
    )


H018 = Room(id="h018", label="H.018", capacity=200, room_type=RoomType.AMPHI)


@pytest.fixture
def monter(db_isole):
    etat = get_state()
    ancien = {
        c: getattr(etat, c)
        for c in (
            "sessions", "sessions_by_id", "timetable", "groups", "rooms", "calendar",
            "current_run_id", "teacher_availability", "teacher_duos", "corrections",
            "courses", "config_dir",
        )
    }

    def _monter(paires, courses=None, rooms=None, role="edit"):
        etat.sessions = [s for s, _ in paires]
        etat.sessions_by_id = {s.id: s for s, _ in paires}
        etat.timetable = [p for _, p in paires if p is not None]
        etat.groups = GROUPES
        etat.rooms = rooms or []
        etat.calendar = build_default_calendar_2026_2027()
        etat.current_run_id = None
        etat.teacher_availability = []
        etat.teacher_duos = []
        etat.corrections = []
        etat.courses = courses if courses is not None else []
        etat.config_dir = ROOT / "data" / "config"
        client = TestClient(app)
        creer_compte_actif_et_connecter(client, role=role)
        return client

    yield _monter

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _corps(**over):
    corps = {
        "libelle": "Présentation PAC", "semestre": "S1",
        "group_ids": ["but1-promo"], "teacher_codes": [],
        "duration_slots": 1, "note": "",
        "week": SEMAINE, "day": 3, "slot": 3, "force": False,
    }
    corps.update(over)
    return corps


# ── 1. Schéma : heure_debut/heure_fin optionnels, validés ──


def test_heure_debut_et_heure_fin_vont_ensemble(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/evenements", json=_corps(heure_debut="13:15"))
    assert r.status_code == 422


def test_heure_fin_doit_etre_apres_heure_debut(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/evenements", json=_corps(heure_debut="14:00", heure_fin="13:15"))
    assert r.status_code == 422


def test_format_horaire_invalide_refuse(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post("/placements/evenements", json=_corps(heure_debut="13h15", heure_fin="14:00"))
    assert r.status_code == 422


# ── 2. Stockage : horaire hors pause vs dans la pause ──


def test_horaire_hors_pause_meridienne_stocke_sans_pause_midi(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="09:00", heure_fin="10:00", day=1, slot=1),
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert (corps["day"], corps["slot"]) == (1, 1)
    assert corps["hor"] == "9h–10h"
    seance = get_state().sessions_by_id[corps["session_id"]]
    assert seance.metadata.get("horaire") == {"debut": "09:00", "fin": "10:00"}
    assert not seance.metadata.get("pause_midi")


def test_horaire_dans_la_pause_meridienne_stocke_sur_le_creneau_3(monter):
    """13h15-14h : `pause_midi` se déclenche, et la position de STOCKAGE
    devient le créneau 3 QUEL QUE SOIT le créneau demandé — jamais affichée
    telle quelle (Vue Promo la rend dans la ligne "pause")."""
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=3, slot=0),
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["slot"] == 3
    assert corps["day"] == 3
    assert corps["hor"] == "13h15–14h"
    seance = get_state().sessions_by_id[corps["session_id"]]
    assert seance.metadata.get("pause_midi") is True
    assert seance.metadata.get("horaire") == {"debut": "13:15", "fin": "14:00"}


def test_borne_12h30_incluse_dans_la_pause(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="12:30", heure_fin="13:00"),
    )
    assert r.status_code == 200, r.text
    seance = get_state().sessions_by_id[r.json()["session_id"]]
    assert seance.metadata.get("pause_midi") is True


def test_borne_14h_exclue_de_la_pause(monter):
    """14h00 pile est déjà le début du créneau 3 normal — pas la pause."""
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="14:00", heure_fin="15:00", slot=3),
    )
    assert r.status_code == 200, r.text
    seance = get_state().sessions_by_id[r.json()["session_id"]]
    assert not seance.metadata.get("pause_midi")


# ── 3. Aucun conflit de ressource entre un évènement pause et une séance normale ──


def test_evenement_pause_midi_ne_bloque_pas_un_cours_a_14h_meme_salle(monter):
    from cal_iut.models.entities import Course, Teacher, TeacherBlock

    a = _seance("a")
    prof = Teacher(code="MRI", nom="Riguet", prenom="Marine")
    cours_wr101 = Course(
        code="WR101", name="Cours existant", semestre="S1", parcours="BUT1", annee="BUT1",
        lead=prof, profs=[TeacherBlock(teacher=prof, block="1", td=17, nbGpTd=1, nbGpTp=1)],
        volumes={"cm": 0, "td": 17, "tp": 0}, groupes_td=1, groupes_tp=1,
        progression_defined=False, seance_sequence=[], ordonnancement=[],
    )
    client = monter([(a, _place(a, 0, 0))], rooms=[H018], courses=[cours_wr101])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2, room_id="h018"),
    )
    assert r.status_code == 200, r.text

    # Séance NORMALE, même semaine/jour/créneau 3 (14h-15h30), MÊME salle :
    # aucun conflit ne doit être signalé avec l'évènement de la pause.
    from cal_iut.models.session import SessionToPlace as _S

    b = _S(
        id="b", course_code="WR101", course_name="Cours existant", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD, sequence_order=1,
        group_ids=["but1-promo"], teacher_codes=["MRI"], duration_slots=1,
    )
    get_state().sessions.append(b)
    get_state().sessions_by_id["b"] = b
    r2 = client.post(
        "/placements/personnalisees",
        json={
            "course_code": "WR101", "session_type": "TD", "group_ids": ["but1-promo"],
            "teacher_codes": ["MRI"], "duration_slots": 1, "week": SEMAINE, "day": 2, "slot": 3,
            "room_id": "h018", "force": False,
        },
    )
    assert r2.status_code == 200, r2.text


def test_placer_un_evenement_pause_midi_ne_signale_aucun_conflit_avec_cours_existant(monter):
    """Sens inverse du test précédent : le cours normal existe déjà au
    créneau 3, l'évènement de la pause se pose ensuite au même endroit."""
    b = SessionToPlace(
        id="b", course_code="WR101", course_name="Cours existant", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD, sequence_order=1,
        group_ids=["but1-promo"], teacher_codes=["MRI"], duration_slots=1,
    )
    client = monter([(b, _place(b, 2, 3))], rooms=[H018])
    get_state().timetable[0].room_id = "h018"

    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2, room_id="h018", teacher_codes=["MRI"]),
    )
    assert r.status_code == 200, r.text


def test_deux_evenements_pause_midi_meme_horaire_meme_salle_signale_un_conflit(monter):
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))], rooms=[H018])
    r1 = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2, room_id="h018"),
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/placements/evenements",
        json=_corps(libelle="Autre évènement", heure_debut="13:00", heure_fin="13:30", day=2, room_id="h018"),
    )
    assert r2.status_code == 409, r2.text


# ── 4. Payload export (`hor`/`midi`) ──


def test_payload_expose_hor_et_midi(monter):
    from cal_iut.export.html_view import build_payload

    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2),
    )
    assert r.status_code == 200, r.text

    state = get_state()
    payload = build_payload(
        {"placements": [
            {"session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
             "course_code": p.course_code, "group_ids": p.group_ids, "teacher_codes": p.teacher_codes,
             "room_id": getattr(p, "room_id", None)}
            for p in state.timetable
        ]},
        state.sessions,
        state.groups,
    )
    row = next(x for x in payload["rows"] if x["id"] == r.json()["session_id"])
    assert row["hor"] == "13h15–14h"
    assert row["midi"] is True

    autre = next(x for x in payload["rows"] if x["id"] == "a")
    assert "midi" not in autre or autre["midi"] is False
    assert autre.get("hor") in (None, "")


# ── 5. Celcat : jamais poussé à un mauvais horaire ──


def test_celcat_refuse_d_enfiler_un_evenement_pause_midi(monter):
    """Retour Jules 23/09/2026 : « ne JAMAIS pousser un tel évènement avec un
    mauvais horaire » — le writer Celcat ne connaît que les six créneaux
    fixes (`SLOT_TIMES`), donc un `pause_midi` (13h15-14h) ne peut être
    poussé qu'à un horaire FAUX (14h-15h30, celui de son créneau de
    stockage). Refusé avant même l'enfilage, journalisé « blocked »."""
    from celcat_sync_helpers import activer_saisie, jobs_en_attente

    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))], rooms=[H018], role="admin")
    activer_saisie(client)

    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2, room_id="h018"),
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    assert not [j for j in jobs_en_attente() if j.get("session_id") == session_id]

    logs = client.get("/celcat/logs?limit=50").json()
    items = logs["items"] if isinstance(logs, dict) else logs
    bloques = [x for x in items if isinstance(x, dict) and x.get("kind") == "blocked" and x.get("session_id") == session_id]
    assert bloques, f"aucune ligne 'blocked' journalisee pour {session_id} : {items}"
    assert "évènement hors créneau" in str(bloques[0].get("motif") or "")
    assert "13h15–14h" in str(bloques[0].get("motif") or "")


def test_plan_celcat_bulk_exclut_un_evenement_pause_midi(monter):
    """Chemin de saisie « en lot » (`GET /celcat/plan`, `celcat/sync.py`) —
    séparé du hook immédiat (`celcat/ops.py`) : un évènement pause_midi ne
    doit pas non plus apparaître dans ce qui SERAIT saisi."""
    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))], role="admin")
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2),
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    plan = client.get(f"/celcat/plan?semaines={SEMAINE}").json()
    ids_vises = {x.get("session_id") for x in plan.get("entrees", [])}
    assert session_id not in ids_vises, plan


# ── 6. Persistance (`custom_sessions.json`) ──


def test_persistance_conserve_horaire_pause_midi_et_evenement(monter):
    """`custom_sessions.py` (isolé par l'autouse `_fichiers_etat_isoles` de
    `conftest.py`) ne doit JAMAIS perdre `evenement`/`horaire`/`pause_midi`
    au rechargement — sans quoi un redémarrage de la prod (qui réingère
    toujours la maquette) remettrait l'évènement à un horaire faux."""
    from cal_iut.api import custom_sessions

    a = _seance("a")
    client = monter([(a, _place(a, 0, 0))])
    r = client.post(
        "/placements/evenements",
        json=_corps(heure_debut="13:15", heure_fin="14:00", day=2),
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    relues = custom_sessions.load_custom_sessions()
    relue = next(s for s in relues if s.id == session_id)
    assert relue.metadata.get("evenement") is True
    assert relue.metadata.get("pause_midi") is True
    assert relue.metadata.get("horaire") == {"debut": "13:15", "fin": "14:00"}
