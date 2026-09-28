"""File Celcat sans issue : jobs qui tournent sans jamais aboutir, 28/09/2026.

Trois comportements signalés en production, tous les trois vus dans la file
de nuit après des passages qui n'apportent plus rien :

    1× event_id=1953851 absent des group_ids=[1660018] interrogés
       (ex. WR312D-S3-TP-13-but2-dev-fi-tp-d)                    — 3 015 tentatives
    1× event_id=1945020 absent des group_ids=[1660013] interrogés
       (ex. WR313D-S3-CM-1)                — 7 700+ tentatives depuis le 11/09
    1× RPC Celcat : 'You need modify access to ALL resource timetables…'
       (ex. WR319D-S3-CM-1)                — droits insuffisants, non réparable
    40× séance sans placement au planning (retirée, ou planning régénéré depuis)

LE DANGER PARTOUT PRÉSENT : créer un doublon dans Celcat (incident du
08/09/2026). D'où le principe directeur de chaque garde-fou ci-dessous :
dans le doute, ne rien faire, et le dire.

Ces tests appellent directement les fonctions de décision
(`_resoudre_evenement_disparu`, `_verifier_refus_droits`,
`_purger_si_session_disparue`) plutôt que de repasser par tout le pipeline de
`_consommer_file` à chaque cas : c'est plus court et surtout PLUS LISIBLE sur
ce qui est exactement prouvé — la logique d'appariement réutilisée
(`celcat/comparaison.py` via `celcat/planification.py`) est déjà couverte par
ses propres tests, on ne la re-teste pas ici. Un test de bout en bout ferme
le dossier (job normal non affecté).
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
from cal_iut.celcat.file_attente import (
    enfiler,
    est_bloque,
    lister,
    marquer_disparu_detecte,
    obtenir,
)
from cal_iut.celcat.logs import tous as logs_tous
from cal_iut.celcat.mapping import SLOT_TIMES, entrees_pour_state
from cal_iut.celcat.nuit import (
    SANS_PLACEMENT,
    BilanDrainage,
    _purger_si_session_disparue,
    _resoudre_evenement_disparu,
    _verifier_refus_droits,
)
from cal_iut.celcat.planification import ContexteComparaison
from cal_iut.celcat.sync import journal as journal_sync

GROUPE = "BUT MMI S1 TD AB"
IDS = {"module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4}
EVENT_PERDU = 1953820


def _placer(session_id: str):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=SEMAINE)]
    return s


def _entree(session_id: str):
    return entrees_pour_state(get_state())[session_id]


def _ctx(session_id: str, groupe: str = GROUPE) -> ContexteComparaison:
    return ContexteComparaison(
        groupes_celcat={session_id: groupe},
        salles_celcat={},
        codes_celcat=None,  # aucune restriction de périmètre pour ces tests
        types_seance={},
    )


def _job_update(session_id: str, *, event_id: int = EVENT_PERDU, **extra) -> dict:
    job = {
        "action": "update",
        "session_id": session_id,
        "event_id": event_id,
        "semaine": SEMAINE,
        "group_id": 1661972,
        **extra,
    }
    enfiler(job)
    return job


def _event_id_journal(session_id: str) -> int | None:
    row = journal_sync().get(session_id)
    return int(row["event_id"]) if isinstance(row, dict) and row.get("event_id") else None


def _journaliser(session_id: str, event_id: int) -> None:
    """Sème le journal AVANT résolution — sans ça, `_event_id_journal` vaut
    déjà None au départ et les assertions « ne doit pas bouger » ne
    prouveraient rien."""
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    journal = dict(doc.get("journal") or {})
    journal[session_id] = {"event_id": event_id, "signature": "peu importe", "semaine": str(SEMAINE)}
    doc["journal"] = journal
    sauver(doc)


MOTIF_DISPARU = f"event_id={EVENT_PERDU} absent des group_ids=[1661972] interrogés"


# ---------------------------------------------------------------------------
# 1. Relevé PÉRIMÉ (plus ancien que la disparition constatée) : rien décidé.
# ---------------------------------------------------------------------------


def test_releve_perime_ne_decide_rien_et_redemande(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    _placer("s-1")
    entree = _entree("s-1")
    job = _job_update("s-1")
    _journaliser("s-1", EVENT_PERDU)

    maintenant = datetime.now(UTC)
    detecte = maintenant.isoformat()
    marquer_disparu_detecte(job, detecte_le=detecte)
    # Un relevé plus ANCIEN que la disparition constatée : il ne prouve rien
    # de plus que ce qu'on savait déjà au moment de la détecter.
    perime = (maintenant - timedelta(hours=1)).isoformat()
    instantane.enregistrer([], groupes=[GROUPE], releve_le=perime)

    a_retirer: list = []
    _resoudre_evenement_disparu(
        job, entree, MOTIF_DISPARU, state=get_state(), ctx=_ctx("s-1"), a_retirer=a_retirer
    )

    assert a_retirer == [], "rien ne doit être décidé sur un relevé périmé"
    assert instantane.demande_en_cours(), "un relevé frais doit être redemandé"
    (restant,) = lister()
    assert int(restant["event_id"]) == EVENT_PERDU, "le job doit rester EXACTEMENT tel quel"
    assert _event_id_journal("s-1") == EVENT_PERDU, "le journal ne doit pas bouger"


# ---------------------------------------------------------------------------
# 2. Relevé frais mais qui n'interroge PAS le groupe de la séance : rien
#    décidé non plus — l'absence n'y prouve rien.
# ---------------------------------------------------------------------------


def test_releve_qui_ne_couvre_pas_le_groupe_ne_decide_rien(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    _placer("s-2")
    entree = _entree("s-2")
    job = _job_update("s-2")
    _journaliser("s-2", EVENT_PERDU)

    detecte = datetime.now(UTC).isoformat()
    marquer_disparu_detecte(job, detecte_le=detecte)
    apres = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    instantane.enregistrer([], groupes=["BUT MMI S1 TD ZZ"], releve_le=apres)

    a_retirer: list = []
    _resoudre_evenement_disparu(
        job, entree, MOTIF_DISPARU, state=get_state(), ctx=_ctx("s-2"), a_retirer=a_retirer
    )

    assert a_retirer == []
    assert instantane.demande_en_cours()
    (restant,) = lister()
    assert int(restant["event_id"]) == EVENT_PERDU
    assert _event_id_journal("s-2") == EVENT_PERDU


# ---------------------------------------------------------------------------
# 3. Relevé frais, couvre le groupe, ET un évènement correspondant existe
#    (la MÊME logique d'appariement que la comparaison) : le journal est
#    réécrit sur ce nouvel event_id, jamais une création.
# ---------------------------------------------------------------------------


def test_relevé_frais_avec_correspondance_reecrit_le_journal(planning) -> None:  # noqa: F811
    from cal_iut.celcat.nuit import _indice_pour

    activer_saisie(planning)
    vider_file()
    _placer("s-3")
    entree = _entree("s-3")
    job = _job_update("s-3")
    _journaliser("s-3", EVENT_PERDU)

    detecte = datetime.now(UTC).isoformat()
    marquer_disparu_detecte(job, detecte_le=detecte)

    indice_celcat = _indice_pour(entree)
    nouvel_event = 987654
    evenement = {
        "event_id": nouvel_event,
        "semaine": indice_celcat,
        "jour": 0,
        "heure_debut": SLOT_TIMES[0][0],
        "module": f"{entree.course_code} Cours",
        "groupe": GROUPE,
        "categorie": "[TD]",
        "salle": "H.101",
    }
    apres = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    instantane.enregistrer([evenement], groupes=[GROUPE], releve_le=apres)

    a_retirer: list = []
    _resoudre_evenement_disparu(
        job, entree, MOTIF_DISPARU, state=get_state(), ctx=_ctx("s-3"), a_retirer=a_retirer
    )

    # Retiré DIRECTEMENT par la fonction (jamais via `a_retirer`, qui
    # collisionnerait avec le remplacement — cf. le commentaire dans
    # `_resoudre_evenement_disparu`) : rien à repousser côté appelant ici.
    assert a_retirer == []
    assert _event_id_journal("s-3") == nouvel_event, "le journal doit pointer sur le NOUVEL event_id"

    (restant,) = lister()
    assert restant["action"] == "update", "une correspondance repart en modification, jamais en création"
    assert int(restant["event_id"]) == nouvel_event
    assert int(restant.get("tentatives_event_perdu") or 0) == 1


# ---------------------------------------------------------------------------
# 4. Relevé frais, couvre le groupe, AUCUN évènement correspondant : le
#    journal est oublié et une création repart, avec TOUS ses garde-fous.
# ---------------------------------------------------------------------------


def test_relevé_frais_sans_correspondance_reenfile_une_creation(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    _placer("s-4")
    entree = _entree("s-4")
    job = _job_update("s-4")
    _journaliser("s-4", EVENT_PERDU)

    detecte = datetime.now(UTC).isoformat()
    marquer_disparu_detecte(job, detecte_le=detecte)
    apres = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    instantane.enregistrer([], groupes=[GROUPE], releve_le=apres)

    a_retirer: list = []
    _resoudre_evenement_disparu(
        job, entree, MOTIF_DISPARU, state=get_state(), ctx=_ctx("s-4"), a_retirer=a_retirer
    )

    assert a_retirer == [], "retiré directement, jamais via `a_retirer` (collision de clé)"
    assert _event_id_journal("s-4") is None, "l'event_id mort doit être oublié"

    (restant,) = lister()
    assert restant["action"] == "create", "sans correspondance, une vraie création repart"
    assert restant.get("event_id") in (None, ""), "jamais d'event_id sur cette création"
    assert int(restant.get("tentatives_event_perdu") or 0) == 1


# ---------------------------------------------------------------------------
# 5. Trois tentatives de résolution sans succès : bloqué, plus jamais
#    retenté — mais le job reste visible en file.
# ---------------------------------------------------------------------------


def test_trois_tentatives_sans_succes_bloquent_le_job(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    _placer("s-5")
    entree = _entree("s-5")
    job = _job_update("s-5", tentatives_event_perdu=3)

    detecte = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    marquer_disparu_detecte(job, detecte_le=detecte)
    apres = datetime.now(UTC).isoformat()
    instantane.enregistrer([], groupes=[GROUPE], releve_le=apres)

    a_retirer: list = []
    _resoudre_evenement_disparu(
        job, entree, MOTIF_DISPARU, state=get_state(), ctx=_ctx("s-5"), a_retirer=a_retirer
    )

    assert a_retirer == [], "un job bloqué n'est pas retiré : il reste visible en file"
    (restant,) = lister()
    assert est_bloque(restant), "le job doit être en quarantaine"
    assert str(EVENT_PERDU) in str(restant.get("dernier_motif") or "")

    bloques = [l for l in logs_tous() if l.get("kind") == "blocked" and l.get("session_id") == "s-5"]
    assert bloques, "le blocage doit être journalisé"
    assert str(EVENT_PERDU) in str(bloques[-1].get("motif") or "")

    # Un quatrième appel ne doit RIEN retenter (le job est déjà bloqué).
    _resoudre_evenement_disparu(
        job, entree, MOTIF_DISPARU, state=get_state(), ctx=_ctx("s-5"), a_retirer=a_retirer
    )
    assert len(lister()) == 1, "aucun second job ne doit être enfilé sur un job bloqué"


# ---------------------------------------------------------------------------
# 6. Cinq refus RPC IDENTIQUES par manque de droits : bloqué.
# ---------------------------------------------------------------------------


def test_cinq_refus_droits_identiques_bloquent(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    job = _job_update("s-droits", event_id=42)
    motif = (
        "RPC Celcat : 'You need modify access to ALL resource timetables "
        "that are affected by this change.'"
    )

    for _ in range(4):
        _verifier_refus_droits(job, "s-droits", motif)
        assert not est_bloque(obtenir(job)), "pas encore au seuil"

    _verifier_refus_droits(job, "s-droits", motif)

    assert est_bloque(obtenir(job)), "le cinquième refus identique doit bloquer le job"
    bloques = [
        l for l in logs_tous() if l.get("kind") == "blocked" and l.get("session_id") == "s-droits"
    ]
    assert bloques, "le blocage doit être journalisé"
    assert "droits insuffisants" in str(bloques[-1].get("motif") or "")
    # Le job reste en file, jamais retiré en silence.
    (restant,) = lister()
    assert restant["session_id"] == "s-droits"


def test_quatre_refus_droits_ne_bloquent_pas(planning) -> None:  # noqa: F811
    """Le seuil compte, pas la répétition seule : sous 5, rien ne bloque."""
    activer_saisie(planning)
    vider_file()
    job = _job_update("s-presque-droits", event_id=43)
    motif = "RPC Celcat : 'You need modify access to ALL resource timetables…'"

    for _ in range(4):
        _verifier_refus_droits(job, "s-presque-droits", motif)

    assert not est_bloque(obtenir(job))


# ---------------------------------------------------------------------------
# 7. Purge d'un job dont la séance n'existe plus DU TOUT dans la maquette.
#    Décision du lead du 28/09/2026 : la purge journalise D'ABORD la MÊME
#    ligne (`kind="blocked"`, motif `SANS_PLACEMENT`) que l'ancien chemin
#    « ignoré » — jamais une ligne à part qui ferait disparaître
#    l'information du panneau des blocages — puis retire le job.
#    `session_id` porte un semestre LISIBLE (« S1 », deuxième segment) qui
#    correspond à une séance déjà présente dans l'état : c'est la condition
#    supplémentaire posée le 28/09/2026 (cf. `_purger_si_session_disparue`).
# ---------------------------------------------------------------------------

DISPARUE_S1 = "WR999D-S1-TP-1-test-disparue"


def test_purge_une_seance_disparue_de_la_maquette(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    _placer("s-existe-encore")  # peuple sessions_by_id d'une séance S1 : l'état n'est pas vide
    job = {"action": "create", "session_id": DISPARUE_S1, "semaine": SEMAINE}

    bilan = BilanDrainage()
    a_retirer: list = []
    purge = _purger_si_session_disparue(job, DISPARUE_S1, get_state(), a_retirer, bilan)

    assert purge is True
    assert a_retirer == [job]
    assert bilan.purges == [(DISPARUE_S1, SANS_PLACEMENT)]
    lignes = [l for l in logs_tous() if l.get("kind") == "blocked" and l.get("session_id") == DISPARUE_S1]
    assert lignes, "la purge doit journaliser la MÊME ligne qu'un job ignoré, pas une ligne à part"
    assert lignes[0]["motif"] == SANS_PLACEMENT


def test_purge_journalise_avant_de_retirer_le_job_de_la_file(planning) -> None:  # noqa: F811
    """Bout en bout, sur la VRAIE file : la ligne de blocage est déjà écrite
    au moment où la fonction rend la main — AVANT même que l'appelant
    n'exécute le retrait qu'elle lui a signalé via `a_retirer` (exactement
    ce que fait `_consommer_file`, une fois tous les jobs du cycle
    examinés). Jamais l'inverse, qui ferait disparaître un job de la file
    sans que rien n'explique pourquoi dans le panneau des blocages."""
    from cal_iut.celcat.file_attente import retirer_traites

    activer_saisie(planning)
    vider_file()
    _placer("s-existe-aussi")
    job = {"action": "create", "session_id": DISPARUE_S1, "semaine": SEMAINE}
    enfiler(job)
    assert any(j.get("session_id") == DISPARUE_S1 for j in lister())

    bilan = BilanDrainage()
    a_retirer: list = []
    assert _purger_si_session_disparue(job, DISPARUE_S1, get_state(), a_retirer, bilan) is True

    # LA PREUVE DE L'ORDRE : la ligne existe déjà alors que le job est
    # ENCORE en file — la fonction ne l'a que SIGNALÉ via `a_retirer`, elle
    # ne l'a pas retiré elle-même.
    lignes = [l for l in logs_tous() if l.get("kind") == "blocked" and l.get("session_id") == DISPARUE_S1]
    assert lignes, "la ligne doit exister avant même que l'appelant ait retiré le job de la file"
    assert any(j.get("session_id") == DISPARUE_S1 for j in lister()), (
        "la fonction ne retire pas elle-même : c'est `_consommer_file` qui le fait, via a_retirer"
    )

    retirer_traites(a_retirer)
    assert not any(j.get("session_id") == DISPARUE_S1 for j in lister()), (
        "une fois l'appelant averti (a_retirer) ET le retrait exécuté, le job quitte bien la file"
    )


