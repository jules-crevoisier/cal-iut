"""Mapper une salle ou un enseignant depuis l'écran, sans redéploiement.

Le 20/09/2026, la production tournait avec cinq séances bloquées depuis des
jours, réécartées toutes les quatre-vingt-dix secondes :

    2× salle « e-102 » sans équivalent Celcat
    3× enseignant JHU sans code Celcat

Deux problèmes distincts, signalés le même jour :

1. ces blocages n'existaient que dans `docker compose logs` — les cinq
   endroits qui écartent un job ne journalisaient rien, si bien que la
   colonne « Bloquées » de l'écran restait vide pendant que la file ne
   descendait pas ;
2. la table de correspondance vit dans `data/config/celcat.yaml`, qui est
   DANS L'IMAGE Docker : ajouter une ligne demandait une modification du
   code, une revue et un déploiement.

    « il faut faire en sorte d'avoir des logs sur ce qu'il se passe, exemple :
      prof non attribué dans Celcat, salle non mappée »
    « pour la salle il faut avoir une option pour mapper »
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cal_iut.celcat import mappings
from cal_iut.celcat.mapping import load_celcat_config


@pytest.fixture(autouse=True)
def _surcouche_isolee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mappings, "_path", lambda: tmp_path / "celcat_mappings.json")


def _celcat_yaml(dossier: Path, contenu: str) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "celcat.yaml").write_text(contenu, encoding="utf-8")
    return dossier


def test_une_salle_mappee_complete_le_yaml(tmp_path: Path) -> None:
    config = _celcat_yaml(tmp_path / "config", 'salles:\n  h018: "Amphi 3 MMI"\n')
    assert load_celcat_config(config).salles.get("e-102") is None

    mappings.definir("salles", "e-102", "H.104", par="jules@iut")

    cfg = load_celcat_config(config)
    assert cfg.salles["e-102"] == "H.104"
    assert cfg.salles["h018"] == "Amphi 3 MMI", "le YAML n'est pas remplacé, il est complété"


def test_la_surcouche_a_le_dernier_mot(tmp_path: Path) -> None:
    """Corriger depuis l'écran une entrée que le YAML a fausse doit marcher
    tout de suite — sinon on édite deux endroits en se demandant lequel gagne."""
    config = _celcat_yaml(tmp_path / "config", 'salles:\n  h018: "Amphi 3 MMI"\n')
    mappings.definir("salles", "h018", "Amphi 2 MMI")
    assert load_celcat_config(config).salles["h018"] == "Amphi 2 MMI"


def test_un_enseignant_se_mappe_en_majuscules(tmp_path: Path) -> None:
    """`load_celcat_config` compare les trigrammes en majuscules : les
    enregistrer autrement les rendrait invisibles."""
    config = _celcat_yaml(tmp_path / "config", "enseignants:\n  DAN: \"16041\"\n")
    mappings.definir("enseignants", "jhu", "38999")
    assert load_celcat_config(config).enseignants["JHU"] == "38999"


def test_un_code_enseignant_a_zero_reste_un_code_absent(tmp_path: Path) -> None:
    """« 0 » signifie « pas encore de code » dans le YAML. Le mapper à « 0 »
    depuis l'écran ferait chercher l'enseignant « 0 » dans Celcat."""
    config = _celcat_yaml(tmp_path / "config", "enseignants: {}\n")
    mappings.definir("enseignants", "JHU", "0")
    assert "JHU" not in load_celcat_config(config).enseignants


def test_une_correspondance_garde_son_origine() -> None:
    """Une table qu'on ne peut pas dater devient un ensemble de décisions que
    plus personne n'assume."""
    entree = mappings.definir("salles", "e-102", "H.104", par="jules@iut")
    assert entree["valeur"] == "H.104"
    assert entree["ajoute_par"] == "jules@iut"
    assert entree["ajoute_le"]


def test_on_peut_oublier_une_correspondance(tmp_path: Path) -> None:
    config = _celcat_yaml(tmp_path / "config", "salles: {}\n")
    mappings.definir("salles", "e-102", "H.104")
    assert mappings.oublier("salles", "e-102") is True
    assert mappings.oublier("salles", "e-102") is False
    assert "e-102" not in load_celcat_config(config).salles


def test_une_valeur_vide_est_refusee() -> None:
    """`definir` avec une valeur vide serait une suppression déguisée."""
    with pytest.raises(ValueError):
        mappings.definir("salles", "e-102", "   ")
    with pytest.raises(ValueError):
        mappings.definir("familles-inventee", "x", "y")


def test_une_surcouche_illisible_ne_casse_pas_la_synchro(tmp_path: Path) -> None:
    """Perdre une correspondance coûte une séance bloquée, visible. Lever ici
    casserait tout l'écran Celcat."""
    mappings._path().write_text('{"salles": {"e-102"', encoding="utf-8")
    config = _celcat_yaml(tmp_path / "config", 'salles:\n  h018: "Amphi 3 MMI"\n')
    assert load_celcat_config(config).salles == {"h018": "Amphi 3 MMI"}


def test_les_motifs_de_blocage_disent_quoi_mapper() -> None:
    """L'écran doit proposer le bon champ : « salle e-102 » mène au mapping
    des salles, « enseignant JHU » à celui des enseignants, et une séance
    disparue de la maquette ne se mappe pas."""
    from cal_iut.api.main import _cle_du_motif, _famille_du_motif

    salle = (
        "séance non saisissable, salle manquant(s) : salle « e-102 » sans "
        "équivalent Celcat (cf. data/config/celcat.yaml)"
    )
    prof = "séance non saisissable, enseignant manquant(s) : enseignant JHU sans code Celcat"

    assert (_famille_du_motif(salle), _cle_du_motif(salle)) == ("salles", "e-102")
    assert (_famille_du_motif(prof), _cle_du_motif(prof)) == ("enseignants", "JHU")
    assert _famille_du_motif("séance inconnue de la maquette") == ""
