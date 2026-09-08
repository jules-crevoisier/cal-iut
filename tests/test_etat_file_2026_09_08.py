"""Voir ce qui se passe après avoir cliqué sur « Corriger ».

Retour utilisateur 08/09/2026, juste après le premier envoi réel : « là on
n'a pas vraiment de vue où l'on voit ce qu'il se passe si on appuie sur
corriger ».

Il avait raison, et le manque est exactement celui que cette semaine a
passé son temps à combler ailleurs : le bouton annonce « 38 corrections
mises en file », puis plus rien. Combien attendent encore ? Le worker est-il
passé ? Qu'a-t-il fait ? L'information existait, mais seulement dans
`docker compose logs`.

DEUX CHOSES À MONTRER, et elles ne disent pas la même chose :

  - la FILE : ce qui reste à faire. Elle se vide quand ça marche, elle
    stagne quand ça échoue — et c'est précisément ce qui a laissé passer
    trois jours de panne silencieuse ;
  - le DERNIER PASSAGE : quand, et avec quel résultat. Une file de 38 jobs
    « depuis 2 secondes » et « depuis 3 heures » n'appellent pas le même
    geste.

L'ÂGE du bilan compte autant que son contenu, pour la même raison que
l'instantané : un compte rendu vieux de trois heures présenté comme l'état
courant induit en erreur au moment précis où l'on vérifie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cal_iut.celcat import drainage


@pytest.fixture(autouse=True)
def _fichier_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(drainage, "_path", lambda: tmp_path / "celcat_drainage.json")
    yield


def test_sans_passage_l_absence_est_dite() -> None:
    """Ne jamais rendre « 0 réussi » quand le worker n'est simplement jamais
    passé : ce serait indiscernable d'un échec total."""
    bilan = drainage.dernier()

    assert bilan.passe_le is None
    assert bilan.age_secondes is None
    assert bilan.resume == ""


def test_un_passage_est_conserve_avec_son_horodatage() -> None:
    drainage.enregistrer(en_attente=38, reussis=12, echecs=26, ignores=0, resume="38 job(s) — 12 réussi(s)")

    bilan = drainage.dernier()
    assert bilan.en_attente == 38
    assert bilan.reussis == 12
    assert bilan.echecs == 26
    assert "12 réussi" in bilan.resume
    assert bilan.passe_le is not None
    assert bilan.age_secondes is not None and bilan.age_secondes < 60


def test_un_bilan_ancien_porte_son_age() -> None:
    """« 38 en attente depuis 2 secondes » et « depuis 3 heures » n'appellent
    pas le même geste."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    drainage.enregistrer(en_attente=38, reussis=0, echecs=38, ignores=0, resume="x", passe_le=vieux)

    assert drainage.dernier().age_secondes > 2 * 3600


def test_un_fichier_illisible_ne_plante_pas() -> None:
    """Le fichier est partagé entre deux conteneurs : une écriture peut être
    lue à mi-chemin. Mieux vaut « aucun passage connu » qu'une exception au
    milieu de l'écran."""
    drainage._path().write_text("{ pas du json", encoding="utf-8")

    assert drainage.dernier().passe_le is None


def test_l_api_sert_la_file_et_le_dernier_passage(db_isole) -> None:
    """Les deux ensemble : une file qui ne bouge pas malgré des passages
    réguliers est le signe d'une panne — c'est ce que trois jours de
    « file d'attente drainée » n'ont pas permis de voir."""
    from fastapi.testclient import TestClient

    from cal_iut.api.main import app
    from cal_iut.celcat.file_attente import enfiler, vider
    from conftest import creer_compte_actif_et_connecter

    client = TestClient(app)
    creer_compte_actif_et_connecter(client, role="admin")

    vider()
    enfiler({"action": "update", "session_id": "a", "event_id": 1})
    enfiler({"action": "delete", "session_id": "b", "event_id": 2})
    enfiler({"action": "update", "session_id": "c", "event_id": 3})
    drainage.enregistrer(en_attente=3, reussis=0, echecs=3, ignores=0, resume="3 job(s) — 0 réussi(s)")

    corps = client.get("/celcat/file").json()
    assert corps["en_attente"] == 3
    assert corps["par_action"] == {"update": 2, "delete": 1}
    assert corps["echecs"] == 3
    assert corps["passe_le"] is not None
    assert "0 réussi" in corps["resume"]


def test_l_api_refuse_un_anonyme(db_isole) -> None:
    from fastapi.testclient import TestClient

    from cal_iut.api.main import app

    client = TestClient(app)
    client.cookies.clear()
    assert client.get("/celcat/file").status_code in (401, 403)
