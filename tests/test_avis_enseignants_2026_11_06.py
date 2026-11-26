"""Tâche #32 : e-mail aux enseignants quand une séance change de date/heure.
SMTP factice : aucun vrai envoi, aucun accès réseau."""

from __future__ import annotations

import smtplib

import pytest

from cal_iut.api import avis_enseignants as avis
from cal_iut.api.state import get_state

from test_mail_teacher_links_2026_08_28 import client, etat_avec_seance, session_admin  # noqa: F401


class SmtpFactice:
    envoyes: list = []
    connexions: list = []

    def __init__(self, hote, port, timeout=None):
        SmtpFactice.connexions.append((hote, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        SmtpFactice.envoyes.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    SmtpFactice.envoyes, SmtpFactice.connexions = [], []
    monkeypatch.setattr(smtplib, "SMTP", SmtpFactice)
    monkeypatch.setattr(avis, "ENVOI_EN_ARRIERE_PLAN", False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("CAL_IUT_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("CAL_IUT_SMTP_FROM", "planning@test.fr")
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kbr@test.fr"},
    )
    return SmtpFactice


def _deplacer(**corps):
    r = client.patch("/placements/s1", json={"week": 0, "day": 0, "slot": 0, "force": True, **corps})
    assert r.status_code == 200, r.text


def test_desactive_par_defaut_rien_ne_part(etat_avec_seance, session_admin, smtp, monkeypatch):
    monkeypatch.delenv(avis.VARIABLE_ACTIVATION, raising=False)
    _deplacer(week=3, day=1)
    assert smtp.envoyes == [] and smtp.connexions == []


def test_changement_de_jour_envoie_un_mail_complet(etat_avec_seance, session_admin, smtp, monkeypatch):
    monkeypatch.setenv(avis.VARIABLE_ACTIVATION, "on")
    _deplacer(week=3, day=1, slot=1)
    assert len(smtp.envoyes) == 1
    msg = smtp.envoyes[0]
    assert msg["To"] == "kbr@test.fr"
    corps = msg.get_content()
    assert "WR101" in corps and "lundi" in corps and "mardi" in corps
    assert "9h30" in corps and "8h00" in corps and "Salle" in corps


def test_meme_horaire_n_envoie_rien(etat_avec_seance, session_admin, smtp, monkeypatch):
    monkeypatch.setenv(avis.VARIABLE_ACTIVATION, "on")
    _deplacer()
    assert smtp.envoyes == []


def test_sans_adresse_ou_sans_smtp_pas_d_envoi_ni_erreur(etat_avec_seance, session_admin, smtp, monkeypatch):
    monkeypatch.setenv(avis.VARIABLE_ACTIVATION, "on")
    monkeypatch.setattr("cal_iut.ingestion.config_loader.load_teacher_contacts", lambda config_dir: {})
    _deplacer(week=3, day=1)
    assert smtp.envoyes == []
    monkeypatch.delenv("CAL_IUT_SMTP_HOST")
    _deplacer(week=3, day=2)
    assert smtp.envoyes == []


def test_echec_smtp_ne_bloque_pas_le_deplacement(etat_avec_seance, session_admin, smtp, monkeypatch):
    monkeypatch.setenv(avis.VARIABLE_ACTIVATION, "on")

    def casse(*a, **k):
        raise OSError("connexion refusée")

    monkeypatch.setattr(smtplib, "SMTP", casse)
    _deplacer(week=3, day=1)
    placement = next(p for p in get_state().timetable if p.session_id == "s1")
    assert placement.day == 1


def test_changement_de_salle_seul_n_envoie_rien():
    pos = {"week": 0, "day": 0, "slot": 0, "horaire": None}
    assert avis.a_change(pos, dict(pos)) is False
    assert avis.a_change(pos, {**pos, "horaire": {"debut": "10:00", "fin": "11:00"}}) is True


@pytest.fixture
def resend(monkeypatch):
    envoyes = []
    monkeypatch.setattr(avis, "ENVOI_EN_ARRIERE_PLAN", False)
    monkeypatch.setenv("RESEND_API_KEY", "cle-test")
    monkeypatch.delenv("CAL_IUT_SMTP_HOST", raising=False)
    monkeypatch.delenv(avis.VARIABLE_ACTIVATION, raising=False)
    monkeypatch.setattr(avis.mailer, "send_email",
                        lambda to, sujet, texte, html=None: envoyes.append((to, sujet, texte)) or "id")
    monkeypatch.setattr(
        "cal_iut.ingestion.config_loader.load_teacher_contacts",
        lambda config_dir: {"KBR": "kbr@test.fr"},
    )
    return envoyes


def test_resend_configure_envoie_sans_interrupteur(etat_avec_seance, session_admin, resend):
    _deplacer(week=3, day=1, slot=1)
    assert len(resend) == 1
    to, sujet, texte = resend[0]
    assert to == "kbr@test.fr" and "WR101" in sujet and "mardi" in texte


def test_interrupteur_off_coupe_meme_avec_resend(etat_avec_seance, session_admin, resend, monkeypatch):
    monkeypatch.setenv(avis.VARIABLE_ACTIVATION, "off")
    _deplacer(week=3, day=1)
    assert resend == []


def test_echec_resend_ne_bloque_pas_le_deplacement(etat_avec_seance, session_admin, resend, monkeypatch):
    def casse(*a, **k):
        raise RuntimeError("Resend indisponible")

    monkeypatch.setattr(avis.mailer, "send_email", casse)
    _deplacer(week=3, day=1)
    placement = next(p for p in get_state().timetable if p.session_id == "s1")
    assert placement.day == 1
