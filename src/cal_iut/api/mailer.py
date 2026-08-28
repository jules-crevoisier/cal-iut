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

Journal d'envoi (`data/state/mail_log.json`, jamais commité — cf. `.gitignore`,
même traitement que `data/state/.secret_key`) : une ligne par enseignant déjà
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


def personal_link(code: str) -> str:
    """Même format que `buildLink`/`useHashRoute.ts` côté front
    (`#vue=prof&prof=<code>&mode=prof&t=<code>`) — construit ici côté
    serveur pour l'e-mail, qui n'a pas de navigateur pour appeler
    `buildLink`. `t` est public depuis le 28/08/2026 (cf. `api/auth.py`) :
    il ne porte plus qu'un identifiant, jamais un jeton signé."""
    return f"{public_base_url()}/#vue=prof&prof={code}&mode=prof&t={code}"


def send_email(to: str, subject: str, text: str, html: str | None = None) -> str:
    """Envoie un mail via l'API Resend — texte brut seul si `html` est
    absent, ou les deux (Resend, comme la plupart des clients mail, choisit
    HTML quand il sait l'afficher et retombe sur le texte brut sinon).
    `html` sert notamment à faire ressortir un avertissement en encart
    coloré, impossible à rendre en texte brut (retour utilisateur
    28/08/2026 : « met l'invitation à placer les cours en warning pour que
    cela soit bien lu »). Rend l'id du message (utile pour retrouver un
    envoi précis côté Resend en cas de souci de délivrabilité). Ne rattrape
    RIEN : un échec (`MailerNotConfigured`, `httpx.HTTPStatusError`, erreur
    réseau) doit remonter tel quel jusqu'à l'appelant, jamais disparaître
    silencieusement."""
    api_key = os.environ.get(_API_KEY_ENV)
    if not api_key:
        raise MailerNotConfigured(f"{_API_KEY_ENV} non configuré — aucun mail ne peut être envoyé.")
    sender = os.environ.get(_FROM_ENV) or _DEFAULT_FROM
    payload: dict[str, object] = {"from": sender, "to": [to], "subject": subject, "text": text}
    if html:
        payload["html"] = html
    response = httpx.post(
        _RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=15.0,
    )
    response.raise_for_status()
    return str(response.json().get("id", ""))


# --------------------------------------------------------------------------
# Journal d'envoi — qui a déjà reçu son lien, et quand.
# --------------------------------------------------------------------------


def _log_path() -> Path:
    # `data/state/`, pas `data/` directement — cf. `api/state.py::DB_PATH`
    # pour pourquoi (config vs état, volume Docker).
    return Path(__file__).resolve().parents[3] / "data" / "state" / "mail_log.json"


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
    # `opened_at` volontairement REMIS À ZÉRO à chaque envoi : un nouveau
    # mail est une nouvelle question (« celui-là, l'a-t-il vu ? »), garder
    # l'ouverture du précédent ferait croire à tort qu'il a été lu.
    log[code] = {"sent_at": datetime.now(timezone.utc).isoformat(), "message_id": message_id}
    _save_log(log)


def record_opened(code: str) -> None:
    """Première ouverture seulement — on veut savoir SI le mail a été vu,
    pas combien de fois (ce serait de la surveillance, pas un accusé de
    réception). Ignoré si aucun envoi n'est enregistré pour ce code : une
    requête sur le pixel sans envoi correspondant ne peut venir que d'une
    URL bricolée, jamais d'un vrai mail."""
    log = _load_log()
    entree = log.get(code)
    if not entree or entree.get("opened_at"):
        return
    entree["opened_at"] = datetime.now(timezone.utc).isoformat()
    _save_log(log)


# GIF transparent 1x1, le plus petit fichier image valide — sert de pixel
# de suivi d'ouverture. Beaucoup de clients mail bloquent les images
# distantes par défaut (Gmail les met en cache, Outlook demande souvent
# l'autorisation) : une ouverture non détectée ne veut donc PAS dire que le
# mail n'a pas été lu. C'est un indice, jamais une preuve — d'où le libellé
# prudent côté interface.
PIXEL_GIF = bytes([
    0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00, 0x00,
    0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x21, 0xF9, 0x04, 0x01, 0x00, 0x00, 0x00,
    0x00, 0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x02, 0x02,
    0x44, 0x01, 0x00, 0x3B,
])


def sent_log() -> dict[str, dict[str, str]]:
    return _load_log()
