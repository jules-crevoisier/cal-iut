"""Mise à jour du 25/08/2026 : ordonnancement, sources rafraîchies, WSA501D.

Chaque test correspond à un défaut MESURÉ sur le run réel `odd26` (2389
placements) ou à une demande explicite de l'utilisateur du même jour :

- 790 paires CM↔TD/TP hors ordre : l'ordre pédagogique n'était vérifié qu'entre
  séances du même `group_id` brut, jamais entre un CM (groupe promo) et les
  TD/TP qui l'encadrent dans `progression.json` ;
- 89/89 relations `before`/`after` violées au critère strict « A fini avant que
  B commence » (seule la position MOYENNE était modélisée) ;
- WSA501D : 0 séance placée sur 34, la SAE étant retirée d'office par le filtre
  « le code commence par WS » ;
- WRA507D : débordait jusqu'au 8-12 mars 2027 alors qu'il doit finir en janvier ;
- VMA : deux dates isolées au format numérique (`23/09/26`) lues comme une
  indisponibilité récurrente « tous les mercredis » ;
- SLO : perdu des enseignants de la SAE WS501D par une frontière de mot dans un
  export où les trigrammes sont concaténés ;
- WSA501D : le second enseignant (BTO) ne recevait aucune séance dès lors que le
  cours était fusionné en blocs de 3h.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

from ortools.sat.python import cp_model

from cal_iut.calendar.academic import (
    build_default_calendar_2026_2027,
    parse_french_date,
    semester_week_offset,
)
from cal_iut.ingestion.config_loader import (
    load_course_max_week_rules,
    load_double_sessions,
    load_teacher_distributions,
    load_groups,
    load_sae_teacher_phases,
    load_session_date_windows,
    load_solver_scheduled_sae,
)
from cal_iut.ingestion.normalize import expand_course_to_sessions
from cal_iut.ingestion.planning_loader import (
    load_mmi_planning_for_semestres,
    sae_supervisor_dates_by_teacher,
)
from cal_iut.models.entities import (
    Course,
    SessionType,
    Teacher,
    TeacherBlock,
    TeacherDistributionRule,
)
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import (
    add_cohort_sequence_constraints,
    add_session_date_window_constraints,
    cohort_sequence_pairs,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY


def _build_contraintes_module():
    """`scripts/build_contraintes.py` n'est pas un paquet importable."""
    spec = importlib.util.spec_from_file_location("build_contraintes", ROOT / "scripts" / "build_contraintes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session(
    sid: str,
    *,
    order: int,
    session_type: SessionType,
    group_ids: list[str],
    course_code: str = "WR106",
    semestre: str = "S1",
) -> SessionToPlace:
    return SessionToPlace(
        id=sid,
        course_code=course_code,
        course_name="Test",
        semestre=semestre,
        parcours="BUT1",
        annee="BUT1",
        session_type=session_type,
        sequence_order=order,
        group_ids=group_ids,
        teacher_codes=["MRI"],
    )


# --------------------------------------------------------------------------
# Ordre pédagogique vu par l'étudiant (CM promo <-> TD/TP sous-groupe)
# --------------------------------------------------------------------------


def test_cm_and_td_of_the_same_cohort_are_paired():
    """Le défaut de fond : un CM et un TD ne partagent aucun `group_id`."""
    groups = load_groups(CONFIG)
    sessions = [
        _session("cm1", order=1, session_type=SessionType.CM, group_ids=["but1-promo"]),
        _session("td1", order=2, session_type=SessionType.TD, group_ids=["but1-td-ab"]),
        _session("tp1", order=3, session_type=SessionType.TP, group_ids=["but1-tp-a"]),
    ]
    pairs = set(cohort_sequence_pairs(sessions, groups))

    assert ("cm1", "td1") in pairs, "le CM doit précéder le TD de la cohorte"
    assert ("td1", "tp1") in pairs, "le TD doit précéder le TP de la même cohorte"


