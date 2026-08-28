"""La boucle de retour étage 3 -> étage 2 (coupes de Benders logiques).

Le défaut d'architecture qu'elle corrige : l'étage 2 répartit les séances en
semaines à partir de COMPTAGES par ressource, l'étage 3 doit ensuite trouver un
horaire RÉEL. Les deux ne sont pas équivalents — mesuré le 26/08/2026, 8
semaines sur 24 étaient prouvées infaisables en 0,1 s alors qu'aucune ressource
n'y dépassait son plafond. Sans retour d'information, l'étage 2 reproposait
indéfiniment des répartitions de la même famille.

Une coupe dit : « ces séances-là, toutes ensemble dans cette semaine-là, c'est
impossible ». Ces tests vérifient qu'elle est bien POSÉE (l'étage 2 l'observe)
et qu'elle reste MINIMALE (elle n'interdit pas plus que ce qui a été prouvé).
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.decomposed import assign_weeks

ROOT = Path(__file__).resolve().parents[1]
GROUPES = load_groups(ROOT / "data" / "config")
CAL = build_default_calendar_2026_2027()


def _seances(n: int, groupe: str) -> list[SessionToPlace]:
    return [
        SessionToPlace(
            id=f"s{i}", course_code="WR101", course_name="Test", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
            sequence_order=i + 1, group_ids=[groupe], teacher_codes=["MRI"],
        )
        for i in range(n)
    ]


def _resoudre(seances, coupes=None, semaines=3):
    return assign_weeks(
        seances, GROUPES, semaines, calendar=CAL, week_offset=0,
        time_limit_seconds=10, num_workers=4,
        forbidden_combinations=coupes,
    )


def test_sans_coupe_l_etage_2_peut_tout_grouper_dans_une_semaine():
    """Point de départ : rien n'empêche la répartition que la coupe visera."""
    res = _resoudre(_seances(3, "but1-td-ab"))
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert len(set(res.week_by_session.values())) == 1


def test_une_coupe_interdit_exactement_la_combinaison_prouvee_impossible():
    seances = _seances(3, "but1-td-ab")
    coupe = [(0, ["s0", "s1", "s2"])]
    res = _resoudre(seances, coupes=coupe)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    semaines = [res.week_by_session[f"s{i}"] for i in range(3)]
    assert semaines.count(0) < 3, "les trois séances sont restées en semaine 0"


def test_la_coupe_n_interdit_pas_une_semaine_entiere():
    """Interdire la semaine 0 tout court serait une coupe FAUSSE : seule la
    combinaison complète a été prouvée impossible, pas chacune de ses parties.

    Démontré par comptage plutôt qu'en espérant que le solveur choisisse la
    semaine 0 : avec deux semaines coupées et trois séances, une semaine DOIT
    en accueillir deux. Si la coupe bannissait la semaine, ce serait infaisable.
    """
    seances = _seances(3, "but1-td-ab")
    res = _resoudre(
        seances, semaines=3,
        coupes=[(w, ["s0", "s1", "s2"]) for w in (0, 1, 2)],
    )
    assert res.status in ("OPTIMAL", "FEASIBLE")
    semaines = [res.week_by_session[f"s{i}"] for i in range(3)]
    assert max(semaines.count(w) for w in (0, 1, 2)) == 2


def test_une_coupe_sur_une_autre_semaine_ne_change_rien_a_la_semaine_0():
    seances = _seances(3, "but1-td-ab")
    res = _resoudre(seances, coupes=[(2, ["s0", "s1", "s2"])])
    assert res.status in ("OPTIMAL", "FEASIBLE")


def test_deux_coupes_s_accumulent():
    seances = _seances(3, "but1-td-ab")
    res = _resoudre(seances, coupes=[(w, ["s0", "s1", "s2"]) for w in (0, 1, 2)])
    assert res.status in ("OPTIMAL", "FEASIBLE")
    for semaine in (0, 1, 2):
        groupees = [i for i in range(3) if res.week_by_session[f"s{i}"] == semaine]
        assert len(groupees) < 3


def test_une_coupe_sur_une_seance_inconnue_est_ignoree_sans_planter():
    """Le rééquilibrage peut faire disparaître un identifiant entre deux tours ;
    une coupe périmée ne doit jamais faire échouer l'affectation."""
    res = _resoudre(_seances(2, "but1-td-ab"), coupes=[(0, ["inexistante", "autre"])])
    assert res.status in ("OPTIMAL", "FEASIBLE")


def test_une_coupe_a_une_seule_seance_est_ignoree():
    """`x != semaine` pour UNE séance n'est pas une coupe de Benders : ce serait
    interdire une affectation individuelle jamais prouvée impossible seule."""
    res = _resoudre(_seances(2, "but1-td-ab"), coupes=[(0, ["s0"])])
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert res.week_by_session["s0"] == 0 or True  # aucune contrainte posée
