"""Affiche un relevé de formulaire Celcat de façon lisible.

`releve.json` fait des dizaines de milliers de caractères — la quasi-totalité
étant la grille horaire et la liste de gauche, sans intérêt ici. Ce script
n'en montre que le panneau de l'inspecteur (en bas à droite), là où sont les
libellés qu'on cherche, avec leurs coordonnées.

    python scripts/lire_releve_celcat.py data/releves/celcat-formulaire-<...>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# L'inspecteur occupe le quart inférieur droit de la fenêtre 1920×1080.
PANNEAU_X = 480
PANNEAU_Y = 320


def _afficher(titre: str, etat: dict) -> None:
    print(f"\n{'=' * 70}\n{titre}\n{'=' * 70}")
    textes = [
        f for f in etat.get("textes", [])
        if f["y"] > PANNEAU_Y and f["x"] > PANNEAU_X
    ]
    print(f"\n-- textes du panneau ({len(textes)})")
    for f in sorted(textes, key=lambda f: (f["y"], f["x"])):
        print(f"   y={f['y']:<5} x={f['x']:<5} {f['texte'][:78]}")

    champs = [
        c for c in etat.get("champs", [])
        if c["y"] > PANNEAU_Y and c["x"] > PANNEAU_X
    ]
    print(f"\n-- champs de saisie du panneau ({len(champs)})")
    for c in sorted(champs, key=lambda c: (c["y"], c["x"])):
        print(f"   y={c['y']:<5} x={c['x']:<5} type={c['type']}")

    icones = etat.get("icones", {})
    presentes = {nom: len(v) for nom, v in icones.items() if v}
    print(f"\n-- icônes de barre présentes : {presentes or 'aucune'}")
    for nom, liste in icones.items():
        for i in liste:
            print(f"   {nom:<12} x={i['x']:<5} y={i['y']:<5}")


def principal() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    dossier = Path(sys.argv[1])
    releve = json.loads((dossier / "releve.json").read_text(encoding="utf-8"))

    print(f"Relevé du {releve['quand']} — base {releve['base']}, rôle {releve['role']}")
    print(f"Groupe : {releve['groupe']}")
    print(f"Inspecteur ouvert : {releve.get('inspecteur_ouvert')}")
    for tentative in releve.get("tentatives_inspecteur", []):
        print(f"  double-clic en {tentative['position']} -> onglets {tentative['onglets_vus']}")
    if releve.get("erreur"):
        print(f"Erreur : {releve['erreur']}")

    if "emploi_du_temps" in releve:
        _afficher("EMPLOI DU TEMPS (avant ouverture de l'inspecteur)", releve["emploi_du_temps"])
    for nom, etat in releve.get("onglets", {}).items():
        if etat.get("absent"):
            print(f"\n== onglet « {nom} » : ABSENT de l'écran")
            continue
        _afficher(f"ONGLET « {nom} »", etat)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
