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

MISE À JOUR DU 28/09/2026 — CE QUE CE FICHIER TESTAIT AVANT NE TIENT PLUS.

La décision du 08/09/2026 ci-dessus — « on oublie dès le premier échec sur
CE motif » — a elle-même produit un incident le MÊME jour : un `event_id`
oublié sur la foi d'un échec isolé, alors que l'évènement existait TOUJOURS
dans Celcat, a fait créer un second évènement à côté du premier. Un motif
qui prouve la disparition (« absent des group_ids ») ne prouve PAS qu'elle
est ARRIVÉE MAINTENANT : le relevé consulté par le job de nuit peut dater
d'avant la panne RPC qui vient d'échouer, auquel cas il ne dit rien de plus
que ce qu'on savait déjà.

La règle resserrée (`nuit.py::_resoudre_evenement_disparu`) remplace donc
« oublier au premier échec sur ce motif » par « ne décider que sur un
relevé PLUS RÉCENT que la disparition constatée, ET qui interroge le GROUPE
Celcat de la séance ». Le premier échec ne fait plus qu'une chose : noter
l'instant et redemander un relevé frais — sans toucher au journal ni à la
file. Ce n'est qu'au passage SUIVANT, une fois ce relevé disponible, que la
décision (oublier + recréer, ou rattacher au bon `event_id` retrouvé par la
comparaison) est prise. Trois tests ci-dessous changent en conséquence :
`test_un_evenement_introuvable_est_oublie_apres_un_releve_frais_et_couvrant`,
`test_apres_l_oubli_la_seance_repart_en_creation` et
`test_l_enregistrement_n_existe_pas_fait_oublier_aussi_apres_un_releve`.
Les deux garde-fous restants (panne réseau, ressource supprimée) ne
changent pas : ils ne prouvaient déjà rien, et continuent de laisser le
journal intact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from cal_iut.celcat.file_attente import lister

