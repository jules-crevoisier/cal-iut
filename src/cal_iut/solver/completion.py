"""Placer, après coup, les séances que le solveur n'a pas su placer.

Pourquoi ce module existe (26/08/2026). Le solveur place ~96,5 % des séances ;
le reste bute sur des combinaisons prouvées infaisables *à l'échelle de la
semaine que l'étage 2 leur a assignée* — pas sur une impossibilité absolue.
Vérifié sur le run réel : sur 20 séances manquantes tirées au hasard, **20**
avaient au moins un créneau parfaitement valable ailleurs dans le semestre.

Faire cliquer une personne 85 fois pour poser des séances que la machine sait
poser serait un gâchis. Ce module fait le tour d'abord ; l'onglet « À placer »
reste là pour ce qu'il ne sait pas faire, et pour reprendre la main.

**Ce que ce module N'EST PAS.** Ce n'est pas un second solveur : il ne déplace
jamais une séance déjà posée, ne cherche aucun optimum, et ne revient pas sur
ses choix. C'est un remplissage glouton, honnête sur ce qu'il ne peut pas
faire. Il ne remplace pas une régénération de semaine, qui elle réarrange.

**Les règles vérifiées.** Le point délicat est que la validation du
glisser-déposer (`api/validation.py`) ne couvre pas tout ce que le solveur
impose. Poser une séance sans plus de contrôle, c'est risquer de mettre WRA507D
en mars alors qu'une règle exige janvier. Sont donc vérifiés ici, en plus :

- **bornes de cours** (`CourseMinWeekRule`, `CourseMaxWeekRule`) ;
- **fenêtres de dates par séance** (`SessionDateWindowRule`) ;
- **plafond hebdomadaire de la cohorte étudiante** — jamais dépassé, c'est la
  charge réellement vécue par un étudiant.

Ce qui reste hors de portée est dit explicitement dans le rapport plutôt que
passé sous silence : alternance d'enseignants, groupement en blocs de 3h,
synchronisation des duos salle rare. Une séance concernée n'est pas placée
d'office — elle est rendue à la décision humaine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cal_iut.calendar.academic import AcademicCalendar, semester_week_offset
from cal_iut.models.entities import Group, TeacherAvailability
from cal_iut.models.session import SessionToPlace
from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY
from cal_iut.solver.resources import build_student_cohorts

# Plafond de créneaux hebdomadaires d'une cohorte étudiante. Repris tel quel de
# `decomposed.FI_WEEKLY_CAP_SLOTS` — une seule source de vérité, la divergence
# entre deux valeurs de plafond ayant déjà masqué un problème dix jours durant
# (cf. docs/DATA.md §63.9bis).
from cal_iut.solver.decomposed import FI_WEEKLY_CAP_SLOTS


@dataclass
class SeancePlacee:
    session_id: str
    course_code: str
    week: int
    day: int
    slot: int
    date_iso: str


@dataclass
class SeanceRefusee:
    session_id: str
    course_code: str
    raison: str


@dataclass
class RapportCompletion:
    placees: list[SeancePlacee] = field(default_factory=list)
    refusees: list[SeanceRefusee] = field(default_factory=list)

    def resume(self) -> str:
        if not self.placees and not self.refusees:
            return "Rien à compléter : toutes les séances étaient déjà placées."
        parts = [f"{len(self.placees)} séance(s) placée(s) automatiquement"]
        if self.refusees:
            parts.append(f"{len(self.refusees)} restent à traiter à la main")
        return ", ".join(parts) + "."


def _bornes_de_cours(config_dir: Path, weeks: int) -> dict[tuple[str, str], tuple[int, int]]:
    """(code, semestre) -> (semaine mini, semaine maxi) autorisées."""
    from cal_iut.ingestion.config_loader import (
        load_course_max_week_rules,
        load_course_min_week_rules,
    )

    bornes: dict[tuple[str, str], tuple[int, int]] = {}
    for r in load_course_min_week_rules(config_dir):
        lo, hi = bornes.get((r.course_code, r.semestre), (0, weeks - 1))
        bornes[(r.course_code, r.semestre)] = (max(lo, r.min_week), hi)
    for r in load_course_max_week_rules(config_dir):
        lo, hi = bornes.get((r.course_code, r.semestre), (0, weeks - 1))
        bornes[(r.course_code, r.semestre)] = (lo, min(hi, r.max_week))
    return bornes


def _fenetres_de_dates(
    sessions: list[SessionToPlace],
    calendar: AcademicCalendar,
    week_offset: int,
    weeks: int,
    config_dir: Path,
) -> dict[str, set[int]]:
    """session_id -> semaines admissibles au titre de sa fenêtre de dates.

    Même calcul que `decomposed._date_window_weeks_by_session`, réécrit ici
    plutôt qu'importé pour ne pas dépendre d'un détail privé du solveur — mais
    LA MÊME définition : une semaine est admissible si elle contient au moins
    un jour ouvré compris dans la fenêtre.
    """
    from cal_iut.ingestion.config_loader import load_session_date_windows

    resultat: dict[str, set[int]] = {}
    for rule in load_session_date_windows(config_dir):
        debut = date.fromisoformat(rule.start_date) if rule.start_date else None
        fin = date.fromisoformat(rule.end_date) if rule.end_date else None
        seules = {date.fromisoformat(d) for d in rule.only_dates}
        admissibles = {
            rel
            for rel in range(weeks)
            for jour in range(DAYS_PER_WEEK)
            if (d := calendar.week_day_to_date(week_offset + rel, jour)) is not None
            and d not in calendar.blocked_dates
            and d not in calendar.holidays
            and (not seules or d in seules)
            and (debut is None or d >= debut)
            and (fin is None or d <= fin)
        }
        if not admissibles:
            continue
        for s in sessions:
            if s.course_code != rule.course_code or s.semestre != rule.semestre:
                continue
            if rule.session_type is not None and s.session_type != rule.session_type:
                continue
            if rule.sequence_orders and s.sequence_order not in rule.sequence_orders:
                continue
            precedent = resultat.get(s.id)
            resultat[s.id] = admissibles if precedent is None else (precedent & admissibles)
    return resultat


def _occupation_par_journee(
    placements: list[object],
    sessions_by_id: dict[str, SessionToPlace],
    cohortes: dict[str, set[str]],
) -> dict[tuple[str, int, int], set[int]]:
    """(cohorte, semaine, jour) -> créneaux déjà occupés.

    Sert à choisir OÙ poser : un créneau collé aux cours existants ne crée
    aucun trou, un créneau isolé en crée deux et peut obliger un étudiant à se
    déplacer pour une seule heure et demie.
    """
    occupation: dict[tuple[str, int, int], set[int]] = {}
    for p in placements:
        session = sessions_by_id.get(p.session_id)
        duree = (session.duration_slots or 1) if session else 1
        groupes = set(p.group_ids or [])
        for cohorte, ids in cohortes.items():
            if ids & groupes:
                occupation.setdefault((cohorte, p.week, p.day), set()).update(
                    range(p.slot, p.slot + duree)
                )
    return occupation


def _trous(creneaux: set[int]) -> int:
    """Créneaux vides ENTRE le premier et le dernier cours de la journée."""
    if len(creneaux) < 2:
        return 0
    return (max(creneaux) - min(creneaux) + 1) - len(creneaux)


def cout_creneau(
    candidat: tuple[int, int, int],
    duree: int,
    cohortes_concernees: list[str],
    occupation: dict[tuple[str, int, int], set[int]],
) -> tuple[int, int, int, int]:
    """Ce que ce créneau coûte À L'ÉTUDIANT. Plus petit = meilleur.

    Deux créneaux proposés sont également VALIDES ; seule leur qualité les
    distingue. Prendre systématiquement le premier libre remplirait le semestre
    par le début en semant des trous — la séance atterrit à 8h alors que la
    cohorte ne commence qu'à 11h ce jour-là.

    Les trois derniers champs départagent de façon stable (plus tôt dans le
    semestre, puis dans la journée) : sans eux, deux exécutions identiques
    donneraient deux plannings différents, et tout diagnostic deviendrait
    impossible.
    """
    w, d, sl = candidat
    nouveaux = set(range(sl, sl + duree))
    penalite = 0
    for c in cohortes_concernees:
        deja = occupation.get((c, w, d), set())
        if not deja:
            # Une journée créée de toutes pièces : un déplacement pour cette
            # seule séance. C'est le pire résultat possible pour un étudiant,
            # d'où un poids nettement supérieur à un simple trou.
            penalite += 4
        else:
            penalite += _trous(deja | nouveaux) - _trous(deja)
    if sl + duree - 1 >= SLOTS_PER_DAY - 1:
        penalite += 1  # finit à 18h30
    return (penalite, w, d, sl)


def _charge_par_cohorte_semaine(
    placements: list[object],
    sessions_by_id: dict[str, SessionToPlace],
    cohortes: dict[str, set[str]],
) -> dict[tuple[str, int], int]:
    """(cohorte, semaine) -> créneaux occupés.

    Compté en CRÉNEAUX, durées comprises : un bloc de 3h en vaut deux. C'est
    la charge réellement vécue par un étudiant, la seule qui ait un sens ici.
    """
    charge: dict[tuple[str, int], int] = {}
    for p in placements:
        session = sessions_by_id.get(p.session_id)
        duree = (session.duration_slots or 1) if session else 1
        groupes = set(p.group_ids or [])
        for cohorte, ids in cohortes.items():
            if ids & groupes:
                charge[(cohorte, p.week)] = charge.get((cohorte, p.week), 0) + duree
    return charge


def completer_placements(
    *,
    sessions: list[SessionToPlace],
    placements: list[object],
    groups: list[Group],
    calendar: AcademicCalendar,
    semestre_par_defaut: str,
    config_dir: Path,
    teacher_availability: list[TeacherAvailability] | None,
    contexte_dur,
    creneaux_candidats,
    poser,
    plafond_cohorte: int = FI_WEEKLY_CAP_SLOTS,
) -> RapportCompletion:
    """Place gloutonnement les séances absentes de `placements`.

    Les trois derniers paramètres sont des fonctions fournies par l'appelant —
    l'API a déjà tout le contexte nécessaire (planning officiel, salles, duos),
    le dupliquer ici serait la meilleure façon de le laisser diverger :

    - `contexte_dur(session) -> (creneaux_bloques, semaines_autorisees)` ;
    - `creneaux_candidats(session) -> [(week, day, slot), ...]` déjà validés
      par les mêmes contrôles que le glisser-déposer ;
    - `poser(session, week, day, slot) -> bool` effectue le placement.

    **L'ordre de traitement compte** : les séances les plus contraintes
    d'abord. Placer une séance facile en premier peut consommer le seul
    créneau d'une séance difficile, alors que l'inverse n'arrive presque
    jamais.
    """
    rapport = RapportCompletion()
    sessions_by_id = {s.id: s for s in sessions}
    placees = {p.session_id for p in placements}

    # SAE non planifiées par le solveur (préfixe "WS", sauf
    # `solver_scheduled_sae`, ex. WSA501D) — jamais complétées ici. Bug réel
    # trouvé le 27/08/2026 (retour utilisateur, Kyllian Bresson : « les WS ne
    # sont pas à placer, ce sera les enseignants qui les placeront pendant
    # les périodes assignées ») : cette liste ne filtrait pas ces séances,
    # contrairement à `/placements/manquantes` (GET) et à l'audit — 221
    # séances SAE fictives se retrouvaient posées sur des dates qui n'ont
    # aucun rapport avec leur fenêtre officielle (`contraintes/
    # 09_dates_sae.json`), en plus de consommer inutilement de la capacité
    # hebdomadaire de cohorte que de VRAIES séances auraient pu utiliser.
    from cal_iut.ingestion.config_loader import load_solver_scheduled_sae

    scheduled_sae = load_solver_scheduled_sae(config_dir)

    def _est_sae_non_planifiee(s: SessionToPlace) -> bool:
        code = s.course_code.upper()
        return code.startswith("WS") and (code, s.semestre) not in scheduled_sae

    manquantes = [s for s in sessions if s.id not in placees and not _est_sae_non_planifiee(s)]
    if not manquantes:
        return rapport

    weeks = max((p.week for p in placements), default=-1) + 1
    if weeks <= 0:
        return rapport

    week_offset = semester_week_offset(calendar, semestre_par_defaut)
    bornes = _bornes_de_cours(config_dir, weeks)
    fenetres = _fenetres_de_dates(sessions, calendar, week_offset, weeks, config_dir)
    cohortes = build_student_cohorts(groups) if groups else {}
    charge = _charge_par_cohorte_semaine(placements, sessions_by_id, cohortes)
    occupation = _occupation_par_journee(placements, sessions_by_id, cohortes)

    def _cohortes_de(session: SessionToPlace) -> list[str]:
        groupes = set(session.group_ids or [])
        return [c for c, ids in cohortes.items() if ids & groupes]

    def _semaines_permises(session: SessionToPlace) -> set[int] | None:
        """None = aucune restriction connue au-delà de l'ordre pédagogique."""
        permises: set[int] | None = None
        borne = bornes.get((session.course_code, session.semestre))
        if borne is not None:
            lo, hi = borne
            permises = set(range(max(0, lo), min(weeks - 1, hi) + 1))
        fenetre = fenetres.get(session.id)
        if fenetre is not None:
            permises = fenetre if permises is None else (permises & fenetre)
        return permises

    # Ordre de TRAITEMENT, deux critères empilés.
    #
    # 1. TOPOLOGIQUE d'abord : les prédécesseurs avant leurs successeurs,
    #    PARMI LES SÉANCES MANQUANTES elles-mêmes. Sans ça, deux séances
    #    liées mais TOUTES LES DEUX manquantes peuvent être traitées dans le
    #    mauvais sens — la suivante, traitée en premier parce qu'elle avait
    #    moins de candidats à cet instant, n'a alors AUCUNE information sur sa
    #    propre précédente : les bornes (`_movable_bounds`, côté API) ne
    #    savent contraindre que contre des séances DÉJÀ posées. Trouvé le
    #    27/08/2026 : 11 des 13 violations d'ordre RÉELLEMENT introduites par
    #    la complétion (sur 36 observées au total, 23 préexistaient déjà côté
    #    solveur, hors de portée d'ici) concentrées sur UN SEUL cours SAE
    #    (WS107), toutes de cette forme.
    # 2. Les plus contraintes ensuite, À PROFONDEUR ÉGALE — mesuré par le
    #    nombre de créneaux candidats. Ce premier passage coûte un appel par
    #    séance manquante, mais il évite le gaspillage typique du glouton :
    #    la séance qui n'avait qu'un seul créneau se le fait prendre par une
    #    autre qui en avait trente.
    from cal_iut.solver.decomposed import _build_sequence_neighbors

    voisins_manquantes = _build_sequence_neighbors(sessions, groups) if groups else {}
    ids_manquantes = {s.id for s in manquantes}
    profondeur: dict[str, int] = {}

    def _profondeur(sid: str, chemin: frozenset[str] = frozenset()) -> int:
        if sid in profondeur:
            return profondeur[sid]
        if sid in chemin:
            return 0  # cycle improbable (jamais observé dans ces données) : ne pas boucler
        preds, _ = voisins_manquantes.get(sid, ([], []))
        preds_manquants = [p for p in preds if p in ids_manquantes]
        profondeur[sid] = (
            0 if not preds_manquants
            else 1 + max(_profondeur(p, chemin | {sid}) for p in preds_manquants)
        )
        return profondeur[sid]

    for s in manquantes:
        _profondeur(s.id)

    candidats_initiaux = {s.id: creneaux_candidats(s) for s in manquantes}
    manquantes.sort(
        key=lambda s: (profondeur[s.id], len(candidats_initiaux[s.id]), -(s.duration_slots or 1))
    )

    for session in manquantes:
        permises = _semaines_permises(session)
        mes_cohortes = _cohortes_de(session)
        duree = session.duration_slots or 1

        # Recalculés : le planning a changé à chaque placement précédent.
        candidats = creneaux_candidats(session)
        if not candidats:
            rapport.refusees.append(SeanceRefusee(
                session.id, session.course_code,
                "aucun créneau ne respecte toutes les règles ; une régénération de "
                "semaine ferait de la place, ou il faut assouplir une contrainte",
            ))
            continue

        admissibles: list[tuple[int, int, int]] = []
        motif_dernier_refus = ""
        for (w, d, sl) in candidats:
            if permises is not None and w not in permises:
                motif_dernier_refus = (
                    "les créneaux libres tombent hors de la période autorisée pour "
                    "ce cours (borne de début/fin ou fenêtre de dates)"
                )
                continue
            if sl + duree > SLOTS_PER_DAY:
                motif_dernier_refus = "le bloc ne tient pas dans la fin de journée"
                continue
            trop_charge = any(
                charge.get((c, w), 0) + duree > plafond_cohorte for c in mes_cohortes
            )
            if trop_charge:
                motif_dernier_refus = (
                    f"toutes les semaines possibles atteignent déjà le plafond de "
                    f"{plafond_cohorte} créneaux pour ce groupe"
                )
                continue
            admissibles.append((w, d, sl))

        # Prendre le PREMIER créneau libre (semaine la plus tôt, heure la plus
        # tôt) remplirait le semestre par le début en semant des trous : la
        # séance atterrit à 8h alors que la cohorte commence à 11h ce jour-là.
        # On choisit donc le moins coûteux pour l'étudiant — celui qui se colle
        # à ce qui existe déjà. C'est gratuit : les créneaux sont tous
        # également valides, seule leur qualité les distingue.
        choisi = (
            min(admissibles, key=lambda c: cout_creneau(c, duree, mes_cohortes, occupation))
            if admissibles
            else None
        )

        if choisi is None:
            rapport.refusees.append(SeanceRefusee(
                session.id, session.course_code,
                motif_dernier_refus or "aucun créneau admissible",
            ))
            continue

        w, d, sl = choisi
        if not poser(session, w, d, sl):
            rapport.refusees.append(SeanceRefusee(
                session.id, session.course_code,
                "le créneau a été refusé au moment de poser la séance",
            ))
            continue

        for c in mes_cohortes:
            charge[(c, w)] = charge.get((c, w), 0) + duree
            occupation.setdefault((c, w, d), set()).update(range(sl, sl + duree))
        jour = calendar.week_day_to_date(week_offset + w, d)
        rapport.placees.append(SeancePlacee(
            session.id, session.course_code, w, d, sl,
            jour.isoformat() if jour else "",
        ))

    return rapport
