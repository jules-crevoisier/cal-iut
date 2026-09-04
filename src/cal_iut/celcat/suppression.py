"""Supprimer une séance déjà posée dans Celcat, via RPC.

Même cause racine que `modification.py` : localiser l'événement d'abord,
jamais deviner. Le garde-fou (`file_attente.autoriser_suppression`) est
réévalué sur l'enregistrement FRAIS relu depuis Celcat, jamais sur
l'instantané porté par le job en file — un jour férié protégé bloque même
si le job a été mis en file avant que la protection ne soit visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cal_iut.celcat.ecriture import verifier_avant_envoi
from cal_iut.celcat.file_attente import autoriser_suppression
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.modification import EvenementIntrouvable, localiser_evenement
from cal_iut.celcat.navigateur import BASE_ENTRAINEMENT
from cal_iut.celcat.rpc import supprimer_evenement_rpc

__all__ = [
    "ElementSuppression",
    "ResultatSuppression",
    "SuppressionRefusee",
    "supprimer_evenement",
    "supprimer_manquants",
]


class SuppressionRefusee(PermissionError):
    """Le garde-fou `file_attente.autoriser_suppression` bloque la suppression."""


def supprimer_evenement(
    page,
    event_id: int,
    *,
    group_id: int,
    methode: str,
    base: str = BASE_ENTRAINEMENT,
    production_autorisee: bool = False,
) -> None:
    """Localise, revérifie sur le FRAIS, supprime. `EvenementIntrouvable`
    (déjà disparu) est un no-op idempotent, pas une erreur."""
    try:
        brut = localiser_evenement(page, event_id, group_ids=[group_id])
    except EvenementIntrouvable:
        return

    ev = evenement_depuis_rpc(brut, group_id=group_id, groupe_nom="")
    if not autoriser_suppression(ev):
        raise SuppressionRefusee(
            f"suppression refusée (garde-fou : jour férié protégé, fantôme, "
            f"protected=Y ou Celcat-en-plus) pour event_id={event_id}"
        )

    verifier_avant_envoi(brut, base=base, production_autorisee=production_autorisee)
    supprimer_evenement_rpc(page, event_id, methode=methode)
    return


@dataclass
class ElementSuppression:
    session_id: str
    event_id: int
    group_id: int


@dataclass
class ResultatSuppression:
    supprimees: list[str] = field(default_factory=list)
    refusees: list[tuple[str, str]] = field(default_factory=list)
    echecs: list[tuple[str, str]] = field(default_factory=list)


def supprimer_manquants(
    page,
    elements: list[ElementSuppression],
    *,
    methode: str,
    base: str = BASE_ENTRAINEMENT,
    production_autorisee: bool = False,
) -> ResultatSuppression:
    """Comme `ecriture.creer_manquants` : un échec isolé n'arrête pas le
    lot. Un refus de garde-fou (`SuppressionRefusee`) va dans `refusees`,
    toute autre exception (RPC/réseau) dans `echecs` — la distinction que
    `nuit.py` utilise pour décider quels jobs retirer de la file."""
    resultat = ResultatSuppression()
    for el in elements:
        try:
            supprimer_evenement(
                page,
                el.event_id,
                group_id=el.group_id,
                methode=methode,
                base=base,
                production_autorisee=production_autorisee,
            )
            resultat.supprimees.append(el.session_id)
            _notifier_celcat(
                "celcat_ok", f"{el.session_id} supprimé Celcat (event_id={el.event_id})"
            )
        except SuppressionRefusee as exc:
            resultat.refusees.append((el.session_id, str(exc)))
        except Exception as exc:  # noqa: BLE001
            resultat.echecs.append((el.session_id, str(exc)))
            _notifier_celcat("celcat_echec", f"{el.session_id} Celcat (suppression) : {exc}")
    return resultat


def _notifier_celcat(evenement: str, texte: str) -> None:
    """Mail optionnel — jamais faire échouer l'écriture Celcat."""
    try:
        from cal_iut.api import notifications

        notifications.signaler(evenement, texte)
        notifications.envoyer_si_temps_ecoule()
    except Exception:  # noqa: BLE001
        return
