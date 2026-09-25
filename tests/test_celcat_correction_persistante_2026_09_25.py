"""`/celcat/comparaison/corriger` doit enregistrer un suivi SERVEUR de la
correction — pour que revenir sur l'onglet Celcat plus tard le retrouve, au
lieu de reproposer « Corriger » comme si rien n'était parti.

Signalement de Jules Crevoisier, 25/09/2026 : « quand par exemple on corrige
un écart, ça envoie, ça met qu'on l'a envoyé à corriger, donc ça fait une
attente du passage du worker. Si on quitte et qu'on revient sur l'onglet
Celcat, ça le remet en mode qu'on peut le recorriger. »

Le calcul (worker repassé ? relevé frais ? périmé ?) vit dans
`cal_iut.celcat.correction_en_cours`, déjà couvert unitairement par
`tests/test_celcat_correction_en_cours_2026_09_25.py`. Ces tests-ci vérifient
seulement le CÂBLAGE : `POST .../corriger` enregistre, `GET .../en-cours` lit,
`DELETE .../en-cours` efface, et les trois exigent le rôle admin comme le
reste de `/celcat`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.celcat import correction_en_cours as cec
from cal_iut.celcat import instantane
from cal_iut.celcat.etat import charger, sauver
from cal_iut.celcat.file_attente import vider
from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

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
def _fichiers_isoles(tmp_path, monkeypatch):
    # Seul le suivi (`correction_en_cours`) est un fichier NOUVEAU introduit
    # par ce correctif : on l'isole pour ne rien laisser trainer dans le
    # dépôt. `instantane`/`etat`/`file_attente` suivent la convention déjà en
    # place dans `test_corriger_ecarts_2026_09_08.py`.
    monkeypatch.setattr(cec, "_path", lambda: tmp_path / "celcat_correction_en_cours.json")
    yield


@pytest.fixture
def client(db_isole):
    c = TestClient(app)
    creer_compte_actif_et_connecter(c, role="admin")
    etat = get_state()
    ancien = {
        k: getattr(etat, k)
        for k in ("sessions", "sessions_by_id", "timetable", "groups", "calendar", "current_run_id", "config_dir")
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
    etat.groups = [Group(id="but1-promo", label="Promo BUT1", parcours="BUT1", annee="BUT1", kind="promo")]
    etat.calendar = build_default_calendar_2026_2027()
    etat.current_run_id = None
    etat.config_dir = Path(__file__).resolve().parents[1] / "data" / "config"
    doc = charger()
    doc["saisie_active"] = True
    doc["journal"] = {}
    sauver(doc)
    vider()
    yield c
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _corriger(client: TestClient):
    return client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}")


def _en_cours(client: TestClient):
    return client.get(f"/celcat/comparaison/en-cours?semaine={SEMAINE}")


def test_should_show_absente_before_any_correction_was_ever_sent(client: TestClient) -> None:
    reponse = _en_cours(client)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["etat"] == "absente"
    assert corps["semaine"] == SEMAINE


def test_corriger_records_a_correction_en_cours_readable_right_after(client: TestClient) -> None:
    # Un écart réel : sans ça, rien n'est enfilé et il n'y a rien à suivre.
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])

    reponse = _corriger(client)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["total"] >= 1

    suivi = _en_cours(client).json()
    assert suivi["etat"] == "en_cours"
    assert suivi["total"] >= 1
    assert suivi["mise_en_file_le"] is not None


def test_corriger_with_nothing_to_enqueue_records_nothing(client: TestClient) -> None:
    # Un relevé identique : rien à corriger, rien à suivre.
    instantane.enregistrer([_ev()], groupes=["BUT MMI S1 CM"])

    reponse = _corriger(client)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["total"] == 0

    assert _en_cours(client).json()["etat"] == "absente"


def test_delete_en_cours_clears_the_tracking_without_touching_the_queue(client: TestClient) -> None:
    from cal_iut.celcat.file_attente import lister

    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])
    _corriger(client)
    assert _en_cours(client).json()["etat"] == "en_cours"
    jobs_avant = lister()
    assert jobs_avant, "le test suppose qu'il y a bien un job en file"

    reponse = client.delete(f"/celcat/comparaison/en-cours?semaine={SEMAINE}")
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["etat"] == "absente"

    assert _en_cours(client).json()["etat"] == "absente"
    # La file, elle, n'a pas bougé : ce n'est qu'un suivi, pas la file.
    assert lister() == jobs_avant


def test_refuse_anonyme_et_edit_sur_les_deux_nouvelles_routes(client: TestClient) -> None:
    anonyme = TestClient(app)
    assert _en_cours(anonyme).status_code in (401, 403)
    assert anonyme.delete(f"/celcat/comparaison/en-cours?semaine={SEMAINE}").status_code in (401, 403)

    editeur = TestClient(app)
    creer_compte_actif_et_connecter(editeur, role="edit")
    assert _en_cours(editeur).status_code in (401, 403)
    assert editeur.delete(f"/celcat/comparaison/en-cours?semaine={SEMAINE}").status_code in (401, 403)