def test_pairs_of_two_different_cohorts_never_cross():
    groups = load_groups(CONFIG)
    sessions = [
        _session("td-ab", order=1, session_type=SessionType.TD, group_ids=["but1-td-ab"]),
        _session("tp-a", order=2, session_type=SessionType.TP, group_ids=["but1-tp-a"]),
        _session("tp-h", order=2, session_type=SessionType.TP, group_ids=["but1-tp-h"]),
    ]
    pairs = set(cohort_sequence_pairs(sessions, groups))

    assert ("td-ab", "tp-a") in pairs
    # TP H dépend du TD GH, pas du TD AB : les deux cohortes restent indépendantes.
    assert ("td-ab", "tp-h") not in pairs


def test_same_group_pairs_are_left_to_the_existing_hard_constraint():
    groups = load_groups(CONFIG)
    sessions = [
        _session("td1", order=1, session_type=SessionType.TD, group_ids=["but1-td-ab"]),
        _session("td2", order=2, session_type=SessionType.TD, group_ids=["but1-td-ab"]),
    ]
    assert cohort_sequence_pairs(sessions, groups) == []
    assert ("td1", "td2") in set(
        cohort_sequence_pairs(sessions, groups, cross_granularity_only=False)
    )


def test_cohort_order_is_enforced_hard_inside_one_week():
    """Reproduit le cas WR103 du run `odd26` : CM-1 après le TD-1."""
    groups = load_groups(CONFIG)
    sessions = [
        _session("cm1", order=1, session_type=SessionType.CM, group_ids=["but1-promo"]),
        _session("td1", order=2, session_type=SessionType.TD, group_ids=["but1-td-ab"]),
    ]
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, SLOTS_PER_WEEK - 1, s.id) for s in sessions}
    added = add_cohort_sequence_constraints(model, sessions, starts, groups)
    assert added == 1

    # On force le TD au tout premier créneau : le CM n'a plus de place valide.
    model.add(starts["td1"] == 0)
    solver = cp_model.CpSolver()
    assert solver.solve(model) == cp_model.INFEASIBLE


def test_cohort_order_needs_groups_to_do_anything():
    sessions = [
        _session("cm1", order=1, session_type=SessionType.CM, group_ids=["but1-promo"]),
        _session("td1", order=2, session_type=SessionType.TD, group_ids=["but1-td-ab"]),
    ]
    model = cp_model.CpModel()
    starts = {s.id: model.new_int_var(0, 10, s.id) for s in sessions}
    assert add_cohort_sequence_constraints(model, sessions, starts, None) == 0


# --------------------------------------------------------------------------
# Dates au format numérique (CSV du 25/08/2026)
# --------------------------------------------------------------------------


def test_numeric_french_dates_are_understood():
    assert parse_french_date("mercredi 23/09/26 toute la journée") == date(2026, 9, 23)
    assert parse_french_date("mercredi 7/10/26") == date(2026, 10, 7)
    assert parse_french_date("7/10/2026") == date(2026, 10, 7)


def test_vma_numeric_dates_are_two_isolated_days_not_every_wednesday():
    tokens = _build_contraintes_module()._tokenize(
        "mercredi 23/09/26 toute la journée - mercredi 7/10/26"
    )
    assert [t["type"] for t in tokens] == ["date_specifique", "date_specifique"]


def test_concatenated_trigrams_keep_every_teacher():
    parse_teachers = _build_contraintes_module()._parse_teachers
    assert parse_teachers("ALO : LOIZON ARIANESLO : LOIZON Sébastien") == ["ALO", "SLO"]
    assert parse_teachers("AFR : FROLI ANTHONYAHA : HARAOUBIA AMINE") == ["AFR", "AHA"]
    assert parse_teachers("aucun") == []


def test_cancelled_vss_event_is_not_a_blocking_event():
    """Retour utilisateur : le VSS du 17/09/2026 est annulé."""
    import json

    data = json.loads((ROOT / "contraintes" / "10_dates_fixes.json").read_text(encoding="utf-8"))
    dates = {e["date"] for e in data["evenements"]}
    assert "2026-09-17" not in dates
    assert any(e["date"] == "2026-09-17" for e in data["annules"])


# --------------------------------------------------------------------------
# WSA501D : SAE planifiée par le solveur, en blocs de 3h
# --------------------------------------------------------------------------


def test_wsa501d_is_declared_as_solver_scheduled():
    assert ("WSA501D", "S5") in load_solver_scheduled_sae(CONFIG)


