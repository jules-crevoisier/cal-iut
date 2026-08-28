"""Le polissage post-run (`scripts/polish_run.py`) — réparation d'ordre,
dilution des CM, regroupement WRA507D/WSA501D.

Trois garanties, dans l'ordre de gravité :

1. **Aucune séance orpheline.** `relocaliser` retire une séance de son
   emplacement avant de chercher où la reposer — toute sortie de fonction
   doit soit la reposer ailleurs, soit la remettre EXACTEMENT où elle était.
   Un bug ici a été trouvé et corrigé le 27/08/2026 : un premier jet sortait
   au milieu de la recherche sans jamais rappeler la restauration.
2. **Une relocalisation qui ne sert à rien est annulée, pas laissée.** Le
   paramètre `verifier` doit intégralement défaire un déplacement qui
   n'améliore pas la mesure visée.
3. **Les trois passes convergent réellement** sur les cas qu'elles ciblent,
   sans jamais dépasser le nombre de séances placées au départ.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pytest

from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.ingestion.constraints_loader import StudentPresence
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace
from cal_iut.solver.rooms import PlacedSessionWithRoom

import polish_run as pr  # noqa: E402

CONFIG = ROOT / "data" / "config"
GROUPES = load_groups(CONFIG)


def _seance(sid, code="WR101", groupe="but1-td-ab", ordre=1, stype=SessionType.TD):
    return SessionToPlace(
        id=sid, course_code=code, course_name="Test", semestre="S1",
        parcours="BUT1", annee="BUT1", session_type=stype,
        sequence_order=ordre, group_ids=[groupe], teacher_codes=["MRI"],
    )


def _place(sid, week, day, slot):
    return PlacedSessionWithRoom(
        session_id=sid, week=week, day=day, slot=slot, course_code="WR101",
        group_ids=["but1-td-ab"], teacher_codes=["MRI"],
    )


@pytest.fixture
def etat():
    e = get_state()
    ancien = {
        "sessions": e.sessions, "sessions_by_id": e.sessions_by_id, "timetable": e.timetable,
        "groups": e.groups, "rooms": e.rooms, "calendar": e.calendar, "current_run_id": e.current_run_id,
        "teacher_availability": e.teacher_availability, "teacher_duos": e.teacher_duos,
        "corrections": e.corrections, "courses": e.courses, "config_dir": e.config_dir,
        "student_presences": e.student_presences, "room_reservations": e.room_reservations,
    }
    e.groups = GROUPES
    e.rooms = []
    e.calendar = build_default_calendar_2026_2027()
    e.current_run_id = None
    e.teacher_availability = []
    e.teacher_duos = []
    e.corrections = []
    e.courses = []
    e.config_dir = CONFIG
    e.student_presences = []
    e.room_reservations = {}
    yield e
    for cle, valeur in ancien.items():
        setattr(e, cle, valeur)


# ==========================================================================
# 1. Aucune séance orpheline
# ==========================================================================


def test_relocaliser_sans_aucun_candidat_restaure_la_position_d_origine(etat):
    """Une seule séance, aucune autre semaine ouverte (`teaching_mondays`
    tronqué artificiellement en filtrant les créneaux) : la recherche doit
    échouer proprement plutôt que perdre la séance."""
    s = _seance("a")
    etat.sessions = [s]
    etat.sessions_by_id = {"a": s}
    p = _place("a", 10, 0, 0)
    etat.timetable = [p]

    ok = pr.relocaliser(etat, "a", verifier=lambda: False)  # verifier toujours faux : jamais gardé
    assert ok is False
    assert len(etat.timetable) == 1
    reste = etat.timetable[0]
    assert (reste.week, reste.day, reste.slot) == (10, 0, 0), "la séance n'est pas revenue à sa position d'origine"


def test_relocaliser_une_seance_inexistante_ne_plante_pas(etat):
    etat.sessions = []
    etat.sessions_by_id = {}
    etat.timetable = []
    assert pr.relocaliser(etat, "fantome") is False
    assert etat.timetable == []


def test_relocaliser_un_duo_synchronise_est_refuse_sans_toucher_au_planning(etat):
    from cal_iut.models.entities import TeacherDuo

    s = _seance("a", code="WR110")
    etat.sessions = [s]
    etat.sessions_by_id = {"a": s}
    etat.timetable = [_place("a", 10, 0, 0)]
    etat.teacher_duos = [TeacherDuo(course_codes=["WR110"], teacher_codes=["MRI", "MRI2"], room_id="h007")]

    assert pr.relocaliser(etat, "a") is False
    assert len(etat.timetable) == 1
    assert etat.timetable[0].week == 10


def test_relocaliser_garde_le_nombre_total_de_seances(etat):
    """Quel que soit le résultat (réussite ou repli), aucune séance ne doit
    disparaître ni se dupliquer."""
    a = _seance("a")
    b = _seance("b", groupe="but1-td-cd")
    etat.sessions = [a, b]
    etat.sessions_by_id = {"a": a, "b": b}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a", week=10, day=0, slot=0, course_code="WR101",
                               group_ids=["but1-td-ab"], teacher_codes=["MRI"]),
        PlacedSessionWithRoom(session_id="b", week=10, day=0, slot=1, course_code="WR101",
                               group_ids=["but1-td-cd"], teacher_codes=["MRI2"]),
    ]
    avant = len(etat.timetable)
    pr.relocaliser(etat, "a")
    assert len(etat.timetable) == avant
    assert {p.session_id for p in etat.timetable} == {"a", "b"}


# ==========================================================================
# 2. `verifier` annule intégralement un déplacement inutile
# ==========================================================================


def test_verifier_faux_annule_completement_le_deplacement(etat):
    s = _seance("a")
    # `_hard_constraint_context` déduit son horizon du planning DÉJÀ posé
    # (`max(week) + 1`) — mais `relocaliser` RETIRE d'abord la séance
    # concernée : sans une AUTRE séance loin dans le semestre, l'horizon
    # tomberait à 0 dès que la seule séance connue est retirée.
    ancre = _seance("ancre")
    etat.sessions = [s, ancre]
    etat.sessions_by_id = {"a": s, "ancre": ancre}
    etat.timetable = [_place("a", 10, 0, 0), _place("ancre", 20, 0, 0)]

    appels = []

    def verifier_toujours_faux():
        appels.append(1)
        return False

    ok = pr.relocaliser(etat, "a", verifier=verifier_toujours_faux)
    assert ok is False
    # Le verifier doit avoir été consulté : sinon la relocalisation n'a
    # jamais vraiment été soumise à l'épreuve.
    assert appels, "verifier n'a jamais été appelé alors qu'un candidat existait"
    a_reste = next(p for p in etat.timetable if p.session_id == "a")
    assert (a_reste.week, a_reste.day, a_reste.slot) == (10, 0, 0)


def test_verifier_vrai_garde_le_nouveau_placement(etat):
    s = _seance("a")
    ancre = _seance("ancre")
    etat.sessions = [s, ancre]
    etat.sessions_by_id = {"a": s, "ancre": ancre}
    etat.timetable = [_place("a", 10, 0, 0), _place("ancre", 20, 0, 0)]

    ok = pr.relocaliser(etat, "a", verifier=lambda: True)
    assert ok is True
    assert len(etat.timetable) == 2  # "a" relocalisée + "ancre" intacte


# ==========================================================================
# 3. Détection des violations — cohérente avec l'audit
# ==========================================================================


def test_violations_ordre_detecte_une_sequence_inversee(etat):
    a = _seance("a", ordre=1)
    b = _seance("b", ordre=2)
    etat.sessions = [a, b]
    etat.sessions_by_id = {"a": a, "b": b}
    etat.timetable = [_place("a", 12, 0, 0), _place("b", 5, 0, 0)]  # b (ordre 2) avant a (ordre 1)

    viol = pr.violations_ordre(etat)
    assert ("a", "b", "sequence") in viol


def test_violations_ordre_vide_quand_tout_est_dans_le_bon_sens(etat):
    a = _seance("a", ordre=1)
    b = _seance("b", ordre=2)
    etat.sessions = [a, b]
    etat.sessions_by_id = {"a": a, "b": b}
    etat.timetable = [_place("a", 5, 0, 0), _place("b", 12, 0, 0)]
    assert pr.violations_ordre(etat) == []


def test_journees_cm_chargees_detecte_le_seuil_depasse(etat):
    promo = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "promo")
    seances = [
        _seance(f"cm{i}", code=f"WR1{i}", groupe=promo.id, stype=SessionType.CM)
        for i in range(pr.CM_THRESHOLD + 2)
    ]
    etat.sessions = seances
    etat.sessions_by_id = {s.id: s for s in seances}
    etat.timetable = [
        PlacedSessionWithRoom(session_id=s.id, week=5, day=2, slot=i, course_code=s.course_code,
                               group_ids=[promo.id], teacher_codes=["MRI"])
        for i, s in enumerate(seances)
    ]
    journees = pr.journees_cm_chargees(etat)
    assert any(w == 5 and d == 2 for _, w, d, _ in journees)


def test_journees_cm_chargees_vide_sous_le_seuil(etat):
    promo = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "promo")
    seances = [_seance(f"cm{i}", code=f"WR1{i}", groupe=promo.id, stype=SessionType.CM) for i in range(2)]
    etat.sessions = seances
    etat.sessions_by_id = {s.id: s for s in seances}
    etat.timetable = [
        PlacedSessionWithRoom(session_id=s.id, week=5, day=2, slot=i, course_code=s.course_code,
                               group_ids=[promo.id], teacher_codes=["MRI"])
        for i, s in enumerate(seances)
    ]
    assert pr.journees_cm_chargees(etat) == []


# ==========================================================================
# `_allowed_weeks_pour_reparation` doit sauter les séances MANQUANTES,
# comme `violations_ordre` le fait déjà — sinon les deux ne parlent pas de
# la même chose.
# ==========================================================================


def test_les_bornes_de_reparation_relient_par_dessus_une_seance_manquante(etat):
    """Trouvé le 27/08/2026 sur le run réel : chaîne 5 -> 6 -> 7 -> 8, #7
    manquante. `violations_ordre` compare #6 et #8 directement (les seules
    séances PLACÉES adjacentes) ; les bornes de réparation doivent faire de
    même, sinon #6 garde #7 (manquante, donc sans contrainte réelle) comme
    seul voisin connu et rien n'empêche #6 de finir après #8."""
    c5 = _seance("c5", ordre=5)
    c6 = _seance("c6", ordre=6)
    c7 = _seance("c7", ordre=7)  # jamais placée
    c8 = _seance("c8", ordre=8)
    etat.sessions = [c5, c6, c7, c8]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        _place("c5", 6, 0, 0),
        _place("c6", 10, 0, 0),  # mal placée : après #8
        _place("c8", 2, 0, 0),
    ]

    # #5 (semaine 6) exige #6 >= 6 ; #8 (semaine 2), maintenant relié
    # DIRECTEMENT à #6 puisque #7 est absente, exige #6 <= 2. Aucune semaine
    # ne satisfait les deux à la fois : la fenêtre est VIDE — c'est la vérité
    # du planning (#6 seule ne peut pas se réparer, il faudrait déplacer #8),
    # et c'est exactement ce que doit détecter cette fonction, pas masquer en
    # ratant le lien vers #8 à cause de #7 manquante.
    bornes = pr._allowed_weeks_pour_reparation(etat, "c6")
    assert bornes == set(), (
        f"bornes={sorted(bornes)} — devrait être vide (#5 exige >=6, #8 exige <=2)"
    )


