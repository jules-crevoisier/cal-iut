"""Garde-fou catégorie CM et audit journal ↔ Live (hors write)."""

from __future__ import annotations

import pytest

from cal_iut.celcat.categories import (
    CategorieRefusee,
    categorie_live_coherente,
    inventaire_ecarts_categorie,
    libelle_categorie,
    verifier_charge_categorie,
)
from cal_iut.celcat.ecriture import charge_utile
from cal_iut.celcat.lecture import EvenementCelcat
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.rpc import masquer_semaine, preparer_evenement


GROUP_ID = 1661971
IDS_CM = {
    "module_id": 601106,
    "room_id": 104105,
    "staff_id": 603001,
    "event_cat_id": 430,
    "dept_id": 610029,
}
IDS_TP_PAR_ERREUR = {**IDS_CM, "event_cat_id": 451}


def _entree_cm(**kw) -> EntreeCelcat:
    base = dict(
        session_id="WR116-S1-CM-1",
        semaine=1,
        jour=2,
        heure_debut="14:00",
        heure_fin="15:30",
        code_enseignant="2569",
        salle="Amphi 3 MMI",
        code_module="TSBZ1M16",
        type_seance=None,
        type_seance_nom="CM",
        groupe="CM",
        semestre="S1",
        lundi="2026-09-07",
        course_code="WR116",
    )
    base.update(kw)
    return EntreeCelcat(**base)


def test_should_map_cm_td_tp_to_bracket_labels() -> None:
    assert libelle_categorie("CM") == "[CM]"
    assert libelle_categorie("td") == "[TD]"
    assert libelle_categorie("TP") == "[TP]"


def test_should_refuse_cm_charge_when_event_cat_id_is_tp() -> None:
    charge = charge_utile(
        _entree_cm(),
        group_id=GROUP_ID,
        ids=IDS_TP_PAR_ERREUR,
        masque=masquer_semaine(longueur=54, indice=3),
        event_id=1933241,
    )
    with pytest.raises(CategorieRefusee, match=r"430|\[CM\]"):
        verifier_charge_categorie(charge, type_seance_nom="CM")


def test_should_accept_cm_charge_when_event_cat_id_is_cm() -> None:
    charge = charge_utile(
        _entree_cm(),
        group_id=GROUP_ID,
        ids=IDS_CM,
        masque=masquer_semaine(longueur=54, indice=3),
        event_id=1933241,
    )
    verifier_charge_categorie(charge, type_seance_nom="CM")
    assert charge["event_id"] == 1933241
    assert charge["event_cat_id"] == 430


def test_should_keep_event_id_and_cm_cat_when_preparer_update() -> None:
    charge = charge_utile(
        _entree_cm(),
        group_id=GROUP_ID,
        ids=IDS_CM,
        masque=masquer_semaine(longueur=54, indice=3),
        event_id=1933241,
    )
    pret = preparer_evenement(charge)
    assert pret["event_id"] == 1933241
    assert pret["event_cat_id"] == 430


def test_should_detect_cm_journaled_as_tp_on_live() -> None:
    journal = {
        "WR116-S1-CM-1": {
            "event_id": 1933241,
            "signature": "1|2|14:00|15:30|2569|Amphi 3 MMI|TSBZ1M16|None|CM",
        }
    }
    live = {
        1933241: EvenementCelcat(
            event_id=1933241,
            jour=2,
            heure_debut="14:00",
            heure_fin="15:30",
            weeks="NNNY" + "N" * 50,
            categorie="[TP]",
            module_nom="WR116 Traitement Info",
            module_code="TSBZ1M16",
            salle="Amphi 3 MMI",
            enseignant="HUEZ Regis",
            group_id=1661971,
            groupe_nom="BUT MMI S1 CM",
            protected="N",
            global_event="N",
            brut={},
            event_cat_id=451,
        )
    }
    ecarts = inventaire_ecarts_categorie(
        journal=journal,
        live_par_event_id=live,
        type_par_session={"WR116-S1-CM-1": "CM"},
    )
    assert len(ecarts) == 1
    assert ecarts[0].session_id == "WR116-S1-CM-1"
    assert "[TP]" in ecarts[0].categorie_live
    assert not categorie_live_coherente("CM", "[TP]")
    assert categorie_live_coherente("CM", "[CM]")