def test_wsa501d_is_split_into_three_hour_blocks_shared_by_both_teachers():
    """34 TD -> 17 blocs de 2 créneaux, partagés entre JSA et BTO.

    Le partage est le vrai enjeu : avant correction, `_teacher_for_group`
    comptait des SÉANCES là où la maquette compte des CRÉNEAUX, et les 17 blocs
    tombaient tous dans le quota de 17 créneaux du premier enseignant.
    """
    jsa = Teacher(code="JSA", nom="SABATER", prenom="JULES")
    bto = Teacher(code="BTO", nom="TOMASINA", prenom="Barthélémy")
    course = Course(
        code="WSA501D",
        name="Développer pour le web",
        semestre="S5",
        parcours="BUT3-DEV-FC",
        annee="BUT3",
        lead=jsa,
        profs=[
            TeacherBlock(block="block1", teacher=jsa, cm=0, td=17, tp=0),
            TeacherBlock(block="block1", teacher=bto, cm=0, td=17, tp=0),
        ],
        volumes={"cm": 0, "td": 34, "tp": 0},
        groupes_td=1,
        groupes_tp=1,
        progression_defined=False,
        seance_sequence=[],
        ordonnancement=[],
    )
    rules = [r for r in load_double_sessions(CONFIG) if r.course_code == "WSA501D"]
    sessions = expand_course_to_sessions(course, load_groups(CONFIG), double_session_rules=rules)

    assert len(sessions) == 17
    assert {s.duration_slots for s in sessions} == {2}
    codes = [s.teacher_codes[0] for s in sessions]
    assert codes.count("JSA") > 0 and codes.count("BTO") > 0
    assert abs(codes.count("JSA") - codes.count("BTO")) <= 1


def test_wsa501d_blocks_stay_between_three_and_four_and_a_half_hours():
    rules = [r for r in load_double_sessions(CONFIG) if r.course_code == "WSA501D"]
    assert rules, "WSA501D doit avoir une règle de bloc"
    assert 2 <= rules[0].slots_per_session <= 3  # 3h à 4h30


# --------------------------------------------------------------------------
# Borne de fin par cours
# --------------------------------------------------------------------------


def test_wra507d_must_end_in_january():
    rules = {(r.course_code, r.semestre): r for r in load_course_max_week_rules(CONFIG)}
    rule = rules[("WRA507D", "S5")]
    calendar = build_default_calendar_2026_2027()
    monday = calendar.teaching_mondays[rule.max_week]

    assert monday.year == 2027 and monday.month == 1, (
        f"la borne doit tomber en janvier 2027, pas le {monday}"
    )


# --------------------------------------------------------------------------
# WS501D : phases enseignants d'Ariane Loizon
# --------------------------------------------------------------------------


def test_ws501d_phases_cover_the_three_teachers():
    phases = [p for p in load_sae_teacher_phases(CONFIG) if p.course_code == "WS501D"]
    assert {p.teacher_code for p in phases} == {"FME", "SLO", "ALO"}


def test_slo_phase_avoids_the_toussaint_closure():
    """« entre le 26 et le 30 octobre » = IUT fermé.

    Ariane Loizon a confirmé le 26/08/2026 (via Kyllian Bresson) qu'il
    s'agissait de la semaine PRÉCÉDENTE, du 19 au 23 octobre. Le test vérifie
    l'INVARIANT qui avait fait remonter la contradiction — une phase ne doit
    contenir aucun jour de fermeture — et non la date elle-même, pour rester
    valide si la répartition évolue encore.
    """
    calendar = build_default_calendar_2026_2027()
    phase = next(
        p for p in load_sae_teacher_phases(CONFIG) if p.teacher_code == "SLO"
    )
    from datetime import timedelta

    debut, fin = date.fromisoformat(phase.debut), date.fromisoformat(phase.fin)
    days = [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]
    ouvrables = [d for d in days if d.weekday() < 5]

    assert ouvrables, "la phase doit contenir au moins un jour ouvrable"
    assert not (set(ouvrables) & calendar.blocked_dates), (
        "la phase de SLO ne doit plus tomber dans la pause pédagogique de la Toussaint"
    )


