"""Polit un run déjà bon, séance par séance, sans jamais rien casser.

Retour utilisateur (27/08/2026, en regardant le run réel dans l'application) :

- « pour les s1 c'est juste imposible ils ont des journée entiere de cm c'est
  trop chiant il faut esseyer de diluer les cm dans la semaine ou les jour,
  sans rien casser » — une journée BUT1 vue en production : 6 CM d'affilée,
  5 matières différentes, aucun TD/TP entre les deux.
- « serait il pas possible qu'un fois que l'on ai un run bien, on ai un step
  qui regarde semaine par semaine parcour par parcours et qui essaie de faire
  les placement ? » — exactement ce que fait ce script.
- « peut tu esseyer de gouper [...] la wra507d et la wsa501d » en journées
  complètes pour les BUT3-DEV-FC — présence limitée à l'IUT, autant remplir
  la journée que la fragmenter.
- Et, découvert en auditant le run pendant cette même conversation : des
  violations d'ordre pédagogique encore présentes (21 + 30) — « il faut que
  cela soit correct sinon les prof seront pas content ». Contrainte DURE, pas
  une nuance de confort : traitée en PREMIER, avant tout confort.

Pourquoi une relocalisation ciblée plutôt qu'un nouveau modèle CP-SAT : pour
déplacer une poignée de séances déjà bien placées, chercher un créneau valide
parmi ceux que le serveur sait déjà calculer correctement
(`_hard_constraint_context`, `suggest_alternative_slots` — corrigés et
vérifiés plus tôt dans ce même chantier) est plus sûr et plus rapide qu'un
nouveau mécanisme non éprouvé. Chaque candidat proposé est, par construction,
déjà cohérent avec TOUTES les règles dures (dispos enseignant, présence FC,
ordre pédagogique, verrous institutionnels) — la relocalisation ne peut donc
jamais introduire une violation qu'elle ne connaît pas déjà.

Trois passes, dans cet ordre de priorité (une contrainte dure passe toujours
avant une préférence de confort) :

1. RÉPARATION DE L'ORDRE — jamais ignorée.
2. DILUTION DES CM — BUT1 seulement, jamais aux dépens d'une contrainte dure.
3. REGROUPEMENT WRA507D/WSA501D — BUT3-DEV-FC seulement.

Discipline « garder le meilleur » : chaque relocalisation n'est acceptée que
si elle règle RÉELLEMENT ce qu'elle visait sans rien dégrader par ailleurs ;
sinon la séance reste exactement où elle était.

    python scripts/polish_run.py --timetable data/generated/timetable_final.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cal_iut.api.main import (  # noqa: E402
    _hard_constraint_context,
    _institutional_violations,
    _is_duo_synced,
    _resolve_room,
)
from cal_iut.api.state import get_state  # noqa: E402
from cal_iut.api.validation import suggest_alternative_slots, validate_move  # noqa: E402
from cal_iut.cli import _construire_etat_pour_completion  # noqa: E402
from cal_iut.models.session import SessionToPlace  # noqa: E402
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY  # noqa: E402
from cal_iut.solver.constraints import cohort_sequence_pairs  # noqa: E402
from cal_iut.solver.decomposed import (  # noqa: E402
    FI_WEEKLY_CAP_SLOTS,
    _build_sequence_neighbors,
    _cours_avec_progression_declaree,
    _movable_bounds,
)
from cal_iut.solver.resources import build_student_cohorts  # noqa: E402
from cal_iut.solver.rooms import PlacedSessionWithRoom  # noqa: E402

SPW = DAYS_PER_WEEK * SLOTS_PER_DAY
FC_GROUPING_PAIRS = [("WRA507D", "WSA501D")]
CM_THRESHOLD = 2  # au-delà, une journée est jugée "chargée en CM"


# ==========================================================================
# Chargement
# ==========================================================================


def charger_etat(timetable_path: Path):
    sessions_path = ROOT / "data" / "generated" / "sessions.json"
    sessions = [SessionToPlace(**s) for s in json.loads(sessions_path.read_text(encoding="utf-8"))]
    donnees = json.loads(timetable_path.read_text(encoding="utf-8"))

    etat = _construire_etat_pour_completion(ROOT)
    etat.sessions = sessions
    etat.sessions_by_id = {s.id: s for s in sessions}
    etat.timetable = [
        PlacedSessionWithRoom(
            session_id=p["session_id"], week=p["week"], day=p["day"], slot=p["slot"],
            course_code=p["course_code"], group_ids=p["group_ids"], teacher_codes=p["teacher_codes"],
            room_id=p.get("room_id"), room_label=p.get("room_label"),
        )
        for p in donnees.get("placements", [])
    ]
    return etat, donnees


def _t_of(etat) -> dict[str, int]:
    return {p.session_id: p.week * SPW + p.day * SLOTS_PER_DAY + p.slot for p in etat.timetable}


def _w_of(etat) -> dict[str, int]:
    return {p.session_id: p.week for p in etat.timetable}


# ==========================================================================
# Détection des violations d'ordre — MÊME calcul que l'audit
# (`export/html_view.py::_rule_checks`), pour que "corrigé" veuille dire
# exactement "l'audit passera au vert".
# ==========================================================================


def violations_ordre(etat) -> list[tuple[str, str, str]]:
    """Liste de `(id_avant, id_apres, source)` en violation — `source` vaut
    "sequence" (même cours/groupe brut) ou "cohorte" (CM promo vs TD/TP)."""
    t_of = _t_of(etat)
    placees = set(t_of)
    placed_sessions = [s for s in etat.sessions if s.id in placees]

    resultat: list[tuple[str, str, str]] = []

    # Séances du MÊME type (TD-TD, TP-TP) exemptées quand aucune progression
    # de contenu n'est déclarée pour ce cours — même correctif que le
    # solveur et l'audit (retour utilisateur 27/08/2026, Kyllian Bresson :
    # « TD n°3 avant TD n°1, ce n'est pas une erreur »). Sans lui, cette
    # passe s'épuisait à essayer de réparer des paires que rien n'oblige à
    # ordonner, pour un résultat que l'audit ne compte de toute façon plus
    # comme une violation.
    cours_avec_progression = _cours_avec_progression_declaree(ROOT)

    by_group_course: dict[tuple[str, str, str], list[SessionToPlace]] = defaultdict(list)
    for s in placed_sessions:
        if s.sequence_order is None:
            continue
        for gid in s.group_ids:
            by_group_course[(s.course_code, s.semestre, gid)].append(s)
    for lst in by_group_course.values():
        ordered = sorted(lst, key=lambda s: s.sequence_order or 0)
        for a, b in zip(ordered, ordered[1:]):
            if (a.sequence_order or 0) == (b.sequence_order or 0):
                continue
            if a.session_type == b.session_type and (a.course_code, a.semestre) not in cours_avec_progression:
                continue
            if not (t_of[a.id] < t_of[b.id]):
                resultat.append((a.id, b.id, "sequence"))

    for a, b in cohort_sequence_pairs(placed_sessions, etat.groups):
        if a in t_of and b in t_of and not (t_of[a] < t_of[b]):
            resultat.append((a, b, "cohorte"))

    return resultat


# ==========================================================================
# Plafond hebdomadaire de cohorte (23 créneaux/semaine, cf.
# `FI_WEEKLY_CAP_SLOTS`) : trouvé le 27/08/2026 — `_hard_constraint_context`
# / `suggest_alternative_slots` ne le vérifient PAS du tout (seul le module
# de complétion l'avait, cf. §66). Une relocalisation OU une permutation
# pouvait donc réparer un problème en en créant un autre, plus grave (un
# audit a trouvé 12 cohortes au-dessus du plafond après une première passe).
# Factorisé pour être appliqué aux DEUX écritures sur `etat.timetable`
# (`relocaliser` et `_permuter`) — ne pas laisser le même trou ouvert deux
# fois.
# ==========================================================================


def _semaine_respecte_plafond(etat, session, week: int) -> bool:
    """La cohorte de `session` reste-t-elle sous le plafond hebdomadaire
    si `session` est placée en semaine `week` ?

    Suppose que `session` a déjà été retirée de `etat.timetable` (c'est
    le cas à tous les points d'appel : `relocaliser` et `_permuter`
    retirent la/les séance(s) avant de tester des positions).
    """
    duree = max(1, session.duration_slots or 1)
    cohortes = build_student_cohorts(etat.groups) if etat.groups else {}
    mes_cohortes = [c for c, ids in cohortes.items() if ids & set(session.group_ids or [])]
    if not mes_cohortes:
        return True
    for c in mes_cohortes:
        ids = cohortes[c]
        charge = 0
        for p in etat.timetable:
            if p.week != week:
                continue
            if not (ids & set(p.group_ids or [])):
                continue
            autre = etat.sessions_by_id.get(p.session_id)
            charge += max(1, (autre.duration_slots or 1) if autre else 1)
        if charge + duree > FI_WEEKLY_CAP_SLOTS:
            return False
    return True


# ==========================================================================
# Relocalisation d'UNE séance — le seul point d'écriture sur `etat.timetable`
# ==========================================================================


def relocaliser(
    etat, session_id: str, *, semaines_preferees: set[int] | None = None,
    jour_impose: int | None = None, semaine_imposee: int | None = None,
    verifier=None,
    allowed_weeks_override: set[int] | None = None,
) -> bool:
    """Retire `session_id` de sa position actuelle, cherche un créneau valide
    (déjà vérifié par `_hard_constraint_context`/`suggest_alternative_slots`,
    donc jamais en violation d'une règle dure), et l'y replace.

    Remet la séance à sa position D'ORIGINE si aucun candidat convenable
    n'est trouvé — jamais de séance orpheline.

    `verifier` : fonction sans argument, appelée APRÈS le déplacement,
    rendant True si le nouveau placement doit être GARDÉ. Sans elle, tout
    candidat valide est gardé. Avec elle, un déplacement qui ne sert à rien
    (ex. ne réduit pas le nombre de violations) est intégralement ANNULÉ —
    jamais laissé "déplacé pour rien", qui dégraderait le planning ailleurs
    sans bénéfice ici.

    `semaines_preferees` / `jour_impose` / `semaine_imposee` : pour guider la
    recherche vers un objectif précis (diluer un jour, regrouper deux cours)
    sans dupliquer la boucle de recherche pour chaque cas d'usage.

    `allowed_weeks_override` : remplace le calcul normal de `allowed_weeks`
    (via `_hard_constraint_context`, qui inclut l'ordonnancement inter-cours).
    Utilisé par la réparation d'ordre (`passe_reparation_ordre`) : combiner la
    borne inter-cours SOUPLE à la borne même-cours peut produire une fenêtre
    [lo,hi] réellement IMPOSSIBLE alors qu'aucune des deux relations, prise
    seule, n'est en violation dure (cf. docs/DATA.md §67 pour le cas trouvé
    sur le run réel). `None` = comportement normal (dilution CM, regroupement
    FC — aucune des deux ne touche à l'ordonnancement inter-cours).
    """
    session = etat.sessions_by_id.get(session_id)
    if session is None:
        return False
    ancien = next((p for p in etat.timetable if p.session_id == session_id), None)
    if ancien is None:
        return False
    if _is_duo_synced(session, etat.teacher_duos):
        return False  # jamais touché seul : casserait la synchronisation salle rare

    origine = (ancien.week, ancien.day, ancien.slot, ancien.room_id, ancien.room_label)
    etat.timetable.remove(ancien)

    def _restaurer() -> None:
        """Remet la séance EXACTEMENT où elle était — le seul autre point
        d'écriture de cette fonction, pour qu'aucun chemin ne puisse la
        laisser orpheline (bug corrigé le 27/08/2026 : un premier jet
        `return False` en plein milieu de la recherche sortait sans jamais
        rappeler cette restauration)."""
        etat.timetable.append(PlacedSessionWithRoom(
            session_id=session_id, week=origine[0], day=origine[1], slot=origine[2],
            course_code=session.course_code, group_ids=list(session.group_ids or []),
            teacher_codes=list(session.teacher_codes or []), room_id=origine[3], room_label=origine[4],
        ))

    try:
        extra_blocked, allowed_weeks = _hard_constraint_context(etat, session)
        if allowed_weeks_override is not None:
            allowed_weeks = allowed_weeks_override
        horizon = len(etat.calendar.teaching_mondays)
        # `semaine_imposee` : démarrer la recherche PILE sur cette semaine
        # plutôt que toujours depuis la semaine 0 — bug réel trouvé le
        # 27/08/2026 (retour utilisateur : rapprocher deux séances WRA507D/
        # WSA501D d'une même journée échouait alors qu'un créneau libre
        # existait bel et bien) : `max_suggestions=60` peut être entièrement
        # consommé par des semaines PLUS TÔT dans l'horizon avant même
        # d'atteindre la semaine imposée, laissant `candidats` vide après le
        # filtre `c.week == semaine_imposee` ci-dessous — jamais une absence
        # réelle de créneau, juste un plafond de suggestions épuisé trop tôt.
        if semaine_imposee is not None:
            recherche_depuis, recherche_semaines = semaine_imposee, 1
        else:
            recherche_depuis, recherche_semaines = 0, horizon
        brutes = suggest_alternative_slots(
            session_id, list(session.group_ids or []), list(session.teacher_codes or []),
            _as_placed(etat.timetable), etat.calendar, session.semestre,
            teacher_availability=etat.teacher_availability, room_id=None,
            search_from_week=recherche_depuis, max_weeks=recherche_semaines, max_suggestions=60,
            extra_blocked=extra_blocked, allowed_weeks=allowed_weeks,
            sessions_by_id=etat.sessions_by_id, groups=etat.groups,
        )
    except Exception:
        _restaurer()
        return False

    candidats = list(brutes)
    if semaine_imposee is not None:
        candidats = [c for c in candidats if c.week == semaine_imposee]
    if jour_impose is not None:
        candidats = [c for c in candidats if c.day == jour_impose]
    if not candidats and semaines_preferees:
        # repli : la contrainte de guidage n'a rien trouvé, on retente sans
        # elle plutôt que d'abandonner — mieux vaut une relocalisation
        # imparfaite qu'aucune.
        candidats = list(brutes)

    if not candidats:
        _restaurer()
        return False

    # Le plus proche de la position d'origine d'abord (semaine, puis jour) :
    # une relocalisation minimale perturbe moins le reste du planning qu'un
    # grand saut arbitraire.
    #
    # La position D'ORIGINE elle-même peut réapparaître dans les candidats
    # (le créneau vient d'être libéré par le retrait ci-dessus) et, triée par
    # proximité, ressortait alors TOUJOURS en tête — un `verifier` la rejette
    # forcément (aucun déplacement n'a eu lieu), mais le bug corrigé le
    # 27/08/2026 arrêtait toute la recherche dès ce premier refus, sans
    # jamais essayer les candidats suivants. Exclue ici, jamais un choix utile.
    candidats = [c for c in candidats if (c.week, c.day, c.slot) != origine[:3]]

    # Plafond hebdomadaire de la cohorte (23 créneaux/semaine, cf.
    # `FI_WEEKLY_CAP_SLOTS`) : trouvé le 27/08/2026 — `_hard_constraint_context`
    # / `suggest_alternative_slots` ne le vérifient PAS du tout (seul le
    # module de complétion l'avait, cf. §66), une relocalisation pouvait
    # donc réparer un problème en en créant un autre, plus grave (un audit
    # a trouvé 12 cohortes au-dessus du plafond après une première passe).
    candidats = [c for c in candidats if _semaine_respecte_plafond(etat, session, c.week)]

    if not candidats:
        _restaurer()
        return False

    def _distance(c):
        pref = 0 if (semaines_preferees and c.week in semaines_preferees) else 1
        return (pref, abs(c.week - origine[0]), abs(c.day - origine[1]), abs(c.slot - origine[2]))

    candidats.sort(key=_distance)

    for choisi in candidats:
        try:
            salle = _resolve_room(etat, session, choisi.week, choisi.day, choisi.slot, origine[3])
            validation = validate_move(
                session_id, choisi.week, choisi.day, choisi.slot, _as_placed(etat.timetable),
                list(session.group_ids or []), list(session.teacher_codes or []),
                getattr(salle, "id", None), sessions_by_id=etat.sessions_by_id, groups=etat.groups,
            )
        except Exception:
            continue
        if not validation.valid:
            continue  # ne devrait pas arriver (la suggestion est déjà vérifiée) : on tente le suivant

        etat.timetable.append(PlacedSessionWithRoom(
            session_id=session_id, week=choisi.week, day=choisi.day, slot=choisi.slot,
            course_code=session.course_code, group_ids=list(session.group_ids or []),
            teacher_codes=list(session.teacher_codes or []),
            room_id=getattr(salle, "id", None), room_label=getattr(salle, "label", None),
        ))

        if verifier is not None and not verifier():
            # Ce candidat précis ne sert à rien pour l'objectif visé : annulé,
            # mais on continue d'essayer les AUTRES candidats — abandonner ici
            # (bug corrigé le 27/08/2026) revenait à ne jamais tester que le
            # tout premier essai, souvent sans rapport avec le meilleur choix.
            etat.timetable[:] = [p for p in etat.timetable if p.session_id != session_id]
            continue
        return True

    _restaurer()
    return False


def _as_placed(timetable):
    from cal_iut.solver.cpsat import PlacedSession
    return [PlacedSession(p.session_id, p.week, p.day, p.slot, p.course_code, p.group_ids, p.teacher_codes) for p in timetable]


# ==========================================================================
# Passe 1 — réparation de l'ordre (contrainte dure)
# ==========================================================================


def _allowed_weeks_pour_reparation(etat, session_id: str) -> set[int]:
    """`allowed_weeks` calculée sur les DEUX sources dures uniquement (séquence
    même-cours + cohorte), SANS l'ordonnancement inter-cours (souple côté
    solveur) — cf. docstring de `relocaliser::allowed_weeks_override`.

    Construite sur les seules séances DÉJÀ PLACÉES, jamais `etat.sessions` en
    entier. Trouvé le 27/08/2026 : quand une séance intermédiaire d'une chaîne
    (ex. #7 sur 5→6→7→8) est manquante, `_build_sequence_neighbors` relie
    quand même #6 à #7 (pas à #8) — le voisin direct de #6 devient une séance
    non placée, dont la borne par défaut est trop souple pour empêcher #6 de
    passer après #8. `violations_ordre`, lui, saute les séances manquantes et
    compare les voisins RÉELLEMENT adjacents dans le planning (#6 et #8
    directement) : sans ce même filtre ici, la borne calculée ne protège pas
    ce que le détecteur de violations vient justement de signaler.

    L'horizon `n_weeks` DOIT être calculé EXACTEMENT comme dans
    `_hard_constraint_context` (`main.py`) : `max(semaine placée) + 1`, jamais
    la longueur totale du calendrier. Bug trouvé le 27/08/2026 en auditant un
    run polissé : une PREMIÈRE version utilisait `len(calendar.teaching_mondays)`
    (~38 semaines) ici, bien PLUS LARGE que l'horizon dynamique que
    `_hard_constraint_context` utilise réellement pour construire
    `extra_blocked` (verrou PAC, présence FC, SAE, planning officiel) — la
    boucle qui remplit `extra_blocked` s'arrête à CET horizon dynamique, donc
    toute semaine au-delà, même autorisée ici par erreur, n'est JAMAIS
    vérifiée contre ces règles. Résultat concret : WSA502D-S5-TP-8-but3-dev-fc-tp-e
    déplacée en semaine 25 alors que les étudiants FC y sont en entreprise —
    `allowed_weeks_override` l'autorisait, mais `extra_blocked` ne la couvrait
    pas encore à ce moment de la réparation. Avec le même horizon des deux
    côtés, une semaine ne peut plus être "autorisée" ici sans avoir aussi été
    réellement vérifiée là-bas.
    """
    placees = {p.session_id for p in etat.timetable}
    sessions_placees = [s for s in etat.sessions if s.id in placees]
    voisins = _build_sequence_neighbors(sessions_placees, etat.groups, include_ordonnancement=False)
    w_of = _w_of(etat)
    # Comme `relocaliser` retire d'abord `session_id` avant son propre appel à
    # `_hard_constraint_context`, on l'exclut aussi ici du calcul du maximum —
    # sinon, si cette séance était l'unique occupante de la semaine la plus
    # tardive, l'horizon calculé ici resterait un cran trop large par rapport
    # à celui que `_hard_constraint_context` verra réellement une fois la
    # séance retirée.
    n_weeks = (max((p.week for p in etat.timetable if p.session_id != session_id), default=-1)) + 1
    lo, hi = _movable_bounds(session_id, voisins, w_of, n_weeks)
    return set(range(lo, hi + 1)) if hi >= lo else set()


def _permuter(etat, sid_a: str, sid_b: str) -> bool:
    """Échange directement les positions de DEUX séances déjà placées.

    Dernier recours pour une paire en violation où déplacer L'UNE OU L'AUTRE
    séparément échoue — trouvé le 27/08/2026 sur le run réel : quand chaque
    séance est elle-même bornée de près par SES PROPRES voisins de chaîne
    (ex. #6 coincée entre #5 et #8, #8 coincée entre #6 et #9), aucune des
    deux ne peut bouger seule vers une fenêtre libre, alors qu'un simple
    ÉCHANGE de leurs deux créneaux (déjà valides chacun pour une séance de ce
    cours/groupe) suffit à inverser leur ordre relatif sans toucher au reste
    du planning.

    Chaque nouvelle position est revalidée par `validate_move` (durées et
    enseignants pouvant différer entre les deux séances), par
    `_institutional_violations` (verrou PAC, présence FC, ordre pédagogique —
    trouvé le 27/08/2026 : une PREMIÈRE version ne vérifiait que les
    conflits de RESSOURCES, pas les règles institutionnelles ; deux séances
    aux contraintes différentes — l'une FI sans restriction, l'autre FC
    limitée à ses jours de présence — peuvent chacune être valides à LEUR
    position d'origine sans l'être à celle de l'autre une fois échangées)
    et par `_semaine_respecte_plafond` (même trouvaille que dans
    `relocaliser` : un échange peut aussi faire déborder le plafond
    hebdomadaire d'une cohorte). Tout échange invalide est annulé
    intégralement.
    """
    pa = next((p for p in etat.timetable if p.session_id == sid_a), None)
    pb = next((p for p in etat.timetable if p.session_id == sid_b), None)
    if pa is None or pb is None:
        return False
    sa, sb = etat.sessions_by_id.get(sid_a), etat.sessions_by_id.get(sid_b)
    if sa is None or sb is None:
        return False
    if _is_duo_synced(sa, etat.teacher_duos) or _is_duo_synced(sb, etat.teacher_duos):
        return False

    pos_a, pos_b = (pa.week, pa.day, pa.slot), (pb.week, pb.day, pb.slot)
    etat.timetable.remove(pa)
    etat.timetable.remove(pb)

    def _essayer(sid, session, pos, salle_pref):
        w, d, sl = pos
        extra_blocked, allowed_weeks = _hard_constraint_context(etat, session)
        if _institutional_violations(w, d, sl, extra_blocked, allowed_weeks):
            return None
        if not _semaine_respecte_plafond(etat, session, w):
            return None
        salle = _resolve_room(etat, session, w, d, sl, salle_pref)
        v = validate_move(
            sid, w, d, sl, _as_placed(etat.timetable),
            list(session.group_ids or []), list(session.teacher_codes or []),
            getattr(salle, "id", None), sessions_by_id=etat.sessions_by_id, groups=etat.groups,
        )
        if not v.valid:
            return None
        return PlacedSessionWithRoom(
            session_id=sid, week=w, day=d, slot=sl, course_code=session.course_code,
            group_ids=list(session.group_ids or []), teacher_codes=list(session.teacher_codes or []),
            room_id=getattr(salle, "id", None), room_label=getattr(salle, "label", None),
        )

    try:
        nouvelle_a = _essayer(sid_a, sa, pos_b, pb.room_id)
        if nouvelle_a is not None:
            etat.timetable.append(nouvelle_a)
        nouvelle_b = _essayer(sid_b, sb, pos_a, pa.room_id) if nouvelle_a is not None else None
        if nouvelle_b is not None:
            etat.timetable.append(nouvelle_b)
    except Exception:
        nouvelle_a = nouvelle_b = None

    if nouvelle_a is not None and nouvelle_b is not None:
        return True

    # Échange invalide ou partiel : tout annuler, remettre les deux séances
    # exactement où elles étaient.
    etat.timetable[:] = [p for p in etat.timetable if p.session_id not in (sid_a, sid_b)]
    etat.timetable.append(PlacedSessionWithRoom(
        session_id=sid_a, week=pos_a[0], day=pos_a[1], slot=pos_a[2], course_code=sa.course_code,
        group_ids=list(sa.group_ids or []), teacher_codes=list(sa.teacher_codes or []),
        room_id=pa.room_id, room_label=pa.room_label,
    ))
    etat.timetable.append(PlacedSessionWithRoom(
        session_id=sid_b, week=pos_b[0], day=pos_b[1], slot=pos_b[2], course_code=sb.course_code,
        group_ids=list(sb.group_ids or []), teacher_codes=list(sb.teacher_codes or []),
        room_id=pb.room_id, room_label=pb.room_label,
    ))
    return False


def passe_reparation_ordre(etat, *, max_passes: int = 4) -> dict:
    avant = len(violations_ordre(etat))
    reparees = 0
    for _tour in range(max_passes):
        viol = violations_ordre(etat)
        if not viol:
            break
        compte = Counter()
        for a, b, _ in viol:
            compte[a] += 1
            compte[b] += 1
        # Le plus impliqué d'abord : le corriger règle souvent plusieurs
        # paires d'un coup.
        ordre = [sid for sid, _ in compte.most_common()]
        progres = False
        for sid in ordre:
            if not any(sid in (a, b) for a, b, _ in violations_ordre(etat)):
                continue  # déjà réglé par une relocalisation précédente ce tour-ci
            n_avant = len(violations_ordre(etat))
            bornes = _allowed_weeks_pour_reparation(etat, sid)
            if relocaliser(
                etat, sid, verifier=lambda: len(violations_ordre(etat)) < n_avant,
                allowed_weeks_override=bornes,
            ):
                reparees += 1
                progres = True
        if not progres:
            break

    # Dernier recours — échange direct pour les paires encore bloquées :
    # aucune des deux ne peut bouger seule (chacune coincée entre SES propres
    # voisins de chaîne), mais échanger leurs deux créneaux inverse leur
    # ordre relatif sans jamais toucher au reste du planning.
    for a, b, _src in list(violations_ordre(etat)):
        n_avant = len(violations_ordre(etat))
        snapshot = list(etat.timetable)
        if _permuter(etat, a, b):
            if len(violations_ordre(etat)) < n_avant:
                reparees += 1
            else:
                # L'échange a réussi techniquement (deux positions valides)
                # mais n'a rien réglé — voire déplacé le problème ailleurs :
                # annulé intégralement, comme toute relocalisation inutile.
                etat.timetable[:] = snapshot

    restantes = violations_ordre(etat)
    return {
        "avant": avant, "apres": len(restantes), "tentatives_reparees": reparees,
        "restantes": [(a, b, src) for a, b, src in restantes],
    }


# ==========================================================================
# Passe 2 — dilution des CM (BUT1, confort)
# ==========================================================================


def journees_cm_chargees(etat) -> list[tuple[str, int, int, list[str]]]:
    """(promo_id, semaine, jour, [session_id CM excédentaires]) pour chaque
    journée dépassant `CM_THRESHOLD` créneaux CM."""
    promo_ids = {g.id for g in etat.groups if g.kind == "promo"}
    by_key: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for p in etat.timetable:
        s = etat.sessions_by_id.get(p.session_id)
        if s is None or str(getattr(s.session_type, "value", s.session_type)) != "CM":
            continue
        for gid in p.group_ids:
            if gid in promo_ids:
                by_key[(gid, p.week, p.day)].append(p.session_id)
    return [
        (gid, w, d, sids) for (gid, w, d), sids in by_key.items() if len(sids) > CM_THRESHOLD
    ]


def _excedent_total_cm(etat) -> int:
    """Somme des dépassements (`count - CM_THRESHOLD`) sur toutes les
    journées chargées — l'AMPLEUR du problème, pas son nombre de journées.

    Bug trouvé le 27/08/2026 : compter les journées encore « en excès »
    rejetait à tort CHAQUE relocalisation individuelle d'une journée à 6 CM
    — la retirer une fois laisse encore 5 (> seuil 2), donc toujours
    « en excès », donc annulée par l'ancien `verifier`, qui ne voyait jamais
    le progrès réel (6 -> 5 -> 4 -> 3 -> 2) tant que le seuil n'était pas
    franchi d'un coup.
    """
    return sum(len(sids) - CM_THRESHOLD for *_key, sids in journees_cm_chargees(etat))


def passe_dilution_cm(etat, *, max_passes: int = 3) -> dict:
    avant = len(journees_cm_chargees(etat))
    excedent_avant = _excedent_total_cm(etat)
    deplacees = 0
    for _ in range(max_passes):
        journees = journees_cm_chargees(etat)
        if not journees:
            break
        progres = False
        for gid, w, d, sids in journees:
            # Une seule séance par journée surchargée à la fois — recalculée
            # à chaque itération, l'excédent baisse tour après tour.
            excedent = sids[CM_THRESHOLD:]
            for sid in excedent:
                autres_semaines_meme_promo = {
                    p.week for p in etat.timetable
                    if p.session_id != sid and gid in p.group_ids
                }
                n_avant = _excedent_total_cm(etat)
                if relocaliser(
                    etat, sid, semaines_preferees={w} | autres_semaines_meme_promo,
                    verifier=lambda: _excedent_total_cm(etat) < n_avant,
                ):
                    deplacees += 1
                    progres = True
        if not progres:
            break
    return {
        "avant": avant, "apres": len(journees_cm_chargees(etat)), "deplacees": deplacees,
        "excedent_avant": excedent_avant, "excedent_apres": _excedent_total_cm(etat),
    }


# ==========================================================================
# Passe 3 — regroupement WRA507D / WSA501D (BUT3-DEV-FC, confort)
# ==========================================================================


def _seances_fc_par_semaine(etat) -> dict[tuple[str, int], list]:
    """(groupe, semaine) -> placements WRA507D+WSA501D de ce groupe cette
    semaine-là, tous cours confondus (`FC_GROUPING_PAIRS`)."""
    codes = {c for paire in FC_GROUPING_PAIRS for c in paire}
    by_key: dict[tuple[str, int], list] = defaultdict(list)
    for p in etat.timetable:
        s = etat.sessions_by_id.get(p.session_id)
        if s is None or s.course_code not in codes:
            continue
        for gid in p.group_ids:
            by_key[(gid, p.week)].append(p)
    return by_key


def jours_fc_disperses(etat) -> list[tuple[str, int, int]]:
    """(groupe, semaine, nombre de jours DISTINCTS utilisés) pour chaque
    semaine où WRA507D/WSA501D occupent plus d'UN jour — le nombre de jours
    est la mesure d'AMPLEUR (pas un tout-ou-rien) : sept séances WRA507D ne
    tiennent pas forcément sur une seule journée de 6 créneaux, mais passer
    de 3 jours à 2 reste un progrès réel, qu'un simple « regroupé oui/non »
    ne peut pas voir (bug corrigé le 27/08/2026, même famille que la
    dilution des CM : compter des JOURNÉES plutôt que leur AMPLEUR rejetait
    à tort tout progrès partiel)."""
    resultat = []
    for (gid, w), placements in _seances_fc_par_semaine(etat).items():
        jours = {p.day for p in placements}
        if len(jours) > 1:
            resultat.append((gid, w, len(jours)))
    return resultat


def _jours_fc_total(etat) -> int:
    """Somme du nombre de jours utilisés sur toutes les semaines concernées —
    la mesure d'AMPLEUR utilisée par le `verifier` de chaque relocalisation."""
    return sum(n for _gid, _w, n in jours_fc_disperses(etat))


def passe_regroupement_fc(etat, *, max_passes: int = 3) -> dict:
    avant = len(jours_fc_disperses(etat))
    ampleur_avant = _jours_fc_total(etat)
    regroupees = 0
    for _ in range(max_passes):
        cibles = _seances_fc_par_semaine(etat)
        semaines_dispersees = {(gid, w) for gid, w, _n in jours_fc_disperses(etat)}
        if not semaines_dispersees:
            break
        progres = False
        for (gid, w) in semaines_dispersees:
            placements = cibles.get((gid, w), [])
            if len(placements) < 2:
                continue
            par_jour = Counter(p.day for p in placements)
            # Vise le jour qui accueille déjà le PLUS de séances — celui qui
            # a le plus de chances de pouvoir absorber les autres.
            jour_vise, _ = par_jour.most_common(1)[0]
            # Les séances déjà sur ce jour restent ; on essaie de rapprocher
            # les autres, UNE À LA FOIS (jamais en bloc : chaque relocalisation
            # est jugée sur son propre mérite via `verifier`).
            for p in placements:
                if p.day == jour_vise:
                    continue
                n_avant = _jours_fc_total(etat)
                if relocaliser(
                    etat, p.session_id, semaine_imposee=w, jour_impose=jour_vise,
                    verifier=lambda: _jours_fc_total(etat) < n_avant,
                ):
                    regroupees += 1
                    progres = True
        if not progres:
            break
    return {
        "avant": avant, "apres": len(jours_fc_disperses(etat)), "regroupees": regroupees,
        "ampleur_avant": ampleur_avant, "ampleur_apres": _jours_fc_total(etat),
    }


# ==========================================================================
# Passe 3bis — fermeture des trous WRA507D/WSA501D DANS une même journée
# ==========================================================================
#
# Retour utilisateur (27/08/2026, sur BTO/JSA en BUT3-DEV-FC) : « laisse les
# séances de BTO le mercredi, c'est pas grave tant que c'est des blocs de 3h
# ou 4h30 ». Le regroupement par JOUR (passe 3) est buté sur les
# indisponibilités déclarées de BTO (dispo uniquement mercredi/jeudi matin) —
# mais rien n'empêchait, À L'INTÉRIEUR d'une même journée déjà retenue, deux
# séances de rester séparées par un créneau vide (ex. créneau 1 puis 3,
# laissant 2 libre) au lieu de se toucher. Cette passe cible spécifiquement
# CE trou-là, sans jamais essayer de changer de jour ni d'enseignant.


def _trous_fc_par_jour(etat) -> list[tuple[str, int, int, int]]:
    """(groupe, semaine, jour, trous) pour chaque journée WRA507D/WSA501D où
    l'écart entre le premier et le dernier créneau dépasse le nombre de
    séances réellement posées — un CRÉNEAU VIDE entre deux séances du même
    jour, jamais un simple compte de séances."""
    codes = {c for paire in FC_GROUPING_PAIRS for c in paire}
    by_day: dict[tuple[str, int, int], list] = defaultdict(list)
    for p in etat.timetable:
        s = etat.sessions_by_id.get(p.session_id)
        if s is None or s.course_code not in codes:
            continue
        for gid in p.group_ids:
            by_day[(gid, p.week, p.day)].append(p)
    resultat = []
    for (gid, w, d), placements in by_day.items():
        if len(placements) < 2:
            continue
        slots = sorted(p.slot for p in placements)
        etendue = slots[-1] - slots[0] + 1
        trous = etendue - len(placements)
        if trous > 0:
            resultat.append((gid, w, d, trous))
    return resultat


def _trous_fc_total(etat) -> int:
    """Somme des créneaux vides sur toutes les journées concernées — la
    mesure d'AMPLEUR utilisée par le `verifier` de chaque relocalisation,
    même famille que `_jours_fc_total`/`_excedent_total_cm`."""
    return sum(t for *_r, t in _trous_fc_par_jour(etat))


def passe_fermeture_trous_fc(etat, *, max_passes: int = 3) -> dict:
    avant = len(_trous_fc_par_jour(etat))
    ampleur_avant = _trous_fc_total(etat)
    fermees = 0
    for _ in range(max_passes):
        cibles = _trous_fc_par_jour(etat)
        if not cibles:
            break
        progres = False
        for gid, w, d, _trous in cibles:
            codes = {c for paire in FC_GROUPING_PAIRS for c in paire}
            placements = [
                p for p in etat.timetable
                if p.week == w and p.day == d and gid in p.group_ids
                and (s := etat.sessions_by_id.get(p.session_id)) is not None
                and s.course_code in codes
            ]
            if len(placements) < 2:
                continue
            # La séance la plus TARDIVE d'abord : la rapprocher du bloc déjà
            # formé plus tôt dans la journée coûte le moins de recherche
            # (relocaliser trie déjà par proximité de l'origine).
            placements.sort(key=lambda p: -p.slot)
            for p in placements:
                n_avant = _trous_fc_total(etat)
                if relocaliser(
                    etat, p.session_id, semaine_imposee=w, jour_impose=d,
                    verifier=lambda: _trous_fc_total(etat) < n_avant,
                ):
                    fermees += 1
                    progres = True
                    break
        if not progres:
            break
    return {
        "avant": avant, "apres": len(_trous_fc_par_jour(etat)), "fermees": fermees,
        "ampleur_avant": ampleur_avant, "ampleur_apres": _trous_fc_total(etat),
    }


# ==========================================================================
# Passe 4bis — libération des trous occupés par un AUTRE cours
# ==========================================================================
#
# Trouvé le 27/08/2026 en vérifiant `passe_fermeture_trous_fc` sur le run
# réel : 0 relocalisation malgré des trous détectés — les « trous » ne sont
# PAS des créneaux vides, mais occupés par un AUTRE vrai cours du même
# groupe (BUT3-DEV-FC suit bien plus que WRA507D/WSA501D). Fermer le trou
# exige donc de déplacer CE cours ailleurs d'abord — une opération en deux
# temps, jamais gardée si le second temps échoue.


def passe_liberation_trous_fc(etat, *, max_passes: int = 3) -> dict:
    """Pour chaque trou WRA507D/WSA501D occupé par un autre cours, déplace ce
    cours ailleurs (recherche libre, n'importe quelle semaine valable) PUIS
    rapproche la séance FC isolée dans le créneau ainsi libéré. Si le
    rapprochement échoue, le cours déplacé est ramené dans la même journée —
    jamais laissé « déplacé pour rien » ailleurs dans le semestre."""
    codes_fc = {c for paire in FC_GROUPING_PAIRS for c in paire}
    avant = len(_trous_fc_par_jour(etat))
    ampleur_avant = _trous_fc_total(etat)
    liberees = 0
    for _ in range(max_passes):
        trous = _trous_fc_par_jour(etat)
        if not trous:
            break
        progres = False
        for gid, w, d, _t in trous:
            fc_placements = [
                p for p in etat.timetable
                if p.week == w and p.day == d and gid in p.group_ids
                and (s := etat.sessions_by_id.get(p.session_id)) is not None
                and s.course_code in codes_fc
            ]
            if len(fc_placements) < 2:
                continue
            slots_fc = sorted(p.slot for p in fc_placements)
            trous_slots = sorted(set(range(slots_fc[0], slots_fc[-1] + 1)) - {p.slot for p in fc_placements})
            if not trous_slots:
                continue

            for slot_vise in trous_slots:
                bloqueur = next(
                    (p for p in etat.timetable if p.week == w and p.day == d and p.slot == slot_vise and gid in p.group_ids),
                    None,
                )
                if bloqueur is None:
                    continue
                position_origine = (bloqueur.week, bloqueur.day, bloqueur.slot)
                sid_bloqueur = bloqueur.session_id
                n_avant = _trous_fc_total(etat)

                if not relocaliser(etat, sid_bloqueur, verifier=lambda: True):
                    continue  # le bloqueur n'a nulle part où aller : rien de tenté, rien à défaire

                # Le créneau est libéré : rapprocher la séance FC la plus
                # proche de ce trou, EN PRIORITÉ celle qui le comblerait
                # exactement.
                fc_ici = [
                    p for p in etat.timetable
                    if p.week == w and p.day == d and gid in p.group_ids
                    and (s := etat.sessions_by_id.get(p.session_id)) is not None
                    and s.course_code in codes_fc
                ]
                fc_ici.sort(key=lambda p: abs(p.slot - slot_vise))
                reussi = False
                for p in fc_ici:
                    if relocaliser(
                        etat, p.session_id, semaine_imposee=w, jour_impose=d,
                        verifier=lambda: _trous_fc_total(etat) < n_avant,
                    ):
                        reussi = True
                        break

                if reussi:
                    liberees += 1
                    progres = True
                    break

                # Rapprochement impossible : ramener le bloqueur dans la
                # MÊME journée (son créneau d'origine est de nouveau libre —
                # jamais laissé ailleurs pour rien).
                relocaliser(
                    etat, sid_bloqueur,
                    semaine_imposee=position_origine[0], jour_impose=position_origine[1],
                    verifier=lambda: True,
                )
        if not progres:
            break
    return {
        "avant": avant, "apres": len(_trous_fc_par_jour(etat)), "liberees": liberees,
        "ampleur_avant": ampleur_avant, "ampleur_apres": _trous_fc_total(etat),
    }


# ==========================================================================
# Écriture
# ==========================================================================


def sauvegarder(etat, donnees: dict, chemin: Path) -> None:
    donnees["placements"] = [
        {
            "session_id": p.session_id, "week": p.week, "day": p.day, "slot": p.slot,
            "course_code": p.course_code, "group_ids": p.group_ids, "teacher_codes": p.teacher_codes,
            "room_id": p.room_id, "room_label": p.room_label,
        }
        for p in etat.timetable
    ]
    chemin.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timetable", default=str(ROOT / "data" / "generated" / "timetable_final.json"))
    parser.add_argument("--output", default=None)
    parser.add_argument("--sans-cm", action="store_true", help="Ne pas exécuter la passe 2 (dilution CM)")
    parser.add_argument("--sans-fc", action="store_true", help="Ne pas exécuter la passe 3 (regroupement FC)")
    args = parser.parse_args()

    chemin = Path(args.timetable)
    etat, donnees = charger_etat(chemin)
    avant_total = len(etat.timetable)

    print("=" * 70)
    print("POLISSAGE DU RUN — réparation d'ordre, dilution CM, regroupement FC")
    print("=" * 70)

    print("\n[1/3] Réparation de l'ordre pédagogique (contrainte dure)…")
    r1 = passe_reparation_ordre(etat)
    print(f"  violations : {r1['avant']} -> {r1['apres']}")
    if r1["restantes"]:
        print(f"  {len(r1['restantes'])} non réparables automatiquement (aucun créneau valable trouvé) :")
        for a, b, src in r1["restantes"][:10]:
            print(f"    [{src}] {a}  <->  {b}")

    if not args.sans_cm:
        print("\n[2/3] Dilution des CM concentrés (BUT1)…")
        r2 = passe_dilution_cm(etat)
        print(f"  journées CM chargées (>{CM_THRESHOLD}/jour) : {r2['avant']} -> {r2['apres']}  ({r2['deplacees']} séance(s) déplacée(s))")
        print(f"  créneaux CM en excès (au-delà de {CM_THRESHOLD}/jour) : {r2['excedent_avant']} -> {r2['excedent_apres']}")
    else:
        r2 = None

    if not args.sans_fc:
        print("\n[3/4] Regroupement WRA507D/WSA501D (BUT3-DEV-FC)…")
        r3 = passe_regroupement_fc(etat)
        print(f"  semaines encore dispersées sur plusieurs jours : {r3['avant']} -> {r3['apres']}  ({r3['regroupees']} relocalisation(s))")
        print(f"  jours utilisés au total (ampleur) : {r3['ampleur_avant']} -> {r3['ampleur_apres']}")

        print("\n[4/5] Libération des trous WRA507D/WSA501D occupés par un autre cours…")
        r4b = passe_liberation_trous_fc(etat)
        print(f"  journées avec un trou : {r4b['avant']} -> {r4b['apres']}  ({r4b['liberees']} libération(s))")
        print(f"  créneaux vides au total (ampleur) : {r4b['ampleur_avant']} -> {r4b['ampleur_apres']}")

        print("\n[5/5] Fermeture des trous WRA507D/WSA501D dans une même journée…")
        r4 = passe_fermeture_trous_fc(etat)
        print(f"  journées avec un trou : {r4['avant']} -> {r4['apres']}  ({r4['fermees']} relocalisation(s))")
        print(f"  créneaux vides au total (ampleur) : {r4['ampleur_avant']} -> {r4['ampleur_apres']}")
    else:
        r3 = None
        r4 = None
        r4b = None

    apres_total = len(etat.timetable)
    print(f"\nSéances placées : {avant_total} -> {apres_total} (doit être identique — relocalisation, jamais suppression)")
    assert avant_total == apres_total, "des séances ont disparu pendant le polissage — ANNULÉ, rien n'est écrit"

    sortie = Path(args.output) if args.output else chemin
    sauvegarder(etat, donnees, sortie)
    print(f"\nécrit : {sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
