"""File d'attente des écritures Celcat (create / update / delete).

Le worker Docker consomme cette file. Le planning HTTP n'attend jamais la
réponse Live : `enfiler` est le seul geste immédiat.

UN RÉPERTOIRE, UN FICHIER PAR JOB — et non plus un tableau JSON unique.

Le tableau avait un défaut qu'aucune relecture ne pouvait corriger : toute
opération le réécrivait EN ENTIER. Or `backend` et `celcat-nuit` sont deux
conteneurs qui partagent `data/state/` par un volume, et qui y écrivent tous
les deux — l'API à chaque déplacement de séance, le worker toutes les trente
secondes. Entre le `_lire()` du worker et son `_ecrire()`, un `enfiler` de
l'API est donc perdu : un cours déplacé qui ne part jamais, sans erreur et
sans trace. `repousser_en_fin` documentait déjà qu'il fallait RELIRE la file
plutôt que réordonner une copie ; relire rétrécit la fenêtre, mais ne la
ferme pas.

Un fichier par job la supprime. Il n'y a plus de section critique : le
backend crée un fichier, le worker en délie un autre, ils ne touchent jamais
les mêmes octets. Et comme le nom du fichier EST la clé d'unicité, la
déduplication devient une propriété du système de fichiers plutôt qu'une
boucle de comparaison.

Le prix à payer est un `scandir` par `lister()`. La file n'a jamais dépassé
le millier de jobs, et le coût réel d'un cycle se compte en minutes de VPN :
quelques millisecondes de lecture ne pèsent rien en face.

MIGRATION AUTOMATIQUE. Le tableau historique est converti au premier usage
puis renommé `.migre` — le déploiement n'a rien à faire, et le fichier reste
là si l'on veut revenir en arrière.

CE QUE LE JOB PORTE EN PLUS. `ordre` tient le rang FIFO (c'est lui que
`repousser_en_fin` réécrit), et `echecs` / `dernier_motif` /
`prochaine_tentative` / `statut` préparent la mise en quarantaine : un job
qui échoue toujours doit cesser de coûter du VPN à chaque tour, SANS jamais
disparaître en silence. Ces clés voyagent avec le job ; tout le code en aval
ne lit que les siennes et les ignore.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from cal_iut.celcat.fichiers import ecrire_json
from cal_iut.celcat.lecture import EvenementCelcat, est_fantome, est_ferie

_CONNUS: dict[int, EvenementCelcat] = {}

# Rang du dernier job enfilé PAR CE PROCESSUS. `time.time_ns()` suffirait en
# théorie, mais rien ne garantit sa résolution : deux `enfiler` consécutifs
# pourraient rendre le même entier, et l'ordre de la file deviendrait alors
# celui du nom de fichier, c'est-à-dire un hachage. Ce garde-fou rend la
# suite strictement croissante quoi qu'en dise l'horloge.
_dernier_ordre = 0


def _path() -> Path:
    """Le tableau HISTORIQUE. Conservé pour la migration — et parce que les
    tests s'isolent en remplaçant cette fonction, ce dont `_repertoire`
    hérite sans qu'ils aient à le savoir."""
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_file_attente.json"


def _repertoire() -> Path:
    return _path().parent / "celcat_file"


def cle_job(job: dict[str, Any]) -> tuple[str, str, str]:
    action = str(job.get("action") or "")
    session_id = str(job.get("session_id") or "")
    event_id = job.get("event_id")
    event_id_s = "" if event_id in (None, "") else str(event_id)
    return (action, session_id, event_id_s)


def _nom(cle: tuple[str, str, str]) -> str:
    """Le nom de fichier d'un job — sa clé d'unicité, hachée.

    Haché plutôt que composé en clair pour deux raisons. Un `session_id`
    contient des caractères qu'un chemin n'accepte pas partout, et
    `WRA305M-S3-TD-1-but2-creacom-fc-td-gh` frôle déjà les limites de
    longueur une fois combiné à une action et à un event_id.

    SHA-1 tronqué : ce n'est pas une empreinte de sécurité, juste un nom
    court et stable. Une collision sur seize hexadécimaux demanderait des
    milliards de jobs ; la file en a vu cinq cents.
    """
    return hashlib.sha1("|".join(cle).encode("utf-8")).hexdigest()[:16] + ".json"


