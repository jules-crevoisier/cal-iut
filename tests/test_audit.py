"""Le système d'audit doit trouver les bugs RÉELS et ne pas crier à tort.

Chaque test rejoue un défaut effectivement rencontré sur ce projet. Un audit qui
produit des faux positifs cesse d'être lu — c'est pourquoi la moitié de ces
tests vérifie qu'il se TAIT sur des situations normales.
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.audit.capacity_audit import audit_capacity
from cal_iut.audit.config_audit import audit_config
from cal_iut.audit.coverage_audit import REGLES, audit_coverage, audit_solver_paths
from cal_iut.audit.data_audit import audit_maquette, audit_teacher_constraints
from cal_iut.audit.report import AuditReport, Severity
from cal_iut.calendar.academic import build_default_calendar_2026_2027
from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.entities import (
    Course,
    SessionType,
    Teacher,
    TeacherAvailability,
    TeacherBlock,
)
from cal_iut.models.session import SessionToPlace

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"


def _checks(report: AuditReport, check: str) -> list:
    return [f for f in report.findings if f.check == check]


def _course(
    code: str = "WRTEST",
    *,
    semestre: str = "S1",
    profs: list[TeacherBlock] | None = None,
    volumes: dict | None = None,
) -> Course:
    lead = Teacher(code="AAA", nom="A", prenom="A")
    return Course(
        code=code,
        name="Test",
        semestre=semestre,
        parcours="BUT1",
        annee="BUT1",
        lead=lead,
        profs=profs if profs is not None else [TeacherBlock(block="b", teacher=lead, cm=0, td=4, tp=0)],
        volumes=volumes or {"cm": 0, "td": 4, "tp": 0},
        groupes_td=1,
        groupes_tp=1,
        progression_defined=False,
        seance_sequence=[],
        ordonnancement=[],
    )


def _session(sid: str, *, course: str = "WRTEST", parcours: str = "BUT1", teacher: str = "AAA",
             semestre: str = "S1", duration: int = 1) -> SessionToPlace:
    return SessionToPlace(
        id=sid, course_code=course, course_name="Test", semestre=semestre,
        parcours=parcours, annee=parcours.split("-")[0], session_type=SessionType.TD,
        sequence_order=1, group_ids=["but1-td-ab"], teacher_codes=[teacher],
        duration_slots=duration,
    )


# --------------------------------------------------------------------------
# Configuration : la règle qui pointe dans le vide
# --------------------------------------------------------------------------


def test_regle_sur_un_cours_inexistant_est_signalee(tmp_path: Path):
    """Une faute de frappe dans un code de cours ne lève rien aujourd'hui."""
    (tmp_path / "course_scheduling_rules.yaml").write_text(
        "min_week_rules:\n  - course_code: WR9999\n    semestre: S1\n    min_week: 3\n",
        encoding="utf-8",
    )
    report = AuditReport()
    audit_config(tmp_path, [_course("WR119")], build_default_calendar_2026_2027(), report)

    trouve = _checks(report, "config.cours_inexistant")
    assert trouve, "un code de cours inconnu doit être signalé"
    assert trouve[0].severity is Severity.ERREUR
    assert "WR9999" in trouve[0].message


def test_bon_semestre_mais_mauvais_cours_donne_un_message_distinct(tmp_path: Path):
    (tmp_path / "course_scheduling_rules.yaml").write_text(
        "max_week_rules:\n  - course_code: WR119\n    semestre: S3\n    max_week: 10\n",
        encoding="utf-8",
    )
    report = AuditReport()
    audit_config(tmp_path, [_course("WR119", semestre="S1")], build_default_calendar_2026_2027(), report)

    trouve = _checks(report, "config.mauvais_semestre")
    assert trouve and "S1" in trouve[0].quoi_faire


def test_fenetre_min_max_vide_est_signalee(tmp_path: Path):
    (tmp_path / "course_scheduling_rules.yaml").write_text(
        "min_week_rules:\n  - course_code: WR119\n    semestre: S1\n    min_week: 12\n"
        "max_week_rules:\n  - course_code: WR119\n    semestre: S1\n    max_week: 4\n",
        encoding="utf-8",
    )
    report = AuditReport()
    audit_config(tmp_path, [_course("WR119")], build_default_calendar_2026_2027(), report)
    assert _checks(report, "config.fenetre_semaine_vide")


def test_enseignant_hors_module_est_signale(tmp_path: Path):
    (tmp_path / "course_scheduling_rules.yaml").write_text(
        "teacher_order_rules:\n  - course_code: WRTEST\n    semestre: S1\n"
        "    teacher_order: [AAA, ZZZ]\n    weight: 100\n",
        encoding="utf-8",
    )
    report = AuditReport()
    audit_config(tmp_path, [_course()], build_default_calendar_2026_2027(), report)

    trouve = _checks(report, "config.enseignant_hors_module")
    assert trouve and "ZZZ" in trouve[0].message


