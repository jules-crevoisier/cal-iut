"""Parsers des fichiers de contraintes (enseignants, étudiants FC, IUT).

Source canonique : `contraintes/03_calendrier_alternance_officiel.json` et
`contraintes/05_enseignants_contraintes.json` (JSON propres, déjà pré-tokenisés
pour les indisponibilités enseignants). Les anciens fichiers CSV/XLSX bruts dont
ces JSON sont dérivés ont disparu du dépôt — on ne les cherche plus.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from cal_iut.calendar.academic import (
    DAY_FR,
    AcademicCalendar,
    parse_french_date,
    parse_iso_or_fr_date,
)
from cal_iut.ingestion.planning_loader import (
    _EVENT_TIME_RE,
    _SLOT_BOUNDS_MIN,
    _slots_for_event_text,
)
from cal_iut.models.entities import TeacherAvailability, TeacherWeekParityRule
from cal_iut.models.timetable import SLOTS_PER_DAY

MORNING_SLOTS = [0, 1, 2]
AFTERNOON_SLOTS = [3, 4, 5]
ALL_SLOTS = list(range(SLOTS_PER_DAY))

# contraintes/03_calendrier_alternance_officiel.json : chaque bloc top-level
# décrit un groupe d'alternants avec ses `parcours_concernes` libellés
# "S{3..6}-{DEV|CREACOM}-FC" ; ces libellés se traduisent en codes `parcours`
# réels (BUT2/BUT3-{DEV|CREACOM}-FC, indépendants du semestre) via ce préfixe.
_ALTERNANCE_BLOCK_BUT_PREFIX = {
    "BUT2_FC_S3_S4": "BUT2",
    "BUT3_FC_S5_S6": "BUT3",
}


@dataclass
class StudentPresence:
    """Jours de présence à l'IUT pour les parcours en alternance (FC)."""

    parcours_keys: list[str]
    presence_dates: set[date] = field(default_factory=set)
    label: str = ""


@dataclass
class ConstraintsBundle:
    calendar: AcademicCalendar
    teachers: list[TeacherAvailability]
    student_presences: list[StudentPresence]
    raw_notes: dict[str, str] = field(default_factory=dict)


class ConstraintsDataError(RuntimeError):
    """Levée quand une source de contraintes attendue est absente/vide.

    Volontairement bruyante : la régression qui a motivé cette réécriture
    (contraintes/03 et 05 jamais chargées, en silence, sans que rien ne le
    signale) est exactement le genre de bug que cette exception empêche de
    reproduire.
    """


def _parse_period_fragment(fragment: str) -> list[tuple[int, int]]:
    """Parseur généraliste de texte libre (ex. "vendredi après-midi").

    Conservé pour un éventuel réimport de texte brut (CSV) futur ; le flux
    principal (JSON pré-tokenisé) n'en a plus besoin, cf. `_slots_for_moment`.
    """
    text = fragment.strip().lower()
    text = (
        text.replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("û", "u")
        .replace("ô", "o")
        .replace("à", "a")
    )
    if not text:
        return []

    day = None
    for name, idx in DAY_FR.items():
        if name in text:
            day = idx
            break
    if day is None:
        return []

    if "15h30" in text or "15:30" in text:
        if "18h" in text:
            return [(day, s) for s in (4, 5)]
        return [(day, 4)]
    if "apres 17" in text:
        return [(day, 5)]
    if "8h00" in text and "9h30" in text:
        return [(day, 0)]
    if "toute la journee" in text or "journee" in text:
        return [(day, s) for s in ALL_SLOTS]
    if "apres-midi" in text or "apres midi" in text:
        return [(day, s) for s in AFTERNOON_SLOTS]
    if "matin" in text:
        return [(day, s) for s in MORNING_SLOTS]
    return [(day, s) for s in ALL_SLOTS]


