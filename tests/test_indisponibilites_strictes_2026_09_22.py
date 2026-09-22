"""Indisponibilités FORTES de Romain Delon : non forçables.

Demande du 22/09/2026 :

    « Pouvez-vous m'ajouter en contrainte forte les indisponibilités de Romain
      Delon (RDE) : 4, 5 et 6 novembre 2026 ; 2, 3 et 4 décembre 2026 ; 24 et
      25 juin 2027. Il faut que dans l'interface on ne puisse pas placer de
      séances de RDE à ces dates. »

Une indisponibilité enseignant ordinaire se FORCE depuis le 03/09/2026. Les
règles datées `stricte: true` rejoignent au contraire les verrous que `force`
ne lève pas.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_forcer_semaine_en_cours_2026_09_21 import _creer  # type: ignore[import-not-found]
from test_placement_manuel import (
    client,  # type: ignore[import-not-found]  # noqa: F401 — fixture réutilisée
)

from cal_iut.api.main import _conflits_deplacement
from cal_iut.api.state import get_state
from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset
from cal_iut.ingestion.config_loader import load_teacher_availability
from cal_iut.models.entities import TeacherAvailability, TeacherDateSlotRule

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"

DATES_FORTES = [
    "2026-11-04", "2026-11-05", "2026-11-06",
    "2026-12-02", "2026-12-03", "2026-12-04",
    "2027-06-24", "2027-06-25",
]


def _semaine_jour(calendrier, semestre: str, cible: date) -> tuple[int, int]:
    """Indice de semaine (relatif au semestre) et jour d'une date réelle."""
    decalage = semester_week_offset(calendrier, semestre)
    for w in range(60):
        for j in range(5):
            if calendrier.week_day_to_date(decalage + w, j) == cible:
                return w, j
    raise AssertionError(f"{cible} introuvable dans le calendrier ({semestre})")


@pytest.fixture
def etat():
    state = get_state()
    ancien = (state.calendar, state.teacher_availability)
    state.calendar = build_default_calendar_2026_2027()
    state.teacher_availability = [
        TeacherAvailability(
            teacher_code="RDE",
            forbidden_date_slots=[
                TeacherDateSlotRule(date="2026-11-05", slots=[0, 1, 2, 3, 4, 5], note="forte", stricte=True),
                TeacherDateSlotRule(date="2026-11-12", slots=[0, 1, 2, 3, 4, 5], note="ordinaire"),
            ],
        )
    ]
    yield state
    state.calendar, state.teacher_availability = ancien


def _seance(semestre: str = "S1", profs=("RDE",)):
    return SimpleNamespace(semestre=semestre, teacher_codes=list(profs), metadata={})


def _conflits(state, jour_iso: str, slot: int = 1, **kw):
    seance = _seance(**kw)
    w, j = _semaine_jour(state.calendar, seance.semestre, date.fromisoformat(jour_iso))
    # `_hard_constraint_context` lit la maquette : neutralisé, seul l'enseignant compte ici.
    return _conflits_deplacement(state, seance, w, j, slot)


def test_une_date_forte_est_un_verrou_non_forcable(etat, monkeypatch) -> None:
    monkeypatch.setattr("cal_iut.api.main._hard_constraint_context", lambda s, x: (set(), set(), None))
    bloquants, forcables = _conflits(etat, "2026-11-05")
    assert any("RDE indisponible le 05/11/2026" in m for m in bloquants), bloquants
    assert not any("Forcer" in m for m in forcables), "ne pas proposer de forcer ce qui est refusé"


def test_une_indisponibilite_ordinaire_reste_forcable(etat, monkeypatch) -> None:
    monkeypatch.setattr("cal_iut.api.main._hard_constraint_context", lambda s, x: (set(), set(), None))
    bloquants, forcables = _conflits(etat, "2026-11-12")
    assert not bloquants
    assert any("indisponible" in m for m in forcables)


def test_un_autre_enseignant_n_est_pas_concerne(etat, monkeypatch) -> None:
    monkeypatch.setattr("cal_iut.api.main._hard_constraint_context", lambda s, x: (set(), set(), None))
    bloquants, forcables = _conflits(etat, "2026-11-05", profs=("MRI",))
    assert not bloquants and not forcables


def test_les_huit_dates_de_rde_sont_declarees_fortes() -> None:
    rde = next(t for t in load_teacher_availability(CONFIG) if t.teacher_code == "RDE")
    fortes = {r.date for r in rde.forbidden_date_slots if r.stricte and r.slots == [0, 1, 2, 3, 4, 5]}
    assert fortes == set(DATES_FORTES)


def test_le_drapeau_survit_a_la_fusion_avec_la_feuille_officielle() -> None:
    """`merge_teacher_availability` reconstruit l'objet : RDE est présent des
    deux côtés (feuille officielle + YAML), c'est là qu'un champ se perd."""
    from cal_iut.ingestion.constraints_loader import merge_teacher_availability

    officiel = TeacherAvailability(teacher_code="RDE", forbidden_slots=[(4, 0)])
    yaml_ = [t for t in load_teacher_availability(CONFIG) if t.teacher_code == "RDE"]
    fusion = next(t for t in merge_teacher_availability(yaml_, [officiel]) if t.teacher_code == "RDE")
    assert sum(r.stricte for r in fusion.forbidden_date_slots) == len(DATES_FORTES)


def test_creer_une_seance_de_rde_le_5_novembre_est_refuse_meme_en_forcant(client) -> None:  # noqa: F811
    """Bout en bout, par la route qu'emprunte « Nouvelle séance »."""
    state = get_state()
    state.teacher_availability = [
        next(t for t in load_teacher_availability(CONFIG) if t.teacher_code == "RDE")
    ]
    w, j = _semaine_jour(state.calendar, "S1", date(2026, 11, 5))
    reponse = _creer(client, teacher_codes=["RDE"], week=w, day=j, force=True)

    assert reponse.status_code == 409, reponse.text
    detail = reponse.json()["detail"]
    assert any("RDE indisponible le 05/11/2026" in m for m in detail["blocking_conflicts"]), detail
