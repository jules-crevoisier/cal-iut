"""Code module Celcat d'une matière, saisi dans l'appli (29/09/2026, « go »).

Le 29/09/2026, « Jeu de piste BU » (WR100BU) bloquait douze séances sur
« module WR100BU sans code Celcat » : la table vit dans `celcat.yaml`, dans
l'image Docker. Les correspondances Celcat saisies à l'écran
(`celcat/mappings.py`) gagnent une famille `matieres` : code de cours ->
code module (`TSB…`). Ce que ces tests protègent :

- la saisie est réservée aux administrateurs, et limitée aux codes modules
  RELEVÉS (`celcat_matieres.yaml`) — un code inconnu échouerait plus loin, à
  l'écriture, loin de la saisie ;
- une fois mappée, la matière n'est plus « bloque Celcat », et le plan
  Celcat (`/celcat/plan`, `_entrees_celcat`) utilise le code saisi ;
- l'écran Celcat la reconnaît dans ses blocages et accepte le même geste ;
- l'identifiant interne (`celcat_matieres.yaml`) et celui des groupes
  (`celcat_groupes.yaml`) restent non saisissables, et le disent.
"""

from __future__ import annotations

from test_completer_reference_2026_09_29 import (  # noqa: F401 — fixtures partagées
    _ids,
    admin,
    edit,
    etat,
    lecteur,
)

from cal_iut.api import main as api_main
from cal_iut.celcat import mappings
from cal_iut.celcat.mapping import load_celcat_config
from cal_iut.ingestion import surcharges_reference


def test_la_famille_matieres_complete_les_modules(etat) -> None:  # noqa: F811
    assert "WRX99" not in load_celcat_config(etat.config_dir).modules
    mappings.definir("matieres", "wrx99", "tsb0101", par="x")
    modules = load_celcat_config(etat.config_dir).modules
    assert modules["WRX99"] == "TSB0101", "clé et valeur en majuscules, comme le YAML"
    assert modules["WR101"] == "TSB0101", "le YAML n'est pas remplacé, il est complété"


def test_une_matiere_sans_module_est_saisissable_par_un_admin(lecteur) -> None:  # noqa: F811
    par_id = {m["id"]: m for m in lecteur.get("/reference/manques").json()["manques"]}
    manque = par_id["cours:WRX99:code_celcat"]
    assert (manque["gravite"], manque["role_requis"]) == ("bloque_celcat", "admin")
    # Les identifiants internes de groupe, eux, ne se saisissent pas.
    groupe = par_id["groupe:BUT MMI S1 CM:id_celcat"]
    assert groupe["role_requis"] is None and "Se règle dans data/config/celcat_groupes.yaml" in groupe["ou_completer"]


def test_code_module_droits_et_validation(edit, admin) -> None:  # noqa: F811
    assert edit.put("/reference/cours/WRX99", json={"code_celcat": "TSB0101"}).status_code == 403
    mauvais = admin.put("/reference/cours/WRX99", json={"code_celcat": "WR101"})
    assert mauvais.status_code == 400 and "TSBZ1M01" in mauvais.json()["detail"]
    inconnu = admin.put("/reference/cours/WRX99", json={"code_celcat": "TSBZ9999"})
    assert inconnu.status_code == 400 and "celcat_matieres.yaml" in inconnu.json()["detail"]
    assert not mappings.charger()["matieres"]


def test_une_fois_mappee_la_matiere_ne_bloque_plus_et_le_plan_l_utilise(admin, etat) -> None:  # noqa: F811
    avant = admin.get("/celcat/plan?semaines=10").json()
    assert avant["motifs_blocage"].get("module WRX99 sans code Celcat") == 1

    reponse = admin.put("/reference/cours/WRX99", json={"code_celcat": " tsb0199 "})
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["valeurs"] == {"code_celcat": "TSB0199"}

    assert "cours:WRX99:code_celcat" not in _ids(admin)
    apres = admin.get("/celcat/plan?semaines=10").json()
    assert "module WRX99 sans code Celcat" not in apres["motifs_blocage"]
    entree = next(e for e in api_main._entrees_celcat(etat) if e.session_id == "wrx1")
    assert entree.code_module == "TSB0199"
    assert not any("module" in b for b in entree.bloquants)
    # Tracé, avec son auteur.
    assert mappings.charger()["matieres"]["WRX99"]["ajoute_par"].startswith("test-admin-")
    ligne = surcharges_reference.journal()[0]
    assert (ligne["famille"], ligne["cle"], ligne["champ"], ligne["apres"]) == ("cours", "WRX99", "code_celcat", "TSB0199")


def test_l_ecran_celcat_reconnait_et_mappe_une_matiere(admin) -> None:  # noqa: F811
    assert api_main._famille_du_motif("module WR100BU sans code Celcat") == "matieres"
    assert api_main._cle_du_motif("module WR100BU sans code Celcat") == "WR100BU"
    refus = admin.put("/celcat/mappings", json={"famille": "matieres", "cle": "WRX99", "valeur": "n'importe"})
    assert refus.status_code == 400
    ok = admin.put("/celcat/mappings", json={"famille": "matieres", "cle": "wrx99", "valeur": "tsb0199"})
    assert ok.status_code == 200, ok.text
    corps = ok.json()
    assert [(m["cle"], m["valeur"]) for m in corps["matieres"]] == [("WRX99", "TSB0199")]
    assert "TSB0101" in corps["matieres_celcat"]
    assert admin.delete("/celcat/mappings?famille=matieres&cle=WRX99").status_code == 200
    assert not mappings.charger()["matieres"]


def test_module_connu_mais_identifiant_interne_absent(admin, etat) -> None:  # noqa: F811
    """Le code module est dans `celcat.yaml`, mais son identifiant interne
    n'est pas relevé : non saisissable, et l'écran dit où le régler."""
    (etat.config_dir / "celcat_matieres.yaml").write_text('"TSB0102": 2\n', encoding="utf-8")
    par_id = {m["id"]: m for m in admin.get("/reference/manques").json()["manques"]}
    manque = par_id["cours:WR101:id_celcat"]
    assert manque["role_requis"] is None
    assert "celcat_matieres.yaml" in manque["ou_completer"] and "TSB0101" in manque["ou_completer"]
