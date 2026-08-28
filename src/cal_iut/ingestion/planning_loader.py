"""Lecture des fenêtres SAE et des événements fixes du calendrier officiel.

Sources canoniques (générées par `scripts/build_contraintes.py`) :

- `contraintes/09_dates_sae.json` — dates de chaque SAE, module par module,
  issues du fichier officiel « DATES SAE 2026_2027 ».
- `contraintes/10_dates_fixes.json` — événements fixes horodatés (rentrées,
  interventions), issus du fichier officiel « Dates MMI 26_27 - DATES OK ».

Ces deux fichiers remplacent l'ancien `04_planning_hebdomadaire_par_promo.json`
(dérivé de `Plannings_MMI_2026_2027.xlsx`), supprimé du dépôt le 10/08/2026 sur
décision utilisateur : les nouvelles sources sont nominatives par module et par
parcours, là où l'ancienne feuille obligeait à deviner à quel code de cours
correspondait un libellé « SAE103 » selon la piste (cf. l'historique de
`_SHEET_CODE_TEMPLATE`, tout ce mécanisme d'inférence a disparu avec elle).

Conséquence assumée du même arbitrage : les SAE de S2/S4/S6 n'ont aucune date
dans la nouvelle source, donc aucune sanctuarisation — ces semestres sont hors
périmètre pour 2026-2027 (cf. `pipeline.py::SEMESTRE_GROUPS`).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cal_iut.ingestion.config_loader import load_sae_teacher_phases

# Semestres réellement couverts par un fichier de dates SAE. Un module est
# retenu pour un run si son semestre est demandé — plus besoin de mapper un
# semestre vers des « feuilles » de tableur.
_SAE_PATH = "09_dates_sae.json"
_FIXED_EVENTS_PATH = "10_dates_fixes.json"


@dataclass
class SaeWindow:
    """Fenêtre SAE : projet / éval sur plusieurs jours complets."""

    label: str
    course_codes: list[str]
    dates: list[date] = field(default_factory=list)
    parcours: str | None = None
    # Restreint la sanctuarisation à ces groupes TD (libellés courts, ex.
    # ["AB"]) au lieu du parcours entier — cf. WS502D, dont le fichier source
    # date séparément chaque groupe. `None` = tout le parcours.
    group_labels: list[str] | None = None
    # Trigrammes des enseignants référents (lead + autres_enseignants) — un
    # enseignant qui encadre cette SAE est très peu disponible ces jours-là
    # pour un cours classique, MÊME SUR UN AUTRE PARCOURS que celui de la SAE
    # (retour utilisateur 11/08/2026). Cf. `sae_supervisor_dates_by_teacher`.
    teachers: list[str] = field(default_factory=list)


@dataclass
class FixedEvent:
    """Événement obligatoire à date et heure fixes (rentrée, intervention)."""

    day: date
    label: str
    slots: list[int] = field(default_factory=list)
    parcours_keys: list[str] = field(default_factory=list)
    room: str | None = None

    @property
    def display_label(self) -> str:
        return self.label


@dataclass
class PlanningBundle:
    sae_windows: list[SaeWindow] = field(default_factory=list)
    # Repères textuels affichés dans l'interface, par date.
    events: dict[date, list[str]] = field(default_factory=dict)
    fixed_events: list[FixedEvent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# Bornes horaires des 6 créneaux de 1h30 (en minutes depuis minuit) — mêmes
# horaires que `models/timetable.py::TimeSlot`, dupliquées ici en minutes pour
# le calcul d'intersection avec un horaire d'événement.
_SLOT_BOUNDS_MIN: tuple[tuple[int, int], ...] = (
    (8 * 60, 9 * 60 + 30),
    (9 * 60 + 30, 11 * 60),
    (11 * 60, 12 * 60 + 30),
    (14 * 60, 15 * 60 + 30),
    (15 * 60 + 30, 17 * 60),
    (17 * 60, 18 * 60 + 30),
)
_EVENT_TIME_RE = re.compile(r"(\d{1,2})\s*[h:]\s*(\d{0,2})")


def _slots_for_interval(start_min: int | None, end_min: int | None) -> list[int]:
    """Créneaux de 1h30 chevauchant [start, end). Un horaire seul (sans fin)
    est traité comme une durée d'une minute : seul le créneau qui le contient
    est retenu."""
    if start_min is None:
        return []
    lo = start_min
    hi = end_min if end_min is not None and end_min > start_min else start_min + 1
    return [idx for idx, (s, e) in enumerate(_SLOT_BOUNDS_MIN) if lo < e and hi > s]


def _slots_for_event_text(text: str) -> set[int]:
    """
    Extrait les horaires explicites d'un libellé (ex. "9h30 Echange IA",
    "17h / 18H30 Présentation…") et retourne les créneaux de 1h30 couverts.

    Ensemble vide si aucun horaire n'est trouvé : un événement sans horaire
    explicite n'est PAS bloqué (règle « donnée fraîche » : on ne devine pas un
    créneau non indiqué), seulement affiché comme repère.
    """
    minutes = [int(h) * 60 + (int(m) if m else 0) for h, m in _EVENT_TIME_RE.findall(text)]
    if not minutes:
        return set()
    return set(_slots_for_interval(min(minutes), max(minutes)))


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_sae_windows(data_root: Path, semestres: Iterable[str] | None = None) -> list[SaeWindow]:
    """Fenêtres SAE de `contraintes/09_dates_sae.json`, filtrées par semestre."""
    data = _load_json(data_root / "contraintes" / _SAE_PATH)
    if not data:
        return []

    wanted = {s.upper() for s in semestres} if semestres is not None else None
    windows: list[SaeWindow] = []
    for entry in data.get("sae", []):
        if wanted is not None and str(entry.get("semestre", "")).upper() not in wanted:
            continue
        dates = sorted({
            date.fromisoformat(d)
            for window in entry.get("fenetres", [])
            for d in window.get("dates", [])
        })
        if not dates:
            continue
        code = str(entry.get("code_matiere", "")).strip()
        if not code:
            continue
        teachers = sorted({
            str(t).strip()
            for t in ([entry.get("lead")] + list(entry.get("autres_enseignants") or []))
            if t
        })
        windows.append(
            SaeWindow(
                label=code,
                course_codes=[code],
                dates=dates,
                parcours=str(entry.get("parcours_source") or "") or None,
                group_labels=entry.get("groupes_td") or None,
                teachers=teachers,
            )
        )
    return windows


def load_fixed_events(data_root: Path) -> list[FixedEvent]:
    """Événements fixes de `contraintes/10_dates_fixes.json`."""
    data = _load_json(data_root / "contraintes" / _FIXED_EVENTS_PATH)
    if not data:
        return []

    events: list[FixedEvent] = []
    for entry in data.get("evenements", []):
        raw_date = entry.get("date")
        if not raw_date:
            continue
        slots = _slots_for_interval(entry.get("debut_minutes"), entry.get("fin_minutes"))
        horaire = ""
        if entry.get("debut"):
            horaire = entry["debut"] + (f"–{entry['fin']}" if entry.get("fin") else "")
        label = " ".join(part for part in (horaire, str(entry.get("motif") or "")) if part)
        events.append(
            FixedEvent(
                day=date.fromisoformat(str(raw_date)),
                label=label.strip(),
                slots=slots,
                parcours_keys=[str(p) for p in entry.get("parcours") or []],
                room=entry.get("salle"),
            )
        )
    return events


def load_mmi_planning(data_root: Path, semestre: str | None = None) -> PlanningBundle:
    """Fenêtres SAE d'un semestre + événements fixes de l'année."""
    return load_mmi_planning_for_semestres(data_root, [semestre] if semestre else [])


def load_mmi_planning_for_semestres(
    data_root: Path, semestres: Iterable[str]
) -> PlanningBundle:
    """
    Fusionne les fenêtres SAE de PLUSIEURS semestres — nécessaire pour un run
    multi-parcours (ex. S1+S3+S5 démarrant la même semaine calendaire, cf.
    `semester_week_offset` : offset commun aux 3).

    `semestres` vide = tous les semestres présents dans le fichier.
    """
    wanted = list(dict.fromkeys(s for s in semestres if s))
    windows = load_sae_windows(data_root, wanted or None)
    fixed = load_fixed_events(data_root)

    events: dict[date, list[str]] = {}
    for event in fixed:
        labels = events.setdefault(event.day, [])
        if event.label not in labels:
            labels.append(event.label)

    notes = [f"Source: {_SAE_PATH} ({len(windows)} SAE datées) + {_FIXED_EVENTS_PATH} ({len(fixed)} événements)"]
    if wanted:
        notes.append("Semestres: " + "+".join(wanted))
    return PlanningBundle(sae_windows=windows, events=events, fixed_events=fixed, notes=notes)


def sae_windows_as_week_days(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> dict[str, set[tuple[int, int]]]:
    """course_code → {(semaine relative, jour)} pour les fenêtres SAE."""
    result: dict[str, set[tuple[int, int]]] = {}
    for window in bundle.sae_windows:
        slots: set[tuple[int, int]] = set()
        for d in window.dates:
            mapped = calendar_date_to_week_day(d)
            if mapped is None:
                continue
            abs_week, day = mapped
            rel = abs_week - week_offset
            if 0 <= rel < weeks:
                slots.add((rel, day))
        if not slots:
            continue
        for code in window.course_codes:
            result.setdefault(code, set()).update(slots)
    return result


def sae_group_labels_by_course(bundle: PlanningBundle) -> dict[str, list[str]]:
    """
    course_code → libellés de groupes TD concernés, pour les SAE dont le
    fichier source ne date qu'une PARTIE de la promotion (ex. WS502D, groupe
    AB uniquement). Absent du dictionnaire = toute la promotion du parcours.
    """
    return {
        code: list(window.group_labels)
        for window in bundle.sae_windows
        if window.group_labels
        for code in window.course_codes
    }


def sae_supervisor_dates_by_teacher(
    bundle: PlanningBundle,
    config_dir: Path | None = None,
) -> dict[str, set[date]]:
    """
    Trigramme enseignant → dates où il encadre une SAE (lead ou co-enseignant,
    n'importe quel parcours confondu) — retour utilisateur du 11/08/2026 :
    « pendant une SAE les profs qui sont assignés dessus ne sont que très peu
    disponibles [...] il faut limiter leur nombre de cours voire pas en mettre
    en même temps ». Un enseignant peut référer plusieurs SAE sur plusieurs
    parcours à la fois (ex. Ariane Loizon : 5 SAE, S1+S3+S5, 48 jours cumulés) —
    toutes leurs dates sont unies ici, quel que soit le parcours de la SAE
    source : l'indisponibilité n'est pas propre à un seul parcours.

    `data/config/sae_teacher_phases.yaml` (modèle `SaeTeacherPhase`) permet de
    RESTREINDRE ces dates enseignant par enseignant quand la répartition réelle
    est connue — cas de WS501D, dont Ariane Loizon a fourni le découpage
    (FME du 19 au 22 octobre, SLO début novembre, FME+ALO à partir du 12
    novembre). Sans ça, ALO comptait 22 jours bloqués sur cette seule SAE,
    alors qu'elle n'y intervient qu'en fin de module — au détriment de la
    WRA505C, qu'elle doit justement commencer tôt.
    """
    phases = load_sae_teacher_phases(
        config_dir or Path(__file__).resolve().parents[3] / "data" / "config"
    )
    # (code_matiere) -> {trigramme -> [(debut, fin), ...]}. Le semestre n'est
    # pas discriminant ici : un code de SAE n'existe que dans un semestre.
    phases_by_course: dict[str, dict[str, list[tuple[date, date, set[date]]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for phase in phases:
        phases_by_course[phase.course_code][phase.teacher_code].append(
            (
                date.fromisoformat(phase.debut),
                date.fromisoformat(phase.fin),
                {date.fromisoformat(d) for d in phase.exclure},
            )
        )

    result: dict[str, set[date]] = defaultdict(set)
    for window in bundle.sae_windows:
        declared = {}
        for code in window.course_codes:
            declared.update(phases_by_course.get(code.upper(), {}))
        for teacher in window.teachers:
            # Enseignant sans phase déclarée : comportement historique, tous
            # les jours de la SAE le bloquent. On ne libère jamais quelqu'un
            # par omission — seule une déclaration explicite restreint.
            ranges = declared.get(teacher.upper())
            if ranges is None:
                result[teacher].update(window.dates)
                continue
            result[teacher].update(
                d
                for d in window.dates
                if any(start <= d <= end and d not in excluded for start, end, excluded in ranges)
            )
    return dict(result)


def planning_events_as_week_days(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> list[dict[str, object]]:
    """
    Repères SANS horaire explicite, convertis en (semaine relative, jour) pour
    un affichage JOUR ENTIER — purement informatif, ne bloque rien. Les
    événements AVEC horaire sont exclus d'ici : cf.
    `planning_events_as_week_day_slots`, qui les place au grain du créneau.
    """
    by_day: dict[tuple[int, int], list[str]] = {}
    for event in bundle.fixed_events:
        if event.slots:
            continue
        mapped = calendar_date_to_week_day(event.day)
        if mapped is None:
            continue
        rel = mapped[0] - week_offset
        if not (0 <= rel < weeks):
            continue
        labels = by_day.setdefault((rel, mapped[1]), [])
        if event.label not in labels:
            labels.append(event.label)
    return [
        {"w": w, "d": d, "labels": sorted(labels)}
        for (w, d), labels in sorted(by_day.items())
    ]


def planning_events_as_week_day_slots(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> list[dict[str, object]]:
    """
    Événements AVEC horaire explicite, un repère par CRÉNEAU précis couvert —
    pas « toute la journée ». Ce sont ces créneaux-là qui bloquent réellement
    un cours classique (cf. `planning_event_blocked_slots_by_parcours`, même
    calcul de créneaux) : l'affichage reste donc cohérent avec le blocage.
    """
    rows: list[dict[str, object]] = []
    for event in bundle.fixed_events:
        mapped = calendar_date_to_week_day(event.day)
        if mapped is None:
            continue
        rel = mapped[0] - week_offset
        if not (0 <= rel < weeks):
            continue
        for slot in event.slots:
            rows.append({
                "w": rel,
                "d": mapped[1],
                "s": slot,
                "label": event.label,
                "parcours": list(event.parcours_keys),
                "room": event.room,
            })
    return rows


# Clé « tous parcours » dans la sortie de
# `planning_event_blocked_slots_by_parcours` : un événement dont le fichier
# source ne précise aucun parcours bloque tout le monde.
ALL_PARCOURS = ""


def planning_event_blocked_slots_by_parcours(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> dict[str, set[tuple[int, int, int]]]:
    """
    Créneaux (semaine relative, jour, slot) à bloquer pour les cours
    classiques, PAR PARCOURS — le fichier officiel « Dates MMI » nomme le
    parcours concerné par chaque événement (colonne BUT), là où l'ancienne
    source ne le faisait pas et forçait un blocage global.

    Concrètement : la rentrée BUT1 du 2 septembre 9h-11h ne bloque plus les
    créneaux de BUT2/BUT3, qui ont leur propre rentrée le même jour à 14h et
    15h30.
    """
    blocked: dict[str, set[tuple[int, int, int]]] = {}
    for event in bundle.fixed_events:
        if not event.slots:
            continue
        mapped = calendar_date_to_week_day(event.day)
        if mapped is None:
            continue
        rel = mapped[0] - week_offset
        if not (0 <= rel < weeks):
            continue
        keys = event.parcours_keys or [ALL_PARCOURS]
        for key in keys:
            bucket = blocked.setdefault(key, set())
            bucket.update((rel, mapped[1], slot) for slot in event.slots)

    # Parcours FC (alternance) : aucun cours classique avant LEUR rentrée
    # exacte (date + heure) — retour utilisateur 11/08/2026 : « date de
    # rentrée des FC S3 : 14/09/2026, 9h30 [...] -> pas de cours avant »,
    # « les 2 parcours [FC S5] ont la rentrée à 14h et ils ont des cours le
    # matin, pas possible ». Jusqu'ici, seul le créneau EXACT de la rentrée
    # était bloqué (ci-dessus) — rien n'empêchait un cours classique le
    # matin du même jour, ni les jours/semaines précédents. Contrairement
    # aux parcours FI (cf. `add_s1_integration_week_lock`, généralisé à
    # TOUS les FI le même jour — un tampon d'une semaine complète, pas juste
    # l'instant de la rentrée), les parcours FC démarrent à des dates très
    # étalées (31/08 pour les BUT3-FC, 14/09 pour les BUT2-FC) : un blocage
    # semaine par semaine n'aurait aucun sens ici, il faut le grain exact de
    # la rentrée déclarée.
    for event in bundle.fixed_events:
        if "rentr" not in event.label.lower():
            continue
        if not any("FC" in key for key in event.parcours_keys):
            continue
        mapped = calendar_date_to_week_day(event.day)
        if mapped is None:
            continue
        event_abs_week, event_day = mapped
        event_first_slot = min(event.slots) if event.slots else 0
        for key in event.parcours_keys:
            if "FC" not in key:
                continue
            bucket = blocked.setdefault(key, set())
            for rel in range(weeks):
                abs_week = week_offset + rel
                for day in range(5):
                    for slot in range(6):
                        if (abs_week, day, slot) < (event_abs_week, event_day, event_first_slot):
                            bucket.add((rel, day, slot))
    return blocked


def fc_rentree_first_week_by_parcours(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
) -> dict[str, int]:
    """
    Semaine RELATIVE (>= 0) de la rentrée de chaque parcours FC — borne basse
    à passer à l'étage 2 (`assign_weeks`).

    Bug réel trouvé le 11/08/2026 en vérifiant le run complet suivant la
    généralisation ci-dessus : `planning_event_blocked_slots_by_parcours`
    (le blocage "avant rentrée exacte") n'est lu qu'à l'étage 3
    (`solve_week_detail`, via `planning_event_blocked_local`) — l'étage 2
    (`assign_weeks`) l'ignore totalement et continue d'assigner des séances
    FC à des semaines ENTIÈREMENT antérieures à leur rentrée (ex.
    BUT2-CREACOM-FC, rentrée le 14/09/2026 -> toute la semaine 0, 31/08-04/09,
    lui est interdite). L'étage 3 découvre alors, TROP TARD, qu'aucun des 30
    créneaux de cette semaine n'est disponible pour ce parcours -> INFEASIBLE
    prouvé en 0s (confirmé par diagnostic ciblé : semaine 0 seule, 3 seeds
    différentes, toutes INFEASIBLE instantanément — signature d'une semaine
    structurellement fermée, pas d'un manque de recherche). Même classe de
    bug que `_teacher_available_slots_by_week`/`_physical_slots_by_week`
    (cf. leurs docstrings) : toute contrainte dure connue de l'étage 3 doit
    aussi border l'étage 2, sous peine de lui laisser assigner l'impossible.
    Cf. docs/DATA.md §58.
    """
    first_week: dict[str, int] = {}
    for event in bundle.fixed_events:
        if "rentr" not in event.label.lower():
            continue
        if not any("FC" in key for key in event.parcours_keys):
            continue
        mapped = calendar_date_to_week_day(event.day)
        if mapped is None:
            continue
        event_abs_week, _ = mapped
        rel = event_abs_week - week_offset
        for key in event.parcours_keys:
            if "FC" not in key:
                continue
            current = first_week.get(key)
            if current is None or rel > current:
                first_week[key] = rel
    return first_week
