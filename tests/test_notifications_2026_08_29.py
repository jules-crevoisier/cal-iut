"""Notifications par mail : à qui, pour quoi, et à quelle cadence.

Demande du 29/08/2026 : « ce serait bien des mails de notification s'il y a
des cours sans salle, modification etc. par mail à Kyllian Bresson ; fais en
sorte que l'on puisse configurer pour quoi les mails partent dans
l'interface, et que l'on puisse modifier l'email et en ajouter plusieurs en
même temps ».

Le risque dominant n'est pas de manquer un mail, c'est d'en envoyer trop.
Une réorganisation d'emploi du temps, c'est vingt déplacements en dix
minutes : un mail par déplacement rendrait la boîte inutilisable et la
fonctionnalité serait coupée dès le premier jour. D'où un RÉSUMÉ groupé,
et une fréquence plafonnée.

Aucun test n'envoie de mail : l'envoi est remplacé par une fonction témoin.
"""

from __future__ import annotations

import pytest

from cal_iut.api import notifications as notif


@pytest.fixture(autouse=True)
def _etat_isole(tmp_path, monkeypatch):
    """Le fichier de configuration ne doit jamais être celui du dépôt : un
    test qui y écrirait changerait les destinataires réels."""
    monkeypatch.setattr(notif, "_chemin_config", lambda: tmp_path / "notifications.json")
    notif.vider_file()
    yield
    notif.vider_file()


@pytest.fixture
def envois(monkeypatch):
    recus: list[tuple[str, str, str]] = []
    monkeypatch.setattr(notif, "_envoyer", lambda to, sujet, texte: recus.append((to, sujet, texte)))
    return recus


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_par_defaut_rien_ne_part() -> None:
    """Une fonctionnalité d'envoi ne s'active jamais toute seule : personne
    n'a demandé à recevoir quoi que ce soit tant que ce n'est pas configuré."""
    cfg = notif.config()
    assert cfg["destinataires"] == []
    assert all(actif is False for actif in cfg["evenements"].values())


def test_la_configuration_se_relit_apres_ecriture() -> None:
    notif.enregistrer_config({"destinataires": ["a@b.fr"], "evenements": {"sans_salle": True}})
    cfg = notif.config()
    assert cfg["destinataires"] == ["a@b.fr"]
    assert cfg["evenements"]["sans_salle"] is True


def test_plusieurs_destinataires_sont_acceptes() -> None:
    notif.enregistrer_config({"destinataires": ["a@b.fr", "c@d.fr", "e@f.fr"]})
    assert len(notif.config()["destinataires"]) == 3


def test_les_doublons_et_les_espaces_sont_nettoyes() -> None:
    """L'interface laisse coller une liste d'adresses ; deux fois la même
    adresse enverrait deux fois le même mail."""
    notif.enregistrer_config({"destinataires": [" a@b.fr ", "A@B.FR", "c@d.fr", ""]})
    assert notif.config()["destinataires"] == ["a@b.fr", "c@d.fr"]


def test_une_adresse_invalide_est_refusee() -> None:
    with pytest.raises(ValueError, match="adresse"):
        notif.enregistrer_config({"destinataires": ["pas-une-adresse"]})


def test_un_evenement_inconnu_est_refuse() -> None:
    """Sinon une faute de frappe dans l'interface désactive silencieusement
    une notification qu'on croit active."""
    with pytest.raises(ValueError, match="événement"):
        notif.enregistrer_config({"evenements": {"nimporte_quoi": True}})


def test_la_liste_des_evenements_est_stable() -> None:
    assert set(notif.EVENEMENTS) == {
        "sans_salle",
        "deplacement",
        "echange",
        "placement",
        "celcat_echec",
        "celcat_ok",
    }


# --------------------------------------------------------------------------
# Ce qui part, et ce qui ne part pas
# --------------------------------------------------------------------------


