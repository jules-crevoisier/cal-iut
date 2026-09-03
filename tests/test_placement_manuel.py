"""L'écran « À placer » : inventaire du reliquat et placement manuel.

Le solveur place ~96,5 % des séances ; le reste bute sur des combinaisons
prouvées infaisables. Jusqu'au 26/08/2026 ces séances disparaissaient sans
bruit — le planning avait l'air complet alors qu'il manquait des heures.

Deux risques dominent, et ce module ne teste qu'eux :

1. **Un inventaire faux vaut moins que pas d'inventaire.** Il doit compter
   exactement ce qui manque, quelle que soit la raison de l'absence.
2. **Un placement manuel ne doit jamais introduire ce qu'un déplacement manuel
   interdit.** `POST /placements/{id}/placer` est une porte neuve vers le
   planning : elle doit refuser tout ce que `PATCH /placements/{id}` refuse.
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


def _seance(sid: str, groupe: str = "but1-td-ab", prof: str = "MRI", duree: int = 1) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="WR101", course_name="Culture numérique", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=[groupe], teacher_codes=[prof], duration_slots=duree,
    )


def _place(session: SessionToPlace, week: int, day: int, slot: int) -> PlacedSessionWithRoom:
    return PlacedSessionWithRoom(
        session_id=session.id, week=week, day=day, slot=slot,
        course_code=session.course_code, group_ids=list(session.group_ids),
        teacher_codes=list(session.teacher_codes),
    )


@pytest.fixture
def client(monkeypatch, db_isole):
    """Un état applicatif minimal, monté à la main.

    Pas de base de données (`current_run_id=None`) : la persistance a ses
    propres tests, et la mêler ici masquerait les règles qu'on veut vérifier.
    """
    etat = get_state()
    ancien = {
        "sessions": etat.sessions, "sessions_by_id": etat.sessions_by_id,
        "timetable": etat.timetable, "groups": etat.groups, "rooms": etat.rooms,
        "calendar": etat.calendar, "current_run_id": etat.current_run_id,
        "teacher_availability": etat.teacher_availability, "teacher_duos": etat.teacher_duos,
        "corrections": etat.corrections, "courses": etat.courses,
        "config_dir": etat.config_dir,
    }

    placee = _seance("placee")
    manquante = _seance("manquante")
    etat.sessions = [placee, manquante]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [_place(placee, 10, 0, 0)]
    etat.groups = GROUPES
    etat.rooms = []
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.teacher_availability = []
    etat.teacher_duos = []
    etat.corrections = []
    etat.courses = []
    # `_hard_constraint_context` remonte de deux crans depuis ce dossier pour
    # retrouver le planning officiel : sans un vrai chemin, la route casse.
    etat.config_dir = ROOT / "data" / "config"

    client = TestClient(app)
    # Compte de test (comptes utilisateurs, cutover 31/08/2026, remplace
    # l'ancien mot de passe partagé) — sans ce login, chaque appel de ce
    # client tomberait en 401.
    creer_compte_actif_et_connecter(client)
    yield client

    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


# --------------------------------------------------------------------------
# L'inventaire
# --------------------------------------------------------------------------


def test_l_inventaire_liste_exactement_les_seances_absentes_du_planning(client):
    corps = client.get("/placements/manquantes").json()
    assert [m["session_id"] for m in corps["manquantes"]] == ["manquante"]
    assert corps["total_a_placer"] == 2
    assert corps["total_placees"] == 1


def test_l_inventaire_inclut_les_sae_pour_placement_manuel(client):
    """Retour 03/09/2026 : les enseignant·es planifient les SAE (WS*) dans
    leurs fenêtres — elles doivent figurer dans « À placer ». L'exclusion
    d'août 2026 (éviter 1121 fantômes) est remplacée par l'exemption de
    sanctuarisation côté placement (`is_unplaced_sae`)."""
    etat = get_state()
    sae_calendaire = SessionToPlace(
        id="sae-calendaire", course_code="WSA310M", course_name="SAE", semestre="S3",
        parcours="BUT2-DEV-FI", annee="BUT2", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["MRI"],
    )
    sae_planifiee = SessionToPlace(
        id="sae-planifiee", course_code="WSA501D", course_name="SAE", semestre="S5",
        parcours="BUT3-DEV-FC", annee="BUT3", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["MRI"],
    )
    etat.sessions = etat.sessions + [sae_calendaire, sae_planifiee]
    etat.sessions_by_id[sae_calendaire.id] = sae_calendaire
    etat.sessions_by_id[sae_planifiee.id] = sae_planifiee

    reponse = client.get("/placements/manquantes").json()
    ids = {m["session_id"] for m in reponse["manquantes"]}
    assert "sae-calendaire" in ids
    assert "sae-planifiee" in ids


def test_l_inventaire_se_calcule_par_difference_pas_depuis_le_solveur(client):
    """Une séance retirée du planning par n'importe quel chemin doit réapparaître.

    C'est la raison du calcul par différence plutôt que par lecture d'un champ
    du solveur : reprise de run partiel, régénération interrompue, correction
    manuelle — l'inventaire doit rester juste dans tous ces cas.
    """
    etat = get_state()
    etat.timetable.clear()
    corps = client.get("/placements/manquantes").json()
    assert {m["session_id"] for m in corps["manquantes"]} == {"placee", "manquante"}


def test_l_inventaire_parle_francais_pas_en_codes(client):
    """Les trigrammes et les identifiants techniques ne parlent qu'aux initiés."""
    manquante = client.get("/placements/manquantes").json()["manquantes"][0]
    assert manquante["duree_libelle"] == "1h30"
    assert manquante["groupes_libelles"] and manquante["groupes_libelles"][0] != ""
    assert manquante["raison"].startswith("Probablement")
    assert manquante["course_name"] == "Culture numérique"