# ==========================================================================
# `_permuter` — dernier recours pour une paire bloquée des deux côtés
# ==========================================================================


def test_permuter_inverse_bien_l_ordre_relatif(etat):
    a = _seance("a", ordre=1)
    b = _seance("b", ordre=2)
    # `_hard_constraint_context` (appelé depuis `_permuter` pour la
    # vérification institutionnelle, cf. 27/08/2026) déduit son horizon du
    # planning déjà posé (`max(week) + 1`) — au milieu de l'échange, une
    # seule des deux séances est encore dans `etat.timetable`, donc sans une
    # AUTRE séance loin dans le semestre l'horizon s'écroulerait autour
    # d'elle. `ancre` est dans un autre groupe pour ne pas entrer dans la
    # même chaîne de séquence que a/b.
    ancre = _seance("ancre", groupe="but1-td-cd")
    etat.sessions = [a, b, ancre]
    etat.sessions_by_id = {"a": a, "b": b, "ancre": ancre}
    # b (ordre 2) actuellement AVANT a (ordre 1) : violation.
    etat.timetable = [_place("a", 12, 0, 0), _place("b", 5, 0, 0), _place("ancre", 25, 0, 0)]
    assert pr.violations_ordre(etat)

    assert pr._permuter(etat, "a", "b") is True
    pos_a = next(p for p in etat.timetable if p.session_id == "a")
    pos_b = next(p for p in etat.timetable if p.session_id == "b")
    assert (pos_a.week, pos_a.day, pos_a.slot) == (5, 0, 0)
    assert (pos_b.week, pos_b.day, pos_b.slot) == (12, 0, 0)
    assert pr.violations_ordre(etat) == []


