"""Sauvegarde JSON quotidienne des semaines et séances placées — item B du
contrat verrouillé (22/09/2026), todo : « Avoir un fichier JSON backup des
semaines et séances placées à une date précise ».

UN FICHIER PAR JOUR CALENDAIRE (`data/state/sauvegardes/cal-iut-AAAA-MM-JJ.
json`), jamais par run ni par écriture : la question posée par le todo est
« à quoi ressemblait le planning CE JOUR-LÀ », pas « à chaque modification ».
`snapshot_si_necessaire` (appelée depuis `api/main.py::_apres_ecriture_
planning` et depuis `startup()`) n'en prend donc AU PLUS UNE par jour — au
premier écrit du jour, ou au démarrage si le fichier du jour manque encore
(cas d'un redémarrage un jour où personne n'a encore rien modifié).

`data/state/` (pas `data/config/`) — même volume persistant que
`custom_sessions.json`/`session_overrides.json` : c'est le seul endroit qui
survit à un redéploiement Dokploy (cf. `api/state.py::DB_PATH`).

AUCUNE RESTAURATION ICI — hors périmètre du contrat verrouillé (« No restore
endpoint (out of scope) »). Relire un instantané pour l'appliquer au planning
soulèverait ses propres questions (fusion des conflits avec l'état courant,
undo partiel...) qu'un simple module de lecture/écriture de fichier ne doit
pas trancher à la place d'un outil dédié.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from cal_iut.api import custom_sessions, session_overrides
from cal_iut.celcat.fichiers import ecrire_atomique

FORMAT_SAUVEGARDE = "cal-iut-sauvegarde/1"

STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "state"
SAUVEGARDES_DIR = STATE_DIR / "sauvegardes"

# Conservées 90 jours (contrat) — au-delà, purgées par `snapshot_si_necessaire`.
RETENTION_JOURS = 90

_PREFIXE = "cal-iut-"
_SUFFIXE = ".json"


def nom_fichier_valide(jour: str) -> bool:
    """`jour` STRICTEMENT au format AAAA-MM-JJ — refuse tout ce qui
    contiendrait un séparateur de chemin (« .. », « / », « \\ ») AVANT même
    d'atteindre le système de fichiers (`GET /sauvegardes/{date}`,
    `api/main.py` : jamais de traversée de chemin possible via ce
    paramètre)."""
    try:
        datetime.strptime(jour, "%Y-%m-%d")  # noqa: DTZ007 — date CALENDAIRE, jamais un horodatage
    except (ValueError, TypeError):
        return False
    return True


def chemin(jour: str) -> Path:
    """Chemin du fichier pour `jour` (AAAA-MM-JJ) — PUBLIC : `api/main.py`
    l'utilise pour le téléchargement (`GET /sauvegardes/{date}`), toujours
    APRÈS avoir validé `jour` avec `nom_fichier_valide` (jamais de
    traversée de chemin — cette fonction ne valide rien elle-même)."""
    return SAUVEGARDES_DIR / f"{_PREFIXE}{jour}{_SUFFIXE}"


def _aujourdhui() -> date:
    """Point d'injection unique pour « aujourd'hui » — les tests gèlent la
    date via `monkeypatch.setattr(sauvegardes, "_aujourdhui", ...)`, même
    principe que `api/main.py::_today` pour l'item A (date passée). Date
    CALENDAIRE locale (jamais un horodatage UTC) : un fichier par JOUR au
    sens du calendrier académique, pas par tranche de 24h universelle."""
    return date.today()  # noqa: DTZ011


def instantane(state: object) -> dict[str, object]:
    """Construit l'instantané JSON — LECTURE SEULE de `state` et des stores
    persistants (`custom_sessions`, `session_overrides`) : un backup ne doit
    jamais avoir d'effet de bord sur ce qu'il décrit.
    """
    calendrier = state.calendar
    # `weekIndex` ici est l'indice ABSOLU du calendrier — comme
    # `calendrier.teaching_mondays`, PAS forcément le même indice que
    # `placements[].week` ci-dessous, qui est relatif au décalage de
    # semestre de CHAQUE séance (`semester_week_offset`, différent par
    # semestre — cf. mémoire "Trois numérotations de semaines" : indice
    # solveur != libellé grille != pastille, toujours le libellé daté pour
    # lever l'ambiguïté). `placements[].week`/`.day` sont un DUMP BRUT de
    # `state.timetable`, tels que l'application les stocke déjà — aucune
    # transformation qui inventerait une nouvelle numérotation.
    semaines = [
        {
            "weekIndex": i,
            "monday": monday.isoformat(),
            "label": calendrier.department_week_label(i),
        }
        for i, monday in enumerate(calendrier.teaching_mondays)
    ]

    placements: list[dict[str, object]] = []
    for p in state.timetable:
        seance = state.sessions_by_id.get(p.session_id)
        placements.append(
            {
                "session_id": p.session_id,
                "course_code": p.course_code,
                "session_type": seance.session_type.value if seance else None,
                "group_ids": list(p.group_ids or []),
                "teacher_codes": list(p.teacher_codes or []),
                "week": p.week,
                "day": p.day,
                "slot": p.slot,
                "duration_slots": seance.duration_slots if seance else None,
                "room_id": getattr(p, "room_id", None),
                "room_label": getattr(p, "room_label", None),
                "locked": bool(seance.locked) if seance else False,
            }
        )

    seances_personnalisees = [
        {
            "id": s.id,
            "course_code": s.course_code,
            "course_name": s.course_name,
            "semestre": s.semestre,
            "parcours": s.parcours,
            "annee": s.annee,
            "session_type": s.session_type.value,
            "group_ids": list(s.group_ids),
            "teacher_codes": list(s.teacher_codes),
            "duration_slots": s.duration_slots,
            "is_eval": s.is_eval,
            "note": s.metadata.get("note") or "",
            "created_at": s.metadata.get("created_at"),
        }
        for s in custom_sessions.load_custom_sessions()
    ]

    return {
        "format": FORMAT_SAUVEGARDE,
        "genere_le": datetime.now(UTC).isoformat(),
        "run_id": state.current_run_id,
        "semaines": semaines,
        "placements": placements,
        "seances_personnalisees": seances_personnalisees,
        "retouches": session_overrides.load_overrides(),
    }


def prendre_maintenant(state: object) -> Path:
    """Écrit (ou ÉCRASE) l'instantané du jour — `POST /sauvegardes`
    (toujours explicite, cf. `api/main.py`) et `snapshot_si_necessaire`
    (au plus une fois par jour)."""
    cible = chemin(_aujourdhui().isoformat())
    ecrire_atomique(cible, json.dumps(instantane(state), ensure_ascii=False, indent=2))
    return cible


def deja_pris_aujourdhui() -> bool:
    return chemin(_aujourdhui().isoformat()).exists()


def purger_anciennes(reference: date | None = None) -> list[str]:
    """Supprime les instantanés antérieurs à `RETENTION_JOURS` — rend les
    jours (AAAA-MM-JJ) supprimés, pour les tests."""
    if not SAUVEGARDES_DIR.exists():
        return []
    reference = reference or _aujourdhui()
    limite = reference - timedelta(days=RETENTION_JOURS)
    supprimes: list[str] = []
    for f in SAUVEGARDES_DIR.glob(f"{_PREFIXE}*{_SUFFIXE}"):
        jour = f.stem[len(_PREFIXE) :]
        if not nom_fichier_valide(jour):
            continue
        if datetime.strptime(jour, "%Y-%m-%d").date() < limite:  # noqa: DTZ007 — date calendaire
            f.unlink(missing_ok=True)
            supprimes.append(jour)
    return supprimes


def snapshot_si_necessaire(state: object) -> None:
    """Point d'appel UNIQUE depuis `api/main.py` — `_apres_ecriture_planning`
    (premier écrit du jour) ET `startup()` (fichier du jour manquant, ex. un
    redémarrage avant toute modification). NE LÈVE JAMAIS : une sauvegarde
    ratée ne doit ni faire échouer un placement, ni empêcher le démarrage de
    l'application (même contrat que `api/main.py::_apres_ecriture_planning`
    pour Celcat)."""
    try:
        if deja_pris_aujourdhui():
            return
        prendre_maintenant(state)
        purger_anciennes()
    except Exception:  # noqa: BLE001 — jamais fatal, cf. docstring.
        return


def lister() -> list[dict[str, object]]:
    """`[{date, taille_octets, nb_placements}]`, plus récent d'abord — `GET
    /sauvegardes` (`api/main.py`). Les noms de fichiers AAAA-MM-JJ trient
    lexicographiquement comme les dates elles-mêmes, pas besoin de reparser
    pour l'ordre."""
    if not SAUVEGARDES_DIR.exists():
        return []
    entrees: list[dict[str, object]] = []
    for f in sorted(SAUVEGARDES_DIR.glob(f"{_PREFIXE}*{_SUFFIXE}"), reverse=True):
        jour = f.stem[len(_PREFIXE) :]
        if not nom_fichier_valide(jour):
            continue
        try:
            contenu = json.loads(f.read_text(encoding="utf-8"))
            nb_placements = len(contenu.get("placements") or [])
        except (OSError, json.JSONDecodeError):
            nb_placements = 0
        entrees.append({"date": jour, "taille_octets": f.stat().st_size, "nb_placements": nb_placements})
    return entrees
