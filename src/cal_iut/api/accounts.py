"""Comptes utilisateurs (email + mot de passe + rôles) — remplace le mot de
passe unique partagé (`CAL_IUT_PASSWORD`, `api/auth.py`) par de vrais
comptes : signup + confirmation e-mail + activation admin, connexion, mot de
passe oublié/réinitialisation, gestion des rôles côté `/admin/users`.

Session : cookie HMAC signé réutilisant `auth.get_secret()` (pas de seconde
clé, pas de table de sessions ni de JWT), qui ne porte que
`user_id + expiration` — le rôle et le statut sont TOUJOURS relus depuis la
table `users` à chaque requête (`get_current_user`), jamais mis en cache
dans le cookie : une désactivation ou un changement de rôle prend effet dès
la requête suivante de la personne concernée, pas à l'expiration du cookie
(30 jours).

`ADMIN_EMAILS` : les deux seules adresses qui sautent directement en admin
actif à la confirmation d'email, sans attendre qu'un admin déjà actif les
active (cf. `AccountRepository.mark_email_confirmed`) — sans ça, le tout
premier compte ne pourrait jamais être activé, personne n'existant encore
pour le faire.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import argon2
from argon2.exceptions import Argon2Error
from fastapi import HTTPException, Request

from cal_iut.api import auth, mailer
from cal_iut.db.accounts_repository import AccountRepository
from cal_iut.db.models import User
from cal_iut.db.session import get_db

ACCOUNT_SESSION_COOKIE = "cal_iut_account_session"  # jamais "cal_iut_session" (cf. auth.py) :
# l'ancien cookie mot de passe partagé ne doit jamais pouvoir être relu comme
# un identifiant de compte.
ACCOUNT_SESSION_MAX_AGE_S = 30 * 24 * 3600  # 30 jours

ROLE_ORDER: dict[str, int] = {"read_only": 0, "edit": 1, "admin": 2}

ADMIN_EMAILS: frozenset[str] = frozenset({
    "crevoisier.ju@gmail.com",
    "kyllian.bresson@univ-reims.fr",
})

CONFIRM_TOKEN_TTL_S = 48 * 3600
RESET_TOKEN_TTL_S = 1 * 3600


# --------------------------------------------------------------------------
# Mot de passe — Argon2, jamais de sel/hash maison.
# --------------------------------------------------------------------------

_ph = argon2.PasswordHasher()


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except Argon2Error:
        # Mot de passe incorrect OU hash malformé (ex. compte inséré à la
        # main par un test avec un hash bidon) : dans les deux cas, un échec
        # de connexion, jamais une exception qui remonterait en 500.
        return False


# --------------------------------------------------------------------------
# Normalisation d'email — toujours minuscules + espaces retirés, à l'entrée
# de toute route qui reçoit un email (signup, login, forgot-password).
# --------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.strip().lower()


# --------------------------------------------------------------------------
# Session — cookie HMAC signé, réutilisant `auth.get_secret()`.
# --------------------------------------------------------------------------


def _sign(payload: str) -> str:
    return hmac.new(auth.get_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_account_session_token(user_id: int) -> str:
    expiry = str(int(time.time()) + ACCOUNT_SESSION_MAX_AGE_S)
    payload = f"{user_id}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def verify_account_session_token(token: str | None) -> int | None:
    """Rend le `user_id` si signature + expiration sont valides — ne
    consulte JAMAIS la base ici (cf. `get_current_user` pour ça) : cette
    fonction ne fait que prouver que le cookie n'a pas été falsifié."""
    if not token or token.count(".") != 2:
        return None
    user_id_str, expiry, sig = token.split(".")
    payload = f"{user_id_str}.{expiry}"
    if not hmac.compare_digest(_sign(payload), sig):
        return None
    try:
        if int(expiry) <= time.time():
            return None
        return int(user_id_str)
    except ValueError:
        return None


def _account_repo() -> AccountRepository:
    from cal_iut.api.state import get_state

    return AccountRepository(get_db(get_state().db_path))


