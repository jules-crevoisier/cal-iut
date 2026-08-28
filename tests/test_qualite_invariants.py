"""Invariants du calcul de qualité et du périmètre des groupes.

`compute_quality` produit LA mesure de qualité du projet (le nombre de trous)
et alimente la boucle de réapprentissage des poids. Personne ne la vérifiait :
deux défauts y ont été trouvés le 26/08/2026.

1. **Les trous étaient surcomptés.** Seul le créneau de DÉPART d'une séance
   était enregistré : un bloc de 3h aux créneaux 3-4 suivi d'un cours au
   créneau 5 — donc sans la moindre interruption — comptait pour un trou.
2. **Les « journées isolées » ne comptaient rien.** La mesure agrégeait par
   JOUR DE LA SEMAINE sur tout le semestre : elle ne se déclenchait que si un
   groupe n'avait qu'une seule séance de toute l'année un lundi. Trois lundis
   à un seul cours renvoyaient 0.

Les propriétés ci-dessous énoncent la définition attendue, pour que ces deux
mesures ne puissent plus dériver en silence.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import SessionType
from cal_iut.models.group_scope import expand_group_filter, parent_td_for_tp, related_group_ids
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.cpsat import PlacedSession
from cal_iut.solver.quality import compute_quality

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
GROUPES = load_groups(CONFIG)

_reglage = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _session(sid: str, duree: int = 1) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code="X", course_name="T", semestre="S1", parcours="BUT1",
        annee="BUT1", session_type=SessionType.TP, sequence_order=1,
        group_ids=["g"], teacher_codes=["T"], duration_slots=duree,
    )


@st.composite
def journee_tiree_au_sort(draw):
    """Une journée d'un groupe : des séances non chevauchantes, avec durées."""
    creneaux: list[tuple[int, int]] = []  # (départ, durée)
    curseur = 0
    while curseur < SLOTS_PER_DAY:
        saut = draw(st.integers(min_value=0, max_value=2))
        curseur += saut
        if curseur >= SLOTS_PER_DAY:
            break
        duree = draw(st.sampled_from([1, 1, 2]))
        if curseur + duree > SLOTS_PER_DAY:
            break
        creneaux.append((curseur, duree))
        curseur += duree
    assume(creneaux)
    return creneaux


# ==========================================================================
# Les trous
# ==========================================================================


@given(journee_tiree_au_sort())
@_reglage
def test_le_nombre_de_trous_egale_les_creneaux_libres_entre_le_premier_et_le_dernier(creneaux):
    """Définition d'un trou : un créneau vide ENTRE deux cours du même jour.

    Calculée ici indépendamment, en posant à plat les créneaux occupés — la
    façon dont un étudiant le vivrait.
    """
    placements, sessions = [], {}
    occupes: set[int] = set()
    for i, (depart, duree) in enumerate(creneaux):
        sid = f"s{i}"
        placements.append(PlacedSession(
            session_id=sid, week=0, day=0, slot=depart, course_code="X",
            group_ids=["g"], teacher_codes=["T"],
        ))
        sessions[sid] = _session(sid, duree)
        occupes.update(range(depart, depart + duree))

    attendu = (max(occupes) - min(occupes) + 1) - len(occupes)
    assert compute_quality(placements, sessions).total_gaps == attendu


@given(journee_tiree_au_sort())
@_reglage
def test_une_journee_sans_interruption_n_a_jamais_de_trou(creneaux):
    """Des cours strictement enchaînés : zéro trou, quelles que soient les durées."""
    placements, sessions = [], {}
    curseur = 0
    for i, (_, duree) in enumerate(creneaux):
        if curseur + duree > SLOTS_PER_DAY:
            break
        sid = f"s{i}"
        placements.append(PlacedSession(
            session_id=sid, week=0, day=0, slot=curseur, course_code="X",
            group_ids=["g"], teacher_codes=["T"],
        ))
        sessions[sid] = _session(sid, duree)
        curseur += duree
    assume(len(placements) >= 2)
    assert compute_quality(placements, sessions).total_gaps == 0


@given(st.integers(min_value=1, max_value=4))
@_reglage
def test_une_seule_seance_dans_la_journee_ne_fait_jamais_de_trou(duree: int):
    assume(duree <= SLOTS_PER_DAY)
    placements = [PlacedSession(
        session_id="s", week=0, day=0, slot=0, course_code="X",
        group_ids=["g"], teacher_codes=["T"],
    )]
    assert compute_quality(placements, {"s": _session("s", duree)}).total_gaps == 0


@given(st.integers(min_value=0, max_value=3), st.integers(min_value=0, max_value=DAYS_PER_WEEK - 1))
@_reglage
def test_les_trous_ne_traversent_jamais_deux_journees(semaine: int, jour: int):
    """Un cours vendredi 17h et un lundi 8h ne créent aucun trou."""
    assume(jour + 1 < DAYS_PER_WEEK)
    placements = [
        PlacedSession(session_id="a", week=semaine, day=jour, slot=SLOTS_PER_DAY - 1,
                      course_code="X", group_ids=["g"], teacher_codes=["T"]),
        PlacedSession(session_id="b", week=semaine, day=jour + 1, slot=0,
                      course_code="X", group_ids=["g"], teacher_codes=["T"]),
    ]
    q = compute_quality(placements, {"a": _session("a"), "b": _session("b")})
    assert q.total_gaps == 0


