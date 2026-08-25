"""Lecture des fenêtres SAE (09) et des événements fixes (10).

Remplace l'ancienne suite qui testait l'inférence de codes SAE depuis les
libellés d'un tableur (`sae_token_to_course_codes`, `_SHEET_CODE_TEMPLATE`) :
la source officielle nomme désormais le module directement, tout ce mécanisme
d'inférence a disparu avec `04_planning_hebdomadaire_par_promo.json`.
"""

from datetime import date
from pathlib import Path

import pytest

from cal_iut.ingestion.planning_loader import (
    ALL_PARCOURS,
    fc_rentree_first_week_by_parcours,
    load_fixed_events,
    load_mmi_planning,
    load_mmi_planning_for_semestres,
    load_sae_windows,
    planning_event_blocked_slots_by_parcours,
    planning_events_as_week_day_slots,
    sae_group_labels_by_course,
    sae_windows_as_week_days,
)

ROOT = Path(__file__).resolve().parents[1]


def _codes(bundle) -> set[str]:
    return {code for w in bundle.sae_windows for code in w.course_codes}


def test_sae_windows_are_filtered_by_semestre():
    s1 = {w.label for w in load_sae_windows(ROOT, ["S1"])}
    s5 = {w.label for w in load_sae_windows(ROOT, ["S5"])}

    assert "WS101" in s1
    assert "WS501D" in s5
    # Aucune fuite d'un semestre vers l'autre : c'était le bug historique de la
    # lecture par « feuille » (une feuille couvrait S1 ET S2).
    assert not s1 & s5


def test_sae_dates_match_the_official_file():
    """WS101 : « mardi 20 octobre 2026 » -> « vendredi 23 octobre 2026 »."""
    window = next(w for w in load_sae_windows(ROOT, ["S1"]) if w.label == "WS101")
    assert window.dates == [
        date(2026, 10, 20),
        date(2026, 10, 21),
        date(2026, 10, 22),
        date(2026, 10, 23),
    ]


def test_sae_windows_skip_weekends():
    """WS501D est daté par paires jeudi/vendredi : aucun samedi/dimanche."""
    window = next(w for w in load_sae_windows(ROOT, ["S5"]) if w.label == "WS501D")
    assert window.dates
    assert all(d.weekday() < 5 for d in window.dates)


def test_sae_without_dates_is_absent():
    """WSA501D a « ??? » comme dates : aucune fenêtre, donc aucun blocage."""
    assert "WSA501D" not in {w.label for w in load_sae_windows(ROOT, ["S5"])}


def test_partial_group_sae_is_flagged():
    """WS502D n'est daté que pour le TD AB (arbitrage utilisateur 10/08/2026)."""
    bundle = load_mmi_planning_for_semestres(ROOT, ["S5"])
    labels = sae_group_labels_by_course(bundle)

    assert labels["WS502D"] == ["AB"]
    # Les SAE qui concernent toute la promotion n'apparaissent pas ici.
    assert "WS501D" not in labels

    window = next(w for w in bundle.sae_windows if w.label == "WS502D")
    assert window.dates == [date(2027, 1, 12), date(2027, 1, 13)]


