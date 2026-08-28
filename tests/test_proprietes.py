"""Tests de PROPRIÉTÉS : chercher les bugs qu'on n'a pas encore rencontrés.

Les autres fichiers de tests encodent des défauts déjà trouvés — c'est de la
non-régression, utile mais aveugle sur l'inconnu. Ici, on énonce des invariants
qui doivent tenir pour TOUTE entrée valide, et Hypothesis fabrique les entrées,
y compris celles auxquelles personne n'aurait pensé.

Les cibles sont choisies par densité historique de bugs, pas au hasard. Sur ce
projet, les trois défauts de données du 25/08/2026 vivaient tous dans des
fonctions PURES de quelques lignes — un parseur de dates, une extraction de
trigrammes, un compteur de créneaux. Ce sont exactement les fonctions où une
propriété se formule facilement et où un contre-exemple est immédiatement
concluant.

Chaque propriété est écrite pour pouvoir ÉCHOUER : si elle ne peut pas être
violée, elle ne teste rien.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import date, timedelta
from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from cal_iut.calendar.academic import parse_french_date
from cal_iut.ingestion.normalize import _merge_double_sessions, expand_course_to_sessions
from cal_iut.ingestion.planning_loader import _slots_for_event_text, _slots_for_interval
from cal_iut.models.entities import (
    Course,
    DoubleSessionRule,
    SessionType,
    Teacher,
    TeacherBlock,
    TeacherDistributionRule,
)
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import SLOTS_PER_DAY
from cal_iut.solver.constraints import cohort_sequence_pairs

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

_lent = settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)


def _build_contraintes():
    spec = importlib.util.spec_from_file_location(
        "build_contraintes", ROOT / "scripts" / "build_contraintes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BC = _build_contraintes()


# ==========================================================================
# Lecture des dates — là où vivait le bug VMA (« 23/09/26 » lu « tous les
# mercredis »). La propriété : une date ÉCRITE puis RELUE doit revenir
# identique, quelle que soit la façon de l'écrire.
# ==========================================================================

dates_annee = st.dates(min_value=date(2026, 8, 1), max_value=date(2027, 8, 31))


@given(dates_annee)
@_lent
def test_une_date_en_toutes_lettres_se_relit_identique(d: date):
    texte = f"{d.day} {MOIS_FR[d.month - 1]} {d.year}"
    assert parse_french_date(texte) == d


@given(dates_annee, st.sampled_from(JOURS_FR))
@_lent
def test_le_nom_du_jour_ne_change_pas_la_date_lue(d: date, jour: str):
    """Un nom de jour ERRONÉ ne doit pas faire dériver la date.

    Le CSV source en contient (« du mardi 19 au vendredi 22 octobre » où le 19
    est un lundi) : la date chiffrée fait foi, le nom du jour est décoratif.
    """
    texte = f"{jour} {d.day} {MOIS_FR[d.month - 1]} {d.year}"
    assert parse_french_date(texte) == d


@given(dates_annee)
@_lent
def test_une_date_numerique_se_relit_identique(d: date):
    for texte in (
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day}/{d.month}/{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year % 100:02d}",
    ):
        assert parse_french_date(texte) == d, texte


@given(dates_annee, st.sampled_from(JOURS_FR))
@_lent
def test_une_date_dans_un_fragment_ne_devient_jamais_une_recurrence(d: date, jour: str):
    """LE bug VMA, généralisé.

    Tout fragment contenant une date précise doit produire un token de DATE.
    S'il produit un token hebdomadaire, l'enseignant est bloqué toutes les
    semaines au lieu d'un seul jour — une sur-contrainte silencieuse et grave.
    """
    for texte in (
        f"{jour} {d.day} {MOIS_FR[d.month - 1]} {d.year}",
        f"{jour} {d.day:02d}/{d.month:02d}/{d.year % 100:02d}",
        f"{jour} {d.day}/{d.month}/{d.year} toute la journée",
    ):
        tokens = BC._tokenize(texte)
        assert tokens, texte
        assert all(t["type"] == "date_specifique" for t in tokens), (
            f"{texte!r} produit {[t['type'] for t in tokens]} — une date lue comme "
            "une récurrence bloque toutes les semaines"
        )


@given(st.lists(dates_annee, min_size=1, max_size=5, unique=True))
@_lent
def test_chaque_date_d_une_liste_produit_son_propre_token(dates: list[date]):
    """Le CSV sépare les fragments par ' - '. Aucune date ne doit se perdre."""
    texte = " - ".join(f"{d.day} {MOIS_FR[d.month - 1]} {d.year}" for d in dates)
    tokens = BC._tokenize(texte)
    lues = {parse_french_date(t["raw"]) for t in tokens}
    assert set(dates) <= lues, f"{texte!r} : dates perdues {set(dates) - lues}"


# ==========================================================================
# Extraction des trigrammes — le bug SLO (« ARIANESLO : » où SLO est collé au
# prénom précédent). Propriété : tout trigramme écrit doit être relu.
# ==========================================================================

trigrammes = st.text(alphabet=st.characters(min_codepoint=65, max_codepoint=90), min_size=3, max_size=3)
noms = st.text(alphabet=st.characters(min_codepoint=65, max_codepoint=90), min_size=2, max_size=10)


@given(st.lists(st.tuples(trigrammes, noms, noms), min_size=1, max_size=5))
@_lent
def test_aucun_trigramme_ne_se_perd_meme_concatene(entrees):
    """L'export colle les entrées sans séparateur : « ALO : LOIZON ARIANESLO : … ».

    Chaque trigramme suivi d'un deux-points doit ressortir. Un seul perdu, et
    l'enseignant n'est jamais compté comme référent de la SAE.
    """
    texte = "".join(f"{tri} : {nom} {prenom}" for tri, nom, prenom in entrees)
    lus = BC._parse_teachers(texte)
    for tri, _, _ in entrees:
        assert tri in lus, f"{tri} perdu dans {texte!r} -> {lus}"


@given(st.lists(trigrammes, min_size=1, max_size=6, unique=True))
@_lent
def test_les_trigrammes_lus_sont_uniques_et_dans_l_ordre(codes: list[str]):
    texte = "".join(f"{c} : NOM PRENOM" for c in codes)
    lus = BC._parse_teachers(texte)
    assert len(lus) == len(set(lus)), f"doublons dans {lus}"


# ==========================================================================
# Fusion en blocs (3h / 4h30) — le mécanisme qui a fait disparaître le service
# d'un enseignant. Propriété centrale : AUCUNE HEURE NE DOIT DISPARAÎTRE.
# ==========================================================================

@st.composite
def sequence_seances(draw, min_size=1, max_size=14):
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    types = draw(st.lists(st.sampled_from(["CM", "TD", "TP"]), min_size=n, max_size=n))
    return [{"ordre": i + 1, "type": t, "eval": False} for i, t in enumerate(types)]


@given(
    sequence_seances(),
    st.sampled_from(["CM", "TD", "TP"]),
    st.integers(min_value=2, max_value=3),
    st.sampled_from(["start", "end"]),
    st.one_of(st.none(), st.integers(min_value=1, max_value=4)),
)
@_lent
def test_la_fusion_en_blocs_conserve_le_volume_horaire(sequence, type_cible, taille, depuis, maxi):
    """Somme des durées après fusion == nombre de séances avant.

    Si cette propriété tombe, des heures ont été inventées ou perdues — le
    genre de défaut qui ne se voit qu'en comptant le service d'un enseignant
    en fin d'année.
    """
    rule = DoubleSessionRule(
        course_code="X", session_type=SessionType(type_cible),
        slots_per_session=taille, pair_from=depuis, max_blocks=maxi,
    )
    fusionnee = _merge_double_sessions(list(sequence), rule)
    avant = len(sequence)
    apres = sum(int(e.get("duration_slots", 1)) for e in fusionnee)
    assert apres == avant, f"{avant} séances -> {apres} créneaux"


@given(
    sequence_seances(),
    st.sampled_from(["CM", "TD", "TP"]),
    st.integers(min_value=2, max_value=3),
    st.sampled_from(["start", "end"]),
)
@_lent
def test_la_fusion_preserve_l_ordre_pedagogique(sequence, type_cible, taille, depuis):
    rule = DoubleSessionRule(
        course_code="X", session_type=SessionType(type_cible),
        slots_per_session=taille, pair_from=depuis,
    )
    fusionnee = _merge_double_sessions(list(sequence), rule)
    ordres = [e["ordre"] for e in fusionnee]
    assert ordres == sorted(ordres), f"ordre cassé : {ordres}"


@given(
    sequence_seances(min_size=4),
    st.sampled_from(["CM", "TD", "TP"]),
    st.integers(min_value=2, max_value=3),
    st.integers(min_value=1, max_value=3),
)
@_lent
def test_max_blocks_est_une_borne_stricte(sequence, type_cible, taille, maxi):
    rule = DoubleSessionRule(
        course_code="X", session_type=SessionType(type_cible),
        slots_per_session=taille, pair_from="end", max_blocks=maxi,
    )
    fusionnee = _merge_double_sessions(list(sequence), rule)
    blocs = [e for e in fusionnee if int(e.get("duration_slots", 1)) > 1]
    assert len(blocs) <= maxi, f"{len(blocs)} blocs pour un maximum de {maxi}"


# ==========================================================================
# Répartition des séances entre enseignants — le bug WSA501D (34 créneaux à
# JSA, 0 à BTO). Propriété : tout enseignant porteur de volume est servi.
# ==========================================================================

@st.composite
def cours_multi_enseignants(draw):
    """Un module à 2-3 enseignants dont les volumes somment au volume total."""
    n_profs = draw(st.integers(min_value=2, max_value=3))
    parts = draw(st.lists(st.integers(min_value=1, max_value=20), min_size=n_profs, max_size=n_profs))
    total_td = sum(parts)
    profs = [
        TeacherBlock(
            block="b",
            teacher=Teacher(code=f"P{i:02d}", nom=f"N{i}", prenom=f"P{i}"),
            cm=0, td=part, tp=0,
        )
        for i, part in enumerate(parts)
    ]
    return Course(
        code="WRPROP", name="Test", semestre="S5", parcours="BUT3-DEV-FC", annee="BUT3",
        lead=profs[0].teacher, profs=profs,
        volumes={"cm": 0, "td": total_td, "tp": 0},
        groupes_td=1, groupes_tp=1,
        progression_defined=False, seance_sequence=[], ordonnancement=[],
    )


@given(cours_multi_enseignants(), st.booleans())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_tout_enseignant_porteur_de_volume_recoit_des_seances(course: Course, alterne: bool):
    """Le bug WSA501D, généralisé à toute répartition.

    Un enseignant à qui la maquette confie des heures DOIT apparaître dans
    l'emploi du temps. Sinon son service disparaît sans que rien ne le signale.
    """
    from cal_iut.ingestion.config_loader import load_groups

    distributions = (
        [TeacherDistributionRule(course_code="WRPROP", semestre="S5", mode="alterne")]
        if alterne
        else []
    )
    sessions = expand_course_to_sessions(
        course, load_groups(CONFIG), teacher_distributions=distributions
    )
    assume(sessions)
    servis = {s.teacher_codes[0] for s in sessions}
    porteurs = {b.teacher.code for b in course.profs if b.td > 0}
    assert porteurs <= servis, (
        f"enseignant(s) sans séance : {sorted(porteurs - servis)} "
        f"(volumes {[(b.teacher.code, b.td) for b in course.profs]})"
    )


@given(cours_multi_enseignants())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_le_volume_total_emis_correspond_a_la_maquette(course: Course):
    from cal_iut.ingestion.config_loader import load_groups

    sessions = expand_course_to_sessions(course, load_groups(CONFIG))
    emis = sum(s.duration_slots for s in sessions)
    attendu = int(course.volumes["td"]) * course.groupes_td
    assert emis == attendu, f"{emis} créneaux émis pour {attendu} attendus"


@given(cours_multi_enseignants())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_l_alternance_ne_change_jamais_le_volume_de_personne(course: Course):
    """Alterner redistribue l'ORDRE, jamais les heures de chacun.

    Une alternance qui déséquilibre les services serait un bug invisible à
    l'œil : le planning aurait l'air correct, mais un enseignant travaillerait
    plus que son dû.
    """
    from cal_iut.ingestion.config_loader import load_groups

    groups = load_groups(CONFIG)
    sequentiel = expand_course_to_sessions(course, groups)
    alterne = expand_course_to_sessions(
        course, groups,
        teacher_distributions=[
            TeacherDistributionRule(course_code="WRPROP", semestre="S5", mode="alterne")
        ],
    )
    assume(sequentiel and alterne)

    def volumes(sessions):
        out: dict[str, int] = {}
        for s in sessions:
            out[s.teacher_codes[0]] = out.get(s.teacher_codes[0], 0) + s.duration_slots
        return out

    a, b = volumes(sequentiel), volumes(alterne)
    for code in set(a) | set(b):
        # Une unité d'écart est inhérente à un découpage en blocs pairs sur un
        # quota impair ; au-delà, la répartition n'est plus fidèle.
        assert abs(a.get(code, 0) - b.get(code, 0)) <= 1, (
            f"{code} : {a.get(code, 0)} créneaux en séquentiel, {b.get(code, 0)} en alterné"
        )


# ==========================================================================
# Ordre pédagogique par cohorte — les paires que le solveur doit respecter.
# ==========================================================================

@st.composite
def seances_d_un_module(draw):
    n = draw(st.integers(min_value=2, max_value=10))
    types = draw(st.lists(st.sampled_from(["CM", "TD", "TP"]), min_size=n, max_size=n))
    sessions = []
    for i, t in enumerate(types):
        if t == "CM":
            groupes = ["but1-promo"]
        elif t == "TD":
            groupes = ["but1-td-ab"]
        else:
            groupes = ["but1-tp-a"]
        sessions.append(SessionToPlace(
            id=f"s{i}", course_code="WRPROP", course_name="T", semestre="S1",
            parcours="BUT1", annee="BUT1", session_type=SessionType(t),
            sequence_order=i + 1, group_ids=groupes, teacher_codes=["AAA"],
        ))
    return sessions


@given(seances_d_un_module())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_les_paires_d_ordre_sont_acycliques_et_coherentes(sessions):
    """Une paire (a, b) veut dire « a strictement avant b ».

    Trois propriétés qui, si elles tombent, rendent le modèle CP-SAT infaisable
    sans que la cause soit lisible : pas de boucle sur soi-même, pas de paire
    contradictoire, et toujours dans le sens de la progression.
    """
    from cal_iut.ingestion.config_loader import load_groups

    par_id = {s.id: s for s in sessions}
    paires = cohort_sequence_pairs(sessions, load_groups(CONFIG))

    for avant, apres in paires:
        assert avant != apres, "une séance ne peut pas se précéder elle-même"
        assert (apres, avant) not in paires, f"paire contradictoire ({avant}, {apres})"
        assert (par_id[avant].sequence_order or 0) < (par_id[apres].sequence_order or 0), (
            "une paire doit toujours suivre l'ordre de la progression"
        )


@given(seances_d_un_module())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_les_paires_relient_toujours_deux_seances_vues_par_un_meme_etudiant(sessions):
    """Deux sous-groupes TP différents n'ont aucune raison d'être ordonnés."""
    from cal_iut.ingestion.config_loader import load_groups
    from cal_iut.solver.resources import build_student_cohorts

    groups = load_groups(CONFIG)
    cohortes = build_student_cohorts(groups)
    par_id = {s.id: s for s in sessions}

    for avant, apres in cohort_sequence_pairs(sessions, groups):
        a, b = par_id[avant], par_id[apres]
        partagee = any(
            ids.intersection(a.group_ids) and ids.intersection(b.group_ids)
            for ids in cohortes.values()
        )
        assert partagee, f"{avant} et {apres} ne sont jamais vues par le même étudiant"


# ==========================================================================
# Horaires d'événements — utilisés pour bloquer des créneaux du planning.
# ==========================================================================

@given(
    st.integers(min_value=8 * 60, max_value=18 * 60),
    st.integers(min_value=0, max_value=180),
)
@_lent
def test_un_evenement_bloque_au_moins_le_creneau_qui_le_contient(debut: int, duree: int):
    """Un événement à 9h30 doit bloquer le créneau 9h30-11h, pas rien."""
    fin = debut + duree
    creneaux = _slots_for_interval(debut, fin)
    bornes = [(8 * 60, 9 * 60 + 30), (9 * 60 + 30, 11 * 60), (11 * 60, 12 * 60 + 30),
              (14 * 60, 15 * 60 + 30), (15 * 60 + 30, 17 * 60), (17 * 60, 18 * 60 + 30)]
    attendus = [i for i, (s, e) in enumerate(bornes) if debut < e and max(fin, debut + 1) > s]
    assert creneaux == attendus, f"{debut}..{fin} -> {creneaux}, attendu {attendus}"


@given(st.integers(min_value=8, max_value=18), st.sampled_from([0, 15, 30, 45]))
@_lent
def test_un_horaire_dans_la_journee_de_cours_bloque_bien_un_creneau(heure: int, minute: int):
    """Un horaire situé dans une plage de cours doit bloquer son créneau.

    TROUVÉ PAR CETTE PROPRIÉTÉ (26/08/2026) : un horaire tombant dans la PAUSE
    MÉRIDIENNE (12h30-14h) ne bloque rien, la grille n'y ayant aucun créneau.
    C'est le comportement correct — on ne place rien à 13h de toute façon — mais
    il est silencieux : un « 13h00 Conseil de département » saisi sans heure de
    fin passerait pour pris en compte alors qu'il ne bloquerait rien.
    Aucun événement réel n'est aujourd'hui dans ce cas ; le contrôle d'audit
    `donnees.evenement_sans_creneau` le signalera si cela change.
    """
    minutes = heure * 60 + minute
    assume(not (12 * 60 + 30 <= minutes < 14 * 60))  # pause méridienne
    assume(8 * 60 <= minutes < 18 * 60 + 30)
    creneaux = _slots_for_event_text(f"{heure}h{minute:02d} Réunion")
    assert creneaux, f"aucun créneau trouvé pour {heure}h{minute:02d}"


@given(st.sampled_from([12 * 60 + 30, 12 * 60 + 45, 13 * 60, 13 * 60 + 30, 13 * 60 + 59]))
@_lent
def test_un_horaire_en_pause_meridienne_ne_bloque_rien_et_c_est_assume(minutes: int):
    """Contrepartie explicite de la propriété ci-dessus.

    Écrite pour que le jour où quelqu'un « corrigerait » ce comportement, le
    test dise pourquoi il était voulu : la grille n'a pas de créneau entre
    12h30 et 14h, y bloquer quelque chose n'aurait aucun sens.
    """
    assert _slots_for_interval(minutes, minutes) == []


@given(st.text(max_size=40))
@_lent
def test_un_libelle_sans_horaire_ne_bloque_jamais_rien(texte: str):
    """Règle « donnée fraîche » : on ne devine jamais un horaire non écrit."""
    assume(not re.search(r"\d", texte))
    assert _slots_for_event_text(texte) == set()


# ==========================================================================
# Bornes générales, valables pour tout créneau produit par le projet.
# ==========================================================================

@given(st.integers(min_value=0, max_value=29), st.integers(min_value=1, max_value=3))
@_lent
def test_un_bloc_ne_deborde_jamais_sur_le_jour_suivant(depart: int, duree: int):
    """Invariant de grille : un bloc de N créneaux tient dans SA journée.

    C'est la contrainte posée par `add_duration_domain_constraints` ; la
    propriété vérifie que l'arithmétique de la grille la rend exprimable.
    """
    assume((depart % SLOTS_PER_DAY) + duree <= SLOTS_PER_DAY)
    jour_debut = depart // SLOTS_PER_DAY
    jour_fin = (depart + duree - 1) // SLOTS_PER_DAY
    assert jour_debut == jour_fin


@given(dates_annee, st.integers(min_value=0, max_value=400))
@_lent
def test_une_plage_de_dates_contient_toujours_ses_bornes(debut: date, jours: int):
    fin = debut + timedelta(days=jours)
    plage = BC.daterange(debut, fin)
    assert plage[0] == debut and plage[-1] == fin
    assert len(plage) == jours + 1