def _slots_for_open_ended_time(text: str) -> list[int]:
    """
    "après/à partir de HHhMM" (ex. "les jeudis après 17h00", "jeudi à partir
    de 14h00") : borne OUVERTE, pas un point isolé — tout créneau qui déborde
    au-delà de l'heure citée est concerné (pas seulement celui qui la
    contient), donc "créneau.fin > heure_citée", contrairement à
    `_slots_for_event_text` (pensé pour des plages BORNÉES). Ne s'applique que
    si une seule heure est trouvée — sinon laisse `_slots_for_event_text` gérer
    le cas borné classique.

    Sert aussi bien à une INDISPONIBILITÉ ouverte ("indisponible après 17h" ->
    créneaux interdits) qu'à une DISPONIBILITÉ ouverte ("disponible à partir de
    14h" -> créneaux autorisés) : la fonction ne rend que l'ensemble de
    créneaux, l'appelant décide du sens.
    """
    text_norm = text.lower().replace("è", "e").replace("é", "e").replace("à", "a")
    if "apres" not in text_norm and "a partir de" not in text_norm:
        return []
    times = _EVENT_TIME_RE.findall(text)
    if len(times) != 1:
        return []
    cutoff = int(times[0][0]) * 60 + (int(times[0][1]) if times[0][1] else 0)
    return [idx for idx, (start, end) in enumerate(_SLOT_BOUNDS_MIN) if end > cutoff]


def _parse_date_token(raw: str) -> list[date]:
    """Date isolée ou plage "du X au Y" (ex. "du lundi 2 au vendredi 6 novembre 2026")."""
    range_m = re.search(r"du\s+(.+?)\s+au\s+(.+)", raw, flags=re.IGNORECASE)
    if range_m:
        start_frag, end_frag = range_m.group(1), range_m.group(2)
        start = parse_french_date(start_frag, 2026) or parse_french_date(start_frag, 2027)
        end = parse_french_date(end_frag, 2026) or parse_french_date(end_frag, 2027)
        # Convention française : le mois n'est souvent précisé qu'une fois,
        # sur la borne de fin ("du lundi 2 au vendredi 6 novembre 2026") — si
        # la borne de début n'a pas de mois propre, on lui emprunte celui de
        # la borne de fin plutôt que d'abandonner toute la plage.
        if start is None and end is not None:
            month_year_m = re.search(
                r"(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\s*(\d{4})?",
                end_frag, flags=re.IGNORECASE,
            )
            if month_year_m:
                start = parse_french_date(f"{start_frag} {month_year_m.group(0)}", end.year)
        if start and end and start <= end:
            dates: list[date] = []
            d = start
            while d <= end:
                dates.append(d)
                d += timedelta(days=1)
            return dates
        return []

    d = parse_french_date(raw, 2026) or parse_french_date(raw, 2027)
    return [d] if d else []


def parse_teacher_unavailability(text: str) -> tuple[list[tuple[int, int]], list[date]]:
    """Parseur généraliste de texte libre multi-fragments (ex. CSV brut).

    Conservé (testé, réutilisable pour un futur réimport de texte brut) mais
    non appelé par le flux principal, qui consomme directement les tokens
    structurés de `contraintes/05_enseignants_contraintes.json`.
    """
    if not text or not text.strip():
        return [], []

    forbidden_slots: list[tuple[int, int]] = []
    forbidden_dates: list[date] = []
    parts = re.split(r"\s*-\s*", text.replace("\n", " - "))

    for part in parts:
        part = part.strip()
        if not part:
            continue

        dates = _parse_date_token(part)
        if dates:
            forbidden_dates.extend(dates)
            continue

        forbidden_slots.extend(_parse_period_fragment(part))

    return sorted(set(forbidden_slots)), sorted(set(forbidden_dates))


def _slots_for_moment(moment: str) -> list[int]:
    if moment == "matin":
        return MORNING_SLOTS
    if moment == "apres_midi":
        return AFTERNOON_SLOTS
    if moment == "toute_la_journee":
        return ALL_SLOTS
    if moment == "apres_17h":
        # "max 17h" (règles de parité TCA) : seul le créneau 17h00-18h30 est
        # concerné — l'enseignant doit avoir terminé à 17h.
        return [SLOTS_PER_DAY - 1]
    return []  # "plage_horaire_precisee_dans_raw" ou inconnu : ne jamais deviner


