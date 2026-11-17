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
from datetime import date, datetime, timezone
from pathlib import Path

from cal_iut.celcat.fichiers import ecrire_json, lire_json_etat

NOMS = ("salles_reservees", "indisponibilites", "dates_sae", "seances_annulees", "doubles_seances", "periodes_modules", "dates_semestres",
    "repartitions", "ordres_enseignants", "duos", "fins_alternants", "parametres_calcul", "semaines_types", "sae_par_le_calcul", "phases_sae", "plafonds_hebdo",
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
    if not bloc["ajouts"] and not bloc["retraits"] and not semaines:
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

REGLES_DE_MODULES = ("doubles_seances", "periodes_modules", "repartitions", "ordres_enseignants", "duos")
MODES_DE_REPARTITION = ("alterne", "par_groupes", "sequentiel")
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


def _codes(valeur: object) -> list[str]:
    return [str(c).strip().upper() for c in (valeur or []) if str(c).strip()]


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
        if len(salles) != 2 or salles[0] == salles[1]:
            raise ReglageInvalide("Choisissez deux salles différentes.")
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
