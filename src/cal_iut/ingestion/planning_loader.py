"""Lecture du planning pédagogique (fenêtres SAE multi-jours).

Source canonique : `contraintes/04_planning_hebdomadaire_par_promo.json`, déjà
structuré semaine par semaine par promotion — l'ancien xlsx dont ce JSON est
dérivé ("Plannings_MMI_2026_2027.xlsx") a disparu du dépôt, on ne le cherche
plus.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# Convention de code réel des séances SAE par feuille source — vérifiée
# empiriquement sur `data/generated/sessions.json`, PAS déduite d'un motif
# générique unique appliqué au texte "SAEnnn" (les 3 pistes utilisent des
# préfixes/suffixes différents, et CREACOM-FC change même de suffixe entre
# BUT2 — "M", héritage "MMI" — et BUT3 — "C" — alors que la feuille SAE
# elle-même écrit systématiquement "C" aux deux niveaux : le suffixe du
# TOKEN source n'est donc jamais fiable, seule la feuille d'origine l'est).
#
# Bug réel corrigé (06/08/2026, retour utilisateur : "il y a les semaines de
# SAE... il faut faire attention à cela pour les alternants") : l'ancienne
# heuristique générique (cf. historique `sae_token_to_course_codes`)
# produisait "WSA{num}{suffixe}" pour tout numéro ne commençant pas par
# 1/2, et lisait TOUJOURS la feuille FI quel que soit le parcours. Deux
# conséquences réelles, vérifiées sur le run déjà résolu (S1+S3+S5) :
# (a) ça ne matchait JAMAIS les vrais codes FI (`WS{num}D`, sans "A") ->
# ZÉRO sanctuarisation SAE pour BUT2/3-DEV-FI ; (b) ça matchait PAR
# COÏNCIDENCE les codes FC réels (`WSA{num}D/M/C`) mais avec les dates de
# la SAE de la piste FI, pas celles de la piste FC — ex. S5 : FI SAE501D
# tombe le 19/10-02/11/2026, alors que la vraie prochaine SAE des FC
# (SAE601D/601C) est le 29/03/2027, dans une feuille FC dédiée jamais lue
# jusqu'ici. Cf. docs/DATA.md §32.
_SHEET_CODE_TEMPLATE: dict[str, str] = {
    "S1S2": "WS{num}",
    "S3S4-FI": "WS{num}D",
    "S5S6-FI": "WS{num}D",
    "S3S4DEV-FC": "WSA{num}D",
    "S5S6DEV-FC": "WSA{num}D",
    "S3S4CREACOM-FC": "WSA{num}M",
    "S5S6CREACOM-FC": "WSA{num}C",
}

# Feuilles à fusionner par semestre : toutes les pistes concurrentes de ce
# semestre, chacune avec sa propre convention de code ET ses propres dates
# réelles de SAE (cf. `_SHEET_CODE_TEMPLATE`) — une SAE se lit sur LA
# feuille de sa piste, jamais sur celle d'une autre piste. La feuille FI est
# toujours en premier (cf. `load_mmi_planning` : `events`/`blocked_labels`
# restent sourcés uniquement depuis elle, portée volontairement limitée à
# la sanctuarisation SAE pour ce correctif).
_SHEETS_BY_SEMESTRE: dict[str, list[str]] = {
    "S1": ["S1S2"],
    "S2": ["S1S2"],
    "S3": ["S3S4-FI", "S3S4DEV-FC", "S3S4CREACOM-FC"],
    "S4": ["S3S4-FI", "S3S4DEV-FC", "S3S4CREACOM-FC"],
    "S5": ["S5S6-FI", "S5S6DEV-FC", "S5S6CREACOM-FC"],
    "S6": ["S5S6-FI", "S5S6DEV-FC", "S5S6CREACOM-FC"],
}

_DAY_OFFSET = {"Lundi": 0, "Mardi": 1, "Mercredi": 2, "Jeudi": 3, "Vendredi": 4}


@dataclass
class SaeWindow:
    """Fenêtre SAE : projet / éval sur plusieurs jours complets."""

    label: str
    course_codes: list[str]
    dates: list[date] = field(default_factory=list)


@dataclass
class PlanningBundle:
    sae_windows: list[SaeWindow] = field(default_factory=list)
    blocked_labels: dict[date, str] = field(default_factory=dict)
    # Repères textuels du planning officiel qui ne sont ni une SAE ni un jour
    # bloqué (vacances/pause/entreprise) — ex. "Rentrée 09h00", "Intégration",
    # "VSS 10h00-12h0", "Rattrapages", "Entretiens ParcourSup" : événements
    # ponctuels/obligatoires réels, affichés tels quels dans l'interface
    # (retour utilisateur : "tu a aussi des séance obligatoire met les").
    events: dict[date, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _normalize_sae_token(text: str) -> str | None:
    """
    Extrait le code numérique d'une cellule marquant une SAE, sous les DEUX
    notations réellement présentes dans le planning officiel :

    1. `"SAE105/106"` — notation littérale, y compris les tokens composés
       (bug corrigé : l'ancienne regex s'arrêtait au premier groupe de
       chiffres et tronquait "105/106" en "105", perdant WS106).
    2. `"WSA501C"` / `"WSA502D"` / `"WSA666"` — le CODE DE COURS brut, sans
       le mot "SAE". Bug réel corrigé (07/08/2026, retour utilisateur : "les
       3e années n'ont pas de SAE... il faut bien que partout il y ait les
       SAE pour tous les groupes") : les feuilles d'alternants
       (`S3S4CREACOM-FC`, `S5S6DEV-FC`, `S5S6CREACOM-FC`) n'utilisent QUE
       cette 2e notation, jamais "SAEnnn" — leurs journées SAE n'étaient
       donc jamais détectées et finissaient classées en simples "événements"
       informatifs, sans aucune sanctuarisation. Cf. docs/DATA.md §40.

    Dans les deux cas seul le NUMÉRO est retenu ; le suffixe éventuel est
    ignoré au profit de la convention de la feuille source (cf.
    `sae_token_to_course_codes` / `_SHEET_CODE_TEMPLATE`) — la feuille
    CREACOM-FC écrit par exemple "WSA401C" alors que le vrai code du module
    au niveau BUT2 est "WSA401M".
    """
    cleaned = re.sub(r"\s+", "", text.upper())

    m = re.search(r"SAE([0-9]{2,3}[A-Z]?(?:/[0-9]{2,3}[A-Z]?)*)", cleaned)
    if m:
        return m.group(1)

    # Code de cours SAE brut : WS/WSA + 2-3 chiffres (+ suffixe de piste).
    # `fullmatch` volontaire : évite d'attraper "WS5PJ"/"WSA5PRJ" (projet
    # enseignants, pas une fenêtre SAE) ou une cellule contenant du texte
    # libre autour du code.
    m = re.fullmatch(r"WSA?([0-9]{2,3})[A-Z]?", cleaned)
    if m:
        return m.group(1)

    return None


def sae_token_to_course_codes(token: str, code_template: str = "WS{num}") -> list[str]:
    """
    Mappe un token SAE normalisé (ex. "103", "301D", "105/106") vers son
    code de cours réel, selon la convention de la feuille source
    (`code_template`, cf. `_SHEET_CODE_TEMPLATE`). Le suffixe éventuel du
    token lui-même (ex. "D" dans "301D") est ignoré — vérifié peu fiable
    (la feuille CREACOM-FC écrit "C" au niveau BUT2 alors que le vrai code
    utilise "M") : seule la convention de LA feuille d'origine fait foi.
    """
    token = token.upper().replace(" ", "")
    codes: list[str] = []

    if "/" in token:
        for part in token.split("/"):
            codes.extend(sae_token_to_course_codes(part, code_template))
        return codes

    m = re.fullmatch(r"(\d{2,3})[A-Z]?", token)
    if not m:
        return codes

    codes.append(code_template.format(num=m.group(1)))
    return codes


# Bruit structurel de la feuille (en-tête de section répété sur ~20
# semaines, pas un événement) — seul filtre appliqué, tout le reste du
# texte "autre" est conservé tel quel (règle "donnée fraîche" : ne pas
# deviner ce qui est ou non un vrai événement au-delà de ce bruit connu).
_NOISE_LABELS = {"semestre 1", "semestre 2"}


def _parse_planning_weeks(weeks: list[dict[str, object]], code_template: str) -> PlanningBundle:
    day_tokens: dict[date, set[str]] = {}
    blocked: dict[date, str] = {}
    events: dict[date, list[str]] = {}

    for week in weeks:
        lundi_raw = week.get("lundi_date")
        if not lundi_raw:
            continue
        monday = date.fromisoformat(str(lundi_raw))
        jours = week.get("jours") or {}

        for day_name, labels in jours.items():
            offset = _DAY_OFFSET.get(str(day_name))
            if offset is None:
                continue
            cell_date = monday + timedelta(days=offset)

            for raw in labels or []:
                text = str(raw).strip()
                if not text:
                    continue
                low = text.lower()
                if "pause" in low or "entreprise" in low or "vacance" in low:
                    blocked[cell_date] = text
                    continue
                token = _normalize_sae_token(text)
                if token:
                    day_tokens.setdefault(cell_date, set()).add(token)
                    continue
                if low in _NOISE_LABELS:
                    continue
                events.setdefault(cell_date, []).append(text)

    by_token: dict[str, list[date]] = {}
    for d, tokens in sorted(day_tokens.items()):
        for token in tokens:
            by_token.setdefault(token, []).append(d)

    windows = [
        SaeWindow(
            label=f"SAE{token}",
            course_codes=sae_token_to_course_codes(token, code_template),
            dates=sorted(set(dates)),
        )
        for token, dates in sorted(by_token.items())
    ]

    return PlanningBundle(sae_windows=windows, blocked_labels=blocked, events=events)


def load_mmi_planning(data_root: Path, semestre: str | None = None) -> PlanningBundle:
    """
    Charge et fusionne TOUTES les feuilles de piste concurrentes du
    semestre (FI + DEV-FC + CREACOM-FC quand elles existent, cf.
    `_SHEETS_BY_SEMESTRE`) — chacune avec sa propre convention de code SAE
    et ses propres dates réelles (cf. `_SHEET_CODE_TEMPLATE`). `events`/
    `blocked_labels` restent sourcés uniquement depuis la première feuille
    du groupe (la FI) : portée volontairement limitée à la sanctuarisation
    SAE pour ce correctif (cf. docs/DATA.md §32).
    """
    path = data_root / "contraintes" / "04_planning_hebdomadaire_par_promo.json"
    if not path.exists():
        return PlanningBundle(notes=[f"{path} introuvable"])

    data = json.loads(path.read_text(encoding="utf-8"))
    feuilles = data.get("feuilles") or {}
    sheet_names = _SHEETS_BY_SEMESTRE.get(semestre or "S1", ["S1S2"])

    merged = PlanningBundle()
    for i, sheet in enumerate(sheet_names):
        weeks = feuilles.get(sheet)
        if weeks is None:
            merged.notes.append(f"Feuille absente: {sheet}")
            continue
        bundle = _parse_planning_weeks(weeks, _SHEET_CODE_TEMPLATE[sheet])
        merged.sae_windows.extend(bundle.sae_windows)
        if i == 0:
            merged.blocked_labels = bundle.blocked_labels
            merged.events = bundle.events

    merged.notes.append(f"Source: {path.name} / feuilles.{'+'.join(sheet_names)}")
    return merged


def load_mmi_planning_for_semestres(data_root: Path, semestres: Iterable[str]) -> PlanningBundle:
    """
    Fusionne `load_mmi_planning` sur PLUSIEURS semestres réels à la fois —
    nécessaire pour un run multi-parcours (ex. Groupe A, S1+S3+S5 démarrant
    la même semaine calendaire, cf. `semester_week_offset` : offset commun
    aux 3) : `load_mmi_planning(data_root, "S1")` seul ne charge QUE la
    feuille S1S2, jamais S3S4-*/S5S6-*.

    Bug réel corrigé (07/08/2026, retour utilisateur : "il n'y avait pas
    des séances obligatoires pour 2e/3e année à propos de leur rentrée ?
    vérifie") : `TimetableSolver.solve_decomposed` appelait
    `load_mmi_planning(root, semestre)` avec le seul semestre ANCRE du
    groupe (ex. "S1" pour --semestre-group odd), donc BUT2 (S3) et BUT3
    (S5) n'avaient JAMAIS leurs propres fenêtres SAE ni leurs propres
    événements (rentrées, etc.) chargés — zéro sanctuarisation SAE et zéro
    blocage d'événement horodaté pour ces deux années, malgré le correctif
    §32 (qui fusionne bien les feuilles PAR semestre, mais n'était jamais
    appelé pour S3/S5 dans un run multi-parcours réel). Confirmé
    empiriquement : `load_mmi_planning(root, "S1")` seul ne retourne QUE
    des codes WSxxx de BUT1 (aucun WS3xx/WS5xx). Cf. docs/DATA.md §37.
    """
    merged = PlanningBundle()
    seen_notes: list[str] = []
    for semestre in dict.fromkeys(semestres):  # dédoublonne en gardant l'ordre
        bundle = load_mmi_planning(data_root, semestre)
        merged.sae_windows.extend(bundle.sae_windows)
        for d, label in bundle.blocked_labels.items():
            merged.blocked_labels.setdefault(d, label)
        for d, labels in bundle.events.items():
            existing = merged.events.setdefault(d, [])
            for label in labels:
                if label not in existing:
                    existing.append(label)
        seen_notes.extend(bundle.notes)
    merged.notes = seen_notes
    return merged


def sae_windows_as_week_days(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> dict[str, set[tuple[int, int]]]:
    """course_code → {(rel_week, day)} pour fenêtres SAE."""
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


def planning_events_as_week_days(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> list[dict[str, object]]:
    """
    Repères/événements SANS horaire explicite (ex. "Intégration",
    "Rattrapages", "Clés de Troyes"), convertis en (semaine relative, jour)
    pour affichage JOUR ENTIER dans la grille — purement informatif, ne
    bloque rien côté solveur NI côté affichage (retour utilisateur : "pour
    les séances Clé de Troyes ce ne sont pas des séances bloquées, c'est
    juste indicatif" — une case sous ce repère reste déposable en
    glisser-déposer). Les événements AVEC horaire explicite (ex. "9h30
    Echange IA") sont exclus d'ici : cf. `planning_events_as_week_day_slots`,
    qui les place au grain du créneau précis (pas "toute la journée").
    """
    rows: list[dict[str, object]] = []
    for d, labels in sorted(bundle.events.items()):
        mapped = calendar_date_to_week_day(d)
        if mapped is None:
            continue
        abs_week, day = mapped
        rel = abs_week - week_offset
        if 0 <= rel < weeks:
            untimed = sorted({label for label in labels if not _slots_for_event_text(label)})
            if untimed:
                rows.append({"w": rel, "d": day, "labels": untimed})
    return rows


def planning_events_as_week_day_slots(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> list[dict[str, object]]:
    """
    Événements AVEC horaire explicite (ex. "9h30 Echange IA", "17h / 18H30
    Présentation des services aux nouveaux étudiants"), un repère par
    CRÉNEAU précis qu'ils recouvrent — pas "toute la journée" (bug affichage
    corrigé le 06/08/2026 : le même libellé apparaissait auparavant répété
    dans CHAQUE case vide du jour, alors que `planning_event_blocked_slots`
    — utilisée côté solveur — sait déjà précisément quel(s) créneau(x) sont
    concernés). Ce sont ces créneaux-là qui bloquent réellement un cours
    classique (cf. `planning_event_blocked_slots`, même extraction
    d'horaire) : l'affichage doit donc rester cohérent avec le blocage.
    """
    rows: list[dict[str, object]] = []
    for d, labels in sorted(bundle.events.items()):
        mapped = calendar_date_to_week_day(d)
        if mapped is None:
            continue
        abs_week, day = mapped
        rel = abs_week - week_offset
        if not (0 <= rel < weeks):
            continue
        for label in labels:
            for slot in sorted(_slots_for_event_text(label)):
                rows.append({"w": rel, "d": day, "s": slot, "label": label})
    return rows


# Bornes horaires des 6 créneaux de 1h30 (en minutes depuis minuit) — mêmes
# horaires que `models/timetable.py::TimeSlot`, dupliquées ici en minutes
# pour le calcul d'intersection avec un horaire extrait d'un libellé texte
# (cf. `_slots_for_event_text`).
_SLOT_BOUNDS_MIN: tuple[tuple[int, int], ...] = (
    (8 * 60, 9 * 60 + 30),
    (9 * 60 + 30, 11 * 60),
    (11 * 60, 12 * 60 + 30),
    (14 * 60, 15 * 60 + 30),
    (15 * 60 + 30, 17 * 60),
    (17 * 60, 18 * 60 + 30),
)
_EVENT_TIME_RE = re.compile(r"(\d{1,2})\s*[h:]\s*(\d{0,2})")


def _slots_for_event_text(text: str) -> set[int]:
    """
    Extrait les horaires explicites d'un libellé d'événement (ex. "9h30
    Echange IA" -> {9h30}, "17h / 18H30 Présentation..." -> {17h, 18h30},
    "VSS 10h00-12h0" -> {10h00, 12h00}) et retourne l'ensemble des créneaux
    de 1h30 qui chevauchent l'intervalle [min horaire, max horaire] trouvé
    (un seul horaire = un point, traité comme une durée d'1 minute pour que
    le chevauchement retienne bien le créneau qui le contient).

    Retourne un ensemble vide si aucun horaire n'est trouvé dans le texte —
    un événement sans horaire explicite (ex. "Rattrapages", "Clés de Troyes")
    n'est PAS bloqué (règle "donnée fraîche" : on ne devine pas un créneau
    non indiqué), seulement affiché comme repère informatif.
    """
    minutes = [int(h) * 60 + (int(m) if m else 0) for h, m in _EVENT_TIME_RE.findall(text)]
    if not minutes:
        return set()
    lo, hi = min(minutes), max(minutes)
    if lo == hi:
        hi = lo + 1
    return {idx for idx, (start, end) in enumerate(_SLOT_BOUNDS_MIN) if lo < end and hi > start}


def planning_event_blocked_slots(
    bundle: PlanningBundle,
    calendar_date_to_week_day,
    week_offset: int,
    weeks: int,
) -> set[tuple[int, int, int]]:
    """
    Créneaux (semaine relative, jour, slot) à bloquer pour les cours
    classiques, déduits des horaires explicites présents dans
    `PlanningBundle.events` — retour utilisateur : les événements affichés
    (ex. "9h30 Echange IA", "17h / 18H30 Présentation des services") n'étaient
    qu'informatifs, sans empêcher le solveur d'y placer un cours classique en
    même temps. Contrairement à `sae_blocked_days_by_parcours` (jour entier,
    par parcours), ce blocage est au grain du créneau, global (pas de notion
    de parcours dans le planning brut).
    """
    blocked: set[tuple[int, int, int]] = set()
    for d, labels in bundle.events.items():
        mapped = calendar_date_to_week_day(d)
        if mapped is None:
            continue
        abs_week, day = mapped
        rel = abs_week - week_offset
        if not (0 <= rel < weeks):
            continue
        for label in labels:
            for slot in _slots_for_event_text(label):
                blocked.add((rel, day, slot))
    return blocked