def test_permuter_garde_le_nombre_total_de_seances(etat):
    a = _seance("a", ordre=1)
    b = _seance("b", ordre=2, groupe="but1-td-cd")
    etat.sessions = [a, b]
    etat.sessions_by_id = {"a": a, "b": b}
    etat.timetable = [_place("a", 12, 0, 0), _place("b", 5, 0, 0)]
    avant = len(etat.timetable)
    pr._permuter(etat, "a", "b")
    assert len(etat.timetable) == avant
    assert {p.session_id for p in etat.timetable} == {"a", "b"}


def test_permuter_une_seance_inexistante_ne_plante_pas(etat):
    etat.sessions = []
    etat.sessions_by_id = {}
    etat.timetable = []
    assert pr._permuter(etat, "x", "y") is False


def test_permuter_refuse_un_echange_qui_placerait_du_fc_hors_presence(etat):
    """Trouvé le 27/08/2026 en auditant un run polissé : une PREMIÈRE version
    de `_permuter` ne revalidait les deux nouvelles positions qu'avec
    `validate_move` (conflits de ressources), jamais avec
    `_institutional_violations` — une séance FC valide à sa position
    d'origine ne l'est pas forcément à celle de l'AUTRE séance échangée
    (ex. réel : WSA502D-S5-TP-8-but3-dev-fc-tp-e placée un jour où les
    étudiants FC étaient en entreprise)."""
    presence_mercredi = StudentPresence(
        parcours_keys=["BUT3-DEV-FC"],
        presence_dates={date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 18)},  # mercredis
    )
    etat.calendar = build_default_calendar_2026_2027()
    etat.student_presences = [presence_mercredi]
    offset = semester_week_offset(etat.calendar, "S5")
    abs_semaine, jour_mercredi = etat.calendar.date_to_week_day(date(2026, 11, 4))
    semaine = abs_semaine - offset
    jour_absence = 0 if jour_mercredi != 0 else 1  # n'importe quel autre jour ouvré, hors présence

    fc = SessionToPlace(
        id="fc", course_code="WRA507D", course_name="T", semestre="S5",
        parcours="BUT3-DEV-FC", annee="BUT3", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but3-dev-fc-td"], teacher_codes=["MRI"],
    )
    fi = SessionToPlace(
        id="fi", course_code="WR999", course_name="T", semestre="S5",
        parcours="BUT3-DEV", annee="BUT3", session_type=SessionType.TD,
        sequence_order=1, group_ids=["but3-dev-td"], teacher_codes=["AUT"],
    )
    ancre = _seance("ancre", groupe="but1-td-cd")
    etat.sessions = [fc, fi, ancre]
    etat.sessions_by_id = {"fc": fc, "fi": fi, "ancre": ancre}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="fc", week=semaine, day=jour_mercredi, slot=0,
                               course_code="WRA507D", group_ids=["but3-dev-fc-td"], teacher_codes=["MRI"]),
        PlacedSessionWithRoom(session_id="fi", week=semaine, day=jour_absence, slot=0,
                               course_code="WR999", group_ids=["but3-dev-td"], teacher_codes=["AUT"]),
        _place("ancre", 25, 0, 0),
    ]
    avant = {(p.session_id, p.week, p.day, p.slot) for p in etat.timetable}

    ok = pr._permuter(etat, "fc", "fi")
    assert ok is False, "l'échange aurait placé la séance FC un jour hors présence"
    apres = {(p.session_id, p.week, p.day, p.slot) for p in etat.timetable}
    assert apres == avant, "un échange refusé doit restaurer EXACTEMENT les positions d'origine"


