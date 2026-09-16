"""La file est un répertoire de jobs, et non plus un tableau réécrit en entier.

Ce que ces tests protègent tient en une phrase : `backend` et `celcat-nuit`
écrivent tous les deux dans `data/state/`, et la version en tableau perdait
silencieusement un job enfilé pendant qu'un cycle se terminait. Les tests
historiques de `file_attente` couvrent le comportement observable (ordre,
déduplication, retraits) et continuent de passer tels quels ; ceux-ci
couvrent ce qu'ils ne pouvaient pas exprimer — la concurrence, la migration,
et le fait qu'un job déjà en échec ne redevienne pas neuf.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cal_iut.celcat import file_attente


@pytest.fixture(autouse=True)
def _file_isolee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Même isolation que `conftest` : on remplace `_path`, et `_repertoire`
    en hérite — c'est précisément pourquoi il est dérivé et non codé à part."""
    monkeypatch.setattr(file_attente, "_path", lambda: tmp_path / "celcat_file_attente.json")


def _job(action: str = "create", session_id: str = "s1", **extra: object) -> dict:
    return {"action": action, "session_id": session_id, **extra}


def test_un_fichier_par_job() -> None:
    file_attente.enfiler(_job(session_id="s1"))
    file_attente.enfiler(_job(session_id="s2"))
    fichiers = sorted(p.name for p in file_attente._repertoire().iterdir())
    assert len(fichiers) == 2, fichiers


def test_l_ordre_d_enfilage_est_conserve() -> None:
    """Le cycle est borné et prend les PREMIERS jobs : un ordre instable
    ferait revoir les mêmes à chaque passage."""
    for sid in ("a", "b", "c", "d"):
        file_attente.enfiler(_job(session_id=sid))
    assert [j["session_id"] for j in file_attente.lister()] == ["a", "b", "c", "d"]


def test_un_job_deja_en_echec_ne_redevient_pas_neuf() -> None:
    """Recliquer sur « Corriger » ré-enfile les mêmes jobs. Si l'enfilage
    réécrivait le fichier, le compteur d'échecs repartirait à zéro et la
    quarantaine ne pourrait jamais se déclencher — le job coûterait une
    session Celcat à chaque tour, indéfiniment."""
    file_attente.enfiler(_job(session_id="s1"))
    file_attente.marquer_echec(_job(session_id="s1"), "groupe Celcat introuvable")
    file_attente.marquer_echec(_job(session_id="s1"), "groupe Celcat introuvable")

    file_attente.enfiler(_job(session_id="s1"))

    (job,) = file_attente.lister()
    assert job["echecs"] == 2
    assert job["dernier_motif"] == "groupe Celcat introuvable"


def test_un_motif_different_repart_a_un() -> None:
    """Une panne réseau puis un vrai refus sont deux histoires : les
    additionner mettrait en quarantaine un job qui n'a échoué qu'une fois
    pour la raison qui compte."""
    file_attente.enfiler(_job(session_id="s1"))
    file_attente.marquer_echec(_job(session_id="s1"), "réseau indisponible")
    file_attente.marquer_echec(_job(session_id="s1"), "réseau indisponible")
    file_attente.marquer_echec(_job(session_id="s1"), "module sans code Celcat")

    (job,) = file_attente.lister()
    assert job["echecs"] == 1
    assert job["dernier_motif"] == "module sans code Celcat"


def test_un_job_illisible_ne_fait_pas_disparaitre_la_file() -> None:
    """LE POINT DE TOUTE LA BASCULE. Un tableau lu à mi-écriture rendait une
    file VIDE, donc « rien à pousser » — la panne parfaitement silencieuse.
    Ici un fichier abîmé ne coûte que lui-même."""
    file_attente.enfiler(_job(session_id="s1"))
    file_attente.enfiler(_job(session_id="s2"))
    abime = next(p for p in file_attente._repertoire().iterdir())
    abime.write_text('{"action": "cre', encoding="utf-8")

    restants = file_attente.lister()
    assert len(restants) == 1, "l'autre job doit survivre"


