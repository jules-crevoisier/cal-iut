"""La pastille n° n désigne l'indice n-1 — et le balayage l'ignorait.

Signalement de Jules Crevoisier, 09/09/2026, sur une séance restée
« Absente de Celcat » sans que rien ne la crée jamais :

    WRA507D-S5-TD-2-but3-dev-fc-td-ef
    mercredi 02/09 09:30 — H.205 (VR/Réseaux) — Absente de Celcat
    « Pourquoi on peut pas la régler, cela ? »

DEUX NUMÉROTATIONS, ET ELLES SE CROISAIENT.

L'écran et tout l'état persisté parlent en PASTILLES 1..30 :

    AdminCelcatView : Array.from({length: 30}, (_, i) => i + 1)
    _semaines_celcat_completes : [n for n in 1..30 if (n - 1) not in indices]
    semaines_celcat_passees : « Chips 1..30 dont la semaine S1 est terminée »

La pastille n désigne donc l'INDICE n-1 du planning. Or `executer_job_nuit`
lisait `semaines_validees` et s'en servait directement comme indice :
`lundis[semaine]`, puis `lignes_comparaison(semaine=...)` comparé à
`placement.week`, qui est un indice 0-basé.

Deux conséquences :

1. valider une semaine faisait balayer la SUIVANTE — donc la semaine
   validée n'était jamais traitée, et une autre l'était sans qu'on l'ait
   demandé ;
2. l'indice 0 (semaine du 31/08/2026) était INATTEIGNABLE, la plus petite
   pastille valant 1. Aucun passage ne pouvait créer WRA507D.

La conversion se fait maintenant en un seul endroit, à l'entrée de
`executer_job_nuit`, et le fichier d'état garde ses pastilles : les
réécrire en indices réinterpréterait en silence ce qui est déjà enregistré
en production.
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

# Une semaine À VENIR : `semaines_celcat_passees` retire du balayage la
# semaine en cours et les précédentes, et un test posé sur une semaine
# passée passerait au vert sans que le balayage ne tourne.
INDICE_PLANNING = 12
PASTILLE = INDICE_PLANNING + 1
INDICE_CELCAT = 15
GROUPE_CELCAT = "BUT MMI S1 TD AB"


def _etat(**champs) -> None:
    from cal_iut.celcat.etat import charger, sauver

    doc = charger()
    doc.update(champs)
    sauver(doc)


def _placer(session_id: str, semaine: int):
    etat = get_state()
    s = seance(session_id)
    etat.sessions = [s]
    etat.sessions_by_id = {session_id: s}
    etat.timetable = [place(s, week=semaine)]
    return s


def _releve_sans_la_seance() -> None:
    """Un relevé RÉEL qui ne contient simplement pas cette séance — pas un
    relevé vide, que le balayage refuse (un Celcat qui paraît vide et un
    Celcat qu'on n'a pas lu se ressemblent trop)."""
    instantane.enregistrer(
        [
            {
                "event_id": 4242, "groupe": GROUPE_CELCAT, "jour": 0,
                "heure_debut": "08:00", "heure_fin": "09:30", "salle": "H.101",
                "categorie": "[TD]", "enseignant": "", "module": "WR999",
                "semaine": INDICE_CELCAT + 1,
            }
        ],
        groupes=[GROUPE_CELCAT],
    )


def test_valider_une_pastille_balaie_la_semaine_qu_elle_designe(planning) -> None:  # noqa: F811
    """LE correctif. Pastille 13 -> indice 12, celui de la séance."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-pastille", INDICE_PLANNING)
    _etat(semaines_validees=[PASTILLE], semaines_lancees=[])
    _releve_sans_la_seance()

    executer_job_nuit()

    jobs = jobs_en_attente()
    assert [j["session_id"] for j in jobs] == ["s-pastille"], jobs
    assert jobs[0]["semaine"] == INDICE_PLANNING, (
        "le job doit porter l'INDICE, c'est lui que le drainage compare"
    )


def test_valider_la_pastille_voisine_ne_balaie_pas_cette_semaine(planning) -> None:  # noqa: F811
    """L'ancien comportement, retourné : consommer la pastille comme un
    indice faisait balayer la semaine SUIVANTE."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-voisine", INDICE_PLANNING)
    _etat(semaines_validees=[INDICE_PLANNING], semaines_lancees=[])
    _releve_sans_la_seance()

    executer_job_nuit()

    assert jobs_en_attente() == [], (
        "la pastille 12 désigne l'indice 11, où rien n'est posé : "
        f"reçu {jobs_en_attente()}"
    )


def test_les_semaines_lancees_restent_des_pastilles(planning) -> None:  # noqa: F811
    """L'écran relit ce champ tel quel pour griser les pastilles : y écrire
    des indices décalerait l'affichage d'un cran."""
    from cal_iut.celcat.etat import charger
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-lancee", INDICE_PLANNING)
    _etat(semaines_validees=[PASTILLE], semaines_lancees=[])
    _releve_sans_la_seance()

    executer_job_nuit()

    assert charger()["semaines_lancees"] == [PASTILLE], (
        f"reçu {charger()['semaines_lancees']}, attendu la pastille {PASTILLE}"
    )


def test_une_semaine_deja_lancee_n_est_pas_rebalayee(planning) -> None:  # noqa: F811
    """Non-régression : la conversion doit valoir dans les DEUX sens, sinon
    une semaine lancée serait relue comme une autre et rebalayée sans fin."""
    from cal_iut.celcat.nuit import executer_job_nuit

    activer_saisie(planning)
    vider_file()
    _placer("s-deja-lancee", INDICE_PLANNING)
    _etat(semaines_validees=[PASTILLE], semaines_lancees=[PASTILLE])
    _releve_sans_la_seance()

    executer_job_nuit()

    assert jobs_en_attente() == [], (
        f"une semaine déjà lancée ne doit rien réenfiler : {jobs_en_attente()}"
    )
