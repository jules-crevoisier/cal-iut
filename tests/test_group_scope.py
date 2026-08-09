"""Tests du périmètre d'affichage TD → TP + CM."""

from pathlib import Path

from cal_iut.ingestion.config_loader import load_groups
from cal_iut.models.group_scope import expand_group_filter, resolve_tp_ids_for_td

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


def test_td_ab_resolves_tp_a_and_b() -> None:
    groups = load_groups(CONFIG)
    td = next(g for g in groups if g.id == "but1-td-ab")
    assert resolve_tp_ids_for_td(td, groups) == ["but1-tp-a", "but1-tp-b"]


def test_expand_td_includes_tp_and_promo() -> None:
    groups = load_groups(CONFIG)
    scope = expand_group_filter("but1-td-ab", groups)
    assert scope == {"but1-td-ab", "but1-tp-a", "but1-tp-b", "but1-promo"}


def test_expand_tp_includes_parent_td_and_promo() -> None:
    groups = load_groups(CONFIG)
    scope = expand_group_filter("but1-tp-a", groups)
    assert "but1-tp-a" in scope
    assert "but1-td-ab" in scope
    assert "but1-promo" in scope


def test_but2_dev_fi_td_ab_resolves_tp_a_and_b() -> None:
    groups = load_groups(CONFIG)
    td = next(g for g in groups if g.id == "but2-dev-fi-td-ab")
    assert resolve_tp_ids_for_td(td, groups) == ["but2-dev-fi-tp-a", "but2-dev-fi-tp-b"]


def test_but2_dev_fi_has_promo_group() -> None:
    groups = load_groups(CONFIG)
    assert any(g.kind == "promo" and g.parcours == "BUT2-DEV-FI" for g in groups)