def test_multi_semestre_merge_covers_every_promotion():
    """Un run S1+S3+S5 doit voir les SAE des trois années, pas seulement l'ancre."""
    anchor_only = _codes(load_mmi_planning(ROOT, "S1"))
    merged = _codes(load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"]))

    assert merged > anchor_only
    assert any(c.startswith(("WS3", "WSA3")) for c in merged)
    assert any(c.startswith(("WS5", "WSA5")) for c in merged)


def test_merge_is_idempotent():
    once = load_mmi_planning_for_semestres(ROOT, ["S5"])
    twice = load_mmi_planning_for_semestres(ROOT, ["S5", "S5"])
    assert len(once.sae_windows) == len(twice.sae_windows)


def test_fixed_events_carry_hours_room_and_parcours():
    events = load_fixed_events(ROOT)
    rentree_but1 = next(
        e for e in events if e.day == date(2026, 9, 2) and e.parcours_keys == ["BUT1"]
    )

    assert rentree_but1.room == "H.018"
    # 9h00-11h00 recouvre le créneau 8h-9h30 (partiellement) et 9h30-11h00.
    assert rentree_but1.slots == [0, 1]


def test_fixed_events_are_scoped_per_parcours():
    """
    Le 2 septembre 2026, trois parcours ont leur rentrée à trois horaires
    différents dans le même amphi. Bloquer globalement (comportement de
    l'ancienne source, qui ne nommait pas le parcours) gèlerait 4 créneaux
    pour tout le monde au lieu de 2 pour chacun.
    """
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])

    class _Cal:
        @staticmethod
        def to_week_day(d):
            return (0, d.weekday()) if d == date(2026, 9, 2) else None

    blocked = planning_event_blocked_slots_by_parcours(bundle, _Cal.to_week_day, 0, 4)

    assert blocked["BUT1"] == {(0, 2, 0), (0, 2, 1)}  # 9h00-11h00
    assert blocked["BUT2-DEV-FI"] == {(0, 2, 3)}  # 14h00-15h30
    assert blocked["BUT3-DEV-FI"] == {(0, 2, 4)}  # 15h30-17h00
    # Aucun événement « tous parcours » ce jour-là.
    assert ALL_PARCOURS not in blocked


def test_fc_rentree_blocks_everything_before_it_not_just_its_own_slot():
    """
    Retour utilisateur 11/08/2026 : « date de rentrée des FC S3 [BUT2-CREACOM-FC] :
    14/09/2026, 9h30 [...] -> pas de cours avant ». Avant ce correctif, seul
    le créneau EXACT de la rentrée (9h30-11h00) était bloqué — rien
    n'empêchait un cours classique le même jour à 8h, ni les jours/semaines
    précédents (contrairement aux parcours FI, qui ont un tampon d'une
    semaine complète via `add_s1_integration_week_lock`, généralisé le même
    jour — mais les parcours FC démarrent à des dates trop étalées pour une
    règle "semaine 3" uniforme, d'où ce blocage au grain exact de LEUR
    rentrée déclarée).
    """
    from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset

    calendar = build_default_calendar_2026_2027()
    week_offset = semester_week_offset(calendar, "S3")
    weeks = 24

    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    blocked = planning_event_blocked_slots_by_parcours(bundle, calendar.date_to_week_day, week_offset, weeks)

    rentree_date = date(2026, 9, 14)
    mapped = calendar.date_to_week_day(rentree_date)
    assert mapped is not None
    rentree_week, rentree_day = mapped[0] - week_offset, mapped[1]

    fc_blocked = blocked["BUT2-CREACOM-FC"]

    # Le matin du jour même de la rentrée (avant 9h30) : bloqué.
    assert (rentree_week, rentree_day, 0) in fc_blocked  # 8h-9h30
    # Une semaine entière avant la rentrée : bloquée.
    assert (rentree_week - 1, 0, 0) in fc_blocked
    # Après la rentrée : un cours classique reste plaçable (le créneau de la
    # rentrée elle-même, lui, reste bloqué — mais par l'AUTRE mécanisme déjà
    # existant, le blocage exact du créneau, pas celui ajouté ici).
    assert (rentree_week, rentree_day, 2) not in fc_blocked  # 11h-12h30, juste après la rentrée
    assert (rentree_week + 1, 0, 0) not in fc_blocked

    # Un parcours FI n'est pas concerné par ce mécanisme précis (il a son
    # propre tampon "semaine 3", cf. `add_s1_integration_week_lock`) — on ne
    # doit pas lui avoir ajouté de blocage "avant rentrée FC" par erreur.
    but1_blocked = blocked.get("BUT1", set())
    assert (rentree_week - 1, 0, 0) not in but1_blocked