def test_alo_is_free_in_october_thanks_to_the_phases():
    """Sans les phases, ALO était bloquée sur les 22 jours de la WS501D."""
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    dates = sae_supervisor_dates_by_teacher(bundle, CONFIG)

    ws501d_days = {
        d for w in bundle.sae_windows if "WS501D" in w.course_codes for d in w.dates
    }
    october_ws501d = {d for d in ws501d_days if d.month == 10}
    assert october_ws501d, "la WS501D a bien des jours en octobre"
    assert not (october_ws501d & dates.get("ALO", set())), (
        "ALO n'intervient sur la WS501D qu'à partir du 12 novembre"
    )
    # FME, lui, est bien mobilisé en octobre.
    assert october_ws501d & dates.get("FME", set())


def test_teacher_without_declared_phase_keeps_every_day():
    """Repli prudent : on ne libère jamais quelqu'un par omission."""
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    dates = sae_supervisor_dates_by_teacher(bundle, CONFIG)
    wsa501c = next(w for w in bundle.sae_windows if "WSA501C" in w.course_codes)

    assert set(wsa501c.dates) <= dates.get("MNI", set())


def test_joint_wra505c_session_is_confined_to_ws501d_days():
    rule = next(
        r for r in load_session_date_windows(CONFIG)
        if r.course_code == "WRA505C" and r.sequence_orders == [17]
    )
    bundle = load_mmi_planning_for_semestres(ROOT, ["S5"])
    ws501d_days = {
        d.isoformat()
        for w in bundle.sae_windows
        if "WS501D" in w.course_codes
        for d in w.dates
    }
    assert rule.only_dates
    assert set(rule.only_dates) <= ws501d_days, (
        "la séance conjointe doit tomber un jour de SAE WS501D"
    )

    alo_phase = next(
        p for p in load_sae_teacher_phases(CONFIG)
        if p.teacher_code == "ALO" and p.course_code == "WS501D"
    )
    assert set(rule.only_dates) <= set(alo_phase.exclure), (
        "ALO doit être libérée de la WS501D ces jours-là pour animer la WRA505C"
    )


def test_only_dates_window_restricts_to_the_listed_days():
    calendar = build_default_calendar_2026_2027()
    week_offset = semester_week_offset(calendar, "S5")
    weeks = 20
    rule = next(
        r for r in load_session_date_windows(CONFIG)
        if r.course_code == "WRA505C" and r.sequence_orders == [17]
    )
    session = _session(
        "wra505c-17",
        order=17,
        session_type=SessionType.TD,
        group_ids=["but3-creacom-fc-td-gh"],
        course_code="WRA505C",
        semestre="S5",
    )
    model = cp_model.CpModel()
    starts = {session.id: model.new_int_var(0, weeks * SLOTS_PER_WEEK - 1, session.id)}
    add_session_date_window_constraints(
        model, [session], starts, [rule], calendar, week_offset, weeks
    )
    solver = cp_model.CpSolver()
    assert solver.solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    t = solver.value(starts[session.id])
    placed = calendar.week_day_to_date(
        week_offset + t // SLOTS_PER_WEEK, (t % SLOTS_PER_WEEK) // SLOTS_PER_DAY
    )
    assert placed.isoformat() in rule.only_dates


# --------------------------------------------------------------------------
# Vœux EDT 2026-2027 (BUT2-DEV-FI S3)
# --------------------------------------------------------------------------


def test_webdoc_wishes_are_translated_into_rules():
    windows = {
        (r.course_code, r.session_type): r
        for r in load_session_date_windows(CONFIG)
        if r.course_code == "WR308D"
    }
    cm = windows[("WR308D", SessionType.CM)]
    tp = windows[("WR308D", SessionType.TP)]

    assert cm.start_date.startswith("2026-09") and cm.end_date.startswith("2026-09")
    assert tp.end_date.startswith("2026-12")


# --------------------------------------------------------------------------
# Répartition alternée des enseignants (WRA507D, 25/08/2026)
# --------------------------------------------------------------------------


def _two_teacher_course(code: str, first: str, second: str) -> Course:
    a = Teacher(code=first, nom=first, prenom=first)
    b = Teacher(code=second, nom=second, prenom=second)
    return Course(
        code=code,
        name="Test",
        semestre="S5",
        parcours="BUT3-DEV-FC",
        annee="BUT3",
        lead=a,
        profs=[
            TeacherBlock(block="block1", teacher=a, cm=0, td=17, tp=0),
            TeacherBlock(block="block1", teacher=b, cm=0, td=17, tp=0),
        ],
        volumes={"cm": 0, "td": 34, "tp": 0},
        groupes_td=1,
        groupes_tp=1,
        progression_defined=False,
        seance_sequence=[],
        ordonnancement=[],
    )


