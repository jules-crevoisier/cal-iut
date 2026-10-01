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

VERSION 2 (30/09/2026, réponses de l'utilisateur) :
- « il faut pouvoir modifier QUE ceux qu'on n'a pas » : un code CONNU —
  `celcat.yaml` ou la maquette (`celcat_modules_maquette.yaml`, cf.
  `celcat/codes_maquette.py`) — est VERROUILLÉ : 409 « code déjà connu ».
  Ne se saisissent que les manquants ; une saisie se modifie, ou s'efface
  (« Revenir à manquant »). Une saisie plus ancienne portée sur un code
  désormais connu reste appliquée (rien ne casse), en lecture seule, avec
  un avertissement si elle diffère ; l'effacer rétablit le code connu ;
- « sans code (voulu) » : une entité qu'on ne veut PAS envoyer à Celcat,
  avec un motif — préenregistrée dans `celcat.yaml::sans_code_voulu`
  (décisions de Kyllian), ou saisie ici par un admin, réversible. Elle ne
  compte plus comme manquante, et rien ne part (`mapping.py`,
  `EntreeCelcat.non_envoyee`).

Tout se lit dans `load_celcat_config` (`connus`, `origines`, `sans_code`) :
aucune autre lecture des fichiers de codes ici.
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
Origine = Literal["fichier", "maquette", "appli", "manquant", "voulu", "regle"]

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

LIBELLE_ORIGINE = {
    "fichier": "fichier de configuration (celcat.yaml)",
    "maquette": "maquette",
    "regle": "envoi sans module (règle)",
}


def note_regle(regle) -> str:
    """Ce que fait une règle d'envoi de cours sans module, en une phrase."""
    qui = ", ".join(regle.enseignants) if regle.enseignants else "tous les enseignants"
    return (
        f"Envoyé sans module : catégorie {regle.categorie}, remarque « {regle.remarque} », "
        f"département {regle.departement} ; interventions de {qui}"
        + (f". {regle.motif}" if regle.motif else ".")
    )


# ── Modèles ─────────────────────────────────────────────────────────────


class LigneCodeCelcat(BaseModel):
    cle: str = Field(description="Code de cours, identifiant de salle, trigramme, nom Celcat du groupe.")
    libelle: str
    semestre: str | None = None
    parcours: str | None = None
    type_salle: str | None = None
    capacite: int | None = None
    nb_seances: int = Field(description="Séances placées au planning.")
    code: str | None = Field(description="Le code qui part vers Celcat.")
    code_connu: str | None = Field(description="Le code connu hors saisie : fichier ou maquette.")
    origine: Origine
    origine_detail: str | None = Field(
        default=None, description="« maquette (corrigé M→C) », « celcat.yaml »… ; pour « voulu » : fichier ou appli."
    )
    code_maquette: str | None = Field(default=None, description="Cours : le code tel que la maquette l'écrit.")
    motif_sans_code: str | None = Field(default=None, description="« Sans code (voulu) » : pourquoi.")
    saisi_le: str | None = None
    saisi_par: str | None = Field(default=None, description="Adresse du compte — administrateurs seulement.")
    valeur_avant: str | None = Field(default=None, description="Administrateurs seulement.")
    alerte: str | None = Field(default=None, description="Code présent mais inutilisable tel quel.")
    avertissement: str | None = Field(default=None, description="Saisie ancienne qui diffère d'un code connu.")
    note: str | None = None
    modifiable: bool = Field(description="Ce compte peut saisir ou modifier ce code (manquant ou saisi).")
    peut_revenir: bool = Field(default=False, description="Ce compte peut retirer la saisie.")
    peut_marquer_sans_code: bool = False
    peut_retirer_sans_code: bool = False


class FamilleCodesCelcat(BaseModel):
    famille: FamilleCode
    aide: str
    exemple: str
    modifiable: bool
    total: int
    sans_code: int = Field(description="Manquants (le « sans code voulu » n'en fait pas partie).")
    sans_code_bloquants: int = Field(description="Manquants avec des séances placées : bloque Celcat.")
    saisis: int
    voulus: int = Field(default=0, description="« Sans code (voulu) ».")
    sans_module: int = Field(default=0, description="Envoyés sans module par une règle de celcat.yaml.")
    maquette: int = Field(default=0, description="Codes préenregistrés depuis la maquette.")
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


class SansCodeRequest(BaseModel):
    famille: FamilleCode
    cle: str = Field(min_length=1, max_length=120)
    motif: str = Field(max_length=200)


class CodeCelcatEnregistre(BaseModel):
    famille: FamilleCode
    cle: str
    code: str | None
    origine: Origine
    message: str
    revision: int


# ── Lecture : tout vient de `load_celcat_config` ────────────────────────


def _config(config_dir: Path):
    from cal_iut.celcat.mapping import load_celcat_config

    return load_celcat_config(Path(config_dir))


def _groupes_du_fichier(config_dir: Path) -> dict[str, str]:
    """`celcat_groupes.yaml` : nom Celcat -> identifiant interne (lecture seule)."""
    chemin = Path(config_dir) / "celcat_groupes.yaml"
    if not chemin.exists():
        return {}
    try:
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in data.items() if v} if isinstance(data, dict) else {}


