"""Instantané de ce que contient Celcat, relevé par le sidecar.

Le conteneur qui sert l'application n'a ni VPN ni navigateur, et c'est
délibéré : la passerelle URCA pousse un tunnel COMPLET, donc monter le VPN
là détournerait tout le trafic sortant et couperait le site public (cf.
`celcat/reseau.py::_connecter_openconnect`). Aucun appel synchrone « lis
Celcat maintenant » n'est donc possible depuis l'API.

Seul le sidecar peut lire Celcat. Il dépose un relevé dans le volume partagé
(`data/state/`, monté par `backend` et `celcat-nuit`), et l'API le sert tel
quel. Ce module est le contrat entre les deux — volontairement PUR : aucun
réseau, aucun navigateur, juste deux fichiers JSON. C'est ce qui le rend
testable sans VPN.

Deux exigences le structurent.

1. L'ÂGE compte autant que le contenu. Un relevé de deux heures présenté
   comme l'état courant induirait en erreur exactement au moment où l'on
   cherche à vérifier quelque chose. La semaine du 07/09/2026 a montré ce
   que coûte une information qui a l'air fraîche sans l'être — un worker qui
   annonçait « file d'attente drainée » sans rien écrire.

2. Le rafraîchissement est une DEMANDE, pas un ordre. Le bouton pose un
   drapeau que le sidecar honore à son prochain passage. Le dire franchement
   (« relevé demandé, en cours ») vaut mieux qu'un sablier qui laisse croire
   à du direct.

Cadence : deux heures (retour utilisateur 08/09/2026, « l'instantané sur
Celcat c'est un peu chiant pour la libération du VPN, on peut mettre toutes
les 2h et on peut fetch au click »). Entre deux relevés, le VPN reste
disponible pour l'équipe — il est partagé avec le compte Celcat, et une
session tenue est une session que personne d'autre ne peut ouvrir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Au-delà, le relevé est signalé périmé et un nouveau est dû.
FRAICHEUR_SECONDES = 2 * 3600


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_instantane.json"


def _path_demande() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_instantane_demande.json"


@dataclass
class Releve:
    """Ce que le sidecar a vu dans Celcat, et QUAND."""

    evenements: list[dict[str, Any]] = field(default_factory=list)
    groupes: list[str] = field(default_factory=list)
    releve_le: str | None = None
    age_secondes: float | None = None
    erreur: str | None = None

    @property
    def perime(self) -> bool:
        """Vrai tant qu'aucun relevé n'existe, ou qu'il dépasse la cadence.
        L'interface s'en sert pour ne jamais présenter un vieux relevé comme
        l'état courant."""
        return self.age_secondes is None or self.age_secondes > FRAICHEUR_SECONDES


def _lire_json(chemin: Path) -> dict[str, Any] | None:
    if not chemin.exists():
        return None
    try:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return contenu if isinstance(contenu, dict) else None


def enregistrer(
    evenements: list[dict[str, Any]],
    *,
    groupes: list[str],
    releve_le: str | None = None,
    erreur: str | None = None,
) -> None:
    """Dépose un relevé. `releve_le` n'est explicite que pour les tests :
    en usage réel c'est l'instant de l'écriture."""
    chemin = _path()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(
            {
                "releve_le": releve_le or datetime.now(timezone.utc).isoformat(),
                "groupes": list(groupes),
                "evenements": list(evenements),
                "erreur": erreur,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def lire() -> Releve:
    """Le dernier relevé, avec son âge. Sans relevé, rend un `Releve` vide
    dont `releve_le` vaut None — jamais une liste vide qui se lirait
    « Celcat ne contient rien »."""
    contenu = _lire_json(_path())
    if contenu is None:
        return Releve()

    releve_le = contenu.get("releve_le")
    age: float | None = None
    if isinstance(releve_le, str):
        try:
            horodatage = datetime.fromisoformat(releve_le)
            if horodatage.tzinfo is None:
                horodatage = horodatage.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - horodatage).total_seconds()
        except ValueError:
            age = None

    evenements = contenu.get("evenements")
    groupes = contenu.get("groupes")
    return Releve(
        evenements=evenements if isinstance(evenements, list) else [],
        groupes=groupes if isinstance(groupes, list) else [],
        releve_le=releve_le if isinstance(releve_le, str) else None,
        age_secondes=age,
        erreur=contenu.get("erreur"),
    )


def demander() -> None:
    """Pose la demande de rafraîchissement (bouton « Rafraîchir »).

    Idempotent : cliquer trois fois ne provoque pas trois relevés — chacun
    prendrait le VPN partagé pour rien.
    """
    chemin = _path_demande()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps({"demande_le": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def demande_en_cours() -> bool:
    return _path_demande().exists()


def consommer_demande() -> bool:
    """Prend la demande s'il y en a une, et la retire.

    La retirer est essentiel : une demande qui resterait ferait relever le
    sidecar à CHAQUE cycle, donc reprendre le VPN en boucle — exactement ce
    que la cadence de deux heures cherche à éviter.
    """
    chemin = _path_demande()
    if not chemin.exists():
        return False
    try:
        chemin.unlink()
    except OSError:
        return False
    return True


def releve_du() -> bool:
    """Faut-il relever maintenant ? Oui si aucun relevé n'existe, s'il a
    dépassé la cadence, ou si quelqu'un l'a demandé — c'est tout l'intérêt
    du bouton que de forcer avant l'échéance."""
    return demande_en_cours() or lire().perime
