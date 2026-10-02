"""Révision de l'état visible — « est-ce que quelque chose a changé ? ».

Demande utilisateur (29/09/2026) : « une api entière pour exposer les données
et faire en sorte de limiter les connexions au serveur ». Sans ce compteur,
un client n'avait AUCUN moyen de savoir si le planning avait bougé sans tout
retélécharger : `/app-state` (≈ 590 Ko, ≈ 150 ms de calcul) repartait à
chaque rafraîchissement, et deux personnes qui éditaient en même temps ne
voyaient pas les changements l'une de l'autre avant un F5.

Un entier monotone et l'heure de sa dernière avance, rien de plus :

- toute écriture qui change ce que voit un client l'incrémente
  (`incrementer`, appelé depuis `api/main.py::_apres_ecriture_planning` et
  les autres chemins d'écriture, plus un middleware filet de sécurité) ;
- les lectures lourdes s'en servent comme clé de cache et d'ETag
  (`api/cache_http.py`) : tant qu'il ne bouge pas, rien n'est recalculé, et
  un client qui a déjà la bonne version reçoit un 304 sans corps ;
- `GET /api/v1/version` l'expose tel quel, pour un sondage à quelques octets.

Valeur de départ = l'heure du démarrage en millisecondes, et jamais moins
que l'heure courante ensuite : un simple compteur repartant de 1 au
redémarrage aurait pu redonner un numéro DÉJÀ vu par un client avant le
redémarrage, pour un tout autre état — et donc un 304 à tort sur un ETag qui
n'aurait plus rien à voir. Ainsi la révision reste croissante d'un processus
à l'autre (à moins de 1000 écritures par seconde, très loin du réel).

Les « sondes » couvrent ce qui change SANS passer par une écriture de l'API :
le passage de minuit (le statut passée / en cours / future des semaines en
dépend, cf. `calendar/academic.py::week_status`), un fichier de
configuration modifié sur le disque, ou un test qui remplace l'état
directement. Elles sont évaluées à chaque lecture de la révision : elles
doivent donc rester quasi gratuites (une sonde coûteuse se limite elle-même,
cf. `sonde_fichiers`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


@dataclass(frozen=True)
class Revision:
    numero: int
    modifie_le: datetime
    motif: str

    def iso(self) -> str:
        return self.modifie_le.isoformat()


def _maintenant_ms() -> int:
    return time.time_ns() // 1_000_000


_verrou = threading.Lock()
_courante = Revision(numero=_maintenant_ms(), modifie_le=datetime.now(UTC), motif="demarrage")
_sondes: dict[str, Callable[[], object]] = {}
_dernieres_valeurs: dict[str, object] = {}


def _avancer(motif: str) -> Revision:
    """À appeler SOUS `_verrou`."""
    global _courante
    numero = max(_courante.numero + 1, _maintenant_ms())
    _courante = Revision(numero=numero, modifie_le=datetime.now(UTC), motif=motif)
    return _courante


def incrementer(motif: str = "") -> Revision:
    """Signale une écriture visible. Ne lève jamais : une révision ratée ne
    doit pas faire échouer l'écriture qui vient de réussir."""
    with _verrou:
        return _avancer(motif or "ecriture")


def actuelle() -> Revision:
    """Révision courante, après avoir relu les sondes (cf. docstring du
    module). Une sonde qui lève est ignorée pour ce tour — elle ne bloque
    jamais une lecture."""
    with _verrou:
        for nom, sonde in list(_sondes.items()):
            try:
                valeur = sonde()
            except Exception:  # noqa: BLE001, S112 — une sonde cassée ne casse pas la lecture
                continue
            if nom in _dernieres_valeurs and _dernieres_valeurs[nom] != valeur:
                _avancer(f"sonde:{nom}")
            _dernieres_valeurs[nom] = valeur
        return _courante


def enregistrer_sonde(nom: str, sonde: Callable[[], object]) -> None:
    """Remplace une sonde existante du même nom (réimport en test, rechargement)."""
    with _verrou:
        _sondes[nom] = sonde
        _dernieres_valeurs.pop(nom, None)


def sonde_jour() -> object:
    # Date LOCALE du serveur, comme `calendar/academic.py::week_status`.
    return date.today()  # noqa: DTZ011


# Délai entre deux relectures des fichiers sondés. `tests/conftest.py` le met
# à 0 : chaque test a son dossier de configuration, et une empreinte gardée
# 5 s faisait avancer la révision au milieu du test suivant (ETag changé,
# 200 au lieu de 304 — CI du 02/10/2026).
INTERVALLE_SONDE_FICHIERS_S = 5.0


def sonde_fichiers(motifs: Callable[[], Iterable[Path]], intervalle_s: float | None = None) -> Callable[[], object]:
    """Empreinte (chemin, date de modification, taille) des fichiers donnés,
    recalculée au plus toutes les `intervalle_s` secondes (défaut :
    `INTERVALLE_SONDE_FICHIERS_S`, lu à chaque appel) : relire ~20 `stat()` à
    chaque requête sondée serait inutilement coûteux pour des fichiers qui ne
    changent qu'au déploiement ou à la main."""
    cache: dict[str, object] = {"quand": 0.0, "valeur": None}

    def _sonde() -> object:
        maintenant = time.monotonic()
        delai = INTERVALLE_SONDE_FICHIERS_S if intervalle_s is None else intervalle_s
        if cache["valeur"] is not None and maintenant - float(cache["quand"]) < delai:
            return cache["valeur"]
        empreinte = []
        for chemin in sorted(motifs()):
            try:
                st = chemin.stat()
            except OSError:
                continue
            empreinte.append((str(chemin), st.st_mtime_ns, st.st_size))
        cache["valeur"] = tuple(empreinte)
        cache["quand"] = maintenant
        return cache["valeur"]

    return _sonde


enregistrer_sonde("jour", sonde_jour)
