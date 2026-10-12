"""BU = A.123, jamais A.123b (Jules, 12/10/2026).

Trois séances WR100BU étaient dans Celcat en « A.123b » au lieu de la BU
(« A.123 ») : la recherche de salle prenait le PREMIER libellé qui
commençait par le nom voulu, même quand le nom exact existait plus loin.
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.celcat import ecriture
from cal_iut.celcat.mapping import load_celcat_config

ROOT = Path(__file__).resolve().parents[1]

CATALOGUE = [
    {"name": "A.123b", "unique_name": "A.123b", "id": 1},
    {"name": "A.123", "unique_name": "A.123", "id": 2},
    {"name": "A.1234", "unique_name": "A.1234", "id": 3},
]


def test_le_nom_exact_l_emporte_sur_un_libelle_qui_commence_pareil() -> None:
    assert ecriture._choisir(CATALOGUE, unique_name="A.123", name="A.123")["id"] == 2
    assert ecriture._choisir(list(reversed(CATALOGUE)), unique_name="A.123", name="A.123")["id"] == 2


def test_un_debut_de_nom_ambigu_est_un_refus() -> None:
    sans_exact = [e for e in CATALOGUE if e["id"] != 2]
    assert ecriture._choisir(sans_exact, unique_name="A.123", name="A.123") is None


def test_un_debut_de_nom_seul_de_son_espece_reste_accepte() -> None:
    assert ecriture._choisir([{"name": "H.022 studio", "id": 9}], name="H.022")["id"] == 9


def test_la_bu_correspond_a_a123_dans_la_config() -> None:
    assert load_celcat_config(ROOT / "data" / "config").salles["bu"] == "A.123"
