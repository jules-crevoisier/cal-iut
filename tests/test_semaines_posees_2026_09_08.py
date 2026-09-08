"""N'écrire dans Celcat que sur les semaines déjà posées là-bas.

Consigne utilisateur 08/09/2026, devant une file de 491 jobs dont 409
créations : « il faut faire les modifications uniquement sur les semaines
posées », « les semaines pas posées dans Celcat il faut attendre ».

CE QU'ON ÉVITE. L'équipe pédagogique saisit Celcat semaine par semaine.
Relevé du jour : les semaines 3, 4 et 5 y tiennent environ trois cents
cours chacune, la 12 en tient 83, les semaines 7 à 21 entre neuf et
vingt-et-un, et une dizaine d'autres n'ont que des « Jour férié ». Pousser
nos créations sur une semaine encore vide déverse une promotion entière
dans un planning que personne n'a ouvert — et il faudra l'y démêler à la
main, alors qu'attendre ne coûte rien : la file est persistante.

CE QUI COMPTE COMME POSÉE. Pas un nombre absolu de cours — la taille d'une
promo change, un seuil codé en dur deviendrait faux sans prévenir. La
référence est ce que cal-iut PRÉVOIT sur cette semaine : une semaine est
posée quand Celcat en couvre au moins la moitié. Les semaines 3/4/5 sont
alors posées (Celcat les couvre presque intégralement), la 12 ne l'est pas
(83 sur trois cents, saisie visiblement en cours), et le choix se
recalibre tout seul quand l'équipe avance.

CE QUI N'EST PAS FILTRÉ. Un `update` ou un `delete` porte un `event_id` :
l'événement EXISTE déjà dans Celcat, donc la semaine y est posée par
construction. Les différer reviendrait à ne plus jamais corriger une heure
fausse — exactement le signalement de Régis Huez cette semaine.

LE PIÈGE. Le cycle est BORNÉ (`limite`) et prend les premiers jobs de la
file. Si les différés y restent en tête, chaque cycle reprend les mêmes et
n'écrit plus jamais rien : le filtre transformerait la file en blocage
définitif, la panne même que cette semaine a passé son temps à réparer. Le
tri doit donc précéder le découpage — c'est
`test_un_job_recevable_passe_meme_derriere_une_file_de_differes`.
"""

from __future__ import annotations

from datetime import date

import pytest
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
from cal_iut.celcat import instantane
from cal_iut.celcat.semaines_posees import (
    cours_par_semaine,
    motif_attente,
    semaines_posees,
)

IDS = {"module_id": 1, "room_id": 2, "staff_id": 3, "event_cat_id": 433, "dept_id": 4}


def _evts(indice: int, combien: int, *, categorie: str = "[TD]") -> list[dict]:
    return [
        {"event_id": 9000 + i, "semaine": indice, "categorie": categorie, "groupe": "BUT MMI S1 TD AB"}
        for i in range(combien)
    ]


# --------------------------------------------------------------------------
# La règle elle-même : pure, sans réseau ni état applicatif.
# --------------------------------------------------------------------------


def test_une_semaine_largement_remplie_est_posee() -> None:
    """Le cas nominal : Celcat couvre ce que cal-iut prévoit."""
    evenements = _evts(3, 323)

    assert 3 in semaines_posees(evenements, attendus={3: 330})


def test_une_semaine_a_peine_commencee_ne_l_est_pas() -> None:
    """La semaine 12 du relevé du 08/09/2026 : 83 cours saisis sur environ
    trois cents. La saisie est en cours — y déverser nos créations
    mélangerait notre planning au travail de l'équipe."""
    evenements = _evts(12, 83)

    assert 12 not in semaines_posees(evenements, attendus={12: 300})


def test_les_jours_feries_ne_font_pas_une_semaine_posee() -> None:
    """Huit semaines du relevé ne contiennent QUE des « Jour férié », un par
    groupe. Vingt-neuf évènements ont l'air d'un planning ; ce n'en est pas
    un. Seules les catégories de cours comptent — elles seules sont entre
    crochets (relevé des 38 catégories, 04/09/2026)."""
    evenements = _evts(18, 29, categorie="Jour férié") + _evts(18, 3, categorie="Conférence")

    assert semaines_posees(evenements, attendus={18: 300}) == set()
    assert cours_par_semaine(evenements) == {}


def test_sans_releve_aucune_semaine_n_est_posee() -> None:
    """Sans instantané, on ne SAIT pas ce que Celcat contient. Écrire à
    l'aveugle serait exactement le geste que la consigne interdit ; attendre
    ne coûte qu'un cycle."""
    assert semaines_posees([], attendus={3: 330, 4: 300}) == set()


def test_une_semaine_que_cal_iut_ne_prevoit_pas_n_est_jamais_posee() -> None:
    """Rien à y pousser : la question ne se pose pas, et diviser par zéro
    encore moins."""
    assert semaines_posees(_evts(7, 18), attendus={}) == set()


