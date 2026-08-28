"""L'ordre pédagogique au grain du CRÉNEAU, pas seulement de la semaine.

`_movable_bounds` ne borne qu'à la SEMAINE (résolution utilisée pour le
rééquilibrage, moins coûteuse). L'ordre pédagogique réel se vérifie au créneau
précis (`export/html_view.py::_rule_checks`, comparaison stricte `<` sur le
temps absolu) : deux séances liées peuvent légitimement PARTAGER une semaine,
mais leur jour/créneau doit encore respecter le sens de la relation.

Trouvé le 27/08/2026 en auditant un run complété : 102 séances (« ordre
pédagogique CM→TD→TP ») et 111 paires (« vu par l'étudiant ») étaient dans la
BONNE semaine mais au MAUVAIS créneau — le placement manuel et la complétion
automatique acceptaient sans le savoir des créneaux chronologiquement à
l'envers, simplement parce que la semaine, elle, était correcte.
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

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
GROUPE = "but1-td-ab"


def _seance(sid: str, ordre: int) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=ordre, group_ids=[GROUPE], teacher_codes=["MRI"],
    )


@pytest.fixture
def client():
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "groups": etat.groups, "rooms": etat.rooms,
        "calendar": etat.calendar, "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability, "teacher_duos": etat.teacher_duos,
        "corrections": etat.corrections, "courses": etat.courses,
        "config_dir": etat.config_dir, "student_presences": etat.student_presences,
    }

    precedente = _seance("precedente", ordre=1)
    manquante = _seance("manquante", ordre=2)
    suivante = _seance("suivante", ordre=3)
    # Séance SANS lien avec les trois autres (cours différent) — sert
    # uniquement à établir un horizon réaliste. `_hard_constraint_context`
    # déduit `n_weeks` du planning DÉJÀ posé (`max(week) + 1`) : sans elle,
    # l'horizon resterait celui, artificiellement court, des trois séances du
    # test (en production, des centaines de séances couvrent déjà tout le
    # semestre avant qu'un placement manuel n'intervienne).
    ancre = SessionToPlace(
        id="ancre", course_code="WR999", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=[GROUPE], teacher_codes=["MRI"],
    )
    etat.sessions = [precedente, manquante, suivante, ancre]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    # `précédente` et `suivante` sont dans la MÊME semaine (10), à des
    # créneaux qui laissent une fenêtre étroite mais réelle entre les deux —
    # exactement le cas qui échappait à `_movable_bounds`.
    etat.timetable = [
        PlacedSessionWithRoom(session_id="precedente", week=10, day=1, slot=1,
                               course_code="WR101", group_ids=[GROUPE], teacher_codes=["MRI"]),
        PlacedSessionWithRoom(session_id="suivante", week=10, day=1, slot=4,
                               course_code="WR101", group_ids=[GROUPE], teacher_codes=["MRI"]),
        PlacedSessionWithRoom(session_id="ancre", week=22, day=0, slot=0,
                               course_code="WR999", group_ids=[GROUPE], teacher_codes=["MRI"]),
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
    etat.student_presences = []

    yield TestClient(app)

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def test_aucun_creneau_propose_ne_precede_la_seance_precedente(client):
    corps = client.get("/placements/manquante/creneaux-libres?maximum=10").json()
    assert corps["creneaux"], "aucun créneau proposé — la fenêtre est-elle trop étroite ?"
    for c in corps["creneaux"]:
        if c["week"] != 10:
            continue
        assert (c["day"], c["slot"]) > (1, 1), f"{c} précède ou égale « précédente » (jour 1, créneau 1)"


def test_aucun_creneau_propose_ne_suit_la_seance_suivante(client):
    corps = client.get("/placements/manquante/creneaux-libres?maximum=10").json()
    for c in corps["creneaux"]:
        if c["week"] != 10:
            continue
        assert (c["day"], c["slot"]) < (1, 4), f"{c} suit ou égale « suivante » (jour 1, créneau 4)"


def test_le_creneau_juste_entre_les_deux_est_accepte(client):
    """La fenêtre existe réellement (jour 1, créneaux 2 et 3) : le correctif
    ne doit pas la fermer par excès de prudence."""
    reponse = client.post("/placements/manquante/placer", json={"week": 10, "day": 1, "slot": 2})
    assert reponse.status_code == 200, reponse.text


def test_placer_avant_la_precedente_est_refuse_meme_en_forcant(client):
    """Jamais contournable, comme le reste de l'ordre pédagogique."""
    reponse = client.post("/placements/manquante/placer", json={
        "week": 10, "day": 1, "slot": 0, "force": True,
    })
    assert reponse.status_code == 409
    assert any("institutionnellement" in m.lower() for m in reponse.json()["detail"]["hard_conflicts"])


def test_une_semaine_hors_bornes_reste_ouverte_par_ailleurs(client):
    """La restriction fine (au créneau) ne doit s'ajouter qu'aux semaines-
    limites — elle ne doit pas, par erreur, se répandre sur tout l'horizon.

    Ici les deux voisins sont dans la MÊME semaine (10) : c'est donc la seule
    semaine autorisée, et une autre semaine est refusée par la borne de
    semaine normale (`allowed_weeks`), PAS par le raffinement au créneau —
    la distinction se vérifie sur le MESSAGE renvoyé.
    """
    reponse = client.post("/placements/manquante/placer", json={"week": 15, "day": 0, "slot": 0})
    assert reponse.status_code == 409
    assert any(
        "cette semaine violerait" in m.lower() for m in reponse.json()["detail"]["hard_conflicts"]
    ), "refusé pour la mauvaise raison : le raffinement au créneau ne doit pas déborder sur d'autres semaines"


def test_une_semaine_sans_aucun_voisin_a_ce_grain_reste_entierement_ouverte(client):
    """Avec un seul voisin (prédécesseur seul, en semaine 10), `hi` reste la
    fin de l'horizon : une semaine bien après ne doit être bridée ni par la
    semaine ni par le créneau.

    Semaine 15 (pas 20) : `fi_max_week` (borne DISTINCTE, ajoutée le
    27/08/2026 — « les FI doivent finir leur semestre le 1er février »,
    semaine-index 18) s'applique à toute séance FI quel que soit son ordre
    pédagogique. La semaine choisie ici doit rester dans les deux bornes à
    la fois pour isoler ce que ce test vérifie réellement : l'absence de
    voisin ne doit pas, PAR AILLEURS, réintroduire une restriction de
    semaine ou de créneau au titre de l'ordre pédagogique."""
    etat = get_state()
    etat.timetable[:] = [p for p in etat.timetable if p.session_id != "suivante"]
    etat.sessions_by_id.pop("suivante", None)

    reponse = client.post("/placements/manquante/placer", json={"week": 15, "day": 2, "slot": 0})
    assert reponse.status_code == 200, reponse.text
