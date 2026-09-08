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


def lignes(
    state: Any, *, semaine: int, semaine_celcat: int, evenements: list[dict],
    ctx: ContexteComparaison | None = None,
) -> list[dict]:
    """Le verdict séance par séance pour une semaine."""
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
    )


def jobs_depuis_lignes(
    lignes_comparaison: list[dict], *, semaine: int, group_id_pour_nom: Any
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
    """
    jobs: list[dict[str, Any]] = []
    for ligne in lignes_comparaison:
        statut = ligne.get("statut")
        if statut in ("identique", "hors_celcat"):
            continue
        session_id = str(ligne.get("session_id") or "")
        celcat = ligne.get("celcat") or {}

        if statut == "ecart" and celcat.get("event_id"):
            jobs.append({
                "action": "update", "session_id": session_id,
                "event_id": int(celcat["event_id"]), "semaine": semaine,
            })
        elif statut == "absente_celcat":
            jobs.append({"action": "create", "session_id": session_id, "semaine": semaine})
        elif statut == "en_trop_celcat" and celcat.get("event_id"):
            # `group_id` est indispensable : la suppression localise
            # l'évènement par son groupe, un job sans lui resterait en file
            # sans jamais pouvoir être traité.
            gid = group_id_pour_nom(str(celcat.get("groupe") or ""))
            if gid is None:
                continue
            jobs.append({
                "action": "delete",
                "session_id": session_id or f"celcat-{celcat['event_id']}",
                "event_id": int(celcat["event_id"]), "group_id": gid, "semaine": semaine,
            })
    return jobs
