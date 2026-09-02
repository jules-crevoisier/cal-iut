"""Le glisser-déposer manuel doit refuser ce que le solveur refuserait.

Ce module est la porte par laquelle un humain peut casser un planning valide.
Deux défauts y ont été trouvés le 26/08/2026 en explorant du code jamais testé,
et tous deux répondaient « OK » à un déplacement qui superposait deux cours :

1. la DURÉE des séances était ignorée — un bloc de 3h n'était vu que sur son
   premier créneau, son second était invisible ;
2. la COHORTE étudiante était ignorée — un TD posé sur le créneau du CM de sa
   propre promotion ne levait aucun conflit, alors que ce sont les mêmes
   étudiants dans deux salles à la fois.

Les propriétés ci-dessous formulent la règle générale dont ces deux cas ne sont
que des instances : **la validation manuelle ne doit jamais être plus permissive
que les contraintes du solveur.**
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cal_iut.api.validation import validate_move
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.cpsat import PlacedSession

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
GROUPES = load_groups(CONFIG)

_reglage = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _session(sid: str, groupe: str, prof: str, duree: int = 1, type_=SessionType.TD):
    return SessionToPlace(
        id=sid, course_code="WRX", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=type_,
        sequence_order=1, group_ids=[groupe], teacher_codes=[prof],
        duration_slots=duree,
    )


# --------------------------------------------------------------------------
# Défaut 1 : la durée des séances
# --------------------------------------------------------------------------


@given(
    st.integers(min_value=0, max_value=SLOTS_PER_DAY - 2),
    st.integers(min_value=2, max_value=3),
)
@_reglage
def test_aucun_creneau_d_un_bloc_long_n_est_libre(depart: int, duree: int):
    """Un bloc de 3h occupe DEUX créneaux : les deux doivent être défendus.

    Avant correction, seul le créneau de départ l'était.
    """
    from hypothesis import assume

    assume(depart + duree <= SLOTS_PER_DAY)
    bloc = PlacedSession(
        session_id="bloc", week=0, day=0, slot=depart, course_code="WR110",
        group_ids=["but1-tp-a"], teacher_codes=["KBR"],
    )
    sessions = {
        "bloc": _session("bloc", "but1-tp-a", "KBR", duree, SessionType.TP),
        "autre": _session("autre", "but1-tp-a", "KBR"),
    }
    for cible in range(depart, depart + duree):
        resultat = validate_move(
            "autre", 0, 0, cible, [bloc], ["but1-tp-a"], ["KBR"],
            sessions_by_id=sessions, groups=GROUPES,
        )
        assert not resultat.valid, (
            f"créneau {cible} accepté alors que le bloc occupe "
            f"{depart}..{depart + duree - 1}"
        )


@given(st.integers(min_value=0, max_value=SLOTS_PER_DAY - 1), st.integers(min_value=2, max_value=3))
@_reglage
def test_un_bloc_long_ne_peut_pas_deborder_sur_le_jour_suivant(depart: int, duree: int):
    """Déposer un bloc de 3h à 17h ferait déborder sur le lendemain."""
    sessions = {"bloc": _session("bloc", "but1-tp-a", "KBR", duree, SessionType.TP)}
    resultat = validate_move(
        "bloc", 0, 0, depart, [], ["but1-tp-a"], ["KBR"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    if depart + duree > SLOTS_PER_DAY:
        assert not resultat.valid, f"bloc de {duree} accepté au créneau {depart}"
    else:
        assert resultat.valid, resultat.hard_conflicts


@given(st.integers(min_value=0, max_value=SLOTS_PER_DAY - 1))
@_reglage
def test_un_creneau_hors_du_bloc_reste_libre(depart_libre: int):
    """Le correctif ne doit pas rendre TOUTE la journée indisponible."""
    from hypothesis import assume

    bloc = PlacedSession(
        session_id="bloc", week=0, day=0, slot=0, course_code="WR110",
        group_ids=["but1-tp-a"], teacher_codes=["KBR"],
    )
    sessions = {
        "bloc": _session("bloc", "but1-tp-a", "KBR", 2, SessionType.TP),
        "autre": _session("autre", "but1-tp-a", "KBR"),
    }
    assume(depart_libre >= 2)  # hors des créneaux 0 et 1 occupés par le bloc
    resultat = validate_move(
        "autre", 0, 0, depart_libre, [bloc], ["but1-tp-a"], ["KBR"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert resultat.valid, resultat.hard_conflicts


# --------------------------------------------------------------------------
# Défaut 2 : la cohorte étudiante
# --------------------------------------------------------------------------


@given(st.sampled_from(["but1-td-ab", "but1-td-cd", "but1-tp-a", "but1-tp-h"]))
@_reglage
def test_un_cm_de_promo_bloque_tous_les_sous_groupes(groupe: str):
    """Le CM concerne toute la promotion : aucun de ses sous-groupes n'est libre."""
    cm = PlacedSession(
        session_id="cm", week=0, day=1, slot=0, course_code="WR101",
        group_ids=["but1-promo"], teacher_codes=["MRI"],
    )
    sessions = {
        "cm": _session("cm", "but1-promo", "MRI", type_=SessionType.CM),
        "td": _session("td", groupe, "AUTRE"),
    }
    resultat = validate_move(
        "td", 0, 1, 0, [cm], [groupe], ["AUTRE"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert not resultat.valid, f"{groupe} accepté sur le créneau du CM de sa promo"


@given(st.sampled_from(["but1-tp-a", "but1-tp-b"]))
@_reglage
def test_un_td_bloque_les_tp_qui_en_dependent(tp: str):
    """Les étudiants du TP A sont ceux du TD AB : les deux ne peuvent coexister."""
    td = PlacedSession(
        session_id="td", week=0, day=1, slot=0, course_code="WR101",
        group_ids=["but1-td-ab"], teacher_codes=["MRI"],
    )
    sessions = {
        "td": _session("td", "but1-td-ab", "MRI"),
        "tp": _session("tp", tp, "AUTRE", type_=SessionType.TP),
    }
    resultat = validate_move(
        "tp", 0, 1, 0, [td], [tp], ["AUTRE"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert not resultat.valid, f"{tp} accepté sur le créneau du TD dont il dépend"


def test_deux_cohortes_distinctes_ne_se_bloquent_pas():
    """Le correctif ne doit pas inventer des conflits entre groupes séparés.

    TP A dépend du TD AB, TP H du TD GH : deux cohortes sans intersection, qui
    doivent pouvoir travailler en parallèle. Sans cette contrepartie, la
    correction du défaut 2 rendrait tout l'emploi du temps infaisable.
    """
    autre = PlacedSession(
        session_id="autre", week=0, day=1, slot=0, course_code="WR101",
        group_ids=["but1-tp-h"], teacher_codes=["MRI"],
    )
    sessions = {
        "autre": _session("autre", "but1-tp-h", "MRI", type_=SessionType.TP),
        "tp": _session("tp", "but1-tp-a", "AUTRE", type_=SessionType.TP),
    }
    resultat = validate_move(
        "tp", 0, 1, 0, [autre], ["but1-tp-a"], ["AUTRE"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert resultat.valid, resultat.hard_conflicts


def test_deux_parcours_differents_ne_se_bloquent_pas():
    autre = PlacedSession(
        session_id="autre", week=0, day=1, slot=0, course_code="WR301D",
        group_ids=["but2-dev-fi-td-ab"], teacher_codes=["TPA"],
    )
    sessions = {
        "autre": _session("autre", "but2-dev-fi-td-ab", "TPA"),
        "td": _session("td", "but1-td-ab", "AUTRE"),
    }
    resultat = validate_move(
        "td", 0, 1, 0, [autre], ["but1-td-ab"], ["AUTRE"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert resultat.valid, resultat.hard_conflicts


def test_un_enseignant_deja_place_sur_un_autre_parcours_est_un_conflit():
    """L'indispo déclarée n'est pas le seul signal : un cours déjà posé aussi.

    Vue Promo ne peint pas le cours de l'autre parcours dans la colonne
    courante — le créneau a l'air libre. validate_move doit quand même
    nommer le cours déjà posé (Forcer reste possible côté API).
    """
    autre = PlacedSession(
        session_id="autre", week=0, day=1, slot=0, course_code="WR311D",
        group_ids=["but2-dev-fi-td-ab"], teacher_codes=["KBR"],
    )
    sessions = {
        "autre": _session("autre", "but2-dev-fi-td-ab", "KBR"),
        "td": _session("td", "but1-td-ab", "KBR"),
    }
    resultat = validate_move(
        "td", 0, 1, 0, [autre], ["but1-td-ab"], ["KBR"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert not resultat.valid
    assert any(
        "KBR" in c and "WR311D" in c and "déjà" in c
        for c in resultat.hard_conflicts
    )


# --------------------------------------------------------------------------
# Propriétés générales de la validation
# --------------------------------------------------------------------------


@given(
    st.integers(min_value=0, max_value=3),
    st.integers(min_value=0, max_value=DAYS_PER_WEEK - 1),
    st.integers(min_value=0, max_value=SLOTS_PER_DAY - 1),
)
@_reglage
def test_deplacer_une_seance_sur_sa_propre_place_reste_valide(semaine, jour, creneau):
    """Une séance ne peut pas entrer en conflit avec elle-même."""
    place = PlacedSession(
        session_id="moi", week=semaine, day=jour, slot=creneau, course_code="WRX",
        group_ids=["but1-tp-a"], teacher_codes=["KBR"],
    )
    sessions = {"moi": _session("moi", "but1-tp-a", "KBR")}
    resultat = validate_move(
        "moi", semaine, jour, creneau, [place], ["but1-tp-a"], ["KBR"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert resultat.valid, resultat.hard_conflicts


@given(
    st.integers(min_value=-3, max_value=DAYS_PER_WEEK + 3),
    st.integers(min_value=-3, max_value=SLOTS_PER_DAY + 3),
)
@_reglage
def test_un_creneau_hors_grille_est_toujours_refuse(jour: int, creneau: int):
    """Aucune entrée hors grille ne doit passer — y compris négative."""
    sessions = {"x": _session("x", "but1-tp-a", "KBR")}
    resultat = validate_move(
        "x", 0, jour, creneau, [], ["but1-tp-a"], ["KBR"],
        sessions_by_id=sessions, groups=GROUPES,
    )
    hors_grille = not (0 <= jour < DAYS_PER_WEEK) or not (0 <= creneau < SLOTS_PER_DAY)
    if hors_grille:
        assert not resultat.valid, f"jour={jour} créneau={creneau} accepté"


@given(st.integers(min_value=0, max_value=SLOTS_PER_DAY - 1))
@_reglage
def test_un_conflit_de_salle_est_toujours_signale(creneau: int):
    autre = PlacedSession(
        session_id="autre", week=0, day=0, slot=creneau, course_code="WRY",
        group_ids=["but2-dev-fi-td-ab"], teacher_codes=["AUTRE"],
    )
    autre.room_id = "h101"
    sessions = {
        "autre": _session("autre", "but2-dev-fi-td-ab", "AUTRE"),
        "moi": _session("moi", "but1-tp-a", "KBR"),
    }
    resultat = validate_move(
        "moi", 0, 0, creneau, [autre], ["but1-tp-a"], ["KBR"], room_id="h101",
        sessions_by_id=sessions, groups=GROUPES,
    )
    assert not resultat.valid
    assert any("salle" in c.lower() for c in resultat.hard_conflicts)
