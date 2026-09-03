"""Modifier une séance déjà posée dans Celcat, via RPC.

Cause racine du bug historique « EUDLDSError: Cannot locate a record using
only a partial key » : un update envoyait un objet RECONSTRUIT depuis zéro
(quelques champs + un `event_id` accroché dessus), pas l'enregistrement
COMPLET que Celcat exige pour identifier une mise à jour. Le correctif :
`localiser_evenement` recharge le dict BRUT complet via `udlTimetables.load`
(le seul chemin qui a marché au canari, event_id 202985), puis
`fusionner_deltas` clone ce dict et n'écrase QUE les champs qui changent —
jamais un objet reconstruit à la main. `modifier_evenement` enchaîne les
deux, revérifie avec les mêmes garde-fous que la création, puis appelle
`enregistrer_evenement` (même RPC `save`, upsert selon la présence d'un
`event_id` valide).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cal_iut.celcat.categories import verifier_charge_categorie
from cal_iut.celcat.ecriture import verifier_avant_envoi
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.navigateur import (
    BASE_ENTRAINEMENT,
    TYPE_MATIERES,
    TYPE_PERSONNEL,
    TYPE_SALLES,
)
from cal_iut.celcat.rpc import (
    charger_edt,
    charger_ressources,
    enregistrer_evenement,
    event_id_retour,
)

__all__ = [
    "ElementModification",
    "EvenementIntrouvable",
    "ResultatModification",
    "fusionner_deltas",
    "localiser_evenement",
    "modifier_evenement",
    "modifier_manquants",
]


class EvenementIntrouvable(LookupError):
    """event_id absent de tous les `group_ids` interrogés."""


def localiser_evenement(page, event_id: int, *, group_ids: list[int]) -> dict:
    """Recharge l'EDT des `group_ids` et renvoie le dict BRUT (pas un
    `EvenementCelcat` normalisé) portant `event_id`. Seul point d'entrée
    admis avant tout `save` d'update ou de delete — cf. docstring module."""
    for brut in charger_edt(page, group_ids=group_ids):
        brut_id = brut.get("event_id")
        if brut_id is None:
            brut_id = brut.get("id")
        if brut_id is not None and int(brut_id) == int(event_id):
            return brut
    raise EvenementIntrouvable(
        f"event_id={event_id} absent des group_ids={group_ids} interrogés"
    )


def _id(ids: dict, *cles: str) -> int | None:
    for cle in cles:
        val = ids.get(cle)
        if val is not None:
            return int(val)
    return None


_TYPE_RESSOURCE_ID = {
    "room_id": TYPE_SALLES,
    "staff_id": TYPE_PERSONNEL,
    "module_id": TYPE_MATIERES,
}


def _ressource_reelle(page, type_id: int, id_cible: int) -> dict | None:
    """Charge l'enregistrement RÉEL de la ressource ciblée (nom, dept_id,
    unique_name, capacité…) via `udlResources.load`. Nécessaire dès que
    l'id change : greffer un id neuf sur le sous-objet de l'ANCIENNE
    ressource envoie un dept_id/nom qui ne correspond plus à ce nouvel id —
    incohérence que Celcat n'a pas toujours refusée avec une erreur : elle
    peut aussi simplement ignorer le champ, écriture RPC en apparence
    réussie mais sans effet (constaté en direct le 02/09/2026 sur un
    changement de salle, event 202985 : réponse OK, salle inchangée)."""
    filtre = {"customOnly": False, "includedDetails": [], "recordIDs": [id_cible]}
    lots = charger_ressources(page, type_id, filtre)
    for lot in lots:
        if int(lot.get("room_id") or lot.get("staff_id") or lot.get("module_id") or lot.get("id") or 0) == id_cible:
            return dict(lot)
    return lots[0] if lots else None


