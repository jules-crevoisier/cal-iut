"""La correction envoyée pour une semaine survit-elle à l'onglet qu'on quitte ?

Retour utilisateur de Jules Crevoisier, 25/09/2026 : « quand par exemple on
corrige un écart, ça envoie, ça met qu'on l'a envoyé à corriger, donc ça fait
une attente du passage du worker. Si on quitte et qu'on revient sur l'onglet
Celcat, ça le remet en mode qu'on peut le recorriger. »

`useBoucleCelcat` (frontend) enchaîne déjà « mettre en file -> attendre le
worker -> demander un relevé -> relire la comparaison » — mais entièrement en
état React, qui meurt avec l'onglet. Ce module porte la même information côté
SERVEUR, pour que revenir sur l'écran la retrouve plutôt que de proposer un
« Corriger » qui redirait ce qui est déjà parti.

Ce n'est PAS un détail d'affichage : Jules et Kyllian travaillent depuis des
postes différents, et le worker qu'ils attendent est le MÊME, partagé. L'état
ne peut donc pas vivre dans le navigateur de l'un ou de l'autre — il vit ici,
comme l'instantané (`instantane.py`) et la trace du worker (`drainage.py`),
avec la même écriture atomique.

« Le worker est-il repassé depuis ? » reste une comparaison D'HORODATAGES
SERVEUR entre eux, jamais l'horloge du navigateur (cf. la docstring de
`useBoucleCelcat.ts`) : on retient la trace du worker AU MOMENT de la mise en
file (`passe_le_avant`), et on la compare à sa trace actuelle.

L'ÉTAT S'EFFACE DE LUI-MÊME, en deux cas :

1. le worker est repassé depuis (sa trace a changé) ET un relevé plus récent
   que la mise en file est arrivé — le travail est fait, vérifié sur du
   frais ;
2. un délai généreux (45 min) s'est écoulé sans que (1) se produise — le
   worker recule jusqu'à trente minutes entre deux passages après des échecs
   répétés (cf. `nuit-quotidienne.sh`), 45 minutes reste donc un délai qui
   laisse une vraie chance au cas normal avant de conclure à une panne. Ce
   cas est nommé "expire", jamais "échoué" : les jobs restent en file
   (`file_attente.py` n'est pas touché ici) et repartiront au passage
   suivant. Rien n'est perdu, seul CE SUIVI cesse d'être fiable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cal_iut.celcat.fichiers import ecrire_json

# Au-delà, le suivi est considéré périmé : le worker recule jusqu'à 30 min
# entre deux passages après des échecs répétés (cf. RECUL_MAX dans
# `nuit-quotidienne.sh`) — 45 minutes laisse une vraie marge avant de conclure
# à une panne plutôt qu'à un passage simplement tardif.
TIMEOUT_SECONDES = 45 * 60


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_correction_en_cours.json"


@dataclass
class EtatCorrection:
    """Ce que l'écran doit savoir pour REPRENDRE, plutôt que reproposer
    « Corriger » comme si rien n'était parti."""

    semaine: int
    # "absente" : rien en file pour cette semaine, jamais suivi ou déjà résolu.
    # "en_cours" : mise en file, en attente du worker et/ou d'un relevé frais.
    # "termine" : le worker est repassé ET un relevé plus récent est arrivé.
    # "expire" : le délai a couru sans (1) — toujours en file, plus suivi.
    etat: str
    mise_en_file_le: str | None = None
    par: str = ""
    total: int = 0
    message: str = ""


