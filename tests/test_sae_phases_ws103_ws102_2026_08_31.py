"""WS103 (BUT1, resp. GLE) et WS102 (BUT1, resp. AFR) — Ariane Loizon (ALO).

Retour utilisateur du 31/08/2026 (relais Kyllian Bresson, message 13h20) : 7
séances WRA505C-S5-TD à déplacer. Le seul créneau libre trouvé sur 4 des
dates visées (23-27 nov. et 4-8 janv.) était bloqué par le mécanisme par
défaut de `sae_supervisor_dates_by_teacher` — ALO listée sur WS103 et WS102
sans jamais avoir de phase déclarée, donc considérée indisponible sur TOUTE
la fenêtre de ces deux SAE. Aucune confirmation de son planning réel n'a été
obtenue pour ces deux-là (contrairement à WS501D, où elle avait donné son
découpage) ; l'utilisateur a explicitement tranché : « c'est pas grave, on
peut mettre des cours pendant les SAE » (31/08/2026).

Ce test vérifie que `data/config/sae_teacher_phases.yaml` libère UNIQUEMENT
les 4 jours ciblés (26-27 nov., 7-8 janv.) et laisse le reste de la fenêtre
de chaque SAE bloqué — pas de libération par excès.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from cal_iut.ingestion.planning_loader import (
    load_mmi_planning_for_semestres,
    sae_supervisor_dates_by_teacher,
)

ROOT = Path(__file__).resolve().parents[1]


def _alo_dates() -> set[date]:
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    return sae_supervisor_dates_by_teacher(bundle)["ALO"]


def test_alo_liberee_sur_les_4_jours_demandes():
    dates = _alo_dates()
    for iso in ("2026-11-26", "2026-11-27", "2027-01-07", "2027-01-08"):
        assert date.fromisoformat(iso) not in dates, f"{iso} devrait être libéré"


def test_alo_reste_bloquee_le_reste_de_la_fenetre_ws103():
    """23, 24 et 25 novembre restent bloqués : seuls les 2 derniers jours de
    la fenêtre WS103 (26-27 nov.) ont été explicitement demandés."""
    dates = _alo_dates()
    for iso in ("2026-11-23", "2026-11-24", "2026-11-25"):
        assert date.fromisoformat(iso) in dates, f"{iso} ne devrait pas être libéré"


def test_alo_reste_bloquee_le_reste_de_la_fenetre_ws102():
    """4, 5 et 6 janvier restent bloqués : seuls les 2 derniers jours de la
    fenêtre WS102 (7-8 janv.) ont été explicitement demandés."""
    dates = _alo_dates()
    for iso in ("2027-01-04", "2027-01-05", "2027-01-06"):
        assert date.fromisoformat(iso) in dates, f"{iso} ne devrait pas être libéré"