def test_purge_refusee_si_aucune_seance_de_ce_semestre_dans_l_etat(planning) -> None:  # noqa: F811
    """Le garde-fou du 28/09/2026 : un état chargé sur un seul groupe de
    semestres (`semestre_group=odd|even`, cf. `ingestion/pipeline.py`) ne
    doit pas purger un job d'un AUTRE semestre — même famille de panne que
    l'état vide du 07/09/2026, à l'échelle d'un semestre. L'état ne contient
    ici que des séances S1 (`_placer` -> `seance()`, semestre fixe) ; un job
    S5 ne doit donc rien purger."""
    activer_saisie(planning)
    vider_file()
    _placer("s-existe-en-s1")  # une seule séance dans l'état, et elle est S1
    job = {"action": "create", "session_id": "WR501D-S5-TP-1-autre-semestre", "semaine": SEMAINE}

    bilan = BilanDrainage()
    a_retirer: list = []
    purge = _purger_si_session_disparue(
        job, "WR501D-S5-TP-1-autre-semestre", get_state(), a_retirer, bilan
    )

    assert purge is False, "aucune séance S5 dans l'état : rien ne prouve que ce job est vraiment orphelin"
    assert a_retirer == []
    assert bilan.purges == []


# ---------------------------------------------------------------------------
# 8. LE GARDE-FOU DU 07/09/2026 : un état applicatif VIDE ne purge JAMAIS
#    rien — sans quoi un redémarrage à froid viderait la file en croyant
#    que toutes les séances ont disparu.
# ---------------------------------------------------------------------------