def test_le_seuil_se_recalibre_sur_ce_que_cal_iut_prevoit() -> None:
    """Aucun nombre absolu : les mêmes 40 cours Celcat font une semaine posée
    pour un petit effectif et une semaine en cours de saisie pour une grosse
    promo. C'est ce qui garde la règle juste quand la promo change de
    taille."""
    evenements = _evts(9, 40)

    assert 9 in semaines_posees(evenements, attendus={9: 60})
    assert 9 not in semaines_posees(evenements, attendus={9: 300})


def test_une_semaine_quasi_vide_ne_passe_pas_parce_que_cal_iut_y_prevoit_peu() -> None:
    """Le cas réel qui a fait ajouter la seconde condition (relevé du
    08/09/2026, indice 9) : Celcat n'y tient que 21 cours quand ses semaines
    posées en tiennent ~350 — la semaine n'est manifestement pas ouverte.
    Mais cal-iut n'y prévoit que 28 séances, si bien qu'une comparaison au
    seul planning cal-iut la déclarait couverte à 75 %.

    Comparer AUSSI à la meilleure semaine du relevé tranche : 21 sur 356,
    c'est une semaine que l'équipe n'a pas commencée.
    """
    releve = _evts(5, 356) + _evts(9, 21)

    posees = semaines_posees(releve, attendus={5: 157, 9: 28})

    assert 5 in posees
    assert 9 not in posees, "une semaine quasi vide ne doit pas passer"


def test_les_trois_semaines_reellement_posees_du_08_09_2026() -> None:
    """Le relevé et le planning RÉELS du jour, bout à bout — le seul test qui
    dise si la règle fait en production ce qu'on croit. Sans lui, tout ce
    fichier ne vérifie que des nombres inventés."""
    releve = (
        _evts(2, 0) + _evts(3, 323) + _evts(4, 288) + _evts(5, 356)
        + _evts(7, 18) + _evts(8, 12) + _evts(9, 21) + _evts(11, 11)
        + _evts(12, 83) + _evts(21, 9)
    )
    # `indice = semaine de planning + 2` (lundi 2026-09-07 -> indice 3).
    attendus = {
        2: 42, 3: 73, 4: 106, 5: 157, 6: 169, 7: 148, 8: 234, 9: 28,
        10: 43, 11: 180, 12: 108, 13: 237, 14: 29, 15: 93,
    }

    assert semaines_posees(releve, attendus=attendus) == {3, 4, 5}


def test_le_motif_dit_les_deux_nombres() -> None:
    """« semaine pas encore posée » sans chiffres n'apprend rien : c'est le
    rapport qui dit s'il faut attendre un jour ou relancer l'équipe."""
    motif = motif_attente(12, celcat=83, attendu=300)

    assert "12" in motif and "83" in motif and "300" in motif


# --------------------------------------------------------------------------
# L'effet réel : ce que le worker fait de la file.
# --------------------------------------------------------------------------


def _indice_de(entree) -> int:
    from cal_iut.celcat.lecture import indice_depuis_lundi
    from cal_iut.celcat.nuit import PREMIERE_SEMAINE_CELCAT

    return indice_depuis_lundi(
        date.fromisoformat(entree.lundi), premiere_semaine_celcat=PREMIERE_SEMAINE_CELCAT
    )


def _placer(session_id: str, *, semaine: int = SEMAINE):
    etat = get_state()
    s = seance(session_id)
    etat.sessions += [s]
    etat.sessions_by_id[session_id] = s
    etat.timetable += [place(s, week=semaine, day=2)]
    return s


def _entree(session_id: str):
    from cal_iut.celcat.mapping import entrees_pour_state

    return entrees_pour_state(get_state())[session_id]


@pytest.fixture
def ecriture_bouchonnee(monkeypatch):
    """Neutralise le RPC : ces tests portent sur ce qu'on DÉCIDE d'écrire,
    pas sur l'écriture."""
    ecrits: list[str] = []

    def _creer(page, entrees, **kw):
        from cal_iut.celcat.ecriture import ResultatEcriture

        r = ResultatEcriture()
        for e in entrees:
            ecrits.append(e.session_id)
            r.crees.append((e.session_id, 900000 + len(ecrits)))
        return r

    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_ids", lambda *a, **k: dict(IDS))
    monkeypatch.setattr("cal_iut.celcat.nuit.resoudre_groupe", lambda *a, **k: 1661972)
    monkeypatch.setattr("cal_iut.celcat.nuit.creer_manquants", _creer)
    return ecrits


