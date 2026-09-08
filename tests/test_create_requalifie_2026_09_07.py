"""Un job « create » vieilli ne doit pas créer un doublon.

Question de Jules Crevoisier, 07/09/2026 : « normalement on est censé avoir
des systèmes qui passent derrière et suppriment et réparent les doublons,
non ? ». Il en existe — `scripts/nettoyer_doublons_production_celcat.py`
(manuel) et le scan des extras (qui DÉTECTE les événements Celcat sans
correspondance, sans rien corriger) — mais aucun ne couvre ce cas.

Le contrôle « cette séance n'a pas encore d'event_id, donc c'est une
création » est fait par `ops.py::_executer` au moment d'ENFILER le job. Il
n'est jamais refait au moment de l'EXÉCUTER. Tant que la file se vidait en
quelques secondes, l'écart entre les deux instants était théorique.

Il ne l'est plus : la file de production comptait 463 jobs figés depuis
plusieurs jours (état applicatif jamais chargé côté sidecar, cf.
`test_etat_sidecar_2026_09_07`). Parmi eux, des « create » enfilés à une
date où la séance n'avait pas encore d'event_id — alors qu'elle en a un
depuis, posé par une saisie manuelle ou par la réconciliation du journal
(PR #114). Les exécuter tels quels créerait un second événement Celcat à
côté du premier, sur un outil qui sert aussi à payer les enseignants.

Le journal est la source de vérité au moment d'écrire, pas au moment
d'enfiler.
"""

from __future__ import annotations

from celcat_sync_helpers import (  # type: ignore[import-not-found]
    SEMAINE,
    activer_saisie,
    jobs_en_attente,
    place,
    poser_semaines_celcat,
    seance,
    vider_file,
)
from test_celcat_nuit import GROUP_ID, planning  # noqa: F401 — fixture réutilisée
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.api.state import get_state

EVENT_ID_DEJA_CONNU = 1933241


def _seance_placee(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _journaliser_event_id(session_id: str, event_id: int) -> None:
    """Pose un event_id au journal, comme le ferait une saisie manuelle ou
    `POST /celcat/journal/reconcilier`."""
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    journal = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}
    journal[session_id] = {"event_id": str(event_id), "semaine": SEMAINE}
    doc["journal"] = journal
    sauver(doc)


def test_un_create_dont_la_seance_a_reçu_un_event_id_devient_une_modification(
    planning, monkeypatch
) -> None:
    """Le cas dangereux : job enfilé hier, event_id apparu depuis."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _seance_placee("s-create-vieilli")
    _journaliser_event_id("s-create-vieilli", EVENT_ID_DEJA_CONNU)

    vider_file()
    enfiler({"action": "create", "session_id": "s-create-vieilli", "semaine": SEMAINE})
    poser_semaines_celcat()

    envoyes: list[int] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        envoyes.append(kw.get("event_id", 0))
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, kw.get("event_id") or 9999))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    bilan = drainer_file_immediate(FaussePage())

    assert envoyes == [EVENT_ID_DEJA_CONNU], (
        "l'écriture doit porter l'event_id connu (donc MODIFIER l'événement "
        "existant), jamais partir avec 0 et en créer un second"
    )
    assert bilan.reussis == 1
    assert jobs_en_attente() == []


def test_un_create_dont_la_seance_n_a_toujours_pas_d_event_id_cree_bien(
    planning, monkeypatch
) -> None:
    """Le cas normal doit rester intact : sans event_id connu, on crée."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _seance_placee("s-create-neuve")

    vider_file()
    enfiler({"action": "create", "session_id": "s-create-neuve", "semaine": SEMAINE})
    poser_semaines_celcat()

    envoyes: list[int] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        envoyes.append(kw.get("event_id", 0))
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 8000001))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    drainer_file_immediate(FaussePage())

    assert envoyes == [0], "aucun event_id connu : c'est une vraie création"
