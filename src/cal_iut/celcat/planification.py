"""Ce qu'il y a À FAIRE dans Celcat pour une semaine — la comparaison, rien d'autre.

Demande utilisateur 08/09/2026 : « c'est possible de virer tout ce qui n'est
pas nécessaire et repartir uniquement de la comparaison », « on veut
uniquement modifier ce qui ne va pas », puis « il faut bien fix cela et tout
ce que l'on a fait pour les prochaines saisies ».

CE QUI N'ALLAIT PAS. `executer_job_nuit` enfilait une CRÉATION pour chaque
séance dont le journal ignorait l'`event_id`, sans jamais regarder ce que
Celcat contient. Le journal étant quasi vide, cela a produit 409 créations
pour les semaines 1 à 3 — quand la comparaison des mêmes semaines dit :

    identique      : 250   -> RIEN à faire
    ecart          :  21   -> modifier (l'évènement existe, on a son event_id)
    absente_celcat :  60   -> créer
    en_trop_celcat :  24   -> supprimer

Soit 105 jobs utiles au lieu de 491. Les ~350 créations superflues visaient
des cours que Celcat possède déjà : au mieux elles échouent (« Cannot locate
a record using only a partial key »), au pire elles posent un doublon.

POURQUOI CE MODULE EXISTE. La construction du contexte de comparaison — nom
Celcat de chaque groupe, table des salles, codes matière connus, type de
séance — vivait uniquement dans `api/main.py`. Le worker, lui, n'a pas accès
à l'API. La dupliquer aurait garanti qu'elle diverge : c'est déjà arrivé le
08/09/2026 avec le nom de groupe reconstruit depuis le `Group` au lieu de la
séance, qui produisait « BUT MMI  CM » et rendait ZÉRO séance identique sur
une semaine entière. Une seule construction, donc, partagée par l'écran et
par le worker — les deux voient exactement le même monde.

CE MODULE NE FAIT AUCUN RÉSEAU. Il lit l'état applicatif et l'instantané
déposé par le sidecar. C'est ce qui le rend testable sans VPN.
"""

from __future__ import annotations

from typing import Any

from cal_iut.celcat.comparaison import comparer
from cal_iut.celcat.mapping import libelle_groupe_celcat, load_celcat_config


class ContexteComparaison:
    """Les tables de correspondance nécessaires pour comparer une semaine.

    Assemblées une fois, réutilisables pour toutes les semaines : leur
    construction lit tout le planning, et la refaire par semaine coûterait
    autant de balayages que de semaines.
    """

    __slots__ = ("groupes_celcat", "salles_celcat", "codes_celcat", "types_seance")

    def __init__(
        self,
        *,
        groupes_celcat: dict[str, str],
        salles_celcat: dict[str, str],
        codes_celcat: set[str],
        types_seance: dict[str, str],
    ) -> None:
        self.groupes_celcat = groupes_celcat
        self.salles_celcat = salles_celcat
        self.codes_celcat = codes_celcat
        self.types_seance = types_seance


def contexte(state: Any) -> ContexteComparaison:
    """Les correspondances cal-iut -> Celcat, depuis l'état applicatif.

    Le nom Celcat d'un groupe s'écrit « BUT MMI S1 CM » : le semestre vient
    de la SÉANCE, pas du `Group` — qui n'a tout simplement pas cet attribut.
    Le construire depuis le groupe donnait « BUT MMI  CM », un nom qui ne
    correspond à rien : la comparaison rendait alors ZÉRO « identique » sur
    une semaine entière, chaque séance ressortant à la fois « absente » et
    « en trop » (constaté en production le 08/09/2026).

    Le TYPE de séance sert à comparer la catégorie d'évènement Celcat —
    signalement de David Annebicque : « les TD sont aléatoirement indiqués en
    TD ou en CM ». Il vient de la séance lui aussi ; le déduire du
    `session_id` marcherait aujourd'hui et casserait au premier identifiant
    nommé autrement.
    """
    cfg = load_celcat_config(state.config_dir)
    libelles = {g.id: g.label for g in state.groups}
    groupes_celcat: dict[str, str] = {}
    types_seance: dict[str, str] = {}

    for placement in state.timetable:
        session = state.sessions_by_id.get(placement.session_id)
        type_seance = str(
            getattr(getattr(session, "session_type", None), "value", "") or ""
        ).strip()
        if type_seance:
            types_seance[placement.session_id] = type_seance.upper()
        semestre = str(getattr(session, "semestre", "") or "").strip()
        ids = list(getattr(placement, "group_ids", None) or [])
        if not semestre or not ids:
            continue
        label = str(libelles.get(ids[0], ids[0]))
        groupes_celcat[placement.session_id] = f"BUT MMI {semestre} {libelle_groupe_celcat(label)}"

    return ContexteComparaison(
        groupes_celcat=groupes_celcat,
        salles_celcat=cfg.salles,
        codes_celcat=set(cfg.modules),
        types_seance=types_seance,
    )


def journal_event_ids(doc: Any) -> dict[str, int]:
    """La table `session_id -> event_id` tenue par `celcat/sync.py`.

    Lue ici plutot que dans `comparaison.py`, qui doit rester une fonction
    des seules donnees qu'on lui passe. Les valeurs y sont des CHAINES
    (`marquer_saisi` les ecrit ainsi) : les convertir au bord evite que
    chaque appelant refasse la meme conversion, et qu'un seul l'oublie.
    """
    brut = doc.get("journal") if isinstance(doc, dict) else None
    if not isinstance(brut, dict):
        return {}
    table: dict[str, int] = {}
    for session_id, ligne in brut.items():
        if not isinstance(ligne, dict):
            continue
        try:
            table[str(session_id)] = int(ligne["event_id"])
        except (KeyError, TypeError, ValueError):
            continue
    return table