def test_une_creation_sur_une_semaine_non_posee_reste_en_file(
    planning, ecriture_bouchonnee  # noqa: F811
) -> None:
    """Elle n'est ni écrite, ni perdue : elle ATTEND. Un job différé sorti de
    la file serait une séance qui n'arriverait jamais dans Celcat."""
    from cal_iut.celcat.file_attente import enfiler, lister
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-attente")
    enfiler({"action": "create", "session_id": "s-attente", "semaine": SEMAINE})
    instantane.enregistrer([], groupes=[])  # Celcat vide : rien n'est posé

    bilan = drainer_file_immediate(FaussePage())

    assert ecriture_bouchonnee == [], "aucune écriture ne doit partir"
    assert bilan.reussis == 0
    assert len(bilan.differes) == 1
    assert len(lister()) == 1, "le job doit RESTER en file pour un prochain cycle"
    assert bilan.echecs == [], "attendre n'est pas un échec"
    assert bilan.ignores == [], "attendre n'est pas un abandon"


def test_une_creation_sur_une_semaine_posee_part_normalement(
    planning, ecriture_bouchonnee  # noqa: F811
) -> None:
    """Le test qui protège du sur-filtrage : sans lui, un filtre trop strict
    bloquerait TOUT sans que rien ne le dise."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    _placer("s-posee")
    enfiler({"action": "create", "session_id": "s-posee", "semaine": SEMAINE})
    indice = _indice_de(_entree("s-posee"))
    instantane.enregistrer(_evts(indice, 20), groupes=["BUT MMI S1 TD AB"])

    bilan = drainer_file_immediate(FaussePage())

    assert ecriture_bouchonnee == ["s-posee"]
    assert bilan.reussis == 1
    assert bilan.differes == []


def test_un_job_recevable_passe_meme_derriere_une_file_de_differes(
    planning, ecriture_bouchonnee  # noqa: F811
) -> None:
    """LE test de cette PR.

    Le cycle est borné : il prend les premiers jobs de la file. Si le tri par
    semaine venait APRÈS le découpage, une file commençant par des différés
    rendrait un cycle vide, puis le suivant aussi, indéfiniment — le job
    recevable placé derrière ne serait jamais atteint. La file cesserait de
    se vider tout en ayant l'air de tourner : la panne exacte du 07/09/2026.
    """
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    activer_saisie(planning)
    vider_file()
    # Deux semaines RÉELLES du calendrier (1 à 38) : une semaine inexistante
    # n'aurait pas de lundi, donc pas d'indice, et passerait sans être
    # différée — elle aurait fait croire le test vert pour la mauvaise
    # raison.
    posee = 1
    autre = 20  # une semaine que Celcat n'a pas ouverte
    for i in range(5):
        _placer(f"s-loin-{i}", semaine=autre)
        enfiler({"action": "create", "session_id": f"s-loin-{i}", "semaine": autre})
    _placer("s-derriere", semaine=posee)
    enfiler({"action": "create", "session_id": "s-derriere", "semaine": posee})

    indice = _indice_de(_entree("s-derriere"))
    instantane.enregistrer(_evts(indice, 50), groupes=["BUT MMI S1 TD AB"])

    bilan = drainer_file_immediate(FaussePage(), limite=2)

    assert "s-derriere" in ecriture_bouchonnee, (
        "le job recevable doit être atteint malgré les différés en tête de file"
    )
    assert bilan.reussis == 1
    assert len(bilan.differes) == 5


@pytest.mark.parametrize("action", ["update", "delete"])
def test_une_correction_n_est_jamais_differee(
    planning, ecriture_bouchonnee, monkeypatch, action  # noqa: F811
) -> None:
    """Un `event_id` prouve que l'évènement existe dans Celcat, donc que la
    semaine y est posée. Différer une correction, ce serait laisser une heure
    fausse en ligne — le signalement de Régis Huez, précisément."""
    from cal_iut.celcat.file_attente import enfiler
    from cal_iut.celcat.nuit import drainer_file_immediate

    vus: list[str] = []

    def _modifier(page, elements, **kw):
        from cal_iut.celcat.modification import ResultatModification

        r = ResultatModification()
        for el in elements:
            vus.append(el.entree.session_id)
            r.modifiees.append((el.entree.session_id, el.event_id))
        return r

    def _supprimer(page, elements, **kw):
        from cal_iut.celcat.suppression import ResultatSuppression

        r = ResultatSuppression()
        for el in elements:
            vus.append(el.session_id)
            r.supprimees.append(el.session_id)
        return r

    monkeypatch.setattr("cal_iut.celcat.nuit.modifier_manquants", _modifier)
    monkeypatch.setattr("cal_iut.celcat.nuit.supprimer_manquants", _supprimer)

    activer_saisie(planning)
    vider_file()
    _placer("s-corrige")
    enfiler(
        {
            "action": action,
            "session_id": "s-corrige",
            "event_id": 1931709,
            "group_id": 1661972,
            "semaine": SEMAINE,
        }
    )
    instantane.enregistrer([], groupes=[])  # aucune semaine posée

    bilan = drainer_file_immediate(FaussePage())

    assert vus == ["s-corrige"], f"un {action} ne doit jamais être différé"
    assert bilan.differes == []
