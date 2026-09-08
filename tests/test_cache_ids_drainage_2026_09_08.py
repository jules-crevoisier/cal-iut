"""Résoudre les mêmes ressources Celcat une fois, pas à chaque job.

Retour utilisateur 08/09/2026, devant un cycle qui n'en finissait pas :
« cela prend 2321 ans ». La file contenait 504 jobs et le worker en était
encore à son premier passage sept minutes plus tard.

CE QUE ÇA COÛTAIT. Chaque job appelait `_group_id_pour` puis `_ids_pour`,
soit une résolution complète — groupe, module, salle, personnel, catégorie,
département : environ six appels RPC. Pour 504 jobs, trois mille
allers-retours, alors que le planning ne compte qu'une poignée de
combinaisons distinctes (une matière dans une salle avec un enseignant).

`scripts/pousser_manquants_celcat.py` met déjà ces résolutions en cache
depuis le début — le worker, lui, ne l'a jamais fait. Le script manuel était
donc rapide et le worker interminable, pour un travail identique.

Le cache vit LE TEMPS D'UN CYCLE et pas au-delà : le catalogue Celcat peut
changer entre deux passages (une salle ajoutée, un module renommé), et un
cache persistant finirait par écrire avec des identifiants périmés — ce qui
est bien pire que lent.
"""

from __future__ import annotations

from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    place,
    seance,
    vider_file,
)
from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state

IDS = {"module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4}


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def test_les_memes_ressources_ne_sont_resolues_qu_une_fois(planning, monkeypatch) -> None:
    """Trois séances de la même matière, même salle, même enseignant : une
    seule résolution suffit. Sans cache, c'était trois fois six appels RPC."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    for i in range(3):
        _placer(f"s-cache-{i}")
        enfiler({"action": "create", "session_id": f"s-cache-{i}", "semaine": SEMAINE})

    resolutions = {"ids": 0, "groupes": 0}

    def _resoudre_ids(*_a, **_k):
        resolutions["ids"] += 1
        return dict(IDS)

    def _resoudre_groupe(*_a, **_k):
        resolutions["groupes"] += 1
        return 1661972

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        r = ResultatEcriture()
        r.crees.append((entrees[0].session_id, 900000))
        return r

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", _resoudre_ids)
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", _resoudre_groupe)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 3, "les trois séances doivent bien être traitées"
    assert resolutions["ids"] == 1, (
        f"une seule résolution d'ids attendue pour trois séances identiques, "
        f"reçu {resolutions['ids']}"
    )
    assert resolutions["groupes"] == 1, (
        f"une seule résolution de groupe attendue, reçu {resolutions['groupes']}"
    )


def test_des_ressources_differentes_sont_resolues_separement(planning, monkeypatch) -> None:
    """Le cache ne doit pas confondre deux séances qui n'ont pas la même
    salle : écrire avec l'identifiant d'une autre salle serait bien pire
    qu'un cycle lent."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    etat = get_state()
    for i, salle in enumerate(("H.101", "H.105")):
        s = seance(f"s-salle-{i}")
        etat.sessions += [s]
        etat.sessions_by_id[s.id] = s
        etat.timetable += [place(s, week=SEMAINE, day=2, room_id=salle.lower().replace(".", ""))]
        enfiler({"action": "create", "session_id": s.id, "semaine": SEMAINE})

    vues: list[str] = []

    def _resoudre_ids(_page, entree, **_k):
        vues.append(str(getattr(entree, "salle", "")))
        return dict(IDS)

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        r = ResultatEcriture()
        r.crees.append((entrees[0].session_id, 900001))
        return r

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", _resoudre_ids)
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *_a, **_k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    drainer_file_immediate(FaussePage())

    assert len(set(vues)) == len(vues), f"deux salles distinctes doivent être résolues à part : {vues}"
