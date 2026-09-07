"""Le VPN ne reste pas monté quand plus personne ne s'en sert.

Retour utilisateur 07/09/2026 : « il faut que tu fasses en sorte que quand
on a pas besoin de faire des actions dessus le VPN se désactive » — dit
après n'avoir pas pu se connecter lui-même à Celcat.

La cause : le VPN et Celcat partagent le MÊME compte
(`reseau.connecter` retombe sur `CELCAT_UTILISATEUR` / `CELCAT_MOT_DE_PASSE`
faute de `VPN_*`), le sidecar montait le tunnel avec ce compte et ne le
rendait JAMAIS — `deconnecter()` existait mais aucun appelant ne s'en
servait. La passerelle URCA n'accordant qu'une session par compte, celle de
l'utilisateur était prise en permanence par le robot.

Ce qui se joue ici tient en une phrase, déjà promise par le module (« ne
coupe que ce que l'outil a lui-même monté ») mais jamais tenue : raccrocher
tout ce qu'on a monté, ne JAMAIS toucher à ce qu'on a trouvé déjà en place.
Ce second point n'est pas une politesse — sur le poste Windows,
`deconnecter()` coupe l'AnyConnect de l'utilisateur ; le faire pendant qu'il
travaille serait exactement le problème qu'on répare, à l'envers.
"""

from __future__ import annotations

import pytest

from cal_iut.celcat import reseau

URL = "https://celcat-lv.univ-reims.fr/"


def _sur_site(monkeypatch) -> None:
    """Celcat répond sans VPN : rien à monter, rien à rendre."""
    monkeypatch.setattr(reseau, "verifier", lambda url, **kw: reseau.Diagnostic(True, "sur site"))


def _vpn_indispensable(monkeypatch, *, celcat_repond_ensuite: bool) -> None:
    """Le nom ne résout pas ; le tunnel monté, Celcat répond — ou pas."""
    reponses = iter(
        [
            reseau.Diagnostic(False, "pas de DNS", vpn_monte=False),
            reseau.Diagnostic(celcat_repond_ensuite, "après montage", vpn_monte=True),
        ]
    )
    monkeypatch.setattr(reseau, "verifier", lambda url, **kw: next(reponses))
    monkeypatch.setattr(reseau, "attendre_acces", lambda url, **kw: reseau.verifier(url))
    monkeypatch.setattr(reseau, "connecter", lambda **kw: reseau.Diagnostic(True, "monté"))


@pytest.fixture
def raccrochages(monkeypatch) -> list[str]:
    appels: list[str] = []
    monkeypatch.setattr(reseau, "deconnecter", lambda: appels.append("deconnecter") or "déconnecté")
    return appels


def test_le_tunnel_monte_par_l_outil_est_rendu_en_sortant(monkeypatch, raccrochages):
    """Le cas du sidecar : il monte, il travaille, il rend la main."""
    _vpn_indispensable(monkeypatch, celcat_repond_ensuite=True)

    with reseau.acces(URL, monter_le_vpn=True) as diagnostic:
        assert diagnostic.joignable
        assert diagnostic.monte_par_nous, "c'est bien nous qui l'avons monté"
        assert raccrochages == [], "surtout pas avant d'avoir fini le travail"

    assert raccrochages == ["deconnecter"]


def test_un_tunnel_trouve_deja_monte_n_est_jamais_coupe(monkeypatch, raccrochages):
    """Sur site, ou pendant que l'utilisateur a son propre AnyConnect ouvert :
    on n'a rien monté, on ne coupe rien. Couper ici reviendrait à jeter
    l'utilisateur hors de sa propre session."""
    _sur_site(monkeypatch)

    with reseau.acces(URL, monter_le_vpn=True) as diagnostic:
        assert diagnostic.joignable
        assert not diagnostic.monte_par_nous

    assert raccrochages == []


def test_le_tunnel_est_rendu_meme_si_la_saisie_echoue(monkeypatch, raccrochages):
    """Une exception au milieu de la saisie (Playwright, RPC, Celcat muet)
    ne doit pas laisser la session VPN derrière elle : c'est précisément
    comme ça qu'un tunnel se retrouve tenu pour rien jusqu'au lendemain."""
    _vpn_indispensable(monkeypatch, celcat_repond_ensuite=True)

    with pytest.raises(RuntimeError, match="saisie cassée"):
        with reseau.acces(URL, monter_le_vpn=True):
            raise RuntimeError("saisie cassée")

    assert raccrochages == ["deconnecter"]


def test_un_tunnel_monte_pour_rien_est_rendu_avant_de_lever(monkeypatch, raccrochages):
    """Tunnel établi mais Celcat toujours muet (service en panne derrière le
    VPN). `exiger_acces` levait alors `AccesIndisponible` en laissant le
    tunnel monté : personne ne l'ayant reçu, personne ne pouvait le rendre.
    C'est la fuite la plus sournoise — elle n'arrive que les jours où ça va
    déjà mal."""
    _vpn_indispensable(monkeypatch, celcat_repond_ensuite=False)

    with pytest.raises(reseau.AccesIndisponible):
        reseau.exiger_acces(URL, monter_le_vpn=True)

    assert raccrochages == ["deconnecter"]


def test_l_echec_du_montage_ne_declenche_pas_de_raccrochage(monkeypatch, raccrochages):
    """Rien n'a été monté : `pkill openconnect` n'aurait rien à tuer, mais
    sur le poste Windows la même commande couperait l'AnyConnect de
    l'utilisateur. On ne raccroche que ce qu'on a soi-même décroché."""
    monkeypatch.setattr(
        reseau, "verifier", lambda url, **kw: reseau.Diagnostic(False, "pas de DNS", vpn_monte=False)
    )
    monkeypatch.setattr(reseau, "connecter", lambda **kw: reseau.Diagnostic(False, "identifiants refusés"))

    with pytest.raises(reseau.AccesIndisponible):
        with reseau.acces(URL, monter_le_vpn=True):
            pytest.fail("le bloc ne doit jamais s'exécuter sans accès")

    assert raccrochages == []


def test_on_peut_demander_a_garder_le_tunnel(monkeypatch, raccrochages):
    """Échappatoire pour l'enchaînement de plusieurs scripts d'enquête à la
    main : remonter le tunnel à chaque commande coûte une authentification
    de plus à la passerelle — exactement ce qu'on cherche à éviter."""
    _vpn_indispensable(monkeypatch, celcat_repond_ensuite=True)

    with reseau.acces(URL, monter_le_vpn=True, raccrocher=False) as diagnostic:
        assert diagnostic.monte_par_nous

    assert raccrochages == []
