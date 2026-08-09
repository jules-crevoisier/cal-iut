"""Calendrier académique IUT Troyes 2026-2027."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
import re

from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

# Racine du dépôt (src/cal_iut/calendar/academic.py -> parents[3] = racine).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CALENDAR_SOURCE_PATH = _REPO_ROOT / "contraintes" / "02_calendrier_iut.json"

# Fériés légaux français confirmés par l'utilisateur (1er mai = Fête du Travail,
# 8 mai = Victoire 1945) : absents de contraintes/02_calendrier_iut.json (source
# IUT), mais réels et à bloquer quoi qu'il arrive — ajoutés explicitement plutôt
# que de faire confiance aveuglément à une source qui semble incomplète sur ce
# point précis (cf. contraintes/08_alertes_qualite_donnees.json).
_CONFIRMED_EXTRA_HOLIDAYS = {date(2027, 5, 1), date(2027, 5, 8)}

DAY_FR = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
}

MONTH_FR = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}


# Lundi de l'ISO-week 35 2026 = "semaine 1" dans la numérotation interne du
# département (confirmé par l'utilisateur : "la semaine 1 est la semaine 35").
# La rentrée (ISO week 36, lundi 31 août 2026) est alors "semaine 2", et le
# vrai démarrage des cours (ISO week 37, lundi 7 septembre 2026) "semaine 3".
# Le numéro continue ensuite d'incrémenter de façon continue (comme dans le
# fichier "Plannings MMI... / Modele Sept-Jan"), sans reset au changement
# d'année civile.
DEPARTMENT_WEEK_ANCHOR = date(2026, 8, 24)


def department_week_number(monday: date) -> int:
    """Numéro de semaine "département" (semaine 1 = lundi ISO-week 35 2026)."""
    delta_days = (monday - DEPARTMENT_WEEK_ANCHOR).days
    return delta_days // 7 + 1


@dataclass
class AcademicCalendar:
    """Semaines enseignables + jours bloqués (vacances, fériés)."""

    year_label: str = "2026-2027"
    teaching_mondays: list[date] = field(default_factory=list)
    blocked_dates: set[date] = field(default_factory=set)
    holidays: set[date] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    @property
    def weeks(self) -> int:
        return len(self.teaching_mondays)

    def _label_for_monday(self, monday: date) -> str:
        friday = monday + timedelta(days=4)
        dept_n = department_week_number(monday)
        month_short = {
            1: "janv.", 2: "févr.", 3: "mars", 4: "avr.", 5: "mai", 6: "juin",
            7: "juil.", 8: "août", 9: "sept.", 10: "oct.", 11: "nov.", 12: "déc.",
        }
        if monday.month == friday.month:
            date_range = f"{monday.day}–{friday.day} {month_short[friday.month]} {friday.year}"
        else:
            date_range = (
                f"{monday.day} {month_short[monday.month]}–"
                f"{friday.day} {month_short[friday.month]} {friday.year}"
            )
        return f"Semaine {dept_n} ({date_range})"

    def department_week_label(self, week_index: int) -> str | None:
        """Ex. index 1 (2e semaine enseignable) -> "Semaine 3 (7–11 sept. 2026)"."""
        if week_index < 0 or week_index >= len(self.teaching_mondays):
            return None
        return self._label_for_monday(self.teaching_mondays[week_index])

    def full_week_range(self, week_offset: int, n_weeks: int) -> list[dict[str, object]]:
        """
        Séquence CONTINUE de semaines "département" entre la 1ère et la
        dernière semaine affichée, SANS sauter les semaines bloquées
        (vacances/fermeture) qui n'ont pas d'index solveur — par défaut
        `teaching_mondays` les exclut silencieusement, ce qui fait "sauter"
        l'affichage de semaine 9 à semaine 11 par ex. (rappel utilisateur :
        toutes les semaines doivent être visibles, même bloquées).

        Chaque entrée : `{monday, label, blocked, weekIndex}` — `weekIndex`
        (relatif à `week_offset`, index solveur) est `None` si `blocked`.
        """
        if week_offset < 0 or week_offset >= len(self.teaching_mondays) or n_weeks <= 0:
            return []
        end_index = min(week_offset + n_weeks - 1, len(self.teaching_mondays) - 1)
        start_monday = self.teaching_mondays[week_offset]
        end_monday = self.teaching_mondays[end_index]

        teaching_index_by_monday = {m: i for i, m in enumerate(self.teaching_mondays)}
        rows: list[dict[str, object]] = []
        cursor = start_monday
        while cursor <= end_monday:
            solver_index = teaching_index_by_monday.get(cursor)
            rows.append(
                {
                    "monday": cursor.isoformat(),
                    "label": self._label_for_monday(cursor),
                    "blocked": solver_index is None,
                    "weekIndex": (solver_index - week_offset) if solver_index is not None else None,
                }
            )
            cursor += timedelta(days=7)
        return rows

    def date_to_week_day(self, d: date) -> tuple[int, int] | None:
        """Retourne (week_index, day) si c'est un jour enseignable."""
        if d in self.blocked_dates or d in self.holidays:
            return None
        return self.date_to_week_day_any(d)

    def date_to_week_day_any(self, d: date) -> tuple[int, int] | None:
        """
        Comme `date_to_week_day`, mais SANS exclure les jours fériés/bloqués —
        retourne (week_index, day) tant que la semaine de `d` a au moins un
        jour enseignable (donc un index dans `teaching_mondays`). Utile pour
        localiser un jour férié précis dans la grille (affichage informatif
        uniquement) : `date_to_week_day` renverrait toujours `None` pour lui,
        par construction.
        """
        if d.weekday() > 4:
            return None
        monday = d - timedelta(days=d.weekday())
        try:
            week = self.teaching_mondays.index(monday)
        except ValueError:
            return None
        return week, d.weekday()

    def week_day_to_date(self, week: int, day: int) -> date | None:
        if week < 0 or week >= len(self.teaching_mondays) or day < 0 or day > 4:
            return None
        return self.teaching_mondays[week] + timedelta(days=day)

    def blocked_time_indices(self, weeks: int | None = None) -> set[int]:
        """Indices temporels interdits (jours fériés dans les semaines enseignables)."""
        n_weeks = weeks or self.weeks
        blocked: set[int] = set()
        slots_per_week = DAYS_PER_WEEK * SLOTS_PER_DAY
        for week in range(min(n_weeks, self.weeks)):
            for day in range(DAYS_PER_WEEK):
                d = self.week_day_to_date(week, day)
                if d is None or d in self.holidays or d in self.blocked_dates:
                    base = week * slots_per_week + day * SLOTS_PER_DAY
                    blocked.update(range(base, base + SLOTS_PER_DAY))
        return blocked


