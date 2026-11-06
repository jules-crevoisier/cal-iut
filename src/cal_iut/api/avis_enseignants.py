"""Prévenir par e-mail un enseignant dont une séance change de date ou d'heure
(tâche #32).

Règles :
- Désactivé par défaut : rien ne part tant que `CAL_IUT_MAIL_ENSEIGNANTS` n'est
  pas posée à `on` (valeurs acceptées : on/1/true/oui/yes).
- Seul un changement de jour, de créneau ou d'horaire déclenche un mail : un
  changement de salle ou de note seul n'envoie RIEN.
- Adresses : celles de la liste des enseignants (`load_teacher_contacts`).
- Envoi par SMTP, réglé par variables d'environnement (voir `_config_smtp`).
- Ne fait JAMAIS échouer l'enregistrement de la séance : tout est journalisé
  (logger `cal_iut.avis_enseignants`), rien ne remonte à l'appelant.
"""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from datetime import timedelta
from email.message import EmailMessage

logger = logging.getLogger("cal_iut.avis_enseignants")

VARIABLE_ACTIVATION = "CAL_IUT_MAIL_ENSEIGNANTS"
_VALEURS_ON = {"on", "1", "true", "oui", "yes"}
_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")
_CRENEAUX = (
    ("8h00", "9h30"), ("9h30", "11h00"), ("11h00", "12h30"),
    ("14h00", "15h30"), ("15h30", "17h00"), ("17h00", "18h30"),
)

# Les tests passent à False pour envoyer de façon synchrone.
ENVOI_EN_ARRIERE_PLAN = True


def actif() -> bool:
    return os.environ.get(VARIABLE_ACTIVATION, "off").strip().lower() in _VALEURS_ON


def _config_smtp() -> dict | None:
    """`CAL_IUT_SMTP_HOST` (obligatoire), `CAL_IUT_SMTP_PORT` (587),
    `CAL_IUT_SMTP_USER`/`CAL_IUT_SMTP_PASSWORD` (facultatifs),
    `CAL_IUT_SMTP_FROM` (défaut : l'utilisateur), `CAL_IUT_SMTP_SECURITE`
    (`starttls` par défaut, `ssl` ou `aucune`)."""
    hote = os.environ.get("CAL_IUT_SMTP_HOST", "").strip()
    if not hote:
        return None
    utilisateur = os.environ.get("CAL_IUT_SMTP_USER", "").strip()
    expediteur = os.environ.get("CAL_IUT_SMTP_FROM", "").strip() or utilisateur
    if not expediteur:
        return None
    return {
        "hote": hote,
        "port": int(os.environ.get("CAL_IUT_SMTP_PORT", "587") or 587),
        "utilisateur": utilisateur,
        "mot_de_passe": os.environ.get("CAL_IUT_SMTP_PASSWORD", ""),
        "expediteur": expediteur,
        "securite": os.environ.get("CAL_IUT_SMTP_SECURITE", "starttls").strip().lower(),
    }


def _horaire_creneau(slot: int, duree: int, horaire: dict | None) -> str:
    if horaire and horaire.get("debut") and horaire.get("fin"):
        return f"{horaire['debut']}–{horaire['fin']}"
    if 0 <= slot < len(_CRENEAUX):
        fin = min(slot + max(1, duree) - 1, len(_CRENEAUX) - 1)
        return f"{_CRENEAUX[slot][0]}–{_CRENEAUX[fin][1]}"
    return "?"


def libelle_horaire(state: object, semestre: str, position: dict, duree: int) -> str:
    """Ex. « lundi 12/10/2026, 8h00–9h30 » (repli : « S5 lundi, … »)."""
    from cal_iut.calendar.academic import semester_week_offset

    jour = _JOURS[position["day"]] if 0 <= position["day"] < 5 else "?"
    quand = f"S{position['week'] + 1} {jour}"
    try:
        index = semester_week_offset(state.calendar, semestre) + position["week"]
        if 0 <= index < len(state.calendar.teaching_mondays):
            date = state.calendar.teaching_mondays[index] + timedelta(days=position["day"])
            quand = f"{jour} {date.strftime('%d/%m/%Y')}"
    except Exception:  # noqa: BLE001 — la date est un confort, jamais une condition
        pass
    return f"{quand}, {_horaire_creneau(position['slot'], duree, position.get('horaire'))}"