def test_etat_vide_ne_purge_jamais_rien(planning) -> None:  # noqa: F811
    activer_saisie(planning)
    vider_file()
    etat = get_state()
    etat.sessions_by_id = {}
    etat.sessions = []
    job = {"action": "create", "session_id": "s-quelconque", "semaine": SEMAINE}

    bilan = BilanDrainage()
    a_retirer: list = []
    purge = _purger_si_session_disparue(job, "s-quelconque", etat, a_retirer, bilan)

    assert purge is False, "un état vide ne doit jamais purger — c'est la panne du 07/09/2026"
    assert a_retirer == []
    assert bilan.purges == []


# ---------------------------------------------------------------------------
# 9. Un job NORMAL, sans rien de ce qui précède, n'est touché par AUCUN des
#    nouveaux garde-fous.
# ---------------------------------------------------------------------------


def test_job_normal_non_touche_par_les_nouvelles_regles(planning, monkeypatch) -> None:  # noqa: F811
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-normal")
    enfiler({"action": "create", "session_id": "s-normal", "semaine": SEMAINE})
    poser_semaines_celcat()

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        resultat = ResultatEcriture()
        resultat.crees.append((entrees[0].session_id, 900_777))
        return resultat

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)

    bilan = drainer_file_immediate(FaussePage())

    assert bilan.reussis == 1
    assert bilan.echecs == []
    assert bilan.ignores == []
    assert bilan.purges == []
    assert lister() == [], "le job traité doit sortir de la file, comme avant ce correctif"
