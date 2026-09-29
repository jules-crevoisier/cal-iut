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
confiance à `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`, cf. Dockerfile), sinon
tous les clients partagent l'adresse du proxy — d'où des plafonds par IP
larges, le vrai frein étant la clé par email.
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


def ip_cliente(request: Request) -> str:
    return request.client.host if request.client else "inconnue"


def limiter(request: Request, action: str, *, email: str | None, par_ip: tuple[int, float],
            par_email: tuple[int, float] | None = None) -> None:
    """Applique les deux plafonds d'une action : par IP, puis par email."""
    limiteur.verifier(f"{action}:ip:{ip_cliente(request)}", *par_ip)
    if email and par_email is not None:
        limiteur.verifier(f"{action}:email:{email}", *par_email)
