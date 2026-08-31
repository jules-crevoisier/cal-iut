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

from conftest import creer_compte_actif_et_connecter

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
def client(db_isole):
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

    client = TestClient(app)
    # Compte de test (comptes utilisateurs, cutover 31/08/2026, remplace
    # l'ancien mot de passe partagé) — sans ce login, chaque appel de ce
    # client tomberait en 401.
    creer_compte_actif_et_connecter(client)
    yield client

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


def test_placer_avant_la_precedente_est_refuse_sans_forcer(client):
    """Refusé par défaut : l'ordre pédagogique reste une vraie règle, pas une
    simple suggestion — mais contournable via `force` (cf. test suivant),
    depuis le 28/08/2026 (retour utilisateur : « on veut que si on appuie
    sur forcer cela soit bon et que le placement se fasse »)."""
    reponse = client.post("/placements/manquante/placer", json={
        "week": 10, "day": 1, "slot": 0, "force": False,
    })
    assert reponse.status_code == 409
    assert any("ordre pédagogique" in m.lower() for m in reponse.json()["detail"]["hard_conflicts"])


def test_placer_avant_la_precedente_reussit_en_forcant(client):
    """Contournable via `force`, à la différence des verrous institutionnels
    (PAC/SAE/etc, cf. `test_ordonnancement_2026_08_25.py` ou équivalent) —
    un humain qui force ici sait qu'il place sciemment cette séance hors de
    l'ordre de contenu attendu."""
    reponse = client.post("/placements/manquante/placer", json={
        "week": 10, "day": 1, "slot": 0, "force": True,
    })
    assert reponse.status_code == 200, reponse.text


# --------------------------------------------------------------------------
# Un placement forcé reste suivi (`api/forced_pending.py`) — retour
# utilisateur 28/08/2026 : « une fois le cm placé il faut le laisser dans
# la liste pour peut-être revenir en arrière, et il faut peut-être un
# bouton valider ».
# --------------------------------------------------------------------------


def test_un_placement_force_reste_visible_dans_a_placer(client):
    reponse = client.post("/placements/manquante/placer", json={
        "week": 10, "day": 1, "slot": 0, "force": True,
    })
    assert reponse.status_code == 200, reponse.text

    corps = client.get("/placements/manquantes").json()
    ligne = next(m for m in corps["manquantes"] if m["session_id"] == "manquante")
    assert ligne["placee_provisoirement"] is True
    assert (ligne["semaine_actuelle"], ligne["jour_actuel"], ligne["slot_actuel"]) == (10, 1, 0)


def test_valider_retire_du_suivi_et_de_la_liste(client):
    client.post("/placements/manquante/placer", json={"week": 10, "day": 1, "slot": 0, "force": True})

    reponse = client.post("/placements/manquante/valider")
    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"session_id": "manquante", "etait_en_attente": True}

    corps = client.get("/placements/manquantes").json()
    assert all(m["session_id"] != "manquante" for m in corps["manquantes"])


def test_valider_deux_fois_est_un_no_op_sans_erreur(client):
    client.post("/placements/manquante/placer", json={"week": 10, "day": 1, "slot": 0, "force": True})
    client.post("/placements/manquante/valider")
    reponse = client.post("/placements/manquante/valider")
    assert reponse.status_code == 200
    assert reponse.json() == {"session_id": "manquante", "etait_en_attente": False}


def test_retirer_repose_la_seance_en_a_placer_normale(client):
    client.post("/placements/manquante/placer", json={"week": 10, "day": 1, "slot": 0, "force": True})

    reponse = client.delete("/placements/manquante")
    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"session_id": "manquante", "etait_en_attente": True}

    corps = client.get("/placements/manquantes").json()
    ligne = next(m for m in corps["manquantes"] if m["session_id"] == "manquante")
    assert ligne["placee_provisoirement"] is False
    assert ligne["semaine_actuelle"] is None

    # Vraiment retirée du planning, pas seulement démasquée dans la liste.
    assert not any(p.session_id == "manquante" for p in get_state().timetable)


def test_retirer_un_placement_non_en_attente_est_refuse(client):
    """Garde-fou : cet endpoint n'est PAS un « supprimer n'importe quel
    placement » générique — seulement le rattrapage d'un forçage d'ordre
    pédagogique en attente. `precedente` est un placement normal, jamais
    forcé."""
    reponse = client.delete("/placements/precedente")
    assert reponse.status_code == 400
    assert any(p.session_id == "precedente" for p in get_state().timetable)


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
        "cette semaine contredit" in m.lower() for m in reponse.json()["detail"]["hard_conflicts"]
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
