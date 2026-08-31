"""Trois demandes relayées par Kyllian Bresson le 31/08/2026 (après-midi).

1. Justine Hussenet (JHU), 14h06 : « Ne souhaite plus assurer les CM [...]
   WR303D ; WRA303M ; WRA309M, il faut donc lui supprimer tous ses CM. »
   Vérifié : seul WR303D a des CM à son nom (2 séances) ; WRA303M et
   WRA309M n'ont aucun volume de CM au programme. Décision utilisateur du
   31/08/2026 : supprimées (pas de co-intervenant déclaré à qui les
   réassigner).

2. WS110/WS102 et WS310D/WS301D, 15h37 : « WS110 à débuter en même temps
   que la WS102 [...] WS310D a placer en même que la SAE WS301D. » Aucune
   des deux n'avait de fenêtre déclarée. Décision utilisateur du
   31/08/2026 : fenêtre identique (WS110 = celle de WS102 ; WS310D = la
   1ère des deux fenêtres de WS301D).

3. Julie Bastard (JBA), 14h34 : « peut intervenir uniquement le vendredi
   après-midi ». Absente jusqu'ici de teacher_availability.yaml — d'où ses
   32 séances dispersées sur toute la semaine avant correction.
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.ingestion.config_loader import load_seances_annulees, load_teacher_availability
from cal_iut.ingestion.planning_loader import (
    appliquer_corrections_sae,
    load_sae_corrections,
    load_sae_windows,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"


# --------------------------------------------------------------------------
# 1. Justine Hussenet — CM WR303D annulés
# --------------------------------------------------------------------------


def test_les_2_cm_wr303d_de_jhu_sont_annules():
    annulees = load_seances_annulees(CONFIG)
    assert "WR303D-S3-CM-1" in annulees
    assert "WR303D-S3-CM-2" in annulees


# --------------------------------------------------------------------------
# 2. WS110 / WS310D — fenêtres créées, alignées sur WS102 / WS301D
# --------------------------------------------------------------------------


def _fenetres_appliquees() -> list:
    fenetres = load_sae_windows(ROOT, ["S1", "S3", "S5"])
    ajouts, retraits = load_sae_corrections(CONFIG)
    return appliquer_corrections_sae(fenetres, ajouts, retraits)


def test_ws110_demarre_en_meme_temps_que_ws102():
    fenetres = _fenetres_appliquees()
    ws110 = next(f for f in fenetres if "WS110" in f.course_codes)
    ws102 = next(f for f in fenetres if "WS102" in f.course_codes)
    assert set(ws110.dates) == set(ws102.dates)


def test_ws310d_couvre_la_premiere_fenetre_de_ws301d():
    fenetres = _fenetres_appliquees()
    ws310d = next(f for f in fenetres if "WS310D" in f.course_codes)
    ws301d_dates = sorted({d for f in fenetres if "WS301D" in f.course_codes for d in f.dates})
    premiere_fenetre_ws301d = [d for d in ws301d_dates if d.isoformat() < "2027-01-01"]
    assert set(ws310d.dates) == set(premiere_fenetre_ws301d)


# --------------------------------------------------------------------------
# 3. Julie Bastard — vendredi après-midi uniquement
# --------------------------------------------------------------------------


def test_jba_restreinte_au_vendredi_apres_midi():
    teachers = {t.teacher_code: t for t in load_teacher_availability(CONFIG)}
    jba = teachers["JBA"]
    assert set(jba.allowed_slots) == {(4, 3), (4, 4), (4, 5)}


def test_jba_indisponible_la_semaine_du_12_octobre():
    teachers = {t.teacher_code: t for t in load_teacher_availability(CONFIG)}
    jba = teachers["JBA"]
    regle = next(r for r in jba.forbidden_date_slots if r.date == "2026-10-16")
    assert set(regle.slots) == {3, 4, 5}
