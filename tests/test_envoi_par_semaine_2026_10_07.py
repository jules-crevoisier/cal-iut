"""Une semaine cochée dans « Envoi par semaine » part au prochain passage.

Signalement de Jules, 07/10/2026 : « quand on clique sur les semaines, on
fait enregistrer la sélection [...] ça fait deux nuits qu'on essaie, ça ne
marche pas. [...] s'il peut le faire au prochain passage directement, c'est
mieux. Et il faut que ça fonctionne. »

Constaté en production le même jour : pastilles 1 à 7 enregistrées et
« lancées », 634 jobs en file dont 590 créations différées « semaine non
posée ». La semaine du 12/10 (pastille 7, indice Celcat 8) comptait 227
séances absentes de Celcat, toutes retenues : cocher la semaine ne levait pas
la garde de `semaines_posees`, seul le bouton « Autoriser la création » du
panneau de comparaison le faisait — un second geste que personne ne
connaissait. Et le balayage n'avait lieu qu'à minuit.

Ce que ce test tient :
- une semaine cochée vaut autorisation de création (c'est la décision
  humaine « cette semaine-là, vas-y » que la garde attend) ;
- « Enregistrer la sélection » balaie tout de suite, sans attendre la nuit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api.main import app
from cal_iut.celcat import etat
from cal_iut.celcat.nuit import BilanDrainage, _ecarter_semaines_non_posees

# Lundi 12/10/2026 : la semaine du signalement, indice solveur 6, pastille 7.
LUNDI = "2026-10-12"
INDICE_SOLVEUR = 6
SEANCE = "WR103-S1-TD-1-but1-td-ab"


def _drainer_une_creation(*, validees: list[int]):
    """Une création sur une semaine que le relevé voit VIDE, aucune
    autorisation explicite : seule la sélection « Envoi par semaine » change."""
    doc = etat.charger()
    doc["semaines_validees"] = validees
    doc["semaines_creation_autorisee"] = []
    etat.sauver(doc)
    entree = SimpleNamespace(lundi=LUNDI, semaine=INDICE_SOLVEUR)
    bilan = BilanDrainage()
    retenus = _ecarter_semaines_non_posees(
        [{"action": "create", "session_id": SEANCE}], {SEANCE: entree}, bilan
    )
    return retenus, bilan


@pytest.fixture
def etat_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(etat, "_path", lambda: tmp_path / "celcat_sync.json", raising=False)
    yield


def test_une_semaine_cochee_laisse_passer_ses_creations(etat_isole) -> None:
    """LE test du signalement : pastille 7 cochée, sa création part."""
    retenus, bilan = _drainer_une_creation(validees=[INDICE_SOLVEUR + 1])
    assert [j["session_id"] for j in retenus] == [SEANCE]
    assert bilan.differes == []


def test_cocher_une_autre_semaine_ne_debloque_pas_celle_ci(etat_isole) -> None:
    """La pastille n désigne l'indice n-1 : cocher la pastille 6 (l'indice 6
    pris pour une pastille) ne doit pas ouvrir la semaine du 12/10."""
    retenus, bilan = _drainer_une_creation(validees=[INDICE_SOLVEUR])
    assert retenus == []
    assert len(bilan.differes) == 1


def test_enregistrer_la_selection_balaie_tout_de_suite(db_isole, monkeypatch) -> None:
    """« Enregistrer » n'attend plus minuit : la semaine est comparée et mise
    en file au même instant, donc marquée lancée dans la réponse."""
    from cal_iut.celcat import etat as etat_celcat
    from cal_iut.celcat.instantane import enregistrer

    monkeypatch.setattr(etat_celcat, "semaines_celcat_passees", lambda **_: [])
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")
    client.patch("/celcat/saisie", json={"active": True})
    # Sans relevé, le balayage refuse d'enfiler (il croirait tout absent).
    enregistrer(
        [
            {
                "event_id": 1, "groupe": "BUT MMI S1 CM", "jour": 0,
                "heure_debut": "08:00", "heure_fin": "09:30", "salle": "H.101",
                "categorie": "[CM]", "module": "WR999", "semaine": 6,
            }
        ],
        groupes=["BUT MMI S1 CM"],
    )

    reponse = client.post("/celcat/valider", json={"semaines": [4, 5]})

    assert reponse.status_code == 200, reponse.text
    assert {4, 5} <= set(reponse.json()["semaines_lancees"])
    assert reponse.json()["dernier_job"]


def test_enregistrer_ecriture_coupee_ne_balaie_pas(db_isole) -> None:
    """Écriture coupée : on enregistre seulement, rien ne part."""
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")

    reponse = client.post("/celcat/valider", json={"semaines": [4, 5]})

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["semaines_lancees"] == []