def test_wra507d_alternates_its_two_teachers():
    """Retour utilisateur : un 2e enseignant s'est ajouté, il faut alterner."""
    rules = load_teacher_distributions(CONFIG)
    rule = next(r for r in rules if r.course_code == "WRA507D")
    assert rule.mode == "alterne"

    sessions = expand_course_to_sessions(
        _two_teacher_course("WRA507D", "BTO", "JSA"),
        load_groups(CONFIG),
        teacher_distributions=rules,
    )
    codes = [s.teacher_codes[0] for s in sessions]

    assert len(codes) == 34
    assert codes[:6] == ["BTO", "JSA", "BTO", "JSA", "BTO", "JSA"]
    assert codes.count("BTO") == 17 and codes.count("JSA") == 17


def test_alternation_respects_each_volume_even_with_merged_blocks():
    """L'alternance sur un cours FUSIONNÉ en blocs préserve les volumes.

    Testée sur une règle construite ici plutôt que sur celle de WSA501D : cette
    dernière a été retirée le 26/08/2026 (elle n'avait jamais été demandée, et
    trois mesures ne lui ont trouvé aucun effet). Le mécanisme, lui, reste
    utilisé par WRA507D et doit continuer de fonctionner sur des blocs.
    """
    double = [r for r in load_double_sessions(CONFIG) if r.course_code == "WSA501D"]
    regle = [TeacherDistributionRule(
        course_code="WSA501D", semestre="S5", mode="alterne", teacher_order=["JSA", "BTO"]
    )]
    sessions = expand_course_to_sessions(
        _two_teacher_course("WSA501D", "JSA", "BTO"),
        load_groups(CONFIG),
        double_session_rules=double,
        teacher_distributions=regle,
    )
    codes = [s.teacher_codes[0] for s in sessions]

    assert len(codes) == 17
    assert {s.duration_slots for s in sessions} == {2}
    # 17 blocs de 2 créneaux = 34 créneaux à partager 17/17 : 9 blocs (18) pour
    # l'un est le plus proche possible sans dépasser le quota de l'autre.
    assert abs(codes.count("JSA") - codes.count("BTO")) == 1
    assert codes[0] != codes[1], "les enseignants doivent bien alterner"


def test_wsa501d_garde_le_decoupage_sequentiel_par_defaut():
    """L'alternance ajoutée sans demande le 25/08 a bien été retirée."""
    assert not [
        r for r in load_teacher_distributions(CONFIG)
        if r.course_code == "WSA501D"
    ], "WSA501D ne doit plus porter de règle de répartition"


def test_a_course_without_rule_keeps_the_sequential_split():
    """WRA505C doit rester en blocs contigus (ALO au début, AFR à la fin)."""
    sessions = expand_course_to_sessions(
        _two_teacher_course("WRA505C", "ALO", "AFR"),
        load_groups(CONFIG),
        teacher_distributions=load_teacher_distributions(CONFIG),
    )
    codes = [s.teacher_codes[0] for s in sessions]

    assert codes[:17] == ["ALO"] * 17
    assert codes[17:] == ["AFR"] * 17


# --------------------------------------------------------------------------
# Plafond enseignant : le jeudi après-midi réservé aux PAC (bug AHA, 25/08/2026)
# --------------------------------------------------------------------------


def _fi_session(idx: int, teacher: str = "AHA") -> SessionToPlace:
    return SessionToPlace(
        id=f"fi-{idx}",
        course_code="WRFI",
        course_name="Test",
        semestre="S1",
        parcours="BUT1",  # formation initiale : pas de jeudi après-midi
        annee="BUT1",
        session_type=SessionType.TD,
        sequence_order=None,
        group_ids=["but1-td-ab"],
        teacher_codes=[teacher],
    )


