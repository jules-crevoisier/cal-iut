"""Relance `cal-iut solve` jusqu'à obtenir le meilleur emploi du temps possible.

Pourquoi un script plutôt qu'une boucle à la main : la résolution n'est pas
reproductible d'un run à l'autre (cf. docs/DATA.md §63.9ter — `max_time_in_seconds`
combiné à plusieurs workers CP-SAT rend le résultat dépendant de quel worker a
fini quoi à l'échéance). Deux exécutions identiques peuvent donner l'une un run
complet, l'autre deux semaines en échec. Relancer avec une graine différente est
le levier le plus efficace, et de loin le moins coûteux, pour sortir d'un échec
local — c'est déjà la stratégie utilisée à l'intérieur du solveur
(`_solve_week_with_retry`), appliquée ici à l'échelle du run entier.

Le script garde le MEILLEUR run rencontré, jamais le dernier, selon un score
lexicographique explicite (cf. `score_run`) — même piège que celui corrigé le
12/08/2026 sur `TimetableSolver.solve_decomposed`, où la boucle de tentatives
écrasait un bon résultat par un moins bon.

    python scripts/solve_until_ok.py --max-hours 8

Journal complet dans `data/generated/solve_runs.jsonl` (une ligne par tentative,
relisible ensuite pour comparer les graines).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cal_iut.ingestion.config_loader import load_groups
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


def solver_scheduled_sae() -> set[tuple[str, str]]:
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    return load_solver_scheduled_sae(ROOT / "data" / "config")


def score_run(
    timetable: dict, sessions: list[SessionToPlace], groups: list, *, fi_max_week: int | None = None,
) -> RunScore:
    placements = timetable.get("placements") or []
    placed_ids = {p["session_id"] for p in placements}
    scheduled = solver_scheduled_sae()

    fi_max_week_violations = 0
    if fi_max_week is not None:
        by_id = {s.id: s for s in sessions}
        for p in placements:
            s = by_id.get(p["session_id"])
            if s is not None and "FC" not in s.parcours and p["week"] > fi_max_week:
                fi_max_week_violations += 1

    to_place = [
        s
        for s in sessions
        if not s.course_code.upper().startswith("WS")
        or (s.course_code.upper(), s.semestre) in scheduled
    ]
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


def run_once(seed: int, out: Path, args: argparse.Namespace) -> tuple[int, str]:
    cmd = [
        sys.executable, "-u", "-m", "cal_iut.cli", "solve", "--decomposed",
        "--semestre-group", args.semestre_group,
        "--weeks", str(args.weeks),
        "--fi-max-week", str(args.fi_max_week),
        "--spread-weight", str(args.spread_weight),
        "--random-seed", str(seed),
        # Une seule passe interne : la diversité de graines vient de CETTE
        # boucle, qui journalise et garde le meilleur. Laisser le solveur
        # relancer 3 fois en interne triplerait la durée de chaque tentative
        # sans rien apporter de plus.
        "--attempts", "1",
        "--output", str(out),
    ]
    if args.no_sae_supervisor_hard:
        cmd.append("--no-sae-supervisor-hard")
    if getattr(args, "num_workers", None) is not None:
        cmd += ["--num-workers", str(args.num_workers)]
    if args.last_resort_seconds is not None:
        cmd += ["--last-resort-seconds", str(args.last_resort_seconds)]
    if args.last_resort_seeds is not None:
        cmd += ["--last-resort-seeds", str(args.last_resort_seeds)]
    if args.benders_rounds is not None:
        cmd += ["--benders-rounds", str(args.benders_rounds)]
    if args.warm_start and Path(args.warm_start).exists():
        cmd += ["--warm-start", args.warm_start]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    status = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("Solver status:"):
            status = line.split(":", 1)[1].strip()
    return proc.returncode, status or (proc.stderr or "")[-300:]


def diagnostiquer(timetable: dict, sessions: list[SessionToPlace]) -> list[str]:
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

        bundle = load_all_constraints(ROOT)
        avail = merge_teacher_availability(
            load_teacher_availability(ROOT / "data" / "config"), bundle.teachers
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
            semester_week_offset(bundle.calendar, "S1"), report,
        )
        return [f.message for f in report.findings]
    except Exception as exc:  # noqa: BLE001 - un diagnostic ne doit jamais casser la boucle
        return [f"diagnostic indisponible : {exc.__class__.__name__} {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--max-runs", type=int, default=40)
    parser.add_argument("--semestre-group", default="odd")
    parser.add_argument("--weeks", type=int, default=24)
    parser.add_argument("--fi-max-week", type=int, default=18)
    parser.add_argument("--spread-weight", type=int, default=8)
    parser.add_argument("--no-sae-supervisor-hard", action="store_true", default=True)
    parser.add_argument("--warm-start", default=None)
    parser.add_argument(
        "--num-workers", type=int, default=None,
        help=(
            "Parallélisme CP-SAT PAR TENTATIVE (transmis à `cal-iut solve --num-workers`). "
            "Non fourni = tous les processeurs logiques (comportement historique, une seule "
            "recherche à la fois). À réduire explicitement (ex. 8 sur 16 threads) pour "
            "lancer PLUSIEURS instances de ce script en parallèle sans sur-souscription — "
            "cf. `--best`/`--journal`, à donner des chemins distincts entre instances."
        ),
    )
    # Défauts VOLONTAIREMENT plus courts qu'en run manuel : en boucle, dix
    # tentatives de graines différentes valent mieux qu'une qui s'acharne.
    parser.add_argument("--last-resort-seconds", type=float, default=90.0)
    parser.add_argument("--last-resort-seeds", type=int, default=3)
    parser.add_argument("--benders-rounds", type=int, default=None)
    parser.add_argument("--first-seed", type=int, default=2027)
    parser.add_argument("--seed-step", type=int, default=1013)
    parser.add_argument("--best", default=str(ROOT / "data" / "generated" / "timetable_best.json"))
    parser.add_argument("--journal", default=str(ROOT / "data" / "generated" / "solve_runs.jsonl"))
    # Continuer même après un run parfait, pour améliorer le confort (trous) :
    # un run "0 manquante, 0 hors ordre" reste améliorable.
    parser.add_argument("--stop-when-perfect", action="store_true")
    parser.add_argument(
        "--sans-completion",
        action="store_true",
        help="Ne pas compléter le meilleur run à la fin (cf. `cal-iut completer`)",
    )
    args = parser.parse_args()

    sessions = load_sessions(ROOT / "data" / "generated" / "sessions.json")
    groups = load_groups(ROOT / "data" / "config")
    best_path = Path(args.best)
    journal = Path(args.journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    # Dérivé du NOM de `--best`, jamais un nom fixe : trouvé le 27/08/2026 en
    # préparant deux recherches en parallèle (retour utilisateur : "pas
    # possible de faire plusieurs run en parallèle ?") — un nom fixe
    # ("timetable_attempt.json") aurait fait écrire les deux processus dans
    # LE MÊME fichier temporaire malgré des `--best` différents (même
    # dossier), corrompant le résultat de l'un ou l'autre au hasard du
    # timing.
    tmp = best_path.with_name(best_path.stem + "_attempt" + best_path.suffix)

    best: RunScore | None = None
    if best_path.exists():
        try:
            best = score_run(json.loads(best_path.read_text(encoding="utf-8")), sessions, groups, fi_max_week=args.fi_max_week)
            print(f"[reprise] meilleur connu : {best.summary()}", flush=True)
        except (json.JSONDecodeError, KeyError, OSError):
            best = None

    deadline = time.time() + args.max_hours * 3600
    for i in range(args.max_runs):
        if time.time() > deadline:
            print("[stop] budget horaire épuisé", flush=True)
            break
        seed = args.first_seed + i * args.seed_step
        # Effacer la sortie de la tentative PRÉCÉDENTE : un run qui plante sans
        # rien écrire laisserait sinon scorer l'ancien fichier comme s'il venait
        # d'être produit, et la boucle croirait avoir progressé.
        tmp.unlink(missing_ok=True)
        started = time.time()
        print(f"\n=== tentative {i + 1} (graine {seed}) — {datetime.now():%H:%M:%S}", flush=True)
        code, status = run_once(seed, tmp, args)
        elapsed = round(time.time() - started)

        entry = {
            "run": i + 1, "seed": seed, "exit_code": code, "status": status,
            "seconds": elapsed, "at": datetime.now().isoformat(timespec="seconds"),
        }
        if tmp.exists():
            try:
                score = score_run(json.loads(tmp.read_text(encoding="utf-8")), sessions, groups, fi_max_week=args.fi_max_week)
            except (json.JSONDecodeError, KeyError) as exc:
                score = None
                entry["error"] = f"sortie illisible : {exc}"
            if score is not None:
                entry.update({
                    "missing": score.missing,
                    "placed": score.placed,
                    "cohort_order_violations": score.cohort_order_violations,
                    "strict_overlap_weeks": score.strict_overlap_weeks,
                    "gaps": score.gaps,
                })
                print(f"    {elapsed}s — {score.summary()}", flush=True)
                if score.missing:
                    raisons = diagnostiquer(
                        json.loads(tmp.read_text(encoding="utf-8")), sessions
                    )
                    if raisons:
                        entry["pourquoi"] = raisons
                        for r in raisons[:3]:
                            print(f"      cause : {r}", flush=True)
                if score.better_than(best):
                    shutil.copyfile(tmp, best_path)
                    best = score
                    best.seed = seed
                    entry["kept"] = True
                    print(f"    -> NOUVEAU MEILLEUR, conservé dans {best_path.name}", flush=True)
                if (
                    args.stop_when_perfect
                    and score.missing == 0
                    and score.cohort_order_violations == 0
                ):
                    with journal.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    print("[stop] run parfait atteint", flush=True)
                    break
        else:
            entry["error"] = "aucune sortie produite"
            print(f"    {elapsed}s — échec : {status}", flush=True)

        with journal.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if best is None:
        print("\nAucun run exploitable.", flush=True)
        return 1
    print(f"\nMEILLEUR RUN (graine {best.seed}) : {best.summary()}", flush=True)
    print(f"  -> {best_path}", flush=True)

    # Complétion du MEILLEUR run seulement, jamais de chaque tentative : elle
    # coûte une dizaine de minutes, et compléter un mauvais run ne le rend pas
    # bon — le score qui décide doit rester celui du solveur.
    #
    # Elle vaut la peine, en revanche, sur celui qu'on garde : mesuré le
    # 26/08/2026 sur un run réel, 899 des 918 séances manquantes avaient un
    # créneau parfaitement valable ailleurs dans le semestre (cf. docs/DATA.md
    # §66). Les laisser de côté serait perdre des heures d'enseignement pour
    # rien.
    if best.missing and not args.sans_completion:
        print(f"\nComplétion des {best.missing} séance(s) restantes…", flush=True)
        code = subprocess.call(
            [sys.executable, "-m", "cal_iut.cli", "completer", "--timetable", str(best_path)],
            cwd=ROOT,
        )
        if code == 0:
            complete = score_run(json.loads(best_path.read_text(encoding="utf-8")), sessions, groups, fi_max_week=args.fi_max_week)
            print(f"  après complétion : {complete.summary()}", flush=True)
            with journal.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "etape": "completion", "seed": best.seed,
                    "missing_avant": best.missing, "missing_apres": complete.missing,
                    "placed_apres": complete.placed, "gaps_apres": complete.gaps,
                    "at": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
        else:
            print("  complétion en échec — le run reste tel quel.", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
