"""Les fenêtres SAE dans le flux .ics — une plage par période réelle.

Retour utilisateur 09/09/2026 : « on a un problème d'ics avec les SAE,
c'est complètement bugué ».

CE QUI SE PASSAIT. `_ics_all_day_sae_items` posait UN évènement journée
entière par fenêtre, de `min(dates)` à `max(dates)`. Or les jours d'une SAE
ne sont pas contigus : ils sont répartis sur plusieurs semaines. Mesuré sur
les données de production, onze fenêtres sur vingt étaient déformées :

    WS501D   22 jours réels  ->  bloc de 89 jours (19/10 au 15/01)
    WSA501C   7 jours réels  ->  bloc de 65 jours
    WS301D   10 jours réels  ->  bloc de 30 jours

Dans un agenda, ça donne un bandeau « SAE » de près de trois mois posé sur
tout — vacances et semaines de cours normales comprises.

DEUX AUTRES DÉFAUTS, visibles dans les mêmes données :

  - `appliquer_corrections_sae` ajoute les dates corrigées dans une fenêtre
    SÉPARÉE, libellée « WSA501C (correction locale) » et SANS parcours. Le
    flux exposait donc ce libellé technique aux utilisateurs, affichait la
    SAE en double, et — le parcours étant absent — la diffusait à TOUS les
    parcours, y compris ceux que ça ne concerne pas.

Corrigé ICI, dans la construction du flux, et pas dans
`appliquer_corrections_sae` : cette fonction sert aussi au solveur, où
fusionner les fenêtres changerait la sanctuarisation des jours (une fenêtre
restreinte à certains groupes TD ne restreint pas de la même façon qu'une
fenêtre sans restriction). Le flux .ics n'a pas ce souci — il n'affiche
rien d'autre qu'un repère.
"""

from __future__ import annotations

from datetime import date

from cal_iut.api.ics_feed import fenetres_sae_pour_ics
from cal_iut.ingestion.planning_loader import SaeWindow


def _jours(*iso: str) -> list[date]:
    return [date.fromisoformat(d) for d in iso]


def test_des_jours_non_contigus_donnent_plusieurs_plages() -> None:
    """LE défaut. Deux semaines de SAE espacées ne sont pas deux mois de SAE."""
    fenetre = SaeWindow(
        label="WS501D", course_codes=["WS501D"], parcours="BUT3-DEV-FI",
        dates=_jours("2026-10-19", "2026-10-20", "2026-11-16", "2026-11-17"),
    )

    items = fenetres_sae_pour_ics([fenetre], "BUT3-DEV-FI")

    assert len(items) == 2, [(i.date_start, i.date_end) for i in items]
    assert (items[0].date_start, items[0].date_end) == ("2026-10-19", "2026-10-20")
    assert (items[1].date_start, items[1].date_end) == ("2026-11-16", "2026-11-17")


def test_une_plage_contigue_reste_un_seul_evenement() -> None:
    """Non-régression : une vraie semaine de projet reste un seul bandeau."""
    fenetre = SaeWindow(
        label="WS102", course_codes=["WS102"], parcours="BUT1",
        dates=_jours("2027-01-04", "2027-01-05", "2027-01-06", "2027-01-07", "2027-01-08"),
    )

    items = fenetres_sae_pour_ics([fenetre], "BUT1")

    assert len(items) == 1
    assert (items[0].date_start, items[0].date_end) == ("2027-01-04", "2027-01-08")


def test_un_week_end_ne_coupe_pas_une_semaine_de_projet() -> None:
    """Vendredi puis lundi, c'est la même SAE qui continue : la couper en
    deux bandeaux serait aussi faux que de tout fusionner. Le samedi et le
    dimanche ne sont pas des jours de cours."""
    fenetre = SaeWindow(
        label="WS104", course_codes=["WS104"], parcours="BUT1",
        dates=_jours("2026-12-11", "2026-12-14"),  # vendredi, puis lundi
    )

    items = fenetres_sae_pour_ics([fenetre], "BUT1")

    assert len(items) == 1, [(i.date_start, i.date_end) for i in items]
    assert (items[0].date_start, items[0].date_end) == ("2026-12-11", "2026-12-14")


def test_chaque_plage_a_son_identifiant_propre() -> None:
    """Deux plages de la même SAE sont deux évènements distincts dans un
    agenda : un UID partagé les ferait s'écraser l'un l'autre."""
    fenetre = SaeWindow(
        label="WS501D", course_codes=["WS501D"], parcours="BUT3-DEV-FI",
        dates=_jours("2026-10-19", "2026-11-16"),
    )

    items = fenetres_sae_pour_ics([fenetre], "BUT3-DEV-FI")

    assert len({i.key for i in items}) == 2, [i.key for i in items]