def test_la_vraie_configuration_du_projet_ne_leve_aucune_erreur():
    """Garde-fou : l'audit doit rester silencieux sur la config réelle."""
    import json

    courses_path = ROOT / "data" / "generated" / "courses.json"
    if not courses_path.exists():
        return  # ingestion pas encore faite : rien à vérifier
    courses = [Course.model_validate(c) for c in json.loads(courses_path.read_text(encoding="utf-8"))]
    report = AuditReport()
    audit_config(CONFIG, courses, build_default_calendar_2026_2027(), report)

    erreurs = [f for f in report.findings if f.severity is Severity.ERREUR]
    assert not erreurs, "\n".join(f"{f.check} : {f.message}" for f in erreurs)


# --------------------------------------------------------------------------
# Capacité : les comptes qui ne tombent pas juste
# --------------------------------------------------------------------------


def test_jeudi_apres_midi_manquant_est_detecte():
    """Le bug AHA : assez de créneaux en tout, pas assez hors jeudi après-midi.

    Un enseignant indisponible le mercredi dispose de 4 jours. Sur une seule
    semaine ouvrable, cela fait 24 créneaux — mais seulement 21 pour de la
    formation initiale, le jeudi après-midi étant réservé aux PAC.
    """
    calendar = build_default_calendar_2026_2027()
    avail = TeacherAvailability(
        teacher_code="AHA",
        forbidden_slots=[(2, s) for s in range(6)],  # mercredi entier
    )
    sessions = [_session(f"s{i}") for i in range(22)]
    for s in sessions:
        s.teacher_codes = ["AHA"]

    report = AuditReport()
    audit_capacity(
        sessions, load_groups(CONFIG), [avail], [], calendar,
        week_offset=0, weeks=1, report=report,
    )
    trouve = _checks(report, "capacite.jeudi_pac_impossible")
    assert trouve, "22 séances FI pour 21 créneaux doit être signalé"
    assert "AHA" in trouve[0].message


def test_un_enseignant_dans_les_clous_ne_declenche_rien():
    calendar = build_default_calendar_2026_2027()
    avail = TeacherAvailability(teacher_code="AHA", forbidden_slots=[(2, s) for s in range(6)])
    sessions = [_session(f"s{i}") for i in range(5)]
    for s in sessions:
        s.teacher_codes = ["AHA"]

    report = AuditReport()
    audit_capacity(sessions, load_groups(CONFIG), [avail], [], calendar,
                   week_offset=0, weeks=1, report=report)
    assert not _checks(report, "capacite.jeudi_pac_impossible")
    assert not _checks(report, "capacite.enseignant_impossible")


def test_volume_superieur_aux_disponibilites_est_detecte():
    calendar = build_default_calendar_2026_2027()
    # Vacataire qui ne vient qu'un seul jour de l'année.
    avail = TeacherAvailability(teacher_code="MNI", allowed_dates=["2026-09-07"])
    sessions = [_session(f"s{i}", teacher="MNI") for i in range(20)]

    report = AuditReport()
    audit_capacity(sessions, load_groups(CONFIG), [avail], [], calendar,
                   week_offset=0, weeks=4, report=report)
    assert _checks(report, "capacite.enseignant_impossible")


# --------------------------------------------------------------------------
# Données : le volume qui n'atteint jamais son enseignant
# --------------------------------------------------------------------------


def test_enseignant_porteur_de_volume_sans_seance_est_detecte():
    """Le bug WSA501D : 34 créneaux à JSA, 0 à BTO."""
    jsa = Teacher(code="JSA", nom="S", prenom="J")
    bto = Teacher(code="BTO", nom="T", prenom="B")
    course = _course(
        "WSA501D", semestre="S5",
        profs=[
            TeacherBlock(block="b", teacher=jsa, cm=0, td=17, tp=0),
            TeacherBlock(block="b", teacher=bto, cm=0, td=17, tp=0),
        ],
        volumes={"cm": 0, "td": 34, "tp": 0},
    )
    sessions = [_session(f"s{i}", course="WSA501D", semestre="S5", teacher="JSA") for i in range(17)]

    report = AuditReport()
    audit_maquette([course], sessions, report, {"S5"})
    trouve = _checks(report, "donnees.enseignant_sans_seance")
    assert trouve and "BTO" in trouve[0].details[0]


def test_semestres_hors_perimetre_ne_sont_pas_signales():
    """S2/S4/S6 n'ont volontairement aucune séance : ce n'est pas un défaut."""
    course = _course("WR201", semestre="S2")
    report = AuditReport()
    audit_maquette([course], [], report, {"S1", "S3", "S5"})
    assert not _checks(report, "donnees.volume_sans_seance")


