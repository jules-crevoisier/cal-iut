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

FUSEAU HORAIRE (retour de David Annebicque, 29/08/2026 : « tu as un offset de
2 heures dans ton export ical ; en fait c'est ton UTC qui n'est pas
configuré »). Les dates étaient écrites sans suffixe ni `TZID` : au sens de
la RFC 5545 c'est une heure FLOTTANTE, que chaque client interprète à sa
façon et que Google lit comme de l'UTC. Le correctif ne pouvait pas être un
décalage fixe : le planning va de septembre à mars et traverse DEUX
changements d'heure (25/10/2026 et 28/03/2027) ; « +2h » serait faux la
moitié de l'année. On publie donc un vrai composant VTIMEZONE Europe/Paris
avec ses deux règles de bascule, et les dates y renvoient par `TZID` — c'est
le fuseau qui porte la règle, pas nous.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

TZID = "Europe/Paris"

# Composant VTIMEZONE minimal mais complet : les deux règles européennes
# (dernier dimanche de mars à 2h locales -> +2, dernier dimanche d'octobre à
# 3h locales -> +1). Écrit à la main plutôt que dérivé de `zoneinfo` : la
# base système ne fournit pas de RRULE, et un VTIMEZONE énumérant chaque
# transition serait à la fois plus long et périssable.
_VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    f"TZID:{TZID}",
    "X-LIC-LOCATION:Europe/Paris",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:+0100",
    "TZOFFSETTO:+0200",
    "TZNAME:CEST",
    "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0200",
    "TZOFFSETTO:+0100",
    "TZNAME:CET",
    "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10",
    "END:STANDARD",
    "END:VTIMEZONE",
]

# Origine du compteur de révision. Voir `_sequence`.
_EPOQUE = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
    # Dernière modification connue du placement (`current_placements.updated_at`).
    # Alimente `SEQUENCE` et `LAST-MODIFIED` : c'est ce qui dit à un agenda
    # « cet événement a changé ». `None` = jamais modifié depuis la génération.
    updated_at: datetime | None = None


def _ics_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _sequence(updated_at: datetime | None) -> int:
    """Numéro de révision, croissant à chaque modification.

    La RFC 5545 demande un entier positif croissant, pas un horodatage : on
    prend les MINUTES écoulées depuis le 1er janvier 2026. Deux modifications
    dans la même minute rendent le même numéro — sans conséquence, puisque
    `LAST-MODIFIED` et le contenu de l'événement changent quand même, et
    qu'un agenda resynchronise au mieux toutes les quelques heures.

    Volontairement dérivé d'une donnée EXISTANTE plutôt que d'un compteur à
    maintenir : un compteur devrait être stocké, incrémenté à chaque
    déplacement, et se désynchroniserait au premier oubli.
    """
    if updated_at is None:
        return 0
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return max(0, int((updated_at - _EPOQUE).total_seconds() // 60))


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
        # resynchronisation — Google Calendar en particulier ignore ce
        # champ et resynchronise sur son propre calendrier, ~toutes les 12 à
        # 24h, sans qu'on puisse forcer plus vite depuis le serveur). Retour
        # utilisateur 04/09/2026 : « en temps réel ou 1h max » — ramené de
        # 6h à 1h, le maximum qu'on promet ; le contenu lui-même est déjà
        # calculé en direct sur `state.timetable` à CHAQUE requête, aucune
        # mise en cache serveur ne s'ajoute par-dessus (cf. `Cache-Control`
        # sur la réponse HTTP, `api/main.py::ics_teacher`/`ics_groupe`).
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
        f"X-WR-CALNAME:{_ics_escape('Planning MMI — ' + calendar_name)}",
        # Repris par Google et Apple pour afficher le calendrier dans le bon
        # fuseau même avant de lire le premier événement.
        f"X-WR-TIMEZONE:{TZID}",
        *_VTIMEZONE,
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
            # UID CONSTANT, même quand la séance se déplace. Le faire varier
            # ferait AJOUTER un événement au lieu de mettre à jour celui qui
            # existe : l'ancien resterait affiché à côté du nouveau.
            f"UID:{uid_prefix}-{it.session_id}@cal-iut",
            f"DTSTAMP:{dtstamp}",
            f"SEQUENCE:{_sequence(it.updated_at)}",
            f"DTSTART;TZID={TZID}:{year:04d}{month:02d}{day:02d}T{start_h:02d}{start_m:02d}00",
            f"DTEND;TZID={TZID}:{year:04d}{month:02d}{day:02d}T{end_h:02d}{end_m:02d}00",
            f"SUMMARY:{_ics_escape(summary)}",
            f"LOCATION:{_ics_escape(it.room_label or '')}",
            f"DESCRIPTION:{_ics_escape(description)}",
        ]
        if it.updated_at is not None:
            horodatage = it.updated_at
            if horodatage.tzinfo is None:
                horodatage = horodatage.replace(tzinfo=timezone.utc)
            lines.append(
                "LAST-MODIFIED:" + horodatage.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