def _prochain_ordre() -> int:
    global _dernier_ordre
    _dernier_ordre = max(time.time_ns(), _dernier_ordre + 1)
    return _dernier_ordre


def _lire_job(chemin: Path) -> dict[str, Any] | None:
    """Un job, ou None s'il est illisible.

    Ne lève jamais : le fichier peut être lu au moment où l'autre conteneur
    l'écrit. Un job illisible est simplement sauté pour ce tour — il sera là
    au suivant. C'est toute la différence avec l'ancien tableau, dont une
    lecture à mi-écriture faisait disparaître la file ENTIÈRE.
    """
    try:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return contenu if isinstance(contenu, dict) else None


def _migrer() -> None:
    """Convertit le tableau historique en fichiers unitaires, une seule fois.

    Renomme plutôt que supprime : si quelque chose tourne mal après
    déploiement, la file d'origine est encore là, intacte et lisible.
    """
    legacy = _path()
    if not legacy.exists():
        return
    try:
        brut = json.loads(legacy.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        brut = []
    for job in brut if isinstance(brut, list) else []:
        if isinstance(job, dict):
            _poser(job)
    try:
        legacy.replace(legacy.with_name(legacy.name + ".migre"))
    except OSError:
        return


def _poser(job: dict[str, Any]) -> bool:
    """Écrit le job s'il n'existe pas déjà. Rend True s'il a été ajouté.

    L'existence fait foi, et on ne réécrit JAMAIS un job déjà là : il porte
    peut-être trois échecs et une quarantaine, que ré-enfiler remettrait à
    zéro. Un job qui échoue depuis ce matin ne doit pas redevenir neuf parce
    que quelqu'un a recliqué sur « Corriger ».
    """
    repertoire = _repertoire()
    repertoire.mkdir(parents=True, exist_ok=True)
    chemin = repertoire / _nom(cle_job(job))
    if chemin.exists():
        return False
    complet = dict(job)
    complet.setdefault("ordre", _prochain_ordre())
    complet.setdefault("echecs", 0)
    complet.setdefault("dernier_motif", "")
    complet.setdefault("prochaine_tentative", None)
    complet.setdefault("statut", "pret")
    ecrire_json(chemin, complet)
    return True


def enfiler(job: dict[str, Any]) -> None:
    """Ajoute un job, SANS jamais en empiler deux identiques.

    Deux chemins produisent le même job — le balayage `executer_job_nuit` et
    le bouton « Corriger » — et deux clics suffisent aussi. Or deux jobs de
    même clé dans un même cycle sont traités DEUX FOIS : deux appels RPC,
    donc deux évènements dans Celcat.

    La clé reste `(action, session_id, event_id)` : « créer » et « supprimer »
    la même séance sont deux intentions distinctes, pas un doublon — les
    confondre ferait disparaître une suppression demandée.

    Depuis que la clé est le NOM DU FICHIER, deux processus qui enfilent le
    même job au même instant produisent toujours un seul fichier. L'ancienne
    version comparait une liste lue avant d'écrire : deux enfilages
    simultanés passaient tous les deux le test.
    """
    _migrer()
    _poser(job)


def lister() -> list[dict[str, Any]]:
    """Les jobs, du plus ancien au plus récent.

    Le tri porte sur `ordre` puis sur le nom : `ordre` peut manquer sur un
    job migré depuis un tableau écrit avant cette version, et deux jobs sans
    rang doivent quand même sortir dans un ordre stable d'un appel à
    l'autre — sans quoi un cycle borné ne verrait pas deux fois les mêmes.
    """
    _migrer()
    repertoire = _repertoire()
    if not repertoire.exists():
        return []
    try:
        entrees = list(os.scandir(repertoire))
    except OSError:
        return []
    jobs: list[tuple[int, str, dict[str, Any]]] = []
    for entree in entrees:
        if not entree.name.endswith(".json"):
            continue
        job = _lire_job(Path(entree.path))
        if job is None:
            continue
        try:
            rang = int(job.get("ordre") or 0)
        except (TypeError, ValueError):
            rang = 0
        jobs.append((rang, entree.name, job))
    jobs.sort(key=lambda t: (t[0], t[1]))
    return [job for _rang, _fichier, job in jobs]


def vider() -> None:
    _migrer()
    repertoire = _repertoire()
    if not repertoire.exists():
        return
    try:
        entrees = list(os.scandir(repertoire))
    except OSError:
        return
    for entree in entrees:
        if not entree.name.endswith(".json"):
            continue
        try:
            os.unlink(entree.path)
        except OSError:
            continue


def retirer_traites(identites: list[dict[str, Any]]) -> None:
    """Retire de la file les jobs dont `(action, session_id, event_id)`
    correspond EXACTEMENT à l'une des identités données — jamais un
    `vider()` global, qui perdrait les jobs arrivés entre-temps ou ceux
    qui ont échoué (RPC/réseau) et doivent rester pour la prochaine nuit."""
    if not identites:
        return
    repertoire = _repertoire()
    for identite in identites:
        try:
            (repertoire / _nom(cle_job(identite))).unlink(missing_ok=True)
        except OSError:
            continue


def retirer_semaines(semaines: set[int]) -> int:
    """Retire les jobs visant ces semaines. Rend le nombre retiré.

    Sert à RECONSTRUIRE une semaine depuis la comparaison : on efface ce
    qu'on croyait devoir faire, on ré-enfile ce qui diverge réellement.

    Ciblé par semaine, jamais un `vider()` global : un déplacement de séance
    demandé en semaine 12 n'a pas à disparaître parce qu'on resynchronise la
    semaine 1. C'est la différence entre « je reconstruis ce périmètre » et
    « j'efface tout », et seule la première est sûre quand l'API continue
    d'enfiler pendant ce temps.
    """
    if not semaines:
        return 0
    retires = 0
    repertoire = _repertoire()
    for job in lister():
        brut = job.get("semaine")
        try:
            sem = int(brut) if brut is not None else None
        except (TypeError, ValueError):
            sem = None
        # Un job sans semaine lisible est CONSERVÉ : on ne sait pas s'il
        # relève du périmètre, et le perdre serait pire que le garder.
        if sem is None or sem not in semaines:
            continue
        try:
            (repertoire / _nom(cle_job(job))).unlink(missing_ok=True)
        except OSError:
            continue
        retires += 1
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

    REPOUSSER N'EST PAS JETER. Aucune mise au rebut : un job impossible
    revient à chaque tour de file et continue donc de figurer au bilan, là
    où on peut le voir.

    Seul le RANG des jobs concernés est réécrit, chacun dans son propre
    fichier. Un job enfilé par l'API pendant ce temps n'est pas touché — ce
    que la version en tableau ne pouvait pas promettre, puisqu'elle
    réécrivait la file entière.
    """
    if not identites:
        return
    repertoire = _repertoire()
    # Le plancher se prend sur la file TELLE QU'ELLE EST : se fier à
    # l'horloge suffirait dans le cas courant, mais un rang venu d'un
    # conteneur en avance ferait alors passer les repoussés devant.
    plancher = time.time_ns()
    for job in lister():
        try:
            plancher = max(plancher, int(job.get("ordre") or 0))
        except (TypeError, ValueError):
            continue
    for decalage, identite in enumerate(identites, start=1):
        chemin = repertoire / _nom(cle_job(identite))
        job = _lire_job(chemin)
        if job is None:
            continue
        job["ordre"] = plancher + decalage
        ecrire_json(chemin, job)


def marquer_echec(identite: dict[str, Any], motif: str) -> None:
    """Compte un échec sur ce job et retient son motif.

    Existe pour que la quarantaine soit possible : un job qui échoue pour la
    même raison depuis quatre-vingt-sept tours n'a aucune chance d'aboutir au
    quatre-vingt-huitième, et chaque tentative coûte une session du compte
    Celcat partagé. Le compteur repart à un quand le MOTIF change — une
    panne réseau puis un vrai refus sont deux histoires différentes.

    N'écarte rien par elle-même : elle compte, et c'est le drainage qui
    décidera. Écarter en silence est exactement ce qui a coûté trois jours.
    """
    chemin = _repertoire() / _nom(cle_job(identite))
    job = _lire_job(chemin)
    if job is None:
        return
    precedent = str(job.get("dernier_motif") or "")
    try:
        compte = int(job.get("echecs") or 0)
    except (TypeError, ValueError):
        compte = 0
    job["echecs"] = compte + 1 if motif == precedent else 1
    job["dernier_motif"] = motif
    ecrire_json(chemin, job)


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
