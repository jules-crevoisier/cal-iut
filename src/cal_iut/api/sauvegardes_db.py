"""Sauvegarde quotidienne de la base SQLite (audit 29/09/2026, P1-10).

Les sauvegardes JSON (`api/sauvegardes.py`) ne gardent que les placements.
La base, elle, porte les comptes, les clés API, les tâches, les corrections
et l'historique des runs : elle n'était sauvegardée nulle part.

Un fichier par jour, `data/state/sauvegardes_db/cal-iut-AAAA-MM-JJ.db`, pris
avec l'API de sauvegarde en ligne de SQLite (`sqlite3.Connection.backup`) :
une copie COHÉRENTE même pendant que l'application écrit (mode WAL), ce
qu'une copie de fichier ne garantit pas. Conservées 30 jours.

Déclenchée au même endroit que l'instantané JSON (premier écrit du jour et
démarrage, au plus une par jour), et à la main avec `cal-iut sauvegarder-base`.
Restauration : cf. `GUIDE.md`, « Restaurer la base ».

Ces fichiers restent sur le même volume que la base : ils protègent d'une
erreur de manipulation ou d'une base abîmée, pas de la perte du volume. Les
copier hors du serveur reste à faire (sauvegarde de volume Dokploy, rclone).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "state"
SAUVEGARDES_DB_DIR = STATE_DIR / "sauvegardes_db"
RETENTION_JOURS = 30

_PREFIXE = "cal-iut-"
_SUFFIXE = ".db"


def _aujourdhui() -> date:
    """Point d'injection pour les tests (même principe que `sauvegardes`)."""
    return date.today()  # noqa: DTZ011 — date CALENDAIRE locale


def chemin(jour: str) -> Path:
    return SAUVEGARDES_DB_DIR / f"{_PREFIXE}{jour}{_SUFFIXE}"


def sauvegarder(source: Path, cible: Path | None = None) -> Path:
    """Copie cohérente de `source` vers `cible` (par défaut, le fichier du
    jour). Écrit d'abord un fichier temporaire, le vérifie
    (`PRAGMA quick_check`), puis le renomme : une sauvegarde ratée ne
    remplace jamais une bonne. Lève en cas d'échec."""
    source = Path(source)
    if not source.exists():
        # `sqlite3.connect` créerait une base vide : on sauvegarderait du vide.
        raise FileNotFoundError(f"Base introuvable : {source}")
    cible = Path(cible) if cible is not None else chemin(_aujourdhui().isoformat())
    cible.parent.mkdir(parents=True, exist_ok=True)
    temporaire = cible.with_name(cible.name + ".tmp")
    temporaire.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(temporaire)) as dst:
            src.backup(dst)
            verdict = dst.execute("PRAGMA quick_check").fetchone()[0]
        if verdict != "ok":
            raise sqlite3.DatabaseError(f"Sauvegarde invalide ({verdict})")
        os.replace(temporaire, cible)
    finally:
        temporaire.unlink(missing_ok=True)
    return cible


def purger_anciennes(reference: date | None = None) -> list[str]:
    """Supprime les sauvegardes de plus de `RETENTION_JOURS` jours ; rend
    les jours supprimés (AAAA-MM-JJ)."""
    if not SAUVEGARDES_DB_DIR.exists():
        return []
    limite = (reference or _aujourdhui()) - timedelta(days=RETENTION_JOURS)
    supprimes: list[str] = []
    for f in SAUVEGARDES_DB_DIR.glob(f"{_PREFIXE}*{_SUFFIXE}"):
        jour = f.name[len(_PREFIXE) : -len(_SUFFIXE)]
        try:
            date_fichier = datetime.strptime(jour, "%Y-%m-%d").date()  # noqa: DTZ007 — date calendaire
        except ValueError:
            continue
        if date_fichier < limite:
            f.unlink(missing_ok=True)
            supprimes.append(jour)
    return sorted(supprimes)


def sauvegarder_si_necessaire(source: Path | None) -> Path | None:
    """Au plus une sauvegarde par jour. NE LÈVE JAMAIS (une sauvegarde ratée
    ne doit ni faire échouer un placement, ni empêcher le démarrage), mais
    l'échec est journalisé."""
    if source is None:
        return None
    try:
        if chemin(_aujourdhui().isoformat()).exists():
            return None
        cible = sauvegarder(Path(source))
        purger_anciennes()
        return cible
    except Exception:
        logger.exception("Sauvegarde quotidienne de la base en échec (%s)", source)
        return None
