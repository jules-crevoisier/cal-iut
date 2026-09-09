"""Garde-fous avant un enregistrement RPC : une semaine, pas de delete."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from cal_iut.celcat.categories import verifier_charge_categorie
from cal_iut.celcat.driver import SemainesNonRestreintes
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.navigateur import (
    BASE_ENTRAINEMENT,
    BASE_PRODUCTION,
    TYPE_CATEGORIES_EVENEMENT,
    TYPE_DEPARTEMENTS,
    TYPE_GROUPES,
    TYPE_MATIERES,
    TYPE_PERSONNEL,
    TYPE_SALLES,
)
from cal_iut.celcat.rpc import (
    charger_ressources,
    enregistrer_evenement,
    event_id_retour,
    id_ressource,
)

# Ré-export : `_event_id_retour` vivait ici avant d'être promu public dans
# `rpc.py` (partagé avec `modification.py`) — alias gardé pour ne rien
# casser d'un éventuel appelant existant qui importait le nom privé.
_event_id_retour = event_id_retour

_FILTRE_VIDE: dict[str, object] = {"customOnly": False, "includedDetails": []}
_CATALOGUE: dict[int, list[dict]] = {}
_GROUPES: dict[str, int] | None = None
_MATIERES: dict[str, int] | None = None
_CHEMIN_GROUPES = (
    Path(__file__).resolve().parents[3] / "data" / "config" / "celcat_groupes.yaml"
)
_CHEMIN_MATIERES = (
    Path(__file__).resolve().parents[3] / "data" / "config" / "celcat_matieres.yaml"
)

__all__ = [
    "ProductionRefusee",
    "RessourceIntrouvable",
    "ResultatEcriture",
    "SemainesNonRestreintes",
    "charge_utile",
    "creer_manquants",
    "resoudre_groupe",
    "resoudre_ids",
    "verifier_avant_envoi",
]


class ProductionRefusee(PermissionError):
    """URCA_2026 n'accepte d'écriture qu'avec --production."""


@dataclass
class ResultatEcriture:
    crees: list[tuple[str, int]] = field(default_factory=list)
    echecs: list[tuple[str, str]] = field(default_factory=list)


def _id(ids: dict, *cles: str) -> int | None:
    for cle in cles:
        val = ids.get(cle)
        if val is not None:
            return int(val)
    return None


class RessourceIntrouvable(LookupError):
    """Identifiant Celcat introuvable pour une ressource requise."""


def charge_utile(
    e: EntreeCelcat,
    *,
    group_id: int,
    ids: dict,
    masque: str,
    event_id: int,
) -> dict:
    charge: dict[str, object] = {
        "day_of_week": e.jour - 1,
        "start_time": e.heure_debut,
        "end_time": e.heure_fin,
        "weeks": masque,
        "event_cat_id": _id(ids, "event_cat_id"),
        "dept_id": _id(ids, "dept_id"),
        "modules": [{"module_id": _id(ids, "module_id")}],
        "rooms": [{"room_id": _id(ids, "room_id", "salle_id")}],
        "staff": [{"staff_id": _id(ids, "staff_id")}],
        "groups": [{"group_id": group_id}],
        "protected": "N",
        "suspended": "N",
        "global_event": "N",
        "break_mins": 0,
        "notes": e.session_id,
    }
    if event_id:
        charge["event_id"] = event_id
    return charge


def verifier_avant_envoi(
    charge: dict, *, base: str, production_autorisee: bool
) -> None:
    masque = str(charge.get("weeks") or "")
    if masque.count("Y") != 1:
        raise SemainesNonRestreintes(
            f"masque semaines {masque.count('Y')}×Y — une seule est exigée"
        )
    if base == BASE_PRODUCTION and not production_autorisee:
        raise ProductionRefusee("URCA_2026 exige --production")


def _filtre_ressource(*, record_ids: list[int] | None = None) -> dict:
    # Celcat n'accepte que customOnly, includedDetails, recordIDs.
    filtre: dict[str, object] = dict(_FILTRE_VIDE)
    if record_ids:
        filtre["recordIDs"] = record_ids
    return filtre


def _catalogue(page, type_id: int) -> list[dict]:
    lots = _CATALOGUE.get(type_id)
    if lots is None:
        lots = charger_ressources(page, type_id, _filtre_ressource())
        _CATALOGUE[type_id] = lots
    return lots


