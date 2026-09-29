"""Moteur SQLite unique par chemin, WAL, sessions refermées — audit du
29/09/2026, P1-9.

Avant : `get_repo()` appelait `init_db()` à chaque appel, qui recréait un
moteur et rejouait `create_all` (198 moteurs distincts pour 200 appels), et
les `Session` n'étaient jamais refermées.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from cal_iut.api.main import app
from cal_iut.api.state import get_repo, get_state
from cal_iut.db import session as db_session
from cal_iut.db.models import Base, PlanningRun
from conftest import creer_compte_actif_et_connecter


def test_un_seul_moteur_par_chemin(tmp_path: Path) -> None:
    chemin = tmp_path / "unique.db"
    assert db_session.get_engine(chemin) is db_session.get_engine(chemin)
    assert db_session.get_engine(tmp_path / "autre.db") is not db_session.get_engine(chemin)


def test_get_repo_ne_recree_ni_moteur_ni_schema(db_isole, monkeypatch) -> None:
    get_repo()
    moteurs_avant = dict(db_session._moteurs)
    appels: list[object] = []
    origine = Base.metadata.create_all
    monkeypatch.setattr(Base.metadata, "create_all", lambda *a, **k: (appels.append(1), origine(*a, **k)))
    for _ in range(50):
        repo = get_repo()
        repo.db.close()
    assert appels == []
    assert db_session._moteurs == moteurs_avant


def test_wal_et_delai_d_attente(tmp_path: Path) -> None:
    chemin = tmp_path / "wal.db"
    db_session.init_db(chemin)
    with db_session.get_engine(chemin).connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == db_session.BUSY_TIMEOUT_MS


def test_changer_de_chemin_change_de_base(tmp_path: Path) -> None:
    """Les tests (et `state.db_path`) basculent de base en cours de route :
    chaque chemin garde ses propres données."""
    etat = get_state()
    ancien = etat.db_path
    try:
        etat.db_path = tmp_path / "a.db"
        repo_a = get_repo()
        repo_a.db.add(PlanningRun(parcours="BUT1", semestre="S1", status="OPTIMAL"))
        repo_a.db.commit()
        repo_a.db.close()

        etat.db_path = tmp_path / "b.db"
        repo_b = get_repo()
        assert repo_b.db.query(PlanningRun).count() == 0
        repo_b.db.close()

        etat.db_path = tmp_path / "a.db"
        repo_a = get_repo()
        assert repo_a.db.query(PlanningRun).count() == 1
        repo_a.db.close()
    finally:
        etat.db_path = ancien


def test_un_fichier_supprime_est_reprepare(tmp_path: Path) -> None:
    chemin = tmp_path / "efface.db"
    db_session.init_db_une_fois(chemin)
    chemin.unlink()
    db_session.init_db_une_fois(chemin)
    db = db_session.get_db(chemin)
    try:
        assert db.query(PlanningRun).count() == 0
    finally:
        db.close()


def test_la_portee_referme_ses_sessions(tmp_path: Path) -> None:
    chemin = tmp_path / "portee.db"
    db_session.init_db(chemin)
    with db_session.portee_sessions():
        db = db_session.get_db(chemin)
        db.query(PlanningRun).count()
        assert db.in_transaction()
    assert not db.in_transaction()


def test_une_requete_referme_les_sessions_qu_elle_ouvre(db_isole, monkeypatch) -> None:
    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="edit")
    ouvertes: list[Session] = []
    origine = db_session.get_db

    def _espion(*a, **k):
        s = origine(*a, **k)
        ouvertes.append(s)
        return s

    monkeypatch.setattr(db_session, "get_db", _espion)
    monkeypatch.setattr("cal_iut.api.main.get_db", _espion)
    monkeypatch.setattr("cal_iut.api.accounts.get_db", _espion)
    monkeypatch.setattr("cal_iut.api.state.get_db", _espion)
    assert client.get("/taches").status_code == 200
    assert ouvertes, "la requête aurait dû ouvrir au moins une session"
    assert all(not s.in_transaction() for s in ouvertes)
