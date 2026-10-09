"""Nouvelles indisponibilités de David Annebicque (DAN), tâche #13.

Demande du 06/10/2026 (Kyllian Bresson) : ajouter, SANS rien retirer de ses
contraintes existantes :

    jeudi 15/10/2026 et vendredi 16/10/2026 : à partir de 11h00 ;
    jeudi 22, vendredi 23 octobre, mercredi 2 et jeudi 3 décembre 2026 :
    toute la journée.

Le générateur ne doit pas y placer de séance ; le placement manuel doit
signaler le conflit.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from cal_iut.api.main import _conflits_deplacement
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
from cal_iut.ingestion.config_loader import load_teacher_availability
from cal_iut.ingestion.constraints_loader import load_all_constraints, merge_teacher_availability

RACINE = Path(__file__).resolve().parents[1]
CONFIG = RACINE / "data" / "config"

TOUTE_LA_JOURNEE = [0, 1, 2, 3, 4, 5]
DES_11H = [2, 3, 4, 5]
ATTENDU = {
    "2026-10-15": DES_11H,
    "2026-10-16": DES_11H,
    "2026-10-22": TOUTE_LA_JOURNEE,
    "2026-10-23": TOUTE_LA_JOURNEE,
    "2026-12-02": TOUTE_LA_JOURNEE,
    "2026-12-03": TOUTE_LA_JOURNEE,
}


def _dan_fusionne():
    bundle = load_all_constraints(RACINE)
    fusion = merge_teacher_availability(load_teacher_availability(CONFIG), bundle.teachers)
    officiel = next(t for t in bundle.teachers if t.teacher_code == "DAN")
    return next(t for t in fusion if t.teacher_code == "DAN"), officiel


def test_les_six_dates_sont_declarees() -> None:
    dan, _ = _dan_fusionne()
    regles = {r.date: sorted(r.slots) for r in dan.forbidden_date_slots}
    assert regles == ATTENDU
    assert not any(r.stricte for r in dan.forbidden_date_slots)


def test_les_contraintes_existantes_sont_conservees() -> None:
    dan, officiel = _dan_fusionne()
    assert officiel.forbidden_slots, "la feuille officielle doit déclarer ses créneaux récurrents"
    assert set(officiel.forbidden_slots) <= set(dan.forbidden_slots)
    dates_officielles = officiel.metadata["forbidden_dates"]
    assert "2026-11-05" in dates_officielles
    assert dan.metadata["forbidden_dates"] == dates_officielles


def _semaine_jour(calendrier, semestre: str, cible: date) -> tuple[int, int]:
    decalage = semester_week_offset(calendrier, semestre)
    for w in range(60):
        for j in range(5):
            if calendrier.week_day_to_date(decalage + w, j) == cible:
                return w, j
    raise AssertionError(f"{cible} introuvable dans le calendrier ({semestre})")


@pytest.fixture
def etat(monkeypatch):
    state = get_state()
    ancien = (state.calendar, state.teacher_availability)
    state.calendar = build_default_calendar_2026_2027()
    state.teacher_availability = [_dan_fusionne()[0]]
    # `_hard_constraint_context` lit la maquette : neutralisé, seul l'enseignant compte ici.
    monkeypatch.setattr("cal_iut.api.main._hard_constraint_context", lambda s, x: (set(), set(), None))
    yield state
    state.calendar, state.teacher_availability = ancien


def _conflits(state, jour_iso: str, slot: int):
    seance = SimpleNamespace(semestre="S1", teacher_codes=["DAN"], metadata={})
    w, j = _semaine_jour(state.calendar, "S1", date.fromisoformat(jour_iso))
    return _conflits_deplacement(state, seance, w, j, slot)


@pytest.mark.parametrize("jour_iso", sorted(ATTENDU))
def test_placement_manuel_signale_le_conflit(etat, jour_iso: str) -> None:
    for slot in ATTENDU[jour_iso]:
        bloquants, forcables = _conflits(etat, jour_iso, slot)
        assert not bloquants
        assert any("DAN" in m and "indisponible" in m for m in forcables), (jour_iso, slot, forcables)


def test_le_matin_du_15_octobre_reste_libre(etat) -> None:
    """« À partir de 11h00 » : 8h00 et 9h30 restent plaçables (le jeudi n'a pas
    d'autre indisponibilité récurrente pour DAN)."""
    for slot in (0, 1):
        bloquants, forcables = _conflits(etat, "2026-10-15", slot)
        assert not bloquants and not forcables, (slot, forcables)