def parse_french_date(text: str, default_year: int | None = None) -> date | None:
    text = text.strip().lower()
    text = text.replace("é", "e").replace("è", "e").replace("ê", "e").replace("û", "u").replace("ô", "o")

    m = re.search(
        r"(lundi|mardi|mercredi|jeudi|vendredi)?\s*(\d{1,2})\s+"
        r"(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s*"
        r"(\d{4})?",
        text,
    )
    if not m:
        return None
    day = int(m.group(2))
    month = MONTH_FR[m.group(3)]
    year = int(m.group(4)) if m.group(4) else (default_year or 2026)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_iso_or_fr_date(value: object, default_year: int = 2026) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text or re.match(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.fromisoformat(text.replace("Z", "")).date()
        except ValueError:
            pass
    return parse_french_date(text, default_year)


def _fallback_holidays_and_pauses() -> tuple[set[date], list[tuple[date, date]]]:
    """Repli codé en dur si contraintes/02_calendrier_iut.json est introuvable."""
    holidays = {
        date(2026, 11, 11),
        date(2027, 3, 29),  # lundi de Pâques approx
        date(2027, 5, 6),
        date(2027, 5, 17),
        date(2027, 7, 14),
    }
    pause_ranges = [
        (date(2026, 10, 26), date(2026, 10, 30)),  # Toussaint
        (date(2026, 12, 21), date(2027, 1, 1)),  # Noël
        (date(2027, 2, 22), date(2027, 2, 26)),  # hiver
        (date(2027, 4, 19), date(2027, 4, 30)),  # printemps
        (date(2027, 5, 6), date(2027, 5, 7)),  # Ascension
    ]
    return holidays, pause_ranges


def _load_holidays_and_pauses_from_source(
    path: Path,
) -> tuple[set[date], list[tuple[date, date]]] | None:
    """Lit contraintes/02_calendrier_iut.json (jours_feries + vacances_et_pauses_pedagogiques)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    holidays = {
        date.fromisoformat(entry["date"])
        for entry in data.get("jours_feries", [])
        if entry.get("date")
    }
    pause_ranges = [
        (date.fromisoformat(entry["debut"]), date.fromisoformat(entry["fin"]))
        for entry in data.get("vacances_et_pauses_pedagogiques", [])
        if entry.get("debut") and entry.get("fin")
    ]
    return holidays, pause_ranges


def build_default_calendar_2026_2027() -> AcademicCalendar:
    """
    Calendrier IUT Troyes 2026-2027, construit à partir de
    `contraintes/02_calendrier_iut.json` (source officielle unique) ; repli codé
    en dur uniquement si ce fichier est absent/illisible (avec avertissement).
    """
    # S1 : lundi 31 août 2026 → vacances Toussaint / Noël exclues
    # S2 théorique lundi 4 janvier 2027, réellement visé lundi 1er février 2027
    # (marge confirmée par l'utilisateur, cf. semester_week_offset)
    s1_start = date(2026, 8, 31)
    year_end = date(2027, 6, 30)

    loaded = _load_holidays_and_pauses_from_source(_CALENDAR_SOURCE_PATH)
    if loaded is None:
        warnings.warn(
            f"{_CALENDAR_SOURCE_PATH} introuvable : repli sur le calendrier codé "
            "en dur (potentiellement obsolète).",
            stacklevel=2,
        )
        holidays, pause_ranges = _fallback_holidays_and_pauses()
        notes = ["Calendrier IUT Troyes 2026-2027 (repli codé en dur, source introuvable)"]
    else:
        holidays, pause_ranges = loaded
        notes = [f"Calendrier IUT Troyes 2026-2027 (source: {_CALENDAR_SOURCE_PATH.name})"]

    holidays |= _CONFIRMED_EXTRA_HOLIDAYS

    blocked: set[date] = set(holidays)
    for start, end in pause_ranges:
        d = start
        while d <= end:
            blocked.add(d)
            d += timedelta(days=1)

    teaching_mondays: list[date] = []
    # Align to Monday
    cursor = s1_start - timedelta(days=s1_start.weekday())
    while cursor <= year_end:
        week_days = [cursor + timedelta(days=i) for i in range(5)]
        if any(d not in blocked for d in week_days):
            teaching_mondays.append(cursor)
        cursor += timedelta(days=7)

    return AcademicCalendar(
        teaching_mondays=teaching_mondays,
        blocked_dates=blocked,
        holidays=holidays,
        notes=notes,
    )


def teaching_weeks_until(calendar: AcademicCalendar, start: date, target: date) -> int:
    """
    Nombre de semaines enseignables entre `start` (inclus) et `target` (exclu),
    calculé depuis le calendrier réel plutôt que codé en dur — utilisé pour que
    l'horizon S1 (weeks) reste calé sur le 1er février 2027 même si le
    calendrier (vacances/fériés) change une année future.
    """
    monday_start = start - timedelta(days=start.weekday())
    monday_target = target - timedelta(days=target.weekday())
    count = 0
    for monday in calendar.teaching_mondays:
        if monday < monday_start:
            continue
        if monday >= monday_target:
            break
        count += 1
    return count


# Cf. `semester_week_offset` : semestres impairs (S1/S3/S5) démarrent début
# septembre et visent le 1er février 2027 comme fin de marge (S2 réel), pas le
# 4 janvier théorique qui ne laisse aucune place.
_S1_S3_S5_START = date(2026, 8, 31)
_S1_S3_S5_TARGET_END = date(2027, 2, 1)
_FALLBACK_WEEKS_OTHER_SEMESTRES = 19  # hors périmètre de cette refonte (S2/S4/S6)


def default_horizon_weeks(calendar: AcademicCalendar, semestre: str | None) -> int:
    """
    Nombre de semaines par défaut pour l'horizon du solveur — source de vérité
    unique (remplace le `weeks=19` codé en dur à 4 endroits différents du repo).

    Pour S1/S3/S5 : calculé depuis le calendrier réel jusqu'au 1er février 2027
    (`teaching_weeks_until`), donc toujours exact même si le calendrier change.
    Pour les autres semestres : repli sur l'ancienne valeur fixe (19), hors
    périmètre de cette refonte centrée sur S1.
    """
    if semestre in {"S1", "S3", "S5"}:
        return teaching_weeks_until(calendar, _S1_S3_S5_START, _S1_S3_S5_TARGET_END)
    return _FALLBACK_WEEKS_OTHER_SEMESTRES


def semester_week_offset(calendar: AcademicCalendar, semestre: str) -> int:
    """Index de la première semaine du semestre dans le calendrier annuel.

    Le S2 est théoriquement au 4 janvier 2027 (maquette), mais avec 16
    semaines de cours S1 démarrant le 31 août, la semaine du 4 janvier
    (semaine-index 15) est déjà occupée par S1 lui-même : caler S2 pile au
    4 janvier ne laisse aucune marge. Confirmé par l'utilisateur : comme
    l'an dernier, on vise plutôt le lundi 1er février 2027 (semaine-index 19,
    ~4 semaines de marge), le S1 étant libre de dépasser 16 semaines
    (`--weeks`) puisque la fin de semestre n'est pas une contrainte dure.
    """
    if semestre in {"S1", "S3", "S5"}:
        # Semestre impair : début septembre
        target = date(2026, 8, 31)
    else:
        target = date(2027, 2, 1)
    monday = target - timedelta(days=target.weekday())
    for i, m in enumerate(calendar.teaching_mondays):
        if m >= monday:
            return i
    return 0


def current_relative_week(
    calendar: AcademicCalendar, semestre: str, today: date | None = None
) -> int | None:
    """
    Index de semaine (relatif à `semester_week_offset(calendar, semestre)`)
    correspondant à `today` (par défaut `date.today()`) — sert de base à
    `week_status` pour geler l'édition manuelle des semaines déjà
    passées/en cours (retour utilisateur : "si une semaine est en cours, on
    ne puisse pas la modifier").

    `date_to_week_day_any` (pas `date_to_week_day`) : un jour férié/bloqué
    doit quand même retomber dans SA semaine, pas renvoyer `None`. Si `today`
    lui-même n'a pas de semaine enseignable (week-end, vacances), on retombe
    sur le prochain lundi enseignable >= today — la semaine en cours reste
    "cette semaine-là" même un samedi.
    """
    today = today or date.today()
    week_offset = semester_week_offset(calendar, semestre)
    mapped = calendar.date_to_week_day_any(today)
    if mapped is not None:
        return mapped[0] - week_offset

    monday = today - timedelta(days=today.weekday())
    for i, m in enumerate(calendar.teaching_mondays):
        if m >= monday:
            return i - week_offset
    return None


def week_status(
    calendar: AcademicCalendar, semestre: str, week_index: int, today: date | None = None
) -> str:
    """
    "past" | "current" | "future" pour `week_index` (relatif au semestre) —
    seules les semaines "future" sont éditables/régénérables manuellement.
    Si `current_relative_week` ne peut pas être résolu (hors calendrier
    connu), on ne bloque rien plutôt que de deviner : "future".
    """
    current = current_relative_week(calendar, semestre, today)
    if current is None:
        return "future"
    if week_index < current:
        return "past"
    if week_index == current:
        return "current"
    return "future"
