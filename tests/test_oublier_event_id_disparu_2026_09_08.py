"""Un event_id qui ne désigne plus rien doit être OUBLIÉ, pas rejoué.

Constaté en production le 08/09/2026 au soir. Huit séances restaient
« Absente de Celcat » cycle après cycle sans jamais être recréées :

    echec  WR106-S1-TD-1-but1-td-ab  event_id=1953820 absent des group_ids=[1661972]
    echec  WR101-S1-TD-1-but1-td-cd  event_id=1953810 absent des group_ids=[1661973]
    echec  WR115-S1-TP-1-but1-tp-g   event_id=1953813 absent des group_ids=[1661982]
    … les huit

L'ENCHAÎNEMENT. Ces évènements ont été supprimés de Celcat à 18h27. Le
journal, lui, a gardé leur `event_id`. Or `_consommer_file` requalifie une
création en modification dès que le journal connaît un identifiant — c'est
juste, et c'est ce qui empêche les doublons. Mais ici l'identifiant ne
désigne plus rien : `localiser_evenement` ne trouve pas l'évènement, la
modification échoue, le job repart en fin de file, et la séance n'est JAMAIS
recréée.

Une boucle parfaitement stable, avec toutes les apparences du travail : le
worker passe, échoue, recommence.

LE REMÈDE. Quand une modification échoue parce que l'évènement est
introuvable — et pour ce motif SEULEMENT — on retire l'entrée du journal.
Le job suivant repartira alors sur une vraie création.

CE MOTIF SEULEMENT, et c'est tout l'enjeu du garde-fou : oublier un
`event_id` sur une panne réseau ou un refus temporaire de Celcat ferait
créer un SECOND évènement à côté de celui qui existe toujours. Le journal
est la seule protection contre les doublons ; on ne l'efface que face à la
preuve que l'évènement a disparu.
"""

from __future__ import annotations

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

IDS = {"module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4}
EVENT_DISPARU = 1953820


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _journaliser(session_id: str, event_id: int) -> None:
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    journal = dict(doc.get("journal") or {})
    journal[session_id] = {"event_id": event_id, "signature": "peu importe"}
    doc["journal"] = journal
    sauver(doc)


def _event_id_journal(session_id: str):
    from cal_iut.celcat.etat import charger

    row = (charger().get("journal") or {}).get(session_id)
    return row.get("event_id") if isinstance(row, dict) else None


def _preparer(monkeypatch, motif: str):
    """Une création requalifiée dont la modification échoue sur `motif`."""
    from cal_iut.celcat.file_attente import enfiler

    _placer("s-fantome")
    _journaliser("s-fantome", EVENT_DISPARU)
    enfiler({"action": "create", "session_id": "s-fantome", "semaine": SEMAINE})
    poser_semaines_celcat()

    def _modifier(page, elements, **kw):
        from cal_iut.celcat.modification import ResultatModification

        resultat = ResultatModification()
        for el in elements:
            resultat.echecs.append((el.entree.session_id, motif))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _modifier)


def test_un_evenement_introuvable_est_oublie_du_journal(planning, monkeypatch) -> None:  # noqa: F811
    """LE cas des huit séances. Sans cet oubli, elles tournent en boucle sans
    jamais être recréées."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(monkeypatch, f"event_id={EVENT_DISPARU} absent des group_ids=[1661972] interrogés")

    drainer_file_immediate(FaussePage())

    assert _event_id_journal("s-fantome") is None, (
        "l'event_id mort doit être oublié, sinon la séance n'est jamais recréée"
    )


def test_apres_l_oubli_la_seance_repart_en_creation(planning, monkeypatch) -> None:  # noqa: F811
    """L'effet recherché : au passage suivant, c'est bien une CRÉATION."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(monkeypatch, f"event_id={EVENT_DISPARU} absent des group_ids=[1661972] interrogés")
    drainer_file_immediate(FaussePage())

    crees: list[int] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        crees.append(kw.get("event_id", 0))
        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 987654))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    drainer_file_immediate(FaussePage())

    assert crees == [0], f"une vraie création, sans event_id, reçu {crees}"


def test_une_panne_reseau_ne_fait_pas_oublier_l_event_id(planning, monkeypatch) -> None:  # noqa: F811
    """LE garde-fou de ce correctif, et il compte plus que le correctif.

    Le journal est la seule protection contre les doublons. Oublier un
    `event_id` sur une panne passagère ferait créer un SECOND évènement à
    côté de celui qui existe toujours — sur un outil qui sert aussi à payer
    les enseignants. On n'oublie que face à la preuve de la disparition.
    """
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(monkeypatch, "RPC Celcat : {'code': 'EUDLDSError', 'message': 'Timeout'}")

    drainer_file_immediate(FaussePage())

    assert _event_id_journal("s-fantome") == EVENT_DISPARU, (
        "un échec qui ne prouve pas la disparition doit laisser le journal intact"
    )


def test_une_ressource_supprimee_ne_fait_pas_oublier_non_plus(planning, monkeypatch) -> None:  # noqa: F811
    """« une des ressources affectées a été supprimée » parle d'une SALLE ou
    d'un ENSEIGNANT disparu, pas de l'évènement : celui-ci est toujours là,
    et le recréer en poserait un second."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(
        monkeypatch,
        "RPC Celcat : {'code': 'EUDLDSError', 'message': \"Impossible d'enregistrer "
        "l'événement, une des ressources affectées a été supprimée\"}",
    )

    drainer_file_immediate(FaussePage())

    assert _event_id_journal("s-fantome") == EVENT_DISPARU


def test_l_enregistrement_n_existe_pas_fait_oublier_aussi(planning, monkeypatch) -> None:  # noqa: F811
    """L'autre formulation de Celcat pour la même chose, vue le 08/09/2026 :
    « L'enregistrement n'existe pas. Il a peut être été supprimé par un autre
    utilisateur. »"""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(
        monkeypatch,
        "RPC Celcat : {'code': 'EUDLDSError', 'message': \"L'enregistrement n'existe pas. "
        "Il a peut être été supprimé par un autre utilisateur.\"}",
    )

    drainer_file_immediate(FaussePage())

    assert _event_id_journal("s-fantome") is None
