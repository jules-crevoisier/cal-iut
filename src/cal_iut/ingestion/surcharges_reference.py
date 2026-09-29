"""Informations de référence complétées depuis l'appli, par-dessus la config.

POURQUOI CE MODULE EXISTE. Demande utilisateur (29/09/2026) : « quand on a un
email manquant, peut-être un numéro de salle Celcat manquant, etc., il faut
pouvoir ajouter l'info et l'enregistrer ». L'appli SIGNALAIT déjà ces manques
(pastille « manquant » de l'annuaire, « adresse mail manquante » sur la fiche)
mais renvoyait vers un fichier — `data/config/teacher_contacts.yaml` — qui est
DANS L'IMAGE Docker, hors du volume : le compléter demandait une modification
du code, une revue et un déploiement, pour une adresse.

Cette surcouche vit dans `data/state/references.json`, le volume persistant
(cf. Dockerfile : seul `data/state/` survit à un redéploiement). Même principe
que les correspondances Celcat (`celcat/mappings.py`), les salles ajoutées
(`api/custom_rooms.py`) et les retouches de séance (`api/session_overrides.py`).

ELLE COMPLÈTE, ELLE NE REMPLACE PAS. Contrairement aux correspondances Celcat,
la configuration garde ici le dernier mot : une adresse, un nom ou un intitulé
saisi dans l'appli ne sert QUE tant que la source officielle (le YAML, la
feuille des contraintes, la maquette) n'en fournit pas. Le jour où
`teacher_contacts.yaml` reçoit l'adresse au déploiement, c'est elle qui
s'affiche — on ne se retrouve jamais à corriger un fichier sans effet parce
qu'une saisie ancienne, oubliée, passe devant.

Familles et champs :
- `enseignants` : `email` (lu par `config_loader.load_teacher_contacts`) et
  `nom` (lu par `ingestion/enseignants.py::enseignants_declares`) ;
- `cours` : `intitule` (appliqué aux séances chargées, `appliquer_intitules`).

Les salles n'y sont pas : leurs attributs éditables vivent déjà dans
`data/state/custom_rooms.json` (`api/custom_rooms.py`), et leur code Celcat
dans `data/state/celcat_mappings.json`. Une seule persistance par donnée.

CHAQUE VALEUR GARDE SON ORIGINE — qui l'a saisie et quand — et chaque saisie
(salles et correspondances Celcat comprises) laisse une ligne au `journal`,
avec la valeur d'avant.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cal_iut.celcat.fichiers import (
    FichierEtatIllisible,
    ecrire_json,
    lire_json_etat,
    verrou_fichier,
)

logger = logging.getLogger(__name__)

CHAMPS: dict[str, tuple[str, ...]] = {
    "enseignants": ("email", "nom"),
    "cours": ("intitule",),
}

# Au-delà, les plus anciennes lignes du journal tombent : il sert à répondre
# à « qui a mis cette adresse ? » sur les dernières semaines, pas à archiver.
JOURNAL_MAX = 500

_verrou = threading.RLock()


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "references.json"


def _vide() -> dict[str, Any]:
    return {**{famille: {} for famille in CHAMPS}, "journal": []}


def _normaliser(brut: object) -> dict[str, Any]:
    doc = _vide()
    if not isinstance(brut, dict):
        return doc
    for famille in CHAMPS:
        entrees = brut.get(famille)
        if isinstance(entrees, dict):
            doc[famille] = {str(k): dict(v) for k, v in entrees.items() if isinstance(v, dict)}
    journal = brut.get("journal")
    if isinstance(journal, list):
        doc["journal"] = [ligne for ligne in journal if isinstance(ligne, dict)]
    return doc


def charger() -> dict[str, Any]:
    """Le document complet, pour une ÉCRITURE : lève `FichierEtatIllisible`
    sur un fichier abîmé (mis de côté), plutôt que de rendre un vide que
    l'écriture suivante persisterait par-dessus les saisies existantes."""
    return _normaliser(lire_json_etat(_path(), _vide(), types=dict))


def _charger_pour_lecture() -> dict[str, Any]:
    """Le document, pour une LECTURE (chargement de la config) : ne lève
    jamais. Un fichier illisible est mis de côté par `lire_json_etat` (copie
    `.corrompu-…` conservée) et la lecture continue avec la seule config —
    une adresse qui manque se voit et se ressaisit, un `/app-state` en échec
    bloquerait tout le monde."""
    try:
        return charger()
    except (FichierEtatIllisible, OSError):
        logger.exception("Surcharges de référence illisibles, lecture sans elles")
        return _vide()


def valeurs(famille: str, champ: str) -> dict[str, str]:
    """`{clé: valeur}` d'un champ, prêt à fusionner sous la config."""
    doc = _charger_pour_lecture()
    sortie: dict[str, str] = {}
    for cle, champs in doc.get(famille, {}).items():
        entree = champs.get(champ)
        if isinstance(entree, dict) and str(entree.get("valeur") or "").strip():
            sortie[cle] = str(entree["valeur"]).strip()
    return sortie


