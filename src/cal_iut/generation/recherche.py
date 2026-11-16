"""Score d'un résultat du solveur et diagnostic d'un résultat incomplet.

Repris de `scripts/solve_until_ok.py` (qui les importe désormais d'ici) pour
que la génération lancée depuis l'interface compare les tentatives
exactement comme la recette en ligne de commande.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.constraints import cohort_sequence_pairs

SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY


@dataclass
class RunScore:
    """Score d'un run, comparé dans l'ordre LEXICOGRAPHIQUE des champs.

    L'ordre traduit une hiérarchie métier, pas une somme pondérée : une séance
    non placée ne se rattrape par aucune amélioration de confort, et un CM après
    ses TD reste un défaut pédagogique quel que soit le nombre de trous.

    `fi_max_week_violations` EN PREMIER : trouvé le 27/08/2026 — le score
    précédent ne vérifiait jamais que `--fi-max-week` (date de fin de
    semestre FI, retour utilisateur : « les FI doivent finir le 1er février »)
    soit réellement respecté par le run gardé. `data/generated/best.json`
    contenait un run de la veille (avant que ce flag n'existe dans cette
    recherche), avec de la FI en semaine 19 — un dépassement pur et simple —
    et rien ne l'aurait jamais détrôné : il gagnait quand même sur les
    critères suivants. Une relance de la nuit avec `--fi-max-week 18` a
    produit des runs *conformes* mais plus incomplets, tous rejetés par
    l'ancien score alors qu'ils étaient les seuls à respecter la vraie
    contrainte dure demandée.
    """

    fi_max_week_violations: int = 10**9  # séances FI (non-FC) après fi_max_week
    missing: int = 10**9  # séances à placer restées non placées
    cohort_order_violations: int = 10**9  # CM/TD/TP hors ordre pour un étudiant
    strict_overlap_weeks: int = 10**9  # chevauchement des modules ordonnés
    gaps: int = 10**9  # trous dans les journées
    placed: int = 0
    status: str = ""
    seed: int = 0
    detail: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (
            self.fi_max_week_violations,
            self.missing,
            self.cohort_order_violations,
            self.strict_overlap_weeks,
            self.gaps,
            -self.placed,
        )

    def better_than(self, other: RunScore | None) -> bool:
        return other is None or self.key() < other.key()

    def summary(self) -> str:
        # `compute_quality` n'est calculé côté solveur que pour un run
        # OPTIMAL/FEASIBLE (cf. cli.py) : un run PARTIAL_WEEKS_FAILED — le cas
        # normal en cours de recherche — n'a pas de trous mesurés. Le
        # sentinel 10**8 existe pour que `RunScore.better_than` continue de
        # fonctionner (ce champ, en dernier de la hiérarchie, ne décide
        # presque jamais), mais l'afficher tel quel donnait "trous
        # 100000000" — un nombre absurde plutôt qu'une absence de mesure.
        trous = "non mesurés (run partiel)" if self.gaps >= 10**8 else str(self.gaps)
        fi = (
            "fin FI OK" if self.fi_max_week_violations == 0
            else f"fin FI DÉPASSÉE x{self.fi_max_week_violations}"
        )
        return (
            f"{self.status} | {fi} | {self.placed} placées, {self.missing} manquantes | "
            f"ordre cohorte {self.cohort_order_violations} | "
            f"chevauchement {self.strict_overlap_weeks} sem. | trous {trous}"
        )


def load_sessions(path: Path) -> list[SessionToPlace]:
    return [SessionToPlace.model_validate(s) for s in json.loads(path.read_text(encoding="utf-8"))]


def seances_a_placer(
    sessions: list[SessionToPlace], scheduled_sae: set[tuple[str, str]]
) -> list[SessionToPlace]:
    """Séances que le solveur doit poser : tout sauf les SAE datées (code
    `WS…`), qui occupent des journées entières fixées par le calendrier — à
    moins que la SAE soit déclarée « placée par le solveur »."""
    return [
        s
        for s in sessions
        if not s.course_code.upper().startswith("WS")
        or (s.course_code.upper(), s.semestre) in scheduled_sae
    ]


def score_run(
    timetable: dict,
    sessions: list[SessionToPlace],
    groups: list,
    *,
    fi_max_week: int | None = None,
    scheduled_sae: set[tuple[str, str]],
) -> RunScore:
    placements = timetable.get("placements") or []
    placed_ids = {p["session_id"] for p in placements}

    fi_max_week_violations = 0
    if fi_max_week is not None:
        by_id = {s.id: s for s in sessions}
        for p in placements:
            s = by_id.get(p["session_id"])
            if s is not None and "FC" not in s.parcours and p["week"] > fi_max_week:
                fi_max_week_violations += 1

    to_place = seances_a_placer(sessions, scheduled_sae)
    missing = sum(1 for s in to_place if s.id not in placed_ids)

    t_of = {
        p["session_id"]: p["week"] * SLOTS_PER_WEEK + p["day"] * SLOTS_PER_DAY + p["slot"]
        for p in placements
    }
    placed_sessions = [s for s in sessions if s.id in t_of]

    pairs = cohort_sequence_pairs(placed_sessions, groups)
    cohort_violations = sum(1 for a, b in pairs if not (t_of[a] < t_of[b]))

    # Chevauchement strict des relations before/after, en semaines cumulées.
    by_group_course: dict[tuple[str, str], list[int]] = defaultdict(list)
    for s in placed_sessions:
        for gid in s.group_ids:
            by_group_course[(s.course_code, gid)].append(t_of[s.id])
    relations = {
        (s.course_code, str(o.get("position")), str(o.get("target_course_code")))
        for s in sessions
        for o in (s.metadata.get("ordonnancement") or [])
        if str(o.get("position")) in ("before", "after") and o.get("target_course_code")
    }
    overlap = 0
    for code, pos, target in relations:
        ga = {g for (c, g) in by_group_course if c == code}
        gb = {g for (c, g) in by_group_course if c == target}
        for gid in ga & gb:
            ta, tb = by_group_course[(code, gid)], by_group_course[(target, gid)]
            first, last = (tb, ta) if pos == "before" else (ta, tb)
            slots = max(last) - min(first) + 1
            if slots > 0:
                overlap += slots // SLOTS_PER_WEEK + 1

    quality = timetable.get("quality") or {}
    gaps = int(quality.get("total_gaps") or 0) if quality else 10**8

    return RunScore(
        fi_max_week_violations=fi_max_week_violations,
        missing=missing,
        cohort_order_violations=cohort_violations,
        strict_overlap_weeks=overlap,
        gaps=gaps,
        placed=len(placements),
        status=str(timetable.get("status", "")),
        detail={"pairs_checked": len(pairs), "relations": len(relations)},
    )


def diagnostiquer(
    timetable: dict, sessions: list[SessionToPlace], racine: Path, semestre_ancre: str = "S1"
) -> list[str]:
    """Pourquoi ce run est-il incomplet ? Réutilise l'audit de capacité.

    Sans ça, le journal ne dirait que « PARTIAL_WEEKS_FAILED:[7, 15] », ce qui
    n'apprend rien au réveil. Avec, il nomme la semaine ET la ressource qui
    sature — c'est exactement ce qu'il a fallu vingt minutes de bisection
    manuelle pour obtenir la première fois (cf. docs/DATA.md §63.9ter).
    """
    statut = str(timetable.get("status", ""))
    if not statut.startswith("PARTIAL_WEEKS_FAILED"):
        return []
    try:
        from cal_iut.audit.capacity_audit import audit_weekly_capacity
        from cal_iut.audit.report import AuditReport
        from cal_iut.calendar.academic import semester_week_offset
        from cal_iut.ingestion.config_loader import load_teacher_availability
        from cal_iut.ingestion.constraints_loader import (
            load_all_constraints,
            merge_teacher_availability,
        )

        bundle = load_all_constraints(racine)
        avail = merge_teacher_availability(
            load_teacher_availability(racine / "data" / "config"), bundle.teachers
        )
        par_semaine: dict[int, list[SessionToPlace]] = defaultdict(list)
        par_id = {s.id: s for s in sessions}
        for p in timetable.get("placements") or []:
            session = par_id.get(p["session_id"])
            if session is not None:
                par_semaine[p["week"]].append(session)
        report = AuditReport()
        audit_weekly_capacity(
            par_semaine, avail, bundle.calendar,
            semester_week_offset(bundle.calendar, semestre_ancre), report,
        )
        return [f.message for f in report.findings]
    except Exception as exc:  # noqa: BLE001 - un diagnostic ne doit jamais casser la boucle
        return [f"diagnostic indisponible : {exc.__class__.__name__} {exc}"]
