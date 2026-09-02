"""Diff cal-iut ↔ Celcat Live : créer les manquants, jamais supprimer."""

from __future__ import annotations

from dataclasses import dataclass, field

from cal_iut.celcat.lecture import (
    EvenementCelcat,
    est_cours,
    est_fantome,
    est_ferie,
    sur_la_semaine,
)
from cal_iut.celcat.mapping import EntreeCelcat


@dataclass(frozen=True)
class ClefDiff:
    module: str
    groupe: str
    salle: str
    indice_semaine: int
    jour: int
    heure_debut: str


@dataclass
class PlanEcriture:
    a_creer: list[EntreeCelcat] = field(default_factory=list)
    deja_la: list[tuple[EntreeCelcat, EvenementCelcat]] = field(default_factory=list)
    a_modifier: list[tuple[EntreeCelcat, EvenementCelcat]] = field(default_factory=list)
    a_supprimer: list[EvenementCelcat] = field(default_factory=list)
    ambigu: list[EntreeCelcat] = field(default_factory=list)
    bloquees: list[EntreeCelcat] = field(default_factory=list)
    celcat_en_plus: list[EvenementCelcat] = field(default_factory=list)
    fantomes: list[EvenementCelcat] = field(default_factory=list)
    feries: list[EvenementCelcat] = field(default_factory=list)


def _module_entree(e: EntreeCelcat) -> str:
    return (e.course_code or e.code_module or "").strip().upper()


def _modules_compatibles(e: EntreeCelcat, ev: EvenementCelcat) -> bool:
    code = _module_entree(e)
    if not code:
        return False
    nom = (ev.module_nom or "").upper()
    unique = (ev.module_code or "").upper()
    if e.code_module and unique == e.code_module.upper():
        return True
    return nom.startswith(code)


def _groupe_compatibles(e: EntreeCelcat, ev: EvenementCelcat) -> bool:
    voulu = e.nom_groupe_celcat.strip().upper()
    vu = ev.groupe_nom.strip().upper()
    return voulu == vu or vu.startswith(voulu)


def _salle_compatibles(e: EntreeCelcat, ev: EvenementCelcat) -> bool:
    a = (e.salle or "").strip().upper()
    b = (ev.salle or "").strip().upper()
    if a == b:
        return True
    # Live raccourcit parfois « Amphi 3 MMI » en « Amphi 3 ».
    if "AMPHI" in a and "AMPHI" in b:
        morceaux_a = a.replace("MMI", "").split()
        morceaux_b = b.replace("MMI", "").split()
        return morceaux_a[:2] == morceaux_b[:2]
    return False


def _heure_compatibles(e: EntreeCelcat, ev: EvenementCelcat) -> bool:
    if not ev.heure_debut:
        return True
    return ev.heure_debut == e.heure_debut


def _apparie(e: EntreeCelcat, ev: EvenementCelcat, indice: int) -> bool:
    """Identité = module + groupe + créneau (pas la salle)."""
    if ev.protected == "Y":
        return False
    if not sur_la_semaine(ev, indice):
        return False
    if not est_cours(ev):
        return False
    return (
        _modules_compatibles(e, ev)
        and _groupe_compatibles(e, ev)
        and ev.jour == e.jour
        and _heure_compatibles(e, ev)
    )


def comparer(
    entrees: list[EntreeCelcat],
    evenements: list[EvenementCelcat],
    *,
    indice_semaine: int,
) -> PlanEcriture:
    plan = PlanEcriture()
    sur_semaine = [ev for ev in evenements if sur_la_semaine(ev, indice_semaine)]
    for ev in sur_semaine:
        if est_ferie(ev):
            plan.feries.append(ev)
        elif est_fantome(ev):
            plan.fantomes.append(ev)

    apparies: set[int] = set()
    for e in entrees:
        if not e.prete:
            plan.bloquees.append(e)
            continue
        hits = [ev for ev in sur_semaine if _apparie(e, ev, indice_semaine)]
        if len(hits) == 0:
            plan.a_creer.append(e)
        elif len(hits) == 1:
            # Salle OU catégorie (CM saisi en [TP], etc.) → update, pas « déjà là ».
            from cal_iut.celcat.categories import categorie_live_coherente

            cat_ok = categorie_live_coherente(e.type_seance_nom, hits[0].categorie)
            if _salle_compatibles(e, hits[0]) and cat_ok:
                plan.deja_la.append((e, hits[0]))
            else:
                plan.a_modifier.append((e, hits[0]))
            apparies.add(hits[0].event_id)
        else:
            plan.ambigu.append(e)
            apparies.update(ev.event_id for ev in hits)

    for ev in sur_semaine:
        if not est_cours(ev) or ev.protected == "Y":
            continue
        if ev.event_id not in apparies:
            plan.celcat_en_plus.append(ev)
    return plan
