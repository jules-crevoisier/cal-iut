"""Pipeline d'ingestion complet."""

import json
import warnings
from collections.abc import Iterable
from pathlib import Path

from cal_iut.ingestion.config_loader import (
    load_additional_courses,
    load_course_corrections,
    load_double_sessions,
    load_groups,
    load_rooms,
    load_teacher_availability,
    load_teacher_distributions,
    load_teacher_duos,
)
from cal_iut.ingestion.fetch import fetch_all_exports_sync
from cal_iut.ingestion.merge import apply_teacher_corrections, merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.models.entities import Course
from cal_iut.models.session import SessionToPlace

# Run global multi-parcours (retour utilisateur : "il faut que tu fasses les
# choses nécessaires pour que les parcours fonctionnent tous ensemble") :
# S1/S3/S5 (et séparément S2/S4/S6) démarrent la même semaine calendaire et
# partagent le même horizon par construction (`semester_week_offset`/
# `default_horizon_weeks` renvoient des valeurs identiques pour les 3), donc
# combiner TOUS les parcours d'un même groupe dans un seul run garantit
# qu'un enseignant partagé entre parcours n'est jamais programmé à 2 endroits
# à la fois — chose qu'un run par parcours indépendant ne peut pas détecter.
# cf. docs/DATA.md pour la validation empirique (Groupe A : 0 conflit inter-
# parcours sur BUT1+BUT2+BUT3 S1/S3/S5 réels, 3108 séances).
SEMESTRE_GROUPS: dict[str, set[str]] = {
    "odd": {"S1", "S3", "S5"},
    "even": {"S2", "S4", "S6"},
}
SEMESTRE_GROUP_ANCHOR: dict[str, str] = {"odd": "S1", "even": "S2"}

# Semestres sans données de dates SAE pour 2026-2027 : le fichier officiel
# « DATES SAE 2026_2027 » ne date que les SAE de S1/S3/S5. Arbitrage
# utilisateur du 10/08/2026 (« CSV uniquement, S2/S4/S6 hors périmètre ») :
# plutôt que de générer S2/S4/S6 sans aucune sanctuarisation SAE — donc avec
# des cours classiques librement plaçables sur des journées de projet — on
# avertit explicitement. Retirer un semestre d'ici dès que ses dates arrivent.
SEMESTRES_HORS_PERIMETRE: set[str] = {"S2", "S4", "S6"}


def out_of_scope_semestres(semestres: Iterable[str]) -> list[str]:
    """Semestres demandés qui n'ont pas de dates SAE cette année."""
    return sorted(set(semestres) & SEMESTRES_HORS_PERIMETRE)


class IngestionResult:
    def __init__(
        self,
        courses: list[Course],
        sessions: list[SessionToPlace],
        stats: dict[str, object],
    ) -> None:
        self.courses = courses
        self.sessions = sessions
        self.stats = stats


