"""Réglages du quotidien modifiables depuis l'interface (lot 6 du chantier
« Nouveau semestre depuis l'interface », 16/11/2026).

Jusque-là, réserver une salle pour la Direction ou noter qu'un enseignant
est absent un matin demandait un développeur : un fichier de
`data/config/`, une PR, un déploiement. Et ce dossier fait partie de
l'image Docker : rien de ce qu'on y écrirait depuis le serveur ne
survivrait au déploiement suivant.

Ici, ce que l'administrateur saisit va dans `data/state/reglages.json`
(volume persistant, sauvegardé). Le fichier ne REMPLACE pas ceux du dépôt,
il les complète :

- `ajouts`   : les entrées saisies à l'écran ;
- `retraits` : les clés des entrées livrées avec l'application qu'on a
  retirées à l'écran.

Une entrée ajoutée plus tard dans le dépôt reste donc prise en compte.

Les chargeurs de `config_loader.py` appliquent ces réglages : le serveur,
l'audit, la génération et le solveur lisent la même chose sans rien savoir
de ce fichier.

Les réglages :

- `salles_reservees`  : complète `salles_reservees.yaml` ;
- `indisponibilites`  : indisponibilités d'un enseignant à une date et des
  créneaux précis, complète les `forbidden_date_slots` de
  `teacher_availability.yaml` ;
- `dates_sae`         : journées d'une SAE saisies à l'écran, ajoutées à
  celles de `contraintes/09_dates_sae.json` (le fichier officiel ne date
  pas les SAE de S2, S4 et S6) ;
- `seances_annulees`  : séances qui n'auront pas lieu, complète
  `seances_annulees.yaml` ;
- `doubles_seances`   : séances d'un module regroupées en blocs de 3 h ou
  4 h 30, complète `double_sessions.yaml` ;
- `periodes_modules`  : période imposée aux séances d'un module, complète
  les `session_date_windows` de `course_scheduling_rules.yaml`.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat

NOMS = ("salles_reservees", "indisponibilites", "dates_sae", "seances_annulees", "doubles_seances", "periodes_modules")
NB_CRENEAUX = 6

_verrou = threading.RLock()


def _path(config_dir: Path) -> Path:
    return config_dir.parents[1] / "data" / "state" / "reglages.json"


def _lire(config_dir: Path) -> dict[str, dict]:
    brut = lire_json_etat(_path(config_dir), {}, types=dict)
    sortie: dict[str, dict] = {}
    for nom in NOMS:
        bloc = brut.get(nom) if isinstance(brut.get(nom), dict) else {}
        sortie[nom] = {
            "ajouts": [a for a in bloc.get("ajouts") or [] if isinstance(a, dict)],
            "retraits": [str(r) for r in bloc.get("retraits") or []],
        }
    return sortie


def _creneaux(valeur: object) -> list[int]:
    return sorted({int(s) for s in (valeur or []) if 0 <= int(s) < NB_CRENEAUX})


# ── Clés : ce qui identifie une entrée livrée avec l'application ──────


def cle_reservation(entree: dict) -> str:
    creneaux = "".join(str(s) for s in _creneaux(entree.get("slots")))
    return f"{str(entree.get('salle')).strip().lower()}|{entree.get('date')}|{creneaux}"


def cle_indisponibilite(code: str, regle: dict) -> str:
    creneaux = "".join(str(s) for s in _creneaux(regle.get("slots")))
    return f"{code}|{regle.get('date')}|{creneaux}"


# ── Lecture : ce que les chargeurs appliquent ─────────────────────────


def reservations(config_dir: Path, livrees: list[dict] | None) -> list[dict]:
    """Les réservations de salles en vigueur : celles du dépôt, moins celles
    retirées à l'écran, plus celles saisies à l'écran. Chaque entrée porte
    `cle` et `origine` (« livree » ou « ajoutee »)."""
    bloc = _lire(config_dir)["salles_reservees"]
    retraits = set(bloc["retraits"])
    sortie = []
    for entree in livrees or []:
        cle = cle_reservation(entree)
        if cle not in retraits:
            sortie.append({**entree, "cle": cle, "origine": "livree"})
    sortie += [{**a, "cle": a["id"], "origine": "ajoutee"} for a in bloc["ajouts"] if a.get("id")]
    return sortie


def indisponibilites_ajoutees(config_dir: Path) -> list[dict]:
    return [a for a in _lire(config_dir)["indisponibilites"]["ajouts"] if a.get("id")]


def indisponibilites_retirees(config_dir: Path) -> set[str]:
    return set(_lire(config_dir)["indisponibilites"]["retraits"])


def appliquer_aux_enseignants(config_dir: Path, enseignants: list[dict]) -> list[dict]:
    """Applique les indisponibilités saisies à l'écran aux entrées BRUTES de
    `teacher_availability.yaml` (avant validation)."""
    bloc = _lire(config_dir)["indisponibilites"]
    if not bloc["ajouts"] and not bloc["retraits"]:
        return enseignants
    retraits = set(bloc["retraits"])
    sortie = []
    par_code: dict[str, dict] = {}
    for brut in enseignants:
        entree = dict(brut)
        code = str(entree.get("teacher_code"))
        regles = entree.get("forbidden_date_slots") or []
        if regles:
            entree["forbidden_date_slots"] = [
                r for r in regles if cle_indisponibilite(code, r) not in retraits
            ]
        sortie.append(entree)
        par_code.setdefault(code, entree)
    for ajout in bloc["ajouts"]:
        code = str(ajout.get("teacher_code") or "")
        if not code or not ajout.get("id"):
            continue
        entree = par_code.get(code)
        if entree is None:
            entree = {"teacher_code": code}
            par_code[code] = entree
            sortie.append(entree)
        entree["forbidden_date_slots"] = [
            *(entree.get("forbidden_date_slots") or []),
            {"date": ajout["date"], "slots": _creneaux(ajout.get("slots")), "note": ajout.get("motif")},
        ]
    return sortie


# ── Écriture ──────────────────────────────────────────────────────────


class ReglageInvalide(ValueError):
    """Saisie refusée, avec un message à afficher tel quel."""


def _valider_date(valeur: str) -> str:
    try:
        return date.fromisoformat(str(valeur)).isoformat()
    except ValueError as exc:
        raise ReglageInvalide("La date n'est pas valide.") from exc


def ajouter(config_dir: Path, nom: str, entree: dict, par: str) -> dict:
    """Enregistre une entrée saisie à l'écran et la renvoie avec son `id`."""
    if nom not in NOMS:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    creneaux = _creneaux(entree.get("slots"))
    if not creneaux:
        raise ReglageInvalide("Choisissez au moins un créneau.")
    motif = str(entree.get("motif") or "").strip()
    if not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    propre = {
        **{k: v for k, v in entree.items() if k not in ("id", "slots", "date", "motif")},
        "id": uuid.uuid4().hex[:12],
        "date": _valider_date(entree.get("date")),
        "slots": creneaux,
        "motif": motif[:300],
        "demande_par": par,
        "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        tout[nom]["ajouts"].append(propre)
        ecrire_json(_path(config_dir), tout)
    return propre


def retirer(config_dir: Path, nom: str, cle: str, *, livree: bool) -> bool:
    """Retire une entrée : supprime un ajout, ou note le retrait d'une entrée
    livrée avec l'application. Faux si rien ne correspond."""
    if nom not in NOMS:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout[nom]
        if livree:
            if cle in bloc["retraits"]:
                return False
            bloc["retraits"].append(cle)
        else:
            reste = [a for a in bloc["ajouts"] if a.get("id") != cle]
            if len(reste) == len(bloc["ajouts"]):
                return False
            bloc["ajouts"] = reste
        ecrire_json(_path(config_dir), tout)
    return True


# ── Dates des SAE ─────────────────────────────────────────────────────

MAX_DATES_SAE = 80


def dates_sae(config_dir: Path) -> dict[str, list[str]]:
    """Journées SAE saisies à l'écran : `{CODE: [dates ISO triées]}`."""
    sortie: dict[str, list[str]] = {}
    for ajout in _lire(config_dir)["dates_sae"]["ajouts"]:
        code = str(ajout.get("course_code") or "").strip().upper()
        dates = sorted({str(d) for d in ajout.get("dates") or []})
        if code and dates:
            sortie[code] = dates
    return sortie


def definir_dates_sae(config_dir: Path, code: str, dates: list[str], par: str) -> list[str]:
    """Remplace les journées saisies à l'écran pour cette SAE (liste vide :
    plus aucune). Renvoie les dates enregistrées."""
    code = str(code or "").strip().upper()
    if not code:
        raise ReglageInvalide("SAE inconnue.")
    propres = sorted({_valider_date(d) for d in dates or []})
    if len(propres) > MAX_DATES_SAE:
        raise ReglageInvalide(f"Trop de dates pour une seule SAE (maximum {MAX_DATES_SAE}).")
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout["dates_sae"]
        bloc["ajouts"] = [a for a in bloc["ajouts"] if str(a.get("course_code") or "").upper() != code]
        if propres:
            bloc["ajouts"].append({
                "id": uuid.uuid4().hex[:12],
                "course_code": code,
                "dates": propres,
                "demande_par": par,
                "le": datetime.now(timezone.utc).date().isoformat(),
            })
        ecrire_json(_path(config_dir), tout)
    return propres


# ── Séances annulées ──────────────────────────────────────────────────


def seances_annulees(config_dir: Path, livrees: list[dict]) -> list[dict]:
    """Les annulations en vigueur : celles livrées avec l'application, moins
    celles rétablies à l'écran, plus celles saisies à l'écran."""
    bloc = _lire(config_dir)["seances_annulees"]
    retraits = set(bloc["retraits"])
    sortie = [{**e, "origine": "livree"} for e in livrees if e["session_id"] not in retraits]
    connues = {e["session_id"] for e in sortie}
    for ajout in bloc["ajouts"]:
        session_id = str(ajout.get("session_id") or "").strip()
        if session_id and session_id not in connues:
            connues.add(session_id)
            sortie.append({
                "session_id": session_id,
                "motif": str(ajout.get("motif") or ""),
                "demande_par": str(ajout.get("demande_par") or ""),
                "le": str(ajout.get("le") or ""),
                "origine": "ajoutee",
            })
    return sortie


def annuler_seance(config_dir: Path, session_id: str, motif: str, par: str, *, livree: bool = False) -> None:
    """Note qu'une séance n'aura pas lieu. `livree` : l'annulation figure
    dans le fichier livré et avait été rétablie à l'écran, on lève ce
    rétablissement."""
    session_id = str(session_id or "").strip()
    motif = str(motif or "").strip()
    if not session_id:
        raise ReglageInvalide("Choisissez une séance.")
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout["seances_annulees"]
        if livree:
            bloc["retraits"] = [r for r in bloc["retraits"] if r != session_id]
        else:
            if not motif:
                raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
            bloc["ajouts"] = [a for a in bloc["ajouts"] if a.get("session_id") != session_id]
            bloc["ajouts"].append({
                "id": uuid.uuid4().hex[:12],
                "session_id": session_id,
                "motif": motif[:300],
                "demande_par": par,
                "le": datetime.now(timezone.utc).date().isoformat(),
            })
        ecrire_json(_path(config_dir), tout)


def retablir_seance(config_dir: Path, session_id: str, *, livree: bool) -> None:
    """La séance aura lieu de nouveau à la prochaine génération."""
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout["seances_annulees"]
        bloc["ajouts"] = [a for a in bloc["ajouts"] if a.get("session_id") != session_id]
        if livree and session_id not in bloc["retraits"]:
            bloc["retraits"].append(session_id)
        ecrire_json(_path(config_dir), tout)


# ── Règles de modules ─────────────────────────────────────────────────

REGLES_DE_MODULES = ("doubles_seances", "periodes_modules")
TYPES_DE_SEANCE = ("CM", "TD", "TP")


def regles_de_modules(config_dir: Path, nom: str) -> list[dict]:
    """Les règles saisies à l'écran pour ce réglage."""
    if nom not in REGLES_DE_MODULES:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    return [dict(a) for a in _lire(config_dir)[nom]["ajouts"] if a.get("course_code")]


def _type_de_seance(valeur: object, *, obligatoire: bool) -> str | None:
    texte = str(valeur or "").strip().upper()
    if not texte and not obligatoire:
        return None
    if texte not in TYPES_DE_SEANCE:
        raise ReglageInvalide("Choisissez le type de séance : CM, TD ou TP.")
    return texte


def ajouter_regle_de_module(config_dir: Path, nom: str, entree: dict, par: str) -> dict:
    """Enregistre une règle saisie à l'écran et la renvoie avec son `id`.

    `doubles_seances` : `course_code`, `session_type`, `slots_per_session`
    (2 = 3 h, 3 = 4 h 30). `periodes_modules` : `course_code`, `semestre`,
    `session_type` (facultatif), `debut` et/ou `fin`."""
    if nom not in REGLES_DE_MODULES:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    code = str(entree.get("course_code") or "").strip()
    if not code:
        raise ReglageInvalide("Choisissez un module.")
    motif = str(entree.get("motif") or "").strip()
    if not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    propre: dict = {"id": uuid.uuid4().hex[:12], "course_code": code}
    if nom == "doubles_seances":
        propre["session_type"] = _type_de_seance(entree.get("session_type"), obligatoire=True)
        try:
            creneaux = int(entree.get("slots_per_session") or 0)
        except (TypeError, ValueError):
            creneaux = 0
        if creneaux not in (2, 3):
            raise ReglageInvalide("Une séance longue dure 3 h ou 4 h 30.")
        propre["slots_per_session"] = creneaux
    else:
        propre["semestre"] = str(entree.get("semestre") or "").strip()
        propre["session_type"] = _type_de_seance(entree.get("session_type"), obligatoire=False)
        debut = _valider_date(entree["debut"]) if entree.get("debut") else None
        fin = _valider_date(entree["fin"]) if entree.get("fin") else None
        if not debut and not fin:
            raise ReglageInvalide("Indiquez au moins une date : le début ou la fin de la période.")
        if debut and fin and debut > fin:
            raise ReglageInvalide("Le début de la période est après sa fin.")
        propre["debut"], propre["fin"] = debut, fin
    propre.update(motif=motif[:300], demande_par=par, le=datetime.now(timezone.utc).date().isoformat())
    with _verrou:
        tout = _lire(config_dir)
        tout[nom]["ajouts"].append(propre)
        ecrire_json(_path(config_dir), tout)
    return propre


def retirer_regle_de_module(config_dir: Path, nom: str, identifiant: str) -> bool:
    if nom not in REGLES_DE_MODULES:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    return retirer(config_dir, nom, identifiant, livree=False)
