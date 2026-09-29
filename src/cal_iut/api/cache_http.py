"""Cache mémoire des lectures lourdes + validation conditionnelle (ETag / 304).

Principe (cf. `api/revision.py`) : une réponse ne dépend que de l'état
applicatif, et l'état ne change qu'avec la révision. La clé d'une réponse
est donc (révision, variante, chemin + paramètres) :

- l'ETag se calcule SANS rien construire — un client qui renvoie le bon
  `If-None-Match` reçoit un 304 vide avant tout calcul ;
- le corps, lui, n'est construit qu'une fois par révision puis resservi tel
  quel, déjà sérialisé (et compressé à la demande, une seule fois).

`Cache-Control: private, no-cache` : le navigateur GARDE la réponse mais
revalide à chaque usage (d'où le 304) — jamais de réponse périmée servie
sans demander. `private` parce que la variante dépend de qui demande (compte
connecté ou lien public, cf. `_CLES_PRIVEES_PAYLOAD` dans `api/main.py`) :
un cache partagé (proxy) ne doit jamais servir l'une à la place de l'autre.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from cal_iut.api import revision

CACHE_CONTROL_PRIVE = "private, no-cache"

# Niveau 6 plutôt que 9 : sur le payload `/app-state` (≈ 590 Ko), le 9 coûte
# nettement plus de temps pour quelques Ko gagnés seulement — et ce calcul-ci
# n'est fait qu'une fois par révision de toute façon.
_NIVEAU_GZIP = 6


def etag_pour(*parties: object) -> str:
    """ETag FAIBLE (`W/`) : la même donnée peut partir compressée ou non,
    donc deux représentations octet à octet différentes du même contenu —
    exactement ce que « faible » veut dire (RFC 9110 §8.8.1)."""
    brut = "|".join(str(p) for p in parties)
    return 'W/"' + hashlib.sha1(brut.encode("utf-8")).hexdigest()[:20] + '"'


def correspond(request: Request, etag: str) -> bool:
    """`If-None-Match` contient-il cet ETag ? Comparaison faible : on ignore
    le préfixe `W/` des deux côtés, et un proxy qui aurait retiré ou ajouté ce
    préfixe (nginx le fait sur une réponse qu'il recompresse) ne doit pas
    faire perdre le 304."""
    entete = request.headers.get("if-none-match")
    if not entete:
        return False
    if entete.strip() == "*":
        return True
    attendu = etag.removeprefix("W/")
    return any(candidat.strip().removeprefix("W/") == attendu for candidat in entete.split(","))


def reponse_304(etag: str, cache_control: str = CACHE_CONTROL_PRIVE) -> Response:
    return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})


@dataclass
class EntreeCache:
    etag: str
    corps: bytes
    media_type: str = "application/json"
    entetes: dict[str, str] = field(default_factory=dict)
    _gz: bytes | None = None

    def compresse(self) -> bytes:
        # Course bénigne : deux threads peuvent compresser en même temps la
        # toute première fois, le résultat est identique et le dernier gagne.
        if self._gz is None:
            self._gz = gzip.compress(self.corps, compresslevel=_NIVEAU_GZIP, mtime=0)
        return self._gz


def servir(request: Request, entree: EntreeCache, cache_control: str = CACHE_CONTROL_PRIVE) -> Response:
    """304 si le client a déjà cette version, sinon le corps — pré-compressé
    si le client l'accepte. `Content-Encoding` déjà posé : `GZipMiddleware`
    laisse alors passer la réponse telle quelle, sans la recompresser."""
    entetes = {"ETag": entree.etag, "Cache-Control": cache_control, **entree.entetes}
    if correspond(request, entree.etag):
        return reponse_304(entree.etag, cache_control)
    if len(entree.corps) >= 1000 and "gzip" in request.headers.get("accept-encoding", ""):
        entetes["Content-Encoding"] = "gzip"
        entetes["Vary"] = "Accept-Encoding"
        return Response(content=entree.compresse(), media_type=entree.media_type, headers=entetes)
    return Response(content=entree.corps, media_type=entree.media_type, headers=entetes)


def serialiser_json(contenu: object) -> bytes:
    """Même sortie que `JSONResponse` de FastAPI (compact, UTF-8 non échappé),
    faite une seule fois par révision au lieu d'une fois par requête.

    `jsonable_encoder` seulement en REPLI (`default=`), pour ce que `json` ne
    sait pas écrire seul (modèle Pydantic, date, ensemble...) : appliqué à
    tout le payload `/app-state` d'avance, il parcourait récursivement ses
    ≈ 590 Ko et coûtait à lui seul plus que le calcul du payload."""
    if isinstance(contenu, BaseModel):
        contenu = contenu.model_dump(mode="json")
    return json.dumps(
        contenu, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":"), default=jsonable_encoder
    ).encode("utf-8")


class CacheParRevision:
    """Réponses déjà construites, par clé, pour la révision COURANTE
    seulement : dès que la révision avance, tout est jeté d'un coup — rien
    ne peut survivre à une écriture.

    Borné (`taille_max`) : `/timetable` et `/api/v1/seances` ont une clé par
    combinaison de filtres, et un client malveillant ou maladroit ne doit
    pas pouvoir faire grossir la mémoire sans limite. Les plus anciennes
    entrées partent d'abord.
    """

    def __init__(self, taille_max: int = 256) -> None:
        self._taille_max = taille_max
        self._entrees: OrderedDict[tuple, EntreeCache] = OrderedDict()
        self._revision: int | None = None
        self._verrou = threading.Lock()
        # Un calcul à la fois : deux clients qui arrivent ensemble juste après
        # une écriture ne doivent pas recalculer deux fois les mêmes 150 ms —
        # le second attend et prend le résultat du premier.
        self._verrou_calcul = threading.Lock()

    def _lire(self, cle: tuple, numero: int) -> EntreeCache | None:
        with self._verrou:
            if self._revision != numero:
                self._entrees.clear()
                self._revision = numero
                return None
            entree = self._entrees.get(cle)
            if entree is not None:
                self._entrees.move_to_end(cle)
            return entree

    def _ecrire(self, cle: tuple, numero: int, entree: EntreeCache) -> None:
        with self._verrou:
            if self._revision != numero:
                # La révision a avancé PENDANT le calcul : ce résultat décrit
                # peut-être déjà un état périmé, il n'est pas gardé.
                return
            self._entrees[cle] = entree
            self._entrees.move_to_end(cle)
            while len(self._entrees) > self._taille_max:
                self._entrees.popitem(last=False)

    def obtenir(
        self,
        cle: tuple,
        construire: Callable[[], bytes],
        *,
        media_type: str = "application/json",
        entetes: dict[str, str] | None = None,
    ) -> EntreeCache:
        rev = revision.actuelle()
        entree = self._lire(cle, rev.numero)
        if entree is not None:
            return entree
        with self._verrou_calcul:
            rev = revision.actuelle()
            entree = self._lire(cle, rev.numero)
            if entree is not None:
                return entree
            corps = construire()
            entree = EntreeCache(
                etag=etag_pour(rev.numero, *cle), corps=corps, media_type=media_type, entetes=dict(entetes or {})
            )
            self._ecrire(cle, rev.numero, entree)
            return entree

    def vider(self) -> None:
        with self._verrou:
            self._entrees.clear()
            self._revision = None


def repondre(
    request: Request,
    cache: CacheParRevision,
    cle: tuple,
    construire: Callable[[], bytes],
    *,
    media_type: str = "application/json",
    cache_control: str = CACHE_CONTROL_PRIVE,
    entetes: dict[str, str] | None = None,
) -> Response:
    """Le chemin complet d'une lecture cachée : 304 immédiat si le client a
    déjà la version courante (sans rien calculer), sinon le corps en cache,
    sinon calcul puis mise en cache."""
    etag = etag_pour(revision.actuelle().numero, *cle)
    if correspond(request, etag):
        return reponse_304(etag, cache_control)
    entree = cache.obtenir(cle, construire, media_type=media_type, entetes=entetes)
    return servir(request, entree, cache_control)