def _ressource_fusionnee(
    page, brut_liste: object, *, cle_id: str, valeur: int | None, event_id: int | None
) -> list[dict]:
    """Sous-objet ressource pour l'événement fusionné.

    Id INCHANGÉE (cas le plus courant : on ne touche qu'à la catégorie, à
    l'horaire…) → on garde le sous-objet CHARGÉ tel quel, id comprise :
    c'est la seule forme prouvée en direct (WR116, 02/09/2026).

    Id CHANGÉE (déplacement vers une autre salle/enseignant/matière) → on
    ne greffe plus le nouvel id sur l'ancien sous-objet : on recharge le
    vrai enregistrement de la ressource visée (`_ressource_reelle`), sinon
    le reste du sous-objet (dept_id, nom…) parle encore de l'ANCIENNE
    ressource — une incohérence que Celcat peut ignorer sans erreur."""
    actuel = None
    if isinstance(brut_liste, list) and brut_liste and isinstance(brut_liste[0], dict):
        actuel = brut_liste[0]
    id_actuel = None
    if actuel is not None:
        for cle in ("id", cle_id):
            if actuel.get(cle) is not None:
                id_actuel = int(actuel[cle])
                break

    type_id = _TYPE_RESSOURCE_ID.get(cle_id)
    if valeur is not None and id_actuel is not None and valeur != id_actuel and type_id is not None:
        reel = _ressource_reelle(page, type_id, valeur)
        if reel is not None:
            # PAS le catalogue complet (udlResources.load renvoie un
            # schéma de ressource — ex. `area: 221.11` pour une salle —
            # que `save` refuse dans un sous-objet d'ÉVÉNEMENT : constaté
            # en direct le 02/09/2026, « '221.11' is not a valid JSON
            # expression »). Seul le sous-ensemble que
            # `event.rooms[]`/`.staff[]`/`.modules[]` porte réellement —
            # `event_id` INCLUS : sans lui, même ce sous-ensemble restreint
            # est encore une « partial key » (constaté juste après, même
            # jour) — l'association événement↔ressource se localise par
            # les DEUX, pas par le seul id de la ressource.
            item = {
                cle_id: valeur,
                "event_id": event_id,
                "dept_id": reel.get("dept_id"),
                "unique_name": reel.get("unique_name"),
                "name": reel.get("name"),
                "weeks": None,
            }
            return [item]
        # Aucun enregistrement retrouvé pour le nouvel id : mieux vaut
        # refuser que d'écrire une ressource fantôme.
        raise EvenementIntrouvable(
            f"ressource {cle_id}={valeur} introuvable via udlResources.load"
        )

    item = dict(actuel) if actuel is not None else {}
    item[cle_id] = valeur
    if "id" in item:
        # Certains relevés Celcat portent un `id` générique EN PLUS du
        # `xxx_id` typé (cf. `lecture._premier_id`, qui lit `id` en
        # priorité) — le laisser périmé après un changement de ressource
        # renverrait « save » vers l'ANCIENNE ressource sans le dire.
        item["id"] = valeur
    return [item]


