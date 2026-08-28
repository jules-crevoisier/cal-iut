"""Les deux nouveaux termes objectif du 27/08/2026, en sens opposés :

- `add_cm_spread_penalties` : DÉCOURAGE la concentration de CM sur un même
  jour pour une promotion (retour utilisateur, en regardant le run réel :
  une journée BUT1 vue en production — 6 CM d'affilée, 5 matières
  différentes, aucun TD/TP entre les deux, « c'est trop chiant »).
- `add_course_grouping_penalties` : ENCOURAGE au contraire deux cours
  précis à se regrouper sur les mêmes journées (BUT3-DEV-FC, WRA507D +
  WSA501D — présence limitée à l'IUT, autant remplir la journée).

Vérifiés isolément, sur de petits modèles CP-SAT résolus à l'optimum — pas
besoin des données réelles pour prouver que le sens de chaque pénalité est
le bon.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from cal_iut.models.entities import Group, SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.objectives import add_cm_spread_penalties, add_course_grouping_penalties

SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY


def _promo() -> Group:
    return Group(id="but1-promo", label="Promo BUT1", parcours="BUT1", annee="BUT1", kind="promo", headcount=120)


def _cm(sid: str, ordre: int = 1) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=f"WR1{ordre:02d}", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.CM,
        sequence_order=1, group_ids=["but1-promo"], teacher_codes=["MRI"],
    )


def test_les_cm_se_repartissent_sur_plusieurs_jours_quand_c_est_possible():
    """4 CM, une seule contrainte : rester dans la semaine — sans la
    pénalité, CP-SAT n'a aucune raison de ne pas tous les coller le même
    jour ; avec elle, il doit les répartir."""
    sessions = [_cm(f"cm{i}") for i in range(4)]
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    # Une seule séance par créneau (sinon la solution triviale : toutes au
    # même horaire, ce qui n'est même pas physiquement un "même jour" au
    # sens utile).
    model.add_all_different(list(starts.values()))

    penalties = add_cm_spread_penalties(model, sessions, starts, [_promo()], weeks=1, weight=10, threshold=2)
    assert penalties, "aucune pénalité générée : le mécanisme ne s'est pas déclenché"
    model.minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 4
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    days = {solver.value(starts[s.id]) // SLOTS_PER_DAY for s in sessions}
    assert len(days) >= 2, f"les 4 CM sont restés concentrés sur {len(days)} jour(s)"


def test_zero_penalite_si_deja_bien_reparti():
    """Si le meilleur agencement possible respecte déjà le seuil, la
    pénalité optimale doit être nulle — pas de biais artificiel."""
    sessions = [_cm(f"cm{i}") for i in range(2)]
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    penalties = add_cm_spread_penalties(model, sessions, starts, [_promo()], weeks=1, weight=10, threshold=2)
    if penalties:
        model.minimize(sum(penalties))
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if penalties:
        assert solver.objective_value == 0


def test_seules_les_promos_sont_concernees_pas_les_td_tp():
    """Un TD n'est pas un CM : la pénalité ne doit jamais s'appliquer à un
    groupe qui n'a que des TD/TP."""
    td_group = Group(id="but1-td-ab", label="TD AB", parcours="BUT1", annee="BUT1", kind="td")
    session = SessionToPlace(
        id="td1", course_code="WR101", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=["MRI"],
    )
    model = cp_model.CpModel()
    starts = {"td1": model.new_int_var(0, SLOTS_PER_WEEK - 1, "td1")}
    penalties = add_cm_spread_penalties(model, [session], starts, [td_group], weeks=1, weight=10)
    assert penalties == []


def test_poids_nul_ne_genere_aucune_penalite():
    sessions = [_cm(f"cm{i}") for i in range(4)]
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    assert add_cm_spread_penalties(model, sessions, starts, [_promo()], weeks=1, weight=0) == []


# ==========================================================================
# add_course_grouping_penalties — le sens inverse
# ==========================================================================


def _seance(sid: str, code: str, groupe: str) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=code, course_name="T", semestre="S5",
        parcours="BUT3-DEV-FC", annee="BUT3", session_type=SessionType.TD,
        sequence_order=1, group_ids=[groupe], teacher_codes=["BTO"],
    )


def test_deux_cours_se_regroupent_sur_le_meme_jour_quand_c_est_possible():
    a = _seance("a", "WRA507D", "but3-dev-fc-td")
    b = _seance("b", "WSA501D", "but3-dev-fc-td")
    model = cp_model.CpModel()
    starts = {"a": model.new_int_var(0, SLOTS_PER_WEEK - 1, "a"), "b": model.new_int_var(0, SLOTS_PER_WEEK - 1, "b")}
    model.add(starts["a"] != starts["b"])
    penalties = add_course_grouping_penalties(model, [a, b], starts, [("WRA507D", "WSA501D")], weight=10)
    assert penalties
    model.minimize(sum(penalties))
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    day_a = solver.value(starts["a"]) // SLOTS_PER_DAY
    day_b = solver.value(starts["b"]) // SLOTS_PER_DAY
    assert day_a == day_b, "les deux cours n'ont pas été regroupés alors que rien ne les en empêchait"


def test_seules_les_paires_du_meme_groupe_sont_comparees():
    """Un groupe FC et un autre groupe FC différent ne doivent pas être tirés
    l'un vers l'autre — ce ne sont pas les mêmes étudiants."""
    a = _seance("a", "WRA507D", "groupe-x")
    b = _seance("b", "WSA501D", "groupe-y")
    model = cp_model.CpModel()
    starts = {"a": model.new_int_var(0, SLOTS_PER_WEEK - 1, "a"), "b": model.new_int_var(0, SLOTS_PER_WEEK - 1, "b")}
    penalties = add_course_grouping_penalties(model, [a, b], starts, [("WRA507D", "WSA501D")], weight=10)
    assert penalties == []


def test_poids_nul_ou_paires_vides_ne_genere_rien():
    a = _seance("a", "WRA507D", "g")
    b = _seance("b", "WSA501D", "g")
    model = cp_model.CpModel()
    starts = {"a": model.new_int_var(0, SLOTS_PER_WEEK - 1, "a"), "b": model.new_int_var(0, SLOTS_PER_WEEK - 1, "b")}
    assert add_course_grouping_penalties(model, [a, b], starts, [("WRA507D", "WSA501D")], weight=0) == []
    assert add_course_grouping_penalties(model, [a, b], starts, [], weight=10) == []
