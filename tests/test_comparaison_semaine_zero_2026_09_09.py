"""La semaine 0 est une semaine comme les autres — `0 or -1` vaut -1.

LE SIGNALEMENT. Jules Crevoisier, 09/09/2026 : « je comprends pas pourquoi
dans la semaine 2 j'ai [39 lignes « En trop dans Celcat »] alors que l'on en
avait 1 la dernière fois », puis « la semaine 2 c'était la semaine dernière,
en semaine universitaire on avait cours ».

« Semaine 2 (31 août-4 sept. 2026) » est l'étiquette de l'INDICE 0 du
planning. Et le filtre des placements s'écrivait :

    du_planning = [p for p in placements
                   if int(getattr(p, "week", -1) or -1) == int(semaine)]

Pour `p.week == 0`, `0 or -1` vaut **-1**. Aucun placement de la première
semaine de cours n'entrait donc dans la comparaison : cal-iut paraissait ne
RIEN y prévoir, et chaque cours que Celcat y possède ressortait « en trop
dans Celcat » — c'est-à-dire candidat à la SUPPRESSION
(`planification.jobs_depuis_lignes` traduit `en_trop_celcat` en job
`delete`).

MESURÉ SUR LES DONNÉES RÉELLES du 09/09/2026, semaine 0, BUT3 alternance :

    avant : 38 en_trop_celcat,  0 identique
    après : 30 identique, 5 ecart, 3 en_trop_celcat, 1 absente_celcat

POURQUOI ÇA SORT MAINTENANT. Le défaut est ancien, mais il était masqué :
tant que `BUT MMI S5 TD EF` et `TD GH` manquaient à `celcat_groupes.yaml`,
le relevé ne lisait pas leurs évènements, et il n'y avait rien à déclarer
« en trop ». Les ajouter (PR #150) a RÉVÉLÉ le défaut, il ne l'a pas créé —
et il l'a rendu dangereux, puisque la suppression exige justement un
`group_id` résoluble.

Le même piège existait sur `ev["semaine"]`, l'indice de masque Celcat, dont
0 est une semaine parfaitement valide.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cal_iut.celcat.comparaison import comparer
from cal_iut.celcat.planification import jobs_depuis_lignes

GROUPE = "BUT MMI S5 TD EF"


def _placement(**kw):
    base = {
        "session_id": "WRA505D-S5-TD-1-but3-dev-fc-td-ef",
        "course_code": "WRA505D",
        "week": 0,
        "day": 1,
        "slot": 2,          # 11:00
        "room_label": "H.005",
        "room_id": None,
        "group_ids": ["but3-dev-fc-td-ef"],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _ev(**kw):
    base = {
        "event_id": 1924087,
        "groupe": GROUPE,
        "jour": 1,
        "heure_debut": "10:50",   # décalage historique de Paris
        "heure_fin": "12:20",
        "salle": "H.005",
        "categorie": "[TD]",
        "enseignant": "",
        "module": "WRA505D Dvpt front",
        "semaine": 2,             # indice de masque = semaine planning + 2
        "protected": "N",
    }
    base.update(kw)
    return base


def _comparer(placements, evenements, *, semaine=0, semaine_celcat=2):
    return comparer(
        placements=placements,
        evenements=evenements,
        semaine=semaine,
        semaine_celcat=semaine_celcat,
        groupes_celcat={p.session_id: GROUPE for p in placements},
        salles_celcat={},
        codes_celcat={"WRA505D"},
        types_seance={p.session_id: "TD" for p in placements},
    )


# --------------------------------------------------------------------------
# LE défaut
# --------------------------------------------------------------------------


def test_une_seance_de_la_semaine_zero_est_bien_comparee() -> None:
    """Sans le correctif : `en_trop_celcat` + rien du côté cal-iut."""
    lignes = _comparer([_placement()], [_ev()])

    statuts = [ligne["statut"] for ligne in lignes]
    assert statuts == ["identique"], (
        f"la semaine 0 doit être comparée comme les autres, reçu {lignes}"
    )


def test_la_semaine_zero_ne_produit_aucune_suppression() -> None:
    """CE QUI ÉTAIT EN JEU. `en_trop_celcat` devient un job `delete` : le
    défaut ne faisait pas qu'afficher faux, il proposait d'effacer de vrais
    cours posés par l'équipe pédagogique."""
    lignes = _comparer([_placement()], [_ev()])

    jobs = jobs_depuis_lignes(lignes, semaine=0, group_id_pour_nom=lambda _n: 1662681)

    assert [j for j in jobs if j["action"] == "delete"] == [], (
        f"aucune suppression ne doit sortir d'une séance qui concorde : {jobs}"
    )


def test_un_evenement_a_l_indice_celcat_zero_est_bien_candidat() -> None:
    """Le même piège sur l'autre indice : `ev["semaine"] == 0`."""
    lignes = _comparer(
        [_placement(week=0)], [_ev(semaine=0)], semaine=0, semaine_celcat=0
    )

    assert [ligne["statut"] for ligne in lignes] == ["identique"]


# --------------------------------------------------------------------------
# Non-régressions : ce que le filtre doit continuer d'écarter
# --------------------------------------------------------------------------


@pytest.mark.parametrize("absent", [None, "", "n'importe quoi"])
def test_un_placement_sans_semaine_lisible_reste_ecarte(absent: object) -> None:
    """Rendre 0 valide ne doit pas rendre valide « je ne sais pas » : un
    placement sans semaine comparé à la semaine 0 la peuplerait de séances
    qui n'y sont pas."""
    lignes = _comparer([_placement(week=absent)], [_ev()])

    assert [ligne["statut"] for ligne in lignes] == ["en_trop_celcat"], (
        "sans semaine lisible, le placement ne doit pas entrer dans la "
        f"comparaison de la semaine 0 : {lignes}"
    )


def test_une_seance_d_une_autre_semaine_reste_hors_du_lot() -> None:
    lignes = _comparer([_placement(week=1)], [_ev()])

    assert [ligne["statut"] for ligne in lignes] == ["en_trop_celcat"]


def test_un_evenement_d_un_autre_indice_reste_hors_du_lot() -> None:
    lignes = _comparer([_placement()], [_ev(semaine=5)])

    assert [ligne["statut"] for ligne in lignes] == ["absente_celcat"]