def codes_effectifs(config_dir: Path, famille: str) -> dict[str, str]:
    """Le code qui part vers Celcat, par famille."""
    if famille == "groupes":
        return _groupes_du_fichier(config_dir)
    cfg = _config(config_dir)
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


def _refus_groupes() -> HTTPException:
    return HTTPException(409, "L'identifiant Celcat d'un groupe ne se saisit pas dans l'appli : " + NOTE_GROUPES)


def _normaliser(famille: str, config_dir: Path, brut: str) -> str:
    texte = " ".join(str(brut or "").split())
    if not texte:
        raise HTTPException(400, "Le code Celcat est vide. Pour retirer une saisie, utilisez « Revenir à manquant ».")
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
    raise _refus_groupes()


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


def _libelle_origine(cfg, famille: str, cle: str) -> str:
    origine = (cfg.origines.get(famille) or {}).get(cle, "")
    if origine == "appli":
        origine = "fichier" if cle in (cfg.connus.get(famille) or {}) else origine
    return LIBELLE_ORIGINE.get(origine, origine)


def _exiger_modifiable(cfg, famille: str, cle: str) -> None:
    """Verrou (30/09/2026, « il faut pouvoir modifier QUE ceux qu'on n'a
    pas ») : un code connu ne se change pas ici, et une entité « sans code
    (voulu) » doit d'abord perdre ce statut."""
    connu = (cfg.connus.get(famille) or {}).get(cle)
    if connu:
        source = "maquette" if str((cfg.origines.get(famille) or {}).get(cle, "")).startswith("maquette") else None
        if source is None:
            source = "maquette" if cle not in _codes_fichier_seul(cfg, famille) else "fichier de configuration"
        raise HTTPException(
            409,
            f"Code déjà connu ({source}) : {connu}. Il ne se modifie pas dans l'appli — "
            "seuls les codes manquants se saisissent ici.",
        )
    voulu = (cfg.sans_code.get(famille) or {}).get(cle)
    if voulu:
        raise HTTPException(
            409,
            f"{cle} est marqué « sans code (voulu) » ({voulu.get('motif') or 'sans motif'}) : "
            "retirez d'abord ce statut pour saisir un code.",
        )
    _refuser_si_regle(cfg, famille, cle)


def _refuser_si_regle(cfg, famille: str, cle: str) -> None:
    """Un cours envoyé sans module par une règle (celcat.yaml) ne prend ni
    code module ni « sans code (voulu) » dans l'appli : la règle du fichier
    décide."""
    if famille == "cours" and cfg.regle_sans_module(cle) is not None:
        raise HTTPException(
            409,
            f"{cle} est envoyé à Celcat sans module (règle de celcat.yaml, « regles_envoi ») : "
            "il ne prend pas de code module. La règle se modifie dans ce fichier.",
        )


def _codes_fichier_seul(cfg, famille: str) -> set[str]:
    """Les clés connues par `celcat.yaml` (et non par la maquette)."""
    connus = cfg.connus.get(famille) or {}
    origines = cfg.origines.get(famille) or {}
    return {cle for cle in connus if not str(origines.get(cle, "")).startswith("maquette")}


