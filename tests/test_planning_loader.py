"""Tests parser Plannings MMI + mapping SAE."""

from pathlib import Path

from cal_iut.ingestion.planning_loader import (
    load_mmi_planning,
    load_mmi_planning_for_semestres,
    sae_token_to_course_codes,
)

ROOT = Path(__file__).resolve().parents[1]


def test_sae_token_mapping() -> None:
    assert "WS103" in sae_token_to_course_codes("103")
    assert "WS101" in sae_token_to_course_codes("101")


def test_sae_token_mapping_uses_sheet_convention() -> None:
    """Le suffixe du token lui-même n'est jamais fiable (ex. la feuille
    CREACOM-FC écrit "301C" alors que le vrai code utilise "M" au niveau
    BUT2) — seule la convention de la feuille d'origine (`code_template`)
    détermine le code réel produit."""
    assert sae_token_to_course_codes("301D", code_template="WS{num}D") == ["WS301D"]
    assert sae_token_to_course_codes("301D", code_template="WSA{num}D") == ["WSA301D"]
    assert sae_token_to_course_codes("301C", code_template="WSA{num}M") == ["WSA301M"]


def test_sae_token_mapping_compound_slash() -> None:
    """Bug corrigé : "SAE105/106" était tronqué à "105", perdant WS106 —
    le xlsx réel contient bien le texte complet "SAE105/106" dans ses cellules."""
    codes = sae_token_to_course_codes("105/106")
    assert "WS105" in codes
    assert "WS106" in codes


def test_load_s1_planning_has_sae_windows() -> None:
    bundle = load_mmi_planning(ROOT, "S1")
    assert bundle.sae_windows, bundle.notes
    labels = {w.label for w in bundle.sae_windows}
    assert any(label.startswith("SAE10") for label in labels)
    ws103 = next((w for w in bundle.sae_windows if "WS103" in w.course_codes), None)
    assert ws103 is not None
    assert len(ws103.dates) >= 3


def test_load_s1_planning_finds_ws105_and_ws106() -> None:
    """Régression : avant le correctif du parseur, WS105/WS106 étaient absents
    du résultat alors que le xlsx contient bien "SAE105/106" dans ses cellules."""
    bundle = load_mmi_planning(ROOT, "S1")
    ws105 = next((w for w in bundle.sae_windows if "WS105" in w.course_codes), None)
    ws106 = next((w for w in bundle.sae_windows if "WS106" in w.course_codes), None)
    assert ws105 is not None
    assert ws106 is not None
    assert len(ws105.dates) >= 3
    assert len(ws106.dates) >= 3


def test_load_s5_planning_protects_fi_with_its_own_code() -> None:
    """Bug réel corrigé (06/08/2026) : le vrai code de séance SAE de
    BUT3-DEV-FI est "WS501D" (sans "A"), mais l'ancienne heuristique ne
    produisait que "WSA501D" — aucune fenêtre SAE ne matchait donc jamais
    les séances FI réelles, qui n'étaient JAMAIS sanctuarisées."""
    bundle = load_mmi_planning(ROOT, "S5")
    ws501d = next((w for w in bundle.sae_windows if "WS501D" in w.course_codes), None)
    assert ws501d is not None
    assert len(ws501d.dates) >= 3


def test_load_s5_planning_separates_fc_from_fi_dates() -> None:
    """Bug réel corrigé (06/08/2026, retour utilisateur : "il faut faire
    attention [aux semaines de SAE] pour les alternants") : les parcours FC
    (DEV-FC / CREACOM-FC) ont leur propre feuille de planning avec leurs
    propres dates de SAE, distinctes de celles de la piste FI — avant ce
    correctif, la seule feuille FI était lue pour tout le monde, et les
    codes FC (WSA501D/WSA501C n'existant qu'à S6 sous SAE601) héritaient
    par coïncidence des dates FI (SAE501D, oct-nov 2026) au lieu des
    leurs (SAE601D/601C, fin mars 2027)."""
    bundle = load_mmi_planning(ROOT, "S5")
    ws501d = next(w for w in bundle.sae_windows if "WS501D" in w.course_codes)
    wsa601d = next((w for w in bundle.sae_windows if "WSA601D" in w.course_codes), None)
    wsa601c = next((w for w in bundle.sae_windows if "WSA601C" in w.course_codes), None)
    assert wsa601d is not None
    assert wsa601c is not None
    # Fenêtres FI (fin 2026 / début janvier) et FC (fin mars 2027) réellement
    # disjointes, pas juste des libellés différents pour les mêmes dates.
    assert max(ws501d.dates) < min(wsa601d.dates)
    assert max(ws501d.dates) < min(wsa601c.dates)