def _lire_table(chemin: Path) -> dict[str, int]:
    """« "clé": 123  # commentaire » -> {"clé": 123}.

    Volontairement sans PyYAML : ces deux tables sont des relevés plats, et
    la lecture doit rester possible dans le sidecar, qui n'a pas toujours la
    dépendance (constaté le 02/09/2026).
    """
    lus: dict[str, int] = {}
    if not chemin.exists():
        return lus
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        texte = ligne.split("#", 1)[0].strip()
        if ":" not in texte:
            continue
        nom, brut = texte.split(":", 1)
        try:
            lus[nom.strip().strip('"')] = int(brut.strip())
        except ValueError:
            continue
    return lus


def _groupes_connus() -> dict[str, int]:
    global _GROUPES
    if _GROUPES is None:
        _GROUPES = _lire_table(_CHEMIN_GROUPES)
    return _GROUPES


def _matieres_connues() -> dict[str, int]:
    """Code Celcat de la matière (« TSBZC01M ») -> module_id.

    Même raison d'être que `_groupes_connus` : `udlResources.load` refuse
    d'énumérer le catalogue des matières (`ETooManyRecords`), et
    `customOnly: True` rend zéro enregistrement. Relevé par balayage de
    plages de `recordIDs`, figé ici.
    """
    global _MATIERES
    if _MATIERES is None:
        _MATIERES = _lire_table(_CHEMIN_MATIERES)
    return _MATIERES


def _trouver(
    page,
    type_id: int,
    libelle: str,
    *cles: str,
    unique_name: str = "",
    name: str = "",
    prefixe: str = "",
) -> int:
    if type_id == TYPE_GROUPES:
        return _trouver_groupe(page, libelle, prefixe or name)
    if type_id == TYPE_MATIERES:
        return _trouver_matiere(page, libelle, unique_name, *cles)
    lots = _catalogue(page, type_id)
    choisi = _choisir(
        lots, unique_name=unique_name, name=name, prefixe=prefixe
    )
    return _exiger(choisi, libelle, *cles)


def _normaliser_groupe(nom: str) -> str:
    """« BUT MMI  s5  TD EF - 2024 » -> « BUT MMI S5 TD EF »."""
    return re.sub(r"\s*-\s*\d{4}\s*$", "", " ".join(nom.split())).strip().upper()


def _trouver_groupe(page, libelle: str, nom: str) -> int:
    """Le nom doit correspondre EXACTEMENT (aux espaces et à la casse près,
    et au suffixe de cohorte « - 2024 » près).

    La comparaison était « préfixe de » dans les deux sens. Tant que la
    table ne portait que le S1 et trois groupes du S5, elle ne pouvait pas
    se tromper. Complétée à 88 groupes le 09/09/2026, elle le pouvait : un
    nom tronqué comme « BUT MMI S5 » aurait accroché « BUT MMI S5 TD AB »
    et déversé une promotion entière sur le mauvais groupe. Un nom inconnu
    doit être un refus, jamais un voisin plausible.
    """
    cible = _normaliser_groupe(nom)
    gid = None
    for cle, identifiant in _groupes_connus().items():
        if _normaliser_groupe(cle) == cible:
            gid = identifiant
            break
    if gid is None:
        raise RessourceIntrouvable(libelle)
    lots = charger_ressources(
        page, TYPE_GROUPES, _filtre_ressource(record_ids=[gid])
    )
    return _exiger(_choisir(lots, prefixe=nom), libelle, "group_id")


def _trouver_matiere(page, libelle: str, code: str, *cles: str) -> int:
    """Le module_id vient de la TABLE, jamais d'une recherche à l'aveugle.

    CE QUI ÉTAIT FAIT AVANT, et pourquoi ça ne pouvait pas marcher. Faute de
    catalogue énumérable, `_modules_par_scan` cherchait en deux temps :

    1. il rechargeait l'EDT des 88 groupes, un par un, et retenait les
       modules déjà posés sur un évènement ;
    2. sinon il balayait ±2500 identifiants autour des trois premiers
       modules ainsi vus — et, s'il n'en avait vu aucun, autour de 1660000,
       qui est un identifiant de GROUPE : la mauvaise plage de 65000.

    Un module ne pouvait donc être trouvé que s'il servait DÉJÀ quelque
    part. Or ceux qu'on cherche sont précisément ceux qui n'ont jamais été
    posés : les alternants BUT2 CREACOM et BUT3. `WRA301M` -> `TSBZC01M`,
    `WRA304M`, `WRA305M`… échouaient tous par « RessourceIntrouvable :
    matière », en production le 09/09/2026.

    Accessoirement, chaque échec coûtait 88 chargements d'EDT plus une
    centaine d'appels de balayage, pour aboutir à rien. Les matières vivent
    entre 1582737 et 1596928 ; elles sont relevées une fois pour toutes dans
    `data/config/celcat_matieres.yaml`.

    Un code absent de la table est un refus NOMMÉ, comme pour les groupes :
    il dit quoi ajouter et où, au lieu de chercher longuement et d'échouer.
    """
    mid = _matieres_connues().get(code.strip().upper())
    if mid is None:
        raise RessourceIntrouvable(
            f"{libelle} — code absent de data/config/celcat_matieres.yaml"
        )
    lots = charger_ressources(
        page, TYPE_MATIERES, _filtre_ressource(record_ids=[mid])
    )
    return _exiger(_choisir(lots, unique_name=code), libelle, *cles)


