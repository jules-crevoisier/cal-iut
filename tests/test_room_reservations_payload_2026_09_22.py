"""Les réservations de salles par des tiers atteignent l'écran.

Vue « Salles libres » (todo département, 22/09/2026) : sans elles, l'amphi
pris par la Direction (`salles_reservees.yaml`) apparaissait « libre ».
"""

from __future__ import annotations

from pathlib import Path

from cal_iut.ingestion.config_loader import load_room_reservation_entries

CONFIG = Path(__file__).resolve().parents[1] / "data" / "config"


def test_les_reservations_declarees_sont_lues_telles_quelles() -> None:
    entrees = load_room_reservation_entries(CONFIG)
    assert {"salle": "h018", "date": "2026-09-11", "slots": [1, 2]}.items() <= next(
        e for e in entrees if e["salle"] == "h018" and e["date"] == "2026-09-11"
    ).items()


def test_une_ligne_incomplete_est_ignoree(tmp_path) -> None:
    (tmp_path / "salles_reservees.yaml").write_text(
        "reservations:\n"
        "  - salle: h018\n"
        "  - salle: h101\n"
        "    date: '2026-10-01'\n"
        "    slots: [0, 9]\n",
        encoding="utf-8",
    )
    assert load_room_reservation_entries(tmp_path) == [
        {"salle": "h101", "date": "2026-10-01", "slots": [0], "motif": ""}
    ]


def test_sans_fichier_aucune_reservation(tmp_path) -> None:
    assert load_room_reservation_entries(tmp_path) == []