def valider_code(state: object, famille: str, cle: str, brut: str) -> str:
    """Le code nettoyé, ou une `HTTPException` qui dit quoi corriger.

    Verrou d'abord (code connu, « sans code voulu »), puis format propre à
    la famille, puis REFUS d'un code déjà porté par une autre entité de la
    même famille : deux salles sous le même nom Celcat y seraient
    confondues, deux enseignants se partageraient une paie, deux cours un
    même module. Exception documentée : une salle fusionnée et l'une de ses
    moitiés (`_salles_jumelees`)."""
    if famille not in _FAMILLE_SURCOUCHE:
        raise _refus_groupes()
    from cal_iut.celcat import mappings

    config_dir = Path(state.config_dir)
    cfg = _config(config_dir)
    cle_propre = mappings.cle_normalisee(_FAMILLE_SURCOUCHE[famille], cle)
    _exiger_modifiable(cfg, famille, cle_propre)
    code = _normaliser(famille, config_dir, brut)
    rooms = list(getattr(state, "rooms", []) or [])
    libelles = _libelles(state, famille)
    effectifs = {"cours": cfg.modules, "salles": cfg.salles, "enseignants": cfg.enseignants}[famille]
    for autre, valeur in sorted(effectifs.items()):
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
    """Persiste un code DÉJÀ validé (`valider_code`) — donc pour une entité
    sans code connu. Trace au journal commun, avec la valeur d'avant.
    Rend l'origine résultante (« appli »)."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    famille_surcouche = _FAMILLE_SURCOUCHE[famille]
    cle_propre = mappings.cle_normalisee(famille_surcouche, cle)
    with _verrou:
        avant = codes_effectifs(Path(state.config_dir), famille).get(cle_propre)
        mappings.definir(famille_surcouche, cle_propre, code, par=par, valeur_fichier=None)
        surcharges_reference.journaliser(
            _FAMILLE_JOURNAL[famille], cle_propre, "code_celcat", avant, code, par=par, valeur_fichier=None
        )
    return "appli"


def definir_code(state: object, famille: str, cle: str, brut: str, *, par: str = "") -> tuple[str, str]:
    """Valide puis enregistre. Rend `(code, origine)`."""
    code = valider_code(state, famille, cle, brut)
    return code, enregistrer_code(state, famille, cle, code, par=par)


def effacer_code(state: object, famille: str, cle: str, *, par: str = "") -> str | None:
    """Retire la saisie : « Revenir à manquant », ou — pour une saisie
    ancienne sur un code désormais connu — rétablit ce code connu. Rend le
    code qui part ensuite (None : manquant). 404 sans saisie."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    if famille not in _FAMILLE_SURCOUCHE:
        raise _refus_groupes()
    config_dir = Path(state.config_dir)
    famille_surcouche = _FAMILLE_SURCOUCHE[famille]
    cle_propre = mappings.cle_normalisee(famille_surcouche, cle)
    with _verrou:
        connu = (_config(config_dir).connus.get(famille) or {}).get(cle_propre)
        retiree = mappings.retirer(famille_surcouche, cle_propre)
        if retiree is None:
            raise HTTPException(404, f"Aucun code Celcat saisi dans l'appli pour {cle_propre}.")
        surcharges_reference.journaliser(
            _FAMILLE_JOURNAL[famille], cle_propre, "code_celcat", retiree.get("valeur"), connu, par=par,
            valeur_fichier=connu,
        )
    return connu


