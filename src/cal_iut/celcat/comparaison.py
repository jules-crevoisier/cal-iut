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

import hashlib
import re
from typing import Any

from cal_iut.celcat.lecture import meme_creneau
from cal_iut.celcat.mapping import SLOT_TIMES

# Ordre d'affichage : ce qui demande une action d'abord. Les lignes
# identiques ne se lisent pas, elles se comptent.
# Ordre d'affichage : ce qui demande une action d'abord. « hors_celcat »
# passe après « identique » — ce sont des séances dont il n'y a rien à faire,
# elles se comptent sans se lire.
_PRIORITE = {
    "ecart": 0,
    "absente_celcat": 1,
    "en_trop_celcat": 2,
    "identique": 3,
    "hors_celcat": 4,
}


def _indice(valeur: Any) -> int:
    """Un indice de semaine, ou -1 s'il n'y en a pas. ZÉRO EST UN INDICE.

    Le filtre s'écrivait `int(getattr(p, "week", -1) or -1)`. Pour la
    semaine 0 — la première semaine de cours, celle du 31 août 2026 —
    `0 or -1` vaut -1 : AUCUN placement de cette semaine n'entrait dans la
    comparaison. cal-iut paraissait ne rien y prévoir, et chaque cours que
    Celcat y possède ressortait « en trop dans Celcat », c'est-à-dire
    candidat à la SUPPRESSION.

    Constaté le 09/09/2026 : 38 cours de BUT3 en alternance, tous réels,
    tous posés par l'équipe pédagogique, sur la semaine que l'écran nomme
    « Semaine 2 (31 août-4 sept.) » — l'indice 0 du planning. Ils étaient
    restés invisibles tant que les groupes S5 TD EF et TD GH manquaient à
    `celcat_groupes.yaml` : le relevé ne lisait pas leurs évènements. Les
    ajouter (PR #150) a révélé le défaut, il ne l'a pas créé.

    Le même piège existait sur `ev["semaine"]`, l'indice de masque Celcat,
    dont 0 est une semaine parfaitement valide.
    """
    if valeur is None:
        return -1
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return -1


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


_ETIQUETTE = re.compile(r"^\s*\[([^\]]+)\]")


def _type_celcat(ev: dict) -> str:
    """Le type de cours porté par la catégorie Celcat : « [CM] 100% » -> CM.

    Seule l'étiquette entre crochets fait foi. Le pourcentage et les
    variantes (bénévole, capacité) ne disent rien du type et signaler leurs
    différences ferait ressortir comme fausses des catégories parfaitement
    correctes. Une catégorie administrative (« Conférence », « Jour férié »)
    n'a pas de crochets et rend donc la chaîne vide.
    """
    m = _ETIQUETTE.match(str(ev.get("categorie") or ""))
    return m.group(1).strip().upper() if m else ""


def _ecarts(
    placement: Any,
    ev: dict,
    salles_celcat: dict[str, str],
    types_seance: dict[str, str] | None = None,
) -> list[str]:
    ecarts: list[str] = []
    # LA CATÉGORIE D'ÉVÈNEMENT, signalée par David Annebicque le 05/09/2026 :
    # « les TD sont aléatoirement indiqués en TD ou en CM dans le type de
    # cours, ça casse la synchro et ça posera souci sur OMEGA ». Elle n'était
    # pas comparée : six TD étiquetés [CM] en production (WR101, WR106,
    # semaine 1) ressortaient « identique », et l'écran affirmait donc que
    # tout concordait précisément là où c'était faux.
    #
    # Ne rien dire quand on ne SAIT pas : un type de séance inconnu ou une
    # catégorie sans crochets ne produit aucun écart, plutôt qu'un écart
    # inventé.
    notre_type = str((types_seance or {}).get(str(getattr(placement, "session_id", "")), "")).upper()
    type_celcat = _type_celcat(ev)
    if notre_type and type_celcat and notre_type != type_celcat:
        ecarts.append("catégorie")
    # UN COURS SUR DEUX SALLES. Signalé par Kyllian Bresson le 08/09/2026 :
    # « Thomas Castellengo est sur deux salles ». Sur l'interface Celcat, une
    # salle glissée sans Maj s'AJOUTE à l'ancienne au lieu de la remplacer.
    #
    # Le relevé ne rapportait que la première salle, si bien qu'un tel
    # évènement passait pour normal — l'écran affirmait « identique » sur un
    # cours qui occupe deux salles à la fois.
    #
    # Le champ est ABSENT des instantanés déjà déposés : on ne signale donc
    # rien tant qu'un nouveau relevé n'est pas passé. Ne pas savoir n'est pas
    # constater une faute.
    salles = ev.get("salles")
    if isinstance(salles, list) and len(salles) > 1:
        ecarts.append("salles multiples")
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
        # Toutes les salles, pour que l'écran puisse MONTRER le doublon qu'il
        # signale : « écart (salles multiples) » sans dire lesquelles
        # obligerait à rouvrir Celcat pour savoir de quoi on parle.
        "salles": ev.get("salles") if isinstance(ev.get("salles"), list) else None,
        "categorie": ev.get("categorie"),
        "module": ev.get("module"),
        "groupe": ev.get("groupe"),
    }


