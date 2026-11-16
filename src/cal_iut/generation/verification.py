"""« À régler avant de générer » (lot 5 du chantier « Nouveau semestre depuis
l'interface », 16/11/2026).

Le même audit des données que celui de l'ouvrier (`cal-iut audit`), mais
lancé AVANT le calcul, depuis l'écran : la liste de ce qui empêcherait le
solveur d'aboutir s'affiche en une seconde au lieu d'être découverte après
des heures de calcul. Tant qu'il reste une erreur, la génération ne se
lance pas (`api/generations_routes.py`) et l'ouvrier s'arrête
(`generation/ouvrier.py`).

Ne lance jamais le solveur et ne touche ni à la base ni au planning en
service : seuls les fichiers de `data/generated/` sont réécrits, comme le
fait l'ouvrier au début d'une génération.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from cal_iut.generation import taches

# Ce contrôle compare des dates de modification de fichiers : dans une image
# Docker elles sont toutes celles du déploiement, et la génération relit les
# sources de toute façon.
CONTROLES_IGNORES = frozenset({"donnees.sources_plus_recentes"})

# Contrôles de cohérence du CODE (le tableau de bord couvre-t-il toutes les
# règles du solveur ?). Un utilisateur n'y peut rien : signalés, jamais
# bloquants.
PREFIXES_NON_BLOQUANTS = ("couverture.",)

_CLES_DU_RESUME = {"erreur": "erreurs", "alerte": "alertes", "info": "infos"}


class GenerationEnCours(RuntimeError):
    """La vérification réécrit `data/generated/`, que l'ouvrier est en train
    de lire."""


def est_bloquant(constat: dict) -> bool:
    return constat.get("severite") == "erreur" and not str(constat.get("controle", "")).startswith(
        PREFIXES_NON_BLOQUANTS
    )


def ecrire_les_fichiers_generes(racine: Path, resultat: object) -> str:
    """Les mêmes fichiers que `cal-iut ingest` : l'audit les relit. Renvoie le
    JSON des séances."""
    seances = json.dumps([s.model_dump() for s in resultat.sessions], ensure_ascii=False, indent=2)
    genere = racine / "data" / "generated"
    genere.mkdir(parents=True, exist_ok=True)
    (genere / "sessions.json").write_text(seances, encoding="utf-8")
    (genere / "courses.json").write_text(
        json.dumps([c.model_dump() for c in resultat.courses], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (genere / "stats.json").write_text(
        json.dumps(resultat.stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return seances


def horizon(racine: Path, groupe: str) -> int:
    from cal_iut.calendar.academic import default_horizon_weeks
    from cal_iut.ingestion.constraints_loader import load_all_constraints
    from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR

    return default_horizon_weeks(load_all_constraints(racine).calendar, SEMESTRE_GROUP_ANCHOR[groupe])


def rapport_des_donnees(racine: Path, groupe: str, *, weeks: int | None, fi_max_week: int | None) -> dict:
    """L'audit des données du groupe, sans les contrôles qui n'ont pas de
    sens sur le serveur. Suppose `data/generated/` à jour."""
    from cal_iut.audit import run_audit

    rapport = run_audit(
        racine,
        weeks=weeks or horizon(racine, groupe),
        fi_max_week=fi_max_week,
        semestre_group=groupe,
    ).as_dict()
    ignores = [c for c in rapport["constats"] if c["controle"] in CONTROLES_IGNORES]
    if ignores:
        rapport["constats"] = [c for c in rapport["constats"] if c not in ignores]
        for constat in ignores:
            cle = _CLES_DU_RESUME.get(constat["severite"])
            if cle:
                rapport["resume"][cle] = max(0, rapport["resume"][cle] - 1)
    return rapport


def bloquants(rapport: dict) -> list[dict]:
    return [c for c in rapport.get("constats", []) if est_bloquant(c)]


def _erreur(controle: str, message: str, quoi_faire: str) -> dict:
    return {"severite": "erreur", "controle": controle, "message": message, "quoi_faire": quoi_faire, "details": []}


def avant_de_generer(groupe: str, racine: Path | None = None) -> dict:
    """Ce qu'il reste à régler avant de générer ce groupe de semestres.

    `bloquant` : la génération serait refusée. `constats` : erreurs d'abord,
    puis alertes (les simples informations ne sont pas renvoyées)."""
    if groupe not in taches.GROUPES:
        raise ValueError(f"Groupe de semestres inconnu : {groupe!r}")
    if taches.active() is not None:
        raise GenerationEnCours("Une génération est en cours.")
    racine = racine or taches.RACINE
    params = taches.parametres_par_defaut(groupe)
    semestres = ", ".join(taches.GROUPES[groupe]["semestres"])
    seances = 0
    try:
        from cal_iut.ingestion.pipeline import run_ingestion

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resultat = run_ingestion(racine / "data" / "config", semestre_group=groupe)
        seances = len(resultat.sessions)
    except Exception as exc:  # noqa: BLE001 — une source illisible est un point à régler, pas une panne
        constats = [_erreur(
            "chargement.sources",
            f"Les données du semestre ne se lisent pas : {exc}",
            "Vérifier la maquette et la progression (bouton « Récupérer depuis MMI Prévi »).",
        )]
    else:
        if not seances:
            constats = [_erreur(
                "chargement.aucune_seance",
                f"Aucune séance à placer : la maquette ne contient aucun module pour {semestres}.",
                "Récupérer la maquette de ces semestres depuis MMI Prévi.",
            )]
        else:
            ecrire_les_fichiers_generes(racine, resultat)
            rapport = rapport_des_donnees(
                racine, groupe, weeks=params["weeks"], fi_max_week=params["fi_max_week"]
            )
            constats = [c for c in rapport["constats"] if c["severite"] in ("erreur", "alerte")]
    constats = [{**c, "bloquant": est_bloquant(c)} for c in constats]
    constats.sort(key=lambda c: (not c["bloquant"], c["severite"] != "erreur"))
    return {
        "semestre_group": groupe,
        "seances": seances,
        "bloquant": any(c["bloquant"] for c in constats),
        "erreurs": sum(1 for c in constats if c["bloquant"]),
        "alertes": sum(1 for c in constats if not c["bloquant"]),
        "constats": constats,
    }