def test_les_seances_fi_ne_comptent_pas_le_jeudi_apres_midi():
    """Le bug qui a coûté deux heures de calcul.

    AHA est indisponible le mercredi : 24 créneaux dans une semaine ouvrable.
    Mais ses séances de formation initiale n'ont pas accès au jeudi après-midi
    (réservé aux PAC), ce qui n'en laisse que 21 — 19 une fois la marge de
    sécurité retirée. L'étage 2 lui en assignait 22, rendant la semaine PROUVÉE
    infaisable à l'étage 3 en 0,1 s.

    Le test vérifie que l'étage 2 refuse désormais d'y mettre plus que la
    capacité réelle, alors même que le plafond « toutes séances confondues »
    l'autoriserait.
    """
    from cal_iut.calendar.academic import build_default_calendar_2026_2027
    from cal_iut.models.entities import TeacherAvailability
    from cal_iut.solver.decomposed import assign_weeks

    calendar = build_default_calendar_2026_2027()
    groups = load_groups(CONFIG)
    avail = [TeacherAvailability(
        teacher_code="AHA",
        forbidden_slots=[(2, s) for s in range(6)],  # mercredi entier
    )]
    # 22 séances FI : sous le plafond « tous types » (24 - 2 = 22), au-dessus
    # du plafond FI réel (21 - 2 = 19).
    sessions = [_fi_session(i) for i in range(22)]

    # 3 semaines : la semaine-index 0 est le verrou d'intégration (interdite à
    # toute la formation initiale), il en reste donc 2 réellement utilisables.
    result = assign_weeks(
        sessions, groups, weeks=3, teacher_availability=avail, calendar=calendar,
        week_offset=1, time_limit_seconds=10, cohort_order_weight=0,
        strict_ordonnancement_weight=0, teacher_clustering_weight=0,
    )
    assert result.status in ("OPTIMAL", "FEASIBLE"), result.status

    par_semaine: dict[int, int] = {}
    for sid, week in result.week_by_session.items():
        par_semaine[week] = par_semaine.get(week, 0) + 1
    assert max(par_semaine.values()) <= 19, (
        "l'étage 2 ne doit jamais assigner plus de séances FI que de créneaux "
        f"disponibles hors jeudi après-midi : {par_semaine}"
    )


def test_un_enseignant_mixte_garde_le_jeudi_apres_midi_pour_ses_seances_fc():
    """Le second plafond ne doit pas pénaliser un enseignant réellement mixte.

    Le correctif remplace un test annuel approximatif par deux plafonds ; il
    serait raté s'il retirait le jeudi après-midi à tout le monde.
    """
    from cal_iut.calendar.academic import build_default_calendar_2026_2027
    from cal_iut.models.entities import TeacherAvailability
    from cal_iut.solver.decomposed import _teacher_available_slots_by_week

    calendar = build_default_calendar_2026_2027()
    avail = [TeacherAvailability(teacher_code="MIX")]

    avec = _teacher_available_slots_by_week(avail, 3, calendar, 1, set())
    sans = _teacher_available_slots_by_week(avail, 3, calendar, 1, {"MIX"})

    assert avec[("MIX", 0)] - sans[("MIX", 0)] == 3, (
        "le jeudi après-midi vaut exactement 3 créneaux d'écart entre les deux "
        "capacités"
    )


def test_la_phase_de_slo_recouvre_de_vrais_jours_de_sae():
    """Une phase qui ne croise presque aucun jour de SAE ne mobilise personne.

    C'est le contrôle qui manquait le 25/08/2026 : la phase provisoire au
    2-6 novembre ne recouvrait que 2 jours de SAE, pour 9 séances à y placer,
    et rien ne le signalait. Après confirmation d'Ariane (19-23 octobre), elle
    en recouvre 4.
    """
    phase = next(
        p for p in load_sae_teacher_phases(CONFIG)
        if p.teacher_code == "SLO" and p.course_code == "WS501D"
    )
    bundle = load_mmi_planning_for_semestres(ROOT, ["S5"])
    jours_sae = {
        d for w in bundle.sae_windows if "WS501D" in w.course_codes for d in w.dates
    }
    debut, fin = date.fromisoformat(phase.debut), date.fromisoformat(phase.fin)
    couverts = {d for d in jours_sae if debut <= d <= fin}

    assert couverts, "la phase de SLO ne recouvre aucun jour de SAE WS501D"
    assert len(couverts) >= 4, (
        f"seulement {len(couverts)} jour(s) de SAE dans la phase de SLO "
        f"({phase.debut}..{phase.fin}) pour 9 séances à y placer"
    )
