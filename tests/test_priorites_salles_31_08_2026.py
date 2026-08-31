"""Priorités de salle demandées le 31/08/2026 (verbatim) :

« on veut prioriser la 205 pour le game dev donc wra507d et wsa501d, et
pour tous les cours de guillaume leulier on veut en prio la h009 »

H.205 (`tp_vr_reseaux`) et H.009 (`td_design`) sont chacune la SEULE salle
de leur type : prioriser le type revient à prioriser la salle, sans avoir
besoin d'un mécanisme de préférence par identifiant de salle.
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.ingestion.config_loader import load_room_assignment_rules
from cal_iut.models.entities import RoomType
from cal_iut.solver.rooms import _find_matching_rule, parse_room_rules

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config"
RULES = parse_room_rules(load_room_assignment_rules(CONFIG))


def test_wra507d_priorise_h205():
    rule = _find_matching_rule(RULES, "WRA507D", "TD")
    assert rule.preferred_room_types[0] == RoomType.TP_VR_RESEAUX


def test_wsa501d_priorise_h205():
    rule = _find_matching_rule(RULES, "WSA501D", "TD")
    assert rule.preferred_room_types[0] == RoomType.TP_VR_RESEAUX


def test_le_reste_du_groupe_wra50xd_n_est_pas_touche():
    """WRA502D (même famille de règle d'origine) garde tp_standard/standard en
    tête — seuls WRA507D et WSA501D basculent vers H.205."""
    rule = _find_matching_rule(RULES, "WRA502D", "TD")
    assert rule.preferred_room_types[0] in (RoomType.TP_STANDARD, RoomType.STANDARD)


def test_cours_de_gle_priorisent_h009():
    for code in ("WR310D", "WRA406M", "WRA506C", "WRA602C", "WSA401M"):
        rule = _find_matching_rule(RULES, code, "TD")
        assert rule.preferred_room_types[0] == RoomType.TD_DESIGN, code


def test_projets_partages_ou_gle_n_est_qu_un_co_enseignant_parmi_d_autres_sont_exclus():
    """WS3PJ/WSA411M etc. listent GLE avec 10+ autres enseignants : ce ne
    sont pas « ses » cours, la règle ne doit pas les toucher."""
    rule = _find_matching_rule(RULES, "WS3PJ", "TD")
    assert rule is None or rule.preferred_room_types[0] != RoomType.TD_DESIGN
