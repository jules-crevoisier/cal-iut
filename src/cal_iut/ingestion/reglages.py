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
  les `session_date_windows` de `course_scheduling_rules.yaml` ;
- `dates_semestres`   : premier et dernier jour de cours d'un groupe de
  semestres, à la place des dates d'origine de `calendar/academic.py`.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat

NOMS = ("salles_reservees", "indisponibilites", "dates_sae", "seances_annulees", "doubles_seances", "periodes_modules", "dates_semestres",
    "repartitions", "ordres_enseignants", "duos", "fins_alternants", "parametres_calcul", "semaines_types", "sae_par_le_calcul", "phases_sae", "plafonds_hebdo", "effectifs", "salles", "regles_salles", "evenements_fixes", "presence_alternants", "cours_hors_maquette", "annees", "annee_en_cours",
    "disponibilites_exclusives", "modules_non_dispenses", "compacter_journee", "projets_modules",
)
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


def appliquer_aux_enseignants(
    config_dir: Path, enseignants: list[dict], *, sans_semaine_type: bool = False
) -> list[dict]:
    """Applique les indisponibilités saisies à l'écran (datées, puis semaine
    type) aux entrées BRUTES de `teacher_availability.yaml` (avant
    validation)."""
    tout = _lire(config_dir)
    bloc = tout["indisponibilites"]
    semaines = [] if sans_semaine_type else [a for a in tout["semaines_types"]["ajouts"] if a.get("teacher_code")]
    exclusives = [a for a in tout["disponibilites_exclusives"]["ajouts"] if a.get("teacher_code") and a.get("id")]
    compacts = {str(a["teacher_code"]) for a in tout["compacter_journee"]["ajouts"] if a.get("teacher_code")}
    if not bloc["ajouts"] and not bloc["retraits"] and not semaines and not exclusives and not compacts:
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
    for ajout in exclusives:
        code = str(ajout["teacher_code"])
        entree = par_code.get(code)
        if entree is None:
            entree = {"teacher_code": code}
            par_code[code] = entree
            sortie.append(entree)
        entree["forbidden_date_slots"] = [
            *(entree.get("forbidden_date_slots") or []),
            *dates_exclues(ajout),
        ]
    for code in sorted(compacts):
        entree = par_code.get(code)
        if entree is None:
            entree = {"teacher_code": code}
            par_code[code] = entree
            sortie.append(entree)
        entree["compacter_journee"] = True
    for ajout in semaines:
        code = str(ajout["teacher_code"])
        entree = par_code.get(code)
        if entree is None:
            entree = {"teacher_code": code}
            par_code[code] = entree
            sortie.append(entree)
        bloques, liberes = _cases(ajout.get("bloques")), _cases(ajout.get("liberes"))
        # `merge_teacher_availability` : (fichier ∪ feuille des contraintes) − annulés.
        interdits = {tuple(c) for c in entree.get("forbidden_slots") or []}
        annules = {tuple(c) for c in entree.get("cancelled_forbidden_slots") or []}
        entree["forbidden_slots"] = [list(c) for c in sorted((interdits | bloques) - liberes)]
        entree["cancelled_forbidden_slots"] = [list(c) for c in sorted((annules | liberes) - bloques)]
    return sortie


def dates_exclues(regle: dict) -> list[dict]:
    """Les indisponibilités (journée entière) que produit une règle « disponible
    uniquement à ces dates » : chaque jour de cours, du lundi au vendredi, de
    `debut` à `fin` inclus, qui ne figure pas dans `dates`."""
    try:
        debut, fin = date.fromisoformat(str(regle["debut"])), date.fromisoformat(str(regle["fin"]))
    except (KeyError, ValueError):
        return []
    gardees = {str(d) for d in regle.get("dates") or []}
    motif = str(regle.get("motif") or "")
    sortie = []
    jour = debut
    while jour <= fin:
        if jour.weekday() < 5 and jour.isoformat() not in gardees:
            sortie.append({"date": jour.isoformat(), "slots": list(range(NB_CRENEAUX)), "note": motif})
        jour += timedelta(days=1)
    return sortie


