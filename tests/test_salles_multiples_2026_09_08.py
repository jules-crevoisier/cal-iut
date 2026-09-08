"""Un cours à DEUX salles dans Celcat doit se voir.

Signalement de Kyllian Bresson, 08/09/2026 à 18h43 :

    « Pour info, Thomas Castellengo est sur deux salles, je pense que c'est
      cal-iut qui n'a pas supprimé une des deux salles, enfin le clic-clic. »
    « Sur Celcat il y a plusieurs façons de changer de salle : soit cliquer
      sur le rond rouge avec la barre blanche à l'intérieur, soit, quand on
      glisse une nouvelle salle dans l'onglet salle, maintenir shift et ça
      remplace la salle existante par la nouvelle. »

L'ANGLE MORT. `lecture._premier_nom` ne garde que la TÊTE de `rooms` :

    salle = _premier_nom(brut.get("rooms"), "name", "unique_name")

Un évènement à deux salles nous paraît donc en avoir une — et c'est la
PREMIÈRE, pas forcément celle qui compte. La comparaison ne pouvait pas voir
le problème, et l'écran affirmait « identique » sur un cours qui occupe deux
salles à la fois.

CE N'EST PROBABLEMENT PAS cal-iut. Nos compteurs de production disaient
`modified: 0` au moment du signalement : l'application n'avait jamais réussi
à modifier la salle d'un évènement existant, elle ne pouvait donc pas avoir
ajouté la seconde. Et la suite l'a confirmé — une fois les modifications
débloquées, les écarts de salle de la semaine 1 sont passés de 16 à 5 : si
Celcat AJOUTAIT au lieu de remplacer, ces corrections n'auraient rien changé.
`save` remplace bien la liste des salles, ce qui veut dire que notre
correction RÉPARE un doublon de salle au lieu de l'aggraver.

Reste donc à le DÉTECTER, pour pouvoir le corriger : c'est l'objet de ce
fichier.
"""

from __future__ import annotations

from cal_iut.celcat.comparaison import comparer
from cal_iut.celcat.lecture import evenement_depuis_rpc

SEMAINE, INDICE = 1, 3
GROUPE = "BUT MMI S1 TD AB"


# --------------------------------------------------------------------------
# 1. La lecture doit rapporter TOUTES les salles.
# --------------------------------------------------------------------------


def test_un_evenement_a_deux_salles_les_rapporte_toutes() -> None:
    ev = evenement_depuis_rpc(
        {
            "event_id": 1, "day_of_week": 0, "start_time": "08:00", "end_time": "09:30",
            "evCatName": "[TD]", "weeks": "Y" + "N" * 53,
            "rooms": [{"id": 1, "name": "H.101"}, {"id": 2, "name": "H.007"}],
            "modules": [{"name": "WR101"}],
        },
        group_id=1, groupe_nom=GROUPE,
    )

    assert ev.salles == ["H.101", "H.007"]
    # `salle` reste la première : tout le code existant s'en sert, et le
    # changer d'un coup ferait diverger les rapprochements déjà éprouvés.
    assert ev.salle == "H.101"


def test_un_evenement_a_une_salle_reste_simple() -> None:
    ev = evenement_depuis_rpc(
        {
            "event_id": 2, "day_of_week": 0, "start_time": "08:00",
            "evCatName": "[TD]", "rooms": [{"id": 1, "name": "H.101"}],
            "modules": [{"name": "WR101"}],
        },
        group_id=1, groupe_nom=GROUPE,
    )

    assert ev.salles == ["H.101"]


def test_un_evenement_sans_salle_ne_casse_pas() -> None:
    ev = evenement_depuis_rpc({"event_id": 3}, group_id=1, groupe_nom=GROUPE)

    assert ev.salles == []


# --------------------------------------------------------------------------
# 2. La comparaison doit le signaler.
# --------------------------------------------------------------------------


class _Placement:
    def __init__(self) -> None:
        self.session_id = "WR101-S1-TD-1-but1-td-ab"
        self.course_code = "WR101"
        self.week = SEMAINE
        self.day = 0
        self.slot = 0
        self.room_id = "h101"
        self.room_label = "H.101"
        self.group_ids = ["but1-td-ab"]


def _comparer(evenement: dict):
    placement = _Placement()
    return comparer(
        placements=[placement],
        evenements=[evenement],
        semaine=SEMAINE,
        semaine_celcat=INDICE,
        groupes_celcat={placement.session_id: GROUPE},
        salles_celcat={"h101": "H.101"},
        types_seance={placement.session_id: "TD"},
    )


def _ev(**extra) -> dict:
    return {
        "event_id": 1931666, "groupe": GROUPE, "jour": 0,
        "heure_debut": "08:00", "heure_fin": "09:30", "salle": "H.101",
        "categorie": "[TD]", "module": "WR101", "semaine": INDICE, **extra,
    }


def test_deux_salles_font_un_ecart() -> None:
    """LE cas de Kyllian. Sans ça, l'écran affirmait « identique » sur un
    cours qui occupe deux salles à la fois."""
    lignes = _comparer(_ev(salles=["H.101", "H.007"]))

    assert lignes[0]["statut"] == "ecart", lignes[0]
    assert "salles multiples" in lignes[0]["ecarts"], lignes[0]["ecarts"]


def test_une_seule_salle_reste_identique() -> None:
    """Non-régression : la salle est correcte, il n'y a rien à signaler."""
    lignes = _comparer(_ev(salles=["H.101"]))

    assert lignes[0]["statut"] == "identique", lignes[0]


def test_un_releve_sans_le_champ_salles_ne_signale_rien() -> None:
    """Les instantanés déjà déposés n'ont pas ce champ. Ne pas SAVOIR n'est
    pas la même chose que constater une faute : on se tait plutôt que de
    remplir l'écran d'écarts inventés le temps qu'un nouveau relevé arrive."""
    lignes = _comparer(_ev())

    assert lignes[0]["statut"] == "identique", lignes[0]


def test_l_ecart_de_salles_multiples_s_ajoute_aux_autres() -> None:
    """Un cours peut être à la fois sur deux salles ET mal étiqueté : n'en
    signaler qu'un ferait corriger à moitié."""
    lignes = _comparer(_ev(salles=["H.101", "H.007"], categorie="[CM]"))

    assert set(lignes[0]["ecarts"]) >= {"salles multiples", "catégorie"}


def test_la_salle_attendue_reste_comparee_normalement() -> None:
    """Deux salles dont AUCUNE n'est la bonne : les deux écarts doivent
    sortir, sans quoi corriger la première laisserait la seconde."""
    lignes = _comparer(_ev(salle="H.007", salles=["H.007", "H.008"]))

    assert set(lignes[0]["ecarts"]) >= {"salles multiples", "salle"}
