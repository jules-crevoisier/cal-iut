"""Semaines du semestre pair dans la couche Celcat (16/11/2026).

Les `week` du semestre pair sont relatives à février ; Celcat veut un indice
du calendrier annuel. Le garde-fou reste en place tant que Jules n'a pas posé
`CAL_IUT_CELCAT_SEMESTRE_PAIR=on`."""

from __future__ import annotations

from datetime import date

import pytest
from test_deux_semestres_2026_11_16 import (  # noqa: F401  (fixtures partagées)
    base,
    deux_semestres,
    main,
)

from cal_iut.api.main import charger_etat_applicatif
from cal_iut.api.state import get_state
from cal_iut.celcat import planification, sync

pytestmark = pytest.mark.usefixtures("date_du_jour_figee")
# ruff: noqa: F811


@pytest.fixture
def printemps(deux_semestres, monkeypatch):
    monkeypatch.setattr(main, "_today", lambda: date(2027, 2, 3))
    charger_etat_applicatif()
    etat = get_state()
    assert etat.semestre_group == "even"
    return etat


def test_la_semaine_zero_du_pair_est_le_premier_lundi_de_fevrier(printemps):
    assert planification.decalage_semaines(printemps) > 0
    assert planification.lundi_de_semaine(printemps, 0) == date(2027, 2, 1)
    # Les semaines de vacances sont absentes de `teaching_mondays` : la
    # semaine 3 du planning est la 3e semaine ENSEIGNÉE, pas le 22/02.
    decalage = planification.decalage_semaines(printemps)
    assert planification.lundi_de_semaine(printemps, 3) == printemps.calendar.teaching_mondays[decalage + 3]
    assert planification.lundi_de_semaine(printemps, -1) is None


def test_l_automne_garde_son_decalage_nul(deux_semestres):
    automne = get_state()
    assert planification.decalage_semaines(automne) == 0
    assert planification.lundi_de_semaine(automne, 0) == date(2026, 8, 31)


def test_l_indice_celcat_du_pair_differe_de_celui_de_l_automne(printemps, deux_semestres):
    assert planification.indice_celcat_de_semaine(printemps, 0) > 19
    assert planification.indice_celcat_de_semaine(printemps, 10_000) == -1


def test_le_garde_fou_reste_ferme_par_defaut_et_s_ouvre_sur_interrupteur(printemps, monkeypatch):
    monkeypatch.delenv("CAL_IUT_CELCAT_SEMESTRE_PAIR", raising=False)
    assert planification.comparaison_prise_en_charge(printemps) is False
    monkeypatch.setenv("CAL_IUT_CELCAT_SEMESTRE_PAIR", "on")
    assert planification.comparaison_prise_en_charge(printemps) is True


def test_la_comparaison_du_pair_utilise_la_semaine_convertie(printemps, monkeypatch):
    monkeypatch.setenv("CAL_IUT_CELCAT_SEMESTRE_PAIR", "on")
    placement = next(p for p in printemps.timetable)
    indice = planification.indice_celcat_de_semaine(printemps, placement.week)
    # Un évènement posé à la semaine de l'AUTOMNE correspondante (même
    # numéro relatif) n'est pas rapproché : il est d'un autre indice.
    ev = {
        "event_id": 9, "semaine": planification.indice_celcat_de_semaine(printemps, placement.week) - 19,
        "module": "WR999", "groupe": "BUT MMI S2 TD AB", "jour": 0, "heure_debut": "08:00", "salle": "H.007",
    }
    lignes = planification.lignes(
        printemps, semaine=placement.week, semaine_celcat=indice, evenements=[ev]
    )
    assert all(l["celcat"] is None or l["celcat"].get("event_id") != 9 for l in lignes)


def test_la_saisie_du_pair_ne_supprime_pas_les_seances_de_l_automne(monkeypatch):
    journal = {
        "A-AUTOMNE": {"session_id": "A-AUTOMNE", "semaine": "3", "semestre": "S1", "event_id": "1"},
        "VIEUX": {"session_id": "VIEUX", "semaine": "3", "event_id": "2"},
        "P-ANCIEN": {"session_id": "P-ANCIEN", "semaine": "3", "semestre": "S2", "event_id": "3"},
    }
    monkeypatch.setattr(sync, "journal", lambda: journal)

    class E:
        session_id, semaine, semestre = "P-NEUF", 3, "S2"
        non_envoyee, prete = "", True
        def signature(self): return "x"

    plan = sync.construire_plan([E()], {3})
    assert plan.a_supprimer == ["P-ANCIEN"]

    class F(E):
        session_id, semestre = "A-NEUF", "S1"

    plan = sync.construire_plan([F()], {3})
    assert sorted(plan.a_supprimer) == ["A-AUTOMNE", "VIEUX"]


def test_les_pastilles_passees_suivent_le_semestre_servi(printemps):
    from cal_iut.celcat.etat import semaines_celcat_passees

    # Début de S2 = 3 février 2027 -> aucune semaine du pair n'est passée,
    # alors que les premières pastilles de S1 le sont.
    assert semaines_celcat_passees(today=date(2027, 2, 3)) == []
