"""Tâche #44 (23/11/2026) : la génération tient compte de l'occupation
Celcat, et refuse de partir sans relevé sûr au lieu de tout croire libre."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cal_iut.api import occupations_externes as ext
from cal_iut.celcat import occupations as occ
from cal_iut.generation import verification


@pytest.fixture
def releve(tmp_path, monkeypatch):
    chemin = tmp_path / "celcat_occupations_externes.json"
    monkeypatch.setattr(occ, "chemin_fichier", lambda: chemin)
    monkeypatch.delenv(verification.ECHAPPEMENT_CELCAT, raising=False)
    ext.invalider()
    yield chemin
    ext.invalider()


def _ecrire(chemin, **champs):
    doc = {"version": 1, "evenements": [], "releve_le": datetime.now(UTC).isoformat(), **champs}
    occ.enregistrer(doc, chemin)
    ext.invalider()


def _controle(tmp_path):
    return verification.controle_celcat(tmp_path)


def test_sans_releve_la_generation_est_bloquee(releve, tmp_path):
    constats = _controle(tmp_path)
    assert len(constats) == 1 and verification.est_bloquant(constats[0])
    assert constats[0]["controle"] == "celcat.releve"


def test_releve_recent_et_complet_ne_dit_rien(releve, tmp_path):
    _ecrire(releve)
    assert _controle(tmp_path) == []


def test_releve_incomplet_est_bloquant_et_detaille(releve, tmp_path):
    _ecrire(releve, erreurs=["salle B.101 : délai dépassé"])
    constats = _controle(tmp_path)
    assert verification.est_bloquant(constats[0])
    assert "incomplet" in constats[0]["message"]
    assert constats[0]["details"] == ["salle B.101 : délai dépassé"]


def test_derniere_lecture_en_echec_est_bloquante(releve, tmp_path):
    _ecrire(releve, erreur="Celcat injoignable")
    assert verification.est_bloquant(_controle(tmp_path)[0])


def test_releve_perime_est_bloquant(releve, tmp_path):
    _ecrire(releve, releve_le=(datetime.now(UTC) - timedelta(hours=48)).isoformat())
    assert verification.est_bloquant(_controle(tmp_path)[0])


def test_echappement_explicite_degrade_en_alerte(releve, tmp_path, monkeypatch):
    monkeypatch.setenv(verification.ECHAPPEMENT_CELCAT, "on")
    constats = _controle(tmp_path)
    assert constats[0]["severite"] == "alerte" and not verification.est_bloquant(constats[0])


def test_le_solveur_recoit_les_occupations_celcat_du_semestre_pair(releve):
    """Mardi 2 février 2027, 8h-9h30, salle B.101 et enseignant XYZ pris
    ailleurs : la salle est réservée au créneau relatif du S2 et l'enseignant
    reçoit une indisponibilité datée (mêmes fonctions que `cal-iut solve`)."""
    from pathlib import Path
    from types import SimpleNamespace

    from cal_iut.ingestion.constraints_loader import load_all_constraints

    _ecrire(releve, evenements=[
        {"type": "salle", "code": "B.101", "date": "2027-02-02", "debut": "08:00", "fin": "09:30", "departement": "TC"},
        {"type": "enseignant", "code": "XYZ", "date": "2027-02-02", "debut": "08:00", "fin": "09:30", "departement": "GEA"},
    ])
    cal = load_all_constraints(Path(__file__).resolve().parents[1]).calendar
    reservees = ext.reservations_effectives(SimpleNamespace(calendar=cal, room_reservations={}), "S2")
    cles = [k for k in reservees if k.lower() == "b.101"]
    assert cles and 0 * 42 + 1 * 6 + 0 in reservees[cles[0]]  # semaine 0 du S2, mardi, créneau 0
    dispos = ext.disponibilites_avec_externes(None, [])
    xyz = next(d for d in dispos if d.teacher_code == "XYZ")
    assert xyz.forbidden_date_slots[0].date == "2027-02-02" and xyz.forbidden_date_slots[0].slots == [0]
