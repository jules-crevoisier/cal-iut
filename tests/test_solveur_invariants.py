"""Invariants et relations métamorphiques du solveur, sur instances tirées au sort.

Trois techniques de recherche de bugs, aucune n'encodant un défaut déjà connu :

1. **Vérificateur indépendant.** Toute solution rendue par le solveur est
   recontrôlée par un code qui ne partage rien avec lui. Un solveur qui viole sa
   propre contrainte est invisible autrement : les deux se trompent ensemble.
2. **Relations métamorphiques.** Des propriétés qui lient DEUX résolutions —
   « ajouter une contrainte dure ne peut pas rendre faisable ce qui ne l'était
   pas », « retirer des séances ne peut pas rendre infaisable ». Elles trouvent
   des bugs qu'aucune exécution isolée ne révèle.
3. **Instances aléatoires petites.** Volontairement minuscules (quelques
   séances, 2-3 semaines) : le but est de couvrir beaucoup de FORMES d'entrée,
   pas de mesurer la performance. Un contre-exemple à 6 séances se lit ;
   un contre-exemple à 2400 ne se lit pas.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from ortools.sat.python import cp_model

from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType, TeacherAvailability
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver import constraints as C
from cal_iut.solver.decomposed import assign_weeks, solve_week_detail
from cal_iut.solver.resources import add_student_and_teacher_no_overlap

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY

_reglage = settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

# Groupes réels du projet : utiliser les vrais évite de tester une cohorte
# fictive que `build_student_cohorts` ne saurait pas rattacher.
GROUPES_BUT1 = ["but1-promo", "but1-td-ab", "but1-tp-a", "but1-td-cd", "but1-tp-c"]


@st.composite
def petit_lot_de_seances(draw, max_seances=8):
    """Quelques séances d'un même parcours, avec ou sans ordre pédagogique."""
    n = draw(st.integers(min_value=1, max_value=max_seances))
    sessions = []
    for i in range(n):
        type_ = draw(st.sampled_from(["CM", "TD", "TP"]))
        if type_ == "CM":
            groupe = "but1-promo"
        elif type_ == "TD":
            groupe = draw(st.sampled_from(["but1-td-ab", "but1-td-cd"]))
        else:
            groupe = draw(st.sampled_from(["but1-tp-a", "but1-tp-c"]))
        sessions.append(SessionToPlace(
            id=f"s{i}",
            course_code=draw(st.sampled_from(["WRA", "WRB"])),
            course_name="T", semestre="S1", parcours="BUT1", annee="BUT1",
            session_type=SessionType(type_),
            sequence_order=i + 1,
            group_ids=[groupe],
            teacher_codes=[draw(st.sampled_from(["T1", "T2"]))],
            duration_slots=draw(st.sampled_from([1, 1, 1, 2])),
        ))
    return sessions


# ==========================================================================
# 1. Vérificateur indépendant : toute solution doit tenir la route
# ==========================================================================


def _placer_une_semaine(sessions, *, avail=None, budget=5.0):
    calendar = build_default_calendar_2026_2027()
    return solve_week_detail(
        sessions, 1,
        teacher_availability=avail, calendar=calendar,
        student_presences=None, groups=load_groups(CONFIG),
        blocked_days_by_parcours_week=None, duos=None,
        time_limit_seconds=budget, num_workers=2, random_seed=7,
    )


@given(petit_lot_de_seances())
@_reglage
def test_une_solution_ne_superpose_jamais_deux_seances_d_un_meme_etudiant(sessions):
    """Contrainte la plus fondamentale : un étudiant n'est pas à deux endroits.

    Recontrôlée ici SANS passer par CP-SAT — un intervalle par séance, comparé
    à la main. Si le solveur et son vérificateur partagent le même code, ils se
    trompent ensemble.
    """
    from cal_iut.solver.resources import build_student_cohorts

    statut, temps = _placer_une_semaine(sessions)
    assume(statut in ("OPTIMAL", "FEASIBLE"))

    cohortes = build_student_cohorts(load_groups(CONFIG))
    par_id = {s.id: s for s in sessions}
    for ids in cohortes.values():
        occupes: dict[int, str] = {}
        for sid, debut in temps.items():
            session = par_id[sid]
            if not ids.intersection(session.group_ids):
                continue
            for creneau in range(debut, debut + max(1, session.duration_slots)):
                assert creneau not in occupes, (
                    f"{sid} et {occupes[creneau]} se chevauchent au créneau {creneau} "
                    f"pour la même cohorte"
                )
                occupes[creneau] = sid


