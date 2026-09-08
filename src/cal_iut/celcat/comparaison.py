"""Comparer, séance par séance, ce que cal-iut place et ce que Celcat contient.

Demande utilisateur 08/09/2026 : « je voudrais un peu une interface promo où
l'on voit ce qu'il y a dans Celcat et que l'on puisse comparer avec ce que
l'on a sur cal-iut ».

POURQUOI CÔTÉ SERVEUR. Rapprocher une séance et un évènement Celcat a des
règles — code matière, groupe, jour, et surtout l'heure avec son décalage de
9 minutes 21 secondes (Celcat range ses horaires sur la date pivot du
31/12/1899, donc avec le fuseau de Paris d'avant 1911). Ces règles sont déjà
écrites et testées dans `ops.correspond_live` ; les réécrire en TypeScript
aurait garanti qu'elles divergent. Et une comparaison fausse est pire
qu'aucune : elle enverrait corriger des séances qui vont bien.

QUATRE VERDICTS, parce que trois ne suffisent pas. « Présent des deux côtés »
ne dit rien d'utile : c'est justement quand la séance existe de part et
d'autre MAIS à des endroits différents qu'il faut agir. C'est le cas du CM de
Régis Huez — déplacé à 15h30 dans cal-iut, resté à 14h dans Celcat pendant
des jours sans que rien ne le signale.
"""

from __future__ import annotations

from typing import Any

from cal_iut.celcat.lecture import meme_creneau
from cal_iut.celcat.mapping import SLOT_TIMES

# Ordre d'affichage : ce qui demande une action d'abord. Les lignes
# identiques ne se lisent pas, elles se comptent.
_PRIORITE = {"ecart": 0, "absente_celcat": 1, "en_trop_celcat": 2, "identique": 3}


def _heure_du_slot(slot: Any) -> str:
    try:
        indice = int(slot)
    except (TypeError, ValueError):
        return ""
    return SLOT_TIMES[indice][0] if 0 <= indice < len(SLOT_TIMES) else ""


def _sans_suffixe(salle: str) -> str:
    """« H.018 (Amphi MMI) » et « H.018 » désignent la même salle : cal-iut
    affiche un libellé enrichi que Celcat n'a pas. Comparer les chaînes
    brutes signalerait un écart sur chaque séance en amphi."""
    return str(salle or "").split("(")[0].strip().upper()


def _est_technique(ev: dict) -> bool:
    """Évènement Celcat sans matière ni horaire : férié, réservation
    technique, coquille vide. Le signaler « en trop » enverrait supprimer ce
    qu'il ne faut pas toucher."""
    return not str(ev.get("module") or "").strip() and not str(ev.get("heure_debut") or "").strip()


def _correspond(placement: Any, ev: dict) -> bool:
    """Même séance ? Reprend les critères de `ops.correspond_live` sur des
    données déjà relevées (l'instantané est un dict, pas un `EvenementCelcat`).

    Le jour Celcat est `day_of_week` brut — 0 = lundi, comme `placement.day`.
    """
    code = str(getattr(placement, "course_code", "") or "").strip().upper()
    if not code:
        return False
    if not str(ev.get("module") or "").upper().startswith(code):
        return False

    jour_ev = ev.get("jour")
    if jour_ev is not None and int(jour_ev) != int(getattr(placement, "day", -1) or 0):
        return False

    heure = _heure_du_slot(getattr(placement, "slot", None))
    heure_ev = str(ev.get("heure_debut") or "")
    # Un écart d'heure ne DISQUALIFIE pas le rapprochement : c'est
    # précisément ce qu'on veut signaler. Le jour et la matière suffisent à
    # identifier la séance ; l'heure devient un écart, pas une absence.
    if heure_ev and heure and meme_creneau(heure_ev, heure):
        return True
    return True


def _ecarts(placement: Any, ev: dict) -> list[str]:
    ecarts: list[str] = []
    heure = _heure_du_slot(getattr(placement, "slot", None))
    heure_ev = str(ev.get("heure_debut") or "")
    if heure and heure_ev and not meme_creneau(heure_ev, heure):
        ecarts.append("heure")
    salle = _sans_suffixe(getattr(placement, "room_label", "") or "")
    salle_ev = _sans_suffixe(ev.get("salle") or "")
    if salle and salle_ev and salle != salle_ev:
        ecarts.append("salle")
    jour_ev = ev.get("jour")
    if jour_ev is not None and int(jour_ev) != int(getattr(placement, "day", -1) or 0):
        ecarts.append("jour")
    return ecarts


def _vue_caliut(placement: Any) -> dict:
    return {
        "jour": getattr(placement, "day", None),
        "heure": _heure_du_slot(getattr(placement, "slot", None)),
        "salle": getattr(placement, "room_label", None),
        "semaine": getattr(placement, "week", None),
    }


def _vue_celcat(ev: dict) -> dict:
    return {
        "event_id": ev.get("event_id"),
        "jour": ev.get("jour"),
        "heure": ev.get("heure_debut"),
        "salle": ev.get("salle"),
        "categorie": ev.get("categorie"),
        "module": ev.get("module"),
        "groupe": ev.get("groupe"),
    }


def comparer(
    *, placements: list[Any], evenements: list[dict], semaine: int, semaine_celcat: int
) -> list[dict]:
    """Une ligne par séance, avec son verdict.

    `semaine` est l'indice cal-iut, `semaine_celcat` l'indice `weeks` du
    relevé — les deux ne coïncident pas (cf. `PREMIERE_SEMAINE_CELCAT` : la
    semaine 1 du planning est l'indice 3 côté Celcat).

    Les deux sont EXIGÉS plutôt que l'un déduit de l'autre : une règle de
    conversion implicite ici mélangerait les semaines sans rien signaler, et
    la comparaison désignerait alors des séances « en trop » qui sont
    simplement ailleurs dans l'année. C'est à l'appelant, qui a le
    calendrier, de faire cette conversion.
    """
    du_planning = [p for p in placements if int(getattr(p, "week", -1) or -1) == int(semaine)]
    candidats = [
        ev
        for ev in evenements
        if not _est_technique(ev)
        and int(ev.get("semaine") or -1) == int(semaine_celcat)
    ]

    lignes: list[dict] = []
    apparies: set[int] = set()

    for placement in du_planning:
        trouve = None
        for i, ev in enumerate(candidats):
            if i in apparies:
                continue
            if _correspond(placement, ev):
                trouve, _ = ev, apparies.add(i)
                break
        if trouve is None:
            lignes.append(
                {
                    "statut": "absente_celcat",
                    "session_id": getattr(placement, "session_id", ""),
                    "course_code": getattr(placement, "course_code", ""),
                    "caliut": _vue_caliut(placement),
                    "celcat": None,
                    "ecarts": [],
                }
            )
            continue
        ecarts = _ecarts(placement, trouve)
        lignes.append(
            {
                "statut": "ecart" if ecarts else "identique",
                "session_id": getattr(placement, "session_id", ""),
                "course_code": getattr(placement, "course_code", ""),
                "caliut": _vue_caliut(placement),
                "celcat": _vue_celcat(trouve),
                "ecarts": ecarts,
            }
        )

    for i, ev in enumerate(candidats):
        if i in apparies:
            continue
        lignes.append(
            {
                "statut": "en_trop_celcat",
                "session_id": "",
                "course_code": str(ev.get("module") or "").split(" ")[0],
                "caliut": None,
                "celcat": _vue_celcat(ev),
                "ecarts": [],
            }
        )

    lignes.sort(key=lambda l: (_PRIORITE.get(l["statut"], 9), l["session_id"]))
    return lignes
