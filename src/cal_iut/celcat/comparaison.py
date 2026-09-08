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
    """« H.018 (Amphi MMI) » et « H.018 » : cal-iut affiche un libellé enrichi
    que Celcat n'a pas."""
    return str(salle or "").split("(")[0].strip().upper()


def _salle_attendue(placement: Any, salles_celcat: dict[str, str]) -> str:
    """Le nom CELCAT de la salle placée, via la table de correspondance.

    `data/config/celcat.yaml` dit `h018: "Amphi 3 MMI"` : les deux outils
    nomment la même salle différemment. Comparer les libellés signalait un
    écart sur TOUS les CM en amphi — les séances les plus visibles. Cette
    table sert déjà à l'écriture ; s'en servir aussi pour comparer, c'est
    garantir que les deux sens voient le même monde.
    """
    room_id = str(getattr(placement, "room_id", "") or "")
    equivalent = salles_celcat.get(room_id)
    if equivalent:
        return _sans_suffixe(equivalent)
    return _sans_suffixe(getattr(placement, "room_label", "") or "")


def _meme_module(code: str, module: str) -> bool:
    """« WR314D » (nous) et « WR314 Prog. Web » (Celcat) : même matière.

    Celcat indexe souvent le module SANS le suffixe de parcours que nous
    ajoutons — la règle est déjà écrite dans `celcat.yaml` pour le mapping,
    elle manquait ici. Sans elle, des séances S3 et S5 ressortaient
    « absentes » ET « en trop » alors que jour, heure et salle concordaient
    (relevé de la semaine 2, 08/09/2026).

    Le suffixe n'est retiré qu'EN DERNIER RECOURS, et seulement si ce qui
    suit le préfixe n'est pas un chiffre : sans cette précaution, « WR31 »
    se rapprocherait de « WR314 » — un faux « identique », bien pire qu'un
    faux « absent » puisqu'il ferait croire à une synchro correcte.
    """
    nom = module.upper()
    if nom.startswith(code):
        return True
    tronque = code[:-1] if len(code) > 1 and code[-1].isalpha() else ""
    if not tronque or not nom.startswith(tronque):
        return False
    suivant = nom[len(tronque) : len(tronque) + 1]
    return not suivant.isdigit()


def _est_technique(ev: dict) -> bool:
    """Évènement Celcat sans matière ni horaire : férié, réservation
    technique, coquille vide. Le signaler « en trop » enverrait supprimer ce
    qu'il ne faut pas toucher."""
    return not str(ev.get("module") or "").strip() and not str(ev.get("heure_debut") or "").strip()


def _correspond(
    placement: Any, ev: dict, groupes_celcat: dict[str, str], salles_celcat: dict[str, str]
) -> bool:
    """Même séance ? Reprend les critères de `ops.correspond_live` sur des
    données déjà relevées (l'instantané est un dict, pas un `EvenementCelcat`).

    Le jour Celcat est `day_of_week` brut — 0 = lundi, comme `placement.day`.

    LE GROUPE EST DÉTERMINANT, et son absence a coûté un premier relevé
    inexploitable (08/09/2026 : 55 séances « absentes » et 51 « en trop »,
    presque symétriques). Deux TD de groupes différents partagent le même
    créneau et la même matière : sans ce critère, le premier placement prend
    l'évènement de l'autre, et le second ne trouve plus rien. Mieux vaut
    « absente de Celcat » qu'un appariement au mauvais groupe — le premier
    envoie vérifier, le second ferait corriger la mauvaise séance.
    """
    code = str(getattr(placement, "course_code", "") or "").strip().upper()
    if not code:
        return False
    module = str(ev.get("module") or "").strip()
    if not module:
        # Évènement officiel saisi à la main dans Celcat (rentrée,
        # présentation des services) : sans module, le rapprochement par code
        # matière est impossible. Le créneau et la salle suffisent à
        # l'identifier — sans quoi il compte DOUBLE, « absent » d'un côté et
        # « en trop » de l'autre.
        meme_jour = ev.get("jour") is None or int(ev["jour"]) == int(getattr(placement, "day", -1) or 0)
        heure = _heure_du_slot(getattr(placement, "slot", None))
        meme_heure = bool(heure) and meme_creneau(str(ev.get("heure_debut") or ""), heure)
        meme_salle = _sans_suffixe(ev.get("salle") or "") == _salle_attendue(placement, salles_celcat)
        return meme_jour and meme_heure and meme_salle
    if not _meme_module(code, module):
        return False

    # Indexé par `session_id` : c'est la SÉANCE qui porte le semestre, et le
    # nom Celcat en a besoin (« BUT MMI S1 CM »). Passer par le groupe seul
    # produisait « BUT MMI  CM » — un nom qui ne correspond à rien.
    attendu = groupes_celcat.get(str(getattr(placement, "session_id", "")), "")
    vu = str(ev.get("groupe") or "").strip().upper()
    if attendu and vu and attendu.strip().upper() != vu:
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


def _ecarts(placement: Any, ev: dict, salles_celcat: dict[str, str]) -> list[str]:
    ecarts: list[str] = []
    heure = _heure_du_slot(getattr(placement, "slot", None))
    heure_ev = str(ev.get("heure_debut") or "")
    if heure and heure_ev and not meme_creneau(heure_ev, heure):
        ecarts.append("heure")
    salle = _salle_attendue(placement, salles_celcat)
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
    *,
    placements: list[Any],
    evenements: list[dict],
    semaine: int,
    semaine_celcat: int,
    groupes_celcat: dict[str, str] | None = None,
    salles_celcat: dict[str, str] | None = None,
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
    # Dédoublonnage par `event_id` : le relevé interroge 29 groupes, et un CM
    # commun à la promo est rendu une fois PAR groupe. Sans ça, le même
    # évènement apparaissait cinq fois « en trop » — liste illisible et
    # compteur faux (constaté sur le premier relevé réel, 08/09/2026).
    candidats: list[dict] = []
    vus: set[int] = set()
    for ev in evenements:
        if _est_technique(ev) or int(ev.get("semaine") or -1) != int(semaine_celcat):
            continue
        identifiant = ev.get("event_id")
        if identifiant is not None:
            if identifiant in vus:
                continue
            vus.add(int(identifiant))
        candidats.append(ev)

    lignes: list[dict] = []
    apparies: set[int] = set()

    for placement in du_planning:
        trouve = None
        for i, ev in enumerate(candidats):
            if i in apparies:
                continue
            if _correspond(placement, ev, groupes_celcat or {}, salles_celcat or {}):
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
        ecarts = _ecarts(placement, trouve, salles_celcat or {})
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
