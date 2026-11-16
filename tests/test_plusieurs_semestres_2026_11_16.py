"""Plusieurs semestres en base (lot 1 du chantier « Nouveau semestre »).

Avant le 16/11/2026, `save_run` vidait toute la table `current_placements` :
charger le planning de S2/S4/S6 aurait effacé celui de S1/S3/S5, retouches
manuelles comprises. Désormais un run ne remplace que le planning des
semestres qu'il couvre, et un run « brouillon » ne touche pas au planning
en service tant qu'il n'est pas publié.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cal_iut.db import session as db_session
from cal_iut.db.load_run import load_run_from_json
from cal_iut.db.models import CurrentPlacement, PlanningRun, SolverPlacement
from cal_iut.db.repository import (
    ETAT_BROUILLON,
    ETAT_PUBLIE,
    PlanningRepository,
    perimetre_semestres,
)
from cal_iut.db.session import get_db, init_db
from cal_iut.ingestion.pipeline import SEMESTRE_GROUPS


@pytest.fixture()
def chemin_base(tmp_path: Path) -> Path:
    return tmp_path / "cal-iut.db"


@pytest.fixture()
def repo(chemin_base: Path) -> PlanningRepository:
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(chemin_base)
    db = get_db(chemin_base)
    yield PlanningRepository(db)
    db.close()
    if db_session._engine:
        db_session._engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None


def _p(session_id: str, slot: int = 0, **extra: object) -> dict[str, object]:
    return {
        "session_id": session_id, "week": 0, "day": 0, "slot": slot,
        "course_code": session_id.split("-")[0], "room_id": "h101", **extra,
    }


def _enregistrer(repo: PlanningRepository, semestre: str, ids: list[str], **kw: object) -> PlanningRun:
    placements = [_p(i) for i in ids]
    return repo.save_run(
        parcours="MMI", semestre=semestre, status="FEASIBLE", objective_value=0,
        gap_penalty=0, weeks=24, solver_placements=placements,
        current_placements=placements, **kw,
    )


def _courants(repo: PlanningRepository) -> dict[str, int]:
    repo.db.expire_all()
    return {c.session_id: c.run_id for c in repo.db.query(CurrentPlacement)}


def test_le_perimetre_suit_les_groupes_de_l_ingestion() -> None:
    for groupe, semestres in SEMESTRE_GROUPS.items():
        assert perimetre_semestres(groupe.upper()) == frozenset(semestres)
        assert perimetre_semestres(groupe) == frozenset(semestres)
    assert perimetre_semestres("S1") == frozenset({"S1"})


def test_charger_le_semestre_pair_garde_le_semestre_impair(repo: PlanningRepository) -> None:
    impair = _enregistrer(repo, "ODD", ["WR101-S1-CM-1", "WR301-S3-TD-1"])
    # Retouche manuelle sur le planning en service.
    repo.update_current_placement("WR101-S1-CM-1", 2, 3, 4, "h018", None, locked=True)

    pair = _enregistrer(repo, "EVEN", ["WR201-S2-CM-1", "WR401-S4-TD-1"])

    courants = _courants(repo)
    assert courants == {
        "WR101-S1-CM-1": impair.id, "WR301-S3-TD-1": impair.id,
        "WR201-S2-CM-1": pair.id, "WR401-S4-TD-1": pair.id,
    }
    retouche = repo.db.get(CurrentPlacement, "WR101-S1-CM-1")
    assert (retouche.week, retouche.day, retouche.slot, retouche.locked) == (2, 3, 4, True)


def test_recharger_le_meme_semestre_remplace_son_planning(repo: PlanningRepository) -> None:
    _enregistrer(repo, "EVEN", ["WR201-S2-CM-1"])
    _enregistrer(repo, "ODD", ["WR101-S1-CM-1", "WR101-S1-CM-2"])
    nouveau = _enregistrer(repo, "ODD", ["WR101-S1-CM-1"])

    courants = _courants(repo)
    assert "WR101-S1-CM-2" not in courants, "l'ancien planning du même semestre est remplacé"
    assert courants["WR101-S1-CM-1"] == nouveau.id
    assert "WR201-S2-CM-1" in courants


def test_un_run_d_un_seul_semestre_remplace_le_groupe_qui_le_contient(repo: PlanningRepository) -> None:
    """`POST /solve` sans groupe enregistre « S1 » : il recoupe ODD."""
    _enregistrer(repo, "ODD", ["WR101-S1-CM-1", "WR301-S3-TD-1"])
    _enregistrer(repo, "EVEN", ["WR201-S2-CM-1"])
    _enregistrer(repo, "S1", ["WR101-S1-CM-9"])

    assert set(_courants(repo)) == {"WR101-S1-CM-9", "WR201-S2-CM-1"}


def test_un_brouillon_ne_touche_pas_au_planning_en_service(repo: PlanningRepository) -> None:
    en_service = _enregistrer(repo, "ODD", ["WR101-S1-CM-1"])
    brouillon = _enregistrer(repo, "ODD", ["WR101-S1-CM-1", "WR101-S1-CM-2"], etat=ETAT_BROUILLON)

    assert brouillon.etat == ETAT_BROUILLON
    assert _courants(repo) == {"WR101-S1-CM-1": en_service.id}
    assert repo.db.query(SolverPlacement).filter_by(run_id=brouillon.id).count() == 2
    # Le serveur restaure le dernier run EN SERVICE, pas le brouillon.
    assert repo.get_latest_run().id == en_service.id
    assert repo.get_latest_run(inclure_brouillons=True).id == brouillon.id


def test_publier_un_brouillon_le_met_en_service(repo: PlanningRepository) -> None:
    pair = _enregistrer(repo, "EVEN", ["WR201-S2-CM-1"])
    _enregistrer(repo, "ODD", ["WR101-S1-CM-1", "WR101-S1-CM-7"])
    brouillon = _enregistrer(repo, "ODD", ["WR101-S1-CM-1", "WR101-S1-CM-2"], etat=ETAT_BROUILLON)

    publie = repo.publier_run(brouillon.id)

    assert publie.etat == ETAT_PUBLIE
    assert _courants(repo) == {
        "WR201-S2-CM-1": pair.id,
        "WR101-S1-CM-1": brouillon.id,
        "WR101-S1-CM-2": brouillon.id,
    }
    assert repo.get_latest_run().id == brouillon.id


def test_publier_refuse_ce_qui_n_est_pas_un_brouillon(repo: PlanningRepository) -> None:
    en_service = _enregistrer(repo, "ODD", ["WR101-S1-CM-1"])
    with pytest.raises(ValueError, match="pas un brouillon"):
        repo.publier_run(en_service.id)
    with pytest.raises(ValueError, match="introuvable"):
        repo.publier_run(9999)
    assert _courants(repo) == {"WR101-S1-CM-1": en_service.id}


def test_etat_inconnu_refuse(repo: PlanningRepository) -> None:
    with pytest.raises(ValueError, match="inconnu"):
        _enregistrer(repo, "ODD", ["WR101-S1-CM-1"], etat="nimporte")
    assert repo.db.query(PlanningRun).count() == 0


def test_une_base_d_avant_la_colonne_etat_reste_lisible(chemin_base: Path) -> None:
    """La base de production n'a pas la colonne `etat` : elle est ajoutée au
    démarrage, et les runs existants (état vide) restent « en service »."""
    with sqlite3.connect(chemin_base) as brut:
        brut.execute(
            "CREATE TABLE planning_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, parcours VARCHAR(64),"
            " semestre VARCHAR(8), status VARCHAR(32), objective_value INTEGER, gap_penalty INTEGER,"
            " weeks INTEGER, created_at DATETIME)"
        )
        brut.execute(
            "INSERT INTO planning_runs (parcours, semestre, status, gap_penalty, weeks)"
            " VALUES ('MMI', 'ODD', 'CACHED', 0, 24)"
        )
    db_session._engine = None
    db_session._SessionLocal = None
    init_db(chemin_base)
    db = get_db(chemin_base)
    try:
        repo = PlanningRepository(db)
        ancien = repo.get_latest_run()
        assert ancien is not None and ancien.etat is None and ancien.semestre == "ODD"
        with pytest.raises(ValueError, match="pas un brouillon"):
            repo.publier_run(ancien.id)
    finally:
        db.close()
        db_session._engine.dispose()
        db_session._engine = None
        db_session._SessionLocal = None


def test_load_run_sauvegarde_la_base_avant_de_remplacer(chemin_base: Path, tmp_path: Path) -> None:
    def fichier(nom: str, ids: list[str]) -> Path:
        f = tmp_path / nom
        f.write_text(json.dumps({"placements": [_p(i) for i in ids]}), encoding="utf-8")
        return f

    db_session._engine = None
    db_session._SessionLocal = None
    try:
        load_run_from_json(fichier("impair.json", ["WR101-S1-CM-1"]), chemin_base, "odd")
        dossier = chemin_base.parent / "sauvegardes_db"
        assert not dossier.exists(), "rien à sauvegarder avant le tout premier chargement"

        pair = load_run_from_json(fichier("pair.json", ["WR201-S2-CM-1"]), chemin_base, "even")
        assert pair.semestre == "EVEN" and pair.etat == ETAT_PUBLIE

        copies = list(dossier.glob("cal-iut-*-avant-remplacement-*.db"))
        assert len(copies) == 1
        with sqlite3.connect(copies[0]) as copie:
            assert [r[0] for r in copie.execute("SELECT session_id FROM current_placements")] == [
                "WR101-S1-CM-1"
            ]
        with sqlite3.connect(chemin_base) as base:
            assert sorted(r[0] for r in base.execute("SELECT session_id FROM current_placements")) == [
                "WR101-S1-CM-1", "WR201-S2-CM-1",
            ]
    finally:
        if db_session._engine:
            db_session._engine.dispose()
        db_session._engine = None
        db_session._SessionLocal = None
