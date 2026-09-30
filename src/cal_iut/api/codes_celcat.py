"""Onglet « Codes Celcat » de Référence — `/reference/codes-celcat`.

Demande utilisateur (30/09/2026, responsable du planning) : « On n'avait pas
dit qu'on voulait un onglet, quelque part où on pouvait renseigner les codes
Celcat pour les cours et les salles aussi ? Et tu peux rajouter les cours.
Que l'utilisateur puisse enregistrer les codes comme ça et ils sont
enregistrés pour Celcat. »

Jusque-là, un code Celcat ne se saisissait que pour ce qui MANQUAIT ou
BLOQUAIT (« Données à compléter », blocages de l'écran Celcat). Rien ne
montrait TOUT ce que l'appli envoie à Celcat, ni d'où vient chaque code.

Ce module sert deux choses :

1. la LISTE complète, par famille (`cours`, `salles`, `enseignants`,
   `groupes`) : chaque entité connue du planning, son nombre de séances
   placées, le code Celcat qui partira, et son ORIGINE — fichier de
   configuration, saisi dans l'appli (par qui, quand), ou manquant ;
2. UNE fonction d'écriture par famille (`definir_code` / `effacer_code`),
   la seule, appelée aussi par « Données à compléter » (`api/reference.py`)
   et par les blocages de l'écran Celcat (`PUT /celcat/mappings`) : même
   validation de format, même refus des doublons, même trace partout.

Où vont les codes : `data/state/celcat_mappings.json` (`celcat/mappings.py`),
fusionné par-dessus `celcat.yaml` par `load_celcat_config` — que lisent le
plan (`/celcat/plan`), la comparaison, la file d'envoi et le worker. Un code
saisi ici part donc au passage suivant, sans déploiement.

GROUPES : EN LECTURE SEULE, et c'est voulu. Ce que Celcat attend pour un
groupe n'est pas un code lisible mais son identifiant INTERNE (`group_id`,
« 1661972 »), relevé par balayage de plages (`celcat_groupes.yaml`) — le
catalogue refuse de s'énumérer (`ETooManyRecords`). Vérifié le 30/09/2026
avant de trancher :
- aucun utilisateur ne le lit dans l'interface de Celcat ;
- il n'existe AUCUNE liste d'identifiants relevés hors de ce fichier contre
  laquelle valider une saisie (le relevé des évènements ne garde que le nom
  du groupe) ;
- six lecteurs le lisent directement (écriture, relevé du sidecar, file,
  suppression, comparaison…), dont le script du sidecar ;
- un identifiant faux ne produit pas un refus mais des DOUBLONS : une
  modification localisée sur le mauvais groupe fait croire l'évènement
  disparu, et le passage suivant le recrée (`nuit.motif_groupe_absent`).
Le rendre saisissable « proprement » n'est donc pas possible sans une
vérification en direct dans Celcat : l'onglet l'affiche, avec « se règle
dans celcat_groupes.yaml ».

Droits : la liste est lisible par tout compte actif (rôles `read_only`,
`edit`, `admin` ; pas le rôle `api`) — Référence est ouverte à tous les
comptes. Pour un non-admin, l'AUTEUR d'une saisie (l'adresse d'un compte)
n'est pas renvoyé : seulement « saisi dans l'appli le JJ/MM ». Saisir,
modifier, effacer : administrateurs, comme toute correspondance Celcat.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cal_iut.api import accounts, revision
from cal_iut.api.verrou import ecriture_planning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reference/codes-celcat", tags=["reference"])

FamilleCode = Literal["cours", "salles", "enseignants", "groupes"]
FAMILLES_CODE: tuple[str, ...] = ("cours", "salles", "enseignants", "groupes")

# Famille de l'onglet -> famille de la surcouche (`celcat/mappings.py`).
# `groupes` n'y est pas : lecture seule (cf. docstring du module).
_FAMILLE_SURCOUCHE = {"cours": "matieres", "salles": "salles", "enseignants": "enseignants"}
# Famille du journal commun (`surcharges_reference.journal`), inchangée.
_FAMILLE_JOURNAL = {"cours": "cours", "salles": "salles", "enseignants": "enseignants"}

AIDE: dict[str, str] = {
    "cours": "Code module Celcat (« TSBZ1M01 »), parmi ceux relevés dans Celcat (celcat_matieres.yaml).",
    "salles": "Nom de la salle dans Celcat, avec le point (« H.104 », « Amphi 3 MMI »).",
    "enseignants": "Identifiant Celcat de l'enseignant : un nombre (« 38999 »), visible dans Celcat.",
    "groupes": (
        "Identifiant interne du groupe, relevé dans Celcat par balayage : il ne se lit pas dans "
        "Celcat et ne se saisit pas ici — il se règle dans data/config/celcat_groupes.yaml (déploiement)."
    ),
}
EXEMPLE: dict[str, str] = {"cours": "TSBZ1M01", "salles": "H.104", "enseignants": "38999", "groupes": "1661972"}

NOTE_GROUPES = "Se règle dans data/config/celcat_groupes.yaml (identifiant interne relevé dans Celcat, puis déploiement)."


# ── Modèles ─────────────────────────────────────────────────────────────


class LigneCodeCelcat(BaseModel):
    cle: str = Field(description="Code de cours, identifiant de salle, trigramme, nom Celcat du groupe.")
    libelle: str
    semestre: str | None = None
    parcours: str | None = None
    type_salle: str | None = None
    capacite: int | None = None
    nb_seances: int = Field(description="Séances placées au planning.")
    code: str | None = Field(description="Le code qui part vers Celcat (fichier, puis saisie par-dessus).")
    code_fichier: str | None = Field(description="Ce que dit le fichier de configuration.")
    origine: Literal["fichier", "appli", "manquant"]
    saisi_le: str | None = None
    saisi_par: str | None = Field(default=None, description="Adresse du compte — administrateurs seulement.")
    valeur_avant: str | None = Field(default=None, description="Administrateurs seulement.")
    suggestion: str | None = Field(default=None, description="Cours : le code de la maquette (codelement), s'il est relevé.")
    alerte: str | None = Field(default=None, description="Code présent mais inutilisable tel quel.")
    note: str | None = None
    modifiable: bool = Field(description="Ce compte peut saisir, modifier ou effacer ce code.")


class FamilleCodesCelcat(BaseModel):
    famille: FamilleCode
    aide: str
    exemple: str
    modifiable: bool
    total: int
    sans_code: int
    sans_code_bloquants: int = Field(description="Sans code ET avec des séances placées : bloque Celcat.")
    saisis: int
    suggestions: list[str] = Field(description="Codes relevés dans Celcat, proposés à la saisie.")
    lignes: list[LigneCodeCelcat]


class CodesCelcat(BaseModel):
    revision: int
    admin: bool
    familles: dict[str, FamilleCodesCelcat]


class CodeCelcatRequest(BaseModel):
    famille: FamilleCode
    cle: str = Field(min_length=1, max_length=120)
    code: str = Field(max_length=80)


class CodeCelcatEnregistre(BaseModel):
    famille: FamilleCode
    cle: str
    code: str | None
    origine: Literal["fichier", "appli", "manquant"]
    message: str
    revision: int


# ── Lecture des fichiers ────────────────────────────────────────────────


def _lire_yaml(chemin: Path) -> dict[str, object]:
    if not chemin.exists():
        return {}
    try:
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def codes_du_fichier(config_dir: Path, famille: str) -> dict[str, str]:
    """Ce que dit la configuration seule, SANS la surcouche — la « valeur du
    fichier » que rétablit l'effacement. Mêmes règles que
    `load_celcat_config` (trigrammes et codes de cours en majuscules, « 0 »
    = pas de code)."""
    from cal_iut.celcat.mapping import _code_renseigne

    config_dir = Path(config_dir)
    if famille == "groupes":
        return {str(k).strip(): str(v).strip() for k, v in _lire_yaml(config_dir / "celcat_groupes.yaml").items() if v}
    data = _lire_yaml(config_dir / "celcat.yaml")
    if famille == "salles":
        return {str(k): str(v) for k, v in (data.get("salles") or {}).items() if v}
    if famille == "enseignants":
        return {str(k).upper(): code for k, v in (data.get("enseignants") or {}).items() if (code := _code_renseigne(v))}
    if famille == "cours":
        return {str(k).upper(): str(v) for k, v in (data.get("modules") or {}).items() if v}
    raise ValueError(famille)


def codes_effectifs(config_dir: Path, famille: str) -> dict[str, str]:
    """Le code qui part vers Celcat : `load_celcat_config`, la table même
    que lisent le plan, la comparaison, la file et le worker."""
    from cal_iut.celcat.mapping import load_celcat_config

    if famille == "groupes":
        return codes_du_fichier(config_dir, "groupes")
    cfg = load_celcat_config(Path(config_dir))
    return {"cours": cfg.modules, "salles": cfg.salles, "enseignants": cfg.enseignants}[famille]


# ── Validation, une règle par famille ───────────────────────────────────

# Identifiant Celcat d'un enseignant : un nombre (« 2158 », « 40683 » dans
# `celcat.yaml`). « 0 » y signifie « pas de code » : jamais une saisie.
_RE_ENSEIGNANT = re.compile(r"^[1-9]\d{0,6}$")
# Nom de salle Celcat : « H.005 », « H.022 studio », « Amphi 3 MMI », « A.018 ».
_RE_SALLE = re.compile(r"^[0-9A-Za-zÀ-ÖØ-öø-ÿ][0-9A-Za-zÀ-ÖØ-öø-ÿ .'()/-]{0,39}$")
# « H104 » : la forme de l'ancien autoclicker. Celcat attend « H.104 » —
# une recherche exacte sur « H104 » ne remonte rien (`celcat.yaml`).
_RE_SALLE_SANS_POINT = re.compile(r"^([A-Za-z])(\d{3})$")
_RE_SALLE_POINT = re.compile(r"^([a-z])\.(\d{3})$")


def _normaliser(famille: str, config_dir: Path, brut: str) -> str:
    texte = " ".join(str(brut or "").split())
    if not texte:
        raise HTTPException(400, "Le code Celcat est vide. Pour revenir à la valeur du fichier, utilisez « Revenir à la valeur du fichier ».")
    if famille == "cours":
        from cal_iut.api.reference import valider_code_module

        return valider_code_module(Path(config_dir), texte)
    if famille == "enseignants":
        if not _RE_ENSEIGNANT.match(texte):
            raise HTTPException(
                400, f"« {texte} » n'est pas un identifiant Celcat d'enseignant (un nombre, ex. 38999 ; « 0 » ne vaut pas code)."
            )
        return texte
    if famille == "salles":
        sans_point = _RE_SALLE_SANS_POINT.match(texte)
        if sans_point:
            propose = f"{sans_point.group(1).upper()}.{sans_point.group(2)}"
            raise HTTPException(400, f"Celcat attend le nom avec le point : « {propose} », pas « {texte} ».")
        minuscule = _RE_SALLE_POINT.match(texte)
        if minuscule:
            texte = f"{minuscule.group(1).upper()}.{minuscule.group(2)}"
        if not _RE_SALLE.match(texte):
            raise HTTPException(400, f"« {texte} » n'est pas un nom de salle Celcat (ex. H.104, Amphi 3 MMI).")
        return texte
    raise HTTPException(
        409, "L'identifiant Celcat d'un groupe ne se saisit pas dans l'appli : " + NOTE_GROUPES
    )


def _salles_jumelees(rooms: list[object], a: str, b: str) -> bool:
    """Vrai si l'une des deux salles est la fusion qui recouvre l'autre
    (`Room.combines`) : H.007-008 porte le code de H.007, décision
    utilisateur du 31/08/2026 (« pour les salles doubles on en choisit une
    seule »). Seul doublon légitime d'une famille."""
    par_id = {getattr(r, "id", ""): r for r in rooms or []}
    ra, rb = par_id.get(a), par_id.get(b)
    return bool(
        (ra is not None and b in (getattr(ra, "combines", None) or []))
        or (rb is not None and a in (getattr(rb, "combines", None) or []))
    )