def marquer_sans_code(state: object, famille: str, cle: str, motif: str, *, par: str = "") -> str:
    """« Sans code (voulu) » : seulement pour une entité SANS code (ni
    connu, ni saisi). Motif obligatoire (3 caractères au moins). Tracé."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    if famille not in _FAMILLE_SURCOUCHE:
        raise _refus_groupes()
    famille_surcouche = _FAMILLE_SURCOUCHE[famille]
    cle_propre = mappings.cle_normalisee(famille_surcouche, cle)
    motif_propre = " ".join(str(motif or "").split())
    if len(motif_propre) < 3:
        raise HTTPException(400, "Le motif est obligatoire : dites en quelques mots pourquoi il n'y a pas de code.")
    with _verrou:
        cfg = _config(Path(state.config_dir))
        _refuser_si_regle(cfg, famille, cle_propre)
        effectif = {"cours": cfg.modules, "salles": cfg.salles, "enseignants": cfg.enseignants}[famille].get(cle_propre)
        if effectif:
            raise HTTPException(
                409, f"{cle_propre} a un code Celcat ({effectif}) : seul ce qui n'en a pas peut être marqué « sans code »."
            )
        voulu = (cfg.sans_code.get(famille) or {}).get(cle_propre)
        if voulu and voulu.get("source") == "fichier":
            raise HTTPException(409, f"{cle_propre} est déjà « sans code (voulu) » dans celcat.yaml.")
        avant = voulu.get("motif") if voulu else None
        mappings.definir_sans_code(famille_surcouche, cle_propre, motif_propre, par=par)
        surcharges_reference.journaliser(
            _FAMILLE_JOURNAL[famille], cle_propre, "sans_code_voulu", avant, motif_propre, par=par
        )
    return motif_propre


def retirer_sans_code(state: object, famille: str, cle: str, *, par: str = "") -> None:
    """Retire un « sans code (voulu) » saisi dans l'appli : l'entité
    redevient manquante. Celui du fichier ne se retire pas ici."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    if famille not in _FAMILLE_SURCOUCHE:
        raise _refus_groupes()
    famille_surcouche = _FAMILLE_SURCOUCHE[famille]
    cle_propre = mappings.cle_normalisee(famille_surcouche, cle)
    with _verrou:
        cfg = _config(Path(state.config_dir))
        voulu = (cfg.sans_code.get(famille) or {}).get(cle_propre)
        if voulu and voulu.get("source") == "fichier":
            raise HTTPException(
                409, f"« Sans code (voulu) » de {cle_propre} vient de celcat.yaml : il se retire dans ce fichier."
            )
        retiree = mappings.retirer_sans_code(famille_surcouche, cle_propre)
        if retiree is None:
            raise HTTPException(404, f"{cle_propre} n'est pas marqué « sans code (voulu) » dans l'appli.")
        surcharges_reference.journaliser(
            _FAMILLE_JOURNAL[famille], cle_propre, "sans_code_voulu", retiree.get("motif"), None, par=par
        )


# ── La liste complète ───────────────────────────────────────────────────


def _nom_groupe_celcat(semestre: str, libelle: str) -> str:
    from cal_iut.celcat.mapping import libelle_groupe_celcat

    return f"BUT MMI {semestre} {libelle_groupe_celcat(libelle)}".strip()


