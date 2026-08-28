"""Mot de passe unique partagé — bloque l'accès à l'API (donc à l'app, qui
n'affiche rien sans elle) sauf pour deux exceptions volontaires :

1. les endpoints d'authentification eux-mêmes (`/auth/*`) et `/health` ;
2. une requête portant un jeton personnel valide (`?t=<trigramme>.<hmac>`),
   généré côté serveur pour CHAQUE enseignant et intégré à son lien
   personnel (`buildLink`, frontend) — retour utilisateur 28/08/2026 :
   « il faut que uniquement les prof ai accès a leur lien sans mot de
   passe ».

Le trigramme seul (ex. `KBR`) N'EST PAS ce jeton : ~17 000 combinaisons,
trivialement devinables. Le jeton est un HMAC signé avec un secret serveur
que le front n'a jamais — sans lui, deviner un trigramme ne suffit plus à
contourner le mot de passe (retour utilisateur, question posée
explicitement avant d'implémenter : « jeton secret par lien
(Recommandé) »).

Limite assumée et documentée (pas cachée) : un jeton prof valide autorise
les MÊMES endpoints qu'une session mot de passe — l'app ne scope pas encore
les réponses par enseignant (`/app-state`/`/timetable` renvoient tout,
filtré côté client). Un jeton prof légitime empêche donc de deviner un
lien, mais n'isole pas cryptographiquement les données d'un enseignant de
celles des autres si quelqu'un modifiait le fragment d'URL à la main.
Scoper réellement les réponses serait un chantier bien plus large, pas ce
qui a été demandé ici (« bloquer l'entrée » à qui n'a ni mot de passe ni
lien).
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
    return Path(__file__).resolve().parents[3] / "data" / ".secret_key"


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


def make_teacher_token(course_code_or_teacher: str) -> str:
    return _sign(f"teacher:{course_code_or_teacher}")[:24]


def verify_teacher_access_param(value: str | None) -> bool:
    """`value` attendu au format `<trigramme>.<jeton>` (paramètre `?t=`)."""
    if not value or "." not in value:
        return False
    code, token = value.split(".", 1)
    return hmac.compare_digest(make_teacher_token(code), token)


SESSION_COOKIE = _SESSION_COOKIE
SESSION_MAX_AGE_S = _SESSION_MAX_AGE_S
