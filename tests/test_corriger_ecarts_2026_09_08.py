"""« Tout corriger » : pousser les écarts de la comparaison vers Celcat.

Demande utilisateur 08/09/2026, après la mise en service de la comparaison :
« maintenant que l'on a cette comparaison, est-ce que l'on ne peut pas faire
un bouton qui règle cela ? » — portée « tout d'un coup », suppressions
incluses, choix explicite.

CE QUI REND LA CHOSE ACCEPTABLE. Le bouton n'écrit PAS dans Celcat : il
ENFILE des jobs dans la file d'attente existante, que le worker consomme
avec ses garde-fous — catégorie d'évènement, masque d'une seule semaine,
refus d'écrire sur URCA_2026 sans `--production`. Un bouton qui écrirait
directement contournerait tout ce qui a été construit cette semaine pour
empêcher une mauvaise écriture.

Chaque verdict a son geste :

    ecart            -> update, avec l'event_id existant (jamais un create,
                        qui poserait un DOUBLON à côté)
    absente_celcat   -> create
    en_trop_celcat   -> delete, avec event_id ET group_id

REFUSER QUAND LA SAISIE EST DÉSARMÉE. Sans `saisie_active`, `ops._executer`
ne fait rien : les jobs partiraient dans le vide et l'écran annoncerait
« 38 corrections envoyées » alors que rien n'attend. C'est exactement le
genre de succès de façade que cette semaine a servi à éliminer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import instantane
from cal_iut.celcat.etat import charger, sauver
from cal_iut.celcat.file_attente import lister, vider
from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

from conftest import creer_compte_actif_et_connecter

client = TestClient(app)
SEMAINE = 1


def _ev(**kw):
    base = {
        "event_id": 1931709,
        "groupe": "BUT MMI S1 CM",
        "jour": 1,
        "heure_debut": "15:30",
        "heure_fin": "17:00",
        "salle": "Amphi 3 MMI",
        "categorie": "[CM]",
        "enseignant": "HUEZ Regis",
        "module": "WR116 Traitement Info",
        "semaine": 3,
        "protected": "N",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _etat(db_isole):
    creer_compte_actif_et_connecter(client, role="admin")
    etat = get_state()
    ancien = {
        k: getattr(etat, k)
        for k in (
            "sessions", "sessions_by_id", "timetable", "groups", "calendar",
            "current_run_id", "config_dir",
        )
    }
    s = SessionToPlace(
        id="WR116-S1-CM-1", course_code="WR116", course_name="Traitement Info",
        semestre="S1", parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
        sequence_order=1, group_ids=["but1-promo"], teacher_codes=["RHU"],
    )
    etat.sessions = [s]
    etat.sessions_by_id = {s.id: s}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id="WR116-S1-CM-1", week=SEMAINE, day=1, slot=4,
            course_code="WR116", group_ids=["but1-promo"], teacher_codes=["RHU"],
            room_id="h018", room_label="H.018 (Amphi MMI)",
        )
    ]
    etat.groups = [
        Group(id="but1-promo", label="Promo BUT1", parcours="BUT1", annee="BUT1", kind="promo")
    ]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    # Sans `config_dir`, `load_celcat_config` ne trouve ni la table des
    # salles ni celle des modules : la comparaison signalerait alors un écart
    # de salle sur chaque amphi (« H.018 » vs « Amphi 3 MMI »).
    etat.config_dir = Path(__file__).resolve().parents[1] / "data" / "config"
    doc = charger()
    doc["saisie_active"] = True
    doc["journal"] = {"WR116-S1-CM-1": {"event_id": "1931709", "semaine": SEMAINE}}
    sauver(doc)
    vider()
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _corriger():
    return client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}")


def test_refuse_un_anonyme() -> None:
    client.cookies.clear()
    assert _corriger().status_code in (401, 403)


def test_un_ecart_enfile_une_MODIFICATION_avec_son_event_id() -> None:
    """Jamais une création : elle poserait un DOUBLON à côté de l'évènement
    existant, sur un outil qui sert aussi à payer les enseignants."""
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])

    reponse = _corriger()
    assert reponse.status_code == 200, reponse.text

    jobs = lister()
    assert [j["action"] for j in jobs] == ["update"]
    assert jobs[0]["session_id"] == "WR116-S1-CM-1"
    assert int(jobs[0]["event_id"]) == 1931709


def test_une_seance_absente_enfile_une_CREATION() -> None:
    instantane.enregistrer([], groupes=["BUT MMI S1 CM"])

    _corriger()

    jobs = lister()
    assert [j["action"] for j in jobs] == ["create"]
    assert jobs[0]["session_id"] == "WR116-S1-CM-1"


def test_un_evenement_en_trop_enfile_une_SUPPRESSION_avec_son_groupe() -> None:
    """`group_id` est indispensable : `supprimer_evenement` localise
    l'évènement par son groupe, et un job sans lui reste en file sans
    jamais pouvoir être traité."""
    get_state().timetable = []
    instantane.enregistrer([_ev(event_id=1933245)], groupes=["BUT MMI S1 CM"])

    _corriger()

    jobs = [j for j in lister() if j["action"] == "delete"]
    assert len(jobs) == 1
    assert int(jobs[0]["event_id"]) == 1933245
    assert jobs[0].get("group_id"), "sans group_id, la suppression ne partira jamais"


def test_une_seance_identique_n_enfile_rien() -> None:
    """Réécrire ce qui est déjà juste ferait passer le worker sur des
    centaines de séances pour rien, VPN pris à chaque fois."""
    instantane.enregistrer([_ev()], groupes=["BUT MMI S1 CM"])

    _corriger()

    assert lister() == []


def test_le_compte_rendu_dit_ce_qui_a_ete_enfile() -> None:
    """Un bouton qui ne rend rien laisse croire au succès sans preuve."""
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])

    corps = _corriger().json()
    assert corps["modifications"] == 1
    assert corps["creations"] == 0
    assert corps["suppressions"] == 0
    assert corps["total"] == 1


def test_refuse_quand_la_saisie_est_desarmee() -> None:
    """Sans `saisie_active`, les jobs partiraient dans le vide : l'écran
    annoncerait « corrections envoyées » alors que rien n'attend. C'est le
    succès de façade que cette semaine a servi à éliminer."""
    doc = charger()
    doc["saisie_active"] = False
    sauver(doc)
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])

    reponse = _corriger()

    assert reponse.status_code == 409, reponse.text
    assert "saisie" in reponse.text.lower()
    assert lister() == [], "rien ne doit être enfilé"


def test_refuse_sans_releve_plutot_que_de_tout_creer() -> None:
    """Sans instantané, TOUTES les séances paraissent absentes de Celcat :
    un « tout corriger » créerait alors des doublons de tout le planning."""
    reponse = _corriger()

    assert reponse.status_code == 409, reponse.text
    assert lister() == []