@given(petit_lot_de_seances())
@_reglage
def test_une_solution_ne_fait_jamais_dedoubler_un_enseignant(sessions):
    statut, temps = _placer_une_semaine(sessions)
    assume(statut in ("OPTIMAL", "FEASIBLE"))

    par_id = {s.id: s for s in sessions}
    par_prof: dict[str, dict[int, str]] = {}
    for sid, debut in temps.items():
        session = par_id[sid]
        for code in session.teacher_codes:
            occupes = par_prof.setdefault(code, {})
            for creneau in range(debut, debut + max(1, session.duration_slots)):
                assert creneau not in occupes, (
                    f"{code} donne {sid} et {occupes[creneau]} en même temps"
                )
                occupes[creneau] = sid


@given(petit_lot_de_seances())
@_reglage
def test_un_bloc_long_ne_deborde_jamais_sur_le_jour_suivant(sessions):
    """Un bloc de 3h doit tenir dans une demi-journée, pas chevaucher la nuit."""
    statut, temps = _placer_une_semaine(sessions)
    assume(statut in ("OPTIMAL", "FEASIBLE"))

    par_id = {s.id: s for s in sessions}
    for sid, debut in temps.items():
        duree = max(1, par_id[sid].duration_slots)
        assert (debut % SLOTS_PER_DAY) + duree <= SLOTS_PER_DAY, (
            f"{sid} démarre au créneau {debut % SLOTS_PER_DAY} et dure {duree}"
        )


@given(petit_lot_de_seances())
@_reglage
def test_aucune_seance_de_formation_initiale_le_jeudi_apres_midi(sessions):
    statut, temps = _placer_une_semaine(sessions)
    assume(statut in ("OPTIMAL", "FEASIBLE"))

    for sid, debut in temps.items():
        jour, creneau = debut // SLOTS_PER_DAY, debut % SLOTS_PER_DAY
        assert not (jour == 3 and creneau >= 3), (
            f"{sid} placée jeudi après-midi alors que le créneau est réservé aux PAC"
        )


@given(petit_lot_de_seances())
@_reglage
def test_l_ordre_pedagogique_est_tenu_dans_toute_solution(sessions):
    """Deux séances d'un même cours vues par un même étudiant restent ordonnées."""
    statut, temps = _placer_une_semaine(sessions)
    assume(statut in ("OPTIMAL", "FEASIBLE"))

    groups = load_groups(CONFIG)
    for avant, apres in C.cohort_sequence_pairs(sessions, groups):
        if avant in temps and apres in temps:
            assert temps[avant] < temps[apres], f"{avant} devrait précéder {apres}"


@given(petit_lot_de_seances())
@_reglage
def test_toutes_les_seances_soumises_sont_placees_ou_aucune(sessions):
    """Pas de solution partielle silencieuse : c'est tout ou rien.

    Une solution qui oublierait une séance sans le dire serait le pire des
    défauts — le planning aurait l'air complet.
    """
    statut, temps = _placer_une_semaine(sessions)
    if statut in ("OPTIMAL", "FEASIBLE"):
        assert set(temps) == {s.id for s in sessions}, (
            f"{len(sessions) - len(temps)} séance(s) manquante(s) dans une solution "
            f"annoncée {statut}"
        )


# ==========================================================================
# 2. Relations métamorphiques : ce qui doit lier DEUX résolutions
# ==========================================================================


@given(petit_lot_de_seances(max_seances=6))
@_reglage
def test_retirer_une_seance_ne_rend_jamais_infaisable(sessions):
    """Monotonie : un sous-ensemble d'une instance faisable reste faisable.

    Une violation signalerait une contrainte qui dépend de la PRÉSENCE d'une
    séance pour être satisfaite — typiquement une contrainte mal indexée, ou
    une paire d'ordre construite sur une séance absente.
    """
    statut, _ = _placer_une_semaine(sessions)
    assume(statut in ("OPTIMAL", "FEASIBLE"))
    assume(len(sessions) > 1)

    reduit = sessions[:-1]
    statut_reduit, _ = _placer_une_semaine(reduit)
    assert statut_reduit in ("OPTIMAL", "FEASIBLE", "NO_SESSIONS"), (
        f"{len(sessions)} séances faisables, mais {len(reduit)} donnent {statut_reduit}"
    )