def _lire_doc() -> dict[str, Any]:
    chemin = _path()
    if not chemin.exists():
        return {}
    try:
        import json

        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Illisible (lecture à mi-écriture par l'autre conteneur, ou fichier
        # corrompu) : mieux vaut « rien de suivi » qu'une exception au milieu
        # de l'écran — même choix que `instantane.py` et `drainage.py`.
        return {}
    return contenu if isinstance(contenu, dict) else {}


def _ecrire_doc(doc: dict[str, Any]) -> None:
    ecrire_json(_path(), doc)


def enregistrer(semaine: int, *, par: str, total: int) -> None:
    """Note qu'une correction vient d'être mise en file pour `semaine`.

    Capture la trace ACTUELLE du worker (`drainage.dernier().passe_le`) au
    moment même de la mise en file : c'est le point de repère qui permettra
    plus tard de dire « il est repassé depuis », par simple comparaison de
    deux horodatages serveur.
    """
    from cal_iut.celcat.drainage import dernier

    doc = _lire_doc()
    doc[str(semaine)] = {
        "mise_en_file_le": datetime.now(UTC).isoformat(),
        "par": par,
        "total": total,
        "passe_le_avant": dernier().passe_le,
    }
    _ecrire_doc(doc)


def effacer(semaine: int) -> None:
    """Retire le suivi de `semaine`. Ne touche JAMAIS `file_attente` : ce
    n'est qu'un suivi, pas la file elle-même."""
    doc = _lire_doc()
    if str(semaine) in doc:
        del doc[str(semaine)]
        _ecrire_doc(doc)


def _apres(a: str | None, b: str | None) -> bool:
    """`a` est-il strictement postérieur à `b` ? Comparaison de deux
    horodatages ISO, jamais l'horloge du navigateur ni même celle de CE
    processus — les deux valeurs comparées viennent toujours d'un fichier
    d'état, écrit par un conteneur ou par un autre."""
    if not a or not b:
        return False
    try:
        ta = datetime.fromisoformat(a)
        tb = datetime.fromisoformat(b)
    except ValueError:
        return False
    if ta.tzinfo is None:
        ta = ta.replace(tzinfo=UTC)
    if tb.tzinfo is None:
        tb = tb.replace(tzinfo=UTC)
    return ta > tb


def lire(semaine: int) -> EtatCorrection:
    """L'état de suivi pour `semaine`, et l'EFFACE si le suivi est conclu —
    fait (worker repassé + relevé frais) ou périmé (délai dépassé). L'appelant
    voit donc UNE FOIS le statut final avant qu'il ne disparaisse, exactement
    ce qu'il faut pour afficher le bon message sans laisser un suivi mort
    trainer indéfiniment."""
    from cal_iut.celcat.drainage import dernier
    from cal_iut.celcat.instantane import lire as lire_instantane

    doc = _lire_doc()
    brut = doc.get(str(semaine))
    if not isinstance(brut, dict):
        return EtatCorrection(semaine=semaine, etat="absente")

    mise_en_file_le = brut.get("mise_en_file_le") if isinstance(brut.get("mise_en_file_le"), str) else None
    par = str(brut.get("par") or "")
    try:
        total = int(brut.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    passe_le_avant = brut.get("passe_le_avant") if isinstance(brut.get("passe_le_avant"), str) else None

    bilan = dernier()
    releve = lire_instantane()

    worker_repasse = bilan.passe_le is not None and bilan.passe_le != passe_le_avant
    releve_frais = _apres(releve.releve_le, mise_en_file_le)

    if worker_repasse and releve_frais:
        effacer(semaine)
        return EtatCorrection(
            semaine=semaine,
            etat="termine",
            mise_en_file_le=mise_en_file_le,
            par=par,
            total=total,
            message="Corrections vérifiées sur un relevé tout frais.",
        )

    age: float | None = None
    if mise_en_file_le:
        try:
            t = datetime.fromisoformat(mise_en_file_le)
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - t).total_seconds()
        except ValueError:
            age = None

    if age is not None and age > TIMEOUT_SECONDES:
        effacer(semaine)
        return EtatCorrection(
            semaine=semaine,
            etat="expire",
            mise_en_file_le=mise_en_file_le,
            par=par,
            total=total,
            message=(
                "Les corrections envoyées restent en file — le worker n'est pas "
                "encore repassé, ou pas depuis un relevé récent. Rien n'est perdu."
            ),
        )

    return EtatCorrection(
        semaine=semaine,
        etat="en_cours",
        mise_en_file_le=mise_en_file_le,
        par=par,
        total=total,
        message="Corrections envoyées — en attente du passage du worker…",
    )
