"""Envoi automatique du lien personnel à chaque enseignant, par mail —
retour utilisateur 28/08/2026 : « on veux une fonctionnalité qui permet
d'envoyer automatiquement un mail à chaque prof avec leur lien ».

Utilise l'API HTTP de Resend (https://resend.com), pas SMTP : Resend
n'expose de toute façon pas de mot de passe SMTP distinct de sa clé API
(l'identifiant SMTP `resend` est fixe pour tout compte, la clé API EST le
mot de passe) — l'API HTTP donne une réponse JSON explicite en cas
d'erreur plutôt qu'un code SMTP à interpréter.

Configuration par variables d'environnement (jamais commitées, posées côté
Dokploy) :
- `RESEND_API_KEY` — obligatoire pour envoyer ;
- `RESEND_FROM` — expéditeur, ex. `cal-iut@nexkeep.fr` (défaut ci-dessous) ;
- `CAL_IUT_PUBLIC_URL` — URL PUBLIQUE DU FRONT, ex.
  `https://cal-iut-mmi.srko.fr` — DISTINCTE du domaine d'envoi
  (`nexkeep.fr` sert à ENVOYER les mails, `cal-iut-mmi.srko.fr` est ce que
  le lien contenu DANS le mail doit pointer ; retour utilisateur : « l'url
  du site sera https://cal-iut-mmi.srko.fr mais on envoie avec l'autre
  domaine »).

Sans `RESEND_API_KEY`/`CAL_IUT_PUBLIC_URL`, toute tentative d'envoi échoue
avec `MailerNotConfigured` plutôt qu'un envoi silencieusement ignoré ou un
lien construit sur une URL locale inutilisable — même philosophie que
`CAL_IUT_PASSWORD` (`api/auth.py`) : un oubli de configuration doit être
visible, jamais confondu avec "ça a marché".

Journal d'envoi (`data/mail_log.json`, jamais commité — cf. `.gitignore`,
même traitement que `data/.secret_key`) : une ligne par enseignant déjà
contacté, pour que l'écran d'envoi puisse avertir avant un ré-envoi
accidentel plutôt que de forcer l'utilisateur à s'en souvenir lui-même.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

_API_KEY_ENV = "RESEND_API_KEY"
_FROM_ENV = "RESEND_FROM"
_PUBLIC_URL_ENV = "CAL_IUT_PUBLIC_URL"
_DEFAULT_FROM = "cal-iut@nexkeep.fr"
_RESEND_ENDPOINT = "https://api.resend.com/emails"


class MailerNotConfigured(Exception):
    """`RESEND_API_KEY` ou `CAL_IUT_PUBLIC_URL` absent(e) — jamais un envoi
    silencieux ni un lien construit sur une URL inutilisable, toujours une
    erreur explicite remontée jusqu'à l'utilisateur."""


def is_configured() -> bool:
    return bool(os.environ.get(_API_KEY_ENV)) and bool(os.environ.get(_PUBLIC_URL_ENV))


def public_base_url() -> str:
    url = os.environ.get(_PUBLIC_URL_ENV)
    if not url:
        raise MailerNotConfigured(
            f"{_PUBLIC_URL_ENV} non configuré — impossible de construire un lien personnel valide."
        )
    return url.rstrip("/")


def personal_link(code: str, token: str) -> str:
    """Même format que `buildLink`/`useHashRoute.ts` côté front
    (`#vue=prof&prof=<code>&mode=prof&t=<code>.<hmac>`) — construit ici
    côté serveur pour l'e-mail, qui n'a pas de navigateur pour appeler
    `buildLink`."""
    return f"{public_base_url()}/#vue=prof&prof={code}&mode=prof&t={token}"


def send_email(to: str, subject: str, text: str) -> str:
    """Envoie un mail texte brut via l'API Resend. Rend l'id du message
    (utile pour retrouver un envoi précis côté Resend en cas de souci de
    délivrabilité). Ne rattrape RIEN : un échec (`MailerNotConfigured`,
    `httpx.HTTPStatusError`, erreur réseau) doit remonter tel quel jusqu'à
    l'appelant, jamais disparaître silencieusement."""
    api_key = os.environ.get(_API_KEY_ENV)
    if not api_key:
        raise MailerNotConfigured(f"{_API_KEY_ENV} non configuré — aucun mail ne peut être envoyé.")
    sender = os.environ.get(_FROM_ENV) or _DEFAULT_FROM
    response = httpx.post(
        _RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": sender, "to": [to], "subject": subject, "text": text},
        timeout=15.0,
    )
    response.raise_for_status()
    return str(response.json().get("id", ""))


# --------------------------------------------------------------------------
# Journal d'envoi — qui a déjà reçu son lien, et quand.
# --------------------------------------------------------------------------


def _log_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "mail_log.json"


def _load_log() -> dict[str, dict[str, str]]:
    path = _log_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Fichier absent/corrompu = journal vide, jamais une erreur qui
        # bloquerait l'écran de prévisualisation — l'historique d'envoi
        # est une aide, pas une donnée dont l'intégrité doit être garantie.
        return {}


def _save_log(log: dict[str, dict[str, str]]) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def record_sent(code: str, message_id: str) -> None:
    log = _load_log()
    log[code] = {"sent_at": datetime.now(timezone.utc).isoformat(), "message_id": message_id}
    _save_log(log)


def sent_log() -> dict[str, dict[str, str]]:
    return _load_log()
