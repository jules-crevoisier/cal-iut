"""Audit de COUVERTURE : quelles règles sont réellement vérifiées ?

Famille de bugs visée, et de loin la plus coûteuse : **une règle déclarée qui ne
s'applique pas**. Six ont été trouvées le 25/08/2026, toutes documentées comme
actives, toutes absentes du seul mode réellement utilisé (`--decomposed`) :
fenêtres de dates, regroupement mensuel, ordre entre enseignants, ordre CM/TD/TP
par cohorte, bornes de fin de module, plafond hebdomadaire de 22 créneaux.

Aucune ne pouvait être détectée par les tests : chacun testait la FONCTION de
contrainte isolément, et chaque fonction marchait parfaitement — elle n'était
simplement jamais appelée sur le chemin qui compte.

Ce module fait donc deux choses :

1. il tient le **registre des règles métier** connues du projet, avec pour
   chacune le contrôle qui la vérifie sur un résultat réel ;
2. il signale toute règle **sans contrôle associé**. Une règle qu'on ne sait pas
   vérifier n'est pas « probablement bonne », c'est un bug qui n'a pas encore
   été remarqué.

Le registre est volontairement écrit à la main plutôt que déduit du code : c'est
la liste de ce qu'on a PROMIS, à confronter à ce que le solveur FAIT. La déduire
du code reviendrait à demander au code de se noter lui-même.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cal_iut.audit.report import AuditReport, Finding, Severity


@dataclass(frozen=True)
class Regle:
    """Une règle métier promise par la documentation ou la configuration."""

    cle: str
    libelle: str
    source: str  # où elle est déclarée / documentée
    # Identifiant du contrôle de `html_view._rule_checks` qui la vérifie sur un
    # emploi du temps réel. `None` = aucune vérification automatique.
    controle: str | None
    # Ce qu'il faudrait faire si elle n'est pas vérifiable automatiquement.
    note: str = ""


# Ordre = ordre d'importance métier décroissante.
REGLES: tuple[Regle, ...] = (
    Regle("plafond_hebdo", "Plafond horaire hebdomadaire (33h FI / ~35h FC)",
          "README + SolverConfig.fi_weekly_cap_slots", "weekly_cap"),
    Regle("jeudi_pac", "Jeudi après-midi réservé aux PAC (formation initiale)",
          "SolverConfig.enforce_thursday_pac_lock", "thursday_pac"),
    Regle("sae_sanctuarisation", "Jour de SAE = pas de cours classique ce jour",
          "contraintes/09_dates_sae.json", "sae_sanctuarization"),
    Regle("semaine_integration", "Semaine d'intégration sans cours classique (FI)",
          "constraints.add_s1_integration_week_lock", "s1_integration_lock"),
    Regle("ordre_pedagogique", "Ordre des séances au sein d'un même groupe",
          "progression.json", "pedagogical_order"),
    Regle("ordre_cohorte", "Ordre vu par l'étudiant (CM avant les TD/TP qui suivent)",
          "constraints.cohort_sequence_pairs", "cohort_pedagogical_order"),
    Regle("eval_apres_contenu", "Évaluation placée après tout le contenu du module",
          "constraints._add_eval_after_cohort_content_constraints", "eval_after_content"),
    Regle("fenetres_dates", "Fenêtres de dates civiles imposées à une séance",
          "course_scheduling_rules.yaml > session_date_windows", "session_date_windows"),
    Regle("borne_fin_cours", "Borne de fin par cours (max_week_rules)",
          "course_scheduling_rules.yaml > max_week_rules", "course_max_week"),
    Regle("sae_planifiee", "SAE que le solveur doit placer lui-même",
          "course_scheduling_rules.yaml > solver_scheduled_sae", "sae_solver_scheduled"),
    Regle("salle_eval", "Toute évaluation en salle A.018",
          "data/config/rooms.yaml", "eval_room"),
    Regle("capacite_salle", "Capacité de la salle suffisante pour la cohorte",
          "data/config/rooms.yaml", "room_capacity"),
    Regle("salle_non_partagee", "Une salle n'accueille jamais deux cours en même temps",
          "solver/rooms.py::assign_rooms", "room_double_booking"),
    Regle("ordonnancement", "Ordonnancement inter-matières (before/after), critère moyenne",
          "progression.json > ordonnancement", "ordonnancement"),
    Regle("ordonnancement_strict", "Module terminé avant le démarrage du suivant",
          "assign_weeks.strict_ordonnancement_weight", "ordonnancement_strict"),
    # --- Règles SANS contrôle automatique : c'est ici que se cachent les bugs ---
    Regle("regroupement_mensuel", "Regroupement mensuel des interventions (ARA, JHU)",
          "contraintes/05 > regroupement_mensuel_max_semaines", "teacher_monthly_clustering"),
    Regle("ordre_enseignants_module", "Ordre entre enseignants d'un module (WRA505C : ALO puis AFR)",
          "course_scheduling_rules.yaml > teacher_order_rules", "course_teacher_order"),
    Regle("repartition_alternee", "Répartition alternée des enseignants (WRA507D)",
          "course_scheduling_rules.yaml > teacher_distribution", None,
          note="Vérifiable à l'ingestion, pas sur le résultat : cf. tests/test_ordonnancement_2026_08_25.py."),
    Regle("phases_sae", "Répartition des jours d'une SAE entre ses enseignants",
          "data/config/sae_teacher_phases.yaml", None,
          note="Se traduit en disponibilités enseignant ; vérifiable via les violations de dispo."),
    Regle("duo_salle_rare", "Duos synchronisés sur une salle rare",
          "data/config/teacher_duos.yaml", "duo_rare_room"),
    Regle("blocs_collés", "Séances fusionnées en blocs de 3h / 4h30",
          "data/config/double_sessions.yaml", "double_sessions"),
    Regle("presence_alternance", "Cours FC uniquement les semaines de présence IUT",
          "contraintes/03_calendrier_alternance_officiel.json", "alternance_presence"),
    Regle("dispos_enseignants", "Indisponibilités et listes blanches enseignant",
          "contraintes/05_enseignants_contraintes.json", "teacher_availability"),
)


def audit_coverage(report: AuditReport, checks_presents: set[str] | None = None) -> None:
    """Confronte le registre aux contrôles réellement disponibles.

    `checks_presents` : identifiants renvoyés par `_rule_checks` sur un run réel.
    Absent, seule la couverture théorique du registre est examinée.
    """
    sans_controle = [r for r in REGLES if r.controle is None]
    if sans_controle:
        report.add(Finding(
            Severity.INFO,
            "couverture.regle_non_verifiee",
            f"{len(sans_controle)} règle(s) métier n'ont AUCUNE vérification automatique sur "
            "le résultat : rien ne signalerait qu'elles cessent de s'appliquer.",
            quoi_faire=(
                "C'est la famille de bugs la plus coûteuse du projet (6 trouvées le "
                "25/08/2026, toutes documentées « actives » et jamais appliquées en "
                "`--decomposed`). Ajouter un contrôle dans "
                "`export/html_view.py::_rule_checks` pour chacune."),
            ou="src/cal_iut/audit/coverage_audit.py > REGLES",
            details=[f"{r.cle} — {r.libelle} ({r.source}) : {r.note}" for r in sans_controle],
        ))

    if checks_presents is None:
        return

    attendus = {r.controle for r in REGLES if r.controle}
    manquants = sorted(attendus - checks_presents)
    # Certains contrôles s'auto-désactivent faute de données plutôt que de
    # produire un verdict faux : `eval_room` et `room_double_booking` n'existent
    # que si des salles ont été affectées, ce que `cal-iut solve` ne fait que
    # sur un run COMPLET. Les signaler comme erreurs sur un run partiel noierait
    # les vrais manques.
    depend_des_salles = {"eval_room", "room_capacity", "room_double_booking"}
    # Il suffit qu'un seul manque pour que la cause soit « pas de salles » :
    # `room_capacity` ne s'affiche que si `rooms` est fourni, les deux autres
    # que si des salles ont été affectées — les trois disparaissent ensemble ou
    # par sous-ensemble selon le chemin d'appel.
    sans_salles = bool(depend_des_salles & set(manquants))
    if sans_salles:
        manquants = [m for m in manquants if m not in depend_des_salles]
        report.add(Finding(
            Severity.INFO,
            "couverture.controles_salles_inactifs",
            "Les contrôles de salle ne s'appliquent pas : aucune salle n'a été affectée "
            "(le run est incomplet, `cal-iut solve` n'attribue les salles qu'en cas de succès).",
            quoi_faire="Reprendre l'audit une fois un run complet obtenu.",
            ou="export/html_view.py::_rule_checks",
        ))
    if manquants:
        report.add(Finding(
            Severity.ERREUR,
            "couverture.controle_absent",
            f"{len(manquants)} contrôle(s) attendu(s) ne figurent pas dans le tableau de bord "
            "du run analysé : la règle correspondante n'a donc pas été vérifiée.",
            quoi_faire=(
                "Soit le contrôle a disparu de `_rule_checks`, soit il s'est auto-désactivé "
                "faute de données (ex. `eval_room` sans salles affectées). Vérifier lequel."),
            ou="export/html_view.py::_rule_checks",
            details=manquants,
        ))
    else:
        report.ok("couverture.controles",
                  f"les {len(attendus)} contrôles attendus sont tous présents dans le run")

    inconnus = sorted(checks_presents - attendus)
    if inconnus:
        report.add(Finding(
            Severity.INFO,
            "couverture.controle_hors_registre",
            f"{len(inconnus)} contrôle(s) existent sans être déclarés au registre des règles.",
            quoi_faire="Les ajouter à `REGLES` pour que la couverture reste lisible.",
            ou="src/cal_iut/audit/coverage_audit.py > REGLES",
            details=inconnus,
        ))


def audit_solver_paths(report: AuditReport, project_root: Path) -> None:
    """Compare ce que pose le modèle JOINT et ce que pose le mode DÉCOMPOSÉ.

    Contrôle purement textuel — il lit quelles fonctions de contrainte sont
    appelées dans chaque fichier — et c'est assumé : le but n'est pas de prouver
    l'équivalence des deux chemins (elle n'existe pas, ils sont structurés
    différemment) mais de faire remonter à l'écran toute contrainte présente
    d'un côté et absente de l'autre, pour qu'un humain tranche. C'est exactement
    ce qu'une relecture ligne à ligne a fini par trouver le 25/08/2026, après
    coup.
    """
    src = project_root / "src" / "cal_iut" / "solver"
    joint = (src / "cpsat.py").read_text(encoding="utf-8") if (src / "cpsat.py").exists() else ""
    decompose = (
        (src / "decomposed.py").read_text(encoding="utf-8")
        if (src / "decomposed.py").exists()
        else ""
    )
    if not joint or not decompose:
        return

    # Contraintes/objectifs dont l'absence d'un côté est un vrai risque. Les
    # équivalents ré-implémentés en ligne dans `assign_weeks` (plafonds,
    # ordonnancement, lissage) sont listés avec leur marqueur propre.
    equivalents = {
        "add_session_date_window_constraints": "add_session_date_window_constraints",
        "add_teacher_monthly_clustering_penalties": "add_teacher_monthly_clustering_penalties",
        "add_course_teacher_order_penalties": "add_course_teacher_order_penalties",
        "add_cohort_sequence_constraints": "add_cohort_sequence_constraints",
        "add_pedagogical_sequence_constraints": "add_pedagogical_sequence_constraints",
        "add_thursday_afternoon_pac_lock": "add_thursday_afternoon_pac_lock",
        "add_teacher_availability_constraints": "add_teacher_availability_constraints",
        "add_student_presence_constraints": "add_student_presence_constraints",
        "add_duo_synchronized_rare_room_constraints": "add_duo_synchronized_rare_room_constraints",
        "add_blocked_calendar_constraints": "add_blocked_calendar_constraints",
        "add_duration_domain_constraints": "add_duration_domain_constraints",
        "add_planning_event_block_constraints": "add_planning_event_block_constraints",
        "add_course_min_week_constraints": "load_course_min_week_rules",
        # Ré-implémenté en ligne dans `assign_weeks` (`week_var[s.id] != 0`)
        # plutôt qu'appelé : le marqueur cible ce code-là.
        "add_s1_integration_week_lock": "!= 0",
        "add_sae_sanctuarization_constraints": "_apply_sae_sanctuarization_for_week",
        "add_weekly_hour_cap_constraints": "fi_cap_slots",
        "add_ordonnancement_constraints": "ordonnancement_weight",
        "add_eval_clustering_penalties": "eval_clustering_weight",
        "add_semester_spread_penalties": "spread_weight",
    }

    def appel_de_fonction(texte: str, nom: str) -> bool:
        """Vrai appel, pas une mention en commentaire ou dans un import."""
        return f"{nom}(" in texte

    def present(texte: str, marqueur: str, *, nom: str) -> bool:
        # Quand le marqueur EST le nom de la fonction, on exige un vrai appel :
        # une mention en commentaire ne prouve rien (c'était précisément le cas
        # des six règles absentes trouvées le 25/08/2026, toutes citées en
        # commentaire côté décomposé sans y être posées).
        if marqueur == nom:
            return appel_de_fonction(texte, marqueur)
        # Sinon le marqueur désigne une ré-implémentation en ligne (un plafond,
        # un poids d'objectif, un test direct sur `week_var`) : sa simple
        # présence suffit, c'est un repère choisi à la main.
        return marqueur in texte

    manquantes = [
        nom
        for nom, marqueur in equivalents.items()
        if appel_de_fonction(joint, nom) and not present(decompose, marqueur, nom=nom)
    ]
    if manquantes:
        report.add(Finding(
            Severity.ERREUR,
            "couverture.regle_absente_du_decompose",
            f"{len(manquantes)} contrainte(s) posée(s) par le modèle joint n'ont aucun "
            "équivalent repéré dans le solveur décomposé — or c'est ce dernier qui produit "
            "les emplois du temps réels (`--decomposed`).",
            quoi_faire=(
                "Vérifier chacune : soit la poser aussi côté décomposé, soit documenter "
                "explicitement pourquoi elle n'y a pas de sens. Six règles étaient dans ce "
                "cas le 25/08/2026, toutes annoncées actives dans le README."),
            ou="solver/cpsat.py vs solver/decomposed.py",
            details=sorted(manquantes),
        ))
    else:
        report.ok("couverture.parite_solveurs",
                  "toute contrainte du modèle joint a un équivalent côté décomposé")
