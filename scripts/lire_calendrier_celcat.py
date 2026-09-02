"""Affiche le relevé du sélecteur de semaines Celcat.

Sert à établir la géométrie des cellules et le format de leurs infobulles —
les deux choses dont `navigateur.choisir_semaine` a besoin, et qu'on ne peut
pas lire dans le DOM : les cellules ne portent aucun texte.

    python scripts/lire_calendrier_celcat.py data/releves/celcat-formulaire-<...>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def principal() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    dossier = Path(sys.argv[1])
    releve = json.loads((dossier / "releve.json").read_text(encoding="utf-8"))
    calendrier = releve.get("calendrier")
    if not calendrier:
        print("Ce relevé ne contient pas de section « calendrier ».", file=sys.stderr)
        return 3

    cellules = calendrier["cellules"]
    avec = [c for c in cellules if c["infobulles"]]
    print(f"{len(cellules)} cellules survolées, {len(avec)} avec infobulle.\n")

    rangees: dict[int, list[dict]] = {}
    for c in avec:
        rangees.setdefault(c["haut"], []).append(c)

    for haut in sorted(rangees):
        ligne = sorted(rangees[haut], key=lambda c: c["gauche"])
        print(f"-- rangée y={haut} ({len(ligne)} cellules)")
        for c in ligne:
            infobulles = " | ".join(c["infobulles"])
            print(f"   x={c['x']:<5} l={c['largeur']:<4} {infobulles}")
        print()

    largeurs = sorted({c["largeur"] for c in avec})
    ecarts = set()
    for ligne in rangees.values():
        tries = sorted(ligne, key=lambda c: c["gauche"])
        for a, b in zip(tries, tries[1:]):
            ecarts.add(b["gauche"] - a["gauche"])
    print(f"largeurs de cellule : {largeurs}")
    print(f"écarts entre cellules : {sorted(ecarts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