def valider_code(state: object, famille: str, cle: str, brut: str) -> str:
    """Le code nettoyé, ou une `HTTPException` qui dit quoi corriger.

    Format propre à la famille, puis REFUS d'un code déjà porté par une
    autre entité de la même famille : deux salles sous le même nom Celcat
    y seraient confondues, deux enseignants se partageraient une paie, deux
    cours un même module. Exception documentée : une salle fusionnée et
    l'une de ses moitiés (`_salles_jumelees`)."""
    config_dir = Path(state.config_dir)
    code = _normaliser(famille, config_dir, brut)
    from cal_iut.celcat import mappings

    cle_propre = mappings.cle_normalisee(_FAMILLE_SURCOUCHE[famille], cle)
    rooms = list(getattr(state, "rooms", []) or [])
    libelles = _libelles(state, famille)
    for autre, valeur in sorted(codes_effectifs(config_dir, famille).items()):
        if autre == cle_propre or str(valeur).strip().upper() != code.upper():
            continue
        if famille == "salles" and _salles_jumelees(rooms, cle_propre, autre):
            continue
        nom = libelles.get(autre)
        qui = f"{nom} ({autre})" if nom and nom != autre else autre
        raise HTTPException(409, f"Le code {code} est déjà celui de {qui}. Corrigez d'abord celui-là.")
    return code