def _choisir(
    lots: list[dict],
    *,
    unique_name: str = "",
    name: str = "",
    prefixe: str = "",
) -> dict | None:
    uniques = unique_name.strip().upper()
    nom = name.strip().upper()
    pref = prefixe.strip().upper()
    for enreg in lots:
        code = str(enreg.get("unique_name") or "").strip().upper()
        libelle = str(
            enreg.get("name") or enreg.get("evCatName") or ""
        ).strip().upper()
        if uniques and code == uniques:
            return enreg
        if nom and libelle == nom:
            return enreg
        if nom and libelle.startswith(nom) and "BENEVOLE" not in libelle and "CAPACITE" not in libelle:
            return enreg
        if pref and (libelle.startswith(pref) or pref in libelle):
            return enreg
    return None


def _exiger(enreg: dict | None, libelle: str, *cles: str) -> int:
    if enreg is None:
        raise RessourceIntrouvable(libelle)
    identifiant = id_ressource(enreg, *cles, "id")
    if identifiant is None:
        raise RessourceIntrouvable(libelle)
    return identifiant


def resoudre_ids(page, e: EntreeCelcat, *, categorie: str) -> dict:
    """Traduit codes cal-iut → IDs numériques de la base Celcat ouverte."""
    return {
        "module_id": _trouver(
            page,
            TYPE_MATIERES,
            f"matière {e.code_module}",
            "module_id",
            unique_name=e.code_module or "",
        ),
        "room_id": _trouver(
            page,
            TYPE_SALLES,
            f"salle {e.salle}",
            "room_id",
            unique_name=e.salle or "",
            name=e.salle or "",
        ),
        "staff_id": _trouver(
            page,
            TYPE_PERSONNEL,
            f"personnel {e.code_enseignant}",
            "staff_id",
            unique_name=e.code_enseignant or "",
        ),
        "event_cat_id": _trouver(
            page,
            TYPE_CATEGORIES_EVENEMENT,
            f"catégorie {categorie}",
            "event_cat_id",
            unique_name=categorie,
            name=categorie,
        ),
        "dept_id": _trouver(
            page,
            TYPE_DEPARTEMENTS,
            "département T_MMI",
            "dept_id",
            unique_name="T_MMI T29",
            name="T_MMI T29",
            prefixe="T_MMI",
        ),
    }


def resoudre_groupe(page, nom: str) -> int:
    return _trouver(
        page,
        TYPE_GROUPES,
        f"groupe {nom}",
        "group_id",
        unique_name=nom,
        name=nom,
        prefixe=nom,
    )


def creer_manquants(
    page,
    entrees: list[EntreeCelcat],
    *,
    group_id: int,
    ids: dict,
    masque: str,
    methode: str,
    base: str = BASE_ENTRAINEMENT,
    production_autorisee: bool = False,
    event_id: int = 0,
) -> ResultatEcriture:
    resultat = ResultatEcriture()
    for e in entrees:
        try:
            charge = charge_utile(
                e, group_id=group_id, ids=ids, masque=masque, event_id=event_id
            )
            verifier_charge_categorie(charge, type_seance_nom=e.type_seance_nom)
            verifier_avant_envoi(
                charge, base=base, production_autorisee=production_autorisee
            )
            retour = enregistrer_evenement(page, charge, methode=methode)
            nouveau = _event_id_retour(retour)
            if nouveau is None or nouveau == 0:
                raise RuntimeError("enregistrement sans event_id")
            resultat.crees.append((e.session_id, nouveau))
            _notifier_celcat(
                "celcat_ok",
                f"{e.session_id} enregistré Celcat (event_id={nouveau}, {e.type_seance_nom})",
            )
        except Exception as exc:  # noqa: BLE001
            resultat.echecs.append((e.session_id, str(exc)))
            _notifier_celcat(
                "celcat_echec",
                f"{e.session_id} Celcat : {exc}",
            )
    return resultat


def _notifier_celcat(evenement: str, texte: str) -> None:
    """Mail optionnel — jamais faire échouer l'écriture Celcat."""
    try:
        from cal_iut.api import notifications

        notifications.signaler(evenement, texte)
        notifications.envoyer_si_temps_ecoule()
    except Exception:  # noqa: BLE001
        return
