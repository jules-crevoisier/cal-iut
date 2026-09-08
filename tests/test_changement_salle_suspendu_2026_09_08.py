"""Un changement de salle est SUSPENDU tant qu'il ajoute au lieu de remplacer.

Constaté en production le 08/09/2026 au soir, dès que la détection des
salles multiples est arrivée :

    WR115-S1-TD-1-but1-td-cd   cal-iut H.101   Celcat: H.007 + H.101
    WR314D-S3-TP-1-tp-a        cal-iut H.007   Celcat: H.005 + H.007
    WR314D-S3-TP-1-tp-b        cal-iut H.007   Celcat: H.005 + H.007

Ce sont exactement les séances qui étaient en « Écart (salle) » : notre
correction a AJOUTÉ la salle voulue à côté de l'ancienne au lieu de la
remplacer. C'est le pendant RPC du glisser-sans-Maj décrit par Kyllian
Bresson le même jour.

LA CAUSE. `_ressource_fusionnee` construit un objet d'association neuf
quand l'identifiant change — sans rien qui désigne l'association EXISTANTE.
Celcat ne peut donc pas savoir laquelle remplacer : il en ajoute une et
garde l'ancienne.

CE QU'ON FAIT EN ATTENDANT. On refuse le changement de salle, avec un motif
qui dit pourquoi. Le remède probable — envoyer `{"-room_id": ancienne}`, la
convention déjà prouvée pour supprimer un évènement — n'a jamais été essayé
contre Celcat, et l'essayer en production aggraverait le problème s'il est
faux. Un refus visible vaut mieux qu'une écriture qui abîme.

CE QUI CONTINUE DE PASSER. Tout le reste : heure, jour, catégorie
d'évènement, semaine. Suspendre la salle ne doit pas suspendre la correction
des catégories fausses signalées par David, ni celle des CM à la mauvaise
heure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import (
    ChangementSalleSuspendu,
    ElementModification,
    modifier_evenement,
    modifier_manquants,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
EVENT_ID = 1931666
SALLE_ACTUELLE = 104105


def _brut() -> dict:
    brut = dict(next(b for b in json.loads(FIX.read_text(encoding="utf-8")) if b["event_id"] == EVENT_ID))
    brut["rooms"] = [{"id": SALLE_ACTUELLE, "room_id": SALLE_ACTUELLE, "name": "H.105"}]
    return brut


def _page() -> FaussePage:
    page = FaussePage()
    page.reponses["udlTimetables.load"] = [_brut()]
    return page


def _entree() -> EntreeCelcat:
    return EntreeCelcat(
        session_id="WR115-S1-TD-1-but1-td-cd",
        semaine=1, jour=1, heure_debut="11:00", heure_fin="12:30",
        code_enseignant="MRI", salle="H.101", code_module="WR115",
        type_seance=1, type_seance_nom="TD", groupe="TD AB", semestre="S1",
        lundi="2026-09-07", course_code="WR115",
    )


def _ids(room_id: int) -> dict:
    return {
        "module_id": 601106, "room_id": room_id, "staff_id": 7,
        "event_cat_id": 433, "dept_id": 4,
    }


def test_changer_de_salle_est_refuse_avec_un_motif_clair() -> None:
    """LE correctif. Sans lui, chaque correction ajoute une salle de plus."""
    with pytest.raises(ChangementSalleSuspendu) as refus:
        modifier_evenement(
            _page(), _entree(), event_id=EVENT_ID, group_id=GROUP_ID,
            ids=_ids(999999), masque="Y" + "N" * 53, methode="udlTimetables.save",
        )

    message = str(refus.value)
    assert "salle" in message.lower()
    # Le motif doit dire QUOI faire, pas seulement que c'est refusé : sinon
    # il ressort dans le bilan sans que personne ne sache s'il faut agir.
    assert "H.105" in message or str(SALLE_ACTUELLE) in message, message


def test_une_salle_inchangee_laisse_passer_la_modification() -> None:
    """Non-régression, et c'est l'essentiel : corriger une heure, un jour ou
    une CATÉGORIE ne doit pas être bloqué par cette suspension. Le
    signalement de David porte précisément sur des catégories fausses."""
    page = _page()

    confirme = modifier_evenement(
        page, _entree(), event_id=EVENT_ID, group_id=GROUP_ID,
        ids=_ids(SALLE_ACTUELLE), masque="Y" + "N" * 53, methode="udlTimetables.save",
    )

    assert confirme == EVENT_ID


def test_le_refus_n_arrete_pas_le_lot() -> None:
    """Un changement de salle refusé ne doit pas empêcher les autres
    corrections du même passage : `modifier_manquants` encaisse un échec
    isolé, et ce refus en est un."""
    page = _page()
    elements = [
        ElementModification(
            entree=_entree(), event_id=EVENT_ID, group_id=GROUP_ID,
            ids=_ids(999999), masque="Y" + "N" * 53,
        ),
        ElementModification(
            entree=_entree(), event_id=EVENT_ID, group_id=GROUP_ID,
            ids=_ids(SALLE_ACTUELLE), masque="Y" + "N" * 53,
        ),
    ]

    resultat = modifier_manquants(page, elements, methode="udlTimetables.save")

    assert len(resultat.echecs) == 1
    assert len(resultat.modifiees) == 1
    assert "salle" in resultat.echecs[0][1].lower()


def test_une_creation_garde_le_droit_de_poser_une_salle() -> None:
    """La suspension ne vise QUE le remplacement d'une salle existante. Une
    séance créée de zéro pose sa salle normalement — sans quoi les 67
    séances absentes de Celcat partiraient sans salle."""
    from cal_iut.celcat.ecriture import charge_utile

    charge = charge_utile(
        _entree(), group_id=GROUP_ID, ids=_ids(999999), masque="Y" + "N" * 53, event_id=0
    )

    assert charge["rooms"] == [{"room_id": 999999}]
