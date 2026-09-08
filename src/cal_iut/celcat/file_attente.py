"""File d'attente des écritures Celcat (create / update / delete).

Le worker Docker consomme cette file. Le planning HTTP n'attend jamais
la réponse Live : `enfiler` est le seul geste immédiat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cal_iut.celcat.lecture import EvenementCelcat, est_fantome, est_ferie

_CONNUS: dict[int, EvenementCelcat] = {}


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_file_attente.json"


def _lire() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(brut, list):
        return []
    return [x for x in brut if isinstance(x, dict)]


def _ecrire(jobs: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def cle_job(job: dict[str, Any]) -> tuple[str, str, str]:
    action = str(job.get("action") or "")
    session_id = str(job.get("session_id") or "")
    event_id = job.get("event_id")
    event_id_s = "" if event_id in (None, "") else str(event_id)
    return (action, session_id, event_id_s)


def enfiler(job: dict[str, Any]) -> None:
    """Ajoute un job, SANS jamais en empiler deux identiques.

    Deux chemins produisent le même job — le balayage `executer_job_nuit` et
    le bouton « Corriger » — et deux clics suffisent aussi. Or deux jobs de
    même clé dans un même cycle sont traités DEUX FOIS : deux appels RPC,
    donc deux évènements dans Celcat. La relecture du journal annoncée par
    `_consommer_file` ne rattrape pas le coup, puisqu'elle lit le document
    chargé une seule fois au début du cycle (trouvé le 08/09/2026 par l'audit
    de la chaîne).

    La clé reste `(action, session_id, event_id)` : « créer » et « supprimer »
    la même séance sont deux intentions distinctes, pas un doublon — les
    confondre ferait disparaître une suppression demandée.
    """
    jobs = _lire()
    nouveau = dict(job)
    if any(cle_job(existant) == cle_job(nouveau) for existant in jobs):
        return
    jobs.append(nouveau)
    _ecrire(jobs)


def lister() -> list[dict[str, Any]]:
    return _lire()


def vider() -> None:
    _ecrire([])


def retirer_traites(identites: list[dict[str, Any]]) -> None:
    """Retire de la file les jobs dont `(action, session_id, event_id)`
    correspond EXACTEMENT à l'une des identités données — jamais un
    `vider()` global, qui perdrait les jobs arrivés entre-temps ou ceux
    qui ont échoué (RPC/réseau) et doivent rester pour la prochaine nuit."""
    if not identites:
        return
    cibles = {cle_job(i) for i in identites}
    restants = [j for j in _lire() if cle_job(j) not in cibles]
    _ecrire(restants)


def retirer_semaines(semaines: set[int]) -> int:
    """Retire les jobs visant ces semaines. Rend le nombre retiré.

    Sert à RECONSTRUIRE une semaine depuis la comparaison : on efface ce
    qu'on croyait devoir faire, on ré-enfile ce qui diverge réellement.

    Ciblé par semaine, jamais un `vider()` global : un déplacement de séance
    demandé en semaine 12 n'a pas à disparaître parce qu'on resynchronise la
    semaine 1. C'est la difference entre « je reconstruis ce périmètre » et
    « j'efface tout », et seule la première est sûre quand l'API continue
    d'enfiler pendant ce temps.
    """
    if not semaines:
        return 0
    jobs = _lire()
    restants = []
    retires = 0
    for job in jobs:
        brut = job.get("semaine")
        try:
            sem = int(brut) if brut is not None else None
        except (TypeError, ValueError):
            sem = None
        # Un job sans semaine lisible est CONSERVÉ : on ne sait pas s'il
        # relève du périmètre, et le perdre serait pire que le garder.
        if sem is not None and sem in semaines:
            retires += 1
            continue
        restants.append(job)
    if retires:
        _ecrire(restants)
    return retires


def repousser_en_fin(identites: list[dict[str, Any]]) -> None:
    """Renvoie ces jobs à la FIN de la file, sans en perdre aucun.

    Un job en échec RPC reste en file — c'est voulu : une panne réseau ou un
    Celcat momentanément indisponible doit être réessayé. Mais le cycle est
    borné et prend les PREMIERS jobs : un job qui échoue SYSTÉMATIQUEMENT
    (ressource supprimée côté Celcat, module absent du catalogue) reste donc
    en tête indéfiniment, et les jobs derrière ne sont jamais atteints.

    Constaté en production le 08/09/2026 : la file est descendue 504 -> 493
    -> 491, puis n'a plus bougé pendant que le worker rejouait toutes les
    cinq minutes les vingt-cinq mêmes échecs, quatre cent dix jobs sains
    attendant derrière. Une file confisquée par sa propre tête, avec toutes
    les apparences du bon fonctionnement.

    REPOUSSER N'EST PAS JETER. Aucun compteur d'échecs, aucune mise au
    rebut : un job impossible revient à chaque tour de file et continue donc
    de figurer au bilan, là où on peut le voir. Écarter en silence est
    exactement ce qui a coûté trois jours cette semaine.

    La file est RELUE ici, jamais réordonnée depuis une copie prise en début
    de cycle : l'API y enfile pendant que le worker travaille, et un
    déplacement de séance fait entre-temps serait sinon effacé.
    """
    if not identites:
        return
    cibles = {cle_job(i) for i in identites}
    jobs = _lire()
    devant = [j for j in jobs if cle_job(j) not in cibles]
    derriere = [j for j in jobs if cle_job(j) in cibles]
    if not derriere:
        return
    _ecrire(devant + derriere)


def retenir_evenement(ev: EvenementCelcat) -> None:
    _CONNUS[ev.event_id] = ev


def evenement_connu(event_id: int) -> EvenementCelcat | None:
    return _CONNUS.get(event_id)


def autoriser_suppression(ev: EvenementCelcat, categorie: str | None = None) -> bool:
    retenir_evenement(ev)
    if est_ferie(ev) or est_fantome(ev):
        return False
    if ev.protected == "Y":
        return False
    if categorie == "celcat_en_plus":
        return False
    return True
