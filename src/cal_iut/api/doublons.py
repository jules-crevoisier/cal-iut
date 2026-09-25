"""Compte rendu « doublons salle / enseignant » — retour Kyllian Bresson
25/09/2026 : « une possibilité de vérification après placement pour salles et
enseignants en double. Car quand je déplace à la main, même avec les
vérifications je dois faire des doublons. Donc si on pouvait avoir un compte
rendu qui indique quelle salle ou quel enseignant est mobilisé deux fois sur
le même créneau, que je puisse corriger cela rapidement. Et aussi pour H.201
et H.203, c'est en soi la même salle, donc il ne faut pas deux modules
différents en même temps dans ces deux salles, pareil pour H.007 et H.008. »

Contrôle A POSTERIORI, distinct de `api/validation.py::validate_move`
(contrôle AVANT un déplacement/placement) : les retouches faites directement
dans Celcat ou par un ancien correctif jamais revérifié peuvent laisser le
planning dans un état déjà en double, que rien ne signale tant qu'on ne
retouche pas CETTE séance précise. Cet écran balaie tout le planning stocké
d'un coup.

Module PUR (aucun accès réseau/DB, aucune dépendance FastAPI) : ne lit que
`state.timetable`/`state.rooms`/`state.sessions_by_id`/`state.courses` —
testable directement sans monter l'API, cf. `tests/test_doublons_salle_
enseignant_2026_09_25.py`.
"""

from __future__ import annotations

from collections import defaultdict

from cal_iut.api.validation import _duration_of, _est_pause_midi
from cal_iut.solver.rooms import build_manual_conflict_map


def _nom_enseignant(state: object, code: str) -> str:
    """Nom complet depuis `state.courses` (même traversée que
    `session_patch.py::codes_enseignants_connus`) — repli sur le CODE brut si
    introuvable (jamais un module PUR ne doit planter faute de `state.courses`
    dans un fixture de test minimal)."""
    for cours in getattr(state, "courses", None) or []:
        lead = getattr(cours, "lead", None)
        if lead is not None and getattr(lead, "code", None) == code:
            nom = f"{lead.prenom} {lead.nom}".strip()
            return nom or code
        for bloc in getattr(cours, "profs", None) or []:
            prof = getattr(bloc, "teacher", None)
            if prof is not None and getattr(prof, "code", None) == code:
                nom = f"{prof.prenom} {prof.nom}".strip()
                return nom or code
    return code


def _seance_dict(p: object) -> dict[str, object]:
    return {
        "session_id": p.session_id,
        "course_code": p.course_code,
        "groupes": list(p.group_ids or []),
        "salle": getattr(p, "room_label", None) or getattr(p, "room_id", None),
        "enseignants": list(p.teacher_codes or []),
    }


def doublons(state: object, semaine: int | None = None) -> list[dict[str, object]]:
    """Scanne `state.timetable` et rend, pour chaque (semaine, jour, créneau)
    où une même ressource est mobilisée par au moins DEUX séances
    différentes : un enseignant présent deux fois, ou une salle occupée deux
    fois — « salle » incluant l'équivalence des salles combinées
    (`build_manual_conflict_map` : H.007/H.008/H.007-008 forment UNE seule
    ressource physique, de même H.201/H.203/H.201-203).

    Une séance sur PLUSIEURS créneaux (`duration_slots`) compte sur CHACUN
    des créneaux qu'elle occupe réellement — un TP de 3h qui chevauche
    seulement la 2e moitié d'un TD de 1h30 ne ressort QUE sur le créneau
    partagé, pas sur les deux.

    Les évènements à horaire libre (pause méridienne, `metadata["pause_midi"]`)
    sont exclus du balayage, comme dans `validate_move` (cf. son docstring) :
    ils sont tous stockés sur le même créneau 3 quelle que soit leur heure
    réelle (`api/main.py::_SLOT_STOCKAGE_PAUSE`), les comparer sur ce
    créneau de STOCKAGE produirait des doublons fantômes entre pauses qui ne
    se chevauchent pas réellement (`_conflit_salle_pause_midi` reste le
    contrôle dédié à leur cas, en minutes réelles).
    """
    rooms = getattr(state, "rooms", None) or []
    sessions_by_id = getattr(state, "sessions_by_id", None) or {}
    conflict_map = build_manual_conflict_map(rooms)
    room_label_by_id = {r.id: r.label for r in rooms}

    def classe_salle(room_id: str) -> frozenset:
        return frozenset({room_id}) | conflict_map.get(room_id, set())

    par_creneau_enseignant: dict[tuple[int, int, int, str], list[object]] = defaultdict(list)
    par_creneau_salle: dict[tuple[int, int, int, frozenset], list[object]] = defaultdict(list)

    for p in getattr(state, "timetable", None) or []:
        if semaine is not None and p.week != semaine:
            continue
        if _est_pause_midi(p.session_id, sessions_by_id):
            continue
        duree = _duration_of(p.session_id, sessions_by_id)
        room_id = getattr(p, "room_id", None)
        for offset in range(duree):
            slot = p.slot + offset
            for code in p.teacher_codes or []:
                par_creneau_enseignant[(p.week, p.day, slot, code)].append(p)
            if room_id:
                par_creneau_salle[(p.week, p.day, slot, classe_salle(room_id))].append(p)

    entries: list[dict[str, object]] = []

    for (week, day, slot, code), placements in par_creneau_enseignant.items():
        uniques = {pp.session_id: pp for pp in placements}
        if len(uniques) < 2:
            continue
        seances = sorted(uniques.values(), key=lambda pp: pp.session_id)
        entries.append({
            "semaine": week,
            "jour": day,
            "creneau": slot,
            "type": "enseignant",
            "ressource": _nom_enseignant(state, code),
            "seances": [_seance_dict(pp) for pp in seances],
        })

    for (week, day, slot, classe), placements in par_creneau_salle.items():
        uniques = {pp.session_id: pp for pp in placements}
        if len(uniques) < 2:
            continue
        seances = sorted(uniques.values(), key=lambda pp: pp.session_id)
        salles_reelles = sorted({
            room_label_by_id.get(getattr(pp, "room_id", None), getattr(pp, "room_id", None))
            for pp in seances
        })
        entries.append({
            "semaine": week,
            "jour": day,
            "creneau": slot,
            "type": "salle",
            "ressource": " / ".join(salles_reelles),
            "seances": [_seance_dict(pp) for pp in seances],
        })

    entries.sort(key=lambda e: (e["semaine"], e["jour"], e["creneau"], e["type"], e["ressource"]))
    return entries
