"""L'indice de semaine Celcat doit survivre au 1er janvier.

Trouvé le 08/09/2026 en cherchant pourquoi des écritures échouaient sur
« masque semaines 0×Y — une seule est exigée ».

`indice_depuis_lundi` calculait `numéro de semaine ISO − 34`. Or au passage
à l'année, la numérotation ISO repart à 1 :

    lundi 2026-12-14  ->  ISO 51  ->  indice  17   correct
    lundi 2027-01-04  ->  ISO  1  ->  indice -33   négatif
    lundi 2027-03-01  ->  ISO  9  ->  indice -25   négatif

`masquer_semaine` refuse un indice négatif, `_masque_pour` encaisse
l'exception et retombe sur un masque vide, et `verifier_avant_envoi` refuse
alors l'écriture. AUCUNE séance de janvier à juin 2027 ne pouvait donc être
écrite dans Celcat — c'est-à-dire toute la seconde moitié de l'année
universitaire, silencieusement.

Le correctif compte les semaines ÉCOULÉES depuis le lundi de référence
plutôt que de soustraire deux numéros ISO. Une différence de dates ne
connaît pas le 1er janvier.
"""

from __future__ import annotations

from datetime import date

import pytest

from cal_iut.celcat.lecture import indice_depuis_lundi

PREMIERE = 34  # `nuit.PREMIERE_SEMAINE_CELCAT`


@pytest.mark.parametrize(
    ("lundi", "attendu"),
    [
        ("2026-08-17", 0),  # la semaine de référence elle-même
        ("2026-08-31", 2),
        ("2026-09-07", 3),  # semaine 1 du planning
        ("2026-10-05", 7),
        ("2026-12-14", 17),
    ],
)
def test_avant_le_1er_janvier_le_calcul_ne_change_pas(lundi: str, attendu: int) -> None:
    """Non-régression : tout ce qui marchait doit continuer à l'identique —
    ces indices sont écrits dans des masques déjà envoyés à Celcat."""
    assert indice_depuis_lundi(date.fromisoformat(lundi), premiere_semaine_celcat=PREMIERE) == attendu


@pytest.mark.parametrize(
    ("lundi", "attendu"),
    [
        ("2027-01-04", 20),
        ("2027-02-01", 24),
        ("2027-03-01", 28),
        ("2027-06-28", 45),
    ],
)
def test_apres_le_1er_janvier_l_indice_continue_de_croitre(lundi: str, attendu: int) -> None:
    """Le second semestre a des indices qui PROLONGENT le premier, jamais
    des négatifs."""
    assert indice_depuis_lundi(date.fromisoformat(lundi), premiere_semaine_celcat=PREMIERE) == attendu


def test_aucun_indice_negatif_sur_toute_l_annee_universitaire() -> None:
    """Le test qui aurait attrapé le défaut : un indice négatif rend le
    masque vide, donc l'écriture impossible — et rien ne le disait."""
    jour = date(2026, 8, 31)
    while jour < date(2027, 7, 1):
        indice = indice_depuis_lundi(jour, premiere_semaine_celcat=PREMIERE)
        assert indice >= 0, f"{jour} rend un indice négatif ({indice})"
        assert indice < 54, f"{jour} sort du masque de 54 caractères ({indice})"
        jour = date.fromordinal(jour.toordinal() + 7)


def test_les_semaines_consecutives_se_suivent() -> None:
    """Deux lundis consécutifs doivent donner deux indices consécutifs :
    un saut placerait une séance sur la mauvaise semaine dans Celcat, ce qui
    est pire qu'un refus."""
    precedent = indice_depuis_lundi(date(2026, 12, 21), premiere_semaine_celcat=PREMIERE)
    for jour in (date(2026, 12, 28), date(2027, 1, 4), date(2027, 1, 11)):
        actuel = indice_depuis_lundi(jour, premiere_semaine_celcat=PREMIERE)
        assert actuel == precedent + 1, f"saut entre {jour} et la semaine précédente"
        precedent = actuel


def test_un_masque_reste_constructible_toute_l_annee() -> None:
    """L'effet recherché : `masquer_semaine` ne doit plus lever, donc
    `_masque_pour` ne doit plus retomber sur un masque vide."""
    from cal_iut.celcat.rpc import masquer_semaine

    for lundi in (date(2026, 9, 7), date(2027, 1, 4), date(2027, 3, 1), date(2027, 6, 28)):
        indice = indice_depuis_lundi(lundi, premiere_semaine_celcat=PREMIERE)
        assert masquer_semaine(longueur=54, indice=indice).count("Y") == 1
