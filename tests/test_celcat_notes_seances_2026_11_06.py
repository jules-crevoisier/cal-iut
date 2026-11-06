"""Tâche #30 : report de la note d'une séance dans la « Remarque » Celcat.

Tout est calculé en mémoire (aucune écriture dans un vrai Celcat). Le report
est DÉSACTIVÉ par défaut (`CAL_IUT_NOTES_ENVOI`) ; l'identifiant de la
séance reste le dernier mot du champ, ce qui permet à la mise à jour de
retrouver le même évènement (aucun doublon).
"""

from __future__ import annotations

import pytest
from test_celcat_regles_envoi_2026_10_01 import _cfg  # type: ignore[import-not-found]

from cal_iut.celcat.mapping import entree_pour_placement, session_id_depuis_notes

SID = "WR101-S1-TD-1-but1-td-ab"


def _entree(note=None, *, cours="WR101", type_="TD", sid=SID):
    return entree_pour_placement(
        _cfg(), session_id=sid, course_code=cours, session_type=type_,
        week=2, day=1, slot=4, duration_slots=1, teacher_codes=["VMA"],
        room_id="h101", groupe="TD AB", semestre="S1", lundi="2026-09-14", note=note,
    )


def test_la_note_n_est_pas_reportee_par_defaut(monkeypatch):
    monkeypatch.delenv("CAL_IUT_NOTES_ENVOI", raising=False)
    e = _entree("Rattrapage")
    assert e.notes_celcat == SID
    assert e.signature() == _entree(None).signature()


def test_la_note_est_reportee_devant_l_identifiant_quand_le_drapeau_est_pose(monkeypatch):
    monkeypatch.setenv("CAL_IUT_NOTES_ENVOI", "on")
    e = _entree("Rattrapage du 12/09")
    assert e.notes_celcat == f"Rattrapage du 12/09 - {SID}"
    assert session_id_depuis_notes(e.notes_celcat) == SID


def test_la_note_est_normalisee_en_ascii_sur_une_ligne(monkeypatch):
    monkeypatch.setenv("CAL_IUT_NOTES_ENVOI", "on")
    e = _entree("Salle à confirmer\n  — été")
    assert e.notes_celcat.isascii()
    assert "\n" not in e.notes_celcat
    assert session_id_depuis_notes(e.notes_celcat) == SID


def test_une_note_modifiee_change_la_signature_donc_met_a_jour_sans_doublon(monkeypatch):
    monkeypatch.setenv("CAL_IUT_NOTES_ENVOI", "on")
    avant, apres, effacee = _entree("A"), _entree("B"), _entree("")
    assert avant.signature() != apres.signature()
    assert effacee.signature() == _entree(None).signature() != avant.signature()
    # Même évènement retrouvé par l'identifiant, quelle que soit la note.
    assert {session_id_depuis_notes(e.notes_celcat) for e in (avant, apres, effacee)} == {SID}


def test_la_note_se_combine_avec_la_remarque_d_une_regle(monkeypatch):
    monkeypatch.setenv("CAL_IUT_NOTES_ENVOI", "on")
    monkeypatch.setenv("CAL_IUT_REGLES_ENVOI", "on")
    sid = "WR100BU-S1-TD-1-but1-td-ab"
    e = _entree("Note", cours="WR100BU", sid=sid)
    assert e.notes_celcat == f"WR100BU - Note - {sid}"
    assert session_id_depuis_notes(e.notes_celcat) == sid


def test_la_note_est_tronquee(monkeypatch):
    monkeypatch.setenv("CAL_IUT_NOTES_ENVOI", "on")
    assert len(_entree("x" * 500).note) == 200
