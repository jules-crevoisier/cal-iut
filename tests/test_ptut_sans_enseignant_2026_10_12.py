"""Une séance PTUT SANS enseignant part quand même dans Celcat.

Signalement de Jules (12/10/2026) : « apparemment les ptut ne se saisissent
pas », puis « une séance de ptut a par défaut pas de prof ». Toute séance
sans enseignant était bloquée (« aucun enseignant ») : le robot ne l'envoyait
jamais, alors que la règle PTUT (catégorie Projet) était active.

La règle PTUT porte désormais `enseignant: facultatif` (celcat.yaml) : une
PTUT sans enseignant part sans personnel (`staff: []`), aucun enseignant
n'est cherché dans Celcat. Une séance ordinaire sans enseignant reste
bloquée, et une PTUT dont l'enseignant n'a pas de code Celcat aussi : là,
c'est une donnée qui manque.
"""

from __future__ import annotations

import pytest
from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    monter_planning,
    place,
    poser_semaines_celcat,
    restaurer_etat,
    seance,
    snapshot_etat,
    vider_file,
)
from test_celcat_regles_envoi_2026_10_01 import (  # type: ignore[import-not-found]
    _cfg,
    _ecrire_config,
    catalogues,  # noqa: F401 — fixture réutilisée
)
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state
from cal_iut.celcat import ecriture
from cal_iut.celcat.categories import verifier_charge_categorie
from cal_iut.celcat.mapping import (
    ConfigCelcatInvalide,
    entree_pour_placement,
    load_celcat_config,
    session_id_depuis_notes,
)
from cal_iut.celcat.navigateur import TYPE_PERSONNEL
from cal_iut.celcat.nuit import motif_non_saisissable
from cal_iut.models.entities import SessionType

MASQUE = "N" * 5 + "Y" + "N" * 48


@pytest.fixture(autouse=True)
def _regles_actives(monkeypatch):
    monkeypatch.setenv("CAL_IUT_REGLES_ENVOI", "on")


def _entree(profs: list[str], *, cours: str = "WR101", type_: str = "PTUT", sid: str = "WR101-S1-PTUT-1"):
    return entree_pour_placement(
        _cfg(),
        session_id=sid,
        course_code=cours,
        session_type=type_,
        week=2, day=1, slot=4, duration_slots=1,
        teacher_codes=profs,
        room_id="h101",
        groupe="TD AB",
        semestre="S1",
        lundi="2026-09-14",
    )


def test_la_regle_ptut_rend_l_enseignant_facultatif_dans_la_config_reelle() -> None:
    cfg = _cfg()
    assert cfg.regles_types["PTUT"].enseignant_facultatif is True
    assert cfg.regles_cours["WR100BU"].enseignant_facultatif is False


def test_une_ptut_sans_enseignant_est_prete_au_lieu_d_etre_bloquee() -> None:
    e = _entree([])
    assert e.prete, e.bloquants
    assert (e.regle, e.sans_enseignant, e.code_enseignant) == ("PTUT", True, None)
    assert e.regle_libelle == "module du cours (règle PTUT), sans enseignant"
    assert motif_non_saisissable(e) == ""


def test_une_ptut_avec_enseignant_ne_change_pas() -> None:
    e = _entree(["MRI"])
    assert e.prete and not e.sans_enseignant and e.code_enseignant == "34044"
    assert e.regle_libelle == "module du cours (règle PTUT)"


def test_une_seance_ordinaire_sans_enseignant_reste_bloquee() -> None:
    e = _entree([], type_="TD", sid="WR101-S1-TD-1")
    assert not e.prete and "aucun enseignant" in e.bloquants and not e.sans_enseignant
    assert "enseignant" in motif_non_saisissable(e)


def test_une_ptut_dont_l_enseignant_n_a_pas_de_code_reste_bloquee() -> None:
    e = _entree(["ZZZ"])
    assert not e.prete and "enseignant ZZZ sans code Celcat" in e.bloquants


