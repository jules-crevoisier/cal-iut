"""Une séance AJOUTÉE À LA MAIN peut partir dans Celcat sans enseignant.

Signalement de Jules (20/10/2026) : quatre séances WS101
(`WS101-S1-TD-CUSTOM2/4-but1-td-ef/gh`) restaient « À créer », retentées
14 586 fois par le robot, motif « séance non saisissable, enseignant
manquant(s) : aucun enseignant ». « Il faut pouvoir poser sans prof avec
juste une salle. »

Une séance personnalisée (`-CUSTOM` dans l'id) sans enseignant part donc avec
`staff: []`, aucun personnel n'est cherché. Une séance de la MAQUETTE sans
enseignant reste bloquée : là, c'est un oubli à signaler.
"""

from __future__ import annotations

from test_celcat_regles_envoi_2026_10_01 import (  # type: ignore[import-not-found]
    _cfg,
    catalogues,  # noqa: F401 — fixture réutilisée
)
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.celcat import ecriture
from cal_iut.celcat.mapping import entree_pour_placement
from cal_iut.celcat.navigateur import TYPE_PERSONNEL
from cal_iut.celcat.nuit import motif_non_saisissable

MASQUE = "N" * 5 + "Y" + "N" * 48


def _entree(sid: str, profs: list[str]):
    return entree_pour_placement(
        _cfg(),
        session_id=sid,
        course_code="WR101",
        session_type="TD",
        week=2, day=1, slot=4, duration_slots=1,
        teacher_codes=profs,
        room_id="h101",
        groupe="TD AB",
        semestre="S1",
        lundi="2026-09-14",
    )


def test_une_seance_personnalisee_sans_enseignant_est_prete() -> None:
    e = _entree("WR101-S1-TD-CUSTOM2-but1-td-ab", [])
    assert e.prete, e.bloquants
    assert e.sans_enseignant and e.code_enseignant is None
    assert motif_non_saisissable(e) == ""


def test_une_seance_de_la_maquette_sans_enseignant_reste_bloquee() -> None:
    e = _entree("WR101-S1-TD-1", [])
    assert not e.prete and "aucun enseignant" in e.bloquants and not e.sans_enseignant
    assert "enseignant" in motif_non_saisissable(e)


def test_une_seance_personnalisee_avec_enseignant_ne_change_pas() -> None:
    e = _entree("WR101-S1-TD-CUSTOM2-but1-td-ab", ["MRI"])
    assert e.prete and not e.sans_enseignant and e.code_enseignant == "34044"


def test_la_charge_n_a_aucun_personnel_et_la_salle_est_gardee(catalogues) -> None:  # noqa: F811
    e = _entree("WR101-S1-TD-CUSTOM2-but1-td-ab", [])
    ids = ecriture.resoudre_ids(FaussePage(), e, categorie="[TD]")
    assert "staff_id" not in ids
    assert TYPE_PERSONNEL not in catalogues.types, "aucun enseignant ne doit être cherché"
    charge = ecriture.charge_utile(e, group_id=1661972, ids=ids, masque=MASQUE, event_id=0)
    assert charge["staff"] == []
    assert charge["rooms"] and charge["rooms"][0]["room_id"]
