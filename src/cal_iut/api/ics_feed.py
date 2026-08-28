"""Flux .ics ABONNABLE (webcal://) — retour utilisateur 28/08/2026 (relayé
depuis Discord) : « pour le ics on pourrait peut-être faire un lien qui
s'update automatiquement ? ». À la différence du téléchargement statique déjà
existant (`frontend/src/utils/ics.ts::downloadIcs`, un fichier figé au
moment du clic), une app d'agenda qui s'ABONNE à cette URL la re-télécharge
périodiquement d'elle-même — le calendrier personnel reste à jour tout seul
après un déplacement de séance, sans jamais re-télécharger un fichier.

UID stable sur `session_id` (jamais recomposé à partir de sa position
semaine/jour/créneau, contrairement au fichier statique) : c'est précisément
ce qui permet à un agenda de reconnaître « c'est le même événement, juste
déplacé » plutôt que de dupliquer un nouvel événement à chaque
resynchronisation après un déplacement.

Ne réutilise PAS `export/formatter.py::build_export_rows` : celui-ci calcule
les dates avec un `week_offset` UNIQUE pour tout l'export (résolu depuis UN
SEUL semestre de référence) — correct pour l'export global existant, mais
faux pour un flux personnel dont les séances peuvent appartenir à PLUSIEURS
semestres (un enseignant intervenant en S1 ET S3, par exemple). Chaque
placement calcule donc sa date depuis SON PROPRE semestre ici.

Public comme le reste des liens personnels (cf. `api/auth.py`) : une app
d'agenda ne peut pas taper le mot de passe partagé à chaque resynchronisation
périodique.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class IcsItem:
    session_id: str
    course_code: str
    course_name: str
    date: str  # ISO "YYYY-MM-DD", "" si non calculable (pas de calendrier chargé)
    time_start: str  # "HH:MM"
    time_end: str
    room_label: str | None
    group_ids: list[str]
    teacher_codes: list[str]


def _ics_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def build_ics(
    items: list[IcsItem],
    calendar_name: str,
    uid_prefix: str,
    group_labels: dict[str, str],
    teacher_labels: dict[str, str],
) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//cal-iut//planning MMI//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        # Suggère un intervalle de rafraîchissement aux applis qui le
        # respectent (pas garanti, chacune a sa propre logique de
        # resynchronisation) — un signal correct à donner plutôt qu'aucun.
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
        f"X-WR-CALNAME:{_ics_escape('Planning MMI — ' + calendar_name)}",
    ]
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for it in items:
        if not it.date:
            continue
        groups = ", ".join(group_labels.get(g, g) for g in it.group_ids)
        teachers = ", ".join(teacher_labels.get(t, t) for t in it.teacher_codes)
        year, month, day = (int(x) for x in it.date.split("-"))
        start_h, start_m = (int(x) for x in it.time_start.split(":"))
        end_h, end_m = (int(x) for x in it.time_end.split(":"))
        summary = it.course_code + (f" — {groups}" if groups else "")
        description = "\n".join(
            part for part in [
                it.course_name or it.course_code,
                f"Groupes : {groups}" if groups else "",
                f"Enseignant(s) : {teachers}" if teachers else "",
            ] if part
        )
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid_prefix}-{it.session_id}@cal-iut",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{year:04d}{month:02d}{day:02d}T{start_h:02d}{start_m:02d}00",
            f"DTEND:{year:04d}{month:02d}{day:02d}T{end_h:02d}{end_m:02d}00",
            f"SUMMARY:{_ics_escape(summary)}",
            f"LOCATION:{_ics_escape(it.room_label or '')}",
            f"DESCRIPTION:{_ics_escape(description)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