def test_permuter_ne_depasse_jamais_le_plafond_hebdomadaire(etat):
    """Même trouvaille que `test_relocaliser_ne_depasse_jamais_le_plafond_hebdomadaire`,
    mais via un ÉCHANGE de positions plutôt qu'une relocalisation simple —
    trouvé le 27/08/2026 : le même trou pouvait s'ouvrir des deux côtés."""
    promo = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "promo")
    td = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "td")

    # Semaine 5 SATURÉE au plafond (23) pour la promo, indépendamment de
    # "cible"/"autre" (retirées avant le contrôle).
    saturantes = [
        _seance(f"sat{i}", code=f"WRY{i}", groupe=promo.id, stype=SessionType.CM)
        for i in range(pr.FI_WEEKLY_CAP_SLOTS)
    ]
    cible = _seance("cible", groupe=td.id)  # même cohorte que la promo (TD -> promo)
    autre = _seance("autre", code="WR999", groupe=td.id)
    etat.sessions = saturantes + [cible, autre]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id=s.id, week=5, day=i % 5, slot=i // 5, course_code=s.course_code,
                               group_ids=[promo.id], teacher_codes=["MRI"])
        for i, s in enumerate(saturantes)
    ] + [_place("autre", 5, 4, 5), _place("cible", 10, 0, 0)]
    avant = {(p.session_id, p.week, p.day, p.slot) for p in etat.timetable}

    ok = pr._permuter(etat, "cible", "autre")
    assert ok is False, "l'échange aurait fait dépasser le plafond hebdomadaire de la cohorte en semaine 5"
    apres = {(p.session_id, p.week, p.day, p.slot) for p in etat.timetable}
    assert apres == avant, "un échange refusé doit restaurer EXACTEMENT les positions d'origine"


