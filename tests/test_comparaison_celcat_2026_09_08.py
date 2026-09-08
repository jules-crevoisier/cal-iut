"""Comparer, séance par séance, ce que cal-iut place et ce que Celcat contient.

Demande utilisateur 08/09/2026 : « pour Celcat je voudrais un peu une
interface promo où l'on voit ce qu'il y a dans Celcat et que l'on puisse
comparer avec ce que l'on a sur cal-iut ».

La comparaison se fait ICI, côté serveur, et pas dans l'écran : le
rapprochement d'une séance et d'un évènement Celcat a des règles (code
matière, groupe, jour, et surtout l'heure avec son décalage de 9'21" dû au
fuseau historique de Paris) déjà écrites et testées dans
`ops.correspond_live`. Les réécrire en TypeScript aurait garanti qu'elles
divergent — et une comparaison fausse est pire qu'aucune comparaison :
elle enverrait corriger des séances qui vont bien.

QUATRE VERDICTS, parce que trois ne suffisent pas. « Présent des deux
côtés » ne dit rien : c'est justement quand la séance existe de part et
d'autre MAIS à des endroits différents qu'il faut agir — le cas du CM de
Régis Huez, déplacé à 15h30 dans cal-iut et resté à 14h dans Celcat pendant
des jours sans que rien ne le signale.

    identique        les deux concordent, rien à faire
    ecart            présente des deux côtés, mais salle/heure/jour diffèrent
    absente_celcat   placée dans cal-iut, introuvable dans Celcat
    en_trop_celcat   dans Celcat, plus placée dans cal-iut

Le dernier verdict est celui de la séance WR120 de Kyllian Bresson :
reportée dans cal-iut, toujours affichée aux étudiants dans Celcat.
"""

from __future__ import annotations

import pytest

from cal_iut.celcat.comparaison import comparer

# Un évènement Celcat tel que l'instantané le dépose. Les heures portent le
# décalage réel : Celcat écrit « 15:20 » là où cal-iut dit « 15:30 ».
def _ev(**kw):
    base = {
        "event_id": 1931709,
        "groupe": "BUT MMI S1 CM",
        "jour": 1,  # day_of_week brut, 0 = lundi
        "heure_debut": "15:20",
        "heure_fin": "16:50",
        "salle": "Amphi 3 MMI",
        "categorie": "[CM]",
        "enseignant": "HUEZ Regis",
        "module": "WR116 Traitement Info",
        "semaine": 3,
        "protected": "N",
    }
    base.update(kw)
    return base


def _placement(**kw):
    from types import SimpleNamespace

    base = {
        "session_id": "WR116-S1-CM-1",
        "course_code": "WR116",
        "week": 1,
        "day": 1,  # mardi
        "slot": 4,  # 15:30
        "room_label": "Amphi 3 MMI",
        "group_ids": [],
        "teacher_codes": ["RHU"],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_une_seance_bien_synchronisee_est_identique() -> None:
    """Le décalage de 9'21" ne doit PAS être vu comme un écart : sans quoi
    toutes les lignes seraient rouges et la vue inexploitable."""
    lignes = comparer(placements=[_placement()], evenements=[_ev()], semaine=1, semaine_celcat=3)

    assert len(lignes) == 1
    assert lignes[0]["statut"] == "identique"
    assert lignes[0]["ecarts"] == []


def test_une_heure_differente_est_un_ecart_et_non_une_absence() -> None:
    """Le cas du CM de Huez : présent des deux côtés, à deux heures
    différentes. Le classer « absent de Celcat » ferait créer un doublon."""
    lignes = comparer(
        placements=[_placement()],  # cal-iut : 15:30
        evenements=[_ev(heure_debut="13:50")],  # Celcat : 14:00
        semaine=1,
        semaine_celcat=3,
    )

    assert lignes[0]["statut"] == "ecart"
    assert "heure" in lignes[0]["ecarts"]
    assert lignes[0]["celcat"]["event_id"] == 1931709, "l'event_id permet d'aller corriger"


def test_une_salle_differente_est_signalee() -> None:
    lignes = comparer(
        placements=[_placement()], evenements=[_ev(salle="H.018")], semaine=1, semaine_celcat=3
    )

    assert lignes[0]["statut"] == "ecart"
    assert "salle" in lignes[0]["ecarts"]


def test_une_seance_absente_de_celcat() -> None:
    lignes = comparer(placements=[_placement()], evenements=[], semaine=1, semaine_celcat=3)

    assert lignes[0]["statut"] == "absente_celcat"
    assert lignes[0]["celcat"] is None


def test_un_evenement_celcat_sans_seance_est_en_trop() -> None:
    """Le cas de la séance WR120 de Kyllian : reportée dans cal-iut, encore
    affichée aux étudiants dans Celcat."""
    lignes = comparer(placements=[], evenements=[_ev()], semaine=1, semaine_celcat=3)

    assert len(lignes) == 1
    assert lignes[0]["statut"] == "en_trop_celcat"
    assert lignes[0]["caliut"] is None
    assert lignes[0]["celcat"]["event_id"] == 1931709


def test_seule_la_semaine_demandee_est_comparee() -> None:
    """Comparer toutes les semaines d'un coup noierait ce qui compte, et
    l'indice de semaine Celcat n'est pas le nôtre (décalage `weeks`)."""
    lignes = comparer(
        placements=[_placement(week=5)],
        evenements=[_ev(semaine=7)],
        semaine=1,
        semaine_celcat=3,
    )

    assert lignes == []


def test_les_ecarts_passent_avant_le_reste() -> None:
    """Une vue de supervision doit montrer d'abord ce qui demande une
    action : les lignes identiques ne se lisent pas, elles se comptent."""
    lignes = comparer(
        placements=[_placement(), _placement(session_id="WR117-S1-CM-1", course_code="WR117", day=2)],
        evenements=[_ev(heure_debut="13:50")],
        semaine=1,
        semaine_celcat=3,
    )

    assert lignes[0]["statut"] in ("ecart", "absente_celcat", "en_trop_celcat")
    assert lignes[0]["statut"] != "identique"


def test_un_evenement_ferie_ou_fantome_n_est_pas_compte_en_trop() -> None:
    """Celcat contient des évènements techniques (fériés, coquilles vides)
    qui n'ont pas vocation à correspondre à une séance : les signaler « en
    trop » enverrait supprimer des choses qu'il ne faut pas toucher."""
    lignes = comparer(
        placements=[],
        evenements=[_ev(module="", heure_debut="", heure_fin="", salle="")],
        semaine=1,
        semaine_celcat=3,
    )

    assert lignes == []


@pytest.mark.parametrize("statut_attendu", ["identique", "ecart", "absente_celcat"])
def test_chaque_ligne_porte_de_quoi_agir(statut_attendu: str) -> None:
    """Un identifiant de séance et, quand elle existe, la position des deux
    côtés : une ligne qui dit seulement « écart » oblige à rouvrir les deux
    outils pour comprendre."""
    cas = {
        "identique": ([_placement()], [_ev()]),
        "ecart": ([_placement()], [_ev(salle="H.018")]),
        "absente_celcat": ([_placement()], []),
    }[statut_attendu]
    ligne = comparer(placements=cas[0], evenements=cas[1], semaine=1, semaine_celcat=3)[0]

    assert ligne["session_id"] == "WR116-S1-CM-1"
    assert ligne["course_code"] == "WR116"
    assert ligne["caliut"]["heure"] == "15:30"
    assert ligne["caliut"]["salle"] == "Amphi 3 MMI"
