"""Limitation de débit des routes publiques d'authentification — audit du
29/09/2026, P1-3.

Sans elle : force brute illimitée sur `/auth/login` (chaque essai coûte un
hachage Argon2 de 64 Mo : quelques dizaines de requêtes parallèles saturent
la mémoire du conteneur), et envoi de mails en masse au nom du domaine par
`/auth/signup` et `/auth/forgot-password` (quota Resend, réputation
d'expéditeur).

Fenêtre glissante EN MÉMOIRE, par clé (`"login:email:<adresse>"`,
`"login:ip:<adresse IP>"`...). Suffisant ici : un seul processus uvicorn
sert l'API. Un redémarrage remet les compteurs à zéro, ce qui est acceptable
pour un frein (ce n'est pas un verrouillage de compte).

L'adresse IP est `request.client.host` : derrière nginx, uvicorn doit faire
confiance à `X-Forwarded-For` posé par le proxy, et À LUI SEUL (cf.
`api/anti_aspiration.py::proxys_de_confiance` et `cli.py::cmd_serve`), sinon
tous les clients partagent l'adresse du proxy — d'où des plafonds par IP
larges, le vrai frein étant la clé par email.

`SeauxAJetons` (29/09/2026) : la même idée généralisée au trafic courant
(`api/anti_aspiration.py`). Un seau par clé, deux nombres par seau — coût
et mémoire constants par client, là où la fenêtre glissante ci-dessous
garde un horodatage par essai (très bien pour 10 essais, pas pour 600).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

# Au-delà, un balayage retire les clés dont la fenêtre est vide : des
# milliers d'emails inventés ne doivent pas faire grossir la mémoire sans fin.
_BALAYAGE_AU_DELA = 10_000


class Limiteur:
    def __init__(self) -> None:
        self._essais: dict[str, deque[float]] = {}
        self._fenetres: dict[str, float] = {}
        self._verrou = threading.Lock()

    def verifier(self, cle: str, max_essais: int, fenetre_s: float) -> None:
        """Compte un essai pour `cle`, ou lève 429 si `max_essais` ont déjà
        eu lieu dans les `fenetre_s` dernières secondes (l'essai refusé
        n'est pas compté)."""
        maintenant = time.monotonic()
        with self._verrou:
            if len(self._essais) > _BALAYAGE_AU_DELA:
                self._balayer(maintenant)
            file = self._essais.setdefault(cle, deque())
            self._fenetres[cle] = fenetre_s
            while file and maintenant - file[0] >= fenetre_s:
                file.popleft()
            if len(file) >= max_essais:
                attente = max(1, math.ceil(fenetre_s - (maintenant - file[0])))
                minutes = max(1, math.ceil(attente / 60))
                raise HTTPException(
                    429,
                    f"Trop de tentatives. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}.",
                    headers={"Retry-After": str(attente)},
                )
            file.append(maintenant)

    def oublier(self, cle: str) -> None:
        with self._verrou:
            self._essais.pop(cle, None)
            self._fenetres.pop(cle, None)

    def vider(self) -> None:
        with self._verrou:
            self._essais.clear()
            self._fenetres.clear()

    def _balayer(self, maintenant: float) -> None:
        for cle in list(self._essais):
            file = self._essais[cle]
            if not file or maintenant - file[-1] >= self._fenetres.get(cle, 0):
                del self._essais[cle]
                self._fenetres.pop(cle, None)


limiteur = Limiteur()


class SeauxAJetons:
    """Seau à jetons par clé : `capacite` jetons au plus (la rafale
    tolérée), remplis au rythme de `debit` jetons par seconde. Une requête
    consomme un jeton ; sans jeton disponible elle est en dépassement.

    Mémoire bornée : au-delà de `_BALAYAGE_AU_DELA` clés, un balayage retire
    les seaux redevenus pleins (client inactif depuis assez longtemps pour
    que l'oublier ne change rien). Thread-safe."""

    def __init__(self) -> None:
        # clé -> [jetons restants, instant du dernier remplissage]
        self._seaux: dict[str, list[float]] = {}
        self._params: dict[str, tuple[float, float]] = {}
        self._verrou = threading.Lock()

    def consommer(self, cle: str, debit: float, capacite: float) -> float | None:
        """Prend un jeton. Rend `None` si c'était possible, sinon l'attente
        en secondes avant le prochain jeton (rien n'est consommé)."""
        maintenant = time.monotonic()
        with self._verrou:
            seau = self._seaux.get(cle)
            if seau is None:
                if len(self._seaux) > _BALAYAGE_AU_DELA:
                    self._balayer(maintenant)
                seau = self._seaux[cle] = [capacite, maintenant]
            else:
                seau[0] = min(capacite, seau[0] + (maintenant - seau[1]) * debit)
                seau[1] = maintenant
            self._params[cle] = (debit, capacite)
            if seau[0] >= 1.0:
                seau[0] -= 1.0
                return None
            return (1.0 - seau[0]) / debit if debit > 0 else float("inf")

    def vider(self) -> None:
        with self._verrou:
            self._seaux.clear()
            self._params.clear()

    def __len__(self) -> int:
        return len(self._seaux)

    def _balayer(self, maintenant: float) -> None:
        for cle in list(self._seaux):
            jetons, instant = self._seaux[cle]
            debit, capacite = self._params.get(cle, (0.0, 0.0))
            if jetons + (maintenant - instant) * debit >= capacite:
                del self._seaux[cle]
                self._params.pop(cle, None)


def ip_cliente(request: Request) -> str:
    return request.client.host if request.client else "inconnue"


def limiter(request: Request, action: str, *, email: str | None, par_ip: tuple[int, float],
            par_email: tuple[int, float] | None = None) -> None:
    """Applique les deux plafonds d'une action : par IP, puis par email."""
    limiteur.verifier(f"{action}:ip:{ip_cliente(request)}", *par_ip)
    if email and par_email is not None:
        limiteur.verifier(f"{action}:email:{email}", *par_email)
