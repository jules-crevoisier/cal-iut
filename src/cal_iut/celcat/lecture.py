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
    # TOUTES les salles de l'évènement. `salle` reste la première — tout le
    # code de rapprochement s'en sert et le changer d'un coup le ferait
    # diverger — mais un cours posé sur DEUX salles doit pouvoir se voir.
    salles: list[str] = field(default_factory=list)

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


def _tous_les_noms(valeurs: object, *cles: str) -> list[str]:
    """TOUS les noms d'une liste de ressources, pas seulement le premier.

    Un évènement Celcat peut porter plusieurs salles : sur l'interface, on
    change de salle soit par le bouton de retrait, soit en glissant la
    nouvelle avec Maj — sans quoi elle s'AJOUTE à l'ancienne. Le cours se
    retrouve alors sur deux salles à la fois (signalé par Kyllian Bresson le
    08/09/2026 : « Thomas Castellengo est sur deux salles »).

    `_premier_nom` ne rapportait que la tête, si bien qu'un tel évènement
    nous paraissait normal — et l'écran affirmait « identique » dessus.
    """
    if not isinstance(valeurs, list):
        return []
    noms: list[str] = []
    for item in valeurs:
        if not isinstance(item, dict):
            texte = str(item).strip()
            if texte:
                noms.append(texte)
            continue
        for cle in cles:
            val = item.get(cle)
            if val not in (None, ""):
                noms.append(str(val))
                break
    return noms


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


# Tolérance de rapprochement entre une heure Celcat et une heure cal-iut.
# Celcat pose ses horaires sur la date pivot du 31/12/1899 (convention
# Delphi) : sérialisés en UTC, ils portent le fuseau HISTORIQUE de Paris,
# celui d'avant l'adoption de GMT en 1911 — `UTC+00:09:21`. Notre 14h00
# s'y lit donc « 13:50 », et notre 15h30 « 15:20 » (vérifié à la seconde
# près le 08/09/2026 sur le CM de Régis Huez).
#
# Une tolérance plutôt qu'une conversion de fuseau : deux créneaux
# consécutifs sont espacés de 90 minutes, donc un quart d'heure d'écart ne
# peut désigner que le même créneau — et cela reste vrai si l'établissement
# décale ses horaires de dix minutes, là où une conversion codée en dur
# deviendrait fausse sans prévenir.
TOLERANCE_CRENEAU_MINUTES = 15


def _minutes(heure: str) -> int | None:
    morceaux = str(heure or "").split(":")
    if len(morceaux) < 2:
        return None
    try:
        return int(morceaux[0]) * 60 + int(morceaux[1])
    except ValueError:
        return None


def meme_creneau(heure_celcat: str, heure_caliut: str) -> bool:
    """Ces deux heures désignent-elles le même créneau ?

    Comparer les chaînes avec `!=` — ce que faisait `ops.correspond_live` —
    échouait pour TOUTES les séances à cause du décalage ci-dessus : un
    évènement Celcat parfaitement à sa place n'était jamais reconnu, et se
    retrouvait signalé comme « extra » à trancher à la main.

    Une heure absente ou illisible ne correspond à rien : un évènement
    fantôme ne doit pas se rapprocher de n'importe quelle séance.
    """
    a, b = _minutes(heure_celcat), _minutes(heure_caliut)
    if a is None or b is None:
        return False
    return abs(a - b) <= TOLERANCE_CRENEAU_MINUTES


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
        salles=_tous_les_noms(brut.get("rooms"), "name", "unique_name"),
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
    """Position d'un lundi dans le masque `weeks` de Celcat.

    Compte les semaines ÉCOULÉES depuis le lundi de référence, et non la
    différence de deux numéros ISO — parce que la numérotation ISO repart à
    1 au 1er janvier :

        lundi 2026-12-14  ->  ISO 51  ->  51 - 34 =  17   correct
        lundi 2027-01-04  ->  ISO  1  ->   1 - 34 = -33   négatif

    Un indice négatif fait lever `masquer_semaine`, `_masque_pour` encaisse
    l'exception et retombe sur un masque vide, et l'écriture est alors
    refusée sur « masque semaines 0×Y ». AUCUNE séance de janvier à juin
    2027 ne pouvait donc partir dans Celcat — toute la seconde moitié de
    l'année universitaire, sans que rien ne le dise (trouvé le 08/09/2026 en
    remontant les échecs du worker).

    L'année de référence se déduit du lundi lui-même : une semaine ISO
    inférieure à `premiere_semaine_celcat` appartient forcément à l'année
    universitaire commencée l'année civile précédente. Une différence de
    dates, elle, ne connaît pas le 1er janvier.
    """
    annee_iso, semaine_iso, _ = lundi.isocalendar()
    annee_reference = annee_iso if semaine_iso >= premiere_semaine_celcat else annee_iso - 1
    lundi_reference = date.fromisocalendar(annee_reference, premiere_semaine_celcat, 1)
    return (lundi - lundi_reference).days // 7


def premiere_semaine_depuis_infobulle(texte: str) -> int | None:
    m = _INFOBULLE_SEMAINE.search(texte)
    return int(m.group(1)) if m else None
