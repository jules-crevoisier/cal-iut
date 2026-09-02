"""Notifications par mail : à qui, pour quoi, à quelle cadence.

Demande du 29/08/2026 : « ce serait bien des mails de notification s'il y a
des cours sans salle, modification etc. par mail à Kyllian Bresson ; fais en
sorte que l'on puisse configurer pour quoi les mails partent dans
l'interface, et que l'on puisse modifier l'email et en ajouter plusieurs en
même temps ».

Trois partis pris, tous dictés par le même risque — pas celui de manquer un
mail, celui d'en envoyer trop :

1. **Résumé groupé, jamais un mail par événement.** Une réorganisation
   d'emploi du temps, c'est vingt déplacements en dix minutes. Vingt mails
   rendraient la boîte inutilisable et la fonctionnalité serait coupée dès
   le premier jour.

2. **Rien n'est actif par défaut.** Aucun destinataire, aucun événement
   coché : une fonctionnalité d'envoi ne s'allume pas toute seule.

3. **Un échec d'envoi n'échoue jamais l'appelant.** La notification est un
   à-côté du déplacement de séance ; si Resend est indisponible, le
   déplacement doit quand même aboutir.

La configuration vit dans `data/state/notifications.json` — le volume
persistant, comme le journal des mails (cf. `mailer.py::_log_path`) : elle
survit à un redéploiement, contrairement à `data/config/` réécrit à chaque
image.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Les seuls événements notifiables. Liste FERMÉE et validée à l'écriture :
# sans cela, une faute de frappe dans l'interface désactiverait en silence
# une notification qu'on croit active.
EVENEMENTS: dict[str, str] = {
    "sans_salle": "Une séance se retrouve sans salle",
    "deplacement": "Une séance est déplacée",
    "echange": "Deux séances échangent leurs places",
    "placement": "Une séance non placée est posée au planning",
    "celcat_echec": "Écriture Celcat refusée ou échouée",
    "celcat_ok": "Écriture Celcat réussie (création ou mise à jour)",
}

_DELAI_DEFAUT_MINUTES = 15
_ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_verrou = threading.Lock()
_file: list[tuple[str, str, str]] = []  # (horodatage, événement, texte)
_dernier_envoi: datetime | None = None


def _chemin_config() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "notifications.json"


def _defaut() -> dict[str, Any]:
    return {
        "destinataires": [],
        "evenements": {cle: False for cle in EVENEMENTS},
        "delai_minutes": _DELAI_DEFAUT_MINUTES,
    }


def config() -> dict[str, Any]:
    chemin = _chemin_config()
    base = _defaut()
    if not chemin.exists():
        return base
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Fichier illisible = configuration par défaut, donc AUCUN envoi.
        # Le pire scénario doit rester « rien ne part », jamais « tout part
        # à une liste d'adresses à moitié lue ».
        return base
    base["destinataires"] = [a for a in brut.get("destinataires", []) if isinstance(a, str)]
    for cle in EVENEMENTS:
        base["evenements"][cle] = bool(brut.get("evenements", {}).get(cle, False))
    delai = brut.get("delai_minutes", _DELAI_DEFAUT_MINUTES)
    base["delai_minutes"] = int(delai) if isinstance(delai, (int, float)) else _DELAI_DEFAUT_MINUTES
    return base


def enregistrer_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Écrit la configuration après NETTOYAGE et VALIDATION.

    Nettoyage : espaces, casse et doublons. L'interface laisse coller une
    liste d'adresses d'un coup ; deux fois la même adresse enverrait deux
    fois le même mail.
    """
    actuel = config()

    if "destinataires" in patch:
        propres: list[str] = []
        for brute in patch["destinataires"] or []:
            adresse = str(brute).strip().lower()
            if not adresse:
                continue
            if not _ADRESSE.match(adresse):
                raise ValueError(f"adresse invalide : « {brute} »")
            if adresse not in propres:
                propres.append(adresse)
        actuel["destinataires"] = propres

    if "evenements" in patch:
        for cle, actif in (patch["evenements"] or {}).items():
            if cle not in EVENEMENTS:
                raise ValueError(f"événement inconnu : « {cle} »")
            actuel["evenements"][cle] = bool(actif)

    if "delai_minutes" in patch:
        actuel["delai_minutes"] = max(0, int(patch["delai_minutes"]))

    chemin = _chemin_config()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(actuel, ensure_ascii=False, indent=2), encoding="utf-8")
    return actuel


def _envoyer(destinataire: str, sujet: str, texte: str) -> None:
    """Isolé dans sa propre fonction pour être remplaçable en test : aucun
    test de ce module ne doit pouvoir envoyer un vrai mail."""
    from cal_iut.api import mailer

    mailer.send_email(destinataire, sujet, texte)


def signaler(evenement: str, texte: str) -> None:
    """Met un événement en file. N'envoie RIEN par lui-même — c'est
    `envoyer_si_temps_ecoule` ou `vider_file` qui déclenchent le résumé."""
    if evenement not in EVENEMENTS:
        return
    if not config()["evenements"].get(evenement):
        return
    with _verrou:
        _file.append((datetime.now(timezone.utc).strftime("%H:%M"), evenement, texte))


def envoyer_si_temps_ecoule() -> bool:
    """Envoie le résumé si le délai configuré est écoulé depuis le dernier.
    Appelée après chaque événement : pas de tâche de fond à surveiller, et
    une rafale de modifications ne produit qu'un seul mail."""
    global _dernier_envoi
    delai = config()["delai_minutes"]
    with _verrou:
        if not _file:
            return False
        if _dernier_envoi is not None and delai > 0:
            ecoule = (datetime.now(timezone.utc) - _dernier_envoi).total_seconds() / 60
            if ecoule < delai:
                return False
        if _dernier_envoi is None and delai > 0 and len(_file) < 2:
            # Premier événement d'une rafale : on laisse une chance aux
            # suivants d'arriver plutôt que d'envoyer un résumé d'une ligne.
            _dernier_envoi = datetime.now(timezone.utc)
            return False
    return vider_file()


def vider_file() -> bool:
    """Envoie tout ce qui attend, maintenant. Rend True si un mail est parti."""
    global _dernier_envoi
    with _verrou:
        if not _file:
            return False
        evenements = list(_file)
        _file.clear()
        _dernier_envoi = datetime.now(timezone.utc)

    cfg = config()
    destinataires = cfg["destinataires"]
    if not destinataires:
        return False

    par_type: dict[str, list[str]] = {}
    for _, evenement, texte in evenements:
        par_type.setdefault(evenement, []).append(texte)

    sujet = f"cal-iut — {len(evenements)} modification(s) du planning"
    lignes = ["Récapitulatif des modifications du planning cal-iut.", ""]
    for evenement, textes in par_type.items():
        lignes.append(f"{EVENEMENTS[evenement]} ({len(textes)}) :")
        lignes += [f"  - {t}" for t in textes]
        lignes.append("")
    lignes.append("Ce message est automatique. Les destinataires et les événements")
    lignes.append("suivis se règlent dans l'onglet Référence de l'application.")
    texte = "\n".join(lignes)

    envoye = False
    for destinataire in destinataires:
        try:
            _envoyer(destinataire, sujet, texte)
            envoye = True
        except Exception:  # noqa: BLE001
            # Une notification qui casse ne doit jamais faire échouer le
            # déplacement de séance qui l'a déclenchée.
            continue
    return envoye


def en_attente() -> int:
    with _verrou:
        return len(_file)
