"""Un évènement Celcat n'appartient qu'à UNE séance.

Signalement d'origine — Kyllian Bresson, 02/10/2026 : « la séance de Julie
Bastard effectuée le vendredi 11/09 à 17h avec le TD CD dans le module
WR312D se décale encore sur Celcat, il faudrait pouvoir identifier la cause.
Ça vient sûrement aussi du module que j'ai réadapté pour que les deux
enseignants (JBA et AHA) aient tous les groupes. »

Constaté dans l'activité du robot : l'évènement Celcat 1945024 était écrit
tour à tour pour `WR312D-S3-TD-3-but2-dev-fi-td-cd` (vendredi 11/09, 17h00,
JBA) et pour `WR312D-S3-TD-2-but2-dev-fi-td-cd` (vendredi 02/10, 11h00, AHA)
— treize écritures en cinq jours. Le journal rattachait les DEUX séances au
même évènement : il avait été créé pour l'une, puis adopté par l'autre après
le réaménagement du module, sans que la première le rende. Chaque correction
déplaçait l'unique évènement vers une séance et le retirait à l'autre.
Même situation, pas encore déclenchée, pour 1949589 (TD-4 et TD-5 du TD CD).
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

EVENEMENT = 1945024
TD2 = "WR312D-S3-TD-2-but2-dev-fi-td-cd"
TD3 = "WR312D-S3-TD-3-but2-dev-fi-td-cd"


def _seance_placee(session_id: str, day: int):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=day)]
    return s


def _poser_journal(lignes: dict[str, dict]) -> None:
    from cal_iut.celcat.etat import _path
    from cal_iut.celcat.fichiers import ecrire_json

    # Écrit TEL QUEL, comme l'état trouvé en production (sans passer par les
    # fonctions qu'on corrige).
    ecrire_json(_path(), {"version": 2, "saisie_active": True, "journal": lignes}, sort_keys=True)


def test_le_journal_ne_garde_qu_une_seance_par_evenement() -> None:
    from cal_iut.celcat.etat import journal_sans_doublons

    journal = {
        TD2: {"session_id": TD2, "event_id": str(EVENEMENT), "saisi_le": "2026-10-01T10:34:13+00:00"},
        TD3: {"session_id": TD3, "event_id": str(EVENEMENT), "saisi_le": "2026-10-02T15:51:40+00:00"},
        "autre": {"session_id": "autre", "event_id": "2024883", "saisi_le": "2026-09-28T10:09:25+00:00"},
        "sans-evenement": {"session_id": "sans-evenement", "signature": "x"},
    }
    propre, retires = journal_sans_doublons(journal)
    assert set(propre) == {TD3, "autre", "sans-evenement"}, "la dernière séance écrite garde l'évènement"
    assert retires == [(TD2, str(EVENEMENT))]
    assert journal_sans_doublons(propre) == (propre, [])


def test_le_journal_charge_est_deja_nettoye(planning) -> None:
    from cal_iut.celcat.etat import charger

    _poser_journal({
        TD2: {"session_id": TD2, "event_id": str(EVENEMENT), "saisi_le": "2026-10-01T10:34:13+00:00"},
        TD3: {"session_id": TD3, "event_id": str(EVENEMENT), "saisi_le": "2026-10-02T15:51:40+00:00"},
    })
    assert set(charger()["journal"]) == {TD3}


def test_rattacher_un_evenement_le_retire_a_son_ancienne_seance(planning) -> None:
    from cal_iut.celcat.etat import charger
    from cal_iut.celcat.mapping import entrees_pour_state
    from cal_iut.celcat.sync import marquer_saisi

    activer_saisie(planning)
    _seance_placee(TD2, day=1)
    _seance_placee(TD3, day=4)
    entrees = entrees_pour_state(get_state())
    marquer_saisi(entrees[TD2], event_id=EVENEMENT, group_id=GROUP_ID)
    marquer_saisi(entrees[TD3], event_id=EVENEMENT, group_id=GROUP_ID)  # TD3 adopte l'évènement

    journal = charger()["journal"]
    assert journal[TD3]["event_id"] == str(EVENEMENT)
    assert TD2 not in journal, "TD2 n'a plus d'évènement : elle sera créée, pas déplacée"


def test_la_seance_depossedee_est_creee_et_l_evenement_ne_bouge_plus(planning, monkeypatch) -> None:
    """Le va-et-vient de production : la comparaison trouve TD2 absente de sa
    semaine et demande sa création. Avant, le robot « savait » que TD2 avait
    l'évènement 1945024 et le DÉPLAÇAIT — le retirant à TD3."""
    from cal_iut.celcat.etat import charger
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    _seance_placee(TD2, day=1)
    _seance_placee(TD3, day=4)
    doc = charger()
    doc["journal"] = {
        TD2: {"session_id": TD2, "event_id": str(EVENEMENT), "semaine": str(SEMAINE),
              "saisi_le": "2026-10-01T10:34:13+00:00"},
        TD3: {"session_id": TD3, "event_id": str(EVENEMENT), "semaine": str(SEMAINE),
              "saisi_le": "2026-10-02T15:51:40+00:00"},
    }
    from cal_iut.celcat.etat import _path
    from cal_iut.celcat.fichiers import ecrire_json

    ecrire_json(_path(), doc, sort_keys=True)

    vider_file()
    enfiler({"action": "create", "session_id": TD2, "semaine": SEMAINE})
    poser_semaines_celcat()

    crees: list[int] = []
    modifies: list[int] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        crees.append(kw.get("event_id", 0))
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 2040001))
        return resultat

    def _modifier(page, elements, **kw):
        from cal_iut.celcat.modification import ResultatModification

        resultat = ResultatModification()
        for el in elements:
            modifies.append(el.event_id)
            resultat.modifiees.append((el.entree.session_id, el.event_id))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _modifier)

    bilan = drainer_file_immediate(FaussePage())

    assert modifies == [], f"l'évènement de TD3 ne doit plus être déplacé (reçu {modifies})"
    assert crees == [0], "TD2 reçoit son propre évènement"
    assert bilan.reussis == 1 and jobs_en_attente() == []
    journal = charger()["journal"]
    assert journal[TD3]["event_id"] == str(EVENEMENT)
    assert journal[TD2]["event_id"] == "2040001"


def test_la_reconciliation_ne_rattache_pas_un_evenement_deja_pris(planning) -> None:
    from cal_iut.celcat.etat import charger
    from cal_iut.celcat.sync import reconcilier

    _poser_journal({TD3: {"session_id": TD3, "event_id": str(EVENEMENT), "saisi_le": "2026-10-02T15:51:40+00:00"}})
    fusionnees, deja, ignorees = reconcilier([{"session_id": TD2, "event_id": EVENEMENT, "semaine": SEMAINE}])
    assert (fusionnees, deja, ignorees) == (0, 0, [TD2])
    assert set(charger()["journal"]) == {TD3}
