"""Une catégorie d'évènement fausse est un ÉCART, pas une concordance.

Signalement de David Annebicque, relayé par Jules le 08/09/2026 :

    « Attention, ce qui est dans Celcat est faux ! Les TD sont aléatoirement
      indiqués en TD ou en CM dans le type de cours (premier onglet), ça
      casse la synchro et ça posera souci sur OMEGA. »

puis, le même jour : « il faut vérifier ça, c'est souvent des catégories
d'évènement avec l'étiquette CM 100% alors que c'est un TD ou un TP ».

L'ANGLE MORT. `_ecarts` comparait l'heure, la salle et le jour — jamais la
catégorie. Un TD étiqueté `[CM]` dans Celcat était donc rendu « identique » :
notre écran affirmait que tout concordait, précisément sur les séances dont
David disait qu'elles étaient fausses.

MESURÉ SUR LA PRODUCTION LE 08/09/2026, semaines 1 à 3 : 263 concordances de
catégorie, et SIX divergences, toutes « TD chez nous, [CM] chez Celcat »,
toutes classées « identique » :

    WR101-S1-TD-1-but1-td-cd   event_id 1931727
    WR101-S1-TD-1-but1-td-ef   event_id 1931765
    WR106-S1-TD-1-but1-td-ab   event_id 1931666
    WR106-S1-TD-1-but1-td-cd   event_id 1931753
    WR106-S1-TD-1-but1-td-ef   event_id 1931756
    WR106-S1-TD-1-but1-td-gh   event_id 1931647

CE QUE ÇA DÉBLOQUE. Une ligne « écart » devient une MODIFICATION portant
l'`event_id` relevé, et `_ids_pour` résout `event_cat_id` depuis NOTRE type
de séance : la correction de la catégorie part donc par le chemin déjà
existant, sans rien de nouveau côté écriture.

POURQUOI LE TYPE VIENT DE LA SÉANCE ET NON DU PLACEMENT. `PlacedSessionWithRoom`
ne porte pas le type — seule la `SessionToPlace` l'a. Le déduire du
`session_id` (« …-TD-1-… ») marcherait aujourd'hui et casserait au premier
identifiant nommé autrement : l'appelant, qui a `sessions_by_id`, passe donc
la table explicitement, comme il le fait déjà pour les groupes.
"""

from __future__ import annotations

from cal_iut.celcat.comparaison import comparer

SEMAINE, INDICE = 1, 3
GROUPE = "BUT MMI S1 TD AB"


class _Placement:
    def __init__(self, session_id: str, *, jour: int = 0, slot: int = 0) -> None:
        self.session_id = session_id
        self.course_code = session_id.split("-")[0]
        self.week = SEMAINE
        self.day = jour
        self.slot = slot
        self.room_id = "h101"
        self.room_label = "H.101"
        self.group_ids = ["but1-td-ab"]


def _ev(categorie: str, *, event_id: int = 1931666, module: str = "WR106") -> dict:
    return {
        "event_id": event_id,
        "groupe": GROUPE,
        "jour": 0,
        "heure_debut": "08:00",
        "heure_fin": "09:30",
        "salle": "H.101",
        "categorie": categorie,
        "module": module,
        "semaine": INDICE,
    }


def _comparer(placement, evenement, types):
    return comparer(
        placements=[placement],
        evenements=[evenement],
        semaine=SEMAINE,
        semaine_celcat=INDICE,
        groupes_celcat={placement.session_id: GROUPE},
        salles_celcat={"h101": "H.101"},
        types_seance=types,
    )


def test_un_td_etiquete_cm_est_un_ecart() -> None:
    """LE cas de David. Six séances de production étaient dans cet état,
    toutes rendues « identique »."""
    placement = _Placement("WR106-S1-TD-1-but1-td-ab")

    lignes = _comparer(placement, _ev("[CM]"), {"WR106-S1-TD-1-but1-td-ab": "TD"})

    assert lignes[0]["statut"] == "ecart", lignes[0]
    assert "catégorie" in lignes[0]["ecarts"], (
        f"la catégorie fausse doit être nommée, reçu {lignes[0]['ecarts']}"
    )


def test_un_td_etiquete_td_reste_identique() -> None:
    """Non-régression : 263 séances concordaient déjà. Les faire ressortir en
    écart noierait les six vraies fautes."""
    placement = _Placement("WR106-S1-TD-1-but1-td-ab")

    lignes = _comparer(placement, _ev("[TD]"), {"WR106-S1-TD-1-but1-td-ab": "TD"})

    assert lignes[0]["statut"] == "identique", lignes[0]


def test_un_cm_etiquete_tp_est_un_ecart() -> None:
    """L'autre sens, signalé le même jour : « CM WR118 de Philippe Villain
    est encore en catégorie [TP] alors qu'il devrait être en [CM] »."""
    placement = _Placement("WR118-S1-CM-1")

    lignes = _comparer(
        placement, _ev("[TP]", module="WR118"), {"WR118-S1-CM-1": "CM"}
    )

    assert lignes[0]["statut"] == "ecart"
    assert "catégorie" in lignes[0]["ecarts"]


def test_les_pourcentages_et_variantes_ne_comptent_pas() -> None:
    """Celcat écrit parfois « [CM] 100% », et il existe des variantes
    bénévole/capacité. Seule l'étiquette entre crochets fait foi — sinon on
    signalerait comme fausses des catégories parfaitement correctes."""
    placement = _Placement("WR106-S1-TD-1-but1-td-ab")

    lignes = _comparer(placement, _ev("[TD] 100%"), {"WR106-S1-TD-1-but1-td-ab": "TD"})

    assert lignes[0]["statut"] == "identique", lignes[0]


def test_sans_type_connu_aucun_ecart_de_categorie() -> None:
    """Ne pas SAVOIR n'est pas la même chose que constater une faute : sans
    type de séance, on se tait plutôt que d'inventer un écart."""
    placement = _Placement("WR106-S1-TD-1-but1-td-ab")

    lignes = _comparer(placement, _ev("[CM]"), {})

    assert lignes[0]["statut"] == "identique", lignes[0]


def test_une_categorie_celcat_vide_ne_cree_pas_d_ecart() -> None:
    """Un évènement administratif sans crochets n'a pas de type de cours à
    comparer."""
    placement = _Placement("WR106-S1-TD-1-but1-td-ab")

    lignes = _comparer(placement, _ev("Conférence"), {"WR106-S1-TD-1-but1-td-ab": "TD"})

    assert "catégorie" not in lignes[0]["ecarts"], lignes[0]


def test_l_ecart_de_type_s_ajoute_aux_autres() -> None:
    """Une séance peut être à la fois au mauvais créneau ET mal étiquetée :
    n'en signaler qu'un ferait corriger à moitié."""
    placement = _Placement("WR106-S1-TD-1-but1-td-ab", slot=2)

    lignes = _comparer(placement, _ev("[CM]"), {"WR106-S1-TD-1-but1-td-ab": "TD"})

    assert set(lignes[0]["ecarts"]) >= {"catégorie", "heure"}, lignes[0]["ecarts"]
