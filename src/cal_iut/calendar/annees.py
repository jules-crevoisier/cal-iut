"""Années universitaires (lot 7 du chantier « paramètres dans l'interface »,
17/11/2026).

Jusqu'ici l'application ne connaissait qu'une année : 2026-2027, écrite
dans `calendar/academic.py` (rentrée, fin des cours) et dans
`contraintes/02_calendrier_iut.json` (vacances, fériés). Ce module décrit
une année par ses dates, et sait en préparer d'autres depuis l'écran.

Une année, c'est :

    {"label": "2027-2028",
     "rentree": "2027-08-30",      # premier jour de cours de l'impair
     "fin_impair": "2028-01-28",   # dernier jour de cours de l'impair
     "debut_pair": "2028-01-31",   # premier jour de cours du pair
     "fin": "2028-06-30",          # dernier jour de cours du pair
     "vacances": [{"nom": "Toussaint", "debut": "…", "fin": "…"}, …],
     "feries": [{"date": "2027-11-11", "nom": "Armistice 1918"}, …]}

L'année d'origine se lit dans les fichiers livrés et ne se modifie pas : le
planning en service est daté avec elle (les placements sont des numéros de
semaine, pas des dates). Les autres années sont saisies à l'écran et
rangées dans `data/state/reglages.json` (réglage `annees`).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from cal_iut.calendar import academic
from cal_iut.calendar.academic import AcademicCalendar

ORIGINE = "2026-2027"
_LABEL = re.compile(r"^(20\d\d)-(20\d\d)$")


class AnneeInvalide(ValueError):
    """Saisie refusée, avec un message à afficher tel quel."""


def _paques(annee: int) -> date:
    """Dimanche de Pâques (algorithme de Meeus, calendrier grégorien)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mois = (h + m - 7 * n + 114) // 31
    jour = (h + m - 7 * n + 114) % 31 + 1
    return date(annee, mois, jour)


def feries_legaux(annee_civile: int) -> dict[date, str]:
    """Les onze jours fériés légaux en France pour une année civile."""
    paques = _paques(annee_civile)
    return {
        date(annee_civile, 1, 1): "Jour de l'an",
        paques + timedelta(days=1): "Lundi de Pâques",
        date(annee_civile, 5, 1): "Fête du Travail",
        date(annee_civile, 5, 8): "Victoire 1945",
        paques + timedelta(days=39): "Ascension",
        paques + timedelta(days=50): "Lundi de Pentecôte",
        date(annee_civile, 7, 14): "Fête nationale",
        date(annee_civile, 8, 15): "Assomption",
        date(annee_civile, 11, 1): "Toussaint",
        date(annee_civile, 11, 11): "Armistice 1918",
        date(annee_civile, 12, 25): "Noël",
    }


def bornes(label: str) -> tuple[int, int]:
    """« 2027-2028 » -> (2027, 2028)."""
    m = _LABEL.match(str(label))
    if not m or int(m.group(2)) != int(m.group(1)) + 1:
        raise AnneeInvalide("Une année universitaire s'écrit « 2027-2028 ».")
    return int(m.group(1)), int(m.group(2))


def suivante(label: str) -> str:
    debut, fin = bornes(label)
    return f"{debut + 1}-{fin + 1}"


def feries_proposes(label: str) -> list[dict]:
    """Les fériés légaux qui tombent un jour de semaine entre le 25 août et
    le 14 juillet de l'année universitaire."""
    debut, fin = bornes(label)
    tous = {**feries_legaux(debut), **feries_legaux(fin)}
    return [
        {"date": d.isoformat(), "nom": nom}
        for d, nom in sorted(tous.items())
        if date(debut, 8, 25) <= d <= date(fin, 7, 14) and d.weekday() < 5
    ]


def _lundi(jour: date) -> date:
    return jour - timedelta(days=jour.weekday())


def proposition(label: str) -> dict:
    """Une année à compléter : les fériés sont calculés, les dates de
    semestre reprennent le rythme de l'année d'origine, les vacances restent
    à saisir (elles changent chaque année)."""
    debut, fin = bornes(label)
    rentree = _lundi(date(debut, 9, 1))  # le lundi de la semaine du 1er septembre
    debut_pair = _lundi(date(fin, 2, 1))
    if debut_pair < date(fin, 2, 1) and date(fin, 2, 1).weekday() >= 5:
        debut_pair += timedelta(days=7)
    return {
        "label": label,
        "rentree": rentree.isoformat(),
        "fin_impair": (debut_pair - timedelta(days=3)).isoformat(),
        "debut_pair": debut_pair.isoformat(),
        "fin": date(fin, 6, 30).isoformat(),
        "vacances": [{"nom": nom, "debut": "", "fin": ""} for nom in ("Toussaint", "Noël", "Hiver", "Printemps")],
        "feries": feries_proposes(label),
    }


