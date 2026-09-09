"""Le résumé d'un cycle doit se lire — les différés ne noient plus le reste.

Demande de Jules Crevoisier, 09/09/2026 : « est-ce que l'on peut, pour plus
de visibilité, enlever les runs qui sont pour les semaines pas posées, étant
donné que l'on s'en fiche ».

CE QU'IL LISAIT, toutes les 90 secondes, identique à la virgule près :

    99 job(s) — 0 réussi(s) — 14 en échec — 7× TP exige event_cat_id pour
    [TP] — reçu vide (…) | 7× TD exige (…) — 1 ignoré(s) — 1× séance
    inconnue de la maquette (…) — 84 en attente d'une semaine posée —
    11× semaine 8 pas encore posée dans Celcat (12 cours sur 235 prévus) —
    en attente (ex. WRA502D-S5-TD-1-but3-dev-fc-td-ef) | 11× semaine 6 pas
    encore posée dans Celcat (0 cours sur 173 prévus) — en attente (ex.
    WR502D-S5-TD-3-but3-dev-fi-td-ab) | et 13 autre(s) motif(s)

La moitié de la ligne décrivait quatre-vingts jobs qui attendent que
l'équipe pédagogique ouvre des semaines : une information qui ne change pas
d'un cycle à l'autre et n'appelle AUCUNE action de notre côté. Elle noyait
les quatorze échecs, qui sont la seule chose à lire.

CE QUI RESTE, ET POURQUOI. Le compte, parce qu'un différé silencieux
ressemble à un job perdu. Et les NUMÉROS de semaine, parce qu'eux se lisent
d'un coup d'œil et disent exactement ce qu'il reste à ouvrir dans Celcat.
Ce qui part, c'est la répartition par motif et les exemples de séances.
"""

from __future__ import annotations

from cal_iut.celcat.nuit import BilanDrainage
from cal_iut.celcat.semaines_posees import motif_attente


def _bilan_realiste() -> BilanDrainage:
    """Le cycle du 09/09/2026 à 13h51, en plus petit."""
    bilan = BilanDrainage(en_attente=99, reussis=0)
    bilan.echecs = [
        (f"WR303D-S3-TP-{i}", "TP exige event_cat_id pour [TP] — reçu vide")
        for i in range(7)
    ]
    bilan.ignores = [("WS310D-S3-TD-CUSTOM1", "séance inconnue de la maquette")]
    for indice, combien in ((6, 11), (8, 11), (9, 5)):
        bilan.semaines_differees.add(indice)
        bilan.differes += [
            (f"s-{indice}-{i}", motif_attente(indice, celcat=0, attendu=173))
            for i in range(combien)
        ]
    return bilan


def test_les_differes_tiennent_en_une_clause() -> None:
    resume = _bilan_realiste().resume()

    assert "27 en attente d'une semaine non posée (semaines 6, 8, 9)" in resume, resume


def test_le_resume_ne_repete_plus_le_detail_des_differes() -> None:
    """LE point : ni les exemples de séances, ni « X cours sur Y prévus »."""
    resume = _bilan_realiste().resume()

    assert "cours sur 173 prévus" not in resume, resume
    assert "ex. s-6-0" not in resume, resume
    assert "autre(s) motif(s)" not in resume, resume


def test_les_echecs_restent_detailles() -> None:
    """Ce qui appelle une action garde sa répartition par motif : c'est
    exactement ce que les différés masquaient."""
    resume = _bilan_realiste().resume()

    assert "7 en échec" in resume
    assert "event_cat_id" in resume
    assert "ex. WR303D-S3-TP-0" in resume


def test_le_compte_des_differes_ne_disparait_pas() -> None:
    """Les retirer complètement ferait ressembler un job en attente à un job
    perdu — et 99 jobs en file avec 72 décrits ne s'expliquerait pas."""
    resume = _bilan_realiste().resume()

    assert "27 en attente" in resume


def test_sans_semaine_identifiee_la_clause_reste_correcte() -> None:
    """Non-régression : un différé dont l'indice n'a pas pu être noté ne
    doit pas produire « (semaines ) »."""
    bilan = BilanDrainage(en_attente=1)
    bilan.differes = [("s-x", "semaine inconnue")]

    resume = bilan.resume()

    assert "1 en attente d'une semaine non posée" in resume
    assert "semaines )" not in resume
    assert "()" not in resume


def test_un_cycle_sans_differe_n_en_parle_pas() -> None:
    bilan = BilanDrainage(en_attente=1, reussis=1)

    assert "en attente d'une semaine" not in bilan.resume()