IDS = {"module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4}
EVENT_DISPARU = 1953820
# Groupe Celcat de « s-fantome » (semestre S1, groupe par défaut de
# `celcat_sync_helpers.seance` : « but1-td-ab » -> « BUT MMI S1 TD AB »,
# cf. `test_celcat_nuit.GROUPE`). Le relevé doit l'interroger pour que la
# règle resserrée accepte de décider quoi que ce soit sur cette séance.
GROUPE = "BUT MMI S1 TD AB"


def _releve_frais_et_couvrant(evenements: list[dict] | None = None) -> None:
    """Un relevé postérieur à la disparition constatée, qui interroge le
    groupe de « s-fantome » — les DEUX conditions que la règle resserrée
    exige avant de décider quoi que ce soit (cf. `_resoudre_evenement_
    disparu`). Horodaté explicitement dans le futur proche : un simple
    `datetime.now()` risquerait d'être trop proche de l'instant où le
    premier échec a été constaté pour garantir l'ordre sur une horloge de
    test rapide.

    Porte aussi UN évènement de remplissage sur la semaine de « s-fantome » :
    sans lui, ce relevé (qui remplace celui de `poser_semaines_celcat`, posé
    par `_preparer`) rendrait sa semaine « pas encore posée » aux yeux de
    `_ecarter_semaines_non_posees`, et le job — toujours une CRÉATION côté
    file — serait différé avant même d'atteindre `_resoudre_evenement_
    disparu`. Un module et un groupe qui ne matchent rien : il ne doit
    JAMAIS être pris pour l'évènement recherché."""
    from cal_iut.celcat.mapping import entrees_pour_state
    from cal_iut.celcat.nuit import _indice_pour

    entree = entrees_pour_state(get_state())["s-fantome"]
    remplissage = {
        "event_id": 700_000,
        "semaine": _indice_pour(entree),
        "categorie": "[TD]",
        "groupe": "AUTRE GROUPE",
        "module": "ZZZ999 Remplissage",
    }
    futur = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    instantane.enregistrer([remplissage, *(evenements or [])], groupes=[GROUPE], releve_le=futur)


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


def test_un_evenement_introuvable_est_oublie_apres_un_releve_frais_et_couvrant(
    planning, monkeypatch  # noqa: F811
) -> None:
    """REMPLACE `test_un_evenement_introuvable_est_oublie_du_journal` (08/09/2026).

    AVANT (08/09/2026) : un seul échec sur « absent des group_ids » oubliait
    l'`event_id` — ce qui a permis l'incident du MÊME jour, un doublon créé
    parce que l'oubli s'est produit sur un évènement en réalité toujours
    vivant. APRÈS (28/09/2026, `_resoudre_evenement_disparu`) : le premier
    échec ne fait que noter l'instant et redemander un relevé ; l'oubli
    n'intervient qu'au passage SUIVANT, sur un relevé prouvé plus récent que
    la disparition constatée ET qui interroge le groupe de la séance. Risque
    visé : recréer à côté d'un évènement qui existe toujours (doublon,
    incident du 08/09/2026).
    """
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(monkeypatch, f"event_id={EVENT_DISPARU} absent des group_ids=[1661972] interrogés")

    # Premier passage : la disparition est CONSTATÉE, rien n'est encore
    # décidé — c'est tout le point de la règle resserrée.
    drainer_file_immediate(FaussePage())
    assert _event_id_journal("s-fantome") == EVENT_DISPARU, (
        "au tout premier échec, rien ne prouve encore que l'évènement a "
        "vraiment disparu : le journal ne doit pas bouger"
    )

    # Un relevé FRAIS et qui COUVRE le groupe : les deux conditions posées
    # par la règle resserrée pour pouvoir enfin décider.
    _releve_frais_et_couvrant()

    drainer_file_immediate(FaussePage())

    assert _event_id_journal("s-fantome") is None, (
        "un relevé frais et couvrant, sans correspondance, doit faire "
        "oublier l'event_id mort"
    )
    creation = next(j for j in lister() if j.get("session_id") == "s-fantome")
    assert creation.get("action") == "create", (
        "l'oubli doit s'accompagner d'une VRAIE création en file, bout en bout"
    )


def test_apres_l_oubli_la_seance_repart_en_creation(planning, monkeypatch) -> None:  # noqa: F811
    """REMPLACE le test du même nom (08/09/2026) : l'effet recherché — au
    passage qui suit l'oubli, c'est bien une CRÉATION, sans `event_id` —
    tient toujours, mais l'oubli lui-même n'a plus lieu qu'après un relevé
    frais et couvrant (cf. le test précédent)."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(monkeypatch, f"event_id={EVENT_DISPARU} absent des group_ids=[1661972] interrogés")

    drainer_file_immediate(FaussePage())  # constate, ne décide rien
    _releve_frais_et_couvrant()
    drainer_file_immediate(FaussePage())  # décide : oublie + enfile une création

    assert _event_id_journal("s-fantome") is None

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


def test_l_enregistrement_n_existe_pas_fait_oublier_aussi_apres_un_releve(
    planning, monkeypatch  # noqa: F811
) -> None:
    """REMPLACE `test_l_enregistrement_n_existe_pas_fait_oublier_aussi`
    (08/09/2026) : l'autre formulation de Celcat pour la même chose —
    « L'enregistrement n'existe pas. Il a peut être été supprimé par un
    autre utilisateur. » — suit désormais la MÊME règle resserrée que
    « absent des group_ids » : un premier échec ne décide rien, il faut un
    relevé prouvé plus récent ET couvrant le groupe pour oublier
    l'`event_id` (même risque de doublon que ci-dessus si on décidait plus
    tôt)."""
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _preparer(
        monkeypatch,
        "RPC Celcat : {'code': 'EUDLDSError', 'message': \"L'enregistrement n'existe pas. "
        "Il a peut être été supprimé par un autre utilisateur.\"}",
    )

    drainer_file_immediate(FaussePage())
    assert _event_id_journal("s-fantome") == EVENT_DISPARU, (
        "premier échec : rien n'est encore prouvé, le journal ne bouge pas"
    )

    _releve_frais_et_couvrant()
    drainer_file_immediate(FaussePage())

    assert _event_id_journal("s-fantome") is None
