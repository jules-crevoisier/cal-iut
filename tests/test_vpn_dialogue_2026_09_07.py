"""`vpncli` : ne jamais répondre à une question qui n'a pas été posée.

Constaté le 07/09/2026 en montant le VPN depuis le poste Windows, journal
d'AnyConnect à l'appui :

    contacting host (vpn.univ-reims.fr) for login information...
    Please enter your username and password.
    Username: [bres0026] Password: >> Login failed.

La passerelle URCA ne propose qu'un seul groupe : elle ne pose donc PAS la
question du groupe et commence par « Username: ». Or `connecter()` envoyait
toujours une première ligne pour ce groupe — vide faute de `VPN_GROUPE`.

Le commentaire du code pariait qu'« une ligne vide saute une question qui
n'est pas posée ». C'est l'inverse : une ligne vide RÉPOND à la question
suivante en acceptant son défaut. Tout le dialogue glissait donc d'un cran
— le nom d'utilisateur mémorisé par AnyConnect était validé, puis notre
identifiant partait comme MOT DE PASSE. Le montage automatique du VPN
n'avait ainsi jamais pu fonctionner depuis ce poste, et l'échec se
présentait comme un banal « Login failed », c'est-à-dire comme un problème
d'identifiants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cal_iut.celcat import reseau


@pytest.fixture
def dialogue(monkeypatch) -> list[str]:
    """Capture les lignes envoyées à `vpncli` sur son entrée standard."""
    envoye: list[str] = []

    class Acheve:
        returncode = 0
        stdout = ""

    def faux_run(commande, **kwargs):
        envoye.append(kwargs.get("input") or "")
        return Acheve()

    monkeypatch.setattr(reseau, "client_disponible", lambda: ("anyconnect", Path("vpncli.exe")))
    monkeypatch.setattr(reseau.subprocess, "run", faux_run)
    monkeypatch.setattr(reseau, "etat_vpn", lambda: "connecté")
    return envoye


def test_sans_groupe_le_dialogue_commence_par_l_identifiant(dialogue):
    """Le cas de la passerelle URCA : pas de question de groupe."""
    diagnostic = reseau.connecter(
        passerelle="vpn.univ-reims.fr", utilisateur="bres0026", mot_de_passe="secret", groupe=""
    )
    assert diagnostic.joignable

    lignes = dialogue[0].split("\n")
    assert lignes[0] == "bres0026", "la première réponse doit être l'identifiant"
    assert lignes[1] == "secret", (
        "le mot de passe doit arriver en DEUXIÈME : décalé d'un cran, "
        "l'identifiant partait comme mot de passe (Login failed)"
    )


def test_avec_groupe_il_passe_en_tete(dialogue):
    """Une passerelle qui propose plusieurs groupes pose la question en
    premier : la réponse doit alors précéder l'identifiant."""
    reseau.connecter(
        passerelle="autre.example.fr",
        utilisateur="bres0026",
        mot_de_passe="secret",
        groupe="ETUDIANTS",
    )

    lignes = dialogue[0].split("\n")
    assert lignes[:3] == ["ETUDIANTS", "bres0026", "secret"]


def test_le_mot_de_passe_ne_fuite_pas_dans_le_diagnostic(monkeypatch):
    """Un échec de montage remonte la sortie de `vpncli` telle quelle : elle
    ne doit jamais contenir le mot de passe (le journal la conserve)."""

    class Acheve:
        returncode = 1
        stdout = "Login failed for secret"

    monkeypatch.setattr(reseau, "client_disponible", lambda: ("anyconnect", Path("vpncli.exe")))
    monkeypatch.setattr(reseau.subprocess, "run", lambda commande, **kw: Acheve())
    monkeypatch.setattr(reseau, "etat_vpn", lambda: "déconnecté")

    diagnostic = reseau.connecter(
        passerelle="vpn.univ-reims.fr", utilisateur="bres0026", mot_de_passe="secret", groupe=""
    )

    assert not diagnostic.joignable
    assert "secret" not in diagnostic.detail
    assert "«masqué»" in diagnostic.detail
