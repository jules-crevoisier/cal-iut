"""Blocs DIFFÉRENTS dans la maquette = partage du CONTENU, pas des groupes.

Signalement du 22/09/2026 (Kyllian Bresson) : « la répartition par block a
été zappée ? Exemple sur le WR117, Joan a le block 1 et [l'autre] le 2. On doit
voir tous les groupes car on ne fait pas la même [chose]. Actuellement je ne
vois que EF et GH. »

Données réelles (`contraintes/maquette.json`) : WR117, WR311D et WR312D ont
leurs enseignants sur `block1` / `block2`. Les 57 autres cours à plusieurs
enseignants sont tous sur `block1` : pour eux, partager les groupes reste juste.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pytest

from cal_iut.ingestion.pipeline import run_ingestion

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


@lru_cache(maxsize=1)
def _seances():
    """Ingestion SANS l'exception du semestre impair 2026-2027 (`mode:
    par_groupes`) : c'est la règle telle qu'elle vaudra à partir du S2."""
    from cal_iut.ingestion import pipeline

    regles = [r for r in pipeline.load_teacher_distributions(CONFIG) if r.mode != "par_groupes"]
    original = pipeline.load_teacher_distributions
    pipeline.load_teacher_distributions = lambda _config_dir: regles
    try:
        return run_ingestion(CONFIG, semestre_group="odd").sessions
    finally:
        pipeline.load_teacher_distributions = original


@lru_cache(maxsize=1)
def _seances_reelles():
    return run_ingestion(CONFIG, semestre_group="odd").sessions


def _repartition(cours: str) -> dict[tuple[str, str], Counter]:
    par_groupe: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for s in _seances():
        if s.course_code == cours and s.session_type.value in ("TD", "TP"):
            par_groupe[(s.session_type.value, s.group_ids[0])][",".join(s.teacher_codes)] += s.duration_slots or 1
    return par_groupe


@pytest.mark.parametrize(
    ("cours", "attendu_td", "attendu_tp"),
    [
        ("WR117", {"JLE": 2, "RDE": 2}, {"JLE": 2, "RDE": 2}),
        ("WR311D", {"KBR": 3, "OLA": 3}, {"KBR": 5, "OLA": 5}),
        ("WR312D", {"AHA": 3, "JBA": 2}, {"AHA": 7, "JBA": 7}),
    ],
)
def test_chaque_enseignant_voit_tous_les_groupes(cours, attendu_td, attendu_tp) -> None:
    repartition = _repartition(cours)
    assert repartition, f"{cours} absent de l'ingestion"
    for (type_, groupe), compte in repartition.items():
        attendu = attendu_td if type_ == "TD" else attendu_tp
        assert dict(compte) == attendu, f"{cours} {type_} {groupe} : {dict(compte)}"


def test_le_bloc_1_passe_avant_le_bloc_2() -> None:
    """Le bloc 1 est la première partie du cours : ses séances précèdent."""
    for s in _seances():
        if s.course_code == "WR117" and s.session_type.value == "TD" and s.group_ids == ["but1-td-ab"]:
            attendu = "JLE" if s.sequence_order <= 3 else "RDE"
            assert s.teacher_codes == [attendu], (s.id, s.sequence_order, s.teacher_codes)


def test_un_meme_bloc_partage_toujours_les_groupes() -> None:
    """WR112 : quatre enseignants, tous `block1` — un sous-groupe chacun."""
    for compte in _repartition("WR112").values():
        assert len(compte) == 1, dict(compte)


def test_le_semestre_impair_2026_2027_reste_tel_quel(monkeypatch) -> None:
    """Décision du 22/09/2026 : « on laisse le S1 tel quel, la règle ne
    s'applique qu'à partir du S2 » — exception déclarée en `mode:
    par_groupes` dans `course_scheduling_rules.yaml`. Contrat : EXACTEMENT
    la répartition d'avant la règle, séance par séance."""
    from cal_iut.ingestion import normalize

    reelles = {s.id: s.teacher_codes for s in _seances_reelles()}
    monkeypatch.setattr(normalize, "_partage_du_contenu", lambda *a, **k: None)
    avant = {s.id: s.teacher_codes for s in run_ingestion(CONFIG, semestre_group="odd").sessions}
    assert reelles == avant