def get_current_user(request: Request, *, optional: bool = False) -> User | None:
    """Résout l'utilisateur courant depuis le cookie de session — rôle et
    statut relus EN BASE à chaque appel, jamais depuis le cookie lui-même.

    `optional=True` (utilisé par `GET /app-state`, en dehors de tout
    `require_role`) rend `None` au lieu de lever 401 quand personne n'est
    connecté — un lien personnel public n'a pas de compte à résoudre, ce
    n'est pas une erreur."""
    user_id = verify_account_session_token(request.cookies.get(ACCOUNT_SESSION_COOKIE))
    if user_id is None:
        if optional:
            return None
        raise HTTPException(401, "Authentification requise.")
    user = _account_repo().get_by_id(user_id)
    if user is None:
        if optional:
            return None
        raise HTTPException(401, "Authentification requise.")
    return user


def require_role(minimum: str) -> Callable[[Request], User]:
    """`Depends(require_role("edit"))` etc. — 401 si pas connecté, 403 si le
    compte n'est pas `active`, 403 si le rôle est insuffisant."""

    def checker(request: Request) -> User:
        # Le middleware `require_auth` a déjà résolu l'utilisateur pour
        # toute route protégée et l'a posé sur `request.state.user` — le
        # relire ici évite une 2e requête SQLite identique par appel
        # (revue qualité du 31/08/2026). Le repli sur `get_current_user`
        # reste utile en défense en profondeur si `require_role` était un
        # jour utilisé sur une route hors du périmètre du middleware.
        user = getattr(request.state, "user", None) or get_current_user(request)
        if user.status != "active":
            raise HTTPException(403, "Compte en attente d'activation ou désactivé.")
        if ROLE_ORDER.get(user.role, -1) < ROLE_ORDER[minimum]:
            raise HTTPException(403, "Permissions insuffisantes pour cette action.")
        return user

    return checker


# --------------------------------------------------------------------------
# Jetons à usage unique (confirmation d'email, réinitialisation de mot de
# passe) — seul le hash SHA-256 est persisté, la valeur brute (`raw`) ne
# transite que dans l'URL envoyée par mail.
# --------------------------------------------------------------------------


def _build_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def build_confirm_token() -> tuple[str, str]:
    return _build_token()


def build_reset_token() -> tuple[str, str]:
    return _build_token()


def confirm_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=CONFIRM_TOKEN_TTL_S)


def reset_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=RESET_TOKEN_TTL_S)


# --------------------------------------------------------------------------
# Liens envoyés par e-mail — même domaine public que le reste de
# l'application (`mailer.public_base_url()`) : le frontend ET l'API vivent
# sous la même origine (cf. `main.py`, montage de `frontend/dist` sur `/`).
# --------------------------------------------------------------------------


def public_base_url_or_placeholder() -> str:
    """`mailer.public_base_url()` avec repli — même principe que
    `main.py::mail_teacher_link_apercu` : un lien reste construit (utile
    pour un aperçu, ou en test où `CAL_IUT_PUBLIC_URL` n'est jamais
    configuré) même quand l'URL publique ne l'est pas, plutôt que de faire
    échouer tout l'appelant (signup, confirmation) pour une variable
    d'environnement qui ne concerne, elle, que l'ENVOI réel du mail."""
    try:
        return mailer.public_base_url()
    except mailer.MailerNotConfigured:
        return "(CAL_IUT_PUBLIC_URL non configurée)"


def confirmation_link(token: str) -> str:
    """Pointe directement sur la route API `GET /auth/confirm-email` (pas
    une route frontend) : confirmer un email est une action à effet de bord
    unique, sans formulaire à afficher avant — la route rend elle-même une
    redirection 302 vers le frontend une fois faite (cf. `main.py`)."""
    return f"{public_base_url_or_placeholder()}/auth/confirm-email?token={token}"


def reset_password_link(token: str) -> str:
    """Pointe vers une route FRONTEND (hash route) : réinitialiser un mot de
    passe demande un formulaire (nouveau mot de passe), il n'y a pas de
    `GET /auth/reset-password` côté API — seulement le `POST` que ce
    formulaire appellera."""
    return f"{public_base_url_or_placeholder()}/#compte=reinitialiser&token={token}"
