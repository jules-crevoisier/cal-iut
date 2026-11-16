"""Flux JSON de MMI Prévi : maquette et progression (16/11/2026).

Depuis novembre 2026, MMI Prévi n'accepte plus d'appel sans jeton. Le jeton
est PERSONNEL : il ne vit que dans la variable d'environnement
`CAL_IUT_MMI_PREVI_JETON` du serveur, ne part que dans l'en-tête
`Authorization` (jamais dans l'URL) et n'est écrit nulle part — ni fichier,
ni journal, ni message d'erreur.

Deux rôles :

1. `telecharger` — un flux, filtré par `?semestres=`.
2. Les COPIES : ce qu'un administrateur a récupéré depuis l'écran « Nouveau
   semestre » est rangé dans `data/state/sources/mmi-previ/<groupe>/` (le
   volume, pas l'image : `contraintes/` est écrasé à chaque déploiement).
   `appliquer_copies` remplace alors, pour les semestres de ce groupe, les
   modules de la copie livrée avec l'application. Toute l'ingestion et le
   solveur passent par là : une génération, la relecture de son brouillon et
   le redémarrage du serveur lisent donc la même maquette.

Les flux portent des noms d'enseignants et des commentaires internes : les
copies restent sur le serveur, et les routes n'en renvoient que des comptes
et des codes de modules.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import httpx

URL_PAR_DEFAUT = "https://mmi23x02.mmi-troyes.fr"
VAR_JETON = "CAL_IUT_MMI_PREVI_JETON"
VAR_URL = "CAL_IUT_MMI_PREVI_URL"
DELAI_S = 30.0

FLUX = ("maquette", "progression")
GROUPES: dict[str, tuple[str, ...]] = {
    "odd": ("S1", "S3", "S5"),
    "even": ("S2", "S4", "S6"),
}


class ErreurMmiPrevi(RuntimeError):
    """Message lisible par un administrateur, sans jeton ni détail réseau."""


class JetonAbsent(ErreurMmiPrevi):
    pass


class JetonRefuse(ErreurMmiPrevi):
    pass


class MmiPreviInjoignable(ErreurMmiPrevi):
    pass


class ReponseInattendue(ErreurMmiPrevi):
    pass


# ── Accès ──────────────────────────────────────────────────────────────


def jeton() -> str | None:
    valeur = (os.environ.get(VAR_JETON) or "").strip()
    return valeur or None


def configure() -> bool:
    return jeton() is not None


def url_de_base() -> str:
    return (os.environ.get(VAR_URL) or URL_PAR_DEFAUT).strip().rstrip("/")


def entetes() -> dict[str, str]:
    """En-têtes d'un appel à MMI Prévi : le jeton s'il est configuré."""
    valeur = jeton()
    entete = {"Accept": "application/json"}
    if valeur:
        entete["Authorization"] = f"Bearer {valeur}"
    return entete


def _semestres(groupe: str) -> tuple[str, ...]:
    if groupe not in GROUPES:
        raise ValueError(f"Groupe de semestres inconnu : {groupe!r}")
    return GROUPES[groupe]


def telecharger(flux: str, semestres: tuple[str, ...] | list[str]) -> list[dict[str, object]]:
    """Un flux (`maquette` ou `progression`) limité aux semestres demandés."""
    if flux not in FLUX:
        raise ValueError(f"Flux inconnu : {flux!r}")
    valeur = jeton()
    if not valeur:
        raise JetonAbsent(
            f"Le jeton d'accès à MMI Prévi n'est pas configuré sur le serveur (variable {VAR_JETON})."
        )
    base = url_de_base()
    if not base.startswith("https://"):
        # Le jeton ne voyage jamais en clair.
        raise MmiPreviInjoignable(f"L'adresse de MMI Prévi ({VAR_URL}) doit commencer par https://.")
    try:
        # Pas de redirection suivie : le jeton ne doit pas partir vers un
        # autre hôte que celui configuré.
        with httpx.Client(timeout=DELAI_S, follow_redirects=False) as client:
            reponse = client.get(
                f"{base}/export/{flux}",
                params={"semestres": ",".join(semestres)},
                headers={"Accept": "application/json", "Authorization": f"Bearer {valeur}"},
            )
    except httpx.HTTPError as exc:
        raise MmiPreviInjoignable(
            f"MMI Prévi ne répond pas ({type(exc).__name__}). Réessayez dans quelques minutes."
        ) from None
    if reponse.status_code == 401:
        raise JetonRefuse(
            "MMI Prévi refuse le jeton d'accès : il est invalide, révoqué ou expiré. "
            f"Demandez-en un nouveau et remplacez la variable {VAR_JETON} du serveur."
        )
    if reponse.status_code != 200:
        raise ReponseInattendue(f"MMI Prévi a répondu par une erreur ({reponse.status_code}) pour le flux {flux}.")
    try:
        contenu = reponse.json()
    except ValueError:
        raise ReponseInattendue(f"La réponse de MMI Prévi pour le flux {flux} n'est pas du JSON.") from None
    if not isinstance(contenu, list):
        raise ReponseInattendue(f"La réponse de MMI Prévi pour le flux {flux} n'est pas une liste de modules.")
    return contenu


# ── Contrôle de ce qui est reçu ────────────────────────────────────────


def _cle(module: dict[str, object]) -> tuple[str, str, str]:
    return (str(module.get("code_matiere")), str(module.get("semestre")), str(module.get("parcours")))


def _etiquette(module: dict[str, object]) -> dict[str, str]:
    code, semestre, parcours = _cle(module)
    return {"code": code, "nom": str(module.get("nom_matiere") or ""), "semestre": semestre, "parcours": parcours}


def controler(
    maquette: list[dict[str, object]],
    progression: list[dict[str, object]],
    semestres: tuple[str, ...],
) -> None:
    """Refuse ce que l'ingestion ne saurait pas lire, avant d'enregistrer
    quoi que ce soit."""
    if not maquette or not progression:
        raise ReponseInattendue(
            "MMI Prévi ne renvoie aucun module pour " + ", ".join(semestres) + ". Rien n'a été modifié."
        )
    sans_responsable: set[str] = set()
    for nom, modules in (("maquette", maquette), ("progression", progression)):
        for module in modules:
            if not isinstance(module, dict) or not all(
                isinstance(module.get(champ), str) and module.get(champ)
                for champ in ("code_matiere", "nom_matiere", "semestre", "parcours")
            ):
                raise ReponseInattendue(
                    f"Le flux {nom} de MMI Prévi contient un module sans code, intitulé, semestre ou parcours."
                )
            if module["semestre"] not in semestres:
                raise ReponseInattendue(
                    f"Le flux {nom} de MMI Prévi contient le module {module['code_matiere']} "
                    f"de {module['semestre']}, hors des semestres demandés."
                )
            responsable = module.get("lead")
            if not isinstance(responsable, dict) or not responsable.get("code"):
                sans_responsable.add(str(module["code_matiere"]))
    if sans_responsable:
        raise ReponseInattendue(
            "Ces modules n'ont pas de responsable dans MMI Prévi : "
            + ", ".join(sorted(sans_responsable))
            + ". Renseignez-le dans MMI Prévi puis recommencez. Rien n'a été modifié."
        )
    from cal_iut.ingestion.merge import merge_exports

    try:
        merge_exports(maquette, progression)
    except Exception as exc:  # noqa: BLE001 — toute forme inattendue = refus
        raise ReponseInattendue(
            f"Les flux de MMI Prévi ont une forme que l'application ne sait pas lire ({type(exc).__name__}). "
            "Rien n'a été modifié."
        ) from None


# ── Copies sur le volume ───────────────────────────────────────────────


def dossier_des_copies(racine: Path) -> Path:
    return racine / "data" / "state" / "sources" / "mmi-previ"


def _lire_json(chemin: Path) -> object | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lire_copie(racine: Path, groupe: str) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    dossier = dossier_des_copies(racine) / groupe
    maquette = _lire_json(dossier / "maquette.json")
    progression = _lire_json(dossier / "progression.json")
    if isinstance(maquette, list) and isinstance(progression, list) and maquette and progression:
        return maquette, progression
    return None


def etat_de_la_copie(racine: Path, groupe: str) -> dict[str, object] | None:
    """Ce qu'on sait d'une copie (date, auteur, comptes), sans son contenu."""
    if lire_copie(racine, groupe) is None:
        return None
    infos = _lire_json(dossier_des_copies(racine) / groupe / "infos.json")
    return infos if isinstance(infos, dict) else {}


def _ecrire(chemin: Path, contenu: object) -> None:
    temporaire = chemin.with_name(chemin.name + ".tmp")
    temporaire.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporaire, chemin)


def enregistrer_copie(
    racine: Path,
    groupe: str,
    maquette: list[dict[str, object]],
    progression: list[dict[str, object]],
    par: str,
) -> dict[str, object]:
    semestres = _semestres(groupe)
    dossier = dossier_des_copies(racine) / groupe
    dossier.mkdir(parents=True, exist_ok=True)
    infos: dict[str, object] = {
        "recuperee_le": datetime.now().astimezone().isoformat(timespec="seconds"),
        "par": par,
        "semestres": list(semestres),
        "modules": len(maquette),
        "avec_progression": sum(
            1 for m in progression if isinstance(m.get("progression"), dict) and m["progression"].get("definie")
        ),
    }
    # Les infos en dernier : une copie sans infos reste lisible.
    _ecrire(dossier / "maquette.json", maquette)
    _ecrire(dossier / "progression.json", progression)
    _ecrire(dossier / "infos.json", infos)
    return infos


def supprimer_copie(racine: Path, groupe: str) -> bool:
    _semestres(groupe)
    dossier = dossier_des_copies(racine) / groupe
    if not dossier.exists():
        return False
    shutil.rmtree(dossier)
    return True


def appliquer_copies(
    racine: Path,
    maquette: list[dict[str, object]],
    progression: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Pour chaque groupe dont une copie MMI Prévi existe, ses modules
    remplacent ceux des mêmes semestres. Les autres semestres ne bougent pas."""
    for groupe, semestres in GROUPES.items():
        copie = lire_copie(racine, groupe)
        if copie is None:
            continue
        maquette = [m for m in maquette if m.get("semestre") not in semestres] + copie[0]
        progression = [m for m in progression if m.get("semestre") not in semestres] + copie[1]
    return maquette, progression


