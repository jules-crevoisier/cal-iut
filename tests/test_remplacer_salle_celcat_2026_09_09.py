"""Changer de salle RETIRE l'ancienne — la convention, éprouvée en direct.

Signalement de Kyllian Bresson, 08/09/2026 : « Thomas Castellengo est sur
deux salles », avec la manip d'interface correspondante — glisser une salle
l'AJOUTE, il faut maintenir Maj pour qu'elle remplace.

Reproduit en production le soir même, dès que la détection des salles
multiples est arrivée :

    WR115-S1-TD-1-but1-td-cd   cal-iut H.101   Celcat: H.007 + H.101
    WR314D-S3-TP-1-tp-a        cal-iut H.007   Celcat: H.005 + H.007

`save` FUSIONNE la liste des salles : poser `rooms: [nouvelle]` ajoute la
nouvelle et garde l'ancienne.

LA CONVENTION, TROUVÉE PAR L'EXPÉRIENCE et non par déduction. Un canari
jetable sur URCA_FORMATION le 09/09/2026
(`scripts/capturer_changement_salle_celcat.py`), et chaque refus disait
précisément ce qui manquait :

    rooms=[B]                          -> ['05_U07M_Info', 'A.018']  (le défaut)
    rooms=[]                           -> ['05_U07M_Info', 'A.018']  (ne vide rien)
    {"-room_id": X}                    -> « Cannot LOCATE … partial key »
    {"-room_id": X, "event_id": E}     -> « Cannot DELETE … partial key »
    {"room_id": X, "-room_id": X}      -> « Champ '-room_id' non trouvé »
    {"-event_id": E, "-room_id": X}    -> ['A.018']   *** une seule salle ***

L'association évènement↔salle n'a pas d'identifiant propre : elle se localise
par le COUPLE `(event_id, room_id)`. Les DEUX composants portent donc le
signe moins — cohérent avec `{"-event_id": N}` pour supprimer un évènement,
où `event_id` est à lui seul la clé.

Retrait et pose dans le MÊME appel, vérifié en direct : `[A.018]` devient
`[05_U07M_Info]`.

CE QUI A ÉTÉ ÉVITÉ. J'avais d'abord conclu de compteurs que `save`
remplaçait (« les écarts de salle sont passés de 16 à 5 »), puis proposé
`{"-room_id": ancienne}` seul comme « convention déjà prouvée ». Les deux
étaient faux, et l'expérience l'a montré en trois minutes. C'est pour ça
qu'elle a eu lieu avant l'écriture, et pas après.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_celcat_rpc import FaussePage  # type: ignore[import-not-found]

from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import ElementModification, fusionner_deltas, modifier_manquants

FIX = Path(__file__).resolve().parent / "fixtures" / "celcat_udl_load.json"
GROUP_ID = 1661972
EVENT_ID = 1931666
SALLE_ACTUELLE = 104105
SALLE_VOULUE = 104103


def _brut(*salles: dict) -> dict:
    brut = dict(
        next(b for b in json.loads(FIX.read_text(encoding="utf-8")) if b["event_id"] == EVENT_ID)
    )
    brut["rooms"] = list(salles) or [
        {"id": SALLE_ACTUELLE, "room_id": SALLE_ACTUELLE, "name": "H.105", "event_id": EVENT_ID}
    ]
    return brut


def _page() -> FaussePage:
    page = FaussePage()
    page.reponses["udlResources.load"] = [
        {"room_id": SALLE_VOULUE, "name": "H.103", "dept_id": 500001, "unique_name": "1700AR_010"}
    ]
    return page


def _entree() -> EntreeCelcat:
    return EntreeCelcat(
        session_id="WR115-S1-TD-1-but1-td-cd",
        semaine=1, jour=1, heure_debut="11:00", heure_fin="12:30",
        code_enseignant="MRI", salle="H.103", code_module="WR115",
        type_seance=1, type_seance_nom="TD", groupe="TD AB", semestre="S1",
        lundi="2026-09-07", course_code="WR115",
    )


def _ids(room_id: int) -> dict:
    return {
        "module_id": 601106, "room_id": room_id, "staff_id": 7,
        "event_cat_id": 433, "dept_id": 4,
    }


def _fusion(brut: dict, room_id: int) -> dict:
    return fusionner_deltas(
        _page(), brut, entree=_entree(), ids=_ids(room_id),
        group_id=GROUP_ID, masque="Y" + "N" * 53,
    )


def test_changer_de_salle_retire_l_ancienne_et_pose_la_nouvelle() -> None:
    """LE correctif. Sans le retrait, le cours se retrouve sur deux salles."""
    rooms = _fusion(_brut(), SALLE_VOULUE)["rooms"]

    retraits = [r for r in rooms if "-room_id" in r]
    poses = [r for r in rooms if "room_id" in r]

    assert len(retraits) == 1, f"l'ancienne salle doit être retirée : {rooms}"
    assert retraits[0]["-room_id"] == SALLE_ACTUELLE
    assert retraits[0]["-event_id"] == EVENT_ID, (
        "les DEUX composants de la clé portent le signe moins — sans event_id, "
        "Celcat répond « Cannot delete a record using only a partial key »"
    )
    assert len(poses) == 1 and poses[0]["room_id"] == SALLE_VOULUE


def test_le_marqueur_de_retrait_ne_porte_jamais_le_champ_normal() -> None:
    """Vérifié en direct : `{"room_id": X, "-room_id": X}` est refusé par
    « Champ '-room_id' non trouvé ». Le marqueur n'est lu qu'en l'absence du
    champ normal."""
    rooms = _fusion(_brut(), SALLE_VOULUE)["rooms"]

    for item in rooms:
        if "-room_id" in item:
            assert "room_id" not in item, item
            assert "event_id" not in item, item


def test_une_salle_inchangee_ne_declenche_aucun_retrait() -> None:
    """Non-régression : quand la salle est déjà la bonne, on garde le
    sous-objet CHARGÉ tel quel — la seule forme prouvée dans ce cas."""
    rooms = _fusion(_brut(), SALLE_ACTUELLE)["rooms"]

    assert not any("-room_id" in r for r in rooms), rooms
    assert len(rooms) == 1 and rooms[0]["room_id"] == SALLE_ACTUELLE


def test_deux_salles_deja_posees_sont_ramenees_a_une_seule() -> None:
    """Le cas des séances déjà abîmées : Celcat en porte deux, cal-iut n'en
    veut qu'une. Les deux mauvaises doivent partir."""
    brut = _brut(
        {"id": SALLE_ACTUELLE, "room_id": SALLE_ACTUELLE, "name": "H.105", "event_id": EVENT_ID},
        {"id": 999, "room_id": 999, "name": "H.999", "event_id": EVENT_ID},
    )

    rooms = _fusion(brut, SALLE_VOULUE)["rooms"]

    retires = sorted(r["-room_id"] for r in rooms if "-room_id" in r)
    assert retires == [999, SALLE_ACTUELLE], rooms
    assert [r["room_id"] for r in rooms if "room_id" in r] == [SALLE_VOULUE]