@given(petit_lot_de_seances(max_seances=6))
@_reglage
def test_une_contrainte_supplementaire_ne_cree_jamais_de_solution(sessions):
    """Monotonie inverse : contraindre davantage ne peut pas débloquer.

    On compare la même instance avec et sans indisponibilités enseignant.
    Si l'ajout d'une contrainte rendait faisable un cas qui ne l'était pas, la
    contrainte serait posée à l'envers.
    """
    sans, _ = _placer_une_semaine(sessions)
    avail = [
        TeacherAvailability(teacher_code="T1", forbidden_slots=[(0, s) for s in range(6)]),
        TeacherAvailability(teacher_code="T2", forbidden_slots=[(4, s) for s in range(6)]),
    ]
    avec, _ = _placer_une_semaine(sessions, avail=avail)

    if avec in ("OPTIMAL", "FEASIBLE"):
        assert sans in ("OPTIMAL", "FEASIBLE"), (
            "instance faisable AVEC indisponibilités mais infaisable SANS : "
            "la contrainte est posée à l'envers"
        )


@given(petit_lot_de_seances(max_seances=6))
@_reglage
def test_les_indisponibilites_declarees_sont_toujours_respectees(sessions):
    avail = [
        TeacherAvailability(teacher_code="T1", forbidden_slots=[(0, s) for s in range(6)]),
        TeacherAvailability(teacher_code="T2", forbidden_slots=[(4, s) for s in range(6)]),
    ]
    statut, temps = _placer_une_semaine(sessions, avail=avail)
    assume(statut in ("OPTIMAL", "FEASIBLE"))

    interdits = {"T1": 0, "T2": 4}
    par_id = {s.id: s for s in sessions}
    for sid, debut in temps.items():
        jour = debut // SLOTS_PER_DAY
        for code in par_id[sid].teacher_codes:
            assert jour != interdits.get(code), (
                f"{sid} ({code}) placée le jour {jour}, déclaré indisponible"
            )


# ==========================================================================
# 3. Étage 2 : l'affectation en semaines
# ==========================================================================


@given(petit_lot_de_seances(max_seances=10), st.integers(min_value=2, max_value=5))
@_reglage
def test_l_affectation_semaine_place_toujours_toutes_les_seances(sessions, semaines):
    calendar = build_default_calendar_2026_2027()
    resultat = assign_weeks(
        sessions, load_groups(CONFIG), semaines, calendar=calendar, week_offset=1,
        time_limit_seconds=5, cohort_order_weight=0, strict_ordonnancement_weight=0,
        teacher_clustering_weight=0,
    )
    assume(resultat.status in ("OPTIMAL", "FEASIBLE"))
    assert set(resultat.week_by_session) == {s.id for s in sessions}


@given(petit_lot_de_seances(max_seances=10), st.integers(min_value=2, max_value=5))
@_reglage
def test_l_affectation_semaine_respecte_le_verrou_d_integration(sessions, semaines):
    """Aucune séance de formation initiale en semaine-index 0."""
    calendar = build_default_calendar_2026_2027()
    resultat = assign_weeks(
        sessions, load_groups(CONFIG), semaines, calendar=calendar, week_offset=1,
        time_limit_seconds=5, cohort_order_weight=0, strict_ordonnancement_weight=0,
        teacher_clustering_weight=0,
    )
    assume(resultat.status in ("OPTIMAL", "FEASIBLE"))
    assert all(w != 0 for w in resultat.week_by_session.values())


