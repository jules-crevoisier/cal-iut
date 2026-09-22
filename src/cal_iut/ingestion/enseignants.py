"""Tous les enseignants connus — pas seulement ceux qui ont déjà une séance.

Demande du 22/09/2026, relayée par Jules Crevoisier :

    « Pour l'instant le plus urgent est de me créer Marc Nino qui intervient
      jeudi & vendredi. »

Marc Nino n'avait pourtant rien à créer : il figure dans la feuille officielle
des contraintes enseignants (disponibilités exclusives le jeudi 24 et le
vendredi 25 septembre, entre autres), et son code Celcat est déjà dans
`celcat.yaml`. Ce qui lui manquait, c'était de POUVOIR ÊTRE CHOISI.

La liste proposée par « Nouvelle séance » (`teacherLabels`, cf.
`export/html_view.py::build_payload`) se construisait sur les séances DÉJÀ
PLACÉES. Un vacataire qui n'enseigne encore rien n'y apparaissait donc pas —
et on ne pouvait pas lui créer sa première séance, précisément parce qu'il
n'en avait aucune.

Ce module rend la liste des enseignants DÉCLARÉS, quelle que soit leur
activité, depuis deux sources :

1. `contraintes/05_enseignants_contraintes.json`, généré depuis la feuille
   officielle — la référence ;
2. `data/config/enseignants_supplementaires.yaml`, pour les enseignants que
   cette feuille ne connaît pas encore (arrivée en cours d'année). Tenu à la
   main, daté, et avec la raison de chaque entrée.

L'ordre compte : la feuille officielle a le dernier mot sur le nom. Un
supplément ne sert qu'à combler un absent, jamais à renommer quelqu'un que
la feuille connaît.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def _depuis_contraintes(racine: Path) -> dict[str, str]:
    chemin = racine / "contraintes" / "05_enseignants_contraintes.json"
    if not chemin.exists():
        return {}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    liste = brut if isinstance(brut, list) else brut.get("enseignants", []) if isinstance(brut, dict) else []
    if isinstance(liste, dict):
        liste = list(liste.values())
    sortie: dict[str, str] = {}
    for entree in liste:
        if not isinstance(entree, dict):
            continue
        code = str(entree.get("trigramme") or "").strip().upper()
        nom = str(entree.get("nom_complet") or "").strip()
        if code:
            sortie[code] = nom or code
    return sortie


def _depuis_supplements(config_dir: Path) -> dict[str, str]:
    chemin = config_dir / "enseignants_supplementaires.yaml"
    if not chemin.exists():
        return {}
    try:
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    if not isinstance(brut, dict):
        return {}
    sortie: dict[str, str] = {}
    for code, fiche in brut.items():
        nom = fiche.get("nom") if isinstance(fiche, dict) else fiche
        code_propre = str(code or "").strip().upper()
        if code_propre:
            sortie[code_propre] = str(nom or "").strip() or code_propre
    return sortie


def enseignants_declares(config_dir: Path) -> dict[str, str]:
    """Trigramme -> « Prénom Nom », pour tout enseignant déclaré.

    Ne lève jamais : une source illisible rend simplement moins de noms. Au
    pire, un enseignant reste introuvable dans la liste — ce qui était le
    comportement d'avant — plutôt que de faire tomber tout l'état applicatif.
    """
    config_dir = Path(config_dir)
    racine = config_dir.parent.parent
    noms = _depuis_supplements(config_dir)
    # La feuille officielle a le dernier mot sur le nom.
    noms.update(_depuis_contraintes(racine))
    return noms
