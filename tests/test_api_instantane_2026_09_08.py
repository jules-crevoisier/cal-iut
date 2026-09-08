"""L'API sert l'instantané Celcat et reçoit les demandes de rafraîchissement.

L'API ne LIT jamais Celcat elle-même : son conteneur n'a ni VPN ni
navigateur, et lui en donner couperait le site public (cf.
`celcat/instantane.py`). Elle ne fait que servir ce que le sidecar a déposé,
et transmettre les demandes.

Ce que ces tests protègent avant tout, c'est l'HONNÊTETÉ de la réponse : un
relevé vieux de deux heures ne doit jamais se présenter comme l'état
courant, et l'absence de relevé ne doit jamais ressembler à « Celcat est
vide ». C'est la leçon de la semaine — un worker qui annonçait « file
d'attente drainée » sans avoir rien écrit a coûté plusieurs jours.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.celcat import instantane

from conftest import creer_compte_actif_et_connecter

client = TestClient(app)

EVENEMENTS = [
    {
        "event_id": 1931709,
        "groupe": "BUT MMI S1 TD CD",
        "jour": 2,
        "heure_debut": "09:20",
        "heure_fin": "10:50",
        "salle": "H.007",
        "categorie": "[TD]",
        "enseignant": "LIBBRECHT Florent",
        "module": "WR120 Soutien",
        "semaine": 3,
    }
]


@pytest.fixture(autouse=True)
def _connecte(db_isole):
    creer_compte_actif_et_connecter(client, role="admin")
    yield


def test_refuse_un_anonyme() -> None:
    client.cookies.clear()
    assert client.get("/celcat/instantane").status_code in (401, 403)
    assert client.post("/celcat/instantane/rafraichir").status_code in (401, 403)


def test_sans_releve_le_dit_au_lieu_de_rendre_une_liste_vide() -> None:
    corps = client.get("/celcat/instantane").json()

    assert corps["releve_le"] is None
    assert corps["evenements"] == []
    assert corps["perime"] is True, "aucun relevé = à rafraîchir, jamais « tout va bien »"


def test_sert_le_releve_depose_par_le_sidecar() -> None:
    instantane.enregistrer(EVENEMENTS, groupes=["BUT MMI S1 TD CD"])

    corps = client.get("/celcat/instantane").json()
    assert len(corps["evenements"]) == 1
    assert corps["evenements"][0]["event_id"] == 1931709
    assert corps["groupes"] == ["BUT MMI S1 TD CD"]
    assert corps["perime"] is False
    assert corps["age_secondes"] is not None


def test_un_vieux_releve_est_annonce_comme_perime() -> None:
    """Sans ce drapeau, la vue afficherait un état d'il y a trois heures
    comme s'il était courant — au moment précis où l'on vérifie quelque
    chose."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    instantane.enregistrer(EVENEMENTS, groupes=[], releve_le=vieux)

    corps = client.get("/celcat/instantane").json()
    assert corps["perime"] is True
    assert corps["age_secondes"] > 2 * 3600


def test_rafraichir_pose_une_demande_sans_promettre_l_immediat() -> None:
    """Le sidecar l'honorera à son prochain passage : la réponse doit le
    dire, pas laisser croire que le relevé est déjà fait."""
    reponse = client.post("/celcat/instantane/rafraichir")

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["demande"] is True
    assert instantane.demande_en_cours() is True


def test_l_etat_de_la_demande_est_visible_dans_l_instantane() -> None:
    """Pour que le bouton puisse afficher « relevé demandé… » plutôt que de
    rester inerte, et pour que l'utilisateur ne clique pas dix fois."""
    assert client.get("/celcat/instantane").json()["demande_en_cours"] is False

    client.post("/celcat/instantane/rafraichir")
    assert client.get("/celcat/instantane").json()["demande_en_cours"] is True


def test_une_erreur_de_releve_remonte_au_lieu_d_etre_tue() -> None:
    """Si le sidecar n'a pas pu lire Celcat (VPN, session expirée), la vue
    doit le dire — un instantané vide sans explication renverrait au même
    silence que le worker de la veille."""
    instantane.enregistrer([], groupes=[], erreur="ESessionTimeout")

    corps = client.get("/celcat/instantane").json()
    assert corps["erreur"] == "ESessionTimeout"