def test_la_bonne_salle_parmi_deux_est_conservee_sans_etre_reposee() -> None:
    """Si la salle voulue est DÉJÀ là à côté d'une intruse, on retire
    seulement l'intruse — inutile de reposer ce qui est en place, et le
    sous-objet chargé est la forme sûre."""
    brut = _brut(
        {"id": SALLE_VOULUE, "room_id": SALLE_VOULUE, "name": "H.103", "event_id": EVENT_ID},
        {"id": 999, "room_id": 999, "name": "H.999", "event_id": EVENT_ID},
    )

    rooms = _fusion(brut, SALLE_VOULUE)["rooms"]

    assert [r["-room_id"] for r in rooms if "-room_id" in r] == [999]
    assert [r["room_id"] for r in rooms if "room_id" in r] == [SALLE_VOULUE]


def test_sans_salle_voulue_on_ne_retire_rien() -> None:
    """Une séance sans salle affectée ne doit pas faire effacer la salle
    posée dans Celcat : ne rien savoir n'autorise pas à détruire."""
    ids = _ids(SALLE_VOULUE)
    ids["room_id"] = None

    rooms = fusionner_deltas(
        _page(), _brut(), entree=_entree(), ids=ids,
        group_id=GROUP_ID, masque="Y" + "N" * 53,
    )["rooms"]

    assert not any("-room_id" in r for r in rooms), rooms
    assert rooms[0]["room_id"] == SALLE_ACTUELLE


def test_un_echec_de_salle_n_arrete_pas_le_lot() -> None:
    """Non-régression : `modifier_manquants` encaisse un échec isolé."""
    page = _page()
    # L'évènement existe (sinon on échouerait sur sa localisation, pas sur la
    # salle — et le test passerait pour la mauvaise raison).
    page.reponses["udlTimetables.load"] = [_brut()]
    page.reponses["udlResources.load"] = []  # la salle visée est introuvable
    elements = [
        ElementModification(
            entree=_entree(), event_id=EVENT_ID, group_id=GROUP_ID,
            ids=_ids(SALLE_VOULUE), masque="Y" + "N" * 53,
        )
    ]

    resultat = modifier_manquants(page, elements, methode="udlTimetables.save")

    assert len(resultat.echecs) == 1
    assert str(SALLE_VOULUE) in resultat.echecs[0][1]
