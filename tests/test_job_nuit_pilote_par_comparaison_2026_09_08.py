"""Le job de nuit enfile ce qui DIVERGE, plus le planning entier.

Demande utilisateur 08/09/2026 : « il faut bien fix cela et tout ce que l'on
a fait pour les prochaines saisies, hein ? ».

La question porte juste. Tout ce qui a été réparé aujourd'hui — filtre des
semaines posées, rotation de file, requalification, comparaison de la
catégorie — traite la file TELLE QU'ELLE EST. Mais elle se remplit par
`executer_job_nuit`, qui enfilait une CRÉATION pour chaque séance dont le
journal ignore l'`event_id`, sans jamais regarder ce que Celcat contient :

    409 créations pour les semaines 1-3, quand 60 séances seulement manquent.

Aujourd'hui le problème est en SOMMEIL — `semaines_validees` vaut [1,2,3] et
`semaines_lancees` aussi, donc l'ensemble à balayer est vide. Le jour où
Jules valide la semaine 4, les ~350 créations aveugles repartent, et tout le
travail de la journée est défait.

CE QUI CHANGE. Le balayage passe par la comparaison : `identique` n'engendre
plus rien, un `ecart` devient une modification portant l'`event_id` relevé,
seule une séance réellement `absente_celcat` devient une création, et un
évènement `en_trop_celcat` devient une suppression.

SANS RELEVÉ, ON N'ENFILE RIEN. Toutes les séances paraîtraient absentes de
Celcat : le balayage créerait alors un doublon de tout le planning. Même
garde-fou que le bouton « Corriger », pour exactement la même raison — et
c'est le seul cas où ne rien faire vaut mieux que faire.
"""

from __future__ import annotations

from celcat_sync_helpers import (  # type: ignore[import-not-found]
    activer_saisie,
    jobs_en_attente,
    place,
    seance,
    vider_file,
)
from test_celcat_nuit import planning  # noqa: F401 — fixture réutilisée

from cal_iut.api.state import get_state
from cal_iut.celcat import instantane

# Une semaine À VENIR, jamais la semaine courante : `semaines_celcat_passees`
# retire du balayage la semaine en cours, si bien qu'un test posé sur la
# semaine 1 passait au vert sans que le balayage ne tourne — vert pour la
# mauvaise raison. Semaine 12 du planning = lundi 2026-11-30 = indice 15.
SEMAINE, INDICE = 12, 15
GROUPE_CELCAT = "BUT MMI S1 TD AB"
EVENT_ID = 1931666


def _valider(semaine: int) -> None:
    """`semaine` est un INDICE de planning, comme `placement.week`.

    L'état persisté, lui, garde des PASTILLES 1..30 — c'est ce que pose
    l'écran (`AdminCelcatView`), et la pastille n désigne l'indice n-1. La
    conversion vit ici, en un seul endroit, pour que les tests continuent de
    se lire « je valide la semaine de cette séance ».
    """
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    doc["semaines_validees"] = [semaine + 1]
    doc["semaines_lancees"] = []
    sauver(doc)


def _placer(session_id: str, *, jour: int = 0, slot: int = 0):
    """UNE seule séance au planning, et c'est délibéré.

    Le fixture `planning` en pose déjà une sur cette même semaine : la
    laisser ferait comparer deux séances là où le test n'en décrit qu'une, et
    le verdict porterait sur la mauvaise.
    """
    etat = get_state()
    s = seance(session_id)
    etat.sessions = [s]
    etat.sessions_by_id = {session_id: s}
    etat.timetable = [place(s, week=SEMAINE, day=jour, slot=slot)]
    return s


def _ev(*, heure: str = "08:00", salle: str = "H.101", categorie: str = "[TD]") -> dict:
    return {
        "event_id": EVENT_ID,
        "groupe": GROUPE_CELCAT,
        "jour": 0,
        "heure_debut": heure,
        "heure_fin": "09:30",
        "salle": salle,
        "categorie": categorie,
        "module": "WR101",
        "semaine": INDICE,
    }