def annee_d_origine() -> dict:
    """2026-2027, telle que l'application la lit depuis toujours."""
    charge = academic._load_holidays_and_pauses_from_source(academic._CALENDAR_SOURCE_PATH)
    feries, pauses = charge if charge is not None else academic._fallback_holidays_and_pauses()
    feries = set(feries) | academic._CONFIRMED_EXTRA_HOLIDAYS
    noms = {**feries_legaux(2026), **feries_legaux(2027)}
    impair, pair = academic.PERIODES_D_ORIGINE["odd"], academic.PERIODES_D_ORIGINE["even"]
    return {
        "label": ORIGINE,
        "rentree": impair[0].isoformat(),
        "fin_impair": impair[1].isoformat(),
        "debut_pair": pair[0].isoformat(),
        "fin": pair[1].isoformat(),
        "vacances": [
            {"nom": "Vacances ou pause pédagogique", "debut": d.isoformat(), "fin": f.isoformat()}
            for d, f in sorted(pauses)
        ],
        "feries": [{"date": d.isoformat(), "nom": noms.get(d, "Jour férié")} for d in sorted(feries)],
    }


def _date(valeur: object, quoi: str) -> date:
    try:
        return date.fromisoformat(str(valeur))
    except ValueError:
        raise AnneeInvalide(f"{quoi} : la date n'est pas valide.") from None


def valider(label: str, donnees: dict) -> dict:
    """L'année saisie, nettoyée. Lève `AnneeInvalide` avec un message clair."""
    debut, fin = bornes(label)
    if label == ORIGINE:
        raise AnneeInvalide(
            f"L'année {ORIGINE} est celle du planning en service : ses dates ne se modifient pas ici."
        )
    rentree = _date(donnees.get("rentree"), "Rentrée")
    fin_impair = _date(donnees.get("fin_impair"), "Fin du semestre impair")
    debut_pair = _date(donnees.get("debut_pair"), "Début du semestre pair")
    fin_cours = _date(donnees.get("fin"), "Fin des cours")
    if not rentree < fin_impair < debut_pair < fin_cours:
        raise AnneeInvalide(
            "Les dates doivent se suivre : rentrée, fin du semestre impair, début du semestre pair, fin des cours."
        )
    if not date(debut, 8, 1) <= rentree <= date(debut, 10, 31):
        raise AnneeInvalide(f"La rentrée de {label} tombe entre août et octobre {debut}.")
    if not date(fin, 4, 1) <= fin_cours <= date(fin, 8, 31):
        raise AnneeInvalide(f"La fin des cours de {label} tombe entre avril et août {fin}.")
    if rentree.weekday() > 4 or debut_pair.weekday() > 4:
        raise AnneeInvalide("La rentrée et le début du semestre pair sont des jours de semaine.")

    vacances = []
    for v in donnees.get("vacances") or []:
        if not v.get("debut") and not v.get("fin"):
            continue  # ligne laissée vide
        nom = str(v.get("nom") or "").strip()[:60] or "Vacances"
        d, f = _date(v.get("debut"), nom), _date(v.get("fin"), nom)
        if d > f:
            raise AnneeInvalide(f"{nom} : le début est après la fin.")
        if (f - d).days > 31:
            raise AnneeInvalide(f"{nom} : une période de vacances ne dépasse pas un mois.")
        if d < rentree or f > fin_cours:
            raise AnneeInvalide(f"{nom} : la période sort de l'année de cours.")
        vacances.append({"nom": nom, "debut": d.isoformat(), "fin": f.isoformat()})
    vacances.sort(key=lambda v: v["debut"])
    for avant, apres in zip(vacances, vacances[1:]):
        if apres["debut"] <= avant["fin"]:
            raise AnneeInvalide(f"{avant['nom']} et {apres['nom']} se chevauchent.")

    feries: dict[str, str] = {}
    for jour in donnees.get("feries") or []:
        if not jour.get("date"):
            continue
        d = _date(jour.get("date"), "Jour férié")
        if not date(debut, 8, 1) <= d <= date(fin, 8, 31):
            raise AnneeInvalide(f"Le jour férié du {d.strftime('%d/%m/%Y')} n'est pas dans l'année {label}.")
        feries[d.isoformat()] = str(jour.get("nom") or "").strip()[:60] or "Jour férié"
    return {
        "label": label,
        "rentree": rentree.isoformat(), "fin_impair": fin_impair.isoformat(),
        "debut_pair": debut_pair.isoformat(), "fin": fin_cours.isoformat(),
        "vacances": vacances,
        "feries": [{"date": d, "nom": n} for d, n in sorted(feries.items())],
    }


