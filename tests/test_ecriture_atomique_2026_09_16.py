"""L'état partagé ne doit jamais être lisible à moitié écrit.

Le défaut réparé ici a une conséquence qu'aucun test ne couvrait : un JSON
tronqué ne fait pas lever `etat.charger()`, qui retombe sur `_vide()` — et le
`sauver()` suivant persiste ce vide. Le journal des correspondances séance ->
`event_id` disparaît alors définitivement, et tout le planning repart en
création, c'est-à-dire en double dans Celcat.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cal_iut.celcat.fichiers import ecrire_atomique, ecrire_json


def test_ecrit_le_contenu(tmp_path: Path) -> None:
    cible = tmp_path / "etat.json"
    ecrire_atomique(cible, '{"a": 1}')
    assert cible.read_text(encoding="utf-8") == '{"a": 1}'


def test_cree_le_repertoire_parent(tmp_path: Path) -> None:
    """Tous les appelants faisaient déjà ce `mkdir` ; l'oublier ici les
    obligerait à le refaire, et le premier qui oublierait planterait au
    premier démarrage sur volume vierge."""
    cible = tmp_path / "state" / "encore" / "etat.json"
    ecrire_atomique(cible, "x")
    assert cible.read_text(encoding="utf-8") == "x"


def test_remplace_sans_jamais_vider(tmp_path: Path) -> None:
    """Le point de tout l'exercice : entre deux versions, un lecteur voit
    l'ancienne ou la nouvelle, jamais un fichier absent ou tronqué."""
    cible = tmp_path / "etat.json"
    ecrire_atomique(cible, "ancien")

    vus: list[str] = []
    vrai_replace = __import__("os").replace

    def espion(source, destination):
        # Juste avant le basculement : la cible doit encore porter l'ancien
        # contenu ENTIER. Un `write_text` l'aurait déjà tronquée.
        vus.append(Path(destination).read_text(encoding="utf-8"))
        return vrai_replace(source, destination)

    from cal_iut.celcat import fichiers

    origine = fichiers.os.replace
    fichiers.os.replace = espion
    try:
        ecrire_atomique(cible, "nouveau")
    finally:
        fichiers.os.replace = origine

    assert vus == ["ancien"]
    assert cible.read_text(encoding="utf-8") == "nouveau"


def test_ne_laisse_aucun_temporaire(tmp_path: Path) -> None:
    cible = tmp_path / "etat.json"
    ecrire_atomique(cible, "x")
    assert [p.name for p in tmp_path.iterdir()] == ["etat.json"]


def test_echec_preserve_l_ancien_et_nettoie(tmp_path: Path, monkeypatch) -> None:
    """Un renommage impossible ne doit pas coûter le fichier précédent.

    C'est la garantie qui manquait : avec `write_text`, un échec en cours
    d'écriture laissait la cible amputée. Ici elle n'est pas touchée, et le
    temporaire ne s'accumule pas dans le volume."""
    cible = tmp_path / "etat.json"
    ecrire_atomique(cible, "ancien")

    from cal_iut.celcat import fichiers

    def casse(source, destination):
        raise OSError("disque plein")

    monkeypatch.setattr(fichiers.os, "replace", casse)
    with pytest.raises(OSError):
        ecrire_atomique(cible, "nouveau")

    assert cible.read_text(encoding="utf-8") == "ancien"
    assert [p.name for p in tmp_path.iterdir()] == ["etat.json"]


def test_json_garde_les_accents_lisibles(tmp_path: Path) -> None:
    """Un fichier d'état se relit à la main quand quelque chose ne va pas."""
    cible = tmp_path / "etat.json"
    ecrire_json(cible, {"motif": "séance non saisissable"})
    brut = cible.read_text(encoding="utf-8")
    assert "séance" in brut
    assert json.loads(brut) == {"motif": "séance non saisissable"}
