"""La comparaison doit rendre le même verdict quel que soit l'ordre du relevé.

POURQUOI CE TEST EXISTE. L'appariement consommait les évènements dans l'ordre
de retour de `udlTimetables.load`, que Celcat ne garantit pas stable, et
`_correspond` accepte volontairement un évènement dont l'heure diffère —
c'est l'écart qu'on veut signaler. Deux séances de même matière, même groupe
et même jour pouvaient donc échanger leur évènement d'un relevé à l'autre.

Sans conséquence tant que rien ne replanifiait tout seul. Mais une boucle de
réconciliation pousserait l'heure A, relirait, pousserait l'heure B, sur un
évènement Celcat bien réel — indéfiniment. C'est le risque numéro un du
passage en continu, et il se ferme ici, avant la boucle.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from cal_iut.celcat.comparaison import comparer, empreinte

SEMAINE = 2
SEMAINE_CELCAT = 5


@dataclass
class FauxPlacement:
    session_id: str
    course_code: str
    day: int
    slot: int
    room_label: str
    week: int = SEMAINE


def _ev(event_id: int, *, jour: int, heure: str, salle: str, module: str = "WR101 Prog. Web") -> dict:
    return {
        "event_id": event_id,
        "groupe": "BUT MMI S1 TD AB",
        "jour": jour,
        "heure_debut": heure,
        "heure_fin": "",
        "salle": salle,
        "salles": [salle],
        "categorie": "[TD] 100%",
        "module": module,
        "semaine": SEMAINE_CELCAT,
    }


def _comparer(placements, evenements, journal=None):
    return comparer(
        placements=placements,
        evenements=evenements,
        semaine=SEMAINE,
        semaine_celcat=SEMAINE_CELCAT,
        groupes_celcat={p.session_id: "BUT MMI S1 TD AB" for p in placements},
        salles_celcat={},
        codes_celcat={"WR101"},
        types_seance={p.session_id: "TD" for p in placements},
        journal=journal,
    )


# Deux séances de MÊME matière, MÊME groupe, MÊME jour : c'est exactement la
# configuration où `_correspond` répond oui aux deux, et où le premier trouvé
# décidait donc tout.
PLACEMENTS = [
    FauxPlacement("WR101-S1-TD-1", "WR101", day=1, slot=0, room_label="H.018"),
    FauxPlacement("WR101-S1-TD-2", "WR101", day=1, slot=3, room_label="H.018"),
]
EVENEMENTS = [
    _ev(1000, jour=1, heure="08:00", salle="H.018"),
    _ev(2000, jour=1, heure="13:50", salle="H.018"),
]


def test_l_ordre_du_releve_ne_change_pas_le_verdict() -> None:
    """Le test de propriété : mêmes données, ordre mélangé, même résultat."""
    reference = _comparer(PLACEMENTS, EVENEMENTS)
    signature = empreinte(reference)

    melange = list(EVENEMENTS)
    alea = random.Random(20260916)
    for _ in range(40):
        alea.shuffle(melange)
        obtenu = _comparer(PLACEMENTS, list(melange))
        assert empreinte(obtenu) == signature, (
            f"l'ordre du relevé a change le verdict : {obtenu}"
        )


def test_chaque_seance_prend_l_evenement_qui_lui_correspond_le_mieux() -> None:
    """Le premier trouvé prenait l'évènement de 8h pour la séance de 13h50 :
    deux écarts d'heure là où il n'y en a aucun, et deux modifications
    poussées dans Celcat pour rien."""
    lignes = _comparer(PLACEMENTS, EVENEMENTS)
    par_seance = {l["session_id"]: l for l in lignes if l["session_id"]}

    assert par_seance["WR101-S1-TD-1"]["celcat"]["event_id"] == 1000
    assert par_seance["WR101-S1-TD-2"]["celcat"]["event_id"] == 2000
    assert all(l["statut"] == "identique" for l in par_seance.values()), lignes


def test_le_journal_fixe_l_identite_meme_quand_l_heure_a_bouge() -> None:
    """Ce que NOUS avons écrit, et où : c'est une identité, pas une
    ressemblance. Sans le journal, une séance déplacée peut se voir attribuer
    l'évènement de sa voisine — et la correction partirait sur le mauvais
    `event_id`."""
    # Les deux séances ont été déplacées, et se retrouvent chacune à l'heure
    # que l'autre occupait dans Celcat.
    deplaces = [
        FauxPlacement("WR101-S1-TD-1", "WR101", day=1, slot=3, room_label="H.018"),
        FauxPlacement("WR101-S1-TD-2", "WR101", day=1, slot=0, room_label="H.018"),
    ]
    journal = {"WR101-S1-TD-1": 1000, "WR101-S1-TD-2": 2000}

    lignes = _comparer(deplaces, EVENEMENTS, journal=journal)
    par_seance = {l["session_id"]: l for l in lignes if l["session_id"]}

    assert par_seance["WR101-S1-TD-1"]["celcat"]["event_id"] == 1000, (
        "le journal doit primer sur la ressemblance d'horaire"
    )
    assert par_seance["WR101-S1-TD-2"]["celcat"]["event_id"] == 2000
    assert par_seance["WR101-S1-TD-1"]["ecarts"] == ["heure"]


def test_un_journal_qui_designe_un_autre_cours_est_ignore() -> None:
    """Celcat recycle ses identifiants. Un journal périmé ne doit pas faire
    corriger la mauvaise séance — le module reste vérifié."""
    journal = {"WR101-S1-TD-1": 3000}
    autre_cours = _ev(3000, jour=1, heure="08:00", salle="H.018", module="WR999 Autre chose")

    lignes = _comparer(PLACEMENTS, [*EVENEMENTS, autre_cours], journal=journal)
    par_seance = {l["session_id"]: l for l in lignes if l["session_id"]}

    assert par_seance["WR101-S1-TD-1"]["celcat"]["event_id"] == 1000


def test_l_empreinte_ignore_ce_qui_concorde() -> None:
    """Deux relevés également conformes doivent rendre la même empreinte,
    sinon la boucle ré-enfilerait une semaine où rien n'a bougé."""
    conforme = _comparer(PLACEMENTS, EVENEMENTS)
    assert all(l["statut"] in ("identique", "hors_celcat") for l in conforme), conforme
    assert empreinte(conforme) == empreinte([])


def test_l_empreinte_change_quand_une_divergence_apparait() -> None:
    decale = [_ev(1000, jour=1, heure="09:30", salle="H.018"), EVENEMENTS[1]]
    assert empreinte(_comparer(PLACEMENTS, decale)) != empreinte(_comparer(PLACEMENTS, EVENEMENTS))


def test_l_empreinte_distingue_deux_event_id_pour_le_meme_ecart() -> None:
    """La signature du battement : la même divergence qui revient en changeant
    d'évènement. C'est ce que la boucle devra refuser de repousser."""
    a = _comparer(PLACEMENTS, [_ev(1000, jour=1, heure="09:30", salle="H.018")])
    b = _comparer(PLACEMENTS, [_ev(2000, jour=1, heure="09:30", salle="H.018")])
    assert empreinte(a) != empreinte(b)