def _resolve_token_slots(token: dict) -> tuple[int | None, list[int]]:
    """(jour, créneaux) d'un token `recurrent_hebdomadaire`.

    Quand `moment` n'est pas catégorisé ("plage_horaire_precisee_dans_raw"),
    l'horaire explicite est bien présent dans `raw` ("15h30 à 18h30", "à partir
    de 14h00") : on l'extrait avec le même mécanisme que les événements du
    calendrier officiel plutôt que de deviner.
    """
    jour = DAY_FR.get(str(token.get("jour", "")).lower())
    raw_text = str(token.get("raw", ""))
    slots = _slots_for_moment(str(token.get("moment", "")))
    if not slots and jour is not None:
        slots = _slots_for_open_ended_time(raw_text) or sorted(_slots_for_event_text(raw_text))
    return jour, slots


def _parse_availability_whitelist(entry: dict) -> tuple[set[tuple[int, int]], set[date], list[str]]:
    """
    Traduit `disponibilites_tokens` en liste blanche DURE quand l'entrée porte
    `disponibilites_exclusives: true` (arbitrage utilisateur du 10/08/2026 :
    « les jours non listés sont interdits »).

    Deux axes indépendants, combinés en ET quand les deux sont présents :
    - créneaux hebdomadaires récurrents -> `allowed_slots` ;
    - dates ponctuelles -> `allowed_dates` (cas du vacataire qui ne donne que
      ses dates de venue, ex. Marc Nino).
    """
    allowed_slots: set[tuple[int, int]] = set()
    allowed_dates: set[date] = set()
    unresolved: list[str] = []

    for token in entry.get("disponibilites_tokens") or []:
        ttype = token.get("type")
        raw_text = str(token.get("raw", ""))
        if ttype == "recurrent_hebdomadaire":
            jour, slots = _resolve_token_slots(token)
            if jour is None or not slots:
                unresolved.append(raw_text)
                continue
            allowed_slots.update((jour, s) for s in slots)
        elif ttype == "date_specifique":
            dates = _parse_date_token(raw_text)
            if not dates:
                unresolved.append(raw_text)
                continue
            allowed_dates.update(dates)
        else:
            unresolved.append(raw_text)

    return allowed_slots, allowed_dates, unresolved


def _parse_parity_rules(entry: dict) -> list[TeacherWeekParityRule]:
    """`regles_parite_semaine` -> règles machine (cf. `TeacherWeekParityRule`)."""
    rules: list[TeacherWeekParityRule] = []
    for raw in entry.get("regles_parite_semaine") or []:
        jour = DAY_FR.get(str(raw.get("jour", "")).lower())
        slots = _slots_for_moment(str(raw.get("moment", "")))
        parity = str(raw.get("parite", ""))
        if jour is None or not slots or parity not in {"paire", "impaire"}:
            continue
        rules.append(TeacherWeekParityRule(parity=parity, day=jour, slots=slots))
    return rules


