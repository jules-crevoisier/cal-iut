"""Celcat et cal-iut ne disent PAS la même heure pour le même cours.

Constaté le 08/09/2026 en corrigeant le CM de Régis Huez : Celcat stocke
`1899-12-31T13:50:39.000Z` pour notre créneau de 14h00. Le décalage est de
9 minutes 21 secondes, exactement — c'est le fuseau HISTORIQUE de Paris,
celui d'avant l'adoption de GMT en 1911 (`UTC+00:09:21`). Celcat pose ses
horaires sur la date pivot du 31/12/1899 (convention Delphi), et la
sérialisation en UTC applique ce décalage d'époque.

Vérifié à la seconde près :

    15h30 le 31/12/1899 à Paris  ->  15:20:39 UTC
    14h00 le 31/12/1899 à Paris  ->  13:50:39 UTC

Ce n'est donc pas une erreur de données : les horaires Celcat sont JUSTES,
simplement exprimés autrement. Mais `lecture._heure` en extrait « 13:50 »
tel quel, et `ops.correspond_live` compare cette chaîne à notre « 14:00 »
avec `!=`. La correspondance sur l'heure échoue donc TOUJOURS, pour toutes
les séances.

Conséquence silencieuse : un évènement Celcat qui correspond parfaitement à
une séance cal-iut n'est jamais reconnu comme tel. `_scanner_extras` le
signale alors comme « extra » — un cours en trop dans Celcat, à trancher à
la main — alors qu'il est exactement à sa place.

Une tolérance vaut mieux qu'une conversion de fuseau : deux créneaux
consécutifs sont espacés de 90 minutes, donc un quart d'heure d'écart ne
peut désigner que le même créneau, et cela reste vrai si l'établissement
change ses horaires de dix minutes.
"""

from __future__ import annotations

import pytest

from cal_iut.celcat.lecture import meme_creneau


@pytest.mark.parametrize(
    ("celcat", "caliut"),
    [
        ("13:50", "14:00"),  # le CM de Huez avant correction
        ("15:20", "15:30"),  # après
        ("09:20", "09:30"),  # le Soutien WR120 de Kyllian
        ("10:50", "11:00"),
        ("16:50", "17:00"),
        ("07:50", "08:00"),
    ],
)
def test_le_decalage_de_9_minutes_designe_bien_le_meme_creneau(celcat: str, caliut: str) -> None:
    assert meme_creneau(celcat, caliut) is True


def test_deux_creneaux_differents_ne_se_confondent_pas() -> None:
    """La tolérance ne doit pas devenir un « à peu près » : 90 minutes
    séparent deux créneaux, confondre reviendrait à valider une séance qui
    n'est pas à la bonne heure."""
    assert meme_creneau("09:20", "11:00") is False
    assert meme_creneau("13:50", "15:30") is False
    assert meme_creneau("08:00", "09:30") is False


def test_des_heures_identiques_correspondent() -> None:
    """Une base sans le décalage (ou déjà normalisée) doit continuer de
    marcher — on ne remplace pas un défaut par son symétrique."""
    assert meme_creneau("14:00", "14:00") is True


def test_une_heure_absente_ne_prétend_pas_correspondre() -> None:
    """Un évènement fantôme (sans horaire) ne doit pas être rapproché de
    n'importe quelle séance."""
    assert meme_creneau("", "14:00") is False
    assert meme_creneau("14:00", "") is False
    assert meme_creneau("", "") is False


def test_une_heure_illisible_ne_plante_pas() -> None:
    """Les données viennent d'un système tiers : une valeur inattendue doit
    rendre « ne correspond pas », jamais lever."""
    assert meme_creneau("n/a", "14:00") is False
    assert meme_creneau("14:00", "midi") is False


def test_correspond_live_reconnait_enfin_une_seance_a_sa_place() -> None:
    """Le vrai effet recherché : un évènement Celcat bien placé cesse d'être
    signalé comme un « extra » à trancher à la main."""
    from types import SimpleNamespace

    from cal_iut.celcat.lecture import EvenementCelcat
    from cal_iut.celcat.ops import correspond_live

    session = SimpleNamespace(course_code="WR116", group_ids=[], semestre="S1")
    placement = SimpleNamespace(day=1, slot=4)  # mardi, 15:30
    ev = EvenementCelcat(
        event_id=1931709,
        jour=2,  # `lecture` rend day_of_week + 1
        heure_debut="15:20",  # ce que Celcat stocke pour 15:30
        heure_fin="16:50",
        weeks="NNNY" + "N" * 50,
        categorie="[CM]",
        module_nom="WR116 Traitement Info",
        module_code="TSBZ1M16",
        salle="Amphi 3 MMI",
        enseignant="HUEZ Regis",
        group_id=1661971,
        groupe_nom="",
        protected="N",
        global_event="N",
        brut={},
    )

    assert correspond_live(session, placement, ev) is True