def test_load_s3_planning_gives_creacom_fc_its_but2_suffix() -> None:
    """Bug réel corrigé : la feuille CREACOM-FC écrit "SAE301C" mais le vrai
    code de séance au niveau BUT2 utilise le suffixe "M" (héritage "MMI"),
    pas "C" — vérifié sur `data/generated/sessions.json` (WSA301M réel)."""
    bundle = load_mmi_planning(ROOT, "S3")
    wsa301m = next((w for w in bundle.sae_windows if "WSA301M" in w.course_codes), None)
    assert wsa301m is not None


def test_load_for_semestres_merges_but2_but3_missed_by_anchor_alone() -> None:
    """
    Bug réel corrigé (07/08/2026, retour utilisateur : "il n'y avait pas des
    séances obligatoires pour 2e/3e année à propos de leur rentrée ?
    vérifie") : un run multi-parcours (Groupe A) appelait
    `load_mmi_planning(root, "S1")` avec le seul semestre ANCRE du groupe —
    BUT2 (S3) et BUT3 (S5) n'avaient donc JAMAIS leurs propres fenêtres SAE
    ni leurs propres événements chargés. `load_mmi_planning_for_semestres`
    doit couvrir les 3 semestres réels à la fois.
    """
    anchor_only = load_mmi_planning(ROOT, "S1")
    anchor_codes = {c for w in anchor_only.sae_windows for c in w.course_codes}
    assert not any(c.startswith(("WS3", "WS5", "WSA3", "WSA5")) for c in anchor_codes), (
        "l'ancre S1 seule ne doit voir aucun code SAE de BUT2/BUT3 (sinon ce test de "
        "régression ne prouve plus rien face au bug d'origine)"
    )

    merged = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    merged_codes = {c for w in merged.sae_windows for c in w.course_codes}
    assert "WS301D" in merged_codes  # BUT2-DEV-FI (S3)
    assert "WS501D" in merged_codes  # BUT3-DEV-FI (S5)
    assert "WSA301M" in merged_codes  # BUT2-CREACOM-FC (S3)


def test_load_for_semestres_merges_events_across_semestres() -> None:
    """Les événements "Rentrée" de BUT2 (S3) et BUT3 (S5), sur leur propre
    feuille, doivent être présents après fusion — absents avec l'ancre seule."""
    from datetime import date

    anchor_only = load_mmi_planning(ROOT, "S1")
    merged = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])

    feb1_anchor = anchor_only.events.get(date(2027, 2, 1), [])
    feb1_merged = merged.events.get(date(2027, 2, 1), [])
    assert len(feb1_merged) > len(feb1_anchor), "les rentrées BUT2/BUT3 du 1er février doivent s'ajouter"


def test_sae_token_accepts_raw_course_code_notation() -> None:
    """
    Bug réel corrigé (07/08/2026, retour utilisateur : "les 3e années n'ont
    pas de SAE... il faut bien que partout il y ait les SAE pour tous les
    groupes") : les feuilles d'alternants écrivent la SAE avec le CODE DE
    COURS brut ("WSA501C"), jamais "SAEnnn" — ces journées n'étaient donc
    jamais reconnues comme des fenêtres SAE.
    """
    from cal_iut.ingestion.planning_loader import _normalize_sae_token

    assert _normalize_sae_token("WSA501C") == "501"
    assert _normalize_sae_token("WSA502D") == "502"
    assert _normalize_sae_token("WSA666") == "666"
    assert _normalize_sae_token("SAE105/106") == "105/106"  # notation historique intacte


def test_sae_token_rejects_non_sae_cells() -> None:
    """Les cellules voisines ne doivent pas être prises pour des SAE : projet
    enseignants (WS5PJ/WSA5PRJ), cours classique, événement horodaté."""
    from cal_iut.ingestion.planning_loader import _normalize_sae_token

    for cell in ("WS5PJ", "WSA5PRJ", "WRA505C - AFR", "Entreprise", "9h30 / 12h30 Echange IA"):
        assert _normalize_sae_token(cell) is None, cell


def test_fc_parcours_have_sae_windows_in_s5() -> None:
    """Les 2 parcours FC de BUT3 doivent avoir de vraies fenêtres SAE sur
    S5 (WSA501C/WSA502C côté CREACOM, WSA502D côté DEV) — aucune avant le
    correctif ci-dessus, alors que leurs feuilles les contenaient bien."""
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    codes = {c for w in bundle.sae_windows for c in w.course_codes}
    assert "WSA501C" in codes
    assert "WSA502C" in codes
    assert "WSA502D" in codes


def test_load_for_semestres_deduplicates_repeated_semestre() -> None:
    """Un même semestre listé 2 fois ne doit pas dupliquer ses fenêtres SAE."""
    once = load_mmi_planning_for_semestres(ROOT, ["S5"])
    twice = load_mmi_planning_for_semestres(ROOT, ["S5", "S5"])
    once_dates = sorted(w.dates for w in once.sae_windows if "WS501D" in w.course_codes)
    twice_dates = sorted(w.dates for w in twice.sae_windows if "WS501D" in w.course_codes)
    assert once_dates == twice_dates