def parse_teacher_constraints_json(path: Path) -> tuple[list[TeacherAvailability], dict[str, str]]:
    """Charge contraintes/05_enseignants_contraintes.json (tokens structurés)."""
    teachers: list[TeacherAvailability] = []
    notes: dict[str, str] = {}
    if not path.exists():
        return teachers, notes

    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        code = str(entry.get("trigramme", "")).strip()
        if not code:
            continue

        forbidden_slots: set[tuple[int, int]] = set()
        forbidden_dates: set[date] = set()
        unresolved: list[str] = []

        for token in entry.get("indisponibilites_tokens") or []:
            ttype = token.get("type")
            raw_text = str(token.get("raw", ""))
            if ttype == "recurrent_hebdomadaire":
                # `moment` non catégorisé (ex. "plage_horaire_precisee_dans_raw")
                # : le jour est connu, seul l'horaire précis n'a pas été rangé
                # dans matin/après-midi/journée par la source — pas une
                # supposition, l'horaire explicite ("15h30 à 18h30") est bien
                # présent dans `raw` (cf. `_resolve_token_slots`).
                jour, slots = _resolve_token_slots(token)
                if jour is None or not slots:
                    unresolved.append(raw_text)
                    continue
                forbidden_slots.update((jour, s) for s in slots)
            elif ttype == "date_specifique":
                dates = _parse_date_token(raw_text)
                if not dates:
                    unresolved.append(raw_text)
                    continue
                forbidden_dates.update(dates)
            else:
                # "autre_a_interpreter" ou type inconnu, sans `jour` structuré
                # (contrairement à "recurrent_hebdomadaire") : n'extraire QUE
                # si un jour ET un horaire explicite sont tous deux présents
                # dans le texte brut (ex. "les jeudis après 17h00") — sinon
                # règle de donnée fraîche du projet, on ne devine jamais.
                text_lower = raw_text.lower()
                jour = next((idx for name, idx in DAY_FR.items() if name in text_lower), None)
                slots = (_slots_for_open_ended_time(raw_text) or sorted(_slots_for_event_text(raw_text))) if jour is not None else []
                if jour is None or not slots:
                    unresolved.append(raw_text)
                    continue
                forbidden_slots.update((jour, s) for s in slots)

        preferred_days: list[int] = []
        for token in entry.get("disponibilites_tokens") or []:
            if token.get("type") == "recurrent_hebdomadaire":
                jour = DAY_FR.get(str(token.get("jour", "")).lower())
                if jour is not None:
                    preferred_days.append(jour)

        allowed_slots: set[tuple[int, int]] = set()
        allowed_dates: set[date] = set()
        if entry.get("disponibilites_exclusives"):
            allowed_slots, allowed_dates, dispo_unresolved = _parse_availability_whitelist(entry)
            unresolved.extend(dispo_unresolved)
            if not allowed_slots and not allowed_dates:
                # Sécurité : une liste blanche vide interdirait TOUT créneau à
                # l'enseignant. Mieux vaut ne rien restreindre et le signaler
                # que produire un modèle silencieusement infaisable.
                unresolved.append(
                    "disponibilites_exclusives=true mais aucun créneau/date exploitable — "
                    "liste blanche ignorée"
                )

        parity_rules = _parse_parity_rules(entry)
        monthly_max = entry.get("regroupement_mensuel_max_semaines")

        note_parts = [
            str(entry.get("contraintes_pedagogiques_raw") or "").strip(),
            str(entry.get("explications_raw") or "").strip(),
        ]
        if unresolved:
            note_parts.append("À interpréter manuellement : " + " | ".join(unresolved))
        note = "\n".join(p for p in note_parts if p)
        notes[code] = note

        teachers.append(
            TeacherAvailability(
                teacher_code=code,
                forbidden_slots=sorted(forbidden_slots),
                preferred_days=sorted(set(preferred_days)),
                allowed_slots=sorted(allowed_slots),
                allowed_dates=sorted(d.isoformat() for d in allowed_dates),
                week_parity_rules=parity_rules,
                parity_reference=str(entry.get("parity_reference") or "departement"),
                monthly_cluster_max_weeks=int(monthly_max) if monthly_max else None,
                notes=note[:500] if note else None,
                metadata={
                    "forbidden_dates": sorted(d.isoformat() for d in forbidden_dates),
                    "raw_indisponibilites": entry.get("indisponibilites_raw"),
                    "raw_disponibilites": entry.get("disponibilites_raw"),
                    "raw_contraintes": entry.get("contraintes_pedagogiques_raw"),
                    "unresolved_tokens": unresolved,
                },
            )
        )
    return teachers, notes