def fusionner_deltas(
    page, brut: dict, *, entree: EntreeCelcat, ids: dict, group_id: int, masque: str
) -> dict:
    """Clone `brut` et n'écrase QUE day_of_week/start_time/end_time/weeks/
    event_cat_id/dept_id/modules/rooms/staff/groups/notes — même jeu de
    champs que `ecriture.charge_utile`, mais superposé sur l'enregistrement
    complet plutôt qu'à la place de rien : c'est tout le correctif. Les
    ressources (modules/rooms/staff/groups) gardent elles aussi leur
    sous-objet chargé quand l'id ne change pas ; quand elle change,
    `_ressource_fusionnee` recharge le VRAI enregistrement visé (`page`
    sert à ça) plutôt que de greffer l'id sur l'ancien sous-objet."""
    fusionne = dict(brut)
    fusionne["day_of_week"] = entree.jour - 1
    fusionne["start_time"] = entree.heure_debut
    fusionne["end_time"] = entree.heure_fin
    fusionne["weeks"] = masque
    fusionne["event_cat_id"] = _id(ids, "event_cat_id")
    fusionne["dept_id"] = _id(ids, "dept_id")
    id_evenement = brut.get("event_id")
    fusionne["modules"] = _ressource_fusionnee(
        page, brut.get("modules"), cle_id="module_id", valeur=_id(ids, "module_id"),
        event_id=id_evenement,
    )
    fusionne["rooms"] = _ressource_fusionnee(
        page, brut.get("rooms"), cle_id="room_id", valeur=_id(ids, "room_id", "salle_id"),
        event_id=id_evenement,
    )
    fusionne["staff"] = _ressource_fusionnee(
        page, brut.get("staff"), cle_id="staff_id", valeur=_id(ids, "staff_id"),
        event_id=id_evenement,
    )
    fusionne["groups"] = _ressource_fusionnee(
        page, brut.get("groups"), cle_id="group_id", valeur=group_id, event_id=id_evenement,
    )
    fusionne["notes"] = entree.session_id
    return fusionne


def modifier_evenement(
    page,
    entree: EntreeCelcat,
    *,
    event_id: int,
    group_id: int,
    ids: dict,
    masque: str,
    methode: str,
    base: str = BASE_ENTRAINEMENT,
    production_autorisee: bool = False,
) -> int:
    """Localise, fusionne, revérifie (mêmes garde-fous que la création),
    enregistre, renvoie l'event_id confirmé. N'attrape rien : c'est
    `modifier_manquants` qui encaisse un échec isolé."""
    brut = localiser_evenement(page, event_id, group_ids=[group_id])
    fusionne = fusionner_deltas(page, brut, entree=entree, ids=ids, group_id=group_id, masque=masque)
    verifier_charge_categorie(fusionne, type_seance_nom=entree.type_seance_nom)
    verifier_avant_envoi(fusionne, base=base, production_autorisee=production_autorisee)
    retour = enregistrer_evenement(page, fusionne, methode=methode)
    confirme = event_id_retour(retour)
    if confirme is None or confirme == 0:
        confirme = event_id
    return confirme


@dataclass
class ElementModification:
    entree: EntreeCelcat
    event_id: int
    group_id: int
    ids: dict
    masque: str


@dataclass
class ResultatModification:
    modifiees: list[tuple[str, int]] = field(default_factory=list)
    echecs: list[tuple[str, str]] = field(default_factory=list)


def modifier_manquants(
    page,
    elements: list[ElementModification],
    *,
    methode: str,
    base: str = BASE_ENTRAINEMENT,
    production_autorisee: bool = False,
) -> ResultatModification:
    """Comme `ecriture.creer_manquants` : un échec isolé n'arrête pas le
    lot, notifie via `_notifier_celcat`."""
    resultat = ResultatModification()
    for el in elements:
        try:
            confirme = modifier_evenement(
                page,
                el.entree,
                event_id=el.event_id,
                group_id=el.group_id,
                ids=el.ids,
                masque=el.masque,
                methode=methode,
                base=base,
                production_autorisee=production_autorisee,
            )
            resultat.modifiees.append((el.entree.session_id, confirme))
            _notifier_celcat(
                "celcat_ok",
                f"{el.entree.session_id} modifié Celcat (event_id={confirme}, {el.entree.type_seance_nom})",
            )
        except Exception as exc:  # noqa: BLE001
            resultat.echecs.append((el.entree.session_id, str(exc)))
            _notifier_celcat("celcat_echec", f"{el.entree.session_id} Celcat : {exc}")
    return resultat


def _notifier_celcat(evenement: str, texte: str) -> None:
    """Mail optionnel — jamais faire échouer l'écriture Celcat."""
    try:
        from cal_iut.api import notifications

        notifications.signaler(evenement, texte)
        notifications.envoyer_si_temps_ecoule()
    except Exception:  # noqa: BLE001
        return