def lignes(
    state: Any, *, semaine: int, semaine_celcat: int, evenements: list[dict],
    ctx: ContexteComparaison | None = None,
    journal: dict[str, int] | None = None,
) -> list[dict]:
    """Le verdict séance par séance pour une semaine.

    `journal` fixe l'identite des seances que nous avons deja ecrites, et
    rend l'appariement stable d'un releve a l'autre. Facultatif : sans lui,
    la comparaison retombe sur la ressemblance seule — c'est ce que faisait
    tout le monde avant le 16/09/2026.
    """
    c = ctx or contexte(state)
    return comparer(
        placements=list(state.timetable),
        evenements=list(evenements),
        semaine=semaine,
        semaine_celcat=semaine_celcat,
        groupes_celcat=c.groupes_celcat,
        salles_celcat=c.salles_celcat,
        codes_celcat=c.codes_celcat,
        types_seance=c.types_seance,
        journal=journal,
    )


def jobs_depuis_lignes(
    lignes_comparaison: list[dict],
    *,
    semaine: int,
    group_id_pour_nom: Any,
    avec_suppressions: bool = True,
    abandonnes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Traduit des verdicts en jobs de file — et RIEN pour ce qui concorde.

    C'est ici que « on veut uniquement modifier ce qui ne va pas » devient du
    code : `identique` et `hors_celcat` ne produisent aucun job.

    Un écart devient une MODIFICATION portant l'`event_id` relevé, jamais une
    création : créer poserait un doublon à côté de l'évènement existant, et
    `creer_manquants` n'a aucun garde-fou pour l'empêcher.

    `group_id_pour_nom` est passé par l'appelant plutôt que lu ici : la table
    des identifiants de groupe vit dans `data/config/celcat_groupes.yaml`, et
    la résolution diffère selon qu'on est côté API ou côté worker.

    `avec_suppressions=False` traduit les modifications et les créations sans
    toucher aux « en trop ». Un écart et une absence sont auto-limitants : si
    quelqu'un a déjà corrigé dans Celcat, la comparaison rend « identique » et
    rien ne part. Une suppression, non — un évènement peut ressortir « en
    trop » parce qu'il fait double emploi, ou parce que notre rapprochement
    l'a raté, et les deux sont indiscernables.

    `abandonnes` recueille ce qu'on n'a PAS su traduire, avec sa raison. Ces
    cas tombaient dans un `continue` muet : l'écran annonçait neuf écarts et
    cinq corrections, sans que rien n'explique les quatre autres. Les nommer
    est le minimum — ils ne partiront jamais tant que personne ne les voit.
    """
    jobs: list[dict[str, Any]] = []
    perdus = abandonnes if abandonnes is not None else []

    def _abandonner(ligne: dict, raison: str, explication: str) -> None:
        celcat = ligne.get("celcat") or {}
        perdus.append(
            {
                "statut": str(ligne.get("statut") or ""),
                "session_id": str(ligne.get("session_id") or ""),
                "course_code": str(ligne.get("course_code") or ""),
                "event_id": celcat.get("event_id"),
                "groupe": celcat.get("groupe"),
                "raison": raison,
                "explication": explication,
            }
        )

    for ligne in lignes_comparaison:
        statut = ligne.get("statut")
        if statut in ("identique", "hors_celcat"):
            continue
        session_id = str(ligne.get("session_id") or "")
        celcat = ligne.get("celcat") or {}

        if statut == "ecart":
            if not celcat.get("event_id"):
                # Un écart suppose un évènement en face ; sans identifiant on
                # ne peut ni le modifier, ni le recréer sans risquer un double.
                _abandonner(
                    ligne,
                    "event_id_absent",
                    "l'évènement Celcat n'a pas d'identifiant : rien à modifier, "
                    "et le créer poserait un doublon",
                )
                continue
            jobs.append({
                "action": "update", "session_id": session_id,
                "event_id": int(celcat["event_id"]), "semaine": semaine,
            })
        elif statut == "absente_celcat":
            jobs.append({"action": "create", "session_id": session_id, "semaine": semaine})
        elif statut == "en_trop_celcat":
            if not celcat.get("event_id"):
                _abandonner(
                    ligne,
                    "event_id_absent",
                    "l'évènement Celcat n'a pas d'identifiant : impossible à supprimer",
                )
                continue
            if not avec_suppressions:
                _abandonner(
                    ligne,
                    "suppression_epargnee",
                    "suppression laissée de côté : une suppression ne se rattrape pas",
                )
                continue
            # `group_id` est indispensable : la suppression localise
            # l'évènement par son groupe, un job sans lui resterait en file
            # sans jamais pouvoir être traité.
            gid = group_id_pour_nom(str(celcat.get("groupe") or ""))
            if gid is None:
                nom = str(celcat.get("groupe") or "?")
                _abandonner(
                    ligne,
                    "groupe_inconnu",
                    f"le groupe « {nom} » manque à data/config/celcat_groupes.yaml : "
                    "la suppression ne pourrait pas être localisée",
                )
                continue
            jobs.append({
                "action": "delete",
                "session_id": session_id or f"celcat-{celcat['event_id']}",
                "event_id": int(celcat["event_id"]), "group_id": gid, "semaine": semaine,
            })
    return jobs