def _cases(valeur: object) -> set[tuple[int, int]]:
    """Des couples (jour 0-4, créneau 0-5) valides, sans doublon."""
    sortie: set[tuple[int, int]] = set()
    for case in valeur or []:
        try:
            jour, creneau = int(case[0]), int(case[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= jour <= 4 and 0 <= creneau < NB_CRENEAUX:
            sortie.add((jour, creneau))
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

REGLES_DE_MODULES = ("doubles_seances", "periodes_modules", "repartitions", "ordres_enseignants", "duos", "projets_modules")
MODES_DE_REPARTITION = ("alterne", "par_groupes", "sequentiel")
TYPES_DE_SEANCE = ("CM", "TD", "TP")


def regles_de_modules(config_dir: Path, nom: str) -> list[dict]:
    """Les règles saisies à l'écran pour ce réglage."""
    if nom not in REGLES_DE_MODULES:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    return [dict(a) for a in _lire(config_dir)[nom]["ajouts"] if a.get("course_code") or a.get("etapes")]


def _type_de_seance(valeur: object, *, obligatoire: bool) -> str | None:
    texte = str(valeur or "").strip().upper()
    if not texte and not obligatoire:
        return None
    if texte not in TYPES_DE_SEANCE:
        raise ReglageInvalide("Choisissez le type de séance : CM, TD ou TP.")
    return texte


def _codes(valeur: object) -> list[str]:
    return [str(c).strip().upper() for c in (valeur or []) if str(c).strip()]


def ajouter_regle_de_module(config_dir: Path, nom: str, entree: dict, par: str) -> dict:
    """Enregistre une règle saisie à l'écran et la renvoie avec son `id`.

    `doubles_seances` : `course_code`, `session_type`, `slots_per_session`
    (2 = 3 h, 3 = 4 h 30). `periodes_modules` : `course_code`, `semestre`,
    `session_type` (facultatif), `debut` et/ou `fin`."""
    if nom not in REGLES_DE_MODULES:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    motif = str(entree.get("motif") or "").strip()
    if nom == "projets_modules":
        return _ajouter_projet(config_dir, entree, par, motif)
    code = str(entree.get("course_code") or "").strip()
    if not code:
        raise ReglageInvalide("Choisissez un module.")
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
    elif nom == "repartitions":
        propre["semestre"] = str(entree.get("semestre") or "").strip()
        propre["session_type"] = _type_de_seance(entree.get("session_type"), obligatoire=False)
        if propre["session_type"] == "CM":
            raise ReglageInvalide("La répartition entre enseignants concerne les TD et les TP.")
        mode = str(entree.get("mode") or "")
        if mode not in MODES_DE_REPARTITION:
            raise ReglageInvalide("Choisissez une façon de répartir les séances.")
        propre["mode"] = mode
        propre["teacher_order"] = _codes(entree.get("teacher_order"))
    elif nom == "ordres_enseignants":
        propre["semestre"] = str(entree.get("semestre") or "").strip()
        ordre = _codes(entree.get("teacher_order"))
        if len(ordre) < 2 or len(set(ordre)) != len(ordre):
            raise ReglageInvalide("Choisissez deux enseignants différents.")
        propre["teacher_order"] = ordre
    elif nom == "duos":
        propre["semestre"] = str(entree.get("semestre") or "").strip()
        duo = _codes(entree.get("teacher_codes"))
        if len(duo) != 2 or duo[0] == duo[1]:
            raise ReglageInvalide("Un duo, ce sont deux enseignants différents.")
        salles = [str(s).strip() for s in entree.get("rare_rooms") or [] if str(s).strip()]
        type_duo = _type_de_seance(entree.get("session_type") or "TP", obligatoire=True)
        if type_duo == "CM":
            raise ReglageInvalide("Un duo concerne les TD et les TP.")
        # Les TP du Studio se font dans deux salles voisines ; les TD, dans les salles habituelles.
        if (type_duo == "TP" and len(salles) != 2) or (salles and (len(salles) != 2 or salles[0] == salles[1])):
            raise ReglageInvalide("Choisissez deux salles différentes.")
        rangs = []
        for cle in ("rang_de", "rang_a"):
            try:
                rang = int(entree[cle]) if entree.get(cle) not in (None, "") else None
            except (TypeError, ValueError):
                raise ReglageInvalide("Le rang d'une séance est un nombre entier.") from None
            if rang is not None and rang < 1:
                raise ReglageInvalide("Le rang d'une séance commence à 1.")
            rangs.append(rang)
        if rangs[0] and rangs[1] and rangs[0] > rangs[1]:
            raise ReglageInvalide("Le rang de début est après le rang de fin.")
        propre["session_type"], propre["rang_de"], propre["rang_a"] = type_duo, rangs[0], rangs[1]
        propre["teacher_codes"], propre["rare_rooms"] = duo, salles
        groupes = entree.get("group_overrides") or None
        if groupes:
            groupes = {str(c).upper(): sorted({str(g) for g in lettres}) for c, lettres in groupes.items()}
            if set(groupes) != set(duo) or not all(groupes.values()) or set(groupes[duo[0]]) & set(groupes[duo[1]]):
                raise ReglageInvalide("Chaque enseignant du duo doit avoir ses groupes de TP, sans groupe en commun.")
        propre["group_overrides"] = groupes
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


MAX_JOURS_PROJET = 5


def _ajouter_projet(config_dir: Path, entree: dict, par: str, motif: str) -> dict:
    """Un projet : plusieurs modules qui se déroulent dans un ordre donné,
    avec au plus N jours par semaine consacrés à l'ensemble.

    `etapes` : liste ordonnée de `{course_code, session_type (facultatif),
    de, a}` (`de` et `a` : rang des séances de ce type, à partir de 1, pour
    isoler une phase d'un module, ex. les TD 5 à 7). `jours_par_semaine` est
    facultatif."""
    if not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    etapes = []
    for brute in entree.get("etapes") or []:
        code = str(brute.get("course_code") or "").strip().upper()
        if not code:
            raise ReglageInvalide("Chaque étape doit désigner un module.")
        etape: dict = {"course_code": code, "session_type": _type_de_seance(brute.get("session_type"), obligatoire=False)}
        for cle in ("de", "a"):
            valeur = brute.get(cle)
            try:
                etape[cle] = int(valeur) if valeur not in (None, "") else None
            except (TypeError, ValueError):
                raise ReglageInvalide("Le rang d'une séance est un nombre entier.") from None
            if etape[cle] is not None and etape[cle] < 1:
                raise ReglageInvalide("Le rang d'une séance commence à 1.")
        if etape["de"] and etape["a"] and etape["de"] > etape["a"]:
            raise ReglageInvalide("Le rang de début d'une étape est après son rang de fin.")
        etapes.append(etape)
    if len(etapes) < 2:
        raise ReglageInvalide("Un projet compte au moins deux étapes.")
    jours = entree.get("jours_par_semaine")
    try:
        jours = int(jours) if jours not in (None, "") else None
    except (TypeError, ValueError):
        raise ReglageInvalide("Le nombre de jours par semaine est un nombre entier.") from None
    if jours is not None and not 1 <= jours <= MAX_JOURS_PROJET:
        raise ReglageInvalide("Un projet occupe entre 1 et 5 jours par semaine.")
    nom_projet = str(entree.get("nom") or "").strip()
    if not nom_projet:
        raise ReglageInvalide("Donnez un nom au projet.")
    propre = {
        "id": uuid.uuid4().hex[:12],
        "nom": nom_projet[:80],
        "semestre": str(entree.get("semestre") or "").strip(),
        "etapes": etapes,
        "jours_par_semaine": jours,
        "motif": motif[:300],
        "demande_par": par,
        "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        tout["projets_modules"]["ajouts"].append(propre)
        ecrire_json(_path(config_dir), tout)
    return propre


def retirer_regle_de_module(config_dir: Path, nom: str, identifiant: str) -> bool:
    if nom not in REGLES_DE_MODULES:
        raise ReglageInvalide(f"Réglage inconnu : {nom!r}")
    return retirer(config_dir, nom, identifiant, livree=False)


# ── Début et fin des cours d'un semestre ──────────────────────────────


def dates_semestres(config_dir: Path) -> dict[str, tuple[str, str]]:
    """`{groupe: (début ISO, fin ISO)}` pour les groupes dont les dates ont
    été saisies à l'écran."""
    sortie: dict[str, tuple[str, str]] = {}
    for ajout in _lire(config_dir)["dates_semestres"]["ajouts"]:
        groupe, debut, fin = ajout.get("groupe"), ajout.get("debut"), ajout.get("fin")
        if groupe and debut and fin:
            sortie[str(groupe)] = (str(debut), str(fin))
    return sortie


def definir_dates_semestre(config_dir: Path, groupe: str, debut: str | None, fin: str | None, par: str) -> None:
    """Remplace les dates saisies pour ce groupe. Sans dates : retour aux
    dates d'origine."""
    if debut or fin:
        if not (debut and fin):
            raise ReglageInvalide("Indiquez le premier et le dernier jour de cours.")
        debut, fin = _valider_date(debut), _valider_date(fin)
        if debut >= fin:
            raise ReglageInvalide("Le dernier jour de cours doit être après le premier.")
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout["dates_semestres"]
        bloc["ajouts"] = [a for a in bloc["ajouts"] if a.get("groupe") != groupe]
        if debut:
            bloc["ajouts"].append({
                "id": uuid.uuid4().hex[:12],
                "groupe": groupe,
                "debut": debut,
                "fin": fin,
                "demande_par": par,
                "le": datetime.now(timezone.utc).date().isoformat(),
            })
        ecrire_json(_path(config_dir), tout)


# ── Fin des cours des alternants, réglages du calcul ──────────────────


def fins_alternants(config_dir: Path) -> dict[str, str | None]:
    """`{groupe: date ISO ou None}` pour les groupes où la fin des cours des
    alternants a été saisie. `None` : ils finissent avec les autres."""
    return {
        str(a["groupe"]): (str(a["fin"]) if a.get("fin") else None)
        for a in _lire(config_dir)["fins_alternants"]["ajouts"]
        if a.get("groupe")
    }


def definir_fin_alternants(config_dir: Path, groupe: str, fin: str | None, par: str, *, oublier: bool = False) -> None:
    """Dernier jour de cours des alternants du groupe. `oublier` : retour à
    la date d'origine."""
    fin = _valider_date(fin) if fin else None
    _remplacer(config_dir, "fins_alternants", groupe, None if oublier else {"fin": fin}, par)


def parametres_calcul(config_dir: Path) -> dict[str, dict]:
    """Les réglages du calcul retenus au dernier lancement, par groupe."""
    return {
        str(a["groupe"]): dict(a.get("valeurs") or {})
        for a in _lire(config_dir)["parametres_calcul"]["ajouts"]
        if a.get("groupe")
    }


def retenir_parametres_calcul(config_dir: Path, groupe: str, valeurs: dict, par: str) -> None:
    _remplacer(config_dir, "parametres_calcul", groupe, {"valeurs": dict(valeurs)} if valeurs else None, par)


def _remplacer(config_dir: Path, nom: str, groupe: str, entree: dict | None, par: str) -> None:
    """Une seule entrée par groupe de semestres ; `None` la retire."""
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout[nom]
        bloc["ajouts"] = [a for a in bloc["ajouts"] if a.get("groupe") != groupe]
        if entree is not None:
            bloc["ajouts"].append({
                "id": uuid.uuid4().hex[:12],
                "groupe": groupe,
                **entree,
                "demande_par": par,
                "le": datetime.now(timezone.utc).date().isoformat(),
            })
        ecrire_json(_path(config_dir), tout)


# ── Semaine type d'un enseignant ──────────────────────────────────────


def semaines_types(config_dir: Path) -> dict[str, dict]:
    """`{code: {"bloques": [...], "liberes": [...], "motif", "demande_par"}}` :
    ce que l'écran a changé à la semaine type de chaque enseignant."""
    return {
        str(a["teacher_code"]): {
            "bloques": [list(c) for c in sorted(_cases(a.get("bloques")))],
            "liberes": [list(c) for c in sorted(_cases(a.get("liberes")))],
            "motif": str(a.get("motif") or ""),
            "demande_par": str(a.get("demande_par") or ""),
        }
        for a in _lire(config_dir)["semaines_types"]["ajouts"]
        if a.get("teacher_code")
    }


def definir_semaine_type(config_dir: Path, code: str, bloques: object, liberes: object, motif: str, par: str) -> None:
    """Remplace ce que l'écran change à la semaine type de l'enseignant :
    créneaux rendus indisponibles (`bloques`) et créneaux rendus disponibles
    (`liberes`). Les deux vides : retour à la semaine d'origine."""
    code = str(code or "").strip()
    if not code:
        raise ReglageInvalide("Choisissez un enseignant.")
    bloques, liberes = _cases(bloques), _cases(liberes)
    motif = str(motif or "").strip()
    if (bloques or liberes) and not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout["semaines_types"]
        bloc["ajouts"] = [a for a in bloc["ajouts"] if a.get("teacher_code") != code]
        if bloques or liberes:
            bloc["ajouts"].append({
                "id": uuid.uuid4().hex[:12],
                "teacher_code": code,
                "bloques": [list(c) for c in sorted(bloques)],
                "liberes": [list(c) for c in sorted(liberes - bloques)],
                "motif": motif[:300],
                "demande_par": par,
                "le": datetime.now(timezone.utc).date().isoformat(),
            })
        ecrire_json(_path(config_dir), tout)


# ── SAE : placement par le calcul, phases par enseignant ──────────────


def sae_par_le_calcul(config_dir: Path) -> list[dict]:
    """Les SAE que l'écran confie au calcul (`course_code`, `semestre`)."""
    return [dict(a) for a in _lire(config_dir)["sae_par_le_calcul"]["ajouts"] if a.get("course_code")]


def confier_sae_au_calcul(config_dir: Path, code: str, semestre: str, oui: bool, motif: str, par: str) -> None:
    code = str(code or "").strip().upper()
    motif = str(motif or "").strip()
    if oui and not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    with _verrou:
        tout = _lire(config_dir)
        bloc = tout["sae_par_le_calcul"]
        bloc["ajouts"] = [a for a in bloc["ajouts"] if str(a.get("course_code")).upper() != code]
        if oui:
            bloc["ajouts"].append({
                "id": uuid.uuid4().hex[:12], "course_code": code, "semestre": str(semestre),
                "motif": motif[:300], "demande_par": par, "le": datetime.now(timezone.utc).date().isoformat(),
            })
        ecrire_json(_path(config_dir), tout)


def phases_sae(config_dir: Path) -> list[dict]:
    """Les périodes d'encadrement saisies à l'écran : quel enseignant suit
    quelle SAE, de quand à quand."""
    return [dict(a) for a in _lire(config_dir)["phases_sae"]["ajouts"] if a.get("course_code") and a.get("id")]


def ajouter_phase_sae(config_dir: Path, entree: dict, par: str) -> dict:
    code = str(entree.get("course_code") or "").strip().upper()
    enseignant = str(entree.get("teacher_code") or "").strip().upper()
    if not code or not enseignant:
        raise ReglageInvalide("Choisissez une SAE et un enseignant.")
    if not entree.get("debut") or not entree.get("fin"):
        raise ReglageInvalide("Indiquez le début et la fin de la période.")
    debut, fin = _valider_date(entree["debut"]), _valider_date(entree["fin"])
    if debut > fin:
        raise ReglageInvalide("Le début de la période est après sa fin.")
    propre = {
        "id": uuid.uuid4().hex[:12], "course_code": code, "semestre": str(entree.get("semestre") or ""),
        "teacher_code": enseignant, "debut": debut, "fin": fin,
        "motif": str(entree.get("motif") or "").strip()[:300], "demande_par": par,
        "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        tout["phases_sae"]["ajouts"].append(propre)
        ecrire_json(_path(config_dir), tout)
    return propre


def retirer_phase_sae(config_dir: Path, identifiant: str) -> bool:
    return retirer(config_dir, "phases_sae", identifiant, livree=False)


# ── Plafonds hebdomadaires du calcul ──────────────────────────────────


def plafonds_hebdo(config_dir: Path) -> dict[str, dict]:
    """Les plafonds saisis à l'écran, par groupe de semestres (cf.
    `solver/plafonds.py`)."""
    return {
        str(a["groupe"]): dict(a.get("valeurs") or {})
        for a in _lire(config_dir)["plafonds_hebdo"]["ajouts"]
        if a.get("groupe")
    }


def definir_plafonds_hebdo(config_dir: Path, groupe: str, valeurs: dict, par: str) -> None:
    """Remplace les plafonds saisis pour ce groupe ; vide : ceux d'origine."""
    _remplacer(config_dir, "plafonds_hebdo", groupe, {"valeurs": dict(valeurs)} if valeurs else None, par)


# ── Effectifs des groupes, capacité et type des salles ────────────────

EFFECTIF_MAXI = 500
CAPACITE_MAXI = 1000


def effectifs(config_dir: Path) -> dict[str, int]:
    """`{id du groupe: effectif}` saisis à l'écran, à la place de ceux de
    `groups.yaml`."""
    sortie: dict[str, int] = {}
    for a in _lire(config_dir)["effectifs"]["ajouts"]:
        try:
            effectif = int(a.get("effectif"))
        except (TypeError, ValueError):
            continue
        if a.get("groupe") and 1 <= effectif <= EFFECTIF_MAXI:
            sortie[str(a["groupe"])] = effectif
    return sortie


def definir_effectif(config_dir: Path, groupe_id: str, effectif: int | None, par: str) -> None:
    """Remplace l'effectif saisi pour ce groupe ; `None` : celui d'origine."""
    if effectif is not None and not 1 <= int(effectif) <= EFFECTIF_MAXI:
        raise ReglageInvalide(f"Un effectif va de 1 à {EFFECTIF_MAXI} étudiants.")
    _remplacer(config_dir, "effectifs", groupe_id, None if effectif is None else {"effectif": int(effectif)}, par)


def salles(config_dir: Path) -> dict[str, dict]:
    """`{id de la salle: {"capacity": int, "room_type": str}}` : ce que
    l'écran a changé à une salle du bâtiment (`rooms.yaml`)."""
    sortie: dict[str, dict] = {}
    for a in _lire(config_dir)["salles"]["ajouts"]:
        valeurs: dict[str, object] = {}
        try:
            if a.get("capacity") is not None and 1 <= int(a["capacity"]) <= CAPACITE_MAXI:
                valeurs["capacity"] = int(a["capacity"])
        except (TypeError, ValueError):
            pass
        if isinstance(a.get("room_type"), str) and a["room_type"]:
            valeurs["room_type"] = a["room_type"]
        if a.get("groupe") and valeurs:
            sortie[str(a["groupe"])] = valeurs
    return sortie


def definir_salle(config_dir: Path, room_id: str, valeurs: dict | None, par: str) -> None:
    """Remplace ce qui est saisi pour cette salle ; vide : la salle d'origine."""
    propres: dict[str, object] = {}
    if valeurs and valeurs.get("capacity") is not None:
        if not 1 <= int(valeurs["capacity"]) <= CAPACITE_MAXI:
            raise ReglageInvalide(f"Une capacité va de 1 à {CAPACITE_MAXI} places.")
        propres["capacity"] = int(valeurs["capacity"])
    if valeurs and valeurs.get("room_type"):
        propres["room_type"] = str(valeurs["room_type"])
    _remplacer(config_dir, "salles", room_id, propres or None, par)


# ── Type de salle d'un module ─────────────────────────────────────────

TYPES_DE_SEANCE = ("CM", "TD", "TP")


def regles_salles(config_dir: Path) -> list[dict]:
    """Les règles « ce module va dans ce type de salle » saisies à l'écran."""
    return [
        dict(a) for a in _lire(config_dir)["regles_salles"]["ajouts"]
        if a.get("id") and a.get("course_code") and a.get("type_prefere")
    ]


def ajouter_regle_salle(config_dir: Path, entree: dict, par: str) -> dict:
    """Une règle par module et par type de séance : la nouvelle remplace
    celle qui visait déjà les mêmes séances."""
    code = str(entree.get("course_code") or "").strip().upper()
    if not code or len(code) > 20 or not code.replace("-", "").replace("_", "").isalnum():
        raise ReglageInvalide("Choisissez un module.")
    types = [t for t in TYPES_DE_SEANCE if t in (entree.get("session_types") or [])]
    if not types:
        raise ReglageInvalide("Cochez au moins un type de séance (CM, TD ou TP).")
    prefere = str(entree.get("type_prefere") or "").strip()
    repli = str(entree.get("type_repli") or "").strip()
    if not prefere:
        raise ReglageInvalide("Choisissez le type de salle préféré.")
    if repli == prefere:
        repli = ""
    propre = {
        "id": uuid.uuid4().hex[:12], "course_code": code, "session_types": types,
        "type_prefere": prefere, "type_repli": repli, "demande_par": par,
        "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        gardees = []
        for a in tout["regles_salles"]["ajouts"]:
            if str(a.get("course_code")) == code:
                restants = [t for t in a.get("session_types") or [] if t not in types]
                if not restants:
                    continue
                a = {**a, "session_types": restants}
            gardees.append(a)
        tout["regles_salles"]["ajouts"] = [*gardees, propre]
        ecrire_json(_path(config_dir), tout)
    return propre


def retirer_regle_salle(config_dir: Path, identifiant: str) -> bool:
    return retirer(config_dir, "regles_salles", identifiant, livree=False)


# ── Événements à date fixe ────────────────────────────────────────────

TOUTES_LES_PROMOTIONS = "*"


def cle_evenement(entree: dict) -> str:
    parcours = ",".join(sorted(str(p) for p in entree.get("parcours") or []))
    return f"{entree.get('date')}|{entree.get('debut') or ''}|{parcours}|{str(entree.get('motif') or '').strip()}"


def evenements_fixes(config_dir: Path, livres: list[dict] | None) -> list[dict]:
    """Les événements à date fixe en vigueur : ceux livrés (`contraintes/
    10_dates_fixes.json`), moins ceux retirés à l'écran, plus ceux saisis.
    Chaque entrée porte `cle` et `origine`."""
    bloc = _lire(config_dir)["evenements_fixes"]
    retraits = set(bloc["retraits"])
    sortie = []
    for entree in livres or []:
        cle = cle_evenement(entree)
        if cle not in retraits:
            sortie.append({**entree, "cle": cle, "origine": "livree"})
    sortie += [{**a, "cle": a["id"], "origine": "ajoutee"} for a in bloc["ajouts"] if a.get("id") and a.get("date")]
    return sortie


# ── Semaines des alternants à l'IUT ───────────────────────────────────

ANNEES_D_ALTERNANCE = ("BUT2", "BUT3")


def cle_presence(annee: str, debut: object) -> str:
    return f"{annee}|{debut}"


def _jours_ouvres(debut: str, fin: str) -> list[str]:
    premier, dernier = date.fromisoformat(debut), date.fromisoformat(fin)
    return [
        date.fromordinal(n).isoformat()
        for n in range(premier.toordinal(), dernier.toordinal() + 1)
        if date.fromordinal(n).weekday() < 5
    ]


def presences_alternants(config_dir: Path, livrees: dict[str, list[dict]] | None) -> list[dict]:
    """Les périodes où les alternants sont à l'IUT : `{annee, debut, fin,
    dates, cle, origine}`. `livrees` : par année (« BUT2 », « BUT3 »), les
    semaines du fichier officiel."""
    bloc = _lire(config_dir)["presence_alternants"]
    retraits = set(bloc["retraits"])
    sortie = []
    for annee, semaines in (livrees or {}).items():
        for semaine in semaines:
            cle = cle_presence(annee, semaine.get("debut"))
            if cle not in retraits:
                sortie.append({
                    "annee": annee, "debut": str(semaine.get("debut")), "fin": str(semaine.get("fin")),
                    "dates": [str(d) for d in semaine.get("dates") or []], "cle": cle, "origine": "livree",
                })
    for a in bloc["ajouts"]:
        if not a.get("id") or a.get("annee") not in ANNEES_D_ALTERNANCE:
            continue
        try:
            dates = _jours_ouvres(str(a.get("debut")), str(a.get("fin")))
        except ValueError:
            continue
        sortie.append({
            "annee": a["annee"], "debut": str(a["debut"]), "fin": str(a["fin"]), "dates": dates,
            "cle": a["id"], "origine": "ajoutee", "demande_par": str(a.get("demande_par") or ""),
        })
    return sorted(sortie, key=lambda e: (e["annee"], e["debut"]))


def ajouter_presence_alternants(config_dir: Path, entree: dict, par: str) -> dict:
    annee = str(entree.get("annee") or "")
    if annee not in ANNEES_D_ALTERNANCE:
        raise ReglageInvalide("Choisissez l'année des alternants (BUT2 ou BUT3).")
    if not entree.get("debut") or not entree.get("fin"):
        raise ReglageInvalide("Indiquez le premier et le dernier jour à l'IUT.")
    debut, fin = _valider_date(entree["debut"]), _valider_date(entree["fin"])
    if debut > fin:
        raise ReglageInvalide("Le premier jour est après le dernier.")
    if (date.fromisoformat(fin) - date.fromisoformat(debut)).days > 60:
        raise ReglageInvalide("Une période à l'IUT ne dépasse pas deux mois : saisissez-la en plusieurs fois.")
    if not _jours_ouvres(debut, fin):
        raise ReglageInvalide("La période ne contient aucun jour de semaine.")
    propre = {
        "id": uuid.uuid4().hex[:12], "annee": annee, "debut": debut, "fin": fin, "demande_par": par,
        "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        tout["presence_alternants"]["ajouts"].append(propre)
        ecrire_json(_path(config_dir), tout)
    return propre


# ── Cours hors maquette ───────────────────────────────────────────────

SEANCES_MAXI = 60


def cours_hors_maquette(config_dir: Path) -> list[dict]:
    """Les modules ajoutés à l'écran, absents de la maquette officielle."""
    return [
        dict(a) for a in _lire(config_dir)["cours_hors_maquette"]["ajouts"]
        if a.get("id") and a.get("code") and a.get("semestre") and a.get("parcours") and a.get("teacher_code")
    ]


def ligne_de_maquette(cours: dict) -> dict:
    """Le module saisi, sous la forme d'une ligne de l'export maquette
    (cf. `additional_courses.yaml`) : un seul enseignant, qui voit tous les
    groupes."""
    groupes_td, groupes_tp = max(1, int(cours.get("groupes_td") or 1)), max(1, int(cours.get("groupes_tp") or 1))
    cm, td, tp = (int(cours.get(t) or 0) for t in ("cm", "td", "tp"))
    enseignant = {
        "code": str(cours["teacher_code"]), "nom": str(cours.get("teacher_nom") or cours["teacher_code"]),
        "prenom": str(cours.get("teacher_prenom") or ""),
    }
    return {
        "code_matiere": str(cours["code"]), "nom_matiere": str(cours.get("nom") or cours["code"]),
        "semestre": str(cours["semestre"]), "parcours": str(cours["parcours"]),
        "lead": dict(enseignant),
        "total": {"cm": cm, "td": td, "tp": tp},
        "profs": [{
            "block": "block1", **enseignant, "cm": cm, "td": td * groupes_td, "tp": tp * groupes_tp,
            "nbGpTd": groupes_td if td else 0, "nbGpTp": groupes_tp if tp else 0,
        }],
        "maquette": {"groupes": {"td": groupes_td if td else 0, "tp": groupes_tp if tp else 0},
                     "bloque": False, "hors_service": False},
    }


def ajouter_cours_hors_maquette(config_dir: Path, entree: dict, par: str) -> dict:
    code = str(entree.get("code") or "").strip().upper()
    if not 3 <= len(code) <= 12 or not code.isalnum():
        raise ReglageInvalide("Le code du module fait 3 à 12 lettres ou chiffres, sans espace.")
    nom = str(entree.get("nom") or "").strip()
    if not nom:
        raise ReglageInvalide("Donnez un intitulé au module.")
    enseignant = str(entree.get("teacher_code") or "").strip().upper()
    if not 2 <= len(enseignant) <= 8 or not enseignant.isalnum():
        raise ReglageInvalide("Choisissez l'enseignant du module.")
    volumes = {}
    for type_ in ("cm", "td", "tp"):
        try:
            volumes[type_] = int(entree.get(type_) or 0)
        except (TypeError, ValueError):
            raise ReglageInvalide("Les nombres de séances sont des entiers.") from None
        if not 0 <= volumes[type_] <= SEANCES_MAXI:
            raise ReglageInvalide(f"Un module compte de 0 à {SEANCES_MAXI} séances par type.")
    if not any(volumes.values()):
        raise ReglageInvalide("Indiquez au moins une séance (CM, TD ou TP).")
    propre = {
        "id": uuid.uuid4().hex[:12], "code": code, "nom": nom[:120],
        "semestre": str(entree.get("semestre") or ""), "parcours": str(entree.get("parcours") or ""),
        "teacher_code": enseignant,
        "teacher_nom": str(entree.get("teacher_nom") or "").strip().upper()[:60],
        "teacher_prenom": str(entree.get("teacher_prenom") or "").strip().upper()[:60],
        **volumes,
        "groupes_td": max(1, int(entree.get("groupes_td") or 1)),
        "groupes_tp": max(1, int(entree.get("groupes_tp") or 1)),
        "demande_par": par, "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        if any(a.get("code") == code and a.get("parcours") == propre["parcours"]
               for a in tout["cours_hors_maquette"]["ajouts"]):
            raise ReglageInvalide(f"Le module {code} est déjà ajouté pour cette promotion.")
        tout["cours_hors_maquette"]["ajouts"].append(propre)
        ecrire_json(_path(config_dir), tout)
    return propre


# ── Années universitaires ─────────────────────────────────────────────

_CHAMPS_D_UNE_ANNEE = ("rentree", "fin_impair", "debut_pair", "fin", "vacances", "feries")


def annees(config_dir: Path) -> dict[str, dict]:
    """`{« 2027-2028 »: {rentree, fin_impair, debut_pair, fin, vacances,
    feries}}` : les années préparées à l'écran (cf. `calendar/annees.py`)."""
    return {
        str(a["groupe"]): {c: a.get(c) for c in _CHAMPS_D_UNE_ANNEE}
        for a in _lire(config_dir)["annees"]["ajouts"]
        if a.get("groupe") and a.get("rentree") and a.get("fin")
    }


def definir_annee(config_dir: Path, label: str, annee: dict | None, par: str) -> None:
    """Enregistre l'année (déjà validée) ; `None` la retire."""
    _remplacer(
        config_dir, "annees", label,
        None if annee is None else {c: annee.get(c) for c in _CHAMPS_D_UNE_ANNEE}, par,
    )


def annee_en_cours(config_dir: Path) -> dict | None:
    """`{"label", "depuis"}` : l'année que l'application utilise, quand ce
    n'est plus celle d'origine, et l'instant où son calendrier a été fixé."""
    for a in _lire(config_dir)["annee_en_cours"]["ajouts"]:
        if a.get("groupe") == "application" and a.get("label"):
            return {"label": str(a["label"]), "depuis": str(a.get("depuis") or "")}
    return None


def definir_annee_en_cours(config_dir: Path, label: str | None, par: str) -> None:
    """Change l'année de l'application (`None` : celle d'origine) et oublie
    les dates de semestres saisies pour l'année quittée."""
    with _verrou:
        _remplacer(
            config_dir, "annee_en_cours", "application",
            None if label is None else {"label": label, "depuis": datetime.now(timezone.utc).isoformat()}, par,
        )
        tout = _lire(config_dir)
        tout["dates_semestres"]["ajouts"] = []
        tout["fins_alternants"]["ajouts"] = []
        ecrire_json(_path(config_dir), tout)


def dater_l_annee_en_cours(config_dir: Path, par: str) -> None:
    """Le calendrier de l'année en cours vient de changer : les brouillons
    calculés avant ne se publient plus."""
    en_cours = annee_en_cours(config_dir)
    if en_cours is not None:
        _remplacer(
            config_dir, "annee_en_cours", "application",
            {"label": en_cours["label"], "depuis": datetime.now(timezone.utc).isoformat()}, par,
        )


# ── Règles d'enseignants et de modules (19/11) ────────────────────────

MAX_DATES_EXCLUSIVES = 120


def disponibilites_exclusives(config_dir: Path) -> list[dict]:
    return [a for a in _lire(config_dir)["disponibilites_exclusives"]["ajouts"] if a.get("id")]


def ajouter_disponibilite_exclusive(
    config_dir: Path, teacher_code: str, debut: str, fin: str, dates: list[str], motif: str, par: str
) -> dict:
    """« Cet enseignant n'est disponible, entre `debut` et `fin`, que aux dates
    listées. » Les autres jours de la période deviennent des indisponibilités
    strictes pour la génération et le placement manuel."""
    code = str(teacher_code or "").strip()
    motif = str(motif or "").strip()
    if not code:
        raise ReglageInvalide("Choisissez un enseignant.")
    if not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    debut, fin = _valider_date(debut), _valider_date(fin)
    if fin < debut:
        raise ReglageInvalide("La fin de la période précède son début.")
    propres = sorted({_valider_date(d) for d in dates or []})
    if not propres:
        raise ReglageInvalide("Indiquez au moins une date de disponibilité.")
    if len(propres) > MAX_DATES_EXCLUSIVES:
        raise ReglageInvalide(f"Trop de dates (maximum {MAX_DATES_EXCLUSIVES}).")
    hors = [d for d in propres if not debut <= d <= fin]
    if hors:
        raise ReglageInvalide(f"La date {hors[0]} est hors de la période.")
    entree = {
        "id": uuid.uuid4().hex[:12], "teacher_code": code, "debut": debut, "fin": fin, "dates": propres,
        "motif": motif[:300], "demande_par": par, "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        tout["disponibilites_exclusives"]["ajouts"].append(entree)
        ecrire_json(_path(config_dir), tout)
    return entree


def modules_non_dispenses(config_dir: Path) -> dict[str, dict]:
    """`{CODE: entrée}` : les modules dont aucune séance n'est créée."""
    return {
        str(a["course_code"]).upper(): a
        for a in _lire(config_dir)["modules_non_dispenses"]["ajouts"]
        if a.get("course_code") and a.get("id")
    }


def _ajouter_simple(config_dir: Path, nom: str, cle: str, valeur: str, motif: str, par: str, unique: bool) -> dict:
    valeur = str(valeur or "").strip()
    motif = str(motif or "").strip()
    if not valeur:
        raise ReglageInvalide("Choisissez une valeur.")
    if not motif:
        raise ReglageInvalide("Le motif est obligatoire : dans un an, personne ne saura pourquoi sinon.")
    if cle == "course_code":
        valeur = valeur.upper()
    entree = {
        "id": uuid.uuid4().hex[:12], cle: valeur, "motif": motif[:300], "demande_par": par,
        "le": datetime.now(timezone.utc).date().isoformat(),
    }
    with _verrou:
        tout = _lire(config_dir)
        if unique and any(a.get(cle) == valeur for a in tout[nom]["ajouts"]):
            raise ReglageInvalide("Déjà enregistré.")
        tout[nom]["ajouts"].append(entree)
        ecrire_json(_path(config_dir), tout)
    return entree


def ajouter_module_non_dispense(config_dir: Path, code: str, motif: str, par: str) -> dict:
    return _ajouter_simple(config_dir, "modules_non_dispenses", "course_code", code, motif, par, True)


def ajouter_compacter_journee(config_dir: Path, teacher_code: str, motif: str, par: str) -> dict:
    return _ajouter_simple(config_dir, "compacter_journee", "teacher_code", teacher_code, motif, par, True)


def compacter_journee(config_dir: Path) -> list[dict]:
    return [a for a in _lire(config_dir)["compacter_journee"]["ajouts"] if a.get("id")]
