"""Les faux positifs du premier relevé réel, un par un.

Sortie de production du 08/09/2026, semaine 1 : 14 écarts, 55 « absentes de
Celcat », 51 « en trop ». Confronté aux données, l'essentiel n'était pas
réel — et une comparaison qui crie au loup ne sera plus lue au bout de deux
fois.

TROIS CAUSES, trois corrections ici.

1. LA MÊME SALLE SOUS DEUX NOMS. `data/config/celcat.yaml` dit
   `h018: "Amphi 3 MMI"` : cal-iut affiche « H.018 (Amphi MMI) », Celcat
   « Amphi 3 MMI ». Comparer les libellés signalait un écart de salle sur
   TOUS les CM en amphi — précisément les séances les plus visibles. La
   table de correspondance existe déjà et sert à l'écriture ; s'en servir
   aussi pour comparer, c'est garantir que les deux sens voient le même
   monde.

2. LE MÊME ÉVÈNEMENT COMPTÉ CINQ FOIS. Le relevé interroge 29 groupes ; un
   CM commun à la promo est rendu une fois PAR groupe. Sans dédoublonnage
   par `event_id`, il apparaissait cinq fois « en trop » — la liste devenait
   illisible, et le nombre affiché faux.

3. UN ÉVÈNEMENT SANS MATIÈRE. Les évènements officiels saisis à la main dans
   Celcat (rentrée, présentation des services) n'ont pas de module : le
   rapprochement par code matière ne peut pas les trouver, et ils
   ressortaient à la fois « absents » côté cal-iut et « en trop » côté
   Celcat. Les rapprocher sur le créneau et la salle vaut mieux que de les
   compter deux fois.
"""

from __future__ import annotations

from cal_iut.celcat.comparaison import comparer


def _ev(**kw):
    base = {
        "event_id": 1933252,
        "groupe": "BUT MMI S1 CM",
        "jour": 2,
        "heure_debut": "15:30",
        "heure_fin": "17:00",
        "salle": "Amphi 3 MMI",
        "categorie": "[CM]",
        "enseignant": "X",
        "module": "WR104 Cult. Numerique",
        "semaine": 3,
        "protected": "N",
    }
    base.update(kw)
    return base


def _placement(**kw):
    from types import SimpleNamespace

    base = {
        "session_id": "WR104-S1-CM-1",
        "course_code": "WR104",
        "week": 1,
        "day": 2,
        "slot": 4,
        "room_id": "h018",
        "room_label": "H.018 (Amphi MMI)",
        "group_ids": ["but1-promo"],
        "teacher_codes": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


SALLES = {"h018": "Amphi 3 MMI", "h101": "H.101"}


def test_h018_et_amphi_3_mmi_sont_la_meme_salle() -> None:
    """Le faux positif le plus visible : tous les CM en amphi étaient
    signalés en écart de salle."""
    lignes = comparer(
        placements=[_placement()],
        evenements=[_ev()],
        semaine=1,
        semaine_celcat=3,
        salles_celcat=SALLES,
    )

    assert lignes[0]["statut"] == "identique", lignes[0]["ecarts"]


def test_une_vraie_difference_de_salle_reste_signalee() -> None:
    """Corriger un faux positif ne doit pas rendre aveugle au vrai."""
    lignes = comparer(
        placements=[_placement()],
        evenements=[_ev(salle="H.101")],
        semaine=1,
        semaine_celcat=3,
        salles_celcat=SALLES,
    )

    assert lignes[0]["statut"] == "ecart"
    assert "salle" in lignes[0]["ecarts"]


def test_un_evenement_vu_dans_plusieurs_groupes_ne_compte_qu_une_fois() -> None:
    """Un CM de promo est rendu par chacun des groupes qui le suivent : cinq
    lignes « en trop » pour un seul évènement rendaient la liste illisible."""
    vu_cinq_fois = [
        _ev(groupe="BUT MMI S1 CM"),
        _ev(groupe="BUT MMI S1 TD AB"),
        _ev(groupe="BUT MMI S1 TD CD"),
        _ev(groupe="BUT MMI S1 TD EF"),
        _ev(groupe="BUT MMI S1 TD GH"),
    ]

    lignes = comparer(
        placements=[], evenements=vu_cinq_fois, semaine=1, semaine_celcat=3, salles_celcat=SALLES
    )

    assert len(lignes) == 1, f"un seul évènement, {len(lignes)} ligne(s)"
    assert lignes[0]["celcat"]["event_id"] == 1933252


def test_le_dedoublonnage_n_efface_pas_deux_evenements_distincts() -> None:
    lignes = comparer(
        placements=[],
        evenements=[_ev(event_id=1), _ev(event_id=2, heure_debut="08:00")],
        semaine=1,
        semaine_celcat=3,
        salles_celcat=SALLES,
    )

    assert len(lignes) == 2


def test_un_evenement_sans_matiere_se_rapproche_par_creneau_et_salle() -> None:
    """Les évènements officiels saisis à la main dans Celcat (rentrée,
    présentation des services) n'ont pas de module : ils comptaient double,
    « absents » d'un côté et « en trop » de l'autre."""
    lignes = comparer(
        placements=[
            _placement(
                session_id="PRESENTATION-DES-SERVICES-S1-CM-CUSTOM1-but1-promo",
                course_code="PRESENTATION-DES-SERVICES",
                day=1, slot=5, room_id="a018", room_label="A.018",
            )
        ],
        evenements=[_ev(event_id=1951047, module="", jour=1, heure_debut="17:00", salle="A.018")],
        semaine=1,
        semaine_celcat=3,
        salles_celcat={"a018": "A.018"},
    )

    assert len(lignes) == 1, "une seule ligne, pas une absence ET un en-trop"
    assert lignes[0]["statut"] == "identique"