def _parcours_code_from_label(label: str, but_prefix: str) -> str:
    """"S3-DEV-FC" + "BUT2" -> "BUT2-DEV-FC" (le code `parcours` réel ne varie pas avec le semestre)."""
    suffix = re.sub(r"^S\d+-", "", label)
    return f"{but_prefix}-{suffix}"


def load_alternance_presence_json(path: Path) -> list[StudentPresence]:
    """Charge contraintes/03_calendrier_alternance_officiel.json (semaines IUT FC)."""
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    presences: list[StudentPresence] = []
    for block_key, but_prefix in _ALTERNANCE_BLOCK_BUT_PREFIX.items():
        block = data.get(block_key)
        if not block:
            continue

        parcours_keys = sorted(
            {_parcours_code_from_label(p, but_prefix) for p in block.get("parcours_concernes", [])}
        )
        dates: set[date] = set()
        for window in block.get("semaines_iut", []):
            for raw in window.get("dates", []):
                d = parse_iso_or_fr_date(raw)
                if d:
                    dates.add(d)

        if parcours_keys and dates:
            presences.append(
                StudentPresence(
                    parcours_keys=parcours_keys,
                    presence_dates=dates,
                    label=f"Alternance {block_key.replace('_', ' ')}",
                )
            )
    return presences


def load_all_constraints(data_root: Path | None = None) -> ConstraintsBundle:
    """Charge calendrier IUT + contraintes enseignants + dispos étudiants FC.

    Source unique : `contraintes/*.json`. Lève `ConstraintsDataError` si les
    fichiers attendus sont absents ou vides plutôt que de dégrader en silence
    vers des contraintes vides (cf. `ConstraintsDataError`).
    """
    from cal_iut.calendar.academic import build_default_calendar_2026_2027

    root = data_root or Path(__file__).resolve().parents[3]
    contraintes_dir = root / "contraintes"

    calendar = build_default_calendar_2026_2027()

    teacher_path = contraintes_dir / "05_enseignants_contraintes.json"
    teachers, notes = parse_teacher_constraints_json(teacher_path)
    if not teachers:
        raise ConstraintsDataError(
            f"Aucun enseignant chargé depuis {teacher_path} (fichier absent ou vide) — "
            "le solveur tournerait sans aucune contrainte enseignante."
        )

    presence_path = contraintes_dir / "03_calendrier_alternance_officiel.json"
    presences = load_alternance_presence_json(presence_path)

    return ConstraintsBundle(
        calendar=calendar,
        teachers=teachers,
        student_presences=presences,
        raw_notes=notes,
    )


def allowed_week_days_for_parcours(
    presence: StudentPresence,
    calendar: AcademicCalendar,
    week_offset: int,
    weeks: int,
) -> set[tuple[int, int]]:
    allowed: set[tuple[int, int]] = set()
    for d in presence.presence_dates:
        mapped = calendar.date_to_week_day(d)
        if mapped is None:
            continue
        abs_week, day = mapped
        rel = abs_week - week_offset
        if 0 <= rel < weeks:
            allowed.add((rel, day))
    return allowed


