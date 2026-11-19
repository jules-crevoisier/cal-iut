"""Une matière changée dans cal-iut doit REMPLACER l'ancienne dans Celcat.

Tâche 34, Kyllian Bresson, 06/11/2026 : la nouvelle matière était ajoutée
sans retirer l'ancienne, la séance portait deux matières. Même cause que les
salles et les enseignants : `save` FUSIONNE la liste `modules`.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_celcat_rpc import FaussePage

from cal_iut.celcat import matieres_doubles
from cal_iut.celcat.comparaison import comparer
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import fusionner_deltas, modifier_evenement
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT
from cal_iut.celcat.rpc import masquer_semaine

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
EVENT_ID = 1931666
ANCIENNE = {"id": 1581057, "module_id": 1581057, "name": "Ancienne", "unique_name": "WR101"}
NOUVELLE = {"module_id": 1590668, "name": "Nouvelle", "dept_id": 500001, "unique_name": "WR112"}


def _brut(modules: list[dict]) -> dict:
    bruts = json.loads(FIX.read_text(encoding="utf-8"))
    brut = dict(next(b for b in bruts if b["event_id"] == EVENT_ID))
    brut["modules"] = [dict(m) for m in modules]
    return brut


def _entree() -> EntreeCelcat:
    return EntreeCelcat(
        session_id="wr112-td-1", semaine=5, jour=2, heure_debut="09:30", heure_fin="11:00",
        code_enseignant="38002", salle="H.105", code_module="TSBZ2106", type_seance=None,
        type_seance_nom="CM", groupe="CM", semestre="S1", lundi="2026-09-07", course_code="WR112",
    )


def _ids(module_id: int | None = 1590668) -> dict:
    return {
        "module_id": module_id, "room_id": 104105, "staff_id": 7002,
        "event_cat_id": 430, "dept_id": 500001,
    }


def _fusionner(modules: list[dict], module_id: int | None = 1590668, page: FaussePage | None = None):
    page = FaussePage() if page is None else page
    brut = _brut(modules)
    page.reponses.setdefault("udlResources.load", [dict(NOUVELLE)])
    return fusionner_deltas(
        page, brut, entree=_entree(), ids=_ids(module_id), group_id=GROUP_ID,
        masque=masquer_semaine(longueur=54, indice=5),
    )["modules"]


def _retrait(mid: int) -> dict:
    return {"-event_id": EVENT_ID, "-module_id": mid, "_type_": "Module"}


def test_une_matiere_changee_retire_l_ancienne_et_pose_la_nouvelle() -> None:
    modules = _fusionner([ANCIENNE])

    assert _retrait(1581057) in modules
    poses = [m for m in modules if "module_id" in m]
    assert [m["module_id"] for m in poses] == [1590668]
    assert poses[0]["event_id"] == EVENT_ID


def test_un_doublon_deja_la_est_repare_en_gardant_la_bonne() -> None:
    bonne = {"id": 1590668, "module_id": 1590668, "name": "Nouvelle", "unique_name": "WR112"}

    assert _fusionner([ANCIENNE, bonne]) == [_retrait(1581057), bonne]


def test_une_matiere_inchangee_n_engendre_aucun_retrait() -> None:
    bonne = {"id": 1590668, "module_id": 1590668, "name": "Nouvelle", "unique_name": "WR112"}

    assert _fusionner([bonne]) == [bonne]


def test_sans_matiere_voulue_on_ne_retire_rien() -> None:
    assert _fusionner([ANCIENNE], module_id=None) == [ANCIENNE]


def test_le_retrait_part_dans_la_charge_envoyee_a_celcat() -> None:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [_brut([ANCIENNE])]
    page.reponses["udlResources.load"] = [dict(NOUVELLE)]
    page.reponses["udlTimetables.save"] = EVENT_ID

    modifier_evenement(
        page, _entree(), event_id=EVENT_ID, group_id=GROUP_ID, ids=_ids(),
        masque=masquer_semaine(longueur=54, indice=5), methode="udlTimetables.save",
        base=BASE_ENTRAINEMENT,
    )

    envois = [a for _js, a in page.journal if isinstance(a, dict) and a.get("methode") == "udlTimetables.save"]
    assert envois, page.journal
    charge = json.dumps(envois[-1], ensure_ascii=False)
    assert '"-module_id": 1581057' in charge
    assert '"module_id": 1590668' in charge


def test_la_lecture_rapporte_toutes_les_matieres() -> None:
    ev = evenement_depuis_rpc(_brut([ANCIENNE, NOUVELLE]), group_id=GROUP_ID, groupe_nom="G")

    assert ev.modules_codes == ["WR101", "WR112"]
    assert ev.module_code == "WR101"


def test_la_liste_ne_retient_que_les_seances_a_plusieurs_matieres() -> None:
    evenements = [
        {"event_id": 1, "groupe": "A", "modules_codes": ["WR101", "WR112"], "semaine": 3},
        {"event_id": 2, "groupe": "A", "modules_codes": ["WR101"], "semaine": 3},
        {"event_id": 3, "groupe": "A", "module": "WR101", "semaine": 3},
        {"event_id": 4, "groupe": "A", "modules_codes": ["WR101", "WR101"], "semaine": 3},
    ]
    lignes = matieres_doubles.lister(evenements)

    assert [l["event_id"] for l in lignes] == [1]
    assert "WR101 + WR112" in matieres_doubles.rapport(lignes)


class _Placement:
    session_id = "WR112-S1-TD-1-but1-td-ab"
    course_code = "WR112"
    week = 1
    day = 0
    slot = 0
    room_id = "h101"
    room_label = "H.101"
    group_ids = ["but1-td-ab"]


def _comparer(**extra) -> dict:
    p = _Placement()
    ev = {
        "event_id": 1, "groupe": "BUT MMI S1 TD AB", "jour": 0, "heure_debut": "08:00",
        "heure_fin": "09:30", "salle": "H.101", "categorie": "[TD]", "module": "WR112",
        "semaine": 3, **extra,
    }
    return comparer(
        placements=[p], evenements=[ev], semaine=1, semaine_celcat=3,
        groupes_celcat={p.session_id: "BUT MMI S1 TD AB"}, salles_celcat={"h101": "H.101"},
        types_seance={p.session_id: "TD"}, enseignants_celcat={p.session_id: "38002"},
    )[0]


def test_la_comparaison_signale_les_matieres_multiples() -> None:
    assert _comparer(modules_codes=["WR101", "WR112"])["ecarts"] == ["matières multiples"]
    assert _comparer(modules_codes=["WR112"])["statut"] == "identique"
    assert _comparer()["statut"] == "identique"
