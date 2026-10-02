"""Occupations hors MMI : un VRAI relevé Celcat, rejoué sans réseau.

Signalement d'origine : docs/A-TESTER-SUR-CELCAT.md, étape 5 du prompt
« Occupations hors MMI » — « enregistre un relevé réel anonymisé et réduit
en fixture de test, et ajoute un test qui le rejoue avec PageSimulee ».

`tests/fixtures/celcat_occupations_releve.json` vient du relevé du
02/10/2026 sur `URCA_2026` (lecture seule) : H.018, les deux amphis partagés
et Anthony Froli, 22 évènements, deux ou trois par cas. Le personnel des
autres départements y est remplacé (« ENSEIGNANT 01 »…), les auteurs des
saisies retirés. Les autres tests d'occupations reposent sur des évènements
inventés ; celui-ci fige la FORME réelle des réponses de Celcat.

Jules Crevoisier, 02/10/2026, sur la réservation de l'amphi : « on a fait
des réservations sur toutes les semaines pour que si d'autres parcours
veulent réserver l'amphi, elles doivent demander. Mais il faut qu'en aucun
cas ça nous bloque, nous. »
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from cal_iut.celcat import occupations as occ

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "celcat_occupations_releve.json"
DU, AU = date(2026, 9, 28), date(2027, 7, 31)


@pytest.fixture
def releve() -> tuple[occ.ResultatReleve, occ.PageSimulee]:
    page = occ.PageSimulee.depuis_fichier(FIXTURE)
    cfg = occ.ConfigOccupations(pause_s=0)
    ressources = occ.ressources_depuis_config(
        cfg, ROOT / "data" / "config", filtre=["H018", "amphi1_tc_gea", "amphi2_gmp_geii", "AFR"]
    )
    res = occ.relever(page, cfg, ressources, ctx=occ.ContexteNous(), du=DU, au=AU, journal=lambda _l: None)
    return res, page


def test_les_quatre_ressources_sont_trouvees_par_leur_identifiant_reel(releve) -> None:
    res, _ = releve
    assert {(r.code, r.celcat_id, r.trouvee) for r in res.ressources} == {
        ("h018", 1604428, True), ("amphi1_tc_gea", 1604507, True),
        ("amphi2_gmp_geii", 1604505, True), ("AFR", 1610999, True),
    }
    assert res.erreurs == []


def test_la_reservation_de_l_amphi_par_mmi_ne_nous_bloque_pas(releve) -> None:
    res, _ = releve
    assert res.ignores["réservation du département MMI"] == 2
    h018 = [e for e in res.evenements if e["code"] == "h018"]
    assert not [e for e in h018 if e["departement"] == "MMI"]
    # Sans la règle, deux réservations de 22 semaines : 44 journées de 8h00 à 20h00.
    sans = occ.relever(
        occ.PageSimulee.depuis_fichier(FIXTURE), occ.ConfigOccupations(pause_s=0, reservations_mmi_ignorees=False),
        [occ.RessourceSurveillee("salle", "h018", "Amphi 3 MMI")], ctx=occ.ContexteNous(), du=DU, au=AU,
        journal=lambda _l: None,
    )
    bloquantes = [e for e in sans.evenements if e["departement"] == "MMI"]
    assert len(bloquantes) == 44 and {(e["debut"], e["fin"]) for e in bloquantes} == {("08:00", "20:00")}


def test_ce_qui_reste_sur_h018_vient_bien_d_ailleurs(releve) -> None:
    res, _ = releve
    h018 = [e for e in res.evenements if e["code"] == "h018"]
    assert Counter(e["departement"] for e in h018) == {"GEA": 5, "CJ": 2, "iut Troyes T00": 1, "": 1}
    # Heures réelles, département écrit « T_ CJ T41 » dans Celcat.
    assert [(e["date"], e["debut"], e["fin"], e["categorie"], e["departement_nom"]) for e in h018 if e["departement"] == "CJ"] == [
        ("2027-01-11", "08:00", "12:00", "[TD]", "T_ CJ T41"),
        ("2027-01-12", "08:00", "12:00", "[TD]", "T_ CJ T41"),
    ]


def test_un_enseignant_programme_dans_un_autre_departement(releve) -> None:
    res, _ = releve
    afr = [e for e in res.evenements if e["code"] == "AFR"]
    assert Counter(e["departement"] for e in afr) == {"TC": 5, "GEA": 1}
    assert ("2026-10-21", "10:00", "12:00", "[TD]") in {(e["date"], e["debut"], e["fin"], e["categorie"]) for e in afr}


def test_nos_evenements_et_les_jours_feries_sont_ecartes(releve) -> None:
    res, _ = releve
    assert res.ignores == {
        "jour férié": 2, "réservation du département MMI": 2,
        "écrit par cal-iut (notes)": 3, "cours d'un groupe MMI": 1,
    }
    assert all(not str(g).startswith("BUT MMI") for e in res.evenements for g in e["groupes"])


def test_seules_des_methodes_de_lecture_sont_appelees(releve) -> None:
    _, page = releve
    assert Counter(m for m, _ in page.appels) == {"udlResources.load": 3, "udlTimetables.load": 2}
    assert [list(p[0]) for m, p in page.appels if m == "udlTimetables.load"] == [["RoomIDs"], ["StaffIDs"]]


@pytest.mark.parametrize("variante", [
    {"evCatName": "Réservation", "event_cat_id": 470},
    {"staff": [{"staff_id": 9_000_001, "name": "ENSEIGNANT 01", "unique_name": "90001"}]},
    {"notes": "réservation amphi H MMI - S2"},
])
def test_une_reservation_mmi_ne_bloque_pas_meme_saisie_autrement(variante) -> None:
    """« En aucun cas ça nous bloque » : la réservation reste reconnue si
    quelqu'un lui pose une catégorie ou un responsable. C'est sa remarque
    (« Réservation… ») et son département qui la désignent."""
    import json

    reservation = next(e for e in json.loads(FIXTURE.read_text(encoding="utf-8"))["evenements"]
                       if e["notes"] == "Réservation Amphi H MMI")
    brut = {**reservation, **variante}
    assert occ.motif_a_nous(brut, occ.ContexteNous(), occ.ConfigOccupations()) == "réservation du département MMI"


def test_une_activite_mmi_saisie_a_la_main_reste_une_occupation() -> None:
    """Une conférence MMI dans l'amphi l'occupe vraiment : elle compte."""
    import json

    reservation = next(e for e in json.loads(FIXTURE.read_text(encoding="utf-8"))["evenements"]
                       if e["notes"] == "Réservation Amphi H MMI")
    conference = {**reservation, "evCatName": "Conférence", "event_cat_id": 458, "notes": "Journée portes ouvertes"}
    assert occ.motif_a_nous(conference, occ.ContexteNous(), occ.ConfigOccupations()) is None