def test_wr100bu_sans_enseignant_n_est_pas_envoyee() -> None:
    """La règle WR100BU n'est pas facultative : sans VMA, rien ne part."""
    e = _entree([], cours="WR100BU", type_="TD", sid="WR100BU-S1-TD-1")
    assert not e.prete and not e.sans_enseignant


def test_la_charge_d_une_ptut_sans_enseignant_n_a_aucun_personnel(catalogues) -> None:  # noqa: F811
    e = _entree([])
    ids = ecriture.resoudre_ids(FaussePage(), e, categorie="")
    assert "staff_id" not in ids
    assert TYPE_PERSONNEL not in catalogues.types, "aucun enseignant ne doit être cherché"
    charge = ecriture.charge_utile(e, group_id=1661972, ids=ids, masque=MASQUE, event_id=0)
    assert charge["staff"] == []
    assert (charge["event_cat_id"], charge["modules"]) == (700, [{"module_id": 1590001}])
    assert charge["notes"] == "PTUT - WR101-S1-PTUT-1"
    verifier_charge_categorie(charge, type_seance_nom="PTUT", categorie_regle="Projet", sans_module=False)


@pytest.mark.parametrize("valeur", ["oui", "optionnel"])
def test_une_valeur_d_enseignant_inconnue_est_refusee(tmp_path, valeur: str) -> None:
    config = _ecrire_config(
        tmp_path,
        "regles_envoi:\n  types:\n    PTUT:\n      module: cours\n      categorie: Projet\n"
        f"      enseignant: {valeur}\n",
    )
    with pytest.raises(ConfigCelcatInvalide, match="`enseignant` doit valoir"):
        load_celcat_config(config)


@pytest.fixture
def ptut_sans_prof(db_isole):
    etat = get_state()
    ancien = snapshot_etat(etat)
    s = seance("ptut-sans-prof", groupe="but1-td-ab", code="WR101").model_copy(
        update={"session_type": SessionType.PTUT, "teacher_codes": []}
    )
    p = place(s, day=3, slot=0)
    client = monter_planning([(s, p)])
    yield client
    restaurer_etat(etat, ancien)


def test_le_plan_montre_la_ptut_sans_prof_a_creer(ptut_sans_prof) -> None:
    corps = ptut_sans_prof.get(f"/celcat/plan?semaines={SEMAINE}").json()
    entree = next(e for e in corps["entrees"] if e["session_id"] == "ptut-sans-prof")
    assert entree["action"] == "creer", entree
    assert "aucun enseignant" not in corps["motifs_blocage"]


def test_le_hook_et_le_robot_envoient_la_ptut_sans_prof(ptut_sans_prof, catalogues, monkeypatch) -> None:  # noqa: F811
    from cal_iut.celcat.file_attente import lister
    from cal_iut.celcat.logs import tous
    from cal_iut.celcat.nuit import drainer_file_immediate
    from cal_iut.celcat.ops import _executer
    from cal_iut.celcat.sync import journal

    envoyees: dict[str, dict] = {}

    def _enregistrer(page, charge, *, methode):
        envoyees[session_id_depuis_notes(charge["notes"])] = charge
        return 5151

    monkeypatch.setattr(ecriture, "enregistrer_evenement", _enregistrer)
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    activer_saisie(ptut_sans_prof)
    vider_file()
    _executer("ptut-sans-prof", "create")
    assert [j["session_id"] for j in lister()] == ["ptut-sans-prof"]
    poser_semaines_celcat()

    drainer_file_immediate(FaussePage(), production_autorisee=False)

    assert set(envoyees) == {"ptut-sans-prof"}, [l for l in tous() if l.get("kind") != "ok"]
    assert envoyees["ptut-sans-prof"]["staff"] == []
    assert envoyees["ptut-sans-prof"]["event_cat_id"] == 700
    assert str(journal()["ptut-sans-prof"]["event_id"]) == "5151"
    assert not [l for l in tous() if l.get("kind") == "blocked"]
