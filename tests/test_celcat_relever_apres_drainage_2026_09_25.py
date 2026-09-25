"""Le worker doit demander un relevé frais après avoir RÉELLEMENT écrit.

Demande de Jules Crevoisier, 25/09/2026 : « une fois que le worker passe pour
corriger, on veut qu'en même temps il vérifie tous ces cas à nouveau, comme
ça il met à jour en même temps les écarts. »

Aujourd'hui le relevé Celcat n'est repris que toutes les deux heures, ou sur
un clic (`celcat/instantane.py`). Sans ce couplage, les écarts affichés après
une correction restent ceux d'AVANT le passage du worker jusqu'à l'une ou
l'autre échéance — exactement la confusion déjà réparée côté écran par
`useBoucleCelcat`.

Le fil retenu (le plus petit honnête) : `_consommer_file` (partagée par
`drainer_file_immediate`, le rythme temps réel, et `executer_job_nuit`, le
job de nuit) pose la DEMANDE de relevé — `instantane.demander()` — dès qu'au
moins un job a réellement réussi. `nuit-quotidienne.sh` appelle déjà
`celcat_instantane.py --vpn` juste après le drainage, dans la MÊME itération
de sa boucle (~30 s) : le cycle existant l'honore sans rien y changer.
"""

from __future__ import annotations

import pytest
from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    place,
    poser_semaines_celcat,
    seance,
    vider_file,
)
from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state
from cal_iut.celcat import instantane


@pytest.fixture(autouse=True)
def _instantane_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(instantane, "_path", lambda: tmp_path / "celcat_instantane.json")
    monkeypatch.setattr(instantane, "_path_demande", lambda: tmp_path / "celcat_instantane_demande.json")
    yield


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _ids_resolus(monkeypatch) -> None:
    monkeypatch.setattr(
        "cal_iut.celcat.nuit.resoudre_ids",
        lambda *_a, **_k: {
            "module_id": 1, "room_id": 2, "staff_id": 3,
            "event_cat_id": 433, "dept_id": 4,
        },
    )


def _creation_reussie(monkeypatch) -> None:
    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 900001))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)


def _creation_en_echec(monkeypatch) -> None:
    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        resultat.echecs.append((entrees[0].session_id, "Celcat indisponible"))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)


def _enfiler_creation(session_id: str) -> None:
    from cal_iut.celcat.file_attente import enfiler

    vider_file()
    _placer(session_id)
    enfiler({"action": "create", "session_id": session_id, "semaine": SEMAINE})
    poser_semaines_celcat()


def test_should_request_a_releve_when_a_drainage_pass_had_at_least_one_success(
    planning, monkeypatch  # noqa: F811
) -> None:
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creation("s-reussi")
    _ids_resolus(monkeypatch)
    _creation_reussie(monkeypatch)
    assert instantane.demande_en_cours() is False

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 1
    assert instantane.demande_en_cours() is True


def test_should_not_request_a_releve_when_nothing_succeeded(planning, monkeypatch) -> None:  # noqa: F811
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creation("s-echoue")
    _ids_resolus(monkeypatch)
    _creation_en_echec(monkeypatch)

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 0
    assert instantane.demande_en_cours() is False


def test_should_not_request_a_releve_when_the_queue_was_empty(planning) -> None:  # noqa: F811
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()

    bilan = drainer_file_immediate(FaussePage())

    assert not bilan
    assert instantane.demande_en_cours() is False


def test_a_releve_request_failure_does_not_break_an_otherwise_successful_pass(
    planning, monkeypatch  # noqa: F811
) -> None:
    """Même si poser le drapeau échoue (volume plein, permission...), le
    bilan du drainage — ce qui compte pour l'utilisateur — doit rester
    intact : une écriture réussie ne doit jamais se transformer en échec
    parce qu'une trace annexe n'a pas pu être posée."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _enfiler_creation("s-reussi-2")
    _ids_resolus(monkeypatch)
    _creation_reussie(monkeypatch)

    def _demande_en_echec() -> None:
        raise OSError("volume plein")

    monkeypatch.setattr("cal_iut.celcat.instantane.demander", _demande_en_echec)

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 1
    assert bilan.echecs == []


def test_should_also_request_a_releve_from_the_nightly_job_when_it_drains_successfully(
    planning, monkeypatch  # noqa: F811
) -> None:
    """`executer_job_nuit` appelle la MÊME `_consommer_file` que le rythme
    temps réel — le couplage doit valoir pour les deux chemins, pas
    seulement celui du bouton « Corriger »."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-nuit")
    enfiler({"action": "create", "session_id": "s-nuit", "semaine": SEMAINE})
    poser_semaines_celcat()
    _ids_resolus(monkeypatch)
    _creation_reussie(monkeypatch)

    executer_job_nuit(page=FaussePage())

    assert instantane.demande_en_cours() is True