def _rang_placement(placement: Any) -> tuple:
    """Ordre stable des seances d'une semaine : jour, creneau, identifiant."""
    return (
        int(getattr(placement, "day", -1) or 0),
        int(getattr(placement, "slot", -1) or 0),
        str(getattr(placement, "session_id", "")),
    )


def _rang_evenement(ev: dict) -> tuple:
    """Ordre stable des evenements Celcat.

    `event_id` ferme le tri : deux evenements qui partagent jour, heure et
    salle existent (un CM dedouble), et sans ce dernier critere leur ordre
    relatif resterait celui du retour RPC.
    """
    try:
        identifiant = int(ev.get("event_id") or 0)
    except (TypeError, ValueError):
        identifiant = 0
    return (
        _indice(ev.get("jour")),
        str(ev.get("heure_debut") or ""),
        str(ev.get("salle") or ""),
        identifiant,
    )


def _apparier(
    du_planning: list[Any],
    candidats: list[dict],
    apparies: set[int],
    *,
    groupes_celcat: dict[str, str],
    salles_celcat: dict[str, str],
    types_seance: dict[str, str],
    journal: dict[str, int],
) -> dict[int, int]:
    """Qui va avec qui — rang de la seance -> rang de l'evenement.

    DEUX PASSES, et l'ordre compte.

    1. LE JOURNAL D'ABORD. `celcat/sync.py` retient l'`event_id` de ce que
       nous avons ecrit : c'est l'identite de la seance la-bas, pas une
       heuristique. Quand il designe un evenement de la semaine, ces deux-la
       vont ensemble, et aucune ressemblance ne peut les separer. C'est ce
       qui rend l'appariement stable d'un releve a l'autre.

       Le module est verifie quand meme : un journal perime pourrait
       designer un evenement recycle par Celcat pour autre chose, et un
       appariement au mauvais cours ferait corriger la mauvaise seance.

    2. LE MEILLEUR CANDIDAT ENSUITE, pas le premier venu. `_correspond`
       accepte volontairement un evenement dont l'heure differe — c'est
       l'ecart qu'on veut signaler. Le premier trouve pouvait donc etre
       celui de 14h quand celui de 15h30 concordait exactement. On compte
       les divergences et on prend le minimum ; a egalite, le plus petit
       `event_id`, pour que le resultat ne depende jamais de l'ordre
       d'arrivee.
    """
    attribue: dict[int, int] = {}

    par_event: dict[int, int] = {}
    for rang, ev in enumerate(candidats):
        try:
            par_event.setdefault(int(ev.get("event_id") or 0), rang)
        except (TypeError, ValueError):
            continue

    for rang_placement, placement in enumerate(du_planning):
        brut = journal.get(str(getattr(placement, "session_id", "")))
        try:
            event_id = int(brut) if brut is not None else None
        except (TypeError, ValueError):
            event_id = None
        if event_id is None:
            continue
        rang_candidat = par_event.get(event_id)
        if rang_candidat is None or rang_candidat in apparies:
            continue
        code = str(getattr(placement, "course_code", "") or "").strip().upper()
        module = str(candidats[rang_candidat].get("module") or "").strip()
        if module and code and not _meme_module(code, module):
            continue
        attribue[rang_placement] = rang_candidat
        apparies.add(rang_candidat)

    for rang_placement, placement in enumerate(du_planning):
        if rang_placement in attribue:
            continue
        meilleur: tuple[tuple[int, int], int] | None = None
        for rang_candidat, ev in enumerate(candidats):
            if rang_candidat in apparies:
                continue
            if not _correspond(placement, ev, groupes_celcat, salles_celcat):
                continue
            try:
                identifiant = int(ev.get("event_id") or 0)
            except (TypeError, ValueError):
                identifiant = 0
            score = (len(_ecarts(placement, ev, salles_celcat, types_seance)), identifiant)
            if meilleur is None or score < meilleur[0]:
                meilleur = (score, rang_candidat)
        if meilleur is not None:
            attribue[rang_placement] = meilleur[1]
            apparies.add(meilleur[1])

    return attribue


