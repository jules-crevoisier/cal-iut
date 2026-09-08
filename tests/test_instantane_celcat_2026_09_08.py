"""Instantané de ce que contient Celcat, relevé par le sidecar.

Demande utilisateur 08/09/2026 : « on peut pas faire une vue qui nous
permette de consulter Celcat directement depuis l'outil, avec un bouton qui
permette de refresh quand l'on veut ? », puis, sur la cadence : « instantané
sur Celcat c'est un peu chiant pour la libération du VPN, on peut mettre
toutes les 2h et on peut fetch au click ».

CE QUI IMPOSE CETTE FORME. Le conteneur qui sert l'application n'a ni VPN ni
navigateur, et c'est délibéré : la passerelle URCA pousse un tunnel COMPLET,
donc monter le VPN là couperait le site public (cf. `celcat/reseau.py`).
Aucun appel synchrone « lis Celcat maintenant » n'est possible depuis l'API.

Seul le sidecar peut lire Celcat. Il dépose donc un relevé dans le volume
partagé, et l'API le sert tel quel. D'où deux exigences qui structurent tout
ce module :

1. L'ÂGE est aussi important que le contenu. Un relevé de deux heures
   présenté comme l'état courant induirait en erreur exactement au moment
   où l'on cherche à vérifier quelque chose — et cette semaine a montré ce
   que coûte une information qui a l'air fraîche sans l'être.

2. Le rafraîchissement est une DEMANDE, pas un ordre. Le bouton pose un
   drapeau que le sidecar honore à son prochain passage (30 à 60 s). Le dire
   franchement vaut mieux que de faire tourner un sablier en laissant croire
   à du direct.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cal_iut.celcat import instantane


@pytest.fixture(autouse=True)
def _fichiers_isoles(tmp_path, monkeypatch):
    monkeypatch.setattr(instantane, "_path", lambda: tmp_path / "celcat_instantane.json")
    monkeypatch.setattr(instantane, "_path_demande", lambda: tmp_path / "celcat_demande.json")
    yield


EVENEMENTS = [
    {
        "event_id": 1931709,
        "groupe": "BUT MMI S1 TD CD",
        "jour": 2,
        "heure_debut": "09:20",
        "heure_fin": "10:50",
        "salle": "H.007",
        "categorie": "[TD]",
        "enseignant": "LIBBRECHT Florent",
        "module": "WR120 Soutien",
        "semaine": 3,
    }
]


def test_sans_releve_l_absence_est_dite_clairement() -> None:
    """Ne jamais rendre une liste vide qui se lirait « Celcat est vide »."""
    releve = instantane.lire()

    assert releve.releve_le is None
    assert releve.evenements == []
    assert releve.age_secondes is None


def test_un_releve_conserve_ses_evenements_et_son_horodatage() -> None:
    instantane.enregistrer(EVENEMENTS, groupes=["BUT MMI S1 TD CD"])

    releve = instantane.lire()
    assert len(releve.evenements) == 1
    assert releve.evenements[0]["event_id"] == 1931709
    assert releve.groupes == ["BUT MMI S1 TD CD"]
    assert releve.releve_le is not None


def test_l_age_du_releve_est_calcule() -> None:
    """C'est ce que la vue affiche : « relevé il y a 47 min »."""
    instantane.enregistrer(EVENEMENTS, groupes=[])

    age = instantane.lire().age_secondes
    assert age is not None and 0 <= age < 60


def test_un_releve_ancien_est_signale_comme_perime() -> None:
    """Deux heures est la cadence choisie : au-delà, la vue doit le dire
    plutôt que de présenter le relevé comme l'état courant."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    instantane.enregistrer(EVENEMENTS, groupes=[], releve_le=vieux)

    releve = instantane.lire()
    assert releve.perime is True
    assert releve.age_secondes > 2 * 3600


def test_un_releve_recent_n_est_pas_perime() -> None:
    instantane.enregistrer(EVENEMENTS, groupes=[])

    assert instantane.lire().perime is False


# --------------------------------------------------------------------------
# La demande de rafraîchissement
# --------------------------------------------------------------------------


def test_aucune_demande_par_defaut() -> None:
    assert instantane.demande_en_cours() is False


def test_demander_puis_consommer() -> None:
    """Le bouton pose la demande ; le sidecar la consomme à son passage.
    Consommer la retire, sinon il relèverait à chaque cycle et reprendrait
    le VPN en boucle — précisément ce qu'on cherche à éviter."""
    instantane.demander()
    assert instantane.demande_en_cours() is True

    assert instantane.consommer_demande() is True
    assert instantane.demande_en_cours() is False
    assert instantane.consommer_demande() is False, "une demande ne vaut qu'une fois"


def test_demander_deux_fois_ne_fait_qu_une_demande() -> None:
    """Cliquer trois fois sur « Rafraîchir » ne doit pas provoquer trois
    relevés successifs."""
    instantane.demander()
    instantane.demander()
    instantane.demander()

    assert instantane.consommer_demande() is True
    assert instantane.consommer_demande() is False


def test_un_releve_est_du_quand_le_precedent_a_plus_de_deux_heures() -> None:
    """La cadence automatique, choisie pour ménager le VPN partagé."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)).isoformat()
    instantane.enregistrer(EVENEMENTS, groupes=[], releve_le=vieux)

    assert instantane.releve_du() is True


def test_aucun_releve_du_juste_apres_un_relevé() -> None:
    instantane.enregistrer(EVENEMENTS, groupes=[])

    assert instantane.releve_du() is False


def test_un_premier_releve_est_toujours_du() -> None:
    """Sans aucun relevé, la vue n'a rien à montrer : il faut en faire un."""
    assert instantane.releve_du() is True


def test_une_demande_rend_le_releve_du_meme_s_il_est_recent() -> None:
    """C'est tout l'intérêt du bouton : forcer avant l'échéance."""
    instantane.enregistrer(EVENEMENTS, groupes=[])
    assert instantane.releve_du() is False

    instantane.demander()
    assert instantane.releve_du() is True