def test_contrainte_non_interpretee_est_remontee():
    avail = TeacherAvailability(
        teacher_code="XXX",
        metadata={"unresolved_tokens": ["quand il fait beau"], "forbidden_dates": []},
    )
    report = AuditReport()
    audit_teacher_constraints([avail], build_default_calendar_2026_2027(), report)
    trouve = _checks(report, "donnees.contrainte_non_interpretee")
    assert trouve and "quand il fait beau" in trouve[0].details[0]


def test_formulation_reprise_par_un_champ_structure_ne_leve_rien():
    """« 1 ou 2 semaines /mois » (ARA) devient `monthly_cluster_max_weeks`."""
    avail = TeacherAvailability(
        teacher_code="ARA",
        monthly_cluster_max_weeks=2,
        metadata={"unresolved_tokens": ["1 ou 2 semaines /mois"], "forbidden_dates": []},
    )
    report = AuditReport()
    audit_teacher_constraints([avail], build_default_calendar_2026_2027(), report)
    assert not _checks(report, "donnees.contrainte_non_interpretee")


def test_un_creneau_bloque_par_jour_nest_pas_une_indisponibilite_totale():
    """KBR ne commence qu'à 9h30 : 5 créneaux bloqués, un par jour."""
    avail = TeacherAvailability(
        teacher_code="KBR",
        forbidden_slots=[(d, 0) for d in range(5)],
        metadata={"forbidden_dates": []},
    )
    report = AuditReport()
    audit_teacher_constraints([avail], build_default_calendar_2026_2027(), report)
    assert not _checks(report, "donnees.enseignant_jamais_disponible")
    assert not _checks(report, "donnees.enseignant_tres_contraint")


def test_enseignant_reellement_bloque_partout_est_signale():
    avail = TeacherAvailability(
        teacher_code="ZZZ",
        forbidden_slots=[(d, s) for d in range(5) for s in range(6)],
        metadata={"forbidden_dates": []},
    )
    report = AuditReport()
    audit_teacher_constraints([avail], build_default_calendar_2026_2027(), report)
    trouve = _checks(report, "donnees.enseignant_jamais_disponible")
    assert trouve and trouve[0].severity is Severity.ERREUR


# --------------------------------------------------------------------------
# Couverture : la règle déclarée qui ne s'applique pas
# --------------------------------------------------------------------------


def test_le_registre_couvre_les_regles_annoncees_par_le_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for cle in ("plafond_hebdo", "jeudi_pac", "sae_sanctuarisation", "ordre_cohorte"):
        assert any(r.cle == cle for r in REGLES), f"{cle} doit figurer au registre"
    # Chaque règle du registre doit citer une source vérifiable.
    for regle in REGLES:
        assert regle.source, f"{regle.cle} sans source"
    assert "Ordonnancement" in readme


def test_controle_manquant_dans_un_run_est_signale():
    report = AuditReport()
    attendus = {r.controle for r in REGLES if r.controle}
    audit_coverage(report, attendus - {"weekly_cap"})
    trouve = _checks(report, "couverture.controle_absent")
    assert trouve and "weekly_cap" in trouve[0].details


def test_tous_les_controles_presents_ne_leve_rien():
    report = AuditReport()
    audit_coverage(report, {r.controle for r in REGLES if r.controle})
    assert not _checks(report, "couverture.controle_absent")


def test_parite_des_deux_solveurs_sur_le_projet_reel():
    """Le contrôle qui aurait trouvé les six règles absentes du décomposé."""
    report = AuditReport()
    audit_solver_paths(report, ROOT)
    trouve = _checks(report, "couverture.regle_absente_du_decompose")
    assert not trouve, (
        "contrainte(s) du modèle joint sans équivalent côté décomposé : "
        + ", ".join(trouve[0].details if trouve else [])
    )


def test_les_regles_sans_controle_sont_annoncees_comme_telles():
    report = AuditReport()
    audit_coverage(report, None)
    trouve = _checks(report, "couverture.regle_non_verifiee")
    assert trouve, "l'audit doit dire ce qu'il ne sait PAS vérifier"
    assert trouve[0].severity is Severity.INFO


# --------------------------------------------------------------------------
# Restitution
# --------------------------------------------------------------------------


def test_chaque_erreur_dit_quoi_faire(tmp_path: Path):
    (tmp_path / "course_scheduling_rules.yaml").write_text(
        "min_week_rules:\n  - course_code: WR9999\n    semestre: S1\n    min_week: 3\n",
        encoding="utf-8",
    )
    report = AuditReport()
    audit_config(tmp_path, [_course("WR119")], build_default_calendar_2026_2027(), report)
    for finding in report.findings:
        if finding.severity is Severity.ERREUR:
            assert finding.quoi_faire, f"{finding.check} n'explique pas quoi faire"