def lister(state: object, *, admin: bool) -> CodesCelcat:
    from cal_iut.api.reference import codes_modules_releves
    from cal_iut.celcat import codes_maquette, mappings
    from cal_iut.celcat.instantane import lire
    from cal_iut.models.entities import RoomType

    config_dir = Path(state.config_dir)
    cfg = _config(config_dir)
    timetable = list(getattr(state, "timetable", []) or [])
    sessions_by_id = getattr(state, "sessions_by_id", {}) or {}
    surcouche = mappings.charger()
    maquette = codes_maquette.lire(config_dir)
    # Codes de la maquette NON repris par prudence : proposés, jamais posés.
    exclus = codes_maquette.lire_exclus(config_dir)
    effectifs = {"cours": cfg.modules, "salles": cfg.salles, "enseignants": cfg.enseignants}

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
        effectif = effectifs[famille].get(cle)
        connu = (cfg.connus.get(famille) or {}).get(cle)
        saisie = (surcouche.get(_FAMILLE_SURCOUCHE[famille]) or {}).get(cle)
        voulu = (cfg.sans_code.get(famille) or {}).get(cle) if not effectif else None
        origine_brute = (cfg.origines.get(famille) or {}).get(cle, "")
        regle = cfg.regle_sans_module(cle) if famille == "cours" else None
        avertissement = None
        if regle is not None:
            # Envoi sans module (règle) : ni code, ni manque, ni « non envoyé ».
            # Ce qui part est décrit par la règle — rien ne se saisit ici.
            reste = {k: v for k, v in champs.items() if k not in ("note", "alerte")}
            return LigneCodeCelcat(
                cle=cle,
                code=None,
                code_connu=None,
                origine="regle",
                origine_detail=LIBELLE_ORIGINE["regle"],
                motif_sans_code=regle.motif or None,
                note=note_regle(regle),
                modifiable=False,
                **reste,
            )
        if saisie and connu:
            # Saisie antérieure au verrou : appliquée, en lecture seule.
            origine: str = "maquette" if cle not in _codes_fichier_seul(cfg, famille) else "fichier"
            detail = origine_brute if origine_brute != "appli" else None
            if str(saisie.get("valeur") or "").strip().upper() != connu.strip().upper():
                avertissement = (
                    f"Une saisie dans l'appli ({saisie.get('valeur')}) passe devant le code connu ({connu}) : "
                    "elle reste appliquée. « Revenir au code connu » la retire."
                )
                origine = "appli"
                detail = None
            else:
                detail = LIBELLE_ORIGINE.get(origine)
        elif saisie:
            origine, detail = "appli", None
        elif effectif:
            origine = "maquette" if origine_brute.startswith("maquette") else "fichier"
            detail = origine_brute if origine == "maquette" else "celcat.yaml"
        elif voulu:
            origine, detail = "voulu", ("celcat.yaml" if voulu.get("source") == "fichier" else "appli")
        else:
            origine, detail = "manquant", None
        voulu_appli = bool(voulu and voulu.get("source") == "appli")
        modifiable = admin and not connu and not voulu
        return LigneCodeCelcat(
            cle=cle,
            code=effectif or None,
            code_connu=connu or None,
            origine=origine,
            origine_detail=detail,
            code_maquette=(
                ((maquette.get(cle) or {}).get("maquette") or (exclus.get(cle) or {}).get("maquette") or None)
                if famille == "cours" else None
            ),
            motif_sans_code=(voulu or {}).get("motif") if origine == "voulu" else None,
            saisi_le=(saisie or {}).get("ajoute_le") or ((voulu or {}).get("ajoute_le") if voulu_appli else None) or None,
            saisi_par=(
                (str((saisie or {}).get("ajoute_par") or "") or ((voulu or {}).get("ajoute_par") if voulu_appli else "") or None)
                if admin else None
            ),
            valeur_avant=(saisie or {}).get("valeur_avant") if admin else None,
            avertissement=avertissement,
            modifiable=modifiable,
            peut_revenir=admin and bool(saisie),
            peut_marquer_sans_code=admin and origine == "manquant",
            peut_retirer_sans_code=admin and voulu_appli,
            **champs,
        )

    familles: dict[str, list[LigneCodeCelcat]] = {}

    # ── Cours : la maquette de tous les parcours et semestres ──
    releves = codes_modules_releves(config_dir)
    cours: dict[str, dict[str, object]] = {}
    for c in getattr(state, "courses", []) or []:
        cours.setdefault(c.code.upper(), {
            "libelle": c.name or c.code, "semestre": c.semestre or None, "parcours": c.parcours or None,
        })
    for s in getattr(state, "sessions", []) or []:
        cours.setdefault(s.course_code.upper(), {
            "libelle": s.course_name or s.course_code, "semestre": s.semestre or None, "parcours": s.parcours or None,
        })
    lignes: list[LigneCodeCelcat] = []
    for cle_maj, c in sorted(cours.items()):
        code = cfg.modules.get(cle_maj)
        alerte = None
        if code and code.strip().upper() not in releves:
            alerte = (
                f"{code} n'est pas dans le relevé des matières Celcat (celcat_matieres.yaml) : "
                "l'envoi échouera tant que son identifiant interne n'y est pas."
            )
        note = None
        if not code and cle_maj in exclus:
            note = f"Code de la maquette non repris : {exclus[cle_maj]['raison']}."
        lignes.append(ligne(
            "cours", cle_maj, libelle=str(c["libelle"]), semestre=c["semestre"], parcours=c["parcours"],
            nb_seances=par_cours.get(cle_maj, 0), alerte=alerte, note=note,
        ))
    familles["cours"] = lignes

    # ── Salles : rooms.yaml + salles ajoutées ──
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
            nb_seances=par_salle.get(r.id, 0), note=note,
        ))
    familles["salles"] = lignes

    # ── Enseignants : maquette, séances, enseignants déclarés ──
    codes = enseignants_connus(state)
    noms = _libelles(state, "enseignants")
    familles["enseignants"] = [
        ligne("enseignants", code, libelle=noms.get(code) or code, nb_seances=par_prof.get(code, 0))
        for code in sorted(c for c in codes if c)
    ]

    # ── Groupes : ceux du fichier + ceux qu'attend le planning (lecture seule) ──
    fichier_groupes = _groupes_du_fichier(config_dir)
    fichier_maj = {k.upper(): v for k, v in fichier_groupes.items()}
    noms_groupes: dict[str, str] = {k.upper(): k for k in fichier_groupes}
    for s in getattr(state, "sessions", []) or []:
        semestre = str(s.semestre or "").strip()
        if semestre and len(s.group_ids or []) == 1:
            nom = _nom_groupe_celcat(semestre, libelle_groupe.get(s.group_ids[0], s.group_ids[0]))
            noms_groupes.setdefault(nom.upper(), nom)
    lignes = []
    for cle_maj, nom in sorted(noms_groupes.items(), key=lambda kv: _ordre_groupe(kv[1])):
        valeur = fichier_maj.get(cle_maj)
        semestre = nom.split()[2] if len(nom.split()) > 2 else None
        lignes.append(LigneCodeCelcat(
            cle=nom, libelle=nom, semestre=semestre, nb_seances=par_groupe.get(cle_maj, 0),
            code=valeur, code_connu=valeur, origine="fichier" if valeur else "manquant",
            origine_detail="celcat_groupes.yaml" if valeur else None, note=NOTE_GROUPES, modifiable=False,
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
    salles_relevees |= set(cfg.salles.values())
    suggestions = {"cours": sorted(releves), "salles": sorted(salles_relevees), "enseignants": [], "groupes": []}

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
            voulus=sum(1 for l in lignes if l.origine == "voulu"),
            sans_module=sum(1 for l in lignes if l.origine == "regle"),
            maquette=sum(1 for l in lignes if l.origine == "maquette"),
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
    return CodeCelcatEnregistre(
        famille=body.famille, cle=cle, code=code, origine=origine, message="Enregistré pour Celcat.",
        revision=rev.numero,
    )


@router.delete("", response_model=CodeCelcatEnregistre, dependencies=[Depends(accounts.require_role("admin"))])
@ecriture_planning
def effacer(famille: FamilleCode, cle: str, request: Request) -> CodeCelcatEnregistre:
    state = _main().get_state()
    cle = entite_canonique(state, famille, cle)
    connu = effacer_code(state, famille, cle, par=_par(request))
    rev = revision.incrementer(f"codes-celcat:{famille}:{cle}")
    origine = "manquant"
    if connu:
        cfg = _config(Path(state.config_dir))
        origine = "maquette" if str((cfg.origines.get(famille) or {}).get(cle, "")).startswith("maquette") else "fichier"
    return CodeCelcatEnregistre(
        famille=famille, cle=cle, code=connu, origine=origine,
        message=f"Code connu rétabli ({connu})." if connu else "Saisie retirée : de nouveau manquant.",
        revision=rev.numero,
    )


@router.put("/sans-code", response_model=CodeCelcatEnregistre, dependencies=[Depends(accounts.require_role("admin"))])
@ecriture_planning
def definir_sans_code(body: SansCodeRequest, request: Request) -> CodeCelcatEnregistre:
    state = _main().get_state()
    cle = entite_canonique(state, body.famille, body.cle)
    marquer_sans_code(state, body.famille, cle, body.motif, par=_par(request))
    rev = revision.incrementer(f"codes-celcat:{body.famille}:{cle}:sans-code")
    return CodeCelcatEnregistre(
        famille=body.famille, cle=cle, code=None, origine="voulu",
        message="Marqué « sans code (voulu) » : rien ne part vers Celcat.", revision=rev.numero,
    )


@router.delete("/sans-code", response_model=CodeCelcatEnregistre, dependencies=[Depends(accounts.require_role("admin"))])
@ecriture_planning
def effacer_sans_code(famille: FamilleCode, cle: str, request: Request) -> CodeCelcatEnregistre:
    state = _main().get_state()
    cle = entite_canonique(state, famille, cle)
    retirer_sans_code(state, famille, cle, par=_par(request))
    rev = revision.incrementer(f"codes-celcat:{famille}:{cle}:sans-code")
    return CodeCelcatEnregistre(
        famille=famille, cle=cle, code=None, origine="manquant",
        message="« Sans code (voulu) » retiré : de nouveau manquant.", revision=rev.numero,
    )


def enseignants_connus(state: object) -> set[str]:
    """Les trigrammes du planning : séances, placements, enseignants
    déclarés, et toute la maquette (intervenants et responsables). La même
    liste pour l'onglet et pour la saisie."""
    from cal_iut.api.reference import _codes_enseignants

    codes = set(_codes_enseignants(state))
    for c in getattr(state, "courses", []) or []:
        for bloc in c.profs or []:
            if bloc.teacher and bloc.teacher.code:
                codes.add(bloc.teacher.code.strip().upper())
        if c.lead and c.lead.code:
            codes.add(c.lead.code.strip().upper())
    return {c for c in codes if c}


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
        connus = {c: c for c in enseignants_connus(state)}
    if cible not in connus:
        raise HTTPException(404, f"« {brut} » n'est pas connu du planning ({famille}).")
    return connus[cible]
