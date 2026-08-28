"""Mot de passe unique partagé — bloque l'accès à l'API (donc à l'app, qui
n'affiche rien sans elle) sauf pour trois exceptions volontaires :

1. les endpoints d'authentification eux-mêmes (`/auth/*`) et `/health` ;
2. une session valide (mot de passe déjà saisi) ;
3. un lien personnel (prof ou groupe, `?t=<code>`) — PUBLIC, sans jeton
   secret : retour utilisateur 28/08/2026, après un aller-retour sur le
   sujet. D'abord un jeton HMAC signé avait été mis en place (« jeton secret
   par lien (Recommandé) », choisi explicitement à l'époque) ; le lien
   GROUPE n'avait ensuite jamais reçu l'équivalent (scope initial limité aux
   profs), ce qui cassait "Aucun planning résolu" en navigation privée sur
   un vrai lien de groupe déployé. Plutôt que d'ajouter le même mécanisme
   pour les groupes, retour utilisateur final : « pour les lien groupe et
   prof on s'en fiche on veut qu'il soit public » — `?t=` n'est donc plus
   vérifié cryptographiquement, sa seule présence suffit.

Limite assumée et documentée (pas cachée), désormais plus large qu'avant :
n'importe qui devinant l'URL exacte d'un lien personnel (ou la reconstruisant
à partir d'un trigramme/id de groupe connu) y accède sans mot de passe — et,
comme avant ce changement, ce lien donne accès aux MÊMES endpoints qu'une
session mot de passe (`/app-state`/`/timetable` renvoient tout, filtré côté
client, jamais scopé par enseignant/groupe). Accepté explicitement par
l'utilisateur : la contrainte réelle reste de ne PAS publier/deviner le lien
lui-même, pas une protection cryptographique dessus.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path

_SESSION_COOKIE = "cal_iut_session"
_SESSION_MAX_AGE_S = 90 * 24 * 3600  # 90 jours — outil interne, pas de données ultra-sensibles.

_SECRET_ENV = "CAL_IUT_SECRET_KEY"
_PASSWORD_ENV = "CAL_IUT_PASSWORD"


def _secret_path() -> Path:
    # `data/state/`, pas `data/` directement — cf. `api/state.py::DB_PATH`
    # pour pourquoi (config vs état, volume Docker).
    return Path(__file__).resolve().parents[3] / "data" / "state" / ".secret_key"


_secret_cache: str | None = None


def get_secret() -> str:
    """Secret HMAC — stable entre redémarrages (sinon TOUS les liens profs
    déjà envoyés casseraient à chaque redéploiement). Priorité à la
    variable d'environnement (Docker/Dokploy, survit à un volume recréé
    différemment) ; à défaut, un fichier dans `data/` (survit tant que ce
    dossier persiste — c'est déjà un volume monté en Docker, cf.
    Dockerfile) généré une seule fois."""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    env = os.environ.get(_SECRET_ENV)
    if env:
        _secret_cache = env
        return _secret_cache
    path = _secret_path()
    if path.exists():
        _secret_cache = path.read_text(encoding="utf-8").strip()
        return _secret_cache
    generated = os.urandom(32).hex()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generated, encoding="utf-8")
    _secret_cache = generated
    return _secret_cache


def get_password() -> str | None:
    """`None` = pas configuré. Traité comme un blocage total côté appelant
    (`require_auth`) plutôt qu'un accès libre par défaut — un oubli de
    configuration à un vrai déploiement ne doit jamais se traduire par
    « aucune protection », ce serait pire que ne pas avoir cette fonction
    du tout."""
    return os.environ.get(_PASSWORD_ENV) or None


def _sign(payload: str) -> str:
    return hmac.new(get_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_token() -> str:
    expiry = str(int(time.time()) + _SESSION_MAX_AGE_S)
    return f"{expiry}.{_sign(expiry)}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expiry, sig = token.split(".", 1)
    if not hmac.compare_digest(_sign(expiry), sig):
        return False
    try:
        return int(expiry) > time.time()
    except ValueError:
        return False


def verify_personal_link_param(value: str | None) -> bool:
    """Lien personnel (prof ou groupe, `?t=<code>`) — PUBLIC depuis le
    28/08/2026 : la seule présence d'une valeur suffit, plus de vérification
    cryptographique (cf. docstring du module pour l'historique de cette
    décision). `value` porte encore le code prof/groupe (utile pour
    déboguer un lien à l'œil), mais son contenu n'est plus significatif ici
    — seule sa présence compte."""
    return bool(value)


SESSION_COOKIE = _SESSION_COOKIE
SESSION_MAX_AGE_S = _SESSION_MAX_AGE_S
