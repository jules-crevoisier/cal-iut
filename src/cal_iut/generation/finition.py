"""Dernière passe sur le meilleur résultat du solveur : salles, puis séances
restées de côté.

Deux étapes qui étaient manuelles et non documentées en août 2026 :

- le solveur ne modélise pas les salles, et `cal-iut solve` ne les attribue
  que pour un résultat complet : un résultat partiel (le cas courant) sortait
  sans aucune salle (75 % des séances le 27/08/2026, rattrapées par
  `scripts/assign_rooms_backfill.py`) ;
- les séances non placées ont presque toutes un créneau valable ailleurs dans
  le semestre (`cal-iut completer`).

ISOLEMENT. La complétion réutilise le moteur du bouton « Tout placer
automatiquement » (`api.main.completer`), qui pose chaque séance par
`placer_seance` : contrôles complets, mais aussi file Celcat, notifications,
sauvegardes et révision de l'état. Ici, on travaille sur un BROUILLON, dans
le processus de l'ouvrier : ces effets sont neutralisés, et
`current_run_id = None` garantit qu'aucun placement n'est écrit en base.
"""

from __future__ import annotations

import json
from pathlib import Path


def _neutraliser_effets_de_bord() -> None:
    from cal_iut.api import forced_pending
    from cal_iut.api import main as api

    def _rien(*_args: object, **_kwargs: object) -> None:
        return None

    api._apres_ecriture_planning = _rien  # file Celcat, sauvegardes, révision
    api._notifier = _rien  # notifications et mails
    forced_pending.sync_after_move = _rien  # fichier d'état du planning en service


def finir_planning(donnees: dict, fichier_seances: Path, racine: Path, groupe: str) -> dict:
    """Complète `donnees["placements"]` EN PLACE. Rend un rapport :
    `a_placer`, `completees`, `sans_salle`, `non_placees` (liste de
    `{session_id, course_code, raison}`)."""
    from cal_iut.api import main as api
    from cal_iut.api.occupations_externes import reservations_effectives
    from cal_iut.cli import _construire_etat_pour_completion
    from cal_iut.generation.recherche import seances_a_placer
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae
    from cal_iut.models.session import SessionToPlace
    from cal_iut.solver.cpsat import PlacedSession
    from cal_iut.solver.rooms import PlacedSessionWithRoom, assign_rooms

    _neutraliser_effets_de_bord()

    seances = [SessionToPlace(**s) for s in json.loads(fichier_seances.read_text(encoding="utf-8"))]
    par_id = {s.id: s for s in seances}
    etat = _construire_etat_pour_completion(racine)
    assert etat.current_run_id is None, "la complétion d'un brouillon ne doit rien écrire en base"
    # Le calendrier du semestre (décalage des semaines) se déduit du groupe.
    etat.semestre_group = groupe
    etat.filter_parcours = None
    etat.filter_semestre = None
    etat.sessions = seances
    etat.sessions_by_id = par_id

    bruts = [p for p in donnees.get("placements", []) if p["session_id"] in par_id]
    if any(not p.get("room_id") for p in bruts):
        # `PlacedSession`, sans salle : `assign_rooms` décide seul, une salle
        # déjà écrite ne doit pas influencer son choix.
        etat.timetable = assign_rooms(
            [
                PlacedSession(
                    session_id=p["session_id"], week=p["week"], day=p["day"], slot=p["slot"],
                    course_code=p["course_code"], group_ids=p["group_ids"],
                    teacher_codes=p["teacher_codes"],
                )
                for p in bruts
            ],
            par_id, etat.rooms, etat.groups, etat.room_rules, etat.teacher_duos,
            reserved=reservations_effectives(etat),
        )
    else:
        etat.timetable = [
            PlacedSessionWithRoom(
                session_id=p["session_id"], week=p["week"], day=p["day"], slot=p["slot"],
                course_code=p["course_code"], group_ids=p["group_ids"],
                teacher_codes=p["teacher_codes"],
                room_id=p.get("room_id"), room_label=p.get("room_label"),
            )
            for p in bruts
        ]

    avant = len(etat.timetable)
    reponse = api.completer()
    non_placees = [
        {"session_id": r.session_id, "course_code": r.course_code, "raison": r.raison}
        for r in reponse.refusees
    ]

    donnees["placements"] = [
        {
            "session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
            "course_code": p.course_code, "group_ids": p.group_ids,
            "teacher_codes": p.teacher_codes,
            "room_id": p.room_id, "room_label": p.room_label,
        }
        for p in etat.timetable
    ]
    a_placer = seances_a_placer(seances, load_solver_scheduled_sae(racine / "data" / "config"))
    return {
        "a_placer": len(a_placer),
        "completees": len(etat.timetable) - avant,
        "sans_salle": sum(1 for p in etat.timetable if not p.room_id),
        "non_placees": non_placees,
    }
