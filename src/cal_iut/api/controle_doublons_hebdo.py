"""Contrôle HEBDOMADAIRE automatique des doublons salle/enseignant — suite du
retour Kyllian Bresson 25/09/2026 (cf. `api/doublons.py`, qui reste le calcul
« à la demande »). Jules Crevoisier, 25/09/2026 : « on veut faire quelque
chose qui vérifie CHAQUE SEMAINE s'il n'y a pas deux salles [...] assignées en
même temps [...] et pareil [...] un prof [...] à deux endroits en même
temps » — ce module ajoute le volet AUTOMATIQUE, SANS ÉCRAN à ouvrir, qui
manquait à `doublons()` (déjà exposé, mais seulement à la demande via
`GET /controles/doublons`).

MÊME PATRON que la sauvegarde quotidienne (`api/sauvegardes.py::
snapshot_si_necessaire`, hooké dans `api/main.py::_apres_ecriture_planning`
ET `startup()`) : un filet au plus une fois par période, jamais deux, et qui
rattrape la période manquée au démarrage si personne n'a rien modifié depuis.
Repris tel quel plutôt qu'inventé un autre mécanisme (queue Celery, cron
séparé...) — les deux filets partagent déjà les mêmes points d'appel dans
`main.py`, la même isolation de test (`tests/conftest.py::
_fichiers_etat_isoles`), et le même contrat « ne lève jamais » ; un troisième
mécanisme pour la même famille de besoin (vérification périodique à l'écrit
planning + au démarrage) aurait dupliqué l'infrastructure sans rien
apporter. Seule différence : la période est la SEMAINE ISO (`date.
isocalendar()`), pas le jour calendaire — semaine ISO plutôt que semaine
solveur/grille : point de repère STABLE, indépendant du calendrier
académique (contrairement à l'indice solveur ou au libellé « Semaine N », cf.
mémoire projet « Trois numérotations de semaines » — ce contrôle porte sur
« cette semaine civile a-t-elle déjà été vérifiée », pas sur une semaine
d'enseignement précise).

UN SEUL FICHIER (`data/state/controle_doublons_hebdo.json`, PAS un fichier
par run comme `sauvegardes.py`) : un tableau des 8 derniers contrôles, du
plus ancien au plus récent — assez pour voir la tendance à l'écran (« À
traiter »), sans grossir indéfiniment. Écriture ATOMIQUE
(`cal_iut.celcat.fichiers.ecrire_atomique`) : même volume Docker partagé
`backend`/`celcat-nuit` que `sauvegardes.py`, mêmes risques de lecture à
moitié écrite.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from cal_iut.api import doublons as doublons_module
from cal_iut.celcat.fichiers import ecrire_atomique

FORMAT_CONTROLE = "cal-iut-controle-doublons-hebdo/1"

# Conservés : les 8 derniers contrôles (auto ou « Vérifier maintenant »),
# assez pour une tendance sur ~2 mois sans grossir indéfiniment (todo Jules
# 25/09/2026, pas de rétention en jours demandée contrairement aux
# sauvegardes — un tableau borné en NOMBRE d'entrées suffit ici).
MAX_RUNS = 8


def _path() -> Path:
    # `data/state/`, pas `data/config/` : état généré, pas figé dans l'image
    # Docker (cf. mémoire projet, même raison que `forced_pending.py`).
    return Path(__file__).resolve().parents[3] / "data" / "state" / "controle_doublons_hebdo.json"


def _aujourdhui() -> date:
    """Point d'injection unique pour « aujourd'hui » — les tests gèlent la
    date via `monkeypatch.setattr(controle_doublons_hebdo, "_aujourdhui",
    ...)`, même principe que `sauvegardes.py::_aujourdhui`."""
    return date.today()  # noqa: DTZ011


def _semaine_iso(jour: date) -> str:
    """« 2026-W39 » — semaine ISO 8601 (lundi-dimanche), STABLE d'une année
    sur l'autre contrairement à l'indice solveur ou au libellé académique
    (« Semaine 5 », vacances comprises) : ce contrôle ne porte que sur « la
    semaine civile a-t-elle déjà tourné », jamais sur une semaine
    d'enseignement précise."""
    annee_iso, semaine_iso, _jour_iso = jour.isocalendar()
    return f"{annee_iso}-W{semaine_iso:02d}"