def test_le_rapport_texte_reste_lisible_sans_constat():
    report = AuditReport()
    report.ok("essai", "rien à signaler")
    texte = report.to_text()
    assert "Aucune erreur bloquante" in texte


def test_les_regles_restantes_sans_controle_sont_justifiees():
    """Toute règle sans contrôle doit expliquer POURQUOI elle n'en a pas.

    Sinon la liste devient un cimetière : on s'habitue à la voir, et une
    nouvelle règle non vérifiée s'y glisse sans que personne ne réagisse.
    """
    sans = [r for r in REGLES if r.controle is None]
    assert len(sans) <= 3, (
        "trop de règles non vérifiées, la couverture se dégrade : "
        + ", ".join(r.cle for r in sans)
    )
    for regle in sans:
        assert regle.note, f"{regle.cle} n'explique pas pourquoi elle n'est pas vérifiée"


def test_chaque_controle_du_registre_est_unique():
    controles = [r.controle for r in REGLES if r.controle]
    assert len(controles) == len(set(controles)), "deux règles pointent le même contrôle"


# --------------------------------------------------------------------------
# Faux positifs du tableau de bord (corrigés le 26/08/2026)
# --------------------------------------------------------------------------


def _payload_pour(timetable: dict):
    """Rejoue `build_payload` sur un emploi du temps, comme le fait l'audit."""
    import json

    from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
    from cal_iut.export.html_view import build_payload
    from cal_iut.ingestion.config_loader import load_rooms
    from cal_iut.models.session import SessionToPlace

    sessions_path = ROOT / "data" / "generated" / "sessions.json"
    if not sessions_path.exists():
        return None
    sessions = [
        SessionToPlace.model_validate(s)
        for s in json.loads(sessions_path.read_text(encoding="utf-8"))
    ]
    calendar = build_default_calendar_2026_2027()
    return build_payload(
        timetable, sessions, load_groups(CONFIG), calendar=calendar, semestre="S1",
        rooms=load_rooms(CONFIG),
    ), semester_week_offset(calendar, "S1")


def test_une_derogation_de_plafond_declaree_n_est_pas_comptee_comme_violation():
    """Le plafond de 22 admet des dérogations CIBLÉES et documentées.

    Sans les lire, le contrôle signalait « 8 cohortes au-dessus du plafond »
    pour la seule semaine explicitement autorisée. Un contrôle qui crie à tort
    finit ignoré — et c'est ainsi qu'une vraie violation passe.
    """
    from cal_iut.export.html_view import _cap_exceptions

    exceptions = _cap_exceptions()
    assert exceptions, "la dérogation WR106 doit être chargée"
    for (parcours, semaine), plafond in exceptions.items():
        assert plafond > 22, f"{parcours} semaine {semaine} : dérogation à {plafond}"
        assert isinstance(semaine, int)


def test_les_controles_de_salle_se_taisent_quand_aucune_salle_n_est_affectee():
    """Un run incomplet n'attribue aucune salle : se prononcer serait faux.

    Le contrôle « toute évaluation en A.018 » annonçait « 16/16 hors A.018 »
    sur un run sans salles, détournant l'attention du vrai problème.
    """
    resultat = _payload_pour({
        "status": "PARTIAL_WEEKS_FAILED:[3]",
        "placements": [],
    })
    if resultat is None:
        return
    payload, _ = resultat
    ids = {c["id"] for c in payload["ruleChecks"]}
    assert "eval_room" not in ids, "eval_room ne doit pas se prononcer sans salles"
    assert "room_double_booking" not in ids


def test_l_audit_de_couverture_tolere_les_controles_de_salle_absents():
    """Leur absence sur un run partiel est attendue, pas une régression."""
    report = AuditReport()
    attendus = {r.controle for r in REGLES if r.controle}
    audit_coverage(report, attendus - {"eval_room", "room_capacity", "room_double_booking"})

    erreurs = _checks(report, "couverture.controle_absent")
    assert not erreurs, "l'absence des contrôles de salle ne doit pas être une erreur"
    assert _checks(report, "couverture.controles_salles_inactifs")


def test_un_vrai_controle_manquant_reste_une_erreur():
    """La tolérance ci-dessus ne doit pas masquer une disparition réelle."""
    report = AuditReport()
    attendus = {r.controle for r in REGLES if r.controle}
    audit_coverage(report, attendus - {"thursday_pac"})
    trouve = _checks(report, "couverture.controle_absent")
    assert trouve and "thursday_pac" in trouve[0].details