def empreinte(lignes: list[dict]) -> str:
    """Signature des DIVERGENCES d'une semaine — pas de son contenu.

    Sert a repondre a « est-ce que la situation a change depuis le dernier
    passage ? ». Deux usages, tous deux dans la boucle de reconciliation :
    ne pas re-enfiler une semaine dont rien n'a bouge, et reperer un
    battement — la meme divergence qui revient en changeant d'`event_id`,
    signature d'un appariement instable qu'aucune ecriture ne reglera.

    Ce qui concorde n'entre pas dans le calcul : une seance qui passe de
    « ecart » a « identique » doit changer l'empreinte, mais deux releves
    egalement conformes doivent rendre la meme.
    """
    parts = []
    for ligne in sorted(lignes, key=lambda l: (str(l.get("statut")), str(l.get("session_id")))):
        statut = str(ligne.get("statut") or "")
        if statut in ("identique", "hors_celcat"):
            continue
        celcat = ligne.get("celcat") or {}
        parts.append(
            "|".join(
                (
                    statut,
                    str(ligne.get("session_id") or ""),
                    str(celcat.get("event_id") or ""),
                    ",".join(str(e) for e in (ligne.get("ecarts") or [])),
                )
            )
        )
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def comparer(
    *,
    placements: list[Any],
    evenements: list[dict],
    semaine: int,
    semaine_celcat: int,
    groupes_celcat: dict[str, str] | None = None,
    salles_celcat: dict[str, str] | None = None,
    codes_celcat: set[str] | None = None,
    types_seance: dict[str, str] | None = None,
    journal: dict[str, int] | None = None,
) -> list[dict]:
    """Une ligne par séance, avec son verdict.

    `journal` est la table `session_id -> event_id` tenue par
    `celcat/sync.py` : ce que NOUS avons ecrit, et ou. Facultative, mais
    c'est elle qui rend l'appariement stable (cf. `_apparier`).

    `semaine` est l'indice cal-iut, `semaine_celcat` l'indice `weeks` du
    relevé — les deux ne coïncident pas (cf. `PREMIERE_SEMAINE_CELCAT` : la
    semaine 1 du planning est l'indice 3 côté Celcat).

    Les deux sont EXIGÉS plutôt que l'un déduit de l'autre : une règle de
    conversion implicite ici mélangerait les semaines sans rien signaler, et
    la comparaison désignerait alors des séances « en trop » qui sont
    simplement ailleurs dans l'année. C'est à l'appelant, qui a le
    calendrier, de faire cette conversion.
    """
    # TRI AVANT TOUT APPARIEMENT, des deux cotes.
    #
    # L'appariement consomme les candidats dans l'ordre ou ils arrivent, et
    # cet ordre venait de `udlTimetables.load`, que Celcat ne garantit pas
    # stable d'un appel a l'autre. Deux seances de meme matiere, meme groupe
    # et meme jour peuvent donc ECHANGER leur evenement entre deux releves :
    # la comparaison rend alors un ecart different a chaque fois, sur des
    # donnees pourtant identiques.
    #
    # Sans consequence tant que personne ne replanifiait tout seul. Mais une
    # boucle de reconciliation pousserait l'heure A, relirait, pousserait
    # l'heure B, indefiniment — sur un evenement Celcat bien reel. Le tri
    # coute deux lignes et supprime la dependance a l'ordre de retour.
    du_planning = sorted(
        (p for p in placements if _indice(getattr(p, "week", None)) == int(semaine)),
        key=_rang_placement,
    )
    # Dédoublonnage par `event_id` : le relevé interroge 29 groupes, et un CM
    # commun à la promo est rendu une fois PAR groupe. Sans ça, le même
    # évènement apparaissait cinq fois « en trop » — liste illisible et
    # compteur faux (constaté sur le premier relevé réel, 08/09/2026).
    candidats: list[dict] = []
    vus: set[int] = set()
    for ev in evenements:
        if _est_technique(ev) or _indice(ev.get("semaine")) != int(semaine_celcat):
            continue
        identifiant = ev.get("event_id")
        if identifiant is not None:
            if identifiant in vus:
                continue
            vus.add(int(identifiant))
        candidats.append(ev)
    candidats.sort(key=_rang_evenement)

    lignes: list[dict] = []
    apparies: set[int] = set()
    attribue = _apparier(
        du_planning,
        candidats,
        apparies,
        groupes_celcat=groupes_celcat or {},
        salles_celcat=salles_celcat or {},
        types_seance=types_seance or {},
        journal=journal or {},
    )

    for rang_placement, placement in enumerate(du_planning):
        indice_trouve = attribue.get(rang_placement)
        trouve = candidats[indice_trouve] if indice_trouve is not None else None
        if trouve is None:
            # WR100BU (la BU), ÉCHANGE-IA, les rentrées : aucune équivalence
            # module dans Celcat, donc aucune vocation à y aller. Les
            # compter « absentes » les mélangerait à de vrais oublis, et un
            # « tout corriger » tenterait de les créer — ce que le worker
            # refuse à chaque passage (« WR100BU sans code Celcat »).
            code_seance = str(getattr(placement, "course_code", "") or "").strip().upper()
            hors_perimetre = codes_celcat is not None and code_seance not in codes_celcat
            lignes.append(
                {
                    "statut": "hors_celcat" if hors_perimetre else "absente_celcat",
                    "session_id": getattr(placement, "session_id", ""),
                    "course_code": getattr(placement, "course_code", ""),
                    "caliut": _vue_caliut(placement),
                    "celcat": None,
                    "ecarts": [],
                }
            )
            continue
        ecarts = _ecarts(placement, trouve, salles_celcat or {}, types_seance or {})
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
