"""Garde-fous d'écriture RPC — une semaine, pas de production, pas de delete."""

from __future__ import annotations

import pytest

from cal_iut.celcat.ecriture import (
    ProductionRefusee,
    SemainesNonRestreintes,
    charge_utile,
    creer_manquants,
    resoudre_ids,
    verifier_avant_envoi,
)
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.rpc import charger_edt, masquer_semaine
from test_celcat_rpc import FaussePage

GROUP_ID = 1661972
IDS = {
    "module_id": 601106,
    "room_id": 104105,
    "staff_id": 603001,
    "event_cat_id": 850,
    "dept_id": 610029,
}


def _entree(**kw) -> EntreeCelcat:
    base = dict(
        session_id="s-wr107-ab",
        semaine=4,
        jour=1,
        heure_debut="08:00",
        heure_fin="09:30",
        code_enseignant="RIGUET",
        salle="H.105",
        code_module="TSBZ2107",
        type_seance=4,
        type_seance_nom="TD",
        groupe="TD AB",
        semestre="S1",
        lundi="2026-09-07",
        course_code="WR107",
    )
    base.update(kw)
    return EntreeCelcat(**base)


def _masque() -> str:
    return masquer_semaine(longueur=54, indice=3)


@pytest.mark.parametrize("weeks", ["Y" * 54, "N" * 54, "YY" + "N" * 52, "YNY" + "N" * 51])
def test_should_refuse_when_weeks_are_not_exactly_one_y(weeks: str) -> None:
    with pytest.raises(SemainesNonRestreintes):
        verifier_avant_envoi(
            {"weeks": weeks},
            base="URCA_FORMATION",
            production_autorisee=True,
        )


def test_should_refuse_production_base_when_production_autorisee_false() -> None:
    with pytest.raises(ProductionRefusee):
        verifier_avant_envoi(
            {"weeks": _masque()},
            base="URCA_2026",
            production_autorisee=False,
        )


def test_should_resolve_numeric_ids_when_resoudre_ids() -> None:
    page = FaussePage()
    page.reponses["udlResources.load"] = [
        {"id": 58186, "unique_name": "TSBZ1307", "name": "WR107 Ecrit. Multimédia"},
        {"id": 1604422, "name": "H.105", "room_id": 1604422},
        {"id": 1610256, "unique_name": "34044", "name": "RIGUET Marine"},
        {"id": 431, "name": "[TD]"},
        {"id": 936, "name": "T_MMI T29"},
    ]
    ids = resoudre_ids(
        page,
        _entree(code_module="TSBZ1307", code_enseignant="34044", salle="H.105"),
        categorie="[TD]",
    )
    assert ids["module_id"] == 58186
    assert ids["room_id"] == 1604422
    assert ids["staff_id"] == 1610256
    assert ids["event_cat_id"] == 431
    assert ids["dept_id"] == 936
    for _js, arg in page.journal:
        if isinstance(arg, dict) and arg.get("methode") == "udlResources.load":
            filtre = arg["params"][1]
            assert "name" not in filtre
            assert "uniqueName" not in filtre


def test_should_send_module_id_and_rpc_monday_zero_when_charge_utile() -> None:
    charge = charge_utile(
        _entree(),
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        event_id=0,
    )
    assert "event_id" not in charge
    assert charge["day_of_week"] == 0
    assert charge["groups"][0]["group_id"] == GROUP_ID
    assert charge["modules"][0]["module_id"] == IDS["module_id"]
    assert charge["rooms"][0]["room_id"] == IDS["room_id"]
    assert charge["staff"][0]["staff_id"] == IDS["staff_id"]
    assert "id" not in charge["groups"][0]


def test_should_send_sentinel_event_id_and_group_when_charge_utile() -> None:
    charge = charge_utile(
        _entree(),
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        event_id=0,
    )
    assert "event_id" not in charge
    assert charge["groups"][0]["group_id"] == GROUP_ID


def test_should_keep_event_id_when_charge_utile_updates_existing_event() -> None:
    """Modifier un cours déjà dans Celcat = save avec le même event_id.

    CI ne frappe pas Live. Ce contrat dit : la charge d'update porte
    l'identifiant, pas un create (event_id absent / 0) ni un delete.
    """
    charge = charge_utile(
        _entree(),
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        event_id=1931666,
    )
    assert charge["event_id"] == 1931666
    assert "new" not in charge
    assert "delete" not in {str(k).lower() for k in charge}


def test_should_not_call_delete_remove_or_new_when_creer_manquants() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.save"] = 8000001
    creer_manquants(
        page,
        [_entree()],
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        methode="udlTimetables.save",
    )
    for _js, arg in page.journal:
        if not isinstance(arg, dict):
            continue
        nom = str(arg.get("methode") or arg.get("method") or "").lower()
        assert "delete" not in nom
        assert "remove" not in nom
        assert "new" not in nom


def test_should_record_session_id_when_save_returns_event_list() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.save"] = [{"event_id": 202985, "notes": "cal-iut-canari"}]
    entree = _entree()
    resultat = creer_manquants(
        page,
        [entree],
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        methode="udlTimetables.save",
    )
    assert (entree.session_id, 202985) in list(resultat.crees)


def test_should_record_session_id_and_event_id_when_save_returns_id() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.save"] = 8000001
    entree = _entree()
    resultat = creer_manquants(
        page,
        [entree],
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        methode="udlTimetables.save",
    )
    assert (entree.session_id, 8000001) in list(resultat.crees)
    events = charger_edt(page, group_ids=[GROUP_ID])
    assert any((e.get("event_id") or e.get("id")) == 8000001 for e in events)


def test_should_pass_event_id_to_save_when_creer_manquants_updates() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.save"] = 1931666
    creer_manquants(
        page,
        [_entree()],
        group_id=GROUP_ID,
        ids=IDS,
        masque=_masque(),
        methode="udlTimetables.save",
        event_id=1931666,
    )
    evenement = None
    for _js, arg in page.journal:
        if isinstance(arg, dict) and arg.get("methode") == "udlTimetables.save":
            evenement = arg["params"][0][0]
            break
    assert evenement is not None
    assert evenement["event_id"] == 1931666
    for _js, arg in page.journal:
        if not isinstance(arg, dict):
            continue
        nom = str(arg.get("methode") or arg.get("method") or "").lower()
        assert "delete" not in nom
        assert "remove" not in nom
        assert "new" not in nom
