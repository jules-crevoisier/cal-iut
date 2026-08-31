"""Secret HMAC partagé + lien personnel public.

Ce module portait autrefois AUSSI le mot de passe unique partagé
(`CAL_IUT_PASSWORD`) et sa session — remplacés le 31/08/2026 par de vrais
comptes utilisateurs (email + mot de passe + rôles, cf. `api/accounts.py` et
`db/models.py::User`). Ce qui reste ici, volontairement : le secret HMAC
(réutilisé tel quel par `accounts.py` pour signer le nouveau cookie de
session — pas de seconde clé à gérer) et le lien personnel public.

Lien personnel (prof ou groupe, `?t=<code>`) — PUBLIC, sans jeton secret :
retour utilisateur 28/08/2026, après un aller-retour sur le sujet. D'abord un
jeton HMAC signé avait été mis en place (« jeton secret par lien
(Recommandé) », choisi explicitement à l'époque) ; le lien GROUPE n'avait
ensuite jamais reçu l'équivalent (scope initial limité aux profs), ce qui
cassait "Aucun planning résolu" en navigation privée sur un vrai lien de
groupe déployé. Plutôt que d'ajouter le même mécanisme pour les groupes,
retour utilisateur final : « pour les lien groupe et prof on s'en fiche on
veut qu'il soit public » — `?t=` n'est donc plus vérifié
cryptographiquement, sa seule présence suffit.

Limite assumée et documentée (pas cachée) : n'importe qui devinant l'URL
exacte d'un lien personnel (ou la reconstruisant à partir d'un trigramme/id
de groupe connu) y accède sans compte — et ce lien donne accès aux MÊMES
endpoints qu'une session de compte (`/app-state`/`/timetable` renvoient
tout, filtré côté client, jamais scopé par enseignant/groupe). Accepté
explicitement par l'utilisateur : la contrainte réelle reste de ne PAS
publier/deviner le lien lui-même, pas une protection cryptographique dessus.
"""

from __future__ import annotations

import os
from pathlib import Path

_SECRET_ENV = "CAL_IUT_SECRET_KEY"


def _secret_path() -> Path:
    # `data/state/`, pas `data/` directement — cf. `api/state.py::DB_PATH`
    # pour pourquoi (config vs état, volume Docker).
    return Path(__file__).resolve().parents[3] / "data" / "state" / ".secret_key"


_secret_cache: str | None = None


def get_secret() -> str:
    """Secret HMAC — stable entre redémarrages (sinon TOUS les liens profs
    déjà envoyés casseraient à chaque redéploiement, et toutes les sessions
    de compte se déconnecteraient). Priorité à la variable d'environnement
    (Docker/Dokploy, survit à un volume recréé différemment) ; à défaut, un
    fichier dans `data/` (survit tant que ce dossier persiste — c'est déjà
    un volume monté en Docker, cf. Dockerfile) généré une seule fois."""
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


def verify_personal_link_param(value: str | None) -> bool:
    """Lien personnel (prof ou groupe, `?t=<code>`) — PUBLIC depuis le
    28/08/2026 : la seule présence d'une valeur suffit, plus de vérification
    cryptographique (cf. docstring du module pour l'historique de cette
    décision). `value` porte encore le code prof/groupe (utile pour
    déboguer un lien à l'œil), mais son contenu n'est plus significatif ici
    — seule sa présence compte."""
    return bool(value)