# ==========================================================================
# 4. Mesures en AMPLEUR, pas en tout-ou-rien — CM et FC
# ==========================================================================


def test_excedent_total_cm_mesure_l_ampleur_pas_le_nombre_de_journees(etat):
    """Bug corrigé le 27/08/2026 : un jour à 6 CM qui redescend à 5 reste
    « en excès » (5 > seuil 2) — un comptage de journées ne verrait aucun
    progrès. L'excédent total, lui, doit baisser de 1."""
    promo = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "promo")
    seances = [_seance(f"cm{i}", code=f"WR1{i}", groupe=promo.id, stype=SessionType.CM) for i in range(6)]
    etat.sessions = seances
    etat.sessions_by_id = {s.id: s for s in seances}
    etat.timetable = [
        PlacedSessionWithRoom(session_id=s.id, week=5, day=2, slot=i, course_code=s.course_code,
                               group_ids=[promo.id], teacher_codes=["MRI"])
        for i, s in enumerate(seances)
    ]
    assert pr._excedent_total_cm(etat) == 6 - pr.CM_THRESHOLD  # 4

    # Une seule séance quitte cette journée : l'excédent baisse d'exactement 1.
    etat.timetable[-1] = PlacedSessionWithRoom(
        session_id="cm5", week=5, day=3, slot=0, course_code="WR15",
        group_ids=[promo.id], teacher_codes=["MRI"],
    )
    assert pr._excedent_total_cm(etat) == 6 - pr.CM_THRESHOLD - 1  # 3


