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
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cal_iut.generation.recherche import (  # noqa: E402
    RunScore,
    load_sessions,
)
from cal_iut.generation.recherche import diagnostiquer as _diagnostiquer  # noqa: E402
from cal_iut.generation.recherche import score_run as _score_run  # noqa: E402
from cal_iut.ingestion.config_loader import load_groups  # noqa: E402
from cal_iut.models.session import SessionToPlace  # noqa: E402

# Score et diagnostic vivent dans le paquet (`cal_iut.generation.recherche`)
# depuis le 16/11/2026 : la génération lancée depuis l'interface les utilise
# aussi, et `scripts/` n'est pas dans l'image de production.


def solver_scheduled_sae() -> set[tuple[str, str]]:
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    return load_solver_scheduled_sae(ROOT / "data" / "config")


def score_run(
    timetable: dict, sessions: list[SessionToPlace], groups: list, *, fi_max_week: int | None = None,
) -> RunScore:
    return _score_run(
        timetable, sessions, groups, fi_max_week=fi_max_week, scheduled_sae=solver_scheduled_sae()
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
    return _diagnostiquer(timetable, sessions, ROOT)


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