def test_un_planning_complet_le_dit_explicitement(client):
    etat = get_state()
    etat.timetable.append(_place(etat.sessions_by_id["manquante"], 11, 1, 0))
    corps = client.get("/placements/manquantes").json()
    assert corps["manquantes"] == []
    assert "Toutes les séances sont placées" in corps["resume"]


def test_une_semaine_avec_une_seance_encore_manquante_n_est_pas_semaines_completes(client) -> None:
    """Retour utilisateur (03/09/2026) : « si la semaine 1 est entièrement
    placée on la met comme placée ». Tant que « manquante » pourrait encore
    atterrir semaine 10 (0-indexée, chip 11), cette semaine n'est pas
    complète — même si `placee` y est déjà."""
    from cal_iut.api.main import _semaines_celcat_completes

    assert 11 not in _semaines_celcat_completes()


def test_une_semaine_ou_tout_est_place_devient_semaines_completes(client) -> None:
    from cal_iut.api.main import _semaines_celcat_completes

    etat = get_state()
    etat.timetable.append(_place(etat.sessions_by_id["manquante"], 10, 2, 0))
    assert 11 in _semaines_celcat_completes()


# --------------------------------------------------------------------------
# Les créneaux proposés
# --------------------------------------------------------------------------


def test_les_creneaux_proposes_portent_une_date_lisible(client):
    """Un créneau annoncé « semaine 12, jour 2 » oblige à ressortir le calendrier."""
    corps = client.get("/placements/manquante/creneaux-libres").json()
    assert corps["creneaux"], "aucun créneau proposé pour une séance simple"
    for c in corps["creneaux"]:
        assert c["date"], f"créneau sans date : {c}"
        assert len(c["date"]) == 10  # ISO


def test_aucun_creneau_propose_ne_recouvre_une_seance_existante(client):
    """La proposition doit être sûre : c'est tout l'intérêt du bouton « Placer ici »."""
    occupe = {(p.week, p.day, p.slot) for p in get_state().timetable}
    for c in client.get("/placements/manquante/creneaux-libres").json()["creneaux"]:
        assert (c["week"], c["day"], c["slot"]) not in occupe


def test_une_seance_inconnue_donne_un_404_pas_une_liste_vide(client):
    assert client.get("/placements/fantome/creneaux-libres").status_code == 404


# --------------------------------------------------------------------------
# Le placement
# --------------------------------------------------------------------------


def test_placer_une_seance_l_ajoute_au_planning(client):
    creneau = client.get("/placements/manquante/creneaux-libres").json()["creneaux"][0]
    reponse = client.post("/placements/manquante/placer", json={
        "week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"],
    })
    assert reponse.status_code == 200, reponse.text
    assert any(p.session_id == "manquante" for p in get_state().timetable)
    assert client.get("/placements/manquantes").json()["manquantes"] == []


def test_placer_deux_fois_la_meme_seance_est_refuse(client):
    creneau = client.get("/placements/manquante/creneaux-libres").json()["creneaux"][0]
    body = {"week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"]}
    assert client.post("/placements/manquante/placer", json=body).status_code == 200
    seconde = client.post("/placements/manquante/placer", json=body)
    assert seconde.status_code == 409
    assert "déjà au planning" in seconde.text


def test_placer_sur_une_seance_du_meme_groupe_est_refuse(client):
    """Le même groupe dans deux salles au même moment : le conflit le plus
    élémentaire, et celui qu'une porte neuve vers le planning risque d'oublier."""
    reponse = client.post("/placements/manquante/placer", json={"week": 10, "day": 0, "slot": 0})
    assert reponse.status_code == 409
    assert reponse.json()["detail"]["hard_conflicts"]