def _configurer(evenement: str = "deplacement", delai: int = 0) -> None:
    notif.enregistrer_config({
        "destinataires": ["kyllian@exemple.fr"],
        "evenements": {evenement: True},
        "delai_minutes": delai,
    })


def test_un_evenement_actif_declenche_un_mail(envois) -> None:
    _configurer()
    notif.signaler("deplacement", "WR106 déplacé lundi 8h")
    notif.vider_file()
    assert len(envois) == 1
    assert "WR106" in envois[0][2]


def test_un_evenement_desactive_ne_declenche_rien(envois) -> None:
    _configurer(evenement="sans_salle")
    notif.signaler("deplacement", "WR106 déplacé")
    notif.vider_file()
    assert envois == []


def test_sans_destinataire_rien_ne_part(envois) -> None:
    notif.enregistrer_config({"destinataires": [], "evenements": {"deplacement": True}})
    notif.signaler("deplacement", "WR106 déplacé")
    notif.vider_file()
    assert envois == []


def test_chaque_destinataire_recoit_le_resume(envois) -> None:
    notif.enregistrer_config({
        "destinataires": ["a@b.fr", "c@d.fr"],
        "evenements": {"deplacement": True},
        "delai_minutes": 0,
    })
    notif.signaler("deplacement", "WR106 déplacé")
    notif.vider_file()
    assert sorted(to for to, _, _ in envois) == ["a@b.fr", "c@d.fr"]


# --------------------------------------------------------------------------
# Le point sensible : ne pas noyer la boîte
# --------------------------------------------------------------------------


def test_vingt_deplacements_donnent_UN_seul_mail(envois) -> None:
    """Le cas réel : une réorganisation, c'est vingt déplacements en dix
    minutes. Un mail chacun rendrait la fonctionnalité inutilisable."""
    _configurer()
    for i in range(20):
        notif.signaler("deplacement", f"séance {i} déplacée")
    notif.vider_file()
    assert len(envois) == 1
    assert "20" in envois[0][1] or envois[0][2].count("séance") == 20


def test_le_resume_liste_bien_tous_les_evenements(envois) -> None:
    _configurer()
    notif.signaler("deplacement", "premier")
    notif.signaler("deplacement", "deuxième")
    notif.vider_file()
    assert "premier" in envois[0][2] and "deuxième" in envois[0][2]


def test_le_resume_regroupe_des_evenements_de_types_differents(envois) -> None:
    notif.enregistrer_config({
        "destinataires": ["a@b.fr"],
        "evenements": {"deplacement": True, "sans_salle": True},
        "delai_minutes": 0,
    })
    notif.signaler("deplacement", "WR106 déplacé")
    notif.signaler("sans_salle", "WR314D sans salle")
    notif.vider_file()
    assert len(envois) == 1
    assert "WR106" in envois[0][2] and "WR314D" in envois[0][2]


def test_rien_a_signaler_n_envoie_pas_de_mail_vide(envois) -> None:
    _configurer()
    notif.vider_file()
    assert envois == []


def test_le_delai_retient_l_envoi(envois) -> None:
    """Avec un délai configuré, l'événement attend : c'est ce qui permet de
    grouper une rafale de modifications en un seul résumé."""
    _configurer(delai=15)
    notif.signaler("deplacement", "WR106 déplacé")
    notif.envoyer_si_temps_ecoule()
    assert envois == [], "trop tôt : le résumé doit encore attendre"
    notif.vider_file()  # forçage explicite
    assert len(envois) == 1


def test_un_echec_d_envoi_ne_fait_pas_echouer_l_appelant(monkeypatch) -> None:
    """Une notification est un à-côté : si le mail casse, le déplacement de
    séance qui l'a déclenchée doit quand même aboutir."""
    _configurer()

    def _explose(*_a, **_k):
        raise RuntimeError("Resend indisponible")

    monkeypatch.setattr(notif, "_envoyer", _explose)
    notif.signaler("deplacement", "WR106 déplacé")
    notif.vider_file()  # ne doit pas lever
