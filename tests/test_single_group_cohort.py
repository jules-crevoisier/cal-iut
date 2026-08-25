"""
Cohortes à groupe unique (1 TD + 1 TP déclarés en maquette : BUT2-CREACOM-FC,
BUT3-CREACOM-FC, BUT3-DEV-FC) — retour utilisateur (07/08/2026) : "en FC 2e
année il faut considérer tous les cours comme des TD car c'est un même
groupe, pareil pour les 3e année créacom" (+ confirmé pour BUT3-DEV-FC).
Cf. `ingestion/normalize.py::expand_course_to_sessions`.
"""

import json
from pathlib import Path

import pytest

from cal_iut.ingestion.config_loader import load_groups
from cal_iut.ingestion.merge import merge_exports
from cal_iut.ingestion.normalize import expand_all_sessions
from cal_iut.models.entities import SessionType
from cal_iut.models.session import SessionToPlace

ROOT = Path(__file__).resolve().parents[1]
# Exports officiels figés par `scripts/build_contraintes.py` — même copie que
# celle dont tous les `contraintes/*.json` sont dérivés (`ingestion/fetch.py`
# la préfère aussi). `data/exports/` est gitignoré : les tests ne peuvent pas
# en dépendre.
FIXTURES = ROOT / "contraintes"
CONFIG = ROOT / "data" / "config"

SINGLE_GROUP_PARCOURS = ("BUT2-CREACOM-FC", "BUT3-CREACOM-FC", "BUT3-DEV-FC")


@pytest.fixture(scope="module")
def all_sessions() -> list[SessionToPlace]:
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((FIXTURES / "progression.json").read_text(encoding="utf-8"))
    courses = merge_exports(maquette, progression)
    return expand_all_sessions(courses, load_groups(CONFIG))


@pytest.mark.parametrize("parcours", SINGLE_GROUP_PARCOURS)
def test_single_group_parcours_emits_only_td(all_sessions: list[SessionToPlace], parcours: str) -> None:
    """Aucune séance de type TP : le groupe ne se scinde jamais."""
    sessions = [s for s in all_sessions if s.parcours == parcours]
    assert sessions, f"aucune séance pour {parcours}"
    assert not [s for s in sessions if s.session_type == SessionType.TP]


@pytest.mark.parametrize("parcours", SINGLE_GROUP_PARCOURS)
def test_single_group_parcours_uses_one_group(all_sessions: list[SessionToPlace], parcours: str) -> None:
    """Toutes les séances (hors CM) visent le MÊME identifiant de groupe —
    avant ce correctif, les mêmes étudiants apparaissaient sous deux entrées
    distinctes (groupe TD et groupe TP) dans l'interface."""
    groups = {
        gid
        for s in all_sessions
        if s.parcours == parcours and s.session_type != SessionType.CM
        for gid in s.group_ids
    }
    assert len(groups) == 1, f"{parcours} devrait n'utiliser qu'un seul groupe, trouvé {sorted(groups)}"


@pytest.mark.parametrize("parcours", SINGLE_GROUP_PARCOURS)
def test_single_group_conversion_preserves_session_count(
    all_sessions: list[SessionToPlace], parcours: str
) -> None:
    """La conversion TP -> TD ne doit RIEN perdre : le volume total de la
    maquette reste intégralement planifié (seul le type/groupe change)."""
    maquette = json.loads((FIXTURES / "maquette.json").read_text(encoding="utf-8"))
    expected = sum(
        x["total"]["cm"] + x["total"]["td"] + x["total"]["tp"]
        for x in maquette
        if x["parcours"] == parcours and x["semestre"] in ("S5", "S3")
    )
    actual = len([s for s in all_sessions if s.parcours == parcours and s.semestre in ("S5", "S3")])
    assert actual == expected


def test_split_parcours_keep_their_tp(all_sessions: list[SessionToPlace]) -> None:
    """Contrôle négatif : les parcours qui se scindent réellement gardent
    bien leurs TP (sinon le test ci-dessus ne prouverait rien)."""
    for parcours in ("BUT1", "BUT2-DEV-FI", "BUT3-DEV-FI"):
        tp = [s for s in all_sessions if s.parcours == parcours and s.session_type == SessionType.TP]
        assert tp, f"{parcours} doit conserver des séances TP"


def test_but3_dev_fi_follows_maquette_one_td_two_tp(all_sessions: list[SessionToPlace]) -> None:
    """Retour utilisateur : "le TD CD en 3e année FI n'a pas de cours" puis
    "suis la maquette" — BUT3-DEV-FI y déclare 1 TD + 2 TP. Aucun groupe
    orphelin ne doit subsister."""
    sessions = [s for s in all_sessions if s.parcours == "BUT3-DEV-FI"]
    td_groups = {g for s in sessions if s.session_type == SessionType.TD for g in s.group_ids}
    tp_groups = {g for s in sessions if s.session_type == SessionType.TP for g in s.group_ids}
    assert len(td_groups) == 1, sorted(td_groups)
    assert len(tp_groups) == 2, sorted(tp_groups)

    configured = {g.id for g in load_groups(CONFIG) if g.parcours == "BUT3-DEV-FI" and g.kind != "promo"}
    assert configured == td_groups | tp_groups, "groupes configurés mais jamais utilisés"
