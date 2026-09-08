"""Une création requalifiée doit passer par le chemin MODIFICATION.

Trouvé le 08/09/2026 par l'audit de la chaîne Celcat, en cherchant pourquoi
« Cannot locate a record using only a partial key » était devenu le motif
d'échec dominant (25 échecs sur 25 lors de certains cycles, toutes promos et
tous types confondus).

L'ENCHAÎNEMENT. `_consommer_file` requalifie une création en modification
quand le journal connaît déjà l'`event_id` — c'est juste, créer poserait un
doublon. Mais elle le faisait en appelant `creer_manquants(..., event_id=N)`,
et `charge_utile` RECONSTRUIT alors l'évènement à partir de rien :

    "rooms":   [{"room_id": 42}]
    "staff":   [{"staff_id": 7}]
    "modules": [{"module_id": 13}]

Or `modification.py` documente exactement cette forme comme la cause du
message d'erreur : un sous-objet de ressource doit porter `event_id`,
`dept_id`, `unique_name`, `name` et `weeks`, faute de quoi Celcat ne
retrouve pas l'enregistrement et refuse — « partial key ».

LE CHEMIN CORRECT EXISTE DÉJÀ. `modifier_manquants` recharge l'évènement
COMPLET depuis Celcat (`localiser_evenement`) puis n'écrase que les champs
qui changent (`fusionner_deltas`). C'est le remède documenté ; il suffit d'y
router les créations requalifiées au lieu de les envoyer en création.

POURQUOI CE TEST N'EXISTAIT PAS. `test_create_requalifie_2026_09_07.py`
vérifie bien que l'`event_id` est transmis — mais il monkeypatche
`creer_manquants` en entier, donc il ne peut RIEN voir de la charge envoyée.
Il prouvait que l'intention était bonne, pas que l'écriture l'était. C'est
la même leçon que la semaine a déjà servie deux fois : un test qui ne
descend pas jusqu'au geste réel ne protège pas du geste réel.
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
EVENT_ID = 1931709


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE, day=2)]
    return s


def _journaliser_event_id(session_id: str, event_id: int) -> None:
    """Le journal connaît l'évènement : la création doit être requalifiée."""
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    journal = doc.get("journal") if isinstance(doc.get("journal"), dict) else {}
    journal[session_id] = {"event_id": event_id, "signature": "peu importe"}
    doc["journal"] = journal
    sauver(doc)


def _bouchons(monkeypatch):
    """Enregistre par où passe l'écriture, sans toucher au réseau."""
    vus: dict[str, list] = {"creations": [], "modifications": []}

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        for e in entrees:
            vus["creations"].append((e.session_id, kw.get("event_id")))
            resultat.crees.append((e.session_id, EVENT_ID))
        return resultat

    def _modifier(page, elements, **kw):
        from cal_iut.celcat.modification import ResultatModification

        resultat = ResultatModification()
        for el in elements:
            vus["modifications"].append((el.entree.session_id, el.event_id))
            resultat.modifiees.append((el.entree.session_id, el.event_id))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _modifier)
    return vus


def test_un_create_dont_l_event_id_est_connu_part_en_modification(planning, monkeypatch) -> None:  # noqa: F811
    """LE test de ce correctif. La création requalifiée ne doit PLUS emprunter
    `creer_manquants` : cette voie envoie une charge reconstruite, que Celcat
    refuse par « partial key »."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-deja-dans-celcat")
    _journaliser_event_id("s-deja-dans-celcat", EVENT_ID)
    enfiler({"action": "create", "session_id": "s-deja-dans-celcat", "semaine": SEMAINE})
    poser_semaines_celcat()
    vus = _bouchons(monkeypatch)

    bilan = drainer_file_immediate(FaussePage())

    assert vus["creations"] == [], (
        "une séance déjà connue de Celcat ne doit jamais repartir en création : "
        "la charge reconstruite est refusée « partial key »"
    )
    assert vus["modifications"] == [("s-deja-dans-celcat", EVENT_ID)], (
        f"elle doit emprunter le chemin modification, reçu {vus['modifications']}"
    )
    assert bilan.reussis == 1


def test_un_create_reellement_neuf_reste_une_creation(planning, monkeypatch) -> None:  # noqa: F811
    """Non-régression : 60 séances manquent VRAIMENT dans Celcat. Router tout
    vers la modification les empêcherait d'exister."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-vraiment-neuve")
    enfiler({"action": "create", "session_id": "s-vraiment-neuve", "semaine": SEMAINE})
    poser_semaines_celcat()
    vus = _bouchons(monkeypatch)

    drainer_file_immediate(FaussePage())

    assert vus["creations"] == [("s-vraiment-neuve", 0)], (
        f"une séance absente de Celcat doit être créée, reçu {vus}"
    )
    assert vus["modifications"] == []


def test_le_meme_job_enfile_deux_fois_n_ecrit_qu_une_fois(planning, monkeypatch) -> None:  # noqa: F811
    """Deux clics sur « Corriger », ou le balayage de nuit doublé par une
    correction manuelle, produisaient DEUX jobs identiques — donc deux appels
    RPC, donc deux évènements Celcat. `enfiler` ne dédoublonnait pas, et la
    relecture du journal annoncée par le commentaire ne pouvait pas rattraper
    le coup : elle lit `doc`, chargé une seule fois au début du cycle."""
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-en-double")
    job = {"action": "create", "session_id": "s-en-double", "semaine": SEMAINE}
    enfiler(dict(job))
    enfiler(dict(job))
    poser_semaines_celcat()

    assert len(lister()) == 1, f"un job identique ne doit pas s'empiler : {lister()}"

    vus = _bouchons(monkeypatch)
    drainer_file_immediate(FaussePage())

    assert len(vus["creations"]) == 1, (
        f"une seule écriture attendue, reçu {vus['creations']} — deux poseraient deux évènements"
    )


def test_deux_jobs_differents_sur_la_meme_seance_coexistent(planning, monkeypatch) -> None:  # noqa: F811
    """Le garde-fou du dédoublonnage : « créer » puis « supprimer » la même
    séance sont deux intentions distinctes, pas un doublon. Les confondre
    ferait disparaître une suppression demandée."""
    from cal_iut.celcat.file_attente import enfiler, lister

    vider_file()
    enfiler({"action": "create", "session_id": "s-x", "semaine": SEMAINE})
    enfiler({"action": "delete", "session_id": "s-x", "event_id": 42, "group_id": 7})

    assert len(lister()) == 2
