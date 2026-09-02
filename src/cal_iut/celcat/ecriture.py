"""Garde-fous avant un enregistrement RPC : une semaine, pas de delete."""

from __future__ import annotations

from dataclasses import dataclass, field

from pathlib import Path

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
from cal_iut.celcat.rpc import charger_edt, charger_ressources, enregistrer_evenement, id_ressource

_FILTRE_VIDE: dict[str, object] = {"customOnly": False, "includedDetails": []}
_CATALOGUE: dict[int, list[dict]] = {}
_GROUPES: dict[str, int] | None = None
_CHEMIN_GROUPES = (
    Path(__file__).resolve().parents[3] / "data" / "config" / "celcat_groupes.yaml"
)

__all__ = [
    "ProductionRefusee",
    "SemainesNonRestreintes",
    "ResultatEcriture",
    "RessourceIntrouvable",
    "charge_utile",
    "verifier_avant_envoi",
    "resoudre_ids",
    "resoudre_groupe",
    "creer_manquants",
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


def _event_id_retour(resultat: object) -> int | None:
    if isinstance(resultat, bool):
        return None
    if isinstance(resultat, int):
        return resultat
    if isinstance(resultat, list) and resultat:
        return _event_id_retour(resultat[0])
    if isinstance(resultat, dict):
        brut = resultat.get("event_id") or resultat.get("id")
        if brut is not None:
            return int(brut)
    return None


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


def _groupes_connus() -> dict[str, int]:
    global _GROUPES
    if _GROUPES is None:
        lus: dict[str, int] = {}
        if _CHEMIN_GROUPES.exists():
            for ligne in _CHEMIN_GROUPES.read_text(encoding="utf-8").splitlines():
                texte = ligne.split("#", 1)[0].strip()
                if ":" not in texte:
                    continue
                nom, brut = texte.split(":", 1)
                lus[nom.strip().strip('"')] = int(brut.strip())
        _GROUPES = lus
    return _GROUPES


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
    lots: list[dict] = []
    try:
        lots = _catalogue(page, type_id)
    except Exception:  # noqa: BLE001 — ETooManyRecords (matières)
        lots = _modules_par_scan(page, unique_name) if unique_name else []
    choisi = _choisir(
        lots, unique_name=unique_name, name=name, prefixe=prefixe
    )
    return _exiger(choisi, libelle, *cles)


def _trouver_groupe(page, libelle: str, nom: str) -> int:
    gid = None
    for cle, identifiant in _groupes_connus().items():
        if nom == cle or nom.startswith(cle) or cle.startswith(nom):
            gid = identifiant
            break
    if gid is None:
        raise RessourceIntrouvable(libelle)
    lots = charger_ressources(
        page, TYPE_GROUPES, _filtre_ressource(record_ids=[gid])
    )
    return _exiger(_choisir(lots, prefixe=nom), libelle, "group_id")


def _modules_par_scan(page, code: str) -> list[dict]:
    vus: list[dict] = []
    for gid in _groupes_connus().values():
        for ev in charger_edt(page, group_ids=[gid]):
            for module in ev.get("modules") or []:
                if isinstance(module, dict):
                    vus.append(module)
                    if str(module.get("unique_name") or "") == code:
                        return [module]
    ancres = [
        int(m.get("module_id") or m.get("id"))
        for m in vus
        if m.get("module_id") or m.get("id")
    ]
    if not ancres:
        ancres = [1660000]
    for ancre in ancres[:3]:
        debut, fin = max(1, ancre - 2500), ancre + 2500
        for a in range(debut, fin, 400):
            lots = charger_ressources(
                page,
                TYPE_MATIERES,
                _filtre_ressource(record_ids=list(range(a, min(a + 400, fin)))),
            )
            choisi = _choisir(lots, unique_name=code)
            if choisi:
                return [choisi]
    return []


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
            verifier_avant_envoi(
                charge, base=base, production_autorisee=production_autorisee
            )
            retour = enregistrer_evenement(page, charge, methode=methode)
            nouveau = _event_id_retour(retour)
            if nouveau is None or nouveau == 0:
                raise RuntimeError("enregistrement sans event_id")
            resultat.crees.append((e.session_id, nouveau))
        except Exception as exc:  # noqa: BLE001
            resultat.echecs.append((e.session_id, str(exc)))
    return resultat