def construire(annee: dict) -> AcademicCalendar:
    """Le calendrier d'une année : semaines de cours, jours bloqués, fériés.
    Même règle que `build_default_calendar_2026_2027` : une semaine compte
    dès qu'elle garde un jour de cours."""
    rentree, fin = date.fromisoformat(annee["rentree"]), date.fromisoformat(annee["fin"])
    feries = {date.fromisoformat(j["date"]) for j in annee.get("feries") or []}
    bloques = set(feries)
    for v in annee.get("vacances") or []:
        jour, dernier = date.fromisoformat(v["debut"]), date.fromisoformat(v["fin"])
        while jour <= dernier:
            bloques.add(jour)
            jour += timedelta(days=1)
    lundis = []
    curseur = _lundi(rentree)
    while curseur <= fin:
        if any(curseur + timedelta(days=i) not in bloques for i in range(5)):
            lundis.append(curseur)
        curseur += timedelta(days=7)
    return AcademicCalendar(
        year_label=annee["label"],
        teaching_mondays=lundis,
        blocked_dates=bloques,
        holidays=feries,
        notes=[f"Calendrier {annee['label']}"],
    )


def resume(annee: dict) -> dict:
    """Ce que l'écran montre d'une année : ses dates et ce qui en découle."""
    calendrier = construire(annee)
    fin_impair, debut_pair = date.fromisoformat(annee["fin_impair"]), date.fromisoformat(annee["debut_pair"])
    return {
        **annee,
        "semaines": calendrier.weeks,
        "semaines_impair": sum(1 for lundi in calendrier.teaching_mondays if lundi <= fin_impair),
        "semaines_pair": sum(1 for lundi in calendrier.teaching_mondays if lundi + timedelta(days=4) >= debut_pair),
    }


def periodes(annee: dict) -> dict[str, tuple[date, date]]:
    """Début et fin des cours de chaque groupe de semestres, pour cette année."""
    return {
        "odd": (date.fromisoformat(annee["rentree"]), date.fromisoformat(annee["fin_impair"])),
        "even": (date.fromisoformat(annee["debut_pair"]), date.fromisoformat(annee["fin"])),
    }


_cache_active: dict[tuple[str, int], dict | None] = {}


def active(config_dir: Path) -> dict | None:
    """L'année que l'application utilise à la place de celle d'origine, ou
    `None` tant que c'est l'année d'origine. Relu seulement quand le fichier
    des réglages change : la question est posée à chaque libellé de semaine."""
    from cal_iut.ingestion import reglages

    chemin = reglages._path(config_dir)
    try:
        cle = (str(chemin), chemin.stat().st_mtime_ns)
    except OSError:
        return None
    if cle not in _cache_active:
        en_cours = reglages.annee_en_cours(config_dir)
        annee = None
        if en_cours is not None and en_cours["label"] != ORIGINE:
            saisie = reglages.annees(config_dir).get(en_cours["label"])
            if saisie:
                annee = {**saisie, "label": en_cours["label"], "depuis": en_cours["depuis"]}
        _cache_active.clear()
        _cache_active[cle] = annee
    return _cache_active[cle]


def saisies(config_dir: Path) -> dict[str, dict]:
    from cal_iut.ingestion import reglages

    return reglages.annees(config_dir)


def toutes(config_dir: Path) -> list[dict]:
    """L'année d'origine, puis celles préparées à l'écran, dans l'ordre."""
    sortie = [{**annee_d_origine(), "origine": True}]
    for label, annee in sorted(saisies(config_dir).items()):
        if label != ORIGINE:
            sortie.append({**annee, "label": label, "origine": False})
    return sortie