def test_fc_rentree_first_week_matches_the_exact_rentree_date():
    """
    Bug réel du 11/08/2026 trouvé en vérifiant le run complet : le blocage
    "avant rentrée" ci-dessus n'était lu QU'à l'étage 3 (`solve_week_detail`),
    jamais à l'étage 2 (`assign_weeks`) — qui pouvait donc assigner à un
    parcours FC une semaine ENTIÈREMENT antérieure à sa rentrée, prouvée
    INFEASIBLE en 0s ensuite (les 30 créneaux de la semaine y sont tous
    bloqués). `fc_rentree_first_week_by_parcours` fournit la borne semaine
    (pas créneau) qu'`assign_weeks` peut appliquer directement. Cf.
    docs/DATA.md §58.
    """
    from cal_iut.calendar.academic import build_default_calendar_2026_2027, semester_week_offset

    calendar = build_default_calendar_2026_2027()
    week_offset = semester_week_offset(calendar, "S3")

    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])
    first_week = fc_rentree_first_week_by_parcours(bundle, calendar.date_to_week_day_any, week_offset)

    rentree_date = date(2026, 9, 14)
    mapped = calendar.date_to_week_day_any(rentree_date)
    assert mapped is not None
    expected_week = mapped[0] - week_offset

    assert first_week["BUT2-CREACOM-FC"] == expected_week
    # BUT3-DEV-FC/CREACOM-FC rentrent le 31/08 — dès la toute première semaine
    # de l'horizon (0), donc aucune borne réellement restrictive.
    assert first_week.get("BUT3-DEV-FC", 0) == 0
    # Un parcours FI n'a pas de rentrée FC déclarée : absent du résultat.
    assert "BUT1" not in first_week


def test_display_slots_match_blocked_slots():
    """L'affichage et le blocage doivent porter sur exactement les mêmes créneaux."""
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1"])

    def to_week_day(d):
        return (0, d.weekday()) if d == date(2026, 9, 8) else None

    blocked = planning_event_blocked_slots_by_parcours(bundle, to_week_day, 0, 4)
    displayed = planning_events_as_week_day_slots(bundle, to_week_day, 0, 4)

    assert {(r["w"], r["d"], r["s"]) for r in displayed} == blocked["BUT1"]


def test_display_rows_carry_the_parcours_for_filtering():
    """
    L'export HTML filtre l'affichage sur le parcours du groupe consulté
    (`eventLabelsAt` dans `templates/timetable.html`) — il lui faut donc la
    même information de portée que le solveur, sinon la rentrée BUT1
    apparaîtrait comme un créneau bloqué chez les BUT2/BUT3.
    """
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1", "S3", "S5"])

    def to_week_day(d):
        return (0, d.weekday()) if d == date(2026, 9, 2) else None

    rows = planning_events_as_week_day_slots(bundle, to_week_day, 0, 4)
    par_parcours = {p: r["s"] for r in rows for p in r["parcours"]}

    assert par_parcours["BUT1"] in (0, 1)
    assert par_parcours["BUT2-DEV-FI"] == 3
    assert par_parcours["BUT3-DEV-FI"] == 4
    assert all(r["room"] for r in rows)


def test_sae_windows_as_week_days_maps_to_solver_grid():
    bundle = load_mmi_planning_for_semestres(ROOT, ["S1"])

    def to_week_day(d):
        return (3, d.weekday()) if d == date(2026, 10, 20) else None

    days = sae_windows_as_week_days(bundle, to_week_day, week_offset=1, weeks=10)
    assert days["WS101"] == {(2, 1)}  # semaine absolue 3 - offset 1, mardi


@pytest.mark.parametrize("semestre", ["S2", "S4", "S6"])
def test_out_of_scope_semestres_have_no_sae_dates(semestre):
    """
    Arbitrage utilisateur du 10/08/2026 : le fichier officiel ne date que les
    SAE de S1/S3/S5. Ce test verrouille l'attente — s'il casse, c'est que des
    dates sont arrivées et que `SEMESTRES_HORS_PERIMETRE` doit être allégé.
    """
    assert load_sae_windows(ROOT, [semestre]) == []
