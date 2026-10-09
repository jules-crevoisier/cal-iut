"""Un enseignant remplacé dans cal-iut doit REMPLACER l'ancien dans Celcat.

Tâche 19, Kyllian Bresson, 09/10/2026 :

    « Lorsqu'un enseignant est remplacé dans cal-iut-mmi, l'outil ajoute le
      nouvel enseignant dans Celcat sans supprimer l'ancien. La séance se
      retrouve donc avec deux enseignants, alors qu'un seul doit être
      affecté. » — constaté sur WR112, WR117 et WR311D.

LA CAUSE est celle des salles du 08/09/2026 : `save` FUSIONNE la liste
`staff`, il ne la remplace pas. `fusionner_deltas` posait le nouvel
enseignant seul, sans retirer l'ancien. Le remède est le même : retrait
explicite par la convention du signe moins.

Et pour retrouver les séances déjà abîmées, la comparaison signale
désormais « enseignants multiples » et « enseignant » : le bouton
« Corriger » de la semaine les envoie en modification, et la modification
retire l'enseignant en trop.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_celcat_rpc import FaussePage

from cal_iut.celcat.comparaison import comparer
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import fusionner_deltas, modifier_evenement
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT
from cal_iut.celcat.rpc import masquer_semaine

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
EVENT_ID = 1931666
ANCIEN = {"id": 7001, "staff_id": 7001, "name": "RIGUET Marine", "unique_name": "38001"}
NOUVEAU = {"staff_id": 7002, "name": "SANSON Jean", "dept_id": 500001, "unique_name": "38002"}


def _brut(staff: list[dict]) -> dict:
    bruts = json.loads(FIX.read_text(encoding="utf-8"))
    brut = dict(next(b for b in bruts if b["event_id"] == EVENT_ID))
    brut["staff"] = [dict(s) for s in staff]
    return brut


def _entree() -> EntreeCelcat:
    return EntreeCelcat(
        session_id="wr112-td-1", semaine=5, jour=2, heure_debut="09:30", heure_fin="11:00",
        code_enseignant="38002", salle="H.105", code_module="TSBZ2106", type_seance=None,
        type_seance_nom="CM", groupe="CM", semestre="S1", lundi="2026-09-07", course_code="WR112",
    )


def _ids(staff_id: int | None) -> dict:
    return {
        "module_id": 601106, "room_id": 104105, "staff_id": staff_id,
        "event_cat_id": 430, "dept_id": 500001,
    }


def _fusionner(staff: list[dict], staff_id: int | None, page: FaussePage | None = None) -> list[dict]:
    page = page or FaussePage()
    fusionne = fusionner_deltas(
        page, _brut(staff), entree=_entree(), ids=_ids(staff_id), group_id=GROUP_ID,
        masque=masquer_semaine(longueur=54, indice=5),
    )
    return fusionne["staff"]


def _retrait(staff_id: int) -> dict:
    return {"-event_id": EVENT_ID, "-staff_id": staff_id, "_type_": "Staff"}


# --------------------------------------------------------------------------
# 1. La modification retire l'ancien enseignant.
# --------------------------------------------------------------------------


def test_un_enseignant_remplace_retire_l_ancien_et_pose_le_nouveau() -> None:
    """LE cas de la tâche 19."""
    page = FaussePage()
    page.reponses["udlResources.load"] = [dict(NOUVEAU)]

    staff = _fusionner([ANCIEN], 7002, page)

    assert _retrait(7001) in staff
    poses = [s for s in staff if "staff_id" in s]
    assert [s["staff_id"] for s in poses] == [7002]
    assert poses[0]["name"] == "SANSON Jean"
    assert poses[0]["event_id"] == EVENT_ID


def test_un_doublon_deja_la_est_repare_en_gardant_le_bon() -> None:
    """Les séances abîmées par l'ancien comportement : le bon enseignant est
    là, l'ancien aussi. On retire l'ancien, on garde le bon tel qu'il a été
    chargé — sans recharger quoi que ce soit."""
    nouveau_charge = {"id": 7002, "staff_id": 7002, "name": "SANSON Jean", "unique_name": "38002"}

    staff = _fusionner([ANCIEN, nouveau_charge], 7002)

    assert staff == [_retrait(7001), nouveau_charge]


def test_un_enseignant_inchange_n_engendre_aucun_retrait() -> None:
    """Le cas courant (on ne touche qu'à l'horaire, à la salle…) : rien ne
    doit changer côté enseignant."""
    staff = _fusionner([ANCIEN], 7001)

    assert staff == [ANCIEN]


def test_sans_enseignant_voulu_on_ne_retire_rien() -> None:
    staff = _fusionner([ANCIEN], None)

    assert staff == [ANCIEN]


def test_un_meme_ancien_rendu_deux_fois_ne_part_qu_en_un_retrait() -> None:
    page = FaussePage()
    page.reponses["udlResources.load"] = [dict(NOUVEAU)]

    staff = _fusionner([ANCIEN, dict(ANCIEN)], 7002, page)

    assert staff.count(_retrait(7001)) == 1


def test_le_retrait_part_bien_dans_la_charge_envoyee_a_celcat() -> None:
    """De bout en bout, à travers `preparer_evenement` : le retrait garde
    ses clés préfixées et son type."""
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [_brut([ANCIEN])]
    page.reponses["udlResources.load"] = [dict(NOUVEAU)]
    page.reponses["udlTimetables.save"] = EVENT_ID

    modifier_evenement(
        page, _entree(), event_id=EVENT_ID, group_id=GROUP_ID, ids=_ids(7002),
        masque=masquer_semaine(longueur=54, indice=5), methode="udlTimetables.save",
        base=BASE_ENTRAINEMENT,
    )

    envois = [arg for _js, arg in page.journal if isinstance(arg, dict) and arg.get("methode") == "udlTimetables.save"]
    assert envois, page.journal
    charge = json.dumps(envois[-1], ensure_ascii=False)
    assert '"-staff_id": 7001' in charge
    assert '"-event_id": 1931666' in charge
    assert '"staff_id": 7002' in charge


# --------------------------------------------------------------------------
# 2. La lecture rapporte TOUS les enseignants.
# --------------------------------------------------------------------------


def test_la_lecture_rapporte_tous_les_enseignants_et_leurs_codes() -> None:
    ev = evenement_depuis_rpc(
        {"event_id": 1, "staff": [ANCIEN, {"staff_id": 7002, "name": "SANSON Jean", "unique_name": "38002"}]},
        group_id=1, groupe_nom="BUT MMI S1 TD AB",
    )

    assert ev.enseignants == ["RIGUET Marine", "SANSON Jean"]
    assert ev.enseignants_codes == ["38001", "38002"]
    assert ev.enseignant == "RIGUET Marine"


# --------------------------------------------------------------------------
# 3. La comparaison les signale.
# --------------------------------------------------------------------------


class _Placement:
    session_id = "WR112-S1-TD-1-but1-td-ab"
    course_code = "WR112"
    week = 1
    day = 0
    slot = 0
    room_id = "h101"
    room_label = "H.101"
    group_ids = ["but1-td-ab"]


def _comparer(attendu: str | None = "38002", **extra) -> list[str]:
    placement = _Placement()
    ev = {
        "event_id": 1, "groupe": "BUT MMI S1 TD AB", "jour": 0, "heure_debut": "08:00",
        "heure_fin": "09:30", "salle": "H.101", "categorie": "[TD]", "module": "WR112",
        "semaine": 3, **extra,
    }
    lignes = comparer(
        placements=[placement], evenements=[ev], semaine=1, semaine_celcat=3,
        groupes_celcat={placement.session_id: "BUT MMI S1 TD AB"},
        salles_celcat={"h101": "H.101"}, types_seance={placement.session_id: "TD"},
        enseignants_celcat={placement.session_id: attendu} if attendu else None,
    )
    assert len(lignes) == 1
    return lignes[0]


def test_deux_enseignants_font_un_ecart_et_l_ecran_dit_lesquels() -> None:
    ligne = _comparer(enseignants=["RIGUET Marine", "SANSON Jean"], enseignants_codes=["38001", "38002"])

    assert ligne["statut"] == "ecart"
    assert ligne["ecarts"] == ["enseignants multiples"]
    assert ligne["celcat"]["enseignants"] == ["RIGUET Marine", "SANSON Jean"]


def test_un_ancien_enseignant_seul_fait_un_ecart_d_enseignant() -> None:
    ligne = _comparer(enseignants=["RIGUET Marine"], enseignants_codes=["38001"])

    assert ligne["ecarts"] == ["enseignant"]


def test_le_bon_enseignant_seul_est_identique() -> None:
    ligne = _comparer(enseignants=["SANSON Jean"], enseignants_codes=["38002"])

    assert ligne["statut"] == "identique"


def test_un_releve_ancien_sans_enseignants_ne_signale_rien() -> None:
    assert _comparer()["statut"] == "identique"


def test_sans_enseignant_attendu_seul_le_doublon_compte() -> None:
    assert _comparer(None, enseignants=["X"], enseignants_codes=["1"])["statut"] == "identique"
    assert _comparer(None, enseignants=["X", "Y"], enseignants_codes=["1", "2"])["ecarts"] == ["enseignants multiples"]