def _load_cached_or_fetch(config_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """
    Préfère le cache local (`contraintes/maquette.json`/`progression.json`,
    régénéré par `scripts/build_contraintes.py`) à un fetch réseau — même
    source que `cal-iut ingest --from-cache contraintes` en CLI.

    Corrige un vrai bug trouvé le 11/08/2026 : `api/main.py::_try_restore_latest`
    (restauration du dernier run au démarrage du serveur) appelait
    `run_ingestion(...)` SANS cache, donc en fetch réseau LIVE — alors que le
    planning stocké en base avait, lui, été calculé via le CLI en
    `--from-cache` (déterministe). Un redémarrage du serveur pouvait ainsi
    ré-ingérer une image légèrement différente de celle réellement résolue
    (un fetch amont ayant changé entre-temps), désynchronisant `state.groups`/
    `state.sessions_by_id` du planning stocké — jusqu'à faire planter
    `/app-state` entier sur un `group_id` que le fetch live ne reconnaissait
    plus (cf. `solver/rooms.py::_headcount_for_groups`, docs/DATA.md §52.1).

    Absence des deux fichiers cache (ex. environnement de dev sans
    `contraintes/` régénéré) = repli sur le fetch réseau, comportement
    inchangé.
    """
    root = config_dir.parents[1]
    maquette_path = root / "contraintes" / "maquette.json"
    progression_path = root / "contraintes" / "progression.json"
    if maquette_path.exists() and progression_path.exists():
        maquette = json.loads(maquette_path.read_text(encoding="utf-8"))
        progression = json.loads(progression_path.read_text(encoding="utf-8"))
        return maquette, progression
    return fetch_all_exports_sync()


def run_ingestion(
    config_dir: Path,
    *,
    maquette: list[dict[str, object]] | None = None,
    progression: list[dict[str, object]] | None = None,
    parcours: str | None = None,
    semestre: str | None = None,
    semestre_group: str | None = None,
) -> IngestionResult:
    if maquette is None or progression is None:
        maquette, progression = _load_cached_or_fetch(config_dir)

    # Cours manuels absents de l'export distant (cf. additional_courses.yaml)
    # — injectés ici pour traverser EXACTEMENT le même pipeline qu'une vraie
    # ligne maquette (fusion, corrections, expansion en séances).
    maquette = list(maquette) + load_additional_courses(config_dir)

    # `semestre_group` ingère TOUS les parcours (le filtrage par groupe de
    # semestres concurrents se fait après coup, sur la liste de sessions déjà
    # étendue) : prioritaire sur parcours/semestre si les deux sont fournis.
    if semestre_group:
        parcours = None
        semestre = None

    courses = merge_exports(maquette, progression)
    courses = apply_teacher_corrections(courses, load_course_corrections(config_dir))
    groups = load_groups(config_dir)
    rooms = load_rooms(config_dir)
    teachers_avail = load_teacher_availability(config_dir)
    double_session_rules = load_double_sessions(config_dir)
    duos = load_teacher_duos(config_dir)
    teacher_distributions = load_teacher_distributions(config_dir)
    sessions = expand_all_sessions(
        courses,
        groups,
        parcours=parcours,
        semestre=semestre,
        double_session_rules=double_session_rules,
        duos=duos,
        teacher_distributions=teacher_distributions,
    )
    if semestre_group:
        wanted = SEMESTRE_GROUPS[semestre_group]
        sessions = [s for s in sessions if s.semestre in wanted]

    requested = set(SEMESTRE_GROUPS[semestre_group]) if semestre_group else ({semestre} if semestre else set())
    out_of_scope = out_of_scope_semestres(requested)
    if out_of_scope:
        warnings.warn(
            f"{', '.join(out_of_scope)} : aucune date SAE fournie pour 2026-2027 "
            "(le fichier « DATES SAE 2026_2027 » ne couvre que S1/S3/S5). Les cours "
            "classiques de ces semestres seront placés SANS sanctuarisation SAE — "
            "cf. contraintes/08_alertes_qualite_donnees.json.",
            stacklevel=2,
        )

    stats: dict[str, object] = {
        "courses_total": len(courses),
        "courses_with_progression": sum(1 for c in courses if c.progression_defined),
        "courses_with_ordonnancement": sum(1 for c in courses if c.ordonnancement),
        "courses_with_commentaire_edt": sum(
            1 for c in courses if c.commentaire_edt and c.commentaire_edt != "UPDATE_OMEGA"
        ),
        "sessions_total": len(sessions),
        "groups_configured": len(groups),
        "rooms_configured": len(rooms),
        "teachers_with_availability": len(teachers_avail),
        "filter_parcours": parcours,
        "filter_semestre": semestre,
        "semestre_group": semestre_group,
    }

    if parcours or semestre:
        filtered_courses = [
            c
            for c in courses
            if (not parcours or c.parcours == parcours) and (not semestre or c.semestre == semestre)
        ]
        stats["courses_filtered"] = len(filtered_courses)

    return IngestionResult(courses=courses, sessions=sessions, stats=stats)
