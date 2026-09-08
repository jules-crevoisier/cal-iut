"""Quelles semaines Celcat a-t-il déjà posées ? — pur, sans réseau.

Consigne utilisateur 08/09/2026, devant une file de 491 jobs dont 409
créations : « il faut faire les modifications uniquement sur les semaines
posées », « les semaines pas posées dans Celcat il faut attendre ».

L'équipe pédagogique saisit Celcat semaine par semaine. Le relevé du jour
le montre sans ambiguïté :

    semaines 3, 4, 5    ~300 cours chacune, 23 groupes   posées
    semaine  12          83 cours, 6 groupes             saisie en cours
    semaines 7 à 21      9 à 21 cours                    à peine ouvertes
    8 autres semaines    0 cours, 29 « Jour férié »      rien du tout

Y déverser nos créations mélangerait notre planning au travail en cours de
l'équipe, et il faudrait l'en démêler à la main. Attendre ne coûte rien :
la file est persistante, un job différé repart au cycle suivant.

LE SEUIL NE PEUT PAS ÊTRE UN NOMBRE ABSOLU. « Au moins cinquante cours »
serait vrai pour MMI aujourd'hui et faux dès qu'une promotion change de
taille, sans que rien ne le signale. La référence est donc ce que cal-iut
PRÉVOIT sur cette semaine : Celcat doit en couvrir au moins la moitié. Le
seuil se recalibre alors tout seul, et la règle reste juste.

CE MODULE NE LIT QUE DES DICTIONNAIRES — l'instantané déposé par le sidecar
et un décompte. Aucun VPN, aucun navigateur : il est donc testable, ce qui
n'est pas un détail pour une décision qui gouverne ce qui part en
production.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

# DEUX conditions, chacune bouchant l'angle mort de l'autre.
#
# La moitié dans les deux cas, parce que l'écart observé entre une semaine
# posée et une semaine en cours de saisie est franc — 356, 323, 288 d'un
# côté, 83 puis 21, 18, 12, 11 de l'autre. Un seuil placé au milieu d'un
# fossé ne tranche jamais de justesse.
#
# 1. Par rapport à la MEILLEURE semaine du relevé : c'est la définition de
#    « largement remplie ». Sans elle, la semaine d'indice 9 passerait —
#    Celcat n'y tient que 21 cours sur ~350, mais cal-iut n'y en prévoit que
#    28, si bien qu'une semaine quasi vide aurait l'air couverte.
COUVERTURE_MINIMALE_RELEVE = 0.5
# 2. Par rapport à ce que cal-iut prévoit : garde-fou pour l'année où le
#    relevé entier serait maigre. La meilleure semaine servant de référence,
#    elle passe toujours son propre test — sans ce second critère, un Celcat
#    à peine commencé s'ouvrirait tout seul.
COUVERTURE_MINIMALE = 0.5


def _est_cours(evenement: Mapping[str, Any]) -> bool:
    """Un vrai CM/TD/TP, jamais une réservation administrative.

    Huit semaines du relevé ne contiennent QUE des « Jour férié », un par
    groupe : vingt-neuf évènements, qui ont tout l'air d'un planning sans en
    être un. Les compter poserait ces semaines comme ouvertes alors qu'elles
    sont vides — précisément l'erreur à éviter.

    Toutes les catégories de cours sont entre crochets (relevé des 38
    catégories Celcat, 04/09/2026) ; aucune catégorie administrative ne
    l'est. Même critère que `lecture.py::est_cours`, appliqué ici à la forme
    aplatie que le sidecar dépose.
    """
    return str(evenement.get("categorie") or "").strip().startswith("[")


def cours_par_semaine(evenements: Iterable[Mapping[str, Any]]) -> dict[int, int]:
    """Nombre de vrais cours par indice de semaine du masque Celcat.

    L'indice est celui que `lecture.py::indice_depuis_lundi` calcule à
    l'écriture : les deux côtés parlent donc du même repère, sans conversion
    intermédiaire où se glisser une erreur.
    """
    comptes: Counter[int] = Counter()
    for evenement in evenements:
        if not _est_cours(evenement):
            continue
        indice = evenement.get("semaine")
        if isinstance(indice, bool) or not isinstance(indice, int):
            continue
        comptes[indice] += 1
    return dict(comptes)


def semaines_posees(
    evenements: Iterable[Mapping[str, Any]], *, attendus: Mapping[int, int]
) -> set[int]:
    """Les indices de semaine sur lesquels on s'autorise à créer.

    Une semaine est posée si elle est À LA FOIS largement remplie au regard
    du relevé (donc comparable aux semaines que l'équipe a fini de saisir) et
    couvrante au regard de ce que cal-iut y prévoit. Les deux ensemble : la
    première seule s'ouvrirait toute seule sur un Celcat encore vide, la
    seconde seule laisserait passer une semaine quasi vide dès que cal-iut y
    prévoit peu (cas réel de l'indice 9 : 21 cours sur ~350, mais 28 prévus).

    Sans relevé — instantané absent, illisible, ou en erreur — l'ensemble est
    VIDE : on ne sait pas ce que Celcat contient, et écrire à l'aveugle est
    exactement le geste que la consigne interdit. Le coût de se tromper dans
    ce sens-là est un cycle d'attente ; dans l'autre, une promotion à
    démêler à la main.
    """
    presents = cours_par_semaine(evenements)
    if not presents:
        return set()
    reference = max(presents.values())
    return {
        indice
        for indice, attendu in attendus.items()
        if attendu > 0
        and presents.get(indice, 0) >= COUVERTURE_MINIMALE_RELEVE * reference
        and presents.get(indice, 0) >= COUVERTURE_MINIMALE * attendu
    }


def motif_attente(indice: int, *, celcat: int, attendu: int) -> str:
    """Pourquoi ce job attend, avec les deux nombres.

    « Semaine pas encore posée » tout court n'apprend rien : c'est le
    rapport qui dit s'il faut attendre un jour de plus ou aller demander à
    l'équipe où elle en est.
    """
    return (
        f"semaine {indice} pas encore posée dans Celcat "
        f"({celcat} cours sur {attendu} prévus) — en attente"
    )
