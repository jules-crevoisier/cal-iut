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
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat, verrou_fichier

# Lire, modifier, écrire : sous ce verrou (threads) ET le verrou de fichier
# (l'API et le worker partagent `data/state/`). Deux saisies simultanées
# depuis l'onglet « Codes Celcat » s'écrasaient sinon l'une l'autre.
_verrou = threading.RLock()

# Les familles que l'écran peut compléter. `matieres` (29/09/2026, « go » de
# l'utilisateur) : code de cours -> code module Celcat (`TSB…`), la même
# table que `celcat.yaml::modules`. Le code module est lisible dans Celcat ;
# son identifiant INTERNE (`celcat_matieres.yaml`), lui, ne l'est pas — il
# reste relevé et figé dans la config, comme celui des groupes. Les types de
# séance n'y sont pas : ils se corrigent dans la maquette.
#
# Pas de famille `groupes` (examiné le 30/09/2026 pour l'onglet « Codes
# Celcat ») : l'identifiant d'un groupe est interne, illisible dans Celcat,
# sans liste relevée contre laquelle valider une saisie, et un identifiant
# faux fabrique des doublons (cf. `api/codes_celcat.py`).
#
# La validation (format par famille, doublon refusé) et la trace vivent dans
# `api/codes_celcat.py`, seul chemin d'écriture de tous les écrans.
FAMILLES = ("salles", "enseignants", "matieres")

# Familles dont la clé est un code comparé en majuscules par
# `load_celcat_config` : trigramme d'enseignant, code de cours.
_CLES_MAJUSCULES = ("enseignants", "matieres")


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


def _charger_pour_ecriture() -> dict[str, dict[str, dict[str, Any]]]:
    """La surcouche pour une ÉCRITURE : un fichier abîmé est mis de côté et
    `FichierEtatIllisible` levée, plutôt que de rendre un vide que
    l'écriture persisterait par-dessus toutes les correspondances saisies."""
    brut = lire_json_etat(_path(), {}, types=dict)
    sortie: dict[str, dict[str, dict[str, Any]]] = {}
    for famille in FAMILLES:
        entrees = brut.get(famille)
        sortie[famille] = {
            str(cle): dict(valeur)
            for cle, valeur in (entrees or {}).items()
            if isinstance(valeur, dict) and str(valeur.get("valeur") or "").strip()
        }
    return sortie


def cle_normalisee(famille: str, cle: str) -> str:
    """La clé telle que la surcouche la range (majuscules pour les
    trigrammes et les codes de cours, cf. `_CLES_MAJUSCULES`)."""
    cle_propre = str(cle).strip()
    return cle_propre.upper() if famille in _CLES_MAJUSCULES else cle_propre


def table(famille: str) -> dict[str, str]:
    """Les correspondances d'une famille, prêtes à fusionner : clé -> valeur."""
    return {cle: str(entree["valeur"]) for cle, entree in charger().get(famille, {}).items()}


def definir(
    famille: str, cle: str, valeur: str, *, par: str = "", valeur_fichier: str | None = None
) -> dict[str, Any]:
    """Ajoute ou corrige une correspondance. Rend l'entrée écrite.

    `valeur` vide n'est pas une suppression déguisée : `oublier` existe pour
    cela, et confondre les deux ferait effacer une correspondance en croyant
    l'enregistrer.

    L'entrée garde sa trace (30/09/2026, onglet « Codes Celcat ») : qui,
    quand, la valeur d'AVANT (saisie précédente, sinon celle du fichier) et
    celle du fichier au moment de la saisie. La validation métier (format,
    doublon) est faite par `api/codes_celcat.py` : ce module persiste.
    """
    if famille not in FAMILLES:
        raise ValueError(f"famille inconnue : « {famille} »")
    cle_propre = str(cle).strip()
    valeur_propre = str(valeur).strip()
    if not cle_propre or not valeur_propre:
        raise ValueError("la clé et la valeur sont toutes deux requises")
    # Trigrammes et codes de cours sont comparés en majuscules par
    # `load_celcat_config` : les enregistrer autrement les rendrait invisibles.
    if famille in _CLES_MAJUSCULES:
        cle_propre = cle_propre.upper()
    if famille == "matieres":
        valeur_propre = valeur_propre.upper()

    with _verrou, verrou_fichier(_path()):
        doc = _charger_pour_ecriture()
        precedente = doc.get(famille, {}).get(cle_propre) or {}
        entree = {
            "valeur": valeur_propre,
            "ajoute_le": datetime.now(UTC).isoformat(),
            "ajoute_par": str(par or "").strip(),
            "valeur_avant": precedente.get("valeur") or valeur_fichier,
            "valeur_fichier": valeur_fichier,
        }
        doc.setdefault(famille, {})[cle_propre] = entree
        ecrire_json(_path(), doc)
    return entree


def oublier(famille: str, cle: str) -> bool:
    """Retire une correspondance. Rend True si elle existait."""
    return retirer(famille, cle) is not None


def retirer(famille: str, cle: str) -> dict[str, Any] | None:
    """Retire une correspondance (« Revenir à la valeur du fichier »). Rend
    l'entrée retirée, ou None s'il n'y en avait pas."""
    if famille not in FAMILLES:
        raise ValueError(f"famille inconnue : « {famille} »")
    cle_propre = cle_normalisee(famille, cle)
    with _verrou, verrou_fichier(_path()):
        doc = _charger_pour_ecriture()
        entree = doc.get(famille, {}).pop(cle_propre, None)
        if entree is None:
            return None
        ecrire_json(_path(), doc)
    return entree
