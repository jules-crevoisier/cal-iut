"""La matière vient d'une table relevée, plus d'une recherche à l'aveugle.

L'ÉCHEC. En production le 09/09/2026, juste après avoir réglé les groupes :

    1× TD exige event_cat_id pour [TD] — reçu vide
       [ids irrésolus : RessourceIntrouvable : matière TSBZC01M]
       (ex. WRA301M-S3-TD-1-but2-creacom-fc-td-gh)

CE QUE FAISAIT `_modules_par_scan`, et pourquoi ça ne pouvait pas marcher.
`udlResources.load` refuse d'énumérer le catalogue des matières
(`ETooManyRecords`) et `customOnly: True` rend zéro enregistrement. Faute de
catalogue, la fonction cherchait en deux temps :

1. elle rechargeait l'EDT des 88 groupes, un par un, et retenait les modules
   déjà posés sur un évènement ;
2. sinon elle balayait ±2500 identifiants autour des trois premiers modules
   ainsi vus — et, si elle n'en avait vu aucun, autour de 1660000, qui est
   un identifiant de GROUPE. Les matières vivent entre 1582737 et 1596928 :
   la mauvaise plage, à 65000 près.

Un module ne pouvait donc être trouvé que s'il servait DÉJÀ quelque part. Or
ceux qu'on cherchait sont précisément ceux qui n'ont jamais été posés : le
BUT2 CREACOM en alternance. Chaque échec coûtait 88 chargements d'EDT plus
une centaine d'appels de balayage, pour aboutir à rien.

LA DEUXIÈME MOITIÉ DU BUG, invisible tant que la première durait. Même avec
un catalogue complet, `TSBZC01M` n'existe pas : nos codes de maquette
finissent par M (S3 CREACOM FC, « combinés D + C = M »), les matières Celcat
par C. Le suffixe M était une déduction de notre part, jamais un relevé.

La règle vient de Kyllian lui-même : les trois seules lignes de ce bloc
qu'il a confirmées le 04/09 — WRA307M, WRA313M, WRA319M — donnent TSBZC07C,
TSBZC13C, TSBZC19C. Les seize autres suivent le même schéma, et les seize
codes en C existent dans Celcat avec le nom du cours attendu.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.celcat import ecriture
from cal_iut.celcat.ecriture import (
    RessourceIntrouvable,
    _matieres_connues,
    _trouver_matiere,
)
from cal_iut.celcat.navigateur import TYPE_MATIERES

RACINE = Path(__file__).resolve().parents[1]
CELCAT = RACINE / "data" / "config" / "celcat.yaml"


def _nos_codes() -> dict[str, str]:
    data = yaml.safe_load(CELCAT.read_text(encoding="utf-8")) or {}
    return {
        str(k).upper(): str(v).strip().upper()
        for k, v in (data.get("modules") or {}).items()
        if v
    }


@pytest.fixture(autouse=True)
def _table_relue():
    """`_MATIERES` est un cache de module."""
    ecriture._MATIERES = None
    yield
    ecriture._MATIERES = None


# --------------------------------------------------------------------------
# La table
# --------------------------------------------------------------------------


def test_chaque_code_de_la_maquette_est_dans_la_table() -> None:
    """LE test qui protège les prochaines saisies. Un code de `celcat.yaml`
    absent de `celcat_matieres.yaml` ne peut plus être trouvé à la volée : il
    échouerait en production, pas ici."""
    table = {c.upper() for c in _matieres_connues()}
    absents = sorted({c for c in _nos_codes().values() if c not in table})
    assert not absents, f"codes sans module_id relevé : {absents}"


@pytest.mark.parametrize(
    ("notre_code", "attendu"),
    [
        ("WRA301M", "TSBZC01C"),   # les 17 « matière introuvable »
        ("WRA304M", "TSBZC04C"),
        ("WRA305M", "TSBZC05C"),
        ("WRA307M", "TSBZC07C"),   # confirmé par Kyllian le 04/09 — la règle
        ("WRA313M", "TSBZC13C"),   # confirmé par Kyllian le 04/09
        ("WRA319M", "TSBZC19C"),   # confirmé par Kyllian le 04/09
        ("WSA301M", "TSBZC51C"),
        ("WSA302M", "TSBZC52C"),
        ("WS106", "TSBZ1556"),     # coquille : « TSBZ156 » n'existe pas
        ("WSA310M", "TSBZC600"),   # non-régression : ce M-là est le bon
    ],
)
def test_les_codes_s3_creacom_pointent_sur_la_matiere_en_c(
    notre_code: str, attendu: str
) -> None:
    assert _nos_codes()[notre_code] == attendu


def test_aucun_code_de_maquette_ne_finit_par_un_suffixe_invente() -> None:
    """Le motif de la panne : `TSBZC..M` était une déduction mécanique
    (WRA3xxM -> TSBZCxxM). Aucun n'existe côté Celcat."""
    fautifs = [c for c in _nos_codes().values() if c.startswith("TSBZC") and c.endswith("M")]
    assert not fautifs, f"suffixes déduits, jamais relevés : {fautifs}"


def test_aucun_identifiant_de_matiere_n_est_partage() -> None:
    table = _matieres_connues()
    valeurs = list(table.values())
    doublons = {v for v in valeurs if valeurs.count(v) > 1}
    assert not doublons, f"identifiants partagés : {doublons}"


# --------------------------------------------------------------------------
# La résolution
# --------------------------------------------------------------------------


def test_un_code_absent_de_la_table_est_un_refus_qui_dit_ou_corriger() -> None:
    with pytest.raises(RessourceIntrouvable) as capture:
        _trouver_matiere(FaussePage(), "matière TSBZC01M", "TSBZC01M", "module_id")
    assert "celcat_matieres.yaml" in str(capture.value)


def test_un_code_absent_ne_declenche_aucun_appel_rpc() -> None:
    """L'ancien chemin chargeait l'EDT des 88 groupes puis balayait une
    centaine de plages AVANT d'échouer. Le refus doit être immédiat."""
    page = FaussePage()
    with pytest.raises(RessourceIntrouvable):
        _trouver_matiere(page, "matière INEXISTANT", "INEXISTANT", "module_id")
    assert page.journal == [], f"aucun appel attendu, reçu {len(page.journal)}"


def test_un_code_connu_se_resout_en_un_seul_appel_cible() -> None:
    page = FaussePage()
    assert _trouver_matiere(page, "matière TSBZC01C", "TSBZC01C", "module_id") == 1601359

    charges = [
        arg for _js, arg in page.journal
        if isinstance(arg, dict) and arg.get("methode") == "udlResources.load"
    ]
    assert len(charges) == 1, f"un seul chargement attendu, reçu {len(charges)}"
    type_id, filtre = charges[0]["params"][0], charges[0]["params"][1]
    assert type_id == TYPE_MATIERES
    assert filtre["recordIDs"] == [1601359], (
        "la requête doit viser l'identifiant relevé, pas une plage à l'aveugle"
    )


def test_la_recherche_a_l_aveugle_n_existe_plus() -> None:
    """Non-régression : tant que `_modules_par_scan` existe, quelqu'un
    finira par le rebrancher — avec son ancre 1660000, qui est un
    identifiant de groupe."""
    assert not hasattr(ecriture, "_modules_par_scan")
