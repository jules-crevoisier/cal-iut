"""Invariants du calendrier — la couche dont tout le reste dépend.

`AcademicCalendar` traduit dans les deux sens entre une DATE réelle et un
couple (semaine, jour) interne. Toute la chaîne s'appuie dessus : les
indisponibilités enseignant sont datées, les fenêtres SAE aussi, les événements
fixes aussi. Une erreur d'un jour ici décale silencieusement des contraintes
entières, et rien ne le signalerait — le planning aurait l'air normal.

C'est exactement le profil d'un module à tester par propriétés plutôt que par
exemples : la règle « aller-retour » se formule en une ligne et couvre toutes
les dates de l'année, y compris les bords (premier lundi, dernier vendredi,
semaines de vacances, week-ends, jours fériés).
"""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from cal_iut.calendar.academic import (
    DEPARTMENT_WEEK_ANCHOR,
    build_default_calendar_2026_2027,
    default_horizon_weeks,
    department_week_number,
    semester_week_offset,
)
from cal_iut.models.timetable import DAYS_PER_WEEK

CAL = build_default_calendar_2026_2027()
_reglage = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])

indices_semaine = st.integers(min_value=0, max_value=max(0, len(CAL.teaching_mondays) - 1))
jours = st.integers(min_value=0, max_value=DAYS_PER_WEEK - 1)
dates_annee = st.dates(min_value=date(2026, 8, 1), max_value=date(2027, 8, 31))


# ==========================================================================
# Aller-retour date <-> (semaine, jour)
# ==========================================================================


@given(indices_semaine, jours)
@_reglage
def test_semaine_jour_vers_date_puis_retour_est_l_identite(semaine: int, jour: int):
    """LA propriété fondamentale. Un décalage d'un jour ici fausserait
    silencieusement toutes les contraintes datées du projet."""
    d = CAL.week_day_to_date(semaine, jour)
    assert d is not None
    assert CAL.date_to_week_day_any(d) == (semaine, jour)


@given(dates_annee)
@_reglage
def test_date_vers_semaine_jour_puis_retour_est_l_identite(d: date):
    mappe = CAL.date_to_week_day_any(d)
    assume(mappe is not None)
    semaine, jour = mappe
    assert CAL.week_day_to_date(semaine, jour) == d


@given(indices_semaine, jours)
@_reglage
def test_le_jour_rendu_correspond_au_vrai_jour_de_la_semaine(semaine: int, jour: int):
    """`day=0` doit être un lundi, `day=4` un vendredi — pas juste un index."""
    d = CAL.week_day_to_date(semaine, jour)
    assert d is not None
    assert d.weekday() == jour


@given(dates_annee)
@_reglage
def test_un_week_end_n_est_jamais_placable(d: date):
    assume(d.weekday() > 4)
    assert CAL.date_to_week_day_any(d) is None
    assert CAL.date_to_week_day(d) is None


@given(dates_annee)
@_reglage
def test_un_jour_ferie_ou_ferme_n_est_jamais_enseignable(d: date):
    """`date_to_week_day` exclut les jours bloqués ; `_any` les localise quand même."""
    if d in CAL.holidays or d in CAL.blocked_dates:
        assert CAL.date_to_week_day(d) is None


@given(dates_annee)
@_reglage
def test_les_deux_lectures_ne_different_que_sur_les_jours_bloques(d: date):
    strict = CAL.date_to_week_day(d)
    souple = CAL.date_to_week_day_any(d)
    if strict is not None:
        assert strict == souple, "un jour enseignable doit se localiser à l'identique"
        assert d not in CAL.holidays and d not in CAL.blocked_dates


@given(st.integers(min_value=-5, max_value=len(CAL.teaching_mondays) + 5),
       st.integers(min_value=-3, max_value=DAYS_PER_WEEK + 3))
@_reglage
def test_un_index_hors_bornes_rend_none_sans_lever(semaine: int, jour: int):
    """Les bords doivent rendre `None`, jamais une date fausse ni une exception."""
    resultat = CAL.week_day_to_date(semaine, jour)
    valide = 0 <= semaine < len(CAL.teaching_mondays) and 0 <= jour < DAYS_PER_WEEK
    assert (resultat is not None) == valide


# ==========================================================================
# Numérotation « semaine département »
# ==========================================================================


@given(st.integers(min_value=-60, max_value=60))
@_reglage
def test_la_numerotation_departement_avance_d_une_unite_par_semaine(decalage: int):
    lundi = DEPARTMENT_WEEK_ANCHOR + timedelta(weeks=decalage)
    assert department_week_number(lundi) == decalage + 1


@given(indices_semaine)
@_reglage
def test_les_numeros_de_semaine_sont_strictement_croissants(semaine: int):
    assume(semaine + 1 < len(CAL.teaching_mondays))
    a = department_week_number(CAL.teaching_mondays[semaine])
    b = department_week_number(CAL.teaching_mondays[semaine + 1])
    assert b > a, f"semaine {semaine} numérotée {a}, la suivante {b}"