def _libelles(state: object, famille: str) -> dict[str, str]:
    if famille == "salles":
        return {r.id: r.label for r in getattr(state, "rooms", []) or []}
    if famille == "cours":
        noms = {c.code.upper(): c.name for c in getattr(state, "courses", []) or []}
        for s in getattr(state, "sessions", []) or []:
            noms.setdefault(s.course_code.upper(), s.course_name)
        return noms
    if famille == "enseignants":
        try:
            from cal_iut.api import main

            return {k.upper(): v for k, v in (main.payload_app_state().get("teacherLabels") or {}).items()}
        except Exception:  # noqa: BLE001 — un nom en moins, jamais un refus
            return {}
    return {}


# ── Écriture : la seule fonction par famille ────────────────────────────


_verrou = threading.RLock()


def enregistrer_code(state: object, famille: str, cle: str, code: str, *, par: str = "") -> str:
    """Persiste un code DÉJÀ validé (`valider_code`). Rend l'origine
    résultante : « fichier » si la saisie redit la valeur du fichier (la
    saisie est alors retirée, pour ne pas masquer une correction future du
    fichier), « appli » sinon. Trace au journal commun, avec la valeur
    d'avant et celle du fichier."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    config_dir = Path(state.config_dir)
    famille_surcouche = _FAMILLE_SURCOUCHE[famille]
    cle_propre = mappings.cle_normalisee(famille_surcouche, cle)
    with _verrou:
        du_fichier = codes_du_fichier(config_dir, famille).get(cle_propre)
        avant = codes_effectifs(config_dir, famille).get(cle_propre)
        if du_fichier is not None and du_fichier.strip().upper() == code.upper():
            retiree = mappings.retirer(famille_surcouche, cle_propre)
            if retiree is not None:
                surcharges_reference.journaliser(
                    _FAMILLE_JOURNAL[famille], cle_propre, "code_celcat", avant, du_fichier, par=par,
                    valeur_fichier=du_fichier,
                )
            return "fichier"
        mappings.definir(famille_surcouche, cle_propre, code, par=par, valeur_fichier=du_fichier)
        surcharges_reference.journaliser(
            _FAMILLE_JOURNAL[famille], cle_propre, "code_celcat", avant, code, par=par, valeur_fichier=du_fichier
        )
    return "appli"


def definir_code(state: object, famille: str, cle: str, brut: str, *, par: str = "") -> tuple[str, str]:
    """Valide puis enregistre. Rend `(code, origine)`."""
    if famille not in _FAMILLE_SURCOUCHE:
        raise HTTPException(409, "L'identifiant Celcat d'un groupe ne se saisit pas dans l'appli : " + NOTE_GROUPES)
    code = valider_code(state, famille, cle, brut)
    return code, enregistrer_code(state, famille, cle, code, par=par)


def effacer_code(state: object, famille: str, cle: str, *, par: str = "") -> str | None:
    """« Revenir à la valeur du fichier » : retire la saisie. Rend la valeur
    du fichier (None s'il n'en a pas : l'entité redevient « manquant »).
    404 s'il n'y avait pas de saisie."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    if famille not in _FAMILLE_SURCOUCHE:
        raise HTTPException(409, "L'identifiant Celcat d'un groupe ne se saisit pas dans l'appli : " + NOTE_GROUPES)
    config_dir = Path(state.config_dir)
    famille_surcouche = _FAMILLE_SURCOUCHE[famille]
    cle_propre = mappings.cle_normalisee(famille_surcouche, cle)
    with _verrou:
        du_fichier = codes_du_fichier(config_dir, famille).get(cle_propre)
        retiree = mappings.retirer(famille_surcouche, cle_propre)
        if retiree is None:
            raise HTTPException(404, f"Aucun code Celcat saisi dans l'appli pour {cle_propre}.")
        surcharges_reference.journaliser(
            _FAMILLE_JOURNAL[famille], cle_propre, "code_celcat", retiree.get("valeur"), du_fichier, par=par,
            valeur_fichier=du_fichier,
        )
    return du_fichier


# ── La liste complète ───────────────────────────────────────────────────


def _nom_groupe_celcat(semestre: str, libelle: str) -> str:
    from cal_iut.celcat.mapping import libelle_groupe_celcat

    return f"BUT MMI {semestre} {libelle_groupe_celcat(libelle)}".strip()


def lister(state: object, *, admin: bool) -> CodesCelcat:
    from cal_iut.api.reference import codes_modules_releves
    from cal_iut.celcat import mappings
    from cal_iut.celcat.instantane import lire
    from cal_iut.models.entities import RoomType

    config_dir = Path(state.config_dir)
    timetable = list(getattr(state, "timetable", []) or [])
    sessions_by_id = getattr(state, "sessions_by_id", {}) or {}
    surcouche = mappings.charger()

    par_cours: Counter[str] = Counter()
    par_salle: Counter[str] = Counter()
    par_prof: Counter[str] = Counter()
    par_groupe: Counter[str] = Counter()
    libelle_groupe = {g.id: g.label for g in getattr(state, "groups", []) or []}
    for p in timetable:
        par_cours[str(p.course_code).upper()] += 1
        if getattr(p, "room_id", None):
            par_salle[p.room_id] += 1
        for code in p.teacher_codes or []:
            par_prof[str(code).upper()] += 1
        session = sessions_by_id.get(p.session_id)
        semestre = str(getattr(session, "semestre", "") or "").strip()
        ids = list(p.group_ids or [])
        # Une séance à plusieurs groupes est bloquée pour une autre raison
        # (un seul onglet Celcat à la fois) : elle ne compte pour aucun.
        if semestre and len(ids) == 1:
            par_groupe[_nom_groupe_celcat(semestre, libelle_groupe.get(ids[0], ids[0])).upper()] += 1

    def ligne(famille: str, cle: str, **champs: object) -> LigneCodeCelcat:
        famille_surcouche = _FAMILLE_SURCOUCHE.get(famille)
        saisie = (surcouche.get(famille_surcouche, {}) if famille_surcouche else {}).get(cle)
        fichier = champs.pop("fichier")
        effectif = champs.pop("effectif")
        origine = "appli" if saisie else ("fichier" if effectif else "manquant")
        return LigneCodeCelcat(
            cle=cle,
            code=effectif or None,
            code_fichier=fichier or None,
            origine=origine,
            saisi_le=(saisie or {}).get("ajoute_le"),
            saisi_par=(str((saisie or {}).get("ajoute_par") or "") or None) if admin else None,
            valeur_avant=(saisie or {}).get("valeur_avant") if admin else None,
            modifiable=admin and famille != "groupes",
            **champs,
        )

    familles: dict[str, list[LigneCodeCelcat]] = {}

    # ── Cours : la maquette de tous les parcours et semestres ──
    fichier = codes_du_fichier(config_dir, "cours")
    effectif = codes_effectifs(config_dir, "cours")
    releves = codes_modules_releves(config_dir)
    cours: dict[str, dict[str, object]] = {}
    for c in getattr(state, "courses", []) or []:
        cours.setdefault(c.code.upper(), {
            "cle": c.code, "libelle": c.name or c.code, "semestre": c.semestre or None,
            "parcours": c.parcours or None, "codelement": (c.codelement or "").strip().upper(),
        })
    for s in getattr(state, "sessions", []) or []:
        cours.setdefault(s.course_code.upper(), {
            "cle": s.course_code, "libelle": s.course_name or s.course_code, "semestre": s.semestre or None,
            "parcours": s.parcours or None, "codelement": "",
        })
    lignes: list[LigneCodeCelcat] = []
    for cle_maj, c in sorted(cours.items()):
        code = effectif.get(cle_maj)
        alerte = None
        if code and code.strip().upper() not in releves:
            alerte = (
                f"{code} n'est pas dans le relevé des matières Celcat (celcat_matieres.yaml) : "
                "l'envoi échouera tant que son identifiant interne n'y est pas."
            )
        suggestion = c["codelement"] if c["codelement"] in releves and c["codelement"] != (code or "").upper() else None
        lignes.append(ligne(
            "cours", cle_maj, libelle=str(c["libelle"]), semestre=c["semestre"], parcours=c["parcours"],
            nb_seances=par_cours.get(cle_maj, 0), fichier=fichier.get(cle_maj), effectif=code,
            suggestion=suggestion or None, alerte=alerte,
        ))
    familles["cours"] = lignes

    # ── Salles : rooms.yaml + salles ajoutées ──
    fichier = codes_du_fichier(config_dir, "salles")
    effectif = codes_effectifs(config_dir, "salles")
    rooms = list(getattr(state, "rooms", []) or [])
    par_id = {r.id: r for r in rooms}
    lignes = []
    for r in sorted(rooms, key=lambda r: r.label.lower()):
        if r.room_type == RoomType.RESERVE:
            continue
        note = None
        if r.combines:
            moities = ", ".join(par_id[m].label if m in par_id else m for m in r.combines)
            note = f"Salles réunies ({moities}) : Celcat ne connaît que l'une des deux, qui peut porter le même code."
        lignes.append(ligne(
            "salles", r.id, libelle=r.label, type_salle=r.room_type.value, capacite=r.capacity,
            nb_seances=par_salle.get(r.id, 0), fichier=fichier.get(r.id), effectif=effectif.get(r.id), note=note,
        ))
    familles["salles"] = lignes

    # ── Enseignants : maquette, séances, enseignants déclarés ──
    from cal_iut.api.reference import _codes_enseignants

    fichier = codes_du_fichier(config_dir, "enseignants")
    effectif = codes_effectifs(config_dir, "enseignants")
    codes = set(_codes_enseignants(state))
    for c in getattr(state, "courses", []) or []:
        for bloc in c.profs or []:
            if bloc.teacher and bloc.teacher.code:
                codes.add(bloc.teacher.code.strip().upper())
        if c.lead and c.lead.code:
            codes.add(c.lead.code.strip().upper())
    noms = _libelles(state, "enseignants")
    familles["enseignants"] = [
        ligne(
            "enseignants", code, libelle=noms.get(code) or code, nb_seances=par_prof.get(code, 0),
            fichier=fichier.get(code), effectif=effectif.get(code),
        )
        for code in sorted(c for c in codes if c)
    ]

    # ── Groupes : ceux du fichier + ceux qu'attend le planning ──
    fichier = codes_du_fichier(config_dir, "groupes")
    fichier_maj = {k.upper(): (k, v) for k, v in fichier.items()}
    noms_groupes: dict[str, str] = {k.upper(): k for k in fichier}
    for s in getattr(state, "sessions", []) or []:
        semestre = str(s.semestre or "").strip()
        if semestre and len(s.group_ids or []) == 1:
            nom = _nom_groupe_celcat(semestre, libelle_groupe.get(s.group_ids[0], s.group_ids[0]))
            noms_groupes.setdefault(nom.upper(), nom)
    lignes = []
    for cle_maj, nom in sorted(noms_groupes.items(), key=lambda kv: _ordre_groupe(kv[1])):
        valeur = fichier_maj.get(cle_maj, (None, None))[1]
        semestre = nom.split()[2] if len(nom.split()) > 2 else None
        lignes.append(ligne(
            "groupes", nom, libelle=nom, semestre=semestre, nb_seances=par_groupe.get(cle_maj, 0),
            fichier=valeur, effectif=valeur, note=NOTE_GROUPES,
        ))
    familles["groupes"] = lignes

    # Suggestions : ce que Celcat contient réellement.
    salles_relevees: set[str] = set()
    try:
        for ev in lire().evenements:
            for nom in [ev.get("salle")] + list(ev.get("salles") or []):
                if isinstance(nom, str) and nom.strip():
                    salles_relevees.add(nom.strip())
    except Exception:  # sans relevé, les noms connus suffisent
        logger.warning("Relevé Celcat illisible : suggestions de salles limitées au fichier", exc_info=True)
    salles_relevees |= set(codes_effectifs(config_dir, "salles").values())
    suggestions = {
        "cours": sorted(releves),
        "salles": sorted(salles_relevees),
        "enseignants": [],
        "groupes": [],
    }

    sortie: dict[str, FamilleCodesCelcat] = {}
    for famille in FAMILLES_CODE:
        lignes = familles[famille]
        sortie[famille] = FamilleCodesCelcat(
            famille=famille,
            aide=AIDE[famille],
            exemple=EXEMPLE[famille],
            modifiable=admin and famille != "groupes",
            total=len(lignes),
            sans_code=sum(1 for l in lignes if l.origine == "manquant"),
            sans_code_bloquants=sum(1 for l in lignes if l.origine == "manquant" and l.nb_seances > 0),
            saisis=sum(1 for l in lignes if l.origine == "appli"),
            suggestions=suggestions[famille],
            lignes=lignes,
        )
    return CodesCelcat(revision=revision.actuelle().numero, admin=admin, familles=sortie)


def _ordre_groupe(nom: str) -> tuple[str, int, str]:
    """« BUT MMI S1 CM » avant « … S1 TD AB » avant « … S1 TP A »."""
    mots = nom.split()
    semestre = mots[2] if len(mots) > 2 else ""
    reste = " ".join(mots[3:])
    rang = 0 if reste.startswith("CM") else 1 if reste.startswith("TD") else 2 if reste.startswith("TP") else 3
    return (semestre, rang, reste)


# ── Routes ──────────────────────────────────────────────────────────────


def _main():
    from cal_iut.api import main

    return main


def _par(request: Request) -> str:
    return str(getattr(getattr(request.state, "user", None), "email", "") or "")


def _est_admin(request: Request) -> bool:
    user = getattr(request.state, "user", None)
    return user is not None and user.role == "admin"


@router.get("", response_model=CodesCelcat, dependencies=[Depends(accounts.require_role("read_only"))])
def lister_codes(request: Request, famille: FamilleCode | None = None) -> CodesCelcat:
    """Toutes les entités du planning et leur code Celcat, par famille.

    Tout compte actif (Référence est ouverte à tous) ; l'auteur d'une
    saisie n'est renvoyé qu'aux administrateurs. `famille` restreint les
    LIGNES à une famille — les compteurs des autres restent, pour les
    pastilles des sous-onglets."""
    reponse = lister(_main().get_state(), admin=_est_admin(request))
    if famille:
        for nom, bloc in reponse.familles.items():
            if nom != famille:
                bloc.lignes = []
    return reponse


@router.put("", response_model=CodeCelcatEnregistre, dependencies=[Depends(accounts.require_role("admin"))])
@ecriture_planning
def definir(body: CodeCelcatRequest, request: Request) -> CodeCelcatEnregistre:
    state = _main().get_state()
    cle = entite_canonique(state, body.famille, body.cle)
    code, origine = definir_code(state, body.famille, cle, body.code, par=_par(request))
    rev = revision.incrementer(f"codes-celcat:{body.famille}:{cle}")
    message = "Valeur du fichier : saisie retirée." if origine == "fichier" else "Enregistré pour Celcat."
    return CodeCelcatEnregistre(
        famille=body.famille, cle=cle, code=code, origine=origine, message=message, revision=rev.numero
    )


@router.delete("", response_model=CodeCelcatEnregistre, dependencies=[Depends(accounts.require_role("admin"))])
@ecriture_planning
def effacer(famille: FamilleCode, cle: str, request: Request) -> CodeCelcatEnregistre:
    state = _main().get_state()
    cle = entite_canonique(state, famille, cle)
    du_fichier = effacer_code(state, famille, cle, par=_par(request))
    rev = revision.incrementer(f"codes-celcat:{famille}:{cle}")
    return CodeCelcatEnregistre(
        famille=famille, cle=cle, code=du_fichier, origine="fichier" if du_fichier else "manquant",
        message="Valeur du fichier rétablie." if du_fichier else "Saisie retirée : plus de code pour Celcat.",
        revision=rev.numero,
    )


def entite_canonique(state: object, famille: str, cle: str) -> str:
    """La clé de l'entité telle que le planning la connaît (« h104 » pour
    « H104 », « KBR » pour « kbr »), ou 404. Un code rangé sous une clé mal
    orthographiée ne servirait jamais, sans que rien ne le dise."""
    brut = str(cle or "").strip()
    cible = brut.upper()
    if famille == "groupes":
        return brut  # refusé plus loin, avec la raison
    connus: dict[str, str]
    if famille == "salles":
        connus = {r.id.upper(): r.id for r in getattr(state, "rooms", []) or []}
    elif famille == "cours":
        connus = {c.code.upper(): c.code.upper() for c in getattr(state, "courses", []) or []}
        connus |= {s.course_code.upper(): s.course_code.upper() for s in getattr(state, "sessions", []) or []}
    else:
        from cal_iut.api.reference import _codes_enseignants

        connus = {c: c for c in _codes_enseignants(state)}
        for c in getattr(state, "courses", []) or []:
            connus |= {b.teacher.code.upper(): b.teacher.code.upper() for b in c.profs or [] if b.teacher and b.teacher.code}
    if cible not in connus:
        raise HTTPException(404, f"« {brut} » n'est pas connu du planning ({famille}).")
    return connus[cible]