def merge_teacher_availability(
    yaml_teachers: list[TeacherAvailability],
    csv_teachers: list[TeacherAvailability],
) -> list[TeacherAvailability]:
    """Fusionne YAML + JSON contraintes (JSON prioritaire sur les créneaux interdits)."""
    by_code = {t.teacher_code: t for t in yaml_teachers}
    for teacher in csv_teachers:
        existing = by_code.get(teacher.teacher_code)
        if not existing:
            by_code[teacher.teacher_code] = teacher
            continue
        slots = sorted(set(existing.forbidden_slots) | set(teacher.forbidden_slots))
        days = sorted(set(existing.preferred_days) | set(teacher.preferred_days))
        meta = {**existing.metadata, **teacher.metadata}
        # Liste blanche : INTERSECTION quand les deux sources en déclarent une
        # (chacune restreint), sinon celle qui existe. Une source sans liste
        # blanche ne doit jamais élargir celle de l'autre.
        if existing.allowed_slots and teacher.allowed_slots:
            allowed_slots = sorted(set(existing.allowed_slots) & set(teacher.allowed_slots))
        else:
            allowed_slots = sorted(set(existing.allowed_slots) | set(teacher.allowed_slots))
        if existing.allowed_dates and teacher.allowed_dates:
            allowed_dates = sorted(set(existing.allowed_dates) & set(teacher.allowed_dates))
        else:
            allowed_dates = sorted(set(existing.allowed_dates) | set(teacher.allowed_dates))
        by_code[teacher.teacher_code] = TeacherAvailability(
            teacher_code=teacher.teacher_code,
            forbidden_slots=slots,
            preferred_slots=existing.preferred_slots or teacher.preferred_slots,
            preferred_days=days,
            allowed_slots=allowed_slots,
            allowed_dates=allowed_dates,
            # UNION, et surtout : ne jamais oublier ce champ ici. Cette fusion
            # RECONSTRUIT l'objet — tout champ non recopié disparaît en silence
            # dès qu'un enseignant est présent des deux côtés, ce qui est le cas
            # de presque tous. Une indisponibilité saisie en YAML serait alors
            # perdue sans le moindre avertissement.
            forbidden_date_slots=(
                list(existing.forbidden_date_slots) + list(teacher.forbidden_date_slots)
            ),
            week_parity_rules=teacher.week_parity_rules or existing.week_parity_rules,
            parity_reference=teacher.parity_reference,
            monthly_cluster_max_weeks=(
                teacher.monthly_cluster_max_weeks or existing.monthly_cluster_max_weeks
            ),
            max_afternoons_per_week=existing.max_afternoons_per_week,
            notes=teacher.notes or existing.notes,
            metadata=meta,
        )
    return list(by_code.values())


def augment_teacher_availability_with_sae_supervision(
    teachers: list[TeacherAvailability],
    supervisor_dates: dict[str, set[date]],
) -> list[TeacherAvailability]:
    """
    Ajoute les dates de supervision SAE (cf. `planning_loader.py::
    sae_supervisor_dates_by_teacher`) aux `forbidden_dates` de chaque
    enseignant — retour utilisateur du 11/08/2026 : « pendant une SAE les
    profs qui sont assignés dessus ne sont que très peu disponibles [...] il
    faut limiter leur nombre de cours voire pas en mettre en même temps ».

    Réutilise volontairement le mécanisme `forbidden_dates` déjà câblé et
    testé (`add_teacher_availability_constraints` pour l'étage dur,
    `decomposed.py::_teacher_available_slots_by_week` pour la capacité de
    l'étage 2) plutôt qu'un chemin de contrainte séparé — même granularité
    (journée entière) que la sanctuarisation SAE par parcours, appliquée ici
    au niveau ENSEIGNANT : un référent de SAE devient indisponible pour tout
    cours classique ce jour-là, sur N'IMPORTE QUEL AUTRE parcours (une SAE
    d'un parcours occupe l'enseignant, peu importe qui d'autre a cours ce
    jour-là).

    Certains référents (ex. FME, 28 jours cumulés sur 4 SAE) n'ont AUCUNE
    ligne dans `CONTRAINTES ENSEIGNANTS` — une entrée minimale est créée pour
    eux plutôt que de silencieusement les ignorer.
    """
    if not supervisor_dates:
        return teachers

    by_code = {t.teacher_code: t for t in teachers}
    for code, dates in supervisor_dates.items():
        if not dates:
            continue
        existing = by_code.get(code)
        new_dates = {d.isoformat() for d in dates}
        if existing is None:
            by_code[code] = TeacherAvailability(
                teacher_code=code,
                metadata={"forbidden_dates": sorted(new_dates)},
            )
            continue
        merged = sorted(set(existing.metadata.get("forbidden_dates") or ()) | new_dates)
        by_code[code] = existing.model_copy(
            update={"metadata": {**existing.metadata, "forbidden_dates": merged}}
        )
    return list(by_code.values())
