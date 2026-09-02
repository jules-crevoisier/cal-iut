"""Modifier une séance déjà posée dans Celcat, via RPC (localiser + fusionner
+ save), jamais un objet reconstruit depuis zéro (cause racine du "partial
key" — cf. `.orchestrator/architect-contract-celcat-modifier-seance.md`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_celcat_rpc import FaussePage

from cal_iut.celcat.categories import CategorieRefusee
from cal_iut.celcat.driver import SemainesNonRestreintes
from cal_iut.celcat.ecriture import ProductionRefusee
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import (
    ElementModification,
    EvenementIntrouvable,
    ResultatModification,
    fusionner_deltas,
    localiser_evenement,
    modifier_evenement,
    modifier_manquants,
)
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT, BASE_PRODUCTION
from cal_iut.celcat.rpc import masquer_semaine
from cal_iut.celcat.sync import journal, marquer_saisi

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
GROUPE = "BUT MMI S1 TD AB"


def _bruts() -> list[dict]:
    return json.loads(FIX.read_text(encoding="utf-8"))


def _wr106_brut() -> dict:
    return dict(next(b for b in _bruts() if b["event_id"] == 1931666))


def _entree(
    *,
    session_id: str = "wr106-cm-1",
    type_seance_nom: str = "CM",
    course_code: str = "WR106",
    code_module: str = "TSBZ2106",
) -> EntreeCelcat:
    return EntreeCelcat(
        session_id=session_id,
        semaine=5,
        jour=2,
        heure_debut="09:30",
        heure_fin="11:00",
        code_enseignant="MRI",
        salle="H.103",
        code_module=code_module,
        type_seance=None,
        type_seance_nom=type_seance_nom,
        groupe="CM",
        semestre="S1",
        lundi="2026-09-07",
        course_code=course_code,
    )


def _ids_valides() -> dict:
    # Ids alignées sur `_wr106_brut()` (module 601106, salle 104105) : ne
    # déclenchent PAS le rechargement de ressource (cf. tests dédiés plus
    # bas, qui visent délibérément un id différent).
    return {
        "module_id": 601106,
        "room_id": 104105,
        "staff_id": 34044,
        "event_cat_id": 430,
        "dept_id": 500001,
    }


def _masque_valide() -> str:
    return masquer_semaine(longueur=54, indice=5)


# ---------------------------------------------------------------------------
# localiser_evenement
# ---------------------------------------------------------------------------


def test_should_raise_evenement_introuvable_when_localiser_evenement_called_with_an_event_id_absent_from_every_loaded_group_id() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = _bruts()
    with pytest.raises(EvenementIntrouvable):
        localiser_evenement(page, 999999999, group_ids=[GROUP_ID])


def test_should_return_the_full_raw_record_including_original_id_when_localiser_evenement_finds_the_event_id_not_a_normalized_evenement() -> None:
    brut = _wr106_brut()
    brut["original_id"] = 1900000
    brut["accessRights"] = {"x": 1}
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [brut]

    trouve = localiser_evenement(page, 1931666, group_ids=[GROUP_ID])

    assert trouve == brut
    assert trouve["original_id"] == 1900000
    assert trouve["accessRights"] == {"x": 1}
    # Un dict brut Celcat, pas un EvenementCelcat normalisé : la clé
    # "evCatName" (jamais renommée "categorie") le prouve.
    assert isinstance(trouve, dict)
    assert "evCatName" in trouve
    assert "categorie" not in trouve


# ---------------------------------------------------------------------------
# fusionner_deltas
# ---------------------------------------------------------------------------


def test_should_overwrite_only_the_delta_fields_when_fusionner_deltas_runs_leaving_every_other_key_from_brut_untouched() -> None:
    brut = _wr106_brut()
    brut["original_id"] = 1900000
    brut["accessRights"] = {"x": 1}
    brut["notes"] = "ancienne note"
    entree = _entree()
    ids = dict(_ids_valides())
    # Ids INCHANGÉES par rapport au fixture (module 601106, staff — aucune
    # id d'origine —, groupe GROUP_ID) : ce test couvre le clonage du
    # sous-objet CHARGÉ, pas le rechargement d'une ressource ciblée (cf.
    # test_should_fetch_the_real_target_room_record_... ci-dessous pour ça).
    ids["module_id"] = 601106
    masque = _masque_valide()

    fusionne = fusionner_deltas(
        FaussePage(), brut, entree=entree, ids=ids, group_id=GROUP_ID, masque=masque
    )

    # Champs voulus REMPLACÉS.
    assert fusionne["day_of_week"] == entree.jour - 1
    assert fusionne["start_time"] == entree.heure_debut
    assert fusionne["end_time"] == entree.heure_fin
    assert fusionne["weeks"] == masque
    assert fusionne["event_cat_id"] == 430
    assert fusionne["dept_id"] == 500001
    assert fusionne["modules"][0]["module_id"] == 601106
    assert fusionne["rooms"][0]["room_id"] == 104105
    assert fusionne["staff"][0]["staff_id"] == 34044
    assert fusionne["groups"][0]["group_id"] == GROUP_ID
    assert fusionne["notes"] == entree.session_id

    # Tout le reste du dict CHARGÉ reste identique — c'est tout le correctif.
    assert fusionne["event_id"] == brut["event_id"]
    assert fusionne["original_id"] == 1900000
    assert fusionne["accessRights"] == {"x": 1}
    assert fusionne["protected"] == brut["protected"]
    assert fusionne["global_event"] == brut["global_event"]


def test_should_fetch_the_real_target_room_record_when_fusionner_deltas_changes_a_resource_id_instead_of_grafting_the_new_id_onto_the_old_rooms_stale_fields() -> None:
    """La cause du silencieux « écrit, mais rien ne change » constaté en
    direct le 02/09/2026 (event 202985, changement de salle) : greffer le
    nouvel id sur le sous-objet de l'ANCIENNE salle laisse un dept_id/nom
    incohérents avec la salle visée. Le correctif recharge le VRAI
    enregistrement de la salle visée via `udlResources.load`."""
    brut = _wr106_brut()  # rooms[0] = {"id": 104105, "name": "H.105"} — autre salle
    entree = _entree()
    ids = dict(_ids_valides())
    ids["room_id"] = 104103  # différent de la salle 104105 du fixture
    masque = _masque_valide()
    page = FaussePage()
    page.reponses["udlResources.load"] = [
        {"room_id": 104103, "name": "H.103", "dept_id": 500001, "unique_name": "1700AR_010"}
    ]

    fusionne = fusionner_deltas(
        page, brut, entree=entree, ids=ids, group_id=GROUP_ID, masque=masque
    )

    # La VRAIE salle 104103 est reprise telle quelle (nom, dept_id…), pas
    # l'ancienne salle 104105 avec juste l'id changée.
    assert fusionne["rooms"][0]["room_id"] == 104103
    assert fusionne["rooms"][0]["name"] == "H.103"
    assert fusionne["rooms"][0]["dept_id"] == 500001
    assert "id" not in fusionne["rooms"][0] or fusionne["rooms"][0]["id"] == 104103


def test_should_raise_evenement_introuvable_when_fusionner_deltas_targets_a_room_id_that_udlresources_load_does_not_return() -> None:
    brut = _wr106_brut()
    entree = _entree()
    ids = dict(_ids_valides())
    ids["room_id"] = 104103  # différent du fixture ; absent de la réponse ci-dessous
    masque = _masque_valide()
    page = FaussePage()
    page.reponses["udlResources.load"] = []

    with pytest.raises(EvenementIntrouvable, match="104103"):
        fusionner_deltas(page, brut, entree=entree, ids=ids, group_id=GROUP_ID, masque=masque)


# ---------------------------------------------------------------------------
# modifier_evenement
# ---------------------------------------------------------------------------


def test_should_send_the_full_merged_record_not_a_synthetic_minimal_one_to_save_when_modifier_evenement_runs_against_a_fausse_page() -> None:
    brut = _wr106_brut()
    brut["original_id"] = 1900000
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [brut]
    page.reponses["udlTimetables.save"] = 1931666

    confirme = modifier_evenement(
        page,
        _entree(),
        event_id=1931666,
        group_id=GROUP_ID,
        ids=_ids_valides(),
        masque=_masque_valide(),
        methode="udlTimetables.save",
    )

    assert confirme == 1931666
    appel_save = next(
        (js, arg)
        for js, arg in page.journal
        if isinstance(arg, dict) and (arg.get("methode") or arg.get("method")) == "udlTimetables.save"
    )
    _js, arg = appel_save
    envoye = arg["params"][0][0]
    assert envoye["event_id"] == 1931666
    # Un champ non touché par la fusion, absent de tout objet reconstruit
    # à la main : preuve que c'est bien l'enregistrement COMPLET qui part.
    assert envoye["original_id"] == 1900000


def test_should_raise_categorie_refusee_when_modifier_evenement_would_send_a_cm_event_without_event_cat_id_430() -> None:
    brut = _wr106_brut()
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [brut]
    page.reponses["udlTimetables.save"] = 1931666

    ids_sans_categorie = dict(_ids_valides())
    ids_sans_categorie["event_cat_id"] = None

    with pytest.raises(CategorieRefusee):
        modifier_evenement(
            page,
            _entree(type_seance_nom="CM"),
            event_id=1931666,
            group_id=GROUP_ID,
            ids=ids_sans_categorie,
            masque=_masque_valide(),
            methode="udlTimetables.save",
        )
    methodes = [
        (arg.get("methode") or arg.get("method"))
        for _js, arg in page.journal
        if isinstance(arg, dict)
    ]
    assert "udlTimetables.save" not in methodes


def test_should_raise_semaines_non_restreintes_when_the_merged_weeks_mask_is_not_exactly_one_y() -> None:
    brut = _wr106_brut()
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [brut]
    page.reponses["udlTimetables.save"] = 1931666

    with pytest.raises(SemainesNonRestreintes):
        modifier_evenement(
            page,
            _entree(),
            event_id=1931666,
            group_id=GROUP_ID,
            ids=_ids_valides(),
            masque="N" * 54,
            methode="udlTimetables.save",
        )


def test_should_raise_production_refusee_when_base_is_urca_2026_and_production_autorisee_is_false() -> None:
    brut = _wr106_brut()
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [brut]
    page.reponses["udlTimetables.save"] = 1931666

    with pytest.raises(ProductionRefusee):
        modifier_evenement(
            page,
            _entree(),
            event_id=1931666,
            group_id=GROUP_ID,
            ids=_ids_valides(),
            masque=_masque_valide(),
            methode="udlTimetables.save",
            base=BASE_PRODUCTION,
            production_autorisee=False,
        )
    assert BASE_ENTRAINEMENT != BASE_PRODUCTION  # garde-fou toujours distinct


# ---------------------------------------------------------------------------
# modifier_manquants
# ---------------------------------------------------------------------------


def test_should_keep_processing_remaining_elements_and_record_the_failure_when_one_element_modification_fails_inside_modifier_manquants() -> None:
    brut_ok = _wr106_brut()
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [brut_ok]
    page.reponses["udlTimetables.save"] = 1931666

    elements = [
        ElementModification(
            entree=_entree(session_id="s-introuvable"),
            event_id=777777777,  # absent du group_id interrogé
            group_id=GROUP_ID,
            ids=_ids_valides(),
            masque=_masque_valide(),
        ),
        ElementModification(
            entree=_entree(session_id="s-ok"),
            event_id=1931666,
            group_id=GROUP_ID,
            ids=_ids_valides(),
            masque=_masque_valide(),
        ),
    ]

    resultat = modifier_manquants(page, elements, methode="udlTimetables.save")

    assert isinstance(resultat, ResultatModification)
    modifiees_ids = {sid for sid, _eid in resultat.modifiees}
    echecs_ids = {sid for sid, _msg in resultat.echecs}
    assert "s-ok" in modifiees_ids
    assert "s-introuvable" in echecs_ids
    assert "s-introuvable" not in modifiees_ids
    assert "s-ok" not in echecs_ids


# ---------------------------------------------------------------------------
# sync.py::marquer_saisi(group_id=...)
# ---------------------------------------------------------------------------


def test_should_persist_group_id_in_the_journal_row_when_marquer_saisi_called_with_one_and_omit_it_when_not_given() -> None:
    entree = _entree(session_id="wr106-cm-group")

    marquer_saisi(entree, event_id=1931666, group_id=GROUP_ID)
    ligne = journal()["wr106-cm-group"]
    assert str(ligne.get("group_id")) == str(GROUP_ID)

    marquer_saisi(entree, event_id=1931666)
    ligne_sans = journal()["wr106-cm-group"]
    assert "group_id" not in ligne_sans
