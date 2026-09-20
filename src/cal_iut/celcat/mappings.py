"""Les correspondances ajoutées depuis l'écran, par-dessus `celcat.yaml`.

POURQUOI CE MODULE EXISTE. Une salle ou un enseignant que Celcat connaît sous
un autre nom bloque la séance : `mapping.py` la marque « non saisissable » et
le worker l'écarte à chaque passage, indéfiniment. Le 20/09/2026, deux
séances attendaient sur « salle e-102 sans équivalent Celcat » et trois sur
« enseignant JHU sans code Celcat ».

La table vit dans `data/config/celcat.yaml`, qui est **dans l'image Docker**,
hors du volume : la corriger demandait donc une modification du code, une
revue, un déploiement — pour une ligne de correspondance. Demande de
l'utilisateur, le 20/09/2026 : « pour la salle il faut avoir une option pour
mapper ».

Cette surcouche vit dans `data/state/`, le volume partagé par l'API et le
worker. Une correspondance ajoutée à l'écran est donc lue par le worker à son
passage suivant, sans redémarrage ni déploiement.

ELLE COMPLÈTE, ELLE NE REMPLACE PAS. `celcat.yaml` reste la référence tenue
avec le code ; la surcouche ajoute ce qui manque et peut corriger une entrée
existante. L'ordre est explicite : le YAML d'abord, la surcouche par-dessus.
On sait ainsi toujours qui a le dernier mot.

CHAQUE ENTRÉE GARDE SON ORIGINE — qui l'a ajoutée et quand. Une table de
correspondance qu'on ne peut pas dater devient, au bout de quelques mois, un
ensemble de décisions que plus personne n'assume.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cal_iut.celcat.fichiers import ecrire_json

# Les deux familles que l'écran peut compléter. Les modules et les types de
# séance n'y sont pas : ils se corrigent dans la maquette, pas au cas par cas.
FAMILLES = ("salles", "enseignants")


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_mappings.json"


def charger() -> dict[str, dict[str, dict[str, Any]]]:
    """La surcouche complète, avec l'origine de chaque entrée.

    Ne lève jamais : un fichier illisible rend une surcouche vide, et la
    synchronisation continue avec le seul `celcat.yaml`. Perdre une
    correspondance coûte une séance bloquée, visible ; lever ici casserait
    tout l'écran Celcat.
    """
    chemin = _path()
    if not chemin.exists():
        return {famille: {} for famille in FAMILLES}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {famille: {} for famille in FAMILLES}
    if not isinstance(brut, dict):
        return {famille: {} for famille in FAMILLES}
    sortie: dict[str, dict[str, dict[str, Any]]] = {}
    for famille in FAMILLES:
        entrees = brut.get(famille)
        sortie[famille] = {
            str(cle): valeur
            for cle, valeur in (entrees or {}).items()
            if isinstance(valeur, dict) and str(valeur.get("valeur") or "").strip()
        }
    return sortie


def table(famille: str) -> dict[str, str]:
    """Les correspondances d'une famille, prêtes à fusionner : clé -> valeur."""
    return {cle: str(entree["valeur"]) for cle, entree in charger().get(famille, {}).items()}


def definir(famille: str, cle: str, valeur: str, *, par: str = "") -> dict[str, Any]:
    """Ajoute ou corrige une correspondance. Rend l'entrée écrite.

    `valeur` vide n'est pas une suppression déguisée : `oublier` existe pour
    cela, et confondre les deux ferait effacer une correspondance en croyant
    l'enregistrer.
    """
    if famille not in FAMILLES:
        raise ValueError(f"famille inconnue : « {famille} »")
    cle_propre = str(cle).strip()
    valeur_propre = str(valeur).strip()
    if not cle_propre or not valeur_propre:
        raise ValueError("la clé et la valeur sont toutes deux requises")
    # Les trigrammes d'enseignant sont comparés en majuscules par
    # `load_celcat_config` : les enregistrer autrement les rendrait invisibles.
    if famille == "enseignants":
        cle_propre = cle_propre.upper()

    doc = charger()
    entree = {
        "valeur": valeur_propre,
        "ajoute_le": datetime.now(UTC).isoformat(),
        "ajoute_par": str(par or "").strip(),
    }
    doc.setdefault(famille, {})[cle_propre] = entree
    ecrire_json(_path(), doc)
    return entree


def oublier(famille: str, cle: str) -> bool:
    """Retire une correspondance. Rend True si elle existait."""
    if famille not in FAMILLES:
        raise ValueError(f"famille inconnue : « {famille} »")
    cle_propre = str(cle).strip()
    if famille == "enseignants":
        cle_propre = cle_propre.upper()
    doc = charger()
    if cle_propre not in doc.get(famille, {}):
        return False
    del doc[famille][cle_propre]
    ecrire_json(_path(), doc)
    return True
