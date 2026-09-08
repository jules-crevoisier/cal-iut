"""Trace du dernier passage du worker, pour que l'interface puisse le montrer.

Retour utilisateur 08/09/2026, juste après le premier envoi réel de
corrections : « là on n'a pas vraiment de vue où l'on voit ce qu'il se passe
si on appuie sur corriger ».

Le bouton annonce « 38 corrections mises en file », puis plus rien. Combien
attendent encore ? Le worker est-il passé ? Qu'a-t-il fait ? L'information
existait — dans `docker compose logs celcat-nuit`, c'est-à-dire nulle part
pour qui utilise l'application.

Le worker vit dans un AUTRE conteneur que l'API : il dépose donc son compte
rendu dans le volume partagé, comme pour l'instantané, et l'API le sert.

L'ÂGE est enregistré avec le reste, pour la même raison que partout ailleurs
cette semaine : un compte rendu de trois heures présenté comme l'état
courant induit en erreur au moment précis où l'on cherche à vérifier. Une
file de 38 jobs « depuis 2 secondes » et « depuis 3 heures » n'appellent pas
le même geste.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_drainage.json"


@dataclass
class Bilan:
    """Ce que le worker a fait à son dernier passage, et QUAND."""

    en_attente: int = 0
    reussis: int = 0
    echecs: int = 0
    ignores: int = 0
    resume: str = ""
    passe_le: str | None = None
    age_secondes: float | None = None


def enregistrer(
    *,
    en_attente: int,
    reussis: int,
    echecs: int,
    ignores: int,
    resume: str,
    passe_le: str | None = None,
) -> None:
    """Dépose le compte rendu d'un passage. Ne lève jamais : un worker ne
    doit pas échouer parce qu'il n'a pas pu écrire sa trace."""
    chemin = _path()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(
                {
                    "passe_le": passe_le or datetime.now(timezone.utc).isoformat(),
                    "en_attente": en_attente,
                    "reussis": reussis,
                    "echecs": echecs,
                    "ignores": ignores,
                    "resume": resume,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def dernier() -> Bilan:
    """Le dernier passage connu, avec son âge.

    Sans passage, rend un `Bilan` dont `passe_le` vaut None — jamais
    « 0 réussi », qui serait indiscernable d'un échec total alors que le
    worker n'est simplement jamais passé.

    Un fichier illisible (écriture lue à mi-chemin, les deux conteneurs
    partageant le volume) rend la même chose : mieux vaut « aucun passage
    connu » qu'une exception au milieu de l'écran.
    """
    chemin = _path()
    if not chemin.exists():
        return Bilan()
    try:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Bilan()
    if not isinstance(contenu, dict):
        return Bilan()

    passe_le = contenu.get("passe_le")
    age: float | None = None
    if isinstance(passe_le, str):
        try:
            horodatage = datetime.fromisoformat(passe_le)
            if horodatage.tzinfo is None:
                horodatage = horodatage.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - horodatage).total_seconds()
        except ValueError:
            age = None

    def _entier(cle: str) -> int:
        try:
            return int(contenu.get(cle) or 0)
        except (TypeError, ValueError):
            return 0

    return Bilan(
        en_attente=_entier("en_attente"),
        reussis=_entier("reussis"),
        echecs=_entier("echecs"),
        ignores=_entier("ignores"),
        resume=str(contenu.get("resume") or ""),
        passe_le=passe_le if isinstance(passe_le, str) else None,
        age_secondes=age,
    )