# ==========================================================================
# Les journées isolées
# ==========================================================================


@given(st.integers(min_value=1, max_value=6))
@_reglage
def test_chaque_journee_a_cours_unique_compte_pour_une_journee_isolee(nb_jours: int):
    """Une journée avec un seul cours oblige à se déplacer pour 1h30."""
    placements, sessions = [], {}
    for i in range(nb_jours):
        sid = f"s{i}"
        placements.append(PlacedSession(
            session_id=sid, week=i, day=0, slot=0, course_code="X",
            group_ids=["g"], teacher_codes=["T"],
        ))
        sessions[sid] = _session(sid)
    assert compute_quality(placements, sessions).isolated_days == nb_jours


@given(st.integers(min_value=2, max_value=5))
@_reglage
def test_une_journee_bien_remplie_n_est_jamais_isolee(nb_cours: int):
    placements, sessions = [], {}
    for i in range(nb_cours):
        sid = f"s{i}"
        placements.append(PlacedSession(
            session_id=sid, week=0, day=0, slot=i, course_code="X",
            group_ids=["g"], teacher_codes=["T"],
        ))
        sessions[sid] = _session(sid)
    assert compute_quality(placements, sessions).isolated_days == 0


# ==========================================================================
# Périmètre des groupes (ce qu'un étudiant voit)
# ==========================================================================


@given(st.sampled_from([g.id for g in GROUPES if g.kind == "tp"]))
@_reglage
def test_chaque_tp_a_un_td_parent(tp_id: str):
    """Sans TD parent, la cohorte étudiante n'est pas construite et le solveur
    cesse de détecter les conflits CM/TD/TP de ce groupe."""
    tp = next(g for g in GROUPES if g.id == tp_id)
    parent = parent_td_for_tp(tp, GROUPES)
    assert parent is not None, f"{tp_id} n'a aucun TD parent"
    assert parent.parcours == tp.parcours


@given(st.sampled_from([g.id for g in GROUPES if g.kind in ("td", "tp")]))
@_reglage
def test_le_perimetre_d_un_groupe_se_contient_lui_meme(gid: str):
    perimetre = expand_group_filter(gid, GROUPES)
    assert gid in perimetre


@given(st.sampled_from([g.id for g in GROUPES if g.kind == "tp"]))
@_reglage
def test_le_perimetre_d_un_tp_contient_son_td_et_sa_promo(tp_id: str):
    """Un étudiant de TP suit aussi les TD de son groupe et les CM de sa promo."""
    tp = next(g for g in GROUPES if g.id == tp_id)
    perimetre = expand_group_filter(tp_id, GROUPES)
    parent = parent_td_for_tp(tp, GROUPES)
    assert parent.id in perimetre
    promo = next((g for g in GROUPES if g.parcours == tp.parcours and g.kind == "promo"), None)
    if promo:
        assert promo.id in perimetre


@given(st.sampled_from([g.id for g in GROUPES if g.kind == "tp"]))
@_reglage
def test_le_perimetre_ne_traverse_jamais_deux_parcours(tp_id: str):
    """Afficher le planning d'un groupe ne doit jamais y mêler une autre promo."""
    tp = next(g for g in GROUPES if g.id == tp_id)
    par_id = {g.id: g for g in GROUPES}
    for gid in expand_group_filter(tp_id, GROUPES):
        autre = par_id.get(gid)
        if autre is not None:
            assert autre.parcours == tp.parcours, (
                f"le périmètre de {tp_id} ({tp.parcours}) contient "
                f"{gid} ({autre.parcours})"
            )


@given(st.sampled_from([g.id for g in GROUPES if g.kind == "td"]))
@_reglage
def test_le_perimetre_d_un_td_contient_tous_ses_tp(td_id: str):
    from cal_iut.models.group_scope import resolve_tp_ids_for_td

    td = next(g for g in GROUPES if g.id == td_id)
    perimetre = expand_group_filter(td_id, GROUPES)
    for tp_id in resolve_tp_ids_for_td(td, GROUPES):
        assert tp_id in perimetre, f"{tp_id} manque au périmètre de {td_id}"


@given(st.sampled_from([g.id for g in GROUPES]))
@_reglage
def test_les_groupes_lies_sont_symetriques_entre_td_et_tp(gid: str):
    """Si A est lié à B, B doit être lié à A — sinon l'affichage diverge selon
    le point d'entrée choisi par l'utilisateur (l'API expose ces liens dans
    `/meta`, et le frontend s'en sert pour la vue Groupe)."""
    par_id = {g.id: g for g in GROUPES}
    groupe = par_id[gid]
    for autre_id in related_group_ids(groupe, GROUPES):
        autre = par_id.get(autre_id)
        if autre is None or autre_id == gid:
            continue
        retour = related_group_ids(autre, GROUPES)
        assert gid in retour, f"{gid} -> {autre_id} mais pas l'inverse"