def test_jours_fc_disperses_compte_les_jours_pas_les_seances(etat):
    a1 = _seance("a1", code="WRA507D", groupe="fc-g")
    a2 = _seance("a2", code="WRA507D", groupe="fc-g")
    b1 = _seance("b1", code="WSA501D", groupe="fc-g")
    etat.sessions = [a1, a2, b1]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a1", week=8, day=1, slot=0, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="a2", week=8, day=2, slot=0, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="b1", week=8, day=3, slot=0, course_code="WSA501D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
    ]
    disperses = pr.jours_fc_disperses(etat)
    assert disperses == [("fc-g", 8, 3)]  # 3 séances, 3 jours différents
    assert pr._jours_fc_total(etat) == 3


def test_jours_fc_disperses_vide_quand_tout_est_deja_le_meme_jour(etat):
    a1 = _seance("a1", code="WRA507D", groupe="fc-g")
    b1 = _seance("b1", code="WSA501D", groupe="fc-g")
    etat.sessions = [a1, b1]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a1", week=8, day=1, slot=0, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="b1", week=8, day=1, slot=1, course_code="WSA501D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
    ]
    assert pr.jours_fc_disperses(etat) == []
    assert pr._jours_fc_total(etat) == 0


# ==========================================================================
# 4bis. Fermeture des trous WRA507D/WSA501D dans une même journée
# ==========================================================================


def test_trous_fc_par_jour_detecte_un_creneau_vide_entre_deux_seances(etat):
    """Retour utilisateur (27/08/2026) : « laisse BTO le mercredi, c'est pas
    grave tant que c'est des blocs de 3h ou 4h30 » — le regroupement par
    JOUR (passe 3) ne voit pas un créneau 1 puis 3 sur le MÊME jour comme un
    défaut : c'est cette mesure-ci qui doit le voir."""
    a1 = _seance("a1", code="WRA507D", groupe="fc-g")
    a2 = _seance("a2", code="WRA507D", groupe="fc-g")
    etat.sessions = [a1, a2]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a1", week=8, day=1, slot=1, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="a2", week=8, day=1, slot=3, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
    ]
    trous = pr._trous_fc_par_jour(etat)
    assert trous == [("fc-g", 8, 1, 1)]  # 1 créneau vide (le 2) entre les deux séances
    assert pr._trous_fc_total(etat) == 1


def test_trous_fc_par_jour_vide_quand_deja_contigu(etat):
    a1 = _seance("a1", code="WRA507D", groupe="fc-g")
    a2 = _seance("a2", code="WRA507D", groupe="fc-g")
    etat.sessions = [a1, a2]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a1", week=8, day=1, slot=1, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="a2", week=8, day=1, slot=2, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
    ]
    assert pr._trous_fc_par_jour(etat) == []
    assert pr._trous_fc_total(etat) == 0


