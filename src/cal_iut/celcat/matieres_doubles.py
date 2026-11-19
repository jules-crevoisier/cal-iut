"""Séances Celcat portant PLUSIEURS matières (tâche 34, 06/11/2026).

Avant le correctif de `modification._matieres_fusionnees`, changer la matière
d'une séance déjà exportée AJOUTAIT la nouvelle dans Celcat sans retirer
l'ancienne. Ce module liste ce qui reste : LECTURE SEULE, à partir du dernier
relevé du sidecar. Il n'écrit jamais dans Celcat — la réparation est une
décision de Jules, séparée.
"""

from __future__ import annotations

from typing import Any


def _distincts(valeurs: object) -> list[str]:
    vus: list[str] = []
    if isinstance(valeurs, list):
        for v in valeurs:
            v = str(v).strip()
            if v and v not in vus:
                vus.append(v)
    return vus


def lister(evenements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Évènements du relevé qui portent plus d'une matière distincte.

    Chaque ligne donne de quoi retrouver la séance : identifiant Celcat,
    groupe, jour, horaire, semaine, et les matières présentes. Les relevés
    sans champ `modules` (antérieurs au correctif) sont ignorés : ne pas
    savoir n'est pas constater une faute.
    """
    lignes: list[dict[str, Any]] = []
    for ev in evenements:
        modules = _distincts(ev.get("modules_codes")) or _distincts(ev.get("modules"))
        if len(modules) < 2:
            continue
        lignes.append(
            {
                "event_id": ev.get("event_id"),
                "groupe": ev.get("groupe"),
                "jour": ev.get("jour"),
                "heure_debut": ev.get("heure_debut"),
                "heure_fin": ev.get("heure_fin"),
                "semaine": ev.get("semaine"),
                "categorie": ev.get("categorie"),
                "modules": modules,
            }
        )
    lignes.sort(key=lambda l: (str(l["groupe"]), l["semaine"] if l["semaine"] is not None else -1,
                               str(l["jour"]), str(l["heure_debut"])))
    return lignes


def rapport(lignes: list[dict[str, Any]]) -> str:
    if not lignes:
        return "Aucune séance à plusieurs matières dans le dernier relevé."
    sortie = [f"{len(lignes)} séance(s) à plusieurs matières (lecture seule, rien n'est modifié) :"]
    for l in lignes:
        sortie.append(
            f"  #{l['event_id']}  {l['groupe']}  semaine {l['semaine']}  jour {l['jour']}  "
            f"{l['heure_debut']}-{l['heure_fin']}  {l['categorie']}  →  {' + '.join(l['modules'])}"
        )
    return "\n".join(sortie)