def test_une_correction_locale_ne_cree_pas_un_doublon() -> None:
    """`appliquer_corrections_sae` ajoute les dates corrigées dans une
    fenêtre à part. Pour l'agenda, c'est la MÊME SAE : deux bandeaux côte à
    côte n'apprendraient rien et donneraient l'impression d'une erreur."""
    fenetres = [
        SaeWindow(label="WSA501C", course_codes=["WSA501C"], parcours="BUT3-CREACOM-FC",
                  dates=_jours("2026-10-12", "2026-10-13")),
        SaeWindow(label="WSA501C (correction locale)", course_codes=["WSA501C"],
                  dates=_jours("2026-10-14")),
    ]

    items = fenetres_sae_pour_ics(fenetres, "BUT3-CREACOM-FC")

    assert len(items) == 1, [(i.title, i.date_start, i.date_end) for i in items]
    assert (items[0].date_start, items[0].date_end) == ("2026-10-12", "2026-10-14")


def test_le_libelle_technique_n_est_jamais_montre() -> None:
    """« (correction locale) » parle de NOTRE tuyauterie. Dans l'agenda d'un
    étudiant, ça ne veut rien dire."""
    fenetres = [
        SaeWindow(label="WSA501C", course_codes=["WSA501C"], parcours="BUT3-CREACOM-FC",
                  dates=_jours("2026-10-12")),
        SaeWindow(label="WSA501C (correction locale)", course_codes=["WSA501C"],
                  dates=_jours("2026-11-04")),
    ]

    items = fenetres_sae_pour_ics(fenetres, "BUT3-CREACOM-FC")

    assert all("correction locale" not in i.title for i in items), [i.title for i in items]


def test_une_correction_locale_herite_du_parcours() -> None:
    """Sans parcours, elle était diffusée à TOUS les flux. Or c'est la même
    SAE que la fenêtre d'origine, donc le même parcours."""
    fenetres = [
        SaeWindow(label="WSA501C", course_codes=["WSA501C"], parcours="BUT3-CREACOM-FC",
                  dates=_jours("2026-10-12")),
        SaeWindow(label="WSA501C (correction locale)", course_codes=["WSA501C"],
                  dates=_jours("2026-11-04")),
    ]

    assert fenetres_sae_pour_ics(fenetres, "BUT1") == []
    assert len(fenetres_sae_pour_ics(fenetres, "BUT3-CREACOM-FC")) == 2


def test_une_fenetre_sans_parcours_connu_reste_visible_partout() -> None:
    """Non-régression : une SAE dont aucune fenêtre ne déclare de parcours
    concerne tout le monde — se taire vaudrait moins bien que d'en montrer
    une de trop."""
    fenetre = SaeWindow(label="WS999", course_codes=["WS999"], dates=_jours("2026-10-12"))

    assert len(fenetres_sae_pour_ics([fenetre], "BUT1")) == 1


def test_une_fenetre_sans_date_ne_produit_rien() -> None:
    assert fenetres_sae_pour_ics([SaeWindow(label="WS1", course_codes=["WS1"])], "BUT1") == []


def test_les_groupes_restent_dans_le_titre() -> None:
    """WS502D date séparément chaque groupe TD : sans le groupe au titre, un
    étudiant ne sait pas si la semaine le concerne."""
    fenetre = SaeWindow(
        label="WS502D", course_codes=["WS502D"], parcours="BUT3-DEV-FI",
        group_labels=["AB"], dates=_jours("2027-01-12", "2027-01-13"),
    )

    items = fenetres_sae_pour_ics([fenetre], "BUT3-DEV-FI")

    assert "AB" in items[0].title


def test_le_parcours_se_retrouve_dans_les_seances_du_meme_code() -> None:
    """Une correction locale dont la fenêtre d'origine a disparu n'a plus de
    parcours. `WS310D` est pourtant du BUT2-DEV-FI de part en part — ses
    onze séances le disent — et il remontait dans le flux de TOUS les
    parcours."""
    fenetre = SaeWindow(
        label="WS310D (correction locale)", course_codes=["WS310D"],
        dates=_jours("2026-12-07", "2026-12-08"),
    )
    connus = {"WS310D": "BUT2-DEV-FI"}

    assert fenetres_sae_pour_ics([fenetre], "BUT1", connus) == []
    assert len(fenetres_sae_pour_ics([fenetre], "BUT2-DEV-FI", connus)) == 1


def test_la_fenetre_prime_sur_les_seances() -> None:
    """Le parcours DÉCLARÉ fait foi : les séances ne sont qu'un repli quand
    il manque."""
    fenetre = SaeWindow(
        label="WS501D", course_codes=["WS501D"], parcours="BUT3-DEV-FI",
        dates=_jours("2026-10-19"),
    )

    assert len(fenetres_sae_pour_ics([fenetre], "BUT3-DEV-FI", {"WS501D": "BUT1"})) == 1
    assert fenetres_sae_pour_ics([fenetre], "BUT1", {"WS501D": "BUT1"}) == []