def test_passe_liberation_trous_fc_deplace_le_cours_bloqueur(etat):
    """Trouvé le 27/08/2026 en vérifiant sur le run réel : le "trou" entre
    deux séances FC est presque toujours occupé par un AUTRE vrai cours du
    même groupe (BUT3-DEV-FC suit bien plus que WRA507D/WSA501D) — jamais un
    créneau vide. `passe_fermeture_trous_fc` seule ne bouge rien dans ce
    cas ; celle-ci doit d'abord déplacer le bloqueur ailleurs."""
    a1 = _seance("a1", code="WRA507D", groupe="fc-g")
    a2 = _seance("a2", code="WRA507D", groupe="fc-g")
    bloqueur = _seance("bloqueur", code="WRA502D", groupe="fc-g")
    etat.sessions = [a1, a2, bloqueur]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a1", week=8, day=1, slot=1, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="bloqueur", week=8, day=1, slot=2, course_code="WRA502D",
                               group_ids=["fc-g"], teacher_codes=["HKO"]),
        PlacedSessionWithRoom(session_id="a2", week=8, day=1, slot=3, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
    ]
    assert pr._trous_fc_total(etat) == 1

    resultat = pr.passe_liberation_trous_fc(etat)
    assert resultat["ampleur_apres"] == 0, resultat
    positions = {p.session_id: (p.week, p.day, p.slot) for p in etat.timetable}
    # le bloqueur a bougé (plus au créneau du trou), jamais disparu.
    assert positions["bloqueur"] != (8, 1, 2)
    assert positions["a1"][:2] == (8, 1) and positions["a2"][:2] == (8, 1)


def test_passe_fermeture_trous_fc_rapproche_la_seance_isolee(etat):
    """La séance la plus tardive (a2, créneau 3) doit se rapprocher de a1
    (créneau 1) pour combler le trou — jamais changer de jour ni de semaine
    (`semaine_imposee`/`jour_impose` sur `relocaliser`)."""
    a1 = _seance("a1", code="WRA507D", groupe="fc-g")
    a2 = _seance("a2", code="WRA507D", groupe="fc-g")
    etat.sessions = [a1, a2]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id="a1", week=8, day=1, slot=1, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
        PlacedSessionWithRoom(session_id="a2", week=8, day=1, slot=3, course_code="WRA507D",
                               group_ids=["fc-g"], teacher_codes=["BTO"]),
    ]
    resultat = pr.passe_fermeture_trous_fc(etat)
    assert resultat["ampleur_apres"] == 0, resultat
    positions = {p.session_id: (p.week, p.day) for p in etat.timetable}
    assert positions["a1"] == (8, 1) and positions["a2"] == (8, 1), (
        "ne doit jamais changer de jour ou de semaine pour combler un trou"
    )


# ==========================================================================
# 5. Le plafond hebdomadaire de la cohorte n'est jamais dépassé
# ==========================================================================


def test_relocaliser_ne_depasse_jamais_le_plafond_hebdomadaire(etat):
    """Bug corrigé le 27/08/2026 : `_hard_constraint_context` ne vérifie pas
    ce plafond — une relocalisation pouvait réparer un problème en en créant
    un autre, plus grave (un audit a trouvé 12 cohortes au-dessus du plafond
    après une première passe sans ce garde-fou)."""
    promo = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "promo")
    td = next(g for g in GROUPES if g.parcours == "BUT1" and g.kind == "td")

    # Semaine 5 SATURÉE au plafond (23) pour la promo, semaine 6 large ouverte.
    saturantes = [
        _seance(f"sat{i}", code=f"WRX{i}", groupe=promo.id, stype=SessionType.CM)
        for i in range(pr.FI_WEEKLY_CAP_SLOTS)
    ]
    cible = _seance("cible", groupe=td.id)  # même cohorte que la promo (TD -> promo)
    etat.sessions = saturantes + [cible]
    etat.sessions_by_id = {s.id: s for s in etat.sessions}
    etat.timetable = [
        PlacedSessionWithRoom(session_id=s.id, week=5, day=i % 5, slot=i // 5, course_code=s.course_code,
                               group_ids=[promo.id], teacher_codes=["MRI"])
        for i, s in enumerate(saturantes)
    ] + [_place("cible", 5, 4, 5)]  # dernier créneau, encore dans la même semaine saturée

    ok = pr.relocaliser(etat, "cible", semaines_preferees={5}, verifier=lambda: True)
    if ok:
        nouvelle = next(p for p in etat.timetable if p.session_id == "cible")
        assert nouvelle.week != 5, (
            "la relocalisation a laissé/replacé la séance dans une semaine déjà au plafond"
        )