@given(petit_lot_de_seances(max_seances=10), st.integers(min_value=3, max_value=6))
@_reglage
def test_elargir_l_horizon_ne_rend_jamais_infaisable(sessions, semaines):
    """Métamorphique : plus de semaines ne peut pas nuire.

    Une violation signalerait une contrainte indexée sur le NOMBRE de semaines
    plutôt que sur la semaine elle-même — un défaut typique et difficile à voir.
    """
    calendar = build_default_calendar_2026_2027()

    def resoudre(n):
        return assign_weeks(
            sessions, load_groups(CONFIG), n, calendar=calendar, week_offset=1,
            time_limit_seconds=5, cohort_order_weight=0, strict_ordonnancement_weight=0,
            teacher_clustering_weight=0,
        ).status

    court = resoudre(semaines)
    assume(court in ("OPTIMAL", "FEASIBLE"))
    long = resoudre(semaines + 2)
    assert long in ("OPTIMAL", "FEASIBLE"), (
        f"{semaines} semaines : {court}, mais {semaines + 2} semaines : {long}"
    )


# ==========================================================================
# 4. Les contraintes prises isolément
# ==========================================================================


@given(petit_lot_de_seances())
@_reglage
def test_l_ordre_par_cohorte_est_toujours_satisfiable_seul(sessions):
    """Posée seule, la contrainte d'ordre ne doit jamais être contradictoire.

    Si elle l'était (un cycle), toute semaine la contenant deviendrait
    infaisable sans cause lisible.
    """
    model = cp_model.CpModel()
    debuts = {s.id: model.new_int_var(0, 1000, s.id) for s in sessions}
    C.add_cohort_sequence_constraints(model, sessions, debuts, load_groups(CONFIG))
    C.add_pedagogical_sequence_constraints(model, sessions, debuts, load_groups(CONFIG))
    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = 5
    assert solveur.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        "l'ordre pédagogique seul est contradictoire — il y a un cycle"
    )


@given(petit_lot_de_seances())
@_reglage
def test_la_version_molle_de_l_ordre_est_toujours_satisfiable(sessions):
    """Le repli mou doit, lui, TOUJOURS admettre une solution.

    C'est sa raison d'être : servir de filet quand la version dure coince.
    Un repli qui peut lui-même être infaisable ne protège de rien.
    """
    model = cp_model.CpModel()
    debuts = {s.id: model.new_int_var(0, 5, s.id) for s in sessions}  # domaine très serré
    penalites: list = []
    C.add_cohort_sequence_constraints(
        model, sessions, debuts, load_groups(CONFIG), soft_weight=10, penalties=penalites
    )
    if penalites:
        model.minimize(sum(penalites))
    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = 5
    assert solveur.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        "la version molle doit rester satisfiable même sur un domaine trop petit"
    )


@given(petit_lot_de_seances())
@_reglage
def test_le_nombre_de_contraintes_posees_egale_le_nombre_de_paires(sessions):
    """Cohérence entre ce que le compteur annonce et ce qui est réellement posé."""
    groups = load_groups(CONFIG)
    paires = C.cohort_sequence_pairs(sessions, groups)
    model = cp_model.CpModel()
    debuts = {s.id: model.new_int_var(0, 100, s.id) for s in sessions}
    posees = C.add_cohort_sequence_constraints(model, sessions, debuts, groups)
    assert posees == len(paires)


@given(petit_lot_de_seances())
@_reglage
def test_le_noOverlap_couvre_toutes_les_seances_soumises(sessions):
    """Aucune séance ne doit échapper aux contraintes d'occupation.

    Une séance oubliée du NoOverlap se superposerait librement aux autres —
    exactement le type de trou qu'un test sur données réelles ne montre que par
    hasard.
    """
    model = cp_model.CpModel()
    debuts = {s.id: model.new_int_var(0, SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    add_student_and_teacher_no_overlap(model, sessions, debuts, load_groups(CONFIG))
    # Forcer TOUTES les séances au même créneau : impossible dès qu'au moins
    # deux partagent une cohorte ou un enseignant.
    for var in debuts.values():
        model.add(var == 0)
    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = 5
    statut = solveur.solve(model)

    from cal_iut.solver.resources import build_student_cohorts

    cohortes = build_student_cohorts(load_groups(CONFIG))
    partage = any(
        len([s for s in sessions if ids.intersection(s.group_ids)]) > 1
        for ids in cohortes.values()
    ) or any(
        len([s for s in sessions if code in s.teacher_codes]) > 1
        for code in {c for s in sessions for c in s.teacher_codes}
    )
    if partage:
        assert statut == cp_model.INFEASIBLE, (
            "des séances partageant une cohorte ou un enseignant ont pu être "
            "empilées sur le même créneau"
        )
