"""Autoriser la création sur une semaine que Celcat a encore vide.

Signalement de Jules, 28/09/2026 : « on a lancé cette semaine-là avec le
worker, elle est en lancé mais elle n'est toujours pas passée [...] et là j'ai
essayé de la pousser en corrigeant les écarts, ça ne marche pas non plus ».

Constaté en production le même jour : 535 jobs en file, **492 différés**, zéro
réussi. La semaine en cours (indice 4, lundi 28/09) ne contenait que 4 cours
dans Celcat pour 155 attendus : `semaines_posees` la jugeait « non posée », et
le worker mettait donc toutes ses créations en attente — d'une saisie manuelle
que personne n'allait faire, puisque c'est justement cal-iut qui doit remplir
cette semaine. La garde tournait contre son but.

Elle reste la règle par défaut. Ce test tient la levée : explicite, par
semaine, décidée par un humain.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from cal_iut.celcat import etat
from cal_iut.celcat.lecture import indice_depuis_lundi
from cal_iut.celcat.nuit import PREMIERE_SEMAINE_CELCAT, BilanDrainage, _ecarter_semaines_non_posees

# Lundi 28/09/2026 : la semaine du signalement.
LUNDI = "2026-09-28"
INDICE_SEMAINE = indice_depuis_lundi(date.fromisoformat(LUNDI), premiere_semaine_celcat=PREMIERE_SEMAINE_CELCAT)


def _drainer_une_creation(monkeypatch, *, autorisees: list[int]):
    """Une création sur une semaine que le relevé voit VIDE (aucun évènement
    relevé), comme la semaine en cours le 28/09/2026 en production."""
    _doc_avec(autorisees)
    from cal_iut.celcat import nuit

    monkeypatch.setattr(nuit, "lire", lambda: SimpleNamespace(evenements=[]), raising=False)
    entree = SimpleNamespace(lundi=LUNDI)
    bilan = BilanDrainage()
    retenus = _ecarter_semaines_non_posees(
        [{"action": "create", "session_id": "WR103-S1-TD-1-but1-td-ab"}],
        {"WR103-S1-TD-1-but1-td-ab": entree},
        bilan,
    )
    return retenus, bilan


@pytest.fixture(autouse=True)
def _etat_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(etat, "_CHEMIN", tmp_path / "celcat_sync.json", raising=False)
    monkeypatch.setattr(etat, "_path", lambda: tmp_path / "celcat_sync.json", raising=False)
    yield


def _doc_avec(autorisees: list[int]) -> dict[str, Any]:
    doc = etat.charger()
    doc["semaines_creation_autorisee"] = autorisees
    etat.sauver(doc)
    return etat.charger()


def test_letat_part_sans_aucune_semaine_autorisee() -> None:
    assert etat.charger()["semaines_creation_autorisee"] == []


def test_une_semaine_autorisee_est_relue_telle_quelle() -> None:
    assert _doc_avec([4])["semaines_creation_autorisee"] == [4]


def test_les_doublons_et_le_desordre_sont_normalises() -> None:
    assert _doc_avec([5, 4, 4])["semaines_creation_autorisee"] == [4, 5]


def test_un_etat_ecrit_avant_ce_champ_reste_lisible() -> None:
    """Une base déployée ne connaît pas encore la clé : elle doit se lire
    comme « aucune autorisation », jamais casser."""
    doc = etat.charger()
    doc.pop("semaines_creation_autorisee", None)
    etat.sauver(doc)
    assert etat.charger()["semaines_creation_autorisee"] == []


def test_le_worker_differe_une_creation_sur_une_semaine_vide(monkeypatch) -> None:
    """Le comportement par défaut, inchangé : Celcat vide, on attend."""
    retenus, bilan = _drainer_une_creation(monkeypatch, autorisees=[])
    assert retenus == []
    assert len(bilan.differes) == 1


def test_une_semaine_autorisee_laisse_passer_la_creation(monkeypatch) -> None:
    """LE test du signalement : la même création passe dès qu'un humain a
    autorisé la semaine, sans rien changer d'autre."""
    retenus, bilan = _drainer_une_creation(monkeypatch, autorisees=[INDICE_SEMAINE])
    assert [j["session_id"] for j in retenus] == ["WR103-S1-TD-1-but1-td-ab"]
    assert bilan.differes == []


def test_autoriser_une_autre_semaine_ne_debloque_pas_celle_ci(monkeypatch) -> None:
    retenus, bilan = _drainer_une_creation(monkeypatch, autorisees=[INDICE_SEMAINE + 1])
    assert retenus == []
    assert len(bilan.differes) == 1
