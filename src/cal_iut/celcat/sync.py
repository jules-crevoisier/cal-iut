"""Ce qui a déjà été saisi dans Celcat, et ce qui reste à y faire.

Retour utilisateur 29/08/2026 : « le but étant que si l'on modifie le
planning de semaines déjà envoyées sur Celcat, cela modifie dessus
automatiquement ». Il ne s'agit donc pas d'un export à sens unique mais
d'une SYNCHRONISATION : à chaque lancement, l'outil doit savoir dire, pour
chaque séance, si elle est nouvelle, inchangée, modifiée, ou supprimée
depuis le dernier envoi.

Le journal (`data/state/celcat_sync.json`, volume persistant — cf.
`api/state.py::DB_PATH` pour la séparation config/état) associe chaque
`session_id` à la SIGNATURE de ce qui a été saisi là-bas
(`mapping.EntreeCelcat.signature`). Comparer la signature courante à celle
journalisée suffit à classer chaque séance, sans jamais relire Celcat — ce
qui serait de toute façon impossible : l'utilisateur n'y a pas d'accès en
lecture programmatique, c'est tout le problème d'origine.

Conséquence assumée : le journal reflète ce que NOUS avons saisi, pas
l'état réel de Celcat. Une modification faite à la main directement dans
Celcat passe donc inaperçue. C'est le seul compromis possible sans API, et
il vaut mieux qu'il soit écrit ici que découvert plus tard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cal_iut.celcat.mapping import EntreeCelcat


def _path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state" / "celcat_sync.json"


def _load() -> dict[str, dict[str, str]]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # Journal illisible = on repart de zéro. Le pire scénario est de
        # re-saisir des séances déjà présentes, jamais d'en perdre.
        return {}


def _save(data: dict[str, dict[str, str]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def journal() -> dict[str, dict[str, str]]:
    return _load()


def marquer_saisi(entree: EntreeCelcat) -> None:
    data = _load()
    data[entree.session_id] = {
        "signature": entree.signature(),
        "saisi_le": datetime.now(timezone.utc).isoformat(),
        "semaine": str(entree.semaine),
    }
    _save(data)


def marquer_supprime(session_id: str) -> None:
    data = _load()
    if session_id in data:
        del data[session_id]
        _save(data)


@dataclass
class PlanSync:
    """Ce qu'il y aurait à faire dans Celcat, sans rien y avoir touché."""

    a_creer: list[EntreeCelcat] = field(default_factory=list)
    a_modifier: list[EntreeCelcat] = field(default_factory=list)
    inchangees: list[EntreeCelcat] = field(default_factory=list)
    # Séances saisies dans Celcat qui n'existent plus chez nous (déplacées
    # hors de la fenêtre, supprimées) : elles doivent être RETIRÉES là-bas,
    # sinon Celcat garde des cours fantômes — et paie potentiellement des
    # heures qui n'ont pas lieu.
    a_supprimer: list[str] = field(default_factory=list)
    # Non saisissables en l'état (code manquant, etc.), avec leur motif.
    bloquees: list[EntreeCelcat] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return len(self.a_creer) + len(self.a_modifier) + len(self.a_supprimer)

    def resume(self) -> str:
        if self.bloquees:
            manque = sorted({b for e in self.bloquees for b in e.bloquants})
            debut = (
                f"{len(self.bloquees)} séance(s) non saisissable(s) — à corriger avant : "
                + " ; ".join(manque[:3])
                + ("…" if len(manque) > 3 else "")
            )
        else:
            debut = ""
        actions = (
            f"{len(self.a_creer)} à créer, {len(self.a_modifier)} à modifier, "
            f"{len(self.a_supprimer)} à supprimer, {len(self.inchangees)} inchangée(s)"
        )
        return f"{debut}. {actions}." if debut else actions + "."


def construire_plan(entrees: list[EntreeCelcat], semaines: set[int]) -> PlanSync:
    """Compare les entrées voulues au journal, pour les semaines demandées.

    `semaines` borne la comparaison : sans elle, toute séance des semaines
    NON traitées cette fois serait vue comme « à supprimer » simplement
    parce qu'elle n'est pas dans le lot courant.
    """
    plan = PlanSync()
    deja = journal()
    vus: set[str] = set()

    for e in entrees:
        if e.semaine not in semaines:
            continue
        vus.add(e.session_id)
        if not e.prete:
            plan.bloquees.append(e)
            continue
        precedent = deja.get(e.session_id)
        if precedent is None:
            plan.a_creer.append(e)
        elif precedent.get("signature") != e.signature():
            plan.a_modifier.append(e)
        else:
            plan.inchangees.append(e)

    for session_id, info in deja.items():
        if session_id in vus:
            continue
        try:
            semaine = int(info.get("semaine", -1))
        except (TypeError, ValueError):
            continue
        if semaine in semaines:
            plan.a_supprimer.append(session_id)

    return plan
