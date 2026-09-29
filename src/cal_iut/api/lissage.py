"""
Lissage du planning d'un parcours (demande du 29/09/2026 : « revoir tout le
planning des 3e année dev FC, l'améliorer au maximum, l'optimiser, le lisser,
on évite tous les cours à 9h30 », précisé ensuite : « on ne veut pas de
cours de 8h à 9h30, après si — en gros on veut que les cours commencent à
9h30 »).

Ce n'est PAS une régénération : seules les séances du parcours demandé,
placées sur des semaines FUTURES et non verrouillées, peuvent bouger. Tout le
reste du planning (autres promotions, séances partagées, semaines passées ou
en cours) est une donnée figée — un enseignant pris ailleurs, une salle
occupée, une SAE, la présence en alternance, un jour férié sont autant de
créneaux interdits.

Deux garanties, par construction :

1. **Mêmes règles que le glisser-déposer.** Chaque créneau candidat est
   filtré par le contexte de contraintes du serveur (`_hard_constraint_context`
   : PAC, SAE sanctuarisée, présence alternant, événements officiels, jours
   fermés), les indisponibilités enseignant (déclarées ET strictes), les
   séances figées de la même cohorte et des mêmes enseignants, et la
   disponibilité d'au moins une salle adaptée. Rien n'est jamais « forcé » :
   une proposition ne contient que des créneaux qu'un humain pourrait poser
   sans cliquer sur « Forcer ».
2. **Même chemin d'écriture qu'un déplacement manuel.** `appliquer` passe par
   `move_session` (validation, corrections, file Celcat, sauvegarde du jour) :
   si le planning a changé entre la proposition et l'application, le
   déplacement concerné est refusé comme il le serait à la main, et rien
   d'autre n'est tenté après lui.

L'objectif (poids réglables, `PoidsLissage`) : pas de cours à 8h (la
journée commence à 9h30), pas de trou dans la journée, peu de 17h, des journées de charge égale, pas
de journée à une seule séance, les séances d'un même enseignant regroupées sur
les jours où il est déjà là — et le moins de changements possible : chaque
déplacement a un coût, qui dit au solveur de ne bouger que ce qui améliore
réellement la semaine (chaque déplacement est une ligne de plus à corriger
dans Celcat et un enseignant de plus à prévenir).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from cal_iut.api.verrou import verrou_planning
from cal_iut.calendar.academic import semester_week_offset, week_status
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

SLOTS_PER_WEEK = DAYS_PER_WEEK * SLOTS_PER_DAY
HORAIRES = ("8h", "9h30", "11h", "14h", "15h30", "17h")
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")
# Créneaux enchaînés sans pause (cf. `solver/constraints.py::_CONTIGUOUS_SLOT_RUNS`).
_RUNS = ((0, 1, 2), (3, 4, 5))


@dataclass
class PoidsLissage:
    """Coût de chaque défaut, par occurrence. Seuls les RAPPORTS comptent.

    Valeurs par défaut fixées avec l'équipe le 29/09/2026 pour la 3e année
    FC : « on ne veut pas de cours de 8h à 9h30, après si — en gros les
    cours commencent à 9h30 ». Le créneau de 8h coûte donc plus cher que
    tout le reste réuni (il n'est pris que si rien d'autre n'est possible),
    le trou vient ensuite (une heure et demie à attendre), puis le 17h
    (préférence déjà exprimée pour la 3e année le 07/08/2026, cf.
    `add_edge_slot_penalties`). 9h30 est un créneau normal. Un déplacement
    coûte peu : il suffit qu'il supprime un défaut pour être retenu.
    """

    trou: int = 100
    cours_8h: int = 500
    cours_9h30: int = 0
    cours_17h: int = 25
    journee_isolee: int = 40
    # Par séance au carré sur la journée : 4+4 (2 et 2) coûte moins que 1+9
    # (1 et 3) — pousse vers des journées de charge égale.
    equilibre: int = 6
    # Par (enseignant, jour) où il ne venait pas déjà : regroupe les séances
    # d'un vacataire sur ses jours de présence.
    jour_enseignant: int = 12
    # Par créneau vide entre deux séances d'un même enseignant dans la
    # journée (toutes promos confondues) : un vacataire qui vient pour 9h30
    # et 15h30 attend quatre heures et demie.
    trou_enseignant: int = 15
    deplacement: int = 8
    changement_semaine: int = 40


@dataclass
class Mesure:
    """Indicateurs d'UNE semaine pour la cohorte du parcours."""

    semaine: int
    libelle: str
    seances: int
    cours_9h30: int = 0
    cours_8h: int = 0
    cours_17h: int = 0
    trous: int = 0
    journees_isolees: int = 0
    # Trous dans la journée des enseignants de la promo, toutes promos
    # confondues (un vacataire qui attend entre deux cours).
    trous_enseignants: int = 0
    charge_max: int = 0
    charges: list[int] = field(default_factory=list)


@dataclass
class Deplacement:
    session_id: str
    course_code: str
    enseignants: list[str]
    de: tuple[int, int, int]
    vers: tuple[int, int, int]
    libelle_de: str = ""
    libelle_vers: str = ""
    salle: str | None = None


@dataclass
class Proposition:
    parcours: str
    statut: str
    message: str
    semaines: list[int]
    deplacements: list[Deplacement]
    avant: list[Mesure]
    apres: list[Mesure]
    duree_s: float
    poids: PoidsLissage
    # Motifs trouvés par la contre-vérification (`verifier`) — vide = chaque
    # déplacement passe les contrôles d'un glisser-déposer manuel, sans forcer.
    verification: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LissageErreur(Exception):
    """Demande invalide (parcours inconnu, rien à lisser…)."""


# ── Lecture de l'état ────────────────────────────────────────────────────────


def _groupes_du_parcours(state: Any, parcours: str) -> set[str]:
    return {g.id for g in state.groups if getattr(g, "parcours", None) == parcours}


def _duree(session: Any) -> int:
    return max(1, int(getattr(session, "duration_slots", 1) or 1))


def _departs_valides(duree: int) -> set[int]:
    return {s for run in _RUNS for s in run if s + duree - 1 <= run[-1]}


def _cohorte_de(state: Any, groupes: set[str]) -> set[str]:
    """Identifiants de groupe qui concernent LES MÊMES étudiants — une
    séance de n'importe lequel occupe toute la cohorte.

    Limite assumée : on traite tout le parcours comme UNE cohorte. C'est
    exact pour les parcours FC (un TD, un TP, les mêmes personnes), trop
    strict pour un parcours à plusieurs TP (deux TP en parallèle y
    deviendraient interdits) — `proposer` refuse donc ces parcours."""
    return set(groupes)


def _libelle_creneau(state: Any, semestre: str, w: int, d: int, s: int) -> str:
    offset = semester_week_offset(state.calendar, semestre)
    date = state.calendar.week_day_to_date(offset + w, d)
    jour = f"{JOURS[d][:3]}. {date.day:02d}/{date.month:02d}" if date else JOURS[d]
    return f"{jour} {HORAIRES[s]}"


def mesurer(state: Any, parcours: str, placements: dict[str, tuple[int, int, int]], semaines: list[int]) -> list[Mesure]:
    """Indicateurs par semaine, à partir d'une position (w, d, s) par séance
    de la cohorte — la même fonction pour l'avant et l'après, pour que la
    comparaison ne dépende que du placement."""
    groupes = _groupes_du_parcours(state, parcours)
    semestre = _semestre_du_parcours(state, parcours)
    offset = semester_week_offset(state.calendar, semestre)
    occupe: dict[tuple[int, int], set[int]] = defaultdict(set)
    compte: dict[int, int] = defaultdict(int)
    profs_semaine: dict[int, set[str]] = defaultdict(set)
    occupe_prof: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    for sid, (w, d, s) in placements.items():
        seance = state.sessions_by_id.get(sid)
        if seance is None:
            continue
        for code in seance.teacher_codes or []:
            for k in range(_duree(seance)):
                occupe_prof[(code, w, d)].add(s + k)
        if not (set(seance.group_ids) & groupes):
            continue
        compte[w] += 1
        profs_semaine[w] |= set(seance.teacher_codes or [])
        for k in range(_duree(seance)):
            occupe[(w, d)].add(s + k)
    resultat = []
    for w in semaines:
        lundi = state.calendar.week_day_to_date(offset + w, 0)
        libelle = state.calendar.department_week_label(offset + w) if hasattr(state.calendar, "department_week_label") else f"Semaine {w + 1}"
        m = Mesure(semaine=w, libelle=str(libelle or (lundi.isoformat() if lundi else w)), seances=compte.get(w, 0))
        for d in range(DAYS_PER_WEEK):
            slots = occupe.get((w, d), set())
            m.charges.append(len(slots))
            if not slots:
                continue
            m.cours_9h30 += 1 in slots
            m.cours_8h += 0 in slots
            m.cours_17h += 5 in slots
            m.trous += (max(slots) - min(slots) + 1) - len(slots)
            m.journees_isolees += len(slots) == 1
        m.charge_max = max(m.charges) if m.charges else 0
        for code in profs_semaine.get(w, set()):
            for d in range(DAYS_PER_WEEK):
                slots = occupe_prof.get((code, w, d))
                if slots:
                    m.trous_enseignants += (max(slots) - min(slots) + 1) - len(slots)
        resultat.append(m)
    return resultat


def _semestre_du_parcours(state: Any, parcours: str) -> str:
    for s in state.sessions:
        if s.parcours == parcours:
            return s.semestre
    raise LissageErreur(f"Aucune séance pour le parcours {parcours}.")


# ── Proposition ──────────────────────────────────────────────────────────────


def proposer(
    state: Any,
    parcours: str,
    *,
    semaines: list[int] | None = None,
    entre_semaines: bool = True,
    poids: PoidsLissage | None = None,
    temps_max_s: float = 90.0,
) -> Proposition:
    """Calcule un meilleur placement pour les séances futures du parcours,
    SANS rien écrire. `semaines` restreint la portée (index solveur) ;
    `entre_semaines=False` interdit tout changement de semaine."""
    from cal_iut.api.main import (
        _hard_constraint_context,
        _indisponibilites_strictes,
        _is_duo_synced,
        _teacher_availability_violations,
    )
    from cal_iut.solver.decomposed import _build_sequence_neighbors
    from cal_iut.solver.rooms import (
        build_manual_conflict_map,
        find_room_for_slot,
        occupation_salles,
    )

    debut = time.monotonic()
    poids = poids or PoidsLissage()
    groupes = _groupes_du_parcours(state, parcours)
    if not groupes:
        raise LissageErreur(f"Parcours inconnu : {parcours}.")
    semestre = _semestre_du_parcours(state, parcours)
    tps = [g for g in state.groups if g.id in groupes and str(getattr(g.kind, "value", g.kind)) == "tp"]
    if len(tps) > 1:
        raise LissageErreur(
            f"{parcours} a {len(tps)} groupes de TP : le lissage ne traite que les parcours à "
            "groupe unique (alternance FC). Utilisez la régénération de semaine pour les autres."
        )
    cohorte = _cohorte_de(state, groupes)

    placement_par_id = {p.session_id: p for p in state.timetable}
    futures = {
        w for w in {p.week for p in state.timetable}
        if week_status(state.calendar, semestre, w) == "future"
    }
    if semaines is not None:
        futures &= set(semaines)

    # Séances mobiles : entièrement dans la cohorte (une séance partagée avec
    # une autre promo reste figée), futures, non verrouillées, pas un
    # événement hors maquette, pas un binôme synchronisé sur salle rare.
    mobiles = []
    for p in state.timetable:
        s = state.sessions_by_id.get(p.session_id)
        if s is None or p.week not in futures:
            continue
        if not set(s.group_ids) or not set(s.group_ids) <= groupes:
            continue
        if s.locked or (s.metadata or {}).get("evenement") or _is_duo_synced(s, state.teacher_duos):
            continue
        mobiles.append(s)
    if not mobiles:
        raise LissageErreur("Aucune séance future et non verrouillée à lisser pour ce parcours.")
    ids_mobiles = {s.id for s in mobiles}

    semaines_touchees = sorted({placement_par_id[s.id].week for s in mobiles})
    # Semaines où la cohorte est à l'IUT : une séance ne peut changer de
    # semaine que vers l'une d'elles (la présence alternant est de toute
    # façon vérifiée créneau par créneau par le contexte institutionnel).
    semaines_cibles = sorted(futures) if entre_semaines else semaines_touchees

    # Occupations figées (tout ce qui ne bouge pas) — au créneau absolu.
    def t_abs(w: int, d: int, s: int) -> int:
        return w * SLOTS_PER_WEEK + d * SLOTS_PER_DAY + s

    cohorte_prise: set[int] = set()
    prof_pris: dict[str, set[int]] = defaultdict(set)
    prof_present: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for p in state.timetable:
        if p.session_id in ids_mobiles:
            continue
        s = state.sessions_by_id.get(p.session_id)
        duree = _duree(s) if s else 1
        cases = {t_abs(p.week, p.day, p.slot) + k for k in range(duree)}
        if set(p.group_ids or []) & cohorte:
            cohorte_prise |= cases
        for code in p.teacher_codes or []:
            prof_pris[code] |= cases
            prof_present[code].add((p.week, p.day))

    # Salles : on calcule la disponibilité contre le planning SANS les
    # séances mobiles (elles vont toutes être reposées) ; comme la cohorte ne
    # peut avoir qu'une séance à la fois, deux séances mobiles ne se
    # disputent jamais une salle au même créneau.
    fige = [p for p in state.timetable if p.session_id not in ids_mobiles]
    carte_salles = build_manual_conflict_map(state.rooms)
    occupation_figee = occupation_salles(
        fige, state.sessions_by_id, state.rooms, getattr(state, "room_reservations", None)
    )

    # Jours SAE du parcours, vus depuis une RESSOURCE (WR*) : une séance de
    # SAE y est admise par les règles (« une SAE peut être placée un jour de
    # SAE »), mais ces jours appartiennent à une SAE précise — y déplacer une
    # séance d'une AUTRE SAE mélangerait deux projets. On ne l'y envoie donc
    # jamais, sauf si elle y est déjà ce jour-là.
    reference_wr = next((s for s in mobiles if not str(s.course_code).upper().startswith("WS")), None)
    jours_bloques_ressource: set[tuple[int, int]] = set()
    if reference_wr is not None:
        bloque_ref, _p, _a = _hard_constraint_context(state, reference_wr)
        jours_bloques_ressource = {(w, d) for (w, d, _sl) in bloque_ref}

    # Domaine de chaque séance mobile.
    domaines: dict[str, list[tuple[int, int, int]]] = {}
    for s in mobiles:
        actuel = placement_par_id[s.id]
        blocked, _pedago, _allowed = _hard_constraint_context(state, s)
        if str(s.course_code).upper().startswith("WS"):
            blocked = set(blocked) | {
                (w, d, sl)
                for (w, d) in jours_bloques_ressource
                if (w, d) != (actuel.week, actuel.day)
                for sl in range(SLOTS_PER_DAY)
            }
        duree = _duree(s)
        departs = _departs_valides(duree)
        # Une séance de SAE (WS*) ne change jamais de semaine : ses dates
        # suivent les phases du projet (`sae_teacher_phases.yaml`) et les
        # jours SAE d'une semaine appartiennent à UNE SAE précise — la
        # déplacer sur les jours d'une autre SAE serait permis par les
        # règles, pas par le bon sens.
        est_sae = str(s.course_code).upper().startswith("WS")
        candidats_semaines = semaines_cibles if entre_semaines and not est_sae else [actuel.week]
        dom: list[tuple[int, int, int]] = []
        for w in candidats_semaines:
            for d in range(DAYS_PER_WEEK):
                for sl in sorted(departs):
                    cases = [(w, d, sl + k) for k in range(duree)]
                    if any(c in blocked for c in cases):
                        continue
                    ta = [t_abs(*c) for c in cases]
                    if any(t in cohorte_prise for t in ta):
                        continue
                    if any(t in prof_pris[code] for code in s.teacher_codes or [] for t in ta):
                        continue
                    if any(
                        _teacher_availability_violations(state, s, *c) or _indisponibilites_strictes(state, s, *c)
                        for c in cases
                    ):
                        continue
                    salle = find_room_for_slot(
                        s, w, d, sl, fige, state.sessions_by_id, state.rooms, state.groups,
                        state.room_rules, prefer_room_id=getattr(actuel, "room_id", None),
                        reserved=getattr(state, "room_reservations", None),
                        conflicts=carte_salles,
                        occupation=occupation_figee,
                    )
                    if salle is None and getattr(actuel, "room_id", None):
                        continue
                    dom.append((w, d, sl))
        position = (actuel.week, actuel.day, actuel.slot)
        if position not in dom:
            # La position actuelle est TOUJOURS permise : le lissage ne doit
            # jamais échouer parce que l'existant a été forcé à la main
            # (indisponibilité acceptée à l'oral, etc.). Elle n'est simplement
            # pas « réparée ».
            dom.append(position)
        domaines[s.id] = dom

    modele = cp_model.CpModel()
    x: dict[tuple[str, tuple[int, int, int]], cp_model.IntVar] = {}
    for s in mobiles:
        for pos in domaines[s.id]:
            x[(s.id, pos)] = modele.new_bool_var(f"x_{s.id}_{pos}")
        modele.add_exactly_one(x[(s.id, pos)] for pos in domaines[s.id])

    # Occupation de la cohorte, créneau par créneau (mobiles uniquement ; le
    # figé a déjà été retiré des domaines).
    couvre: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    for s in mobiles:
        for pos in domaines[s.id]:
            for k in range(_duree(s)):
                couvre[t_abs(pos[0], pos[1], pos[2] + k)].append(x[(s.id, pos)])
    for t, vs in couvre.items():
        if len(vs) > 1:
            modele.add_at_most_one(vs)

    # Un enseignant ne donne qu'une séance à la fois — déjà garanti entre
    # séances mobiles par la cohorte unique, mais pas si une autre séance de
    # l'enseignant est mobile dans un AUTRE parcours : impossible ici (un seul
    # parcours à la fois), rien à ajouter.

    # Ordre pédagogique (même source que le solveur et le glisser-déposer).
    voisins = _build_sequence_neighbors(state.sessions, state.groups)

    def debut_expr(sid: str) -> cp_model.LinearExpr:
        return sum(t_abs(*pos) * x[(sid, pos)] for pos in domaines[sid])

    def t_fixe(sid: str) -> int | None:
        p = placement_par_id.get(sid)
        return t_abs(p.week, p.day, p.slot) if p else None

    for sid in ids_mobiles:
        preds, _succs = voisins.get(sid, ([], []))
        for pid in preds:
            pred = state.sessions_by_id.get(pid)
            if pred is None or pid not in placement_par_id:
                continue
            # Paire DÉJÀ inversée dans l'existant (forçage manuel) : on ne
            # l'impose pas, sinon le modèle serait infaisable pour une raison
            # que personne ne demande de corriger ici.
            if t_fixe(pid) is not None and t_fixe(sid) is not None and t_fixe(pid) >= t_fixe(sid):
                continue
            fin_pred = _duree(pred) - 1
            if pid in ids_mobiles:
                modele.add(debut_expr(pid) + fin_pred < debut_expr(sid))
            else:
                modele.add(debut_expr(sid) > t_fixe(pid) + fin_pred)

    for sid in ids_mobiles:
        _preds, succs = voisins.get(sid, ([], []))
        for nid in succs:
            if nid in ids_mobiles or nid not in placement_par_id:
                continue
            if t_fixe(sid) >= t_fixe(nid):
                continue
            modele.add(debut_expr(sid) + _duree(state.sessions_by_id[sid]) - 1 < t_fixe(nid))

    # ── Objectif ──
    termes: list[cp_model.LinearExpr] = []
    for w in semaines_cibles:
        for d in range(DAYS_PER_WEEK):
            occ: list[cp_model.LinearExpr | int] = []
            for sl in range(SLOTS_PER_DAY):
                t = t_abs(w, d, sl)
                if t in cohorte_prise:
                    occ.append(1)
                elif couvre.get(t):
                    occ.append(sum(couvre[t]))
                else:
                    occ.append(0)
            if all(isinstance(o, int) and o == 0 for o in occ):
                continue
            ob = []
            for sl, o in enumerate(occ):
                b = modele.new_bool_var(f"o_{w}_{d}_{sl}")
                modele.add(b == o)
                ob.append(b)
            termes.append(poids.cours_9h30 * ob[1])
            termes.append(poids.cours_8h * ob[0])
            termes.append(poids.cours_17h * ob[5])
            for sl in range(1, SLOTS_PER_DAY - 1):
                avant = modele.new_bool_var("")
                apres = modele.new_bool_var("")
                modele.add_max_equality(avant, ob[:sl])
                modele.add_max_equality(apres, ob[sl + 1:])
                trou = modele.new_bool_var("")
                modele.add(trou >= avant + apres - 1 - ob[sl])
                termes.append(poids.trou * trou)
            charge = modele.new_int_var(0, SLOTS_PER_DAY, "")
            modele.add(charge == sum(ob))
            carre = modele.new_int_var(0, SLOTS_PER_DAY**2, "")
            modele.add_multiplication_equality(carre, [charge, charge])
            termes.append(poids.equilibre * carre)
            au_moins_1 = modele.new_bool_var("")
            au_moins_2 = modele.new_bool_var("")
            modele.add_max_equality(au_moins_1, ob)
            modele.add(charge >= 2 * au_moins_2)
            isolee = modele.new_bool_var("")
            modele.add(isolee >= au_moins_1 - au_moins_2)
            termes.append(poids.journee_isolee * isolee)

    # Jours de présence des enseignants (hors jours où ils viennent déjà).
    par_prof_jour: dict[tuple[str, int, int], list[cp_model.IntVar]] = defaultdict(list)
    for s in mobiles:
        for pos in domaines[s.id]:
            for code in s.teacher_codes or []:
                if (pos[0], pos[1]) not in prof_present[code]:
                    par_prof_jour[(code, pos[0], pos[1])].append(x[(s.id, pos)])
    for vs in par_prof_jour.values():
        vient = modele.new_bool_var("")
        modele.add_max_equality(vient, vs)
        termes.append(poids.jour_enseignant * vient)

    # Trous dans la journée d'un enseignant : ses séances figées (autres
    # promos) comptent comme occupées, ses séances mobiles comme variables.
    couvre_prof: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
    jours_prof: set[tuple[str, int, int]] = set()
    for s in mobiles:
        for pos in domaines[s.id]:
            for code in s.teacher_codes or []:
                jours_prof.add((code, pos[0], pos[1]))
                for k in range(_duree(s)):
                    couvre_prof[(code, t_abs(pos[0], pos[1], pos[2] + k))].append(x[(s.id, pos)])
    for code, w, d in jours_prof:
        occ_prof: list[cp_model.IntVar | int] = []
        for sl in range(SLOTS_PER_DAY):
            t = t_abs(w, d, sl)
            if t in prof_pris[code]:
                occ_prof.append(1)
            elif couvre_prof.get((code, t)):
                b = modele.new_bool_var("")
                modele.add(b == sum(couvre_prof[(code, t)]))
                occ_prof.append(b)
            else:
                occ_prof.append(0)
        for sl in range(1, SLOTS_PER_DAY - 1):
            if isinstance(occ_prof[sl], int) and occ_prof[sl] == 1:
                continue
            avant_l = [o for o in occ_prof[:sl] if not (isinstance(o, int) and o == 0)]
            apres_l = [o for o in occ_prof[sl + 1:] if not (isinstance(o, int) and o == 0)]
            if not avant_l or not apres_l:
                continue
            if any(isinstance(o, int) for o in avant_l):
                avant = 1
            else:
                avant = modele.new_bool_var("")
                modele.add_max_equality(avant, avant_l)
            if any(isinstance(o, int) for o in apres_l):
                apres = 1
            else:
                apres = modele.new_bool_var("")
                modele.add_max_equality(apres, apres_l)
            trou = modele.new_bool_var("")
            modele.add(trou >= avant + apres - 1 - occ_prof[sl])
            termes.append(poids.trou_enseignant * trou)

    for s in mobiles:
        p = placement_par_id[s.id]
        actuel = (p.week, p.day, p.slot)
        for pos in domaines[s.id]:
            if pos == actuel:
                continue
            cout = poids.deplacement + (poids.changement_semaine if pos[0] != p.week else 0)
            termes.append(cout * x[(s.id, pos)])
        # Indice : partir de l'existant (toujours faisable par construction).
        for pos in domaines[s.id]:
            modele.add_hint(x[(s.id, pos)], pos == actuel)

    modele.minimize(sum(termes))
    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = temps_max_s
    solveur.parameters.num_search_workers = 8
    solveur.parameters.random_seed = 2027
    statut = solveur.solve(modele)
    nom_statut = solveur.status_name(statut)

    avant_pos = {p.session_id: (p.week, p.day, p.slot) for p in state.timetable}
    semaines_rapport = sorted(set(semaines_touchees) | set(semaines_cibles))
    avant = [m for m in mesurer(state, parcours, avant_pos, semaines_rapport) if m.seances or m.semaine in semaines_touchees]
    if statut not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Proposition(
            parcours=parcours, statut=nom_statut, message="Aucune solution trouvée — rien ne change.",
            semaines=semaines_touchees, deplacements=[], avant=avant, apres=avant,
            duree_s=round(time.monotonic() - debut, 1), poids=poids,
        )

    deplacements: list[Deplacement] = []
    apres_pos = dict(avant_pos)
    for s in mobiles:
        choisi = next(pos for pos in domaines[s.id] if solveur.value(x[(s.id, pos)]))
        apres_pos[s.id] = choisi
        if choisi != avant_pos[s.id]:
            deplacements.append(Deplacement(
                session_id=s.id, course_code=s.course_code, enseignants=list(s.teacher_codes or []),
                de=avant_pos[s.id], vers=choisi,
                libelle_de=_libelle_creneau(state, semestre, *avant_pos[s.id]),
                libelle_vers=_libelle_creneau(state, semestre, *choisi),
            ))
    deplacements.sort(key=lambda m: (m.vers, m.session_id))
    semaines_apres = sorted(set(semaines_rapport))
    apres = mesurer(state, parcours, apres_pos, semaines_apres)
    apres = [m for m in apres if m.seances or m.semaine in semaines_touchees]
    verification = verifier(state, deplacements)
    return Proposition(
        parcours=parcours,
        statut=nom_statut,
        message=f"{len(deplacements)} déplacement(s) proposé(s).",
        semaines=semaines_touchees,
        deplacements=deplacements,
        avant=avant,
        apres=apres,
        duree_s=round(time.monotonic() - debut, 1),
        poids=poids,
        verification=verification,
    )


def verifier(state: Any, deplacements: list[Deplacement]) -> list[str]:
    """Rejoue la proposition sur une COPIE du planning final et passe chaque
    séance déplacée dans les contrôles d'un déplacement manuel sans forçage
    (`_conflits_deplacement` + `validate_move` : groupes, cohortes,
    enseignants, salles de toutes les promotions). Renseigne au passage la
    salle retenue (`Deplacement.salle`). Rend la liste des motifs de refus.

    Indépendant du modèle d'optimisation : si le modèle oubliait une règle,
    c'est ici qu'on le verrait, avant d'écrire quoi que ce soit."""
    import dataclasses

    from cal_iut.api.main import _conflits_deplacement, build_manual_conflict_map
    from cal_iut.api.validation import validate_move
    from cal_iut.solver.rooms import find_room_for_slot

    if not deplacements:
        return []
    cibles = {m.session_id: m for m in deplacements}
    simule = [
        dataclasses.replace(p, week=cibles[p.session_id].vers[0], day=cibles[p.session_id].vers[1],
                            slot=cibles[p.session_id].vers[2])
        if p.session_id in cibles else p
        for p in state.timetable
    ]
    # Salles : réattribuées une à une sur le planning simulé, en gardant
    # l'actuelle quand elle reste libre (comme `move_session`).
    par_id = {p.session_id: i for i, p in enumerate(simule)}
    for sid, m in cibles.items():
        i = par_id[sid]
        p = simule[i]
        seance = state.sessions_by_id[sid]
        salle = find_room_for_slot(
            seance, p.week, p.day, p.slot, simule, state.sessions_by_id, state.rooms, state.groups,
            state.room_rules, prefer_room_id=getattr(p, "room_id", None),
            reserved=getattr(state, "room_reservations", None),
            conflicts=build_manual_conflict_map(state.rooms),
        )
        if salle is not None:
            simule[i] = dataclasses.replace(p, room_id=salle.id, room_label=salle.label)
            m.salle = salle.label
    etat_simule = dataclasses.replace(state, timetable=simule) if dataclasses.is_dataclass(state) else state
    motifs: list[str] = []
    for sid, m in cibles.items():
        p = simule[par_id[sid]]
        seance = state.sessions_by_id[sid]
        institutionnel, forcable = _conflits_deplacement(etat_simule, seance, p.week, p.day, p.slot)
        room_id = getattr(p, "room_id", None)
        validation = validate_move(
            sid, p.week, p.day, p.slot, simule, list(seance.group_ids or []), list(seance.teacher_codes or []),
            room_id, sessions_by_id=state.sessions_by_id, groups=state.groups,
            conflicting_room_ids=build_manual_conflict_map(state.rooms).get(room_id, set()) if room_id else None,
        )
        problemes = institutionnel + forcable + (validation.hard_conflicts if not validation.valid else [])
        for motif in problemes:
            motifs.append(f"{m.course_code} {m.libelle_de} → {m.libelle_vers} : {motif}")
    return motifs


# ── Application ──────────────────────────────────────────────────────────────


@dataclass
class ResultatApplication:
    appliques: list[str]
    echec: dict[str, Any] | None
    restants: list[str]


def ordre_application(
    deplacements: list[Deplacement], occupation_actuelle: dict[str, tuple[int, int, int]], durees: dict[str, int]
) -> list[tuple[Deplacement, tuple[int, int, int] | None]]:
    """Ordonne les déplacements pour qu'aucun ne tombe sur une case encore
    occupée par une autre séance de la cohorte qui n'a pas encore bougé.

    Un cycle (A va sur B qui va sur A) se résout en posant d'abord l'un des
    deux sur une case LIBRE de sa semaine, puis en le ramenant : rend donc
    des couples (déplacement, étape_intermédiaire). La file Celcat ne garde
    qu'un job par séance, l'étape intermédiaire n'y laisse aucune trace.
    """
    def cases(pos: tuple[int, int, int], sid: str) -> set[tuple[int, int, int]]:
        return {(pos[0], pos[1], pos[2] + k) for k in range(durees.get(sid, 1))}

    position = dict(occupation_actuelle)
    restants = list(deplacements)
    ordre: list[tuple[Deplacement, tuple[int, int, int] | None]] = []
    # Garde-fou : chaque tour pose un déplacement définitif OU sort une
    # séance d'un cycle vers une case qu'aucun autre déplacement ne vise —
    # le nombre de tours est donc borné ; au-delà, c'est un défaut de
    # l'algorithme, jamais une raison de tourner en rond.
    for _ in range(4 * len(deplacements) + 4):
        if not restants:
            return ordre
        occupe = {c: sid for sid, pos in position.items() for c in cases(pos, sid)}
        pret = next(
            (m for m in restants if all(occupe.get(c) in (None, m.session_id) for c in cases(m.vers, m.session_id))),
            None,
        )
        if pret is not None:
            ordre.append((pret, None))
            position[pret.session_id] = pret.vers
            restants.remove(pret)
            continue
        # Cycle : on sort le premier vers une case libre de sa semaine
        # d'arrivée, qui ne soit la cible d'AUCUN déplacement restant (sinon
        # on recréerait le blocage qu'on veut briser) ni sa propre position.
        m = restants[0]
        visees = {c for x in restants for c in cases(x.vers, x.session_id)}
        actuelles = cases(position[m.session_id], m.session_id)
        w = m.vers[0]
        libre = next(
            (
                (w, d, sl)
                for d in range(DAYS_PER_WEEK)
                for sl in sorted(_departs_valides(durees.get(m.session_id, 1)))
                if not (cases((w, d, sl), m.session_id) & (visees | actuelles | set(occupe)))
            ),
            None,
        )
        if libre is None:
            raise LissageErreur("Impossible d'ordonner les déplacements (aucune case libre pour briser un cycle).")
        ordre.append((Deplacement(**{**asdict(m), "vers": libre}), None))
        position[m.session_id] = libre
    raise LissageErreur("Impossible d'ordonner les déplacements (cycle non résolu).")


def appliquer(state: Any, proposition: Proposition) -> ResultatApplication:
    """Écrit la proposition, déplacement par déplacement, par le chemin d'un
    déplacement manuel. S'arrête au premier refus (le planning a changé
    depuis la proposition) : ce qui est déjà passé reste valide, puisque
    chaque étape l'a été à elle seule.

    Toute la séquence tient le verrou d'écriture du planning (P1-4) : lire
    l'occupation puis enchaîner les déplacements sans qu'une autre écriture
    s'intercale. `move_session` le reprend (verrou réentrant)."""
    from fastapi import HTTPException

    from cal_iut.api.main import move_session
    from cal_iut.api.schemas import MoveSessionRequest

    with verrou_planning:
        groupes = _groupes_du_parcours(state, proposition.parcours)
        occupation = {
            p.session_id: (p.week, p.day, p.slot)
            for p in state.timetable
            if set(p.group_ids or []) & groupes
        }
        durees = {sid: _duree(state.sessions_by_id[sid]) for sid in occupation if sid in state.sessions_by_id}
        etapes = ordre_application(proposition.deplacements, occupation, durees)
        appliques: list[str] = []
        for m, _ in etapes:
            w, d, sl = m.vers
            try:
                move_session(m.session_id, MoveSessionRequest(week=w, day=d, slot=sl, force=False))
            except HTTPException as exc:
                restants = [x.session_id for x in proposition.deplacements if x.session_id not in appliques]
                return ResultatApplication(
                    appliques=appliques,
                    echec={"session_id": m.session_id, "vers": list(m.vers), "detail": exc.detail},
                    restants=restants,
                )
            if m.session_id not in appliques and any(
                x.session_id == m.session_id and x.vers == m.vers for x in proposition.deplacements
            ):
                appliques.append(m.session_id)
        return ResultatApplication(appliques=appliques, echec=None, restants=[])