def test_enfiler_pendant_un_retrait_ne_perd_rien() -> None:
    """Le scénario exact de la perte : le worker retire ce qu'il a traité
    pendant que l'API enfile un déplacement de séance. Avec un tableau
    réécrit en entier, le nouveau job disparaissait."""
    file_attente.enfiler(_job(session_id="traite"))
    file_attente.enfiler(_job(session_id="aussi-traite"))
    a_retirer = list(file_attente.lister())

    # L'API enfile ENTRE la lecture du worker et son écriture.
    file_attente.enfiler(_job(session_id="arrive-entre-temps"))
    file_attente.retirer_traites(a_retirer)

    assert [j["session_id"] for j in file_attente.lister()] == ["arrive-entre-temps"]


def test_enfiler_pendant_une_rotation_ne_perd_rien() -> None:
    """Même scénario avec `repousser_en_fin`, qui réécrivait lui aussi toute
    la file. Le job qui arrive pendant la rotation doit rester, et rester
    devant les repoussés."""
    file_attente.enfiler(_job(session_id="maudit"))
    file_attente.enfiler(_job(session_id="sain"))
    echecs = [j for j in file_attente.lister() if j["session_id"] == "maudit"]

    file_attente.enfiler(_job(session_id="arrive-entre-temps"))
    file_attente.repousser_en_fin(echecs)

    ordre = [j["session_id"] for j in file_attente.lister()]
    assert ordre == ["sain", "arrive-entre-temps", "maudit"], ordre


def test_le_tableau_historique_est_migre_puis_conserve(tmp_path: Path) -> None:
    """Le déploiement ne doit rien avoir à faire — et un retour en arrière
    doit rester possible, d'où le renommage plutôt qu'une suppression."""
    legacy = tmp_path / "celcat_file_attente.json"
    legacy.write_text(
        json.dumps(
            [
                {"action": "update", "session_id": "s1", "event_id": 42, "semaine": 3},
                {"action": "create", "session_id": "s2", "semaine": 3},
            ]
        ),
        encoding="utf-8",
    )

    jobs = file_attente.lister()

    assert [j["session_id"] for j in jobs] == ["s1", "s2"]
    assert int(jobs[0]["event_id"]) == 42
    assert not legacy.exists(), "le tableau migré ne doit plus être relu"
    assert (tmp_path / "celcat_file_attente.json.migre").exists(), (
        "il doit rester lisible si l'on veut revenir en arrière"
    )


def test_la_migration_ne_rejoue_pas_les_jobs_deja_traites(tmp_path: Path) -> None:
    """Une migration qui repasserait à chaque appel ferait ressusciter des
    jobs retirés entre-temps — donc réécrirait dans Celcat ce qui vient
    d'y être écrit."""
    legacy = tmp_path / "celcat_file_attente.json"
    legacy.write_text(json.dumps([{"action": "create", "session_id": "s1"}]), encoding="utf-8")

    file_attente.lister()
    file_attente.vider()

    assert file_attente.lister() == []


def test_creer_et_supprimer_la_meme_seance_sont_deux_jobs() -> None:
    """La clé reste `(action, session_id, event_id)` : les confondre ferait
    disparaître une suppression demandée."""
    file_attente.enfiler(_job("create", "s1"))
    file_attente.enfiler(_job("delete", "s1", event_id=42, group_id=7))
    assert sorted(j["action"] for j in file_attente.lister()) == ["create", "delete"]


def test_un_session_id_a_rallonge_ne_casse_pas_le_nommage() -> None:
    """Les identifiants réels ressemblent à
    `WRA305M-S3-TD-1-but2-creacom-fc-td-gh` : composer un nom de fichier en
    clair frôlerait les limites de longueur et les caractères interdits."""
    long = "WRA305M-S3-TD-1-but2-creacom-fc-td-gh" * 8
    file_attente.enfiler(_job(session_id=long))
    (job,) = file_attente.lister()
    assert job["session_id"] == long