def _charger() -> list[dict[str, object]]:
    chemin = _path()
    if not chemin.exists():
        return []
    try:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(contenu, list):
        return []
    return contenu


def dernier() -> dict[str, object] | None:
    """Le contrôle le plus récent — `GET /controles/doublons/hebdo` (`None`
    si le contrôle n'a jamais tourné, cf. écran « jamais exécuté »)."""
    runs = _charger()
    return runs[-1] if runs else None


def deja_fait_cette_semaine() -> bool:
    run = dernier()
    return run is not None and run.get("semaine_iso") == _semaine_iso(_aujourdhui())


def _cle_doublon(d: dict[str, object]) -> tuple[object, ...]:
    """Clé STABLE (semaine, jour, créneau, type, ressource) pour apparier un
    doublon d'un run à l'autre — les listes de `seances` peuvent différer
    (une séance déplacée ailleurs mais qui recrée le même doublon un cran
    plus loin resterait, à raison, un doublon DIFFÉRENT)."""
    return (d["semaine"], d["jour"], d["creneau"], d["type"], d["ressource"])


def _diff(
    precedent: list[dict[str, object]] | None, actuel: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """`(nouveaux, résolus)` entre le run précédent et `actuel` — `None`
    (jamais aucun run avant) rend les deux listes vides : rien à comparer à
    un premier contrôle, afficher « 111 nouveaux » au tout premier passage
    serait un mensonge (il n'y a pas de contrôle précédent), cf.
    `premier_controle` sur le run rendu."""
    if precedent is None:
        return [], []
    cles_avant = {_cle_doublon(d) for d in precedent}
    cles_apres = {_cle_doublon(d) for d in actuel}
    nouveaux = [d for d in actuel if _cle_doublon(d) not in cles_avant]
    resolus = [d for d in precedent if _cle_doublon(d) not in cles_apres]
    return nouveaux, resolus


def executer_maintenant(state: object) -> dict[str, object]:
    """Exécute le contrôle MAINTENANT, sans se soucier du filet
    hebdomadaire — geste explicite (`POST /controles/doublons/hebdo`,
    bouton « Vérifier maintenant »), même distinction que `sauvegardes.
    prendre_maintenant` vs `snapshot_si_necessaire`. Balaie TOUTES les
    semaines (`doublons.doublons(state)` sans filtre) : le contrôle porte
    sur l'ensemble du planning stocké, pas une semaine en particulier."""
    runs = _charger()
    precedent = runs[-1] if runs else None
    actuel = doublons_module.doublons(state)

    nouveaux, resolus = _diff(
        precedent["doublons"] if precedent else None, actuel
    )
    par_type: dict[str, int] = {}
    for d in actuel:
        par_type[d["type"]] = par_type.get(d["type"], 0) + 1

    jour = _aujourdhui()
    run: dict[str, object] = {
        "format": FORMAT_CONTROLE,
        "date": jour.isoformat(),
        "semaine_iso": _semaine_iso(jour),
        "genere_le": datetime.now(UTC).isoformat(),
        "total": len(actuel),
        "par_type": par_type,
        "doublons": actuel,
        "nouveaux": nouveaux,
        "resolus": resolus,
        "premier_controle": precedent is None,
    }

    runs.append(run)
    runs = runs[-MAX_RUNS:]
    ecrire_atomique(_path(), json.dumps(runs, ensure_ascii=False, indent=2))
    return run


def verifier_si_necessaire(state: object) -> dict[str, object] | None:
    """Point d'appel UNIQUE depuis `api/main.py` — `_apres_ecriture_planning`
    (premier écrit de la semaine ISO) ET `startup()` (semaine jamais faite,
    ex. redémarrage un lundi où personne n'a encore rien modifié). NE LÈVE
    JAMAIS : un contrôle raté ne doit ni faire échouer un placement, ni
    empêcher le démarrage de l'application (même contrat que `sauvegardes.
    snapshot_si_necessaire`). Rend le run pris (ou `None` si déjà fait cette
    semaine, ou si le contrôle a échoué) — utile aux tests, ignoré des deux
    appelants réels."""
    try:
        if deja_fait_cette_semaine():
            return None
        return executer_maintenant(state)
    except Exception:  # noqa: BLE001 — jamais fatal, cf. docstring.
        return None
