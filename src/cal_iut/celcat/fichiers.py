"""Écrire un fichier d'état sans jamais le laisser à moitié écrit.

POURQUOI CE MODULE EXISTE. Tous les fichiers de `data/state/` étaient écrits
par un `Path.write_text` direct — vingt-sept appels répartis sur dix-sept
modules. Un `write_text` tronque le fichier PUIS écrit : entre les deux, le
fichier existe et il est vide ou incomplet. Trois choses peuvent s'y glisser,
et les trois arrivent en production :

1. LE LECTEUR DE L'AUTRE CONTENEUR. `backend` et `celcat-nuit` partagent
   `data/state/` par un volume Docker. L'un lit pendant que l'autre écrit.
   `drainage.dernier()` documente déjà le symptôme — « un fichier illisible
   (écriture lue à mi-chemin, les deux conteneurs partageant le volume) ».

2. L'ARRÊT AU MAUVAIS MOMENT. Un redéploiement Dokploy redémarre tous les
   services, y compris au milieu d'une écriture.

3. ET SURTOUT, LA PERTE DÉFINITIVE. `etat.charger()` ne lève pas sur un JSON
   tronqué : il retombe sur `_vide()`. Le `sauver()` suivant persiste alors
   ce vide. Or `celcat_sync.json` porte le journal des correspondances
   séance -> `event_id` — 268 lignes en production, et le SEUL rempart contre
   les doublons. Le perdre ferait repartir tout le planning en création,
   c'est-à-dire en double dans Celcat.

LE REMÈDE tient en deux lignes : on écrit dans un fichier temporaire, puis on
le renomme sur la cible. `os.replace` est atomique sur ext4 (le conteneur)
comme sur NTFS (le poste de développement) : un lecteur voit soit l'ancien
contenu entier, soit le nouveau, jamais un entre-deux, et jamais un fichier
absent.

LE TEMPORAIRE VIT DANS LE MÊME RÉPERTOIRE que la cible, jamais dans `/tmp` :
`os.replace` n'est atomique qu'à l'intérieur d'un même système de fichiers, et
`data/state/` est précisément un point de montage distinct du reste.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def ecrire_atomique(chemin: Path, texte: str, *, encoding: str = "utf-8") -> None:
    """Écrit `texte` dans `chemin` en une seule étape visible.

    Crée le répertoire parent au besoin — tous les appelants le faisaient
    déjà, et l'oublier ici les obligerait à le refaire.

    Le temporaire est nettoyé même si le renommage échoue : un
    `celcat_sync.json.a3f8b2.tmp` abandonné à chaque échec finirait par
    remplir le volume, et personne ne saurait d'où il vient.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)

    descripteur, provisoire = tempfile.mkstemp(
        dir=str(chemin.parent), prefix=f".{chemin.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descripteur, "w", encoding=encoding, newline="\n") as f:
            f.write(texte)
            # Le contenu doit être SUR LE DISQUE avant le renommage. Sans ce
            # `fsync`, un arrêt brutal peut laisser le nom en place et le
            # contenu perdu : on aurait remplacé un fichier valide par un
            # fichier vide, soit exactement ce qu'on répare.
            f.flush()
            os.fsync(f.fileno())
        os.replace(provisoire, chemin)
    except BaseException:
        try:
            os.unlink(provisoire)
        except OSError:
            pass
        raise


def ecrire_json(chemin: Path, donnees: Any, **options: Any) -> None:
    """`ecrire_atomique` pour du JSON, avec les options maison par défaut.

    `ensure_ascii=False` et `indent=2` sont ce qu'écrivaient déjà tous les
    appelants : un fichier d'état se relit à la main quand quelque chose ne
    va pas, et des accents récrits en séquences d'échappement le rendraient
    illisible au moment précis où on en a besoin.
    """
    options.setdefault("ensure_ascii", False)
    options.setdefault("indent", 2)
    ecrire_atomique(chemin, json.dumps(donnees, **options))


class FichierEtatIllisible(RuntimeError):
    """Un fichier d'état existe mais ne se relit pas (JSON tronqué, forme
    inattendue). Il a été mis de côté sous `copie` pour être réparé à la main.

    POURQUOI LEVER plutôt que rendre une liste vide (audit du 29/09/2026,
    P0-4) : `custom_sessions.json` illisible rendait `[]` sans bruit ; l'ajout
    suivant réécrivait le fichier avec une seule séance, toutes les autres
    étaient perdues, et le démarrage d'après purgeait leurs placements de la
    base comme « orphelins ». Une erreur visible coûte une action refusée ;
    un vide silencieux coûte les données.
    """

    def __init__(self, chemin: Path, copie: Path | None) -> None:
        self.chemin = Path(chemin)
        self.copie = copie
        ou = f" (copie conservée : {copie.name})" if copie is not None else ""
        super().__init__(
            f"Fichier d'état illisible : {self.chemin.name}{ou}. "
            "Restaurez-le depuis la copie ou une sauvegarde avant de continuer."
        )


def mettre_de_cote(chemin: Path) -> Path | None:
    """Renomme `chemin` en `<nom>.corrompu-<horodatage>` à côté de lui.

    Rend le nouveau chemin, ou `None` si le renommage a échoué (fichier déjà
    déplacé par un autre processus, droits) — l'erreur d'origine reste plus
    utile à remonter que celle-ci.
    """
    from datetime import datetime

    chemin = Path(chemin)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    copie = chemin.with_name(f"{chemin.name}.corrompu-{horodatage}")
    try:
        os.replace(chemin, copie)
    except OSError:
        return None
    return copie


def lire_json_etat(chemin: Path, defaut: Any, *, types: type | tuple[type, ...] | None = None) -> Any:
    """Relit un fichier d'état JSON écrit par `ecrire_json`.

    - fichier absent : `defaut` (état initial légitime) ;
    - JSON illisible, ou racine qui n'est pas du type attendu (`types`) : le
      fichier est mis de côté (`mettre_de_cote`) et `FichierEtatIllisible`
      est levée — jamais `defaut`, cf. la docstring de l'exception ;
    - erreur d'entrée/sortie : remontée telle quelle, le fichier est laissé
      en place (il n'est pas forcément abîmé).
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return defaut
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FichierEtatIllisible(chemin, mettre_de_cote(chemin)) from None
    if types is not None and not isinstance(brut, types):
        raise FichierEtatIllisible(chemin, mettre_de_cote(chemin))
    return brut
