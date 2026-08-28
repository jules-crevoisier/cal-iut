"""« Quelles règles sont actives en ce moment ? » — en français, sans YAML.

Une personne qui reprend l'outil doit pouvoir répondre à cette question avant de
toucher à quoi que ce soit. Les règles vivent dans six fichiers de configuration
et trois fichiers de contraintes générés ; les lire suppose de connaître leur
format, ce qui est exactement ce qu'on veut éviter.

Chaque règle est restituée avec **sa raison** (le champ `note` des YAML, qui
consigne qui l'a demandée et pourquoi). Une règle dont on ne sait plus la raison
finit supprimée à tort, ou conservée à tort — les deux coûtent cher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RegleLisible:
    categorie: str
    resume: str
    raison: str = ""
    ou: str = ""

    def to_text(self) -> str:
        lignes = [f"  - {self.resume}"]
        if self.raison:
            # Les `note:` des YAML sont écrites sur plusieurs lignes.
            raison = " ".join(self.raison.split())
            if len(raison) > 300:
                raison = raison[:297] + "…"
            lignes.append(f"      raison : {raison}")
        if self.ou:
            lignes.append(f"      fichier : {self.ou}")
        return "\n".join(lignes)


@dataclass
class Inventaire:
    regles: list[RegleLisible] = field(default_factory=list)

    def par_categorie(self) -> dict[str, list[RegleLisible]]:
        out: dict[str, list[RegleLisible]] = {}
        for r in self.regles:
            out.setdefault(r.categorie, []).append(r)
        return out

    def to_text(self) -> str:
        lignes: list[str] = []
        for categorie, regles in self.par_categorie().items():
            lignes.append("")
            lignes.append("=" * 70)
            lignes.append(f"{categorie} ({len(regles)})")
            lignes.append("=" * 70)
            lignes.extend(r.to_text() for r in regles)
        lignes.append("")
        lignes.append(f"{len(self.regles)} règle(s) déclarée(s) au total.")
        lignes.append(
            "Pour en ajouter ou en modifier : cf. le tableau du § 6 de GUIDE.md. "
            "Après toute modification, lancez `cal-iut audit`."
        )
        return "\n".join(lignes)


def _label_semaine(calendar, index: int) -> str:
    libelle = calendar.department_week_label(index) if calendar else None
    return libelle or f"semaine-index {index}"


def inventorier(project_root: Path) -> Inventaire:
    from cal_iut.calendar.academic import build_default_calendar_2026_2027
    from cal_iut.ingestion.config_loader import (
        load_course_max_week_rules,
        load_course_min_week_rules,
        load_course_teacher_orders,
        load_double_sessions,
        load_groups,
        load_rooms,
        load_sae_teacher_phases,
        load_session_date_windows,
        load_solver_scheduled_sae,
        load_teacher_distributions,
        load_teacher_duos,
        load_weekly_cap_exceptions,
    )

    config = project_root / "data" / "config"
    calendar = build_default_calendar_2026_2027()
    inv = Inventaire()
    yaml_ref = "data/config/course_scheduling_rules.yaml"

    for g in load_groups(config):
        if g.kind == "promo":
            inv.regles.append(RegleLisible(
                "Groupes étudiants",
                f"{g.parcours} : promotion « {g.label} », {g.headcount} étudiants",
                ou="data/config/groups.yaml",
            ))

    salles = load_rooms(config)
    if salles:
        inv.regles.append(RegleLisible(
            "Salles",
            f"{len(salles)} salle(s) déclarée(s), de {min(s.capacity for s in salles)} "
            f"à {max(s.capacity for s in salles)} places",
            ou="data/config/rooms.yaml",
        ))

    for r in load_course_min_week_rules(config):
        inv.regles.append(RegleLisible(
            "Quand un cours peut commencer / doit finir",
            f"{r.course_code} ({r.semestre}) ne commence pas avant la "
            f"{_label_semaine(calendar, r.min_week)}",
            raison=r.note or "", ou=f"{yaml_ref} > min_week_rules",
        ))
    for r in load_course_max_week_rules(config):
        inv.regles.append(RegleLisible(
            "Quand un cours peut commencer / doit finir",
            f"{r.course_code} ({r.semestre}) doit être terminé au plus tard en "
            f"{_label_semaine(calendar, r.max_week)}",
            raison=r.note or "", ou=f"{yaml_ref} > max_week_rules",
        ))

    for r in load_session_date_windows(config):
        cible = r.session_type.value if r.session_type else "toutes les séances"
        precision = f" n° {', '.join(map(str, r.sequence_orders))}" if r.sequence_orders else ""
        quand = (
            f"uniquement le(s) {', '.join(r.only_dates)}"
            if r.only_dates
            else f"entre le {r.start_date} et le {r.end_date}"
        )
        inv.regles.append(RegleLisible(
            "Séances imposées à une date",
            f"{r.course_code} ({r.semestre}) — {cible}{precision} : {quand}",
            raison=r.note or "", ou=f"{yaml_ref} > session_date_windows",
        ))

    for r in load_double_sessions(config):
        duree = {1: "1h30", 2: "3h", 3: "4h30"}.get(r.slots_per_session, f"{r.slots_per_session}×1h30")
        limite = f", au plus {r.max_blocks} bloc(s)" if r.max_blocks else ""
        depuis = " (formés depuis la fin)" if r.pair_from == "end" else ""
        inv.regles.append(RegleLisible(
            "Durée des séances",
            f"{r.course_code} — les {r.session_type.value} sont des blocs de {duree}{limite}{depuis}",
            raison=r.note or "", ou="data/config/double_sessions.yaml",
        ))

    for r in load_course_teacher_orders(config):
        inv.regles.append(RegleLisible(
            "Répartition entre enseignants",
            f"{r.course_code} ({r.semestre}) — ordre souhaité : {' puis '.join(r.teacher_order)}",
            raison=r.note or "", ou=f"{yaml_ref} > teacher_order_rules",
        ))
    for r in load_teacher_distributions(config):
        mode = "alternent une séance sur deux" if r.mode == "alterne" else "se partagent en blocs contigus"
        qui = f" ({' puis '.join(r.teacher_order)})" if r.teacher_order else ""
        inv.regles.append(RegleLisible(
            "Répartition entre enseignants",
            f"{r.course_code} ({r.semestre}) — les enseignants {mode}{qui}",
            raison=r.note or "", ou=f"{yaml_ref} > teacher_distribution",
        ))

    for duo in load_teacher_duos(config):
        inv.regles.append(RegleLisible(
            "Co-animation en salle dédoublée",
            f"{' + '.join(duo.teacher_codes)} sur {', '.join(duo.course_codes)} — "
            f"salles {', '.join(duo.rare_rooms) if duo.rare_rooms else 'non précisées'}",
            raison=duo.note or "", ou="data/config/teacher_duos.yaml",
        ))

    for code, semestre in sorted(load_solver_scheduled_sae(config)):
        inv.regles.append(RegleLisible(
            "SAE",
            f"{code} ({semestre}) est placée par le solveur, et non par ses enseignants",
            ou=f"{yaml_ref} > solver_scheduled_sae",
        ))
    for phase in load_sae_teacher_phases(config):
        exclu = f" (sauf le {', '.join(phase.exclure)})" if phase.exclure else ""
        inv.regles.append(RegleLisible(
            "SAE",
            f"{phase.course_code} — {phase.teacher_code} encadre du {phase.debut} "
            f"au {phase.fin}{exclu}",
            raison=phase.note or "", ou="data/config/sae_teacher_phases.yaml",
        ))

    for exc in load_weekly_cap_exceptions(config):
        inv.regles.append(RegleLisible(
            "Dérogations au plafond horaire",
            f"{exc.parcours} ({exc.semestre}) — semaine du {exc.week_monday} : "
            f"jusqu'à {exc.cap} créneaux au lieu de 22",
            raison=exc.note or "", ou=f"{yaml_ref} > weekly_cap_exceptions",
        ))

    # Contraintes enseignant : issues du CSV, donc trop nombreuses pour être
    # détaillées ici — on en donne le compte et le point d'entrée.
    contraintes_json = project_root / "contraintes" / "05_enseignants_contraintes.json"
    if contraintes_json.exists():
        import json

        entries = json.loads(contraintes_json.read_text(encoding="utf-8"))
        avec_indispo = sum(1 for e in entries if e.get("indisponibilites_raw"))
        listes_blanches = sum(1 for e in entries if e.get("disponibilites_exclusives"))
        inv.regles.append(RegleLisible(
            "Disponibilités des enseignants",
            f"{len(entries)} enseignant(s) déclarés, dont {avec_indispo} avec des "
            f"indisponibilités et {listes_blanches} en liste blanche stricte "
            "(ils ne sont plaçables QUE sur les créneaux listés)",
            raison=(
                "Issu du CSV « CONTRAINTES ENSEIGNANTS ». Le détail par enseignant est "
                "visible dans l'onglet Enseignant de l'interface web."
            ),
            ou="contraintes_update/CONTRAINTES ENSEIGNANTS … .csv",
        ))

    return inv