def sources_en_vigueur(racine: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    """Maquette et progression réellement utilisées : la copie livrée dans
    `contraintes/`, corrigée par les copies MMI Prévi. `None` sans copie
    livrée."""
    maquette = _lire_json(racine / "contraintes" / "maquette.json")
    progression = _lire_json(racine / "contraintes" / "progression.json")
    if not isinstance(maquette, list) or not isinstance(progression, list):
        return None
    return appliquer_copies(racine, maquette, progression)


# ── Ce qui change ──────────────────────────────────────────────────────


def _volumes(module: dict[str, object]) -> tuple[float, float, float]:
    total = module.get("total") or module.get("volumes") or {}
    if not isinstance(total, dict):
        return (0.0, 0.0, 0.0)
    return tuple(float(total.get(t) or 0) for t in ("cm", "td", "tp"))  # type: ignore[return-value]


def differences(
    avant: list[dict[str, object]],
    apres: list[dict[str, object]],
    semestres: tuple[str, ...],
) -> dict[str, list[dict[str, str]]]:
    """Modules ajoutés, retirés, et dont les volumes ou le responsable
    changent, entre deux maquettes, pour les semestres donnés."""
    anciens = {_cle(m): m for m in avant if m.get("semestre") in semestres}
    nouveaux = {_cle(m): m for m in apres if m.get("semestre") in semestres}

    def _responsable(module: dict[str, object]) -> str:
        lead = module.get("lead")
        return str(lead.get("code")) if isinstance(lead, dict) else ""

    return {
        "ajoutes": [_etiquette(nouveaux[c]) for c in sorted(nouveaux.keys() - anciens.keys())],
        "retires": [_etiquette(anciens[c]) for c in sorted(anciens.keys() - nouveaux.keys())],
        "modifies": [
            _etiquette(nouveaux[c])
            for c in sorted(nouveaux.keys() & anciens.keys())
            if _volumes(nouveaux[c]) != _volumes(anciens[c]) or _responsable(nouveaux[c]) != _responsable(anciens[c])
        ],
    }


def recuperer(racine: Path, groupe: str, par: str) -> dict[str, object]:
    """Télécharge maquette et progression du groupe, les contrôle, puis les
    enregistre comme copie en vigueur. Rien n'est écrit en cas d'échec."""
    semestres = _semestres(groupe)
    maquette = telecharger("maquette", semestres)
    progression = telecharger("progression", semestres)
    controler(maquette, progression, semestres)
    en_vigueur = sources_en_vigueur(racine)
    infos = enregistrer_copie(racine, groupe, maquette, progression, par)
    return {
        "source": infos,
        "differences": differences(en_vigueur[0] if en_vigueur else [], maquette, semestres),
    }