def origine(famille: str, cle: str, champ: str) -> dict[str, Any] | None:
    """`{"valeur", "modifie_le", "modifie_par"}` d'une saisie, ou None."""
    entree = _charger_pour_lecture().get(famille, {}).get(cle, {}).get(champ)
    return dict(entree) if isinstance(entree, dict) else None


def _ligne_journal(famille: str, cle: str, champ: str, avant: object, apres: object, par: str) -> dict[str, Any]:
    return {
        "le": datetime.now(UTC).isoformat(),
        "par": str(par or "").strip(),
        "famille": famille,
        "cle": cle,
        "champ": champ,
        "avant": avant,
        "apres": apres,
    }


def _ajouter_au_journal(doc: dict[str, Any], ligne: dict[str, Any]) -> None:
    doc["journal"] = (list(doc.get("journal") or []) + [ligne])[-JOURNAL_MAX:]
    logger.info(
        "Référence complétée : %s %s.%s = %r (avant %r) par %s",
        ligne["famille"], ligne["cle"], ligne["champ"], ligne["apres"], ligne["avant"], ligne["par"] or "?",
    )


def definir(famille: str, cle: str, champ: str, valeur: str, *, par: str = "") -> dict[str, Any]:
    """Enregistre UNE valeur (déjà validée par l'appelant). Rend l'entrée.

    La validation métier (format d'adresse, doublon, entité connue) est
    faite par `api/reference.py`, seul appelant : ce module ne fait que
    persister, dater et journaliser.
    """
    if champ not in CHAMPS.get(famille, ()):
        raise ValueError(f"champ inconnu : « {famille}.{champ} »")
    cle_propre = str(cle).strip()
    valeur_propre = str(valeur).strip()
    if not cle_propre or not valeur_propre:
        raise ValueError("la clé et la valeur sont toutes deux requises")
    with _verrou, verrou_fichier(_path()):
        doc = charger()
        champs = dict(doc[famille].get(cle_propre, {}))
        avant = (champs.get(champ) or {}).get("valeur") if isinstance(champs.get(champ), dict) else None
        entree = {
            "valeur": valeur_propre,
            "modifie_le": datetime.now(UTC).isoformat(),
            "modifie_par": str(par or "").strip(),
        }
        champs[champ] = entree
        doc[famille][cle_propre] = champs
        _ajouter_au_journal(doc, _ligne_journal(famille, cle_propre, champ, avant, valeur_propre, par))
        ecrire_json(_path(), doc)
    return entree


def journaliser(famille: str, cle: str, champ: str, avant: object, apres: object, *, par: str = "") -> None:
    """Trace une saisie persistée AILLEURS (salle, correspondance Celcat) :
    un seul journal pour « qui a complété quoi », quel que soit le fichier
    qui porte la valeur. Ne lève jamais : la saisie a déjà réussi."""
    try:
        with _verrou, verrou_fichier(_path()):
            doc = charger()
            _ajouter_au_journal(doc, _ligne_journal(famille, str(cle), champ, avant, apres, par))
            ecrire_json(_path(), doc)
    except Exception:
        logger.exception("Journal des compléments : écriture impossible (%s %s.%s)", famille, cle, champ)


def journal() -> list[dict[str, Any]]:
    """Les dernières saisies, la plus récente d'abord."""
    return list(reversed(_charger_pour_lecture().get("journal") or []))


def intitule_manquant(code: str, intitule: str | None) -> bool:
    """Vide, ou égal au code : ce que rend une matière dont la source ne
    donne que le code."""
    texte = str(intitule or "").strip()
    return not texte or texte.upper() == str(code).strip().upper()


def appliquer_intitules(
    sessions: list[Any], courses: list[Any] | None = None, *, remplacables: dict[str, str] | None = None
) -> None:
    """Pose l'intitulé saisi sur les séances (et matières) qui n'en ont pas.

    Une séance qui porte déjà un vrai intitulé le garde : la maquette a le
    dernier mot (cf. docstring). `remplacables` (`{code: ancienne saisie}`)
    permet de corriger EN MÉMOIRE une saisie précédente, qui n'est plus
    « manquante » une fois posée."""
    intitules = valeurs("cours", "intitule")
    if not intitules:
        return
    for objet in list(sessions) + list(courses or []):
        code = str(getattr(objet, "course_code", None) or getattr(objet, "code", "") or "")
        nouveau = intitules.get(code)
        if not nouveau:
            continue
        attribut = "course_name" if hasattr(objet, "course_name") else "name"
        actuel = str(getattr(objet, attribut, "") or "").strip()
        ancien = (remplacables or {}).get(code)
        if intitule_manquant(code, actuel) or (ancien is not None and actuel == ancien):
            setattr(objet, attribut, nouveau)