def test_le_conflit_de_ressource_reste_forcable_par_un_humain(client):
    """Distinction volontaire : un conflit de ressources peut avoir une bonne
    raison ponctuelle, une règle institutionnelle n'en a jamais."""
    reponse = client.post(
        "/placements/manquante/placer",
        json={"week": 10, "day": 0, "slot": 0, "force": True},
    )
    assert reponse.status_code == 200, reponse.text


def test_placer_dans_une_semaine_passee_est_refuse(client):
    """Même garde-fou que le glisser-déposer : on ne réécrit pas le passé."""
    reponse = client.post("/placements/manquante/placer", json={"week": 0, "day": 0, "slot": 0})
    assert reponse.status_code == 409
    assert "non modifiable" in reponse.text


def test_placer_une_seance_inconnue_donne_un_404(client):
    reponse = client.post("/placements/fantome/placer", json={"week": 10, "day": 1, "slot": 0})
    assert reponse.status_code == 404


def test_un_placement_manuel_est_journalise_comme_correction(client):
    """La boucle de réapprentissage des poids lit ces corrections ; un placement
    manuel non journalisé serait une décision humaine perdue."""
    creneau = client.get("/placements/manquante/creneaux-libres").json()["creneaux"][0]
    client.post("/placements/manquante/placer", json={
        "week": creneau["week"], "day": creneau["day"], "slot": creneau["slot"],
    })
    corrections = get_state().corrections
    assert corrections and corrections[-1]["session_id"] == "manquante"
    # Aucune position proposée : le solveur ne l'avait pas placée du tout.
    assert corrections[-1]["proposed"] is None


def test_l_inventaire_reste_rapide_meme_avec_beaucoup_de_manquantes(client):
    """L'inventaire ne doit pas recharger le planning officiel séance par séance.

    Première version : `_hard_constraint_context` appelé pour chacune, donc
    relecture du planning sur disque et parcours des 3101 séances à chaque
    tour — 13,6 s mesurées sur un run très incomplet (795 manquantes). Les
    bornes d'ordre pédagogique se calculent une fois pour toutes, pour un
    résultat identique.
    """
    import time

    etat = get_state()
    # 300 séances non placées : le cas d'un run qui s'est mal passé, celui-là
    # même où l'inventaire est le plus utile.
    etat.sessions = etat.sessions + [_seance(f"m{i}") for i in range(300)]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}

    debut = time.perf_counter()
    corps = client.get("/placements/manquantes").json()
    duree = time.perf_counter() - debut

    assert len(corps["manquantes"]) == 301
    assert duree < 2.0, f"inventaire trop lent : {duree:.1f} s"


# --------------------------------------------------------------------------
# L'invariant qui manquait : proposer, c'est s'engager
# --------------------------------------------------------------------------


def test_tout_creneau_propose_est_accepte_au_placement(client):
    """Un outil qui propose ce qu'il refuse ensuite est pire qu'inutile.

    Défaut trouvé le 26/08/2026 en lançant le remplissage automatique sur le
    run réel : **649 créneaux proposés sur 918** étaient refusés au moment de
    poser la séance. `suggest_alternative_slots` appelait `validate_move` sans
    `sessions_by_id` ni `groups` — la validation ignorait alors la DURÉE des
    séances et la COHORTE étudiante, les deux défauts pourtant corrigés côté
    glisser-déposer (cf. docs/DATA.md §65.2). La suggestion était donc
    structurellement plus permissive que le placement.

    Cette propriété interdit à l'écart de revenir : ce qui est proposé doit
    être posable.
    """
    etat = get_state()
    # Un bloc de 3h et un CM de promo : les deux formes précisément ignorées
    # par la validation incomplète.
    bloc = _seance("bloc", duree=2)
    etat.sessions.append(bloc)
    etat.sessions_by_id[bloc.id] = bloc

    for sid in ("manquante", "bloc"):
        creneaux = client.get(f"/placements/{sid}/creneaux-libres?maximum=4").json()["creneaux"]
        assert creneaux, f"aucun créneau proposé pour {sid}"
        for c in creneaux:
            reponse = client.post(f"/placements/{sid}/placer", json={
                "week": c["week"], "day": c["day"], "slot": c["slot"],
            })
            assert reponse.status_code == 200, (
                f"créneau proposé pour {sid} puis refusé : {c} — {reponse.text}"
            )
            # Retiré pour tester le suivant : on vérifie chaque proposition,
            # pas seulement la première.
            etat.timetable[:] = [p for p in etat.timetable if p.session_id != sid]
