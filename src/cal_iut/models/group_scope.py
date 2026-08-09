"""Résolution du périmètre d'affichage d'un groupe étudiant (TD → TP + CM)."""

from cal_iut.models.entities import Group


def _promo_id(groups: list[Group], parcours: str) -> str | None:
    promo = next((g for g in groups if g.parcours == parcours and g.kind == "promo"), None)
    return promo.id if promo else None


def resolve_tp_ids_for_td(td: Group, groups: list[Group]) -> list[str]:
    """Mappe les clés YAML (A, B, 1…) vers les ids TP du même parcours."""
    tp_groups = [g for g in groups if g.parcours == td.parcours and g.kind == "tp"]
    resolved: list[str] = []

    for key in td.tp_groups:
        key_norm = str(key).strip().lower()
        match = next(
            (
                g
                for g in tp_groups
                if g.id == key_norm
                or g.id.endswith(f"-tp-{key_norm}")
                or g.label.lower() == f"tp {key_norm}"
                or g.label.lower().endswith(f" {key_norm}")
            ),
            None,
        )
        if match and match.id not in resolved:
            resolved.append(match.id)

    return resolved


def parent_td_for_tp(tp: Group, groups: list[Group]) -> Group | None:
    """Retrouve le TD parent d'un groupe TP."""
    for td in groups:
        if td.parcours != tp.parcours or td.kind != "td":
            continue
        if tp.id in resolve_tp_ids_for_td(td, groups):
            return td
    return None


def expand_group_filter(group_id: str, groups: list[Group], *, include_promo: bool = True) -> set[str]:
    """
    Étend un filtre groupe pour l'emploi du temps étudiant.

    - TD AB → TD AB + TP A + TP B + promo (CM)
    - TP A  → TP A + TD parent + promo
    - promo → promo seule
    """
    selected = next((g for g in groups if g.id == group_id), None)
    if selected is None:
        return {group_id}

    ids: set[str] = {selected.id}

    if selected.kind == "td":
        ids.update(resolve_tp_ids_for_td(selected, groups))
    elif selected.kind == "tp":
        parent = parent_td_for_tp(selected, groups)
        if parent:
            ids.add(parent.id)

    if include_promo and selected.kind != "promo":
        promo = _promo_id(groups, selected.parcours)
        if promo:
            ids.add(promo)

    return ids


def related_group_ids(group: Group, groups: list[Group]) -> list[str]:
    """Ids liés exposés dans /meta (sans la promo)."""
    if group.kind == "td":
        return resolve_tp_ids_for_td(group, groups)
    if group.kind == "tp":
        parent = parent_td_for_tp(group, groups)
        return [parent.id] if parent else []
    return []