def test_une_seance_deja_dans_celcat_n_engendre_aucun_job(planning) -> None:  # noqa: F811
    """LE cœur de la demande. Celcat a déjà cette séance, au bon créneau :
    le balayage ne doit RIEN enfiler — ni création (doublon), ni
    modification inutile."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-deja-la")
    _valider(SEMAINE)
    instantane.enregistrer([_ev()], groupes=[GROUPE_CELCAT])

    executer_job_nuit()

    assert jobs_en_attente() == [], (
        f"une séance qui concorde ne doit engendrer aucun job, reçu {jobs_en_attente()}"
    )


def test_une_seance_absente_devient_une_creation(planning) -> None:  # noqa: F811
    """Non-régression : 60 séances manquent VRAIMENT. Ne plus rien créer
    serait aussi faux que tout créer."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-absente")
    _valider(SEMAINE)
    # Un relevé RÉEL qui ne contient simplement pas cette séance — pas un
    # relevé vide, que le balayage refuse désormais (un Celcat qui paraît
    # vide et un Celcat qu'on n'a pas lu se ressemblent trop).
    instantane.enregistrer(
        [{**_ev(), "event_id": 4242, "module": "WR999", "semaine": INDICE + 1}],
        groupes=[GROUPE_CELCAT],
    )

    executer_job_nuit()

    jobs = jobs_en_attente()
    assert [j["action"] for j in jobs] == ["create"], jobs


def test_un_ecart_devient_une_modification_avec_l_event_id(planning) -> None:  # noqa: F811
    """Jamais une création : créer poserait un doublon à côté de l'évènement
    existant. C'est tout le risque des 350 créations superflues."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-mauvaise-salle")
    _valider(SEMAINE)
    instantane.enregistrer([_ev(salle="H.007")], groupes=[GROUPE_CELCAT])

    executer_job_nuit()

    jobs = jobs_en_attente()
    assert len(jobs) == 1, jobs
    assert jobs[0]["action"] == "update"
    assert jobs[0]["event_id"] == EVENT_ID


def test_une_categorie_fausse_devient_une_modification(planning) -> None:  # noqa: F811
    """Le signalement de David : un TD étiqueté [CM]. Il doit repartir en
    modification, sans quoi la faute reste en ligne indéfiniment."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-mal-etiquetee")
    _valider(SEMAINE)
    instantane.enregistrer([_ev(categorie="[CM]")], groupes=[GROUPE_CELCAT])

    executer_job_nuit()

    jobs = jobs_en_attente()
    assert [j["action"] for j in jobs] == ["update"], jobs
    assert jobs[0]["event_id"] == EVENT_ID


def test_sans_releve_le_balayage_n_enfile_rien(planning) -> None:  # noqa: F811
    """Sans instantané, toutes les séances paraissent absentes : le balayage
    créerait un doublon de tout le planning. Ne rien faire vaut mieux."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-quelconque")
    _valider(SEMAINE)

    executer_job_nuit()

    assert jobs_en_attente() == [], (
        "sans relevé on ne sait pas ce que Celcat contient : on n'écrit pas à l'aveugle"
    )


def test_un_releve_vide_est_traite_comme_une_absence_de_releve(planning) -> None:  # noqa: F811
    """Un Celcat qui paraît VIDE et un Celcat qu'on n'a pas lu se ressemblent
    trop pour être traités différemment : dans les deux cas toutes les
    séances semblent absentes, et le balayage créerait un doublon du planning
    entier. Le second cas est même le plus traître — `releve_le` est
    renseigné, donc le relevé a l'air valide."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-quelconque")
    _valider(SEMAINE)
    instantane.enregistrer([], groupes=[GROUPE_CELCAT])

    executer_job_nuit()

    assert jobs_en_attente() == [], "un relevé vide ne doit rien déclencher"


def test_la_semaine_reste_non_lancee_sans_releve(planning) -> None:  # noqa: F811
    """Le garde-fou du garde-fou. Marquer la semaine « lancée » alors qu'on
    n'a rien enfilé la retirerait du balayage pour toujours : elle ne
    partirait JAMAIS. C'est précisément ce qui est arrivé aux semaines 1, 2
    et 3, marquées lancées sans qu'un seul job ne parte (07/09/2026)."""
    from cal_iut.celcat.etat import charger
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-quelconque")
    _valider(SEMAINE)

    executer_job_nuit()

    assert SEMAINE not in (charger().get("semaines_lancees") or []), (
        "une semaine sans relevé ne doit pas être marquée lancée : elle ne "
        "serait plus jamais balayée"
    )