@given(indices_semaine)
@_reglage
def test_l_etiquette_de_semaine_porte_bien_son_numero(semaine: int):
    """L'étiquette affichée doit correspondre au numéro réel — c'est elle que
    lisent les enseignants dans l'export HTML."""
    libelle = CAL.department_week_label(semaine)
    assert libelle is not None
    attendu = department_week_number(CAL.teaching_mondays[semaine])
    assert libelle.startswith(f"Semaine {attendu} "), libelle


# ==========================================================================
# Structure de la liste des semaines enseignables
# ==========================================================================


def test_les_lundis_enseignables_sont_ordonnes_et_uniques():
    lundis = CAL.teaching_mondays
    assert lundis == sorted(lundis), "les semaines ne sont pas dans l'ordre"
    assert len(lundis) == len(set(lundis)), "une semaine apparaît deux fois"


def test_chaque_semaine_enseignable_est_bien_un_lundi():
    for m in CAL.teaching_mondays:
        assert m.weekday() == 0, f"{m} n'est pas un lundi"


def test_aucune_semaine_enseignable_n_est_entierement_fermee():
    """Une semaine sans aucun jour ouvrable ne devrait pas figurer dans la
    liste : l'étage 2 du solveur pourrait y affecter des séances que l'étage 3
    ne pourra jamais placer."""
    vides = []
    for i, lundi in enumerate(CAL.teaching_mondays):
        ouverts = [
            lundi + timedelta(days=j)
            for j in range(DAYS_PER_WEEK)
            if (lundi + timedelta(days=j)) not in CAL.blocked_dates
            and (lundi + timedelta(days=j)) not in CAL.holidays
        ]
        if not ouverts:
            vides.append((i, lundi))
    assert not vides, f"semaines enseignables sans aucun jour ouvrable : {vides}"


@given(st.sampled_from(["S1", "S2", "S3", "S4", "S5", "S6"]))
@_reglage
def test_l_offset_de_semestre_reste_dans_les_bornes(semestre: str):
    offset = semester_week_offset(CAL, semestre)
    assert 0 <= offset < len(CAL.teaching_mondays), f"{semestre} -> offset {offset}"


@given(st.sampled_from(["S1", "S3", "S5"]))
@_reglage
def test_l_horizon_par_defaut_tient_dans_le_calendrier(semestre: str):
    horizon = default_horizon_weeks(CAL, semestre)
    offset = semester_week_offset(CAL, semestre)
    assert horizon > 0
    assert offset + horizon <= len(CAL.teaching_mondays) + 1, (
        f"{semestre} : offset {offset} + horizon {horizon} dépasse "
        f"{len(CAL.teaching_mondays)} semaines"
    )


# ==========================================================================
# Créneaux bloqués
# ==========================================================================


@given(st.integers(min_value=1, max_value=len(CAL.teaching_mondays)))
@_reglage
def test_les_creneaux_bloques_correspondent_a_de_vrais_jours_fermes(semaines: int):
    """Chaque créneau déclaré bloqué doit pointer sur un jour réellement fermé."""
    from cal_iut.models.timetable import SLOTS_PER_DAY

    bloques = CAL.blocked_time_indices(semaines)
    slots_par_semaine = DAYS_PER_WEEK * SLOTS_PER_DAY
    for index in sorted(bloques)[:200]:  # échantillon : la liste peut être longue
        semaine = index // slots_par_semaine
        jour = (index % slots_par_semaine) // SLOTS_PER_DAY
        d = CAL.week_day_to_date(semaine, jour)
        assert d is None or d in CAL.holidays or d in CAL.blocked_dates, (
            f"créneau {index} ({d}) déclaré bloqué alors que le jour est ouvert"
        )


@given(st.integers(min_value=1, max_value=len(CAL.teaching_mondays)))
@_reglage
def test_tout_jour_ferme_a_bien_tous_ses_creneaux_bloques(semaines: int):
    """La réciproque : un jour fermé ne doit pas laisser passer un créneau."""
    from cal_iut.models.timetable import SLOTS_PER_DAY

    bloques = CAL.blocked_time_indices(semaines)
    slots_par_semaine = DAYS_PER_WEEK * SLOTS_PER_DAY
    for semaine in range(min(semaines, len(CAL.teaching_mondays))):
        for jour in range(DAYS_PER_WEEK):
            d = CAL.week_day_to_date(semaine, jour)
            if d is None or (d not in CAL.holidays and d not in CAL.blocked_dates):
                continue
            base = semaine * slots_par_semaine + jour * SLOTS_PER_DAY
            manquants = [t for t in range(base, base + SLOTS_PER_DAY) if t not in bloques]
            assert not manquants, f"{d} est fermé mais {len(manquants)} créneau(x) restent libres"
