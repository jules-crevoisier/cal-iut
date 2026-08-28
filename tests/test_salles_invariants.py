"""Invariants de l'affectation des salles — un angle mort jusqu'ici.

`solver/rooms.py` fait 474 lignes de placement glouton avec règles, priorités,
continuité de salle et surcharges de duo. Aucun test ne vérifiait la propriété
la plus élémentaire : **une salle ne peut pas accueillir deux cours en même
temps**. Un tel défaut ne se voit ni dans le tableau de bord (qui contrôle la
capacité, pas l'occupation) ni à l'œil sur un planning de 2400 séances — mais il
envoie deux groupes dans la même pièce.

Les instances sont tirées au sort et minuscules, pour couvrir des FORMES d'entrée
(beaucoup de séances simultanées, groupes trop grands pour toute salle, blocs
longs, évaluations) plutôt que du volume.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from cal_iut.ingestion.config_loader import (
    load_groups,
    load_room_assignment_rules,
    load_rooms,
)
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.cpsat import PlacedSession
from cal_iut.solver.rooms import _headcount_for_groups, assign_rooms, parse_room_rules

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY

_reglage = settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])

GROUPES = ["but1-promo", "but1-td-ab", "but1-td-cd", "but1-tp-a", "but1-tp-b", "but1-tp-c"]
COURS = ["WR101", "WR110", "WR112"]


@st.composite
def planning_tire_au_sort(draw, max_seances=10):
    """Des placements déjà décidés (semaine/jour/créneau), à habiller de salles.

    Les placements produits sont VALIDES au sens du solveur : jamais deux
    séances d'une même cohorte, ni d'un même enseignant, au même créneau. Une
    première version ne le garantissait pas et « trouvait » des violations de
    capacité qui n'étaient que la conséquence d'une entrée impossible (trois CM
    simultanés pour la même promotion, se disputant les deux amphis). Un test de
    propriété n'a de valeur que si ses entrées sont atteignables.
    """
    n = draw(st.integers(min_value=1, max_value=max_seances))
    placements, sessions = [], {}
    occupes: set[tuple[str, int]] = set()  # (groupe ou prof, créneau absolu)
    for i in range(n):
        groupe = draw(st.sampled_from(GROUPES))
        type_ = SessionType.CM if groupe.endswith("promo") else draw(
            st.sampled_from([SessionType.TD, SessionType.TP])
        )
        duree = draw(st.sampled_from([1, 1, 1, 2]))
        semaine = draw(st.integers(min_value=0, max_value=2))
        jour = draw(st.integers(min_value=0, max_value=DAYS_PER_WEEK - 1))
        # Un bloc long doit tenir dans sa journée : c'est une pré-condition du
        # placement, pas quelque chose que l'affectation de salle doit rattraper.
        creneau = draw(st.integers(min_value=0, max_value=SLOTS_PER_DAY - duree))
        prof = draw(st.sampled_from(["T1", "T2"]))

        base = semaine * SLOTS_PER_WEEK + jour * SLOTS_PER_DAY + creneau
        # Le groupe `promo` recouvre TOUS les sous-groupes : un CM occupe donc
        # aussi les TD et TP de la promotion.
        ressources = {prof, groupe} | ({g for g in GROUPES} if groupe.endswith("promo") else {"but1-promo"})
        creneaux = {(r, t) for r in ressources for t in range(base, base + duree)}
        assume(not (creneaux & occupes))
        occupes |= creneaux

        sid = f"s{i}"
        code = draw(st.sampled_from(COURS))
        placements.append(PlacedSession(
            session_id=sid, week=semaine, day=jour, slot=creneau, course_code=code,
            group_ids=[groupe], teacher_codes=[prof],
        ))
        sessions[sid] = SessionToPlace(
            id=sid, course_code=code, course_name="T", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=type_,
            sequence_order=i + 1, is_eval=draw(st.booleans()), group_ids=[groupe],
            teacher_codes=[prof], duration_slots=duree,
        )
    return placements, sessions


def _affecter(placements, sessions):
    return assign_rooms(
        placements, sessions, load_rooms(CONFIG), load_groups(CONFIG),
        parse_room_rules(load_room_assignment_rules(CONFIG)),
    )


@given(planning_tire_au_sort())
@_reglage
def test_une_salle_n_accueille_jamais_deux_cours_en_meme_temps(donnees):
    """LA propriété fondamentale, jamais vérifiée jusqu'au 26/08/2026.

    Deux groupes envoyés dans la même pièce au même moment est le pire défaut
    possible côté usage — et il est invisible sur un planning imprimé.
    """
    placements, sessions = donnees
    resultats = _affecter(placements, sessions)

    occupation: dict[tuple[str, int], str] = {}
    for r in resultats:
        if not r.room_id:
            continue
        duree = max(1, sessions[r.session_id].duration_slots)
        base = r.week * SLOTS_PER_WEEK + r.day * SLOTS_PER_DAY + r.slot
        for t in range(base, base + duree):
            cle = (r.room_id, t)
            assert cle not in occupation, (
                f"salle {r.room_id} attribuée à {r.session_id} ET à "
                f"{occupation[cle]} au même créneau"
            )
            occupation[cle] = r.session_id


@given(planning_tire_au_sort())
@_reglage
def test_une_salle_attribuee_peut_toujours_accueillir_le_groupe(donnees):
    """La capacité doit être suffisante — sinon les étudiants restent debout."""
    placements, sessions = donnees
    groups = load_groups(CONFIG)
    salles = {r.id: r for r in load_rooms(CONFIG)}
    resultats = _affecter(placements, sessions)

    for r in resultats:
        if not r.room_id:
            continue
        salle = salles[r.room_id]
        effectif = _headcount_for_groups(r.group_ids, groups)
        assert effectif <= salle.capacity, (
            f"{r.session_id} : {effectif} étudiants dans {salle.label} "
            f"({salle.capacity} places)"
        )


@given(planning_tire_au_sort())
@_reglage
def test_l_affectation_conserve_exactement_les_placements(donnees):
    """Habiller de salles ne doit ni perdre, ni déplacer, ni dupliquer une séance."""
    placements, sessions = donnees
    resultats = _affecter(placements, sessions)

    assert len(resultats) == len(placements)
    avant = {(p.session_id, p.week, p.day, p.slot) for p in placements}
    apres = {(r.session_id, r.week, r.day, r.slot) for r in resultats}
    assert avant == apres, "l'affectation de salle a modifié un horaire"


@given(planning_tire_au_sort())
@_reglage
def test_l_affectation_est_deterministe(donnees):
    """Deux appels identiques doivent donner exactement les mêmes salles.

    Le placement est glouton, donc déterministe par construction — mais il
    dépend d'un tri (`_sort_key`). Un tri instable rendrait les régénérations
    partielles incohérentes avec le reste du semestre.
    """
    placements, sessions = donnees
    a = {r.session_id: r.room_id for r in _affecter(placements, sessions)}
    b = {r.session_id: r.room_id for r in _affecter(placements, sessions)}
    assert a == b


@given(planning_tire_au_sort())
@_reglage
def test_l_ordre_d_entree_ne_change_pas_le_resultat(donnees):
    """Métamorphique : mélanger la liste d'entrée ne doit rien changer.

    `assign_rooms` trie lui-même ses entrées. Si l'ordre d'arrivée influençait
    le résultat, deux exécutions du pipeline donneraient des salles différentes
    pour un planning identique — et le diff solveur/manuel deviendrait illisible.
    """
    placements, sessions = donnees
    assume(len(placements) > 1)
    a = {r.session_id: r.room_id for r in _affecter(placements, sessions)}
    b = {r.session_id: r.room_id for r in _affecter(list(reversed(placements)), sessions)}
    assert a == b, "l'ordre d'entrée influence l'affectation des salles"


@given(planning_tire_au_sort())
@_reglage
def test_toute_evaluation_va_dans_la_salle_d_examen(donnees):
    """Règle métier dure : `is_eval` implique A.018."""
    placements, sessions = donnees
    resultats = _affecter(placements, sessions)

    for r in resultats:
        if not sessions[r.session_id].is_eval or not r.room_label:
            continue
        assert r.room_label.startswith("A.018"), (
            f"évaluation {r.session_id} placée en {r.room_label}"
        )


@given(planning_tire_au_sort(max_seances=6))
@_reglage
def test_retirer_une_seance_ne_prive_pas_les_autres_de_salle(donnees):
    """Monotonie : moins de concurrence ne peut pas dégrader l'affectation.

    Une violation trahirait un état partagé mal réinitialisé entre deux appels —
    typiquement un dictionnaire d'occupation conservé d'une exécution à l'autre.
    """
    placements, sessions = donnees
    assume(len(placements) > 1)

    complet = _affecter(placements, sessions)
    sans_salle_complet = sum(1 for r in complet if not r.room_id)

    reduit = placements[:-1]
    partiel = _affecter(reduit, sessions)
    sans_salle_partiel = sum(1 for r in partiel if not r.room_id)

    assert sans_salle_partiel <= sans_salle_complet, (
        f"{len(reduit)} séances laissent {sans_salle_partiel} sans salle, "
        f"contre {sans_salle_complet} pour {len(placements)}"
    )


# ==========================================================================
# Régression : la salle de duo prise sans vérifier qu'elle est libre
# ==========================================================================


def test_une_salle_de_duo_deja_occupee_ne_provoque_pas_de_double_reservation():
    """BUG RÉEL du run `odd26` (trouvé le 26/08/2026 par exploration).

    La branche « salle de duo » de `assign_rooms` prenait sa salle sans
    consulter l'occupation. Une séance ordinaire traitée plus tôt pouvait déjà
    l'occuper : les deux se retrouvaient dans la même pièce au même créneau.
    Quatre cas dans le planning de production, tous sur les salles de duo
    (H.007, H.008, H.201, H.203).

    Le scénario reproduit ici est celui du run réel : un TP de WR109 (sans duo)
    et un TP de WR113 (duo RHU/AHA sur H.007-H.008) au même créneau.
    """
    from cal_iut.ingestion.config_loader import load_teacher_duos

    duos = load_teacher_duos(CONFIG)
    duo_wr113 = next(d for d in duos if "WR113" in d.course_codes)
    prof_duo = duo_wr113.teacher_codes[0]
    groupe_duo = f"but1-tp-{duo_wr113.group_overrides[prof_duo][0].lower()}"

    placements = [
        # Traité en premier : rafle une salle de duo par la voie ordinaire.
        PlacedSession(session_id="ordinaire", week=0, day=0, slot=0,
                      course_code="WR109", group_ids=["but1-tp-e"],
                      teacher_codes=["AUTRE"]),
        PlacedSession(session_id="duo", week=0, day=0, slot=0,
                      course_code="WR113", group_ids=[groupe_duo],
                      teacher_codes=[prof_duo]),
    ]
    sessions = {
        "ordinaire": SessionToPlace(
            id="ordinaire", course_code="WR109", course_name="T", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType.TP,
            sequence_order=1, group_ids=["but1-tp-e"], teacher_codes=["AUTRE"],
        ),
        "duo": SessionToPlace(
            id="duo", course_code="WR113", course_name="T", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType.TP,
            sequence_order=1, group_ids=[groupe_duo], teacher_codes=[prof_duo],
        ),
    }

    resultats = assign_rooms(
        placements, sessions, load_rooms(CONFIG), load_groups(CONFIG),
        parse_room_rules(load_room_assignment_rules(CONFIG)), duos,
    )
    salles = [r.room_id for r in resultats if r.room_id]
    assert len(salles) == len(set(salles)), (
        f"deux séances simultanées dans la même salle : {salles}"
    )


def test_une_seance_de_duo_garde_sa_salle_quand_elle_est_libre():
    """Le correctif ne doit pas priver les duos de leur salle sans raison."""
    from cal_iut.ingestion.config_loader import load_teacher_duos

    duos = load_teacher_duos(CONFIG)
    duo_wr113 = next(d for d in duos if "WR113" in d.course_codes)
    prof_duo = duo_wr113.teacher_codes[0]
    groupe_duo = f"but1-tp-{duo_wr113.group_overrides[prof_duo][0].lower()}"

    placements = [PlacedSession(
        session_id="duo", week=0, day=0, slot=0, course_code="WR113",
        group_ids=[groupe_duo], teacher_codes=[prof_duo],
    )]
    sessions = {"duo": SessionToPlace(
        id="duo", course_code="WR113", course_name="T", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=SessionType.TP,
        sequence_order=1, group_ids=[groupe_duo], teacher_codes=[prof_duo],
    )}
    resultats = assign_rooms(
        placements, sessions, load_rooms(CONFIG), load_groups(CONFIG),
        parse_room_rules(load_room_assignment_rules(CONFIG)), duos,
    )
    assert resultats[0].room_id in duo_wr113.rare_rooms, (
        f"le duo a perdu sa salle dédiée : {resultats[0].room_id}"
    )
