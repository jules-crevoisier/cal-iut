"""« Corriger » doit dire ce qui s'est réellement passé, pas ce qu'il voulait faire.

Retour utilisateur du 16/09/2026 :

    « j'ai l'impression de devoir cliquer plusieurs fois à des heures
    différentes sur "Corriger les écarts de cette semaine" pour que ça les
    corrige vraiment. »

Trois affirmations fausses le poussaient à recliquer, et toutes au moment
précis où il cherchait à vérifier :

1. « 12 corrections mises en file » alors que `enfiler` avait tout
   dédoublonné en silence et n'avait rien ajouté ;
2. « le worker les pousse à son prochain passage » alors que le worker était
   en pause et que rien ne partirait jamais ;
3. neuf écarts au tableau, cinq corrections au message, et rien pour
   expliquer les quatre autres — tombés dans un `continue` muet.

Ces tests tiennent les trois.
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
    etat.config_dir = Path(__file__).resolve().parents[1] / "data" / "config"
    doc = charger()
    doc["saisie_active"] = True
    doc["worker_actif"] = True
    doc["journal"] = {"WR116-S1-CM-1": {"event_id": "1931709", "semaine": SEMAINE}}
    sauver(doc)
    vider()
    yield etat
    for cle, valeur in ancien.items():
        setattr(etat, cle, valeur)


def _corriger(**params):
    suffixe = "".join(f"&{k}={v}" for k, v in params.items())
    return client.post(f"/celcat/comparaison/corriger?semaine={SEMAINE}{suffixe}")


def test_recliquer_ne_pretend_plus_avoir_enfile_a_nouveau() -> None:
    """LE TEST DE CE RETOUR UTILISATEUR. Le second clic annonçait le même
    compte que le premier alors que `enfiler` n'avait rien ajouté."""
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])

    premier = _corriger().json()
    assert premier["total"] == 1
    assert premier["deja_en_file"] == 0

    second = _corriger().json()

    assert second["total"] == 0, "rien de neuf n'a été mis en file"
    assert second["deja_en_file"] == 1
    assert len(lister()) == 1, "et la file n'a pas doublé"
    assert "attendai" in second["message"], (
        f"le message doit dire que la correction attend déjà : {second['message']}"
    )


def test_le_message_ne_promet_plus_rien_quand_le_worker_est_en_pause() -> None:
    """Worker en pause, rien ne part — jamais. Le message promettait quand
    même « moins d'une minute » : seul `saisie_active` était vérifié."""
    doc = charger()
    doc["worker_actif"] = False
    sauver(doc)
    instantane.enregistrer([_ev(heure_debut="13:50")], groupes=["BUT MMI S1 CM"])

    reponse = _corriger()

    assert reponse.status_code == 409, reponse.text
    assert "pause" in reponse.text.lower()
    assert lister() == [], "et rien ne s'empile en attendant"


def test_un_ecart_sans_event_id_est_nomme_au_lieu_d_etre_tu() -> None:
    """Le tableau disait neuf écarts, le message cinq corrections, et rien
    n'expliquait les quatre autres."""
    # Même cours, heure différente : c'est un écart. Mais sans `event_id`, on
    # ne peut ni le modifier ni le créer sans risquer un doublon.
    instantane.enregistrer(
        [_ev(event_id=None, heure_debut="13:50")], groupes=["BUT MMI S1 CM"]
    )

    corps = _corriger().json()

    assert corps["total"] == 0
    assert len(corps["abandonnes"]) == 1, corps["abandonnes"]
    abandonne = corps["abandonnes"][0]
    assert abandonne["raison"] == "event_id_absent"
    assert abandonne["session_id"] == "WR116-S1-CM-1"
    assert "doublon" in abandonne["explication"]
    assert "n'ont pas pu être traduits" in corps["message"], corps["message"]


def test_une_suppression_epargnee_est_nommee_avec_son_evenement() -> None:
    """« Corriger sans supprimer » comptait les épargnées sans dire
    lesquelles : impossible d'aller vérifier dans Celcat."""
    get_state().timetable = []
    instantane.enregistrer([_ev(event_id=1933245)], groupes=["BUT MMI S1 CM"])

    corps = _corriger(supprimer="false").json()

    assert corps["suppressions_ignorees"] == 1
    epargnees = [a for a in corps["abandonnes"] if a["raison"] == "suppression_epargnee"]
    assert len(epargnees) == 1
    assert epargnees[0]["event_id"] == 1933245, (
        "sans l'identifiant, impossible d'aller voir de quel cours il s'agit"
    )


def test_la_pastille_worker_ne_ment_plus() -> None:
    """`worker_ok` valait `True` EN DUR : la pastille restait verte worker
    mort, c'est-à-dire précisément quand elle devait alerter."""
    from cal_iut.celcat import drainage

    doc = charger()
    doc["worker_actif"] = True
    sauver(doc)

    drainage.enregistrer(
        en_attente=0, reussis=0, echecs=0, ignores=0, resume="",
        passe_le="2020-01-01T00:00:00+00:00",
    )
    assert client.get("/celcat/etat").json()["worker_ok"] is False

    drainage.enregistrer(en_attente=0, reussis=3, echecs=0, ignores=0, resume="")
    assert client.get("/celcat/etat").json()["worker_ok"] is True


def test_une_pause_deliberee_n_est_pas_une_panne() -> None:
    """Le worker à l'arrêt sur demande est joignable : il ne travaille
    simplement pas, et l'écran le dit déjà par ailleurs. Crier à la panne
    apprendrait à ignorer la pastille."""
    from cal_iut.celcat import drainage

    drainage.enregistrer(
        en_attente=0, reussis=0, echecs=0, ignores=0, resume="",
        passe_le="2020-01-01T00:00:00+00:00",
    )
    doc = charger()
    doc["worker_actif"] = False
    sauver(doc)

    assert client.get("/celcat/etat").json()["worker_ok"] is True