def a_change(avant: dict, apres: dict) -> bool:
    cle = lambda p: (p["week"], p["day"], p["slot"], (p.get("horaire") or None))  # noqa: E731
    return cle(avant) != cle(apres)


def construire_message(
    destinataire: str, nom: str, course_code: str, course_name: str,
    ancien: str, nouveau: str, salle: str | None, expediteur: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = expediteur
    msg["To"] = destinataire
    msg["Subject"] = f"Changement d'horaire : {course_code}"
    module = f"{course_name} ({course_code})" if course_name and course_name != course_code else course_code
    msg.set_content(
        f"Bonjour {nom},\n\n"
        f"Une de vos séances a changé de date ou d'heure.\n\n"
        f"Module : {module}\n"
        f"Ancien horaire : {ancien}\n"
        f"Nouvel horaire : {nouveau}\n"
        f"Salle : {salle or 'non précisée'}\n\n"
        "Message automatique de la plateforme de planning.\n"
    )
    return msg


def _envoyer(messages: list[EmailMessage], cfg: dict) -> None:
    try:
        if cfg["securite"] == "ssl":
            serveur = smtplib.SMTP_SSL(cfg["hote"], cfg["port"], timeout=15)
        else:
            serveur = smtplib.SMTP(cfg["hote"], cfg["port"], timeout=15)
        with serveur:
            if cfg["securite"] == "starttls":
                serveur.starttls()
            if cfg["utilisateur"]:
                serveur.login(cfg["utilisateur"], cfg["mot_de_passe"])
            for msg in messages:
                try:
                    serveur.send_message(msg)
                    logger.info("Avis de changement envoyé à %s (%s)", msg["To"], msg["Subject"])
                except Exception:  # noqa: BLE001 — un échec n'arrête pas les suivants
                    logger.exception("Échec d'envoi de l'avis à %s", msg["To"])
    except Exception:  # noqa: BLE001
        logger.exception("Connexion SMTP impossible : %d avis non envoyé(s)", len(messages))


def prevenir(
    state: object, session: object | None, avant: dict, apres: dict,
    salle: str | None, noms: dict | None = None,
) -> int:
    """Prépare et envoie les avis. Rend le nombre de mails mis en file.
    `avant`/`apres` : {week, day, slot, horaire}."""
    try:
        if session is None or not a_change(avant, apres):
            return 0
        if not actif():
            logger.info("Séance %s déplacée : avis enseignants désactivé (%s=off).",
                        getattr(session, "session_id", "?"), VARIABLE_ACTIVATION)
            return 0
        cfg = _config_smtp()
        if cfg is None:
            logger.warning("%s=on mais CAL_IUT_SMTP_HOST / CAL_IUT_SMTP_FROM absents : aucun avis envoyé.",
                           VARIABLE_ACTIVATION)
            return 0
        from cal_iut.ingestion.config_loader import load_teacher_contacts

        contacts = load_teacher_contacts(state.config_dir)
        duree = max(1, getattr(session, "duration_slots", None) or 1)
        semestre = getattr(session, "semestre", "") or ""
        ancien = libelle_horaire(state, semestre, avant, duree)
        nouveau = libelle_horaire(state, semestre, apres, duree)
        messages: list[EmailMessage] = []
        for code in getattr(session, "teacher_codes", None) or []:
            adresse = contacts.get(code)
            if not adresse:
                logger.warning("Aucune adresse pour l'enseignant %s : avis non envoyé.", code)
                continue
            messages.append(construire_message(
                adresse, (noms or {}).get(code, code), session.course_code,
                getattr(session, "course_name", "") or "", ancien, nouveau, salle, cfg["expediteur"],
            ))
        if not messages:
            return 0
        if ENVOI_EN_ARRIERE_PLAN:
            threading.Thread(target=_envoyer, args=(messages, cfg), daemon=True).start()
        else:
            _envoyer(messages, cfg)
        return len(messages)
    except Exception:  # noqa: BLE001 — jamais faire échouer l'enregistrement
        logger.exception("Préparation des avis enseignants impossible")
        return 0
