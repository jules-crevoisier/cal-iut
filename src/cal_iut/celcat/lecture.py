"""Événements Celcat Live, extraits d'un `udlTimetables.load`."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

_INFOBULLE_SEMAINE = re.compile(r"Week:\s*(\d+)", re.I)


@dataclass
class EvenementCelcat:
    event_id: int
    jour: int
    heure_debut: str
    heure_fin: str
    weeks: str
    categorie: str
    module_nom: str
    module_code: str
    salle: str
    enseignant: str
    group_id: int
    groupe_nom: str
    protected: str
    global_event: str
    brut: dict = field(repr=False)
    event_cat_id: int | None = None
    module_id: int | None = None
    salle_id: int | None = None
    staff_id: int | None = None
    dept_id: int | None = None
    suspended: str = "N"

    @property
    def indice_semaine(self) -> int | None:
        if self.weeks.count("Y") != 1:
            return None
        return self.weeks.index("Y")


def _premier_id(valeurs: object) -> int | None:
    if not isinstance(valeurs, list) or not valeurs:
        return None
    tete = valeurs[0]
    if not isinstance(tete, dict):
        return None
    for cle in ("id", "module_id", "room_id", "staff_id", "group_id"):
        if tete.get(cle) is not None:
            try:
                return int(tete[cle])
            except (TypeError, ValueError):
                return None
    return None


def _premier_nom(valeurs: object, *cles: str) -> str:
    if not isinstance(valeurs, list) or not valeurs:
        return ""
    tete = valeurs[0]
    if not isinstance(tete, dict):
        return str(tete)
    for cle in cles:
        val = tete.get(cle)
        if val not in (None, ""):
            return str(val)
    return ""


def _heure(valeur: object) -> str:
    if valeur is None or valeur == "":
        return ""
    if isinstance(valeur, bool):
        return ""
    if isinstance(valeur, (int, float)):
        total = int(valeur)
        if total > 24 * 60:
            total //= 60
        return f"{total // 60:02d}:{total % 60:02d}"
    if isinstance(valeur, str) and "T" in valeur:
        return valeur.split("T", 1)[1][:5]
    texte = str(valeur)
    if " " in texte and ":" in texte.split(" ", 1)[1]:
        return texte.split(" ", 1)[1][:5]
    if ":" in texte:
        return texte[:5]
    return ""


def _sans_cohorte(nom: str) -> str:
    return re.sub(r"\s+-\s+\d{4}\s*$", "", nom).strip()


def evenement_depuis_rpc(
    brut: dict, *, group_id: int, groupe_nom: str
) -> EvenementCelcat:
    groupes = brut.get("groups") if isinstance(brut.get("groups"), list) else []
    nom_groupe = _sans_cohorte(_premier_nom(groupes, "name", "unique_name")) or groupe_nom
    gid = _premier_id(groupes) or group_id
    return EvenementCelcat(
        event_id=int(brut.get("event_id") or brut.get("id") or 0),
        jour=int(brut["day_of_week"]) + 1 if brut.get("day_of_week") not in (None, "") else 0,
        heure_debut=_heure(brut.get("start_time")),
        heure_fin=_heure(brut.get("end_time")),
        weeks=str(brut.get("weeks") or ""),
        categorie=str(brut.get("evCatName") or ""),
        module_nom=_premier_nom(brut.get("modules"), "name", "unique_name"),
        module_code=_premier_nom(brut.get("modules"), "unique_name", "name"),
        salle=_premier_nom(brut.get("rooms"), "name", "unique_name"),
        enseignant=_premier_nom(brut.get("staff"), "name", "unique_name"),
        group_id=gid,
        groupe_nom=nom_groupe,
        protected=str(brut.get("protected") or "N"),
        global_event=str(brut.get("global_event") or "N"),
        brut=brut,
        event_cat_id=int(brut["event_cat_id"]) if brut.get("event_cat_id") is not None else None,
        module_id=_premier_id(brut.get("modules")),
        salle_id=_premier_id(brut.get("rooms")),
        staff_id=_premier_id(brut.get("staff")),
        dept_id=int(brut["dept_id"]) if brut.get("dept_id") is not None else None,
        suspended=str(brut.get("suspended") or "N"),
    )


def sur_la_semaine(ev: EvenementCelcat, indice: int) -> bool:
    if indice < 0 or indice >= len(ev.weeks):
        return False
    return ev.weeks[indice] == "Y"


def est_ferie(ev: EvenementCelcat) -> bool:
    cat = unicodedata.normalize("NFD", ev.categorie)
    cat = cat.encode("ascii", "ignore").decode().casefold()
    return "ferie" in cat


def est_fantome(ev: EvenementCelcat) -> bool:
    if est_ferie(ev):
        return False
    return not ev.module_nom and not ev.heure_debut and not ev.heure_fin


def est_cours(ev: EvenementCelcat) -> bool:
    """Un vrai CM/TD/TP — jamais une réservation administrative (Conférence,
    Réunion, Jury, Jour férié, Réservation BU…). Repéré le 05/09/2026 :
    ces catégories-là ont un `salle`/`heure_debut` (donc passaient le filtre
    d'avant) mais aucun module ni enseignant — Celcat les affiche comme
    « en plus » à chaque comparaison sans que ce soit jamais un vrai écart,
    juste un booking hors du périmètre cours de cal-iut. Toutes les
    catégories de cours (relevé complet du 04/09/2026, 38 catégories) sont
    encadrées de crochets — `[CM]`/`[TD]`/`[TP]` et leurs variantes
    bénévole/capacité — aucune catégorie administrative ne l'est."""
    if est_ferie(ev) or est_fantome(ev):
        return False
    if not ev.categorie.strip().startswith("["):
        return False
    return bool(ev.module_nom or ev.heure_debut or ev.salle)


def indice_depuis_lundi(lundi: date, *, premiere_semaine_celcat: int) -> int:
    return lundi.isocalendar().week - premiere_semaine_celcat


def premiere_semaine_depuis_infobulle(texte: str) -> int | None:
    m = _INFOBULLE_SEMAINE.search(texte)
    return int(m.group(1)) if m else None
