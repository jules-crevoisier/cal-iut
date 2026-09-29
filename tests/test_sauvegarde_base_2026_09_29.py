"""Sauvegarde quotidienne de la base SQLite (audit 29/09/2026, P1-10).

Copie cohérente par l'API de sauvegarde de SQLite (pas une copie de
fichier), au plus une par jour, 30 jours de rétention, jamais fatale.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

from cal_iut.api import sauvegardes_db
from cal_iut.cli import main as cli_main


def _base(chemin, lignes: int = 3) -> None:
    with closing(sqlite3.connect(chemin)) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t (x INTEGER)")
        c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(lignes)])
        c.commit()


def _compter(chemin) -> int:
    with closing(sqlite3.connect(chemin)) as c:
        return c.execute("SELECT COUNT(*) FROM t").fetchone()[0]


def test_la_sauvegarde_contient_les_ecritures_encore_dans_le_journal_wal(tmp_path, monkeypatch):
    """Une connexion reste ouverte avec des écritures non reportées dans le
    fichier principal (WAL) : une simple copie de `cal-iut.db` les perdrait."""
    monkeypatch.setattr(sauvegardes_db, "_aujourdhui", lambda: date(2026, 9, 29))
    base = tmp_path / "cal-iut.db"
    _base(base)
    ouverte = sqlite3.connect(base)
    ouverte.execute("PRAGMA wal_autocheckpoint=0")
    ouverte.execute("INSERT INTO t VALUES (99)")
    ouverte.commit()
    try:
        cible = sauvegardes_db.sauvegarder(base)
    finally:
        ouverte.close()
    assert cible == sauvegardes_db.SAUVEGARDES_DB_DIR / "cal-iut-2026-09-29.db"
    assert _compter(cible) == 4
    assert not list(sauvegardes_db.SAUVEGARDES_DB_DIR.glob("*.tmp"))


def test_une_seule_sauvegarde_par_jour_et_retention_de_30_jours(tmp_path, monkeypatch):
    base = tmp_path / "cal-iut.db"
    _base(base)
    dossier = sauvegardes_db.SAUVEGARDES_DB_DIR
    dossier.mkdir(parents=True)
    (dossier / "cal-iut-2026-08-29.db").write_bytes(b"")  # 31 jours : purgée
    (dossier / "cal-iut-2026-08-30.db").write_bytes(b"")  # 30 jours : gardée
    (dossier / "autre-chose.db").write_bytes(b"")  # jamais touché
    monkeypatch.setattr(sauvegardes_db, "_aujourdhui", lambda: date(2026, 9, 29))

    assert sauvegardes_db.sauvegarder_si_necessaire(base) is not None
    with closing(sqlite3.connect(base)) as c:
        c.execute("INSERT INTO t VALUES (7)")
        c.commit()
    assert sauvegardes_db.sauvegarder_si_necessaire(base) is None  # déjà prise aujourd'hui
    assert _compter(dossier / "cal-iut-2026-09-29.db") == 3
    assert sorted(f.name for f in dossier.iterdir()) == [
        "autre-chose.db", "cal-iut-2026-08-30.db", "cal-iut-2026-09-29.db",
    ]


def test_une_sauvegarde_ratee_ne_leve_jamais_et_ne_cree_pas_de_base_vide(tmp_path, caplog):
    absente = tmp_path / "absente.db"
    assert sauvegardes_db.sauvegarder_si_necessaire(absente) is None
    assert not absente.exists()
    assert "Sauvegarde quotidienne de la base en échec" in caplog.text


def test_le_premier_enregistrement_du_jour_sauvegarde_la_base(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from cal_iut.api import main

    base = tmp_path / "cal-iut.db"
    _base(base)
    monkeypatch.setattr(main, "get_state", lambda: SimpleNamespace(db_path=base))
    monkeypatch.setattr(main.sauvegardes, "snapshot_si_necessaire", lambda _s: None)
    monkeypatch.setattr(main.controle_doublons_hebdo, "verifier_si_necessaire", lambda _s: None)
    monkeypatch.setattr("cal_iut.celcat.ops.apres_ecriture_planning", lambda sid, action: None)
    monkeypatch.setattr(sauvegardes_db, "_aujourdhui", lambda: date(2026, 9, 29))
    main._apres_ecriture_planning("S1", "update")
    assert _compter(sauvegardes_db.SAUVEGARDES_DB_DIR / "cal-iut-2026-09-29.db") == 3


def test_commande_sauvegarder_base(tmp_path, monkeypatch, capsys):
    base = tmp_path / "cal-iut.db"
    _base(base, lignes=5)
    sortie = tmp_path / "copie.db"
    monkeypatch.setattr("sys.argv", ["cal-iut", "sauvegarder-base", "--base", str(base), "--sortie", str(sortie)])
    assert cli_main() == 0
    assert _compter(sortie) == 5
    assert "Base sauvegardée" in capsys.readouterr().out
