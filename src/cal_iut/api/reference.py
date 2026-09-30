"""Compléter une information de référence manquante — `/reference/...`.

Demande utilisateur (29/09/2026) : « quand on a un email manquant, peut-être
un numéro de salle Celcat manquant, etc., il faut pouvoir ajouter l'info et
l'enregistrer ». L'appli signalait ces manques à plusieurs endroits (pastille
« manquant » de l'annuaire, « adresse mail manquante » sur la fiche,
blocages de l'écran Celcat), chacun avec sa propre règle, et renvoyait vers
un fichier de `data/config/` — figé dans l'image Docker.

Ce module fait deux choses, et une seule fois chacune :

1. `manques(state)` : LA liste de tout ce qui manque (famille, entité,
   champ, où c'est utilisé, gravité), servie par `GET /reference/manques`
   et `GET /api/v1/manques`, et relue par chaque écran qui signale un manque.
2. une fonction « compléter » par famille — `completer_enseignant`,
   `completer_salle`, `completer_cours` — qui valide, persiste dans le
   volume (`data/state/`), met à jour l'état en mémoire, journalise
   (qui, quand, valeur d'avant) et avance la révision (`api/revision.py`)
   pour que les autres écrans se mettent à jour.

Où vont les valeurs (jamais dans `data/config/`, réécrit à chaque
déploiement) :
- mail, nom d'enseignant, intitulé de matière : `data/state/references.json`
  (`ingestion/surcharges_reference.py`), fusionné PAR-DESSUS la config au
  chargement — la saisie a le dernier mot (elle peut aussi CORRIGER une
  valeur du fichier, 29/09/2026), l'écran la marque « modifiée dans
  l'appli » et `DELETE` la retire (« Revenir à la valeur du fichier ») ;
- capacité et type d'une salle créée dans l'appli : `data/state/
  custom_rooms.json` (`api/custom_rooms.py`, déjà sa persistance) ;
- code Celcat d'une salle, d'un enseignant ou code module d'une matière :
  `data/state/celcat_mappings.json` (`celcat/mappings.py`, déjà sa
  persistance, lue par le worker à son passage suivant).

Droits : le rôle `edit` complète ou corrige mail, nom, intitulé, capacité et
type ; ce qui touche à Celcat reste `admin`, comme l'écran Celcat. Les
identifiants INTERNES Celcat des groupes et des matières ne se saisissent
pas ici : ce sont des numéros relevés par balayage (`celcat_groupes.yaml`,
`celcat_matieres.yaml`), qu'aucun utilisateur ne peut lire dans Celcat —
ils sont listés, avec le fichier où les régler, et `role_requis` vaut `None`.
"""

from __future__ import annotations

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

router = APIRouter(prefix="/reference", tags=["reference"])

Famille = Literal["enseignant", "salle", "cours", "groupe", "seance"]
Champ = Literal["email", "nom", "code_celcat", "capacite", "type", "intitule", "id_celcat", "salle"]
Gravite = Literal["bloque_celcat", "bloque_envoi_liens", "cosmetique"]

LIBELLES_CHAMP: dict[str, str] = {
    "email": "Adresse mail",
    "nom": "Nom complet",
    "code_celcat": "Correspondance Celcat",
    "capacite": "Capacité",
    "type": "Type de salle",
    "intitule": "Intitulé",
    "id_celcat": "Identifiant Celcat",
    "salle": "Salle",
}

ORDRE_GRAVITE = {"bloque_celcat": 0, "bloque_envoi_liens": 1, "cosmetique": 2}
ORDRE_FAMILLE = {"enseignant": 0, "salle": 1, "cours": 2, "groupe": 3, "seance": 4}


# ── Modèles ─────────────────────────────────────────────────────────────


class ManqueV1(BaseModel):
    id: str = Field(description="Clé stable : « famille:clé:champ ».")
    famille: Famille
    cle: str = Field(description="Code enseignant, identifiant de salle, code de matière, nom Celcat du groupe ou identifiant de séance.")
    libelle: str = Field(description="Nom lisible de l'entité.")
    champ: Champ
    champ_libelle: str
    gravite: Gravite = Field(
        description="`bloque_celcat` : la séance ne peut pas être recopiée dans Celcat ; "
        "`bloque_envoi_liens` : l'enseignant ne reçoit pas son lien personnel ; `cosmetique` : affichage seulement."
    )
    usage: str = Field(description="Où la donnée sert (« 36 séances placées »).")
    nb_seances: int
    role_requis: Literal["edit", "admin"] | None = Field(
        description="Rôle qui peut compléter depuis l'appli ; `null` = pas depuis l'appli (fichier de configuration)."
    )
    ou_completer: str
    ecran: dict[str, str | int] = Field(description="Écran où compléter (fragment d'URL de l'appli).")


class ManquesV1(BaseModel):
    revision: int
    modifie_le: str
    total: int
    par_gravite: dict[str, int]
    par_famille: dict[str, int]
    manques: list[ManqueV1]


class ContactEnseignantRequest(BaseModel):
    email: str = Field(max_length=254)


class EnseignantReferenceRequest(BaseModel):
    nom: str | None = Field(default=None, max_length=120)
    code_celcat: str | None = Field(default=None, max_length=40)


class SalleReferenceRequest(BaseModel):
    capacite: int | None = Field(default=None, ge=1, le=1000)
    type: str | None = Field(default=None, max_length=40)
    code_celcat: str | None = Field(default=None, max_length=80)


class CoursReferenceRequest(BaseModel):
    intitule: str | None = Field(default=None, max_length=160)
    code_celcat: str | None = Field(default=None, max_length=20)


class NouvelIntervenantRequest(BaseModel):
    nom: str = Field(default="", max_length=120, description="« Prénom Nom ».")
    code: str = Field(default="", max_length=10, description="2 à 4 lettres (normalisé en majuscules).")
    code_celcat: str | None = Field(default=None, max_length=40, description="Identifiant Celcat (un nombre), facultatif.")
    email: str | None = Field(default=None, max_length=254)
    confirmer: bool = Field(default=False, description="Créer malgré les avertissements (jamais malgré un bloquant).")


class ErreurIntervenant(BaseModel):
    champ: Literal["nom", "code", "code_celcat", "email"]
    statut: int = Field(description="400 : saisie invalide ; 409 : déjà pris.")
    message: str
    code_existant: str | None = Field(default=None, description="Enseignant qui porte déjà ce code / cette adresse.")


class AvertissementIntervenant(BaseModel):
    type: Literal["code_dans_celcat", "code_celcat_pris", "nom_proche"]
    titre: str
    message: str
    code_existant: str | None = None
    nom_existant: str | None = None
    fiche: bool = Field(default=False, description="`code_existant` a une fiche dans l'appli (lien).")
    bloquant: bool = Field(default=False, description="`confirmer` ne suffit pas : corriger la saisie.")


class VerificationIntervenant(BaseModel):
    code: str
    nom: str
    email: str | None
    code_celcat: str | None
    erreurs: list[ErreurIntervenant]
    avertissements: list[AvertissementIntervenant]
    suggestion_code: str | None = Field(default=None, description="Un code libre tiré du nom.")
    peut_creer: bool = Field(description="Aucune erreur ni avertissement bloquant (confirmation encore requise s'il y a des avertissements).")


class IntervenantCree(BaseModel):
    code: str
    nom: str
    email: str | None
    code_celcat: str | None
    cree_le: str
    avertissements_confirmes: list[AvertissementIntervenant]
    message: str
    revision: int


class ReferenceEnregistree(BaseModel):
    famille: Famille
    cle: str
    valeurs: dict[str, str | int]
    message: str
    revision: int


# ── Outils ──────────────────────────────────────────────────────────────


def _main():
    # Import tardif : `api/main.py` importe ce module pour monter le routeur.
    from cal_iut.api import main

    return main


def _par(request: Request) -> str:
    return str(getattr(getattr(request.state, "user", None), "email", "") or "")


def _est_admin(request: Request) -> bool:
    user = getattr(request.state, "user", None)
    return user is not None and user.role == "admin"


def _lire_table_yaml(chemin: Path) -> dict[str, object]:
    if not chemin.exists():
        return {}
    try:
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _ecran_codes(famille: str, cle: str) -> dict[str, str | int]:
    """La bonne ligne de l'onglet « Codes Celcat » de Référence (30/09/2026) :
    tout code Celcat y est listé, avec son origine."""
    return {"vue": "reference", "onglet": "codes-celcat", "famille": famille, "cle": cle}


def _usage(n: int) -> str:
    if not n:
        return "aucune séance placée"
    return f"{n} séance placée" if n == 1 else f"{n} séances placées"


# ── La liste des manques ────────────────────────────────────────────────

_memo: tuple[int, ManquesV1] | None = None
_verrou_memo = threading.Lock()


def manques() -> ManquesV1:
    """Tout ce qui manque, recalculé seulement quand la révision a avancé
    (≈ 0,2 s sur le planning réel, surtout la traduction Celcat)."""
    global _memo
    rev = revision.actuelle()
    memo = _memo
    if memo is not None and memo[0] == rev.numero:
        return memo[1]
    with _verrou_memo:
        rev = revision.actuelle()
        if _memo is not None and _memo[0] == rev.numero:
            return _memo[1]
        liste = _calculer_manques(_main().get_state())
        reponse = ManquesV1(
            revision=rev.numero,
            modifie_le=rev.iso(),
            total=len(liste),
            par_gravite=dict(Counter(m.gravite for m in liste)),
            par_famille=dict(Counter(m.famille for m in liste)),
            manques=liste,
        )
        if revision.actuelle().numero == rev.numero:
            _memo = (rev.numero, reponse)
        return reponse


def _calculer_manques(state: object) -> list[ManqueV1]:
    from cal_iut.api import custom_rooms
    from cal_iut.celcat.mapping import entrees_pour_state, load_celcat_config
    from cal_iut.ingestion import surcharges_reference
    from cal_iut.models.entities import RoomType

    payload = _main().payload_app_state()
    libelles: dict[str, str] = dict(payload.get("teacherLabels") or {})
    emails: dict[str, str] = dict(payload.get("teacherEmails") or {})
    timetable = list(getattr(state, "timetable", []) or [])
    sessions_by_id = getattr(state, "sessions_by_id", {}) or {}
    config_dir = Path(state.config_dir)
    cfg = load_celcat_config(config_dir)

    seances_par_prof: Counter[str] = Counter()
    seances_par_salle: Counter[str] = Counter()
    for p in timetable:
        for code in p.teacher_codes or []:
            seances_par_prof[code] += 1
        if getattr(p, "room_id", None):
            seances_par_salle[p.room_id] += 1

    sortie: list[ManqueV1] = []

    def ajouter(**champs: object) -> None:
        champ = str(champs["champ"])
        sortie.append(ManqueV1(
            id=f"{champs['famille']}:{champs['cle']}:{champ}",
            champ_libelle=LIBELLES_CHAMP[champ],
            usage=_usage(int(champs["nb_seances"])),
            **champs,
        ))

    # ── Enseignants : mail, nom, code Celcat ──
    for code in sorted(libelles):
        nom = libelles.get(code) or code
        n = seances_par_prof.get(code, 0)
        if not str(emails.get(code) or "").strip():
            ajouter(
                famille="enseignant", cle=code, libelle=nom, champ="email", gravite="bloque_envoi_liens",
                nb_seances=n, role_requis="edit",
                ou_completer="Annuaire des enseignants, fiche de l'enseignant ou « À traiter ».",
                ecran={"vue": "prof", "prof": code},
            )
        if nom.strip().upper() == code.upper():
            ajouter(
                famille="enseignant", cle=code, libelle=nom, champ="nom", gravite="cosmetique",
                nb_seances=n, role_requis="edit",
                ou_completer="Fiche de l'enseignant ou « À traiter ».",
                ecran={"vue": "prof", "prof": code},
            )
    # Code Celcat : seulement pour qui a des séances placées — c'est la
    # recopie de CES séances qui bloque (`mapping.py`, premier enseignant).
    voulus = cfg.sans_code  # « sans code (voulu) » : pas un manque (30/09/2026)
    for code, n in sorted(seances_par_prof.items()):
        if code.upper() not in cfg.enseignants and code.upper() not in voulus.get("enseignants", {}):
            ajouter(
                famille="enseignant", cle=code, libelle=libelles.get(code, code), champ="code_celcat",
                gravite="bloque_celcat", nb_seances=n, role_requis="admin",
                ou_completer="Référence → Codes Celcat, ou ici pour un administrateur.",
                ecran=_ecran_codes("enseignants", code),
            )

    # ── Salles : code Celcat, type imposé à la création ──
    imposes = custom_rooms.types_imposes()
    for room in sorted(getattr(state, "rooms", []) or [], key=lambda r: r.label.lower()):
        if room.room_type == RoomType.RESERVE:
            continue
        n = seances_par_salle.get(room.id, 0)
        if room.id not in cfg.salles and room.id not in voulus.get("salles", {}):
            ajouter(
                famille="salle", cle=room.id, libelle=room.label, champ="code_celcat", gravite="bloque_celcat",
                nb_seances=n, role_requis="admin",
                ou_completer="Référence → Codes Celcat ou fiche de la salle (administrateurs).",
                ecran=_ecran_codes("salles", room.id),
            )
        if room.id in imposes:
            ajouter(
                famille="salle", cle=room.id, libelle=room.label, champ="type", gravite="cosmetique",
                nb_seances=n, role_requis="edit",
                ou_completer="Fiche de la salle : le type « standard » a été posé d'office à sa création.",
                ecran={"vue": "salle", "salle": room.id},
            )

    # ── Matières : intitulé ──
    intitules: dict[str, str] = {}
    for s in getattr(state, "sessions", []) or []:
        intitules.setdefault(s.course_code, s.course_name)
    seances_par_cours = Counter(p.course_code for p in timetable)
    for code, nom in sorted(intitules.items()):
        if surcharges_reference.intitule_manquant(code, nom):
            ajouter(
                famille="cours", cle=code, libelle=code, champ="intitule", gravite="cosmetique",
                nb_seances=seances_par_cours.get(code, 0), role_requis="edit",
                ou_completer="« À traiter » ou fiche de la matière.",
                ecran={"vue": "cours", "cours": code},
            )

    # ── Celcat : matières et groupes (identifiants relevés, pas saisis) ──
    matieres_connues = codes_modules_releves(config_dir)
    groupes_connus = {str(k).strip().upper() for k in _lire_table_yaml(config_dir / "celcat_groupes.yaml")}
    modules_manquants: Counter[str] = Counter()
    groupes_manquants: Counter[str] = Counter()
    for entree in entrees_pour_state(state).values():
        if entree.course_code.upper() in voulus.get("cours", {}):
            continue
        code_module = cfg.modules.get(entree.course_code.upper())
        if not code_module or code_module.strip().upper() not in matieres_connues:
            modules_manquants[entree.course_code] += 1
        # Plusieurs groupes : bloqué pour une autre raison (un seul onglet
        # Celcat à la fois), pas faute d'identifiant.
        un_seul_groupe = entree.semestre and entree.groupe and "," not in entree.groupe
        if un_seul_groupe and entree.nom_groupe_celcat.strip().upper() not in groupes_connus:
            groupes_manquants[entree.nom_groupe_celcat] += 1
    for code, n in sorted(modules_manquants.items()):
        if not cfg.modules.get(code.upper()):
            # Le code module (« TSB… ») se lit dans Celcat : saisissable ici.
            ajouter(
                famille="cours", cle=code, libelle=intitules.get(code) or code, champ="code_celcat",
                gravite="bloque_celcat", nb_seances=n, role_requis="admin",
                ou_completer="Référence → Codes Celcat ou « À traiter » (administrateurs) : code module TSB… de la matière.",
                ecran=_ecran_codes("cours", code),
            )
        else:
            # Son identifiant INTERNE, lui, ne se lit pas : relevé et figé.
            ajouter(
                famille="cours", cle=code, libelle=intitules.get(code) or code, champ="id_celcat",
                gravite="bloque_celcat", nb_seances=n, role_requis=None,
                ou_completer=(
                    f"Se règle dans data/config/celcat_matieres.yaml : identifiant de « {cfg.modules[code.upper()]} » "
                    "à relever dans Celcat — déploiement."
                ),
                ecran=_ecran_codes("cours", code),
            )
    for nom, n in sorted(groupes_manquants.items()):
        ajouter(
            famille="groupe", cle=nom, libelle=nom, champ="id_celcat", gravite="bloque_celcat",
            nb_seances=n, role_requis=None,
            ou_completer="Se règle dans data/config/celcat_groupes.yaml : identifiant à relever dans Celcat — déploiement.",
            ecran=_ecran_codes("groupes", nom),
        )

    # ── Séances placées sans salle (« salle à définir ») : déjà
    # complétables en Vue Promo, listées ici pour que la liste soit entière.
    libelle_groupe = {g.id: g.label for g in getattr(state, "groups", []) or []}
    for p in timetable:
        if getattr(p, "room_id", None):
            continue
        session = sessions_by_id.get(p.session_id)
        if (getattr(session, "metadata", None) or {}).get("pause_midi"):
            continue
        type_seance = str(getattr(getattr(session, "session_type", None), "value", "") or "")
        groupes = ", ".join(libelle_groupe.get(g, g) for g in (p.group_ids or []))
        ajouter(
            famille="seance", cle=p.session_id,
            libelle=" · ".join(x for x in (p.course_code, type_seance, groupes) if x),
            champ="salle", gravite="bloque_celcat", nb_seances=1, role_requis="edit",
            ou_completer="Vue Promo : choisir la salle de la séance.",
            ecran={"vue": "promo", "sem": int(p.week), "jour": int(p.day)},
        )

    sortie.sort(key=lambda m: (ORDRE_GRAVITE[m.gravite], ORDRE_FAMILLE[m.famille], -m.nb_seances, m.libelle.lower()))
    return sortie


# ── Compléter : une fonction par famille ────────────────────────────────

_RE_EMAIL = re.compile(r"^[^@\s<>(),;:\"\[\]]+@[^@\s<>(),;:\"\[\]]+\.[^@\s<>(),;:\"\[\].]{2,}$")


def normaliser_email(brut: str) -> str:
    """Adresse nettoyée (espaces, minuscules) ou `ValueError` lisible."""
    email = str(brut or "").strip().lower()
    email = email.removeprefix("mailto:")
    if not email:
        raise ValueError("L'adresse mail est vide.")
    if not _RE_EMAIL.match(email) or ".." in email:
        raise ValueError(f"« {brut.strip()} » n'est pas une adresse mail valide (forme attendue : prenom.nom@univ-reims.fr).")
    return email


def _codes_enseignants(state: object) -> set[str]:
    from cal_iut.ingestion.enseignants import enseignants_declares

    codes = {c for s in getattr(state, "sessions", []) or [] for c in (s.teacher_codes or [])}
    codes |= {c for p in getattr(state, "timetable", []) or [] for c in (p.teacher_codes or [])}
    codes |= set(enseignants_declares(Path(state.config_dir)))
    return {c.strip().upper() for c in codes if c}


def _nom_officiel(state: object, code: str) -> str | None:
    """Le nom que donnent la maquette, la feuille des contraintes ou
    `enseignants_supplementaires.yaml` — None s'ils ne donnent que le code."""
    from cal_iut.export.html_view import _teacher_names
    from cal_iut.ingestion.enseignants import noms_officiels

    noms = {**noms_officiels(Path(state.config_dir)), **_teacher_names(state.sessions)}
    nom = str(noms.get(code) or "").strip()
    return nom if nom and nom.upper() != code.upper() else None


def completer_enseignant(
    state: object,
    code: str,
    *,
    email: str | None = None,
    nom: str | None = None,
    code_celcat: str | None = None,
    par: str = "",
    admin: bool = False,
) -> dict[str, str | int]:
    """Complète OU CORRIGE mail, nom et/ou code Celcat d'un enseignant connu.

    La saisie a le dernier mot sur la configuration (29/09/2026) ; la trace
    garde la valeur d'avant ET celle du fichier. Saisir exactement la valeur
    du fichier retire la surcharge au lieu d'en poser une identique.
    - mail : format validé, minuscules, refusé s'il est déjà celui d'un
      autre enseignant (un lien personnel partirait chez quelqu'un d'autre) ;
    - code Celcat : administrateurs, `api/codes_celcat.py` (le worker le
      lit à son passage suivant)."""
    from cal_iut.api import codes_celcat
    from cal_iut.export.html_view import _teacher_names
    from cal_iut.ingestion.config_loader import load_teacher_contacts, load_teacher_contacts_yaml
    from cal_iut.ingestion.enseignants import enseignants_declares

    code = str(code or "").strip().upper()
    if code not in _codes_enseignants(state):
        raise HTTPException(404, f"Enseignant « {code} » inconnu.")
    if email is None and nom is None and code_celcat is None:
        raise HTTPException(400, "Rien à enregistrer : indiquez une adresse, un nom ou un code Celcat.")
    config_dir = Path(state.config_dir)
    noms = {**enseignants_declares(config_dir), **{k: v for k, v in _teacher_names(state.sessions).items() if v != k}}
    ecrit: dict[str, str | int] = {}

    # Tout est validé AVANT la première écriture : une requête à deux champs
    # dont le second est refusé ne doit rien laisser à moitié enregistré.
    email_propre = None
    if email is not None:
        try:
            email_propre = normaliser_email(email)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        for autre, adresse in load_teacher_contacts(config_dir).items():
            if autre.upper() != code and adresse.strip().lower() == email_propre:
                raise HTTPException(
                    409, f"L'adresse {email_propre} est déjà celle de {noms.get(autre.upper(), autre)} ({autre})."
                )
    nom_propre = None
    if nom is not None:
        nom_propre = " ".join(str(nom).split())
        if len(nom_propre) < 2 or nom_propre.upper() == code:
            raise HTTPException(400, "Le nom complet est vide (attendu : « Prénom Nom »).")
    celcat_propre = None
    if code_celcat is not None:
        if not admin:
            raise HTTPException(403, "La correspondance Celcat est réservée aux administrateurs (écran Celcat).")
        # Même règle que l'onglet « Codes Celcat » : format, doublon refusé.
        celcat_propre = codes_celcat.valider_code(state, "enseignants", code, code_celcat)

    if email_propre is not None:
        du_fichier = load_teacher_contacts_yaml(config_dir).get(code)
        _poser_ou_retirer("enseignants", code, "email", email_propre, du_fichier, par)
        ecrit["email"] = email_propre
    if nom_propre is not None:
        _poser_ou_retirer("enseignants", code, "nom", nom_propre, _nom_officiel(state, code), par)
        ecrit["nom"] = nom_propre
    if celcat_propre is not None:
        codes_celcat.enregistrer_code(state, "enseignants", code, celcat_propre, par=par)
        ecrit["code_celcat"] = celcat_propre
    return ecrit


def _poser_ou_retirer(famille: str, cle: str, champ: str, valeur: str, du_fichier: str | None, par: str) -> None:
    """Enregistre la saisie — sauf si elle redit la valeur du fichier : on
    retire alors la surcharge (sinon l'écran marquerait « modifiée dans
    l'appli » une valeur identique, qui masquerait une future correction du
    fichier)."""
    from cal_iut.ingestion import surcharges_reference

    identique = du_fichier is not None and (
        du_fichier.strip().lower() == valeur.lower() if champ == "email" else du_fichier.strip() == valeur
    )
    if identique:
        surcharges_reference.effacer(famille, cle, champ, par=par, valeur_fichier=du_fichier)
    else:
        surcharges_reference.definir(famille, cle, champ, valeur, par=par, valeur_fichier=du_fichier)


def effacer_enseignant(state: object, code: str, champ: str, *, par: str = "") -> str:
    """« Revenir à la valeur du fichier » : retire la saisie (mail ou nom)."""
    from cal_iut.ingestion import surcharges_reference
    from cal_iut.ingestion.config_loader import load_teacher_contacts_yaml

    code = str(code or "").strip().upper()
    du_fichier = (
        load_teacher_contacts_yaml(Path(state.config_dir)).get(code) if champ == "email" else _nom_officiel(state, code)
    )
    retiree = surcharges_reference.effacer("enseignants", code, champ, par=par, valeur_fichier=du_fichier)
    if retiree is None:
        raise HTTPException(404, f"Aucune valeur modifiée dans l'appli pour {code} ({LIBELLES_CHAMP[champ].lower()}).")
    return retiree


def surcharges_pour_payload(state: object) -> dict[str, dict[str, dict[str, dict[str, object]]]]:
    """Ce qui a été modifié dans l'appli, avec la valeur d'origine — pour la
    marque « modifiée dans l'appli » et « Revenir à la valeur du fichier ».
    Réservé aux comptes (`_CLES_PRIVEES_PAYLOAD` : adresses)."""
    from cal_iut.ingestion import surcharges_reference
    from cal_iut.ingestion.config_loader import load_teacher_contacts_yaml

    doc = surcharges_reference._charger_pour_lecture()
    fichier = load_teacher_contacts_yaml(Path(state.config_dir))
    crees = doc.get("intervenants", {})
    sortie: dict[str, dict[str, dict[str, dict[str, object]]]] = {"enseignants": {}, "cours": {}}
    for code, champs in doc.get("enseignants", {}).items():
        for champ, entree in champs.items():
            if not isinstance(entree, dict):
                continue
            origine = fichier.get(code) if champ == "email" else _nom_officiel(state, code)
            # Le mail d'un intervenant créé dans l'appli n'a pas de « valeur
            # du fichier » à laquelle revenir : ce n'est pas une modification.
            if champ == "email" and code in crees and origine is None:
                continue
            sortie["enseignants"].setdefault(code, {})[champ] = {
                "valeur": entree.get("valeur"), "origine": origine,
                "modifie_le": entree.get("modifie_le"), "modifie_par": entree.get("modifie_par") or "",
            }
    for code, champs in doc.get("cours", {}).items():
        entree = champs.get("intitule")
        if isinstance(entree, dict):
            sortie["cours"][code] = {"intitule": {
                "valeur": entree.get("valeur"),
                "origine": surcharges_reference.intitule_d_origine(state.sessions, code),
                "modifie_le": entree.get("modifie_le"), "modifie_par": entree.get("modifie_par") or "",
            }}
    return sortie


def completer_salle(
    state: object,
    room_id: str,
    *,
    capacite: int | None = None,
    type_salle: str | None = None,
    code_celcat: str | None = None,
    par: str = "",
    admin: bool = False,
) -> dict[str, str | int]:
    """Complète capacité, type et/ou code Celcat d'une salle.

    Capacité et type : salles créées dans l'appli seulement (celles du
    bâtiment viennent de `rooms.yaml`, avec le code) — persistées dans
    `custom_rooms.json`, et l'état en mémoire suit tout de suite. Code
    Celcat : administrateurs, toute salle (`api/codes_celcat.py`)."""
    from cal_iut.api import codes_celcat, custom_rooms
    from cal_iut.ingestion import surcharges_reference
    from cal_iut.models.entities import RoomType

    salle = next((r for r in getattr(state, "rooms", []) or [] if r.id == room_id), None)
    if salle is None:
        raise HTTPException(404, f"Salle « {room_id} » inconnue.")
    if capacite is None and type_salle is None and code_celcat is None:
        raise HTTPException(400, "Rien à enregistrer : indiquez une capacité, un type ou un code Celcat.")

    type_enum = None
    if type_salle is not None:
        try:
            type_enum = RoomType(str(type_salle).strip())
        except ValueError:
            raise HTTPException(400, f"Type de salle inconnu : « {type_salle} ».") from None
        if type_enum in (RoomType.RESERVE, RoomType.COMBINED):
            raise HTTPException(400, f"Le type « {type_enum.value} » ne se choisit pas pour une salle ajoutée.")
    if (capacite is not None or type_enum is not None) and room_id not in custom_rooms.ids_personnalisees():
        raise HTTPException(
            409,
            f"{salle.label} est une salle du bâtiment : sa capacité et son type viennent de data/config/rooms.yaml.",
        )
    celcat_propre = None
    if code_celcat is not None:
        if not admin:
            raise HTTPException(403, "La correspondance Celcat est réservée aux administrateurs (écran Celcat).")
        celcat_propre = codes_celcat.valider_code(state, "salles", room_id, code_celcat)

    ecrit: dict[str, str | int] = {}
    if capacite is not None or type_enum is not None:
        avant = custom_rooms.completer_salle_personnalisee(room_id, capacity=capacite, room_type=type_enum)
        maj: dict[str, object] = {}
        if capacite is not None:
            maj["capacity"] = int(capacite)
            ecrit["capacite"] = int(capacite)
            surcharges_reference.journaliser("salles", room_id, "capacite", avant.get("capacity"), capacite, par=par)
        if type_enum is not None:
            maj["room_type"] = type_enum
            ecrit["type"] = type_enum.value
            surcharges_reference.journaliser("salles", room_id, "type", avant.get("room_type"), type_enum.value, par=par)
        salle_maj = salle.model_copy(update=maj)
        state.rooms = [salle_maj if r.id == room_id else r for r in state.rooms]
    if celcat_propre is not None:
        codes_celcat.enregistrer_code(state, "salles", room_id, celcat_propre, par=par)
        ecrit["code_celcat"] = celcat_propre
    return ecrit


_RE_CODE_MODULE = re.compile(r"^TSB[0-9A-Z]{4,6}$")


def codes_modules_releves(config_dir: Path) -> set[str]:
    """Codes modules Celcat dont l'identifiant interne est relevé
    (`celcat_matieres.yaml`) : les seuls que l'écriture sait retrouver."""
    return {str(k).strip().upper() for k in _lire_table_yaml(Path(config_dir) / "celcat_matieres.yaml")}


def valider_code_module(config_dir: Path, brut: str) -> str:
    """Code module Celcat (« TSBZ1M01 », « TSB0305C ») nettoyé, ou 400.

    Forme relevée sur `celcat.yaml::modules` et `celcat_matieres.yaml` :
    « TSB » + 4 à 6 chiffres ou majuscules. Et il doit être RELEVÉ : un code
    absent de `celcat_matieres.yaml` bloquerait plus loin, à l'écriture
    (« RessourceIntrouvable »), loin de la saisie."""
    code = str(brut or "").strip().upper()
    if not _RE_CODE_MODULE.match(code):
        raise HTTPException(400, f"« {str(brut).strip()} » n'est pas un code module Celcat (forme attendue : TSBZ1M01).")
    if code not in codes_modules_releves(config_dir):
        raise HTTPException(
            400,
            f"Le module {code} n'est pas dans le relevé des matières Celcat (data/config/celcat_matieres.yaml) : "
            "son identifiant interne doit y être ajouté d'abord.",
        )
    return code


def completer_cours(
    state: object,
    code: str,
    *,
    intitule: str | None = None,
    code_celcat: str | None = None,
    par: str = "",
    admin: bool = False,
) -> dict[str, str | int]:
    """Complète ou corrige l'intitulé d'une matière (rôle `edit`, la saisie
    a le dernier mot sur la maquette), et/ou son code module Celcat
    (administrateurs, `api/codes_celcat.py`, famille `cours`)."""
    from cal_iut.api import codes_celcat
    from cal_iut.ingestion import surcharges_reference

    code = str(code or "").strip()
    seances = [s for s in getattr(state, "sessions", []) or [] if s.course_code == code]
    if not seances:
        raise HTTPException(404, f"Matière « {code} » inconnue.")
    if intitule is None and code_celcat is None:
        raise HTTPException(400, "Rien à enregistrer : indiquez un intitulé ou un code module Celcat.")
    propre = None
    if intitule is not None:
        propre = " ".join(str(intitule).split())
        if surcharges_reference.intitule_manquant(code, propre):
            raise HTTPException(400, "L'intitulé est vide (ou n'est que le code).")
    module = None
    if code_celcat is not None:
        if not admin:
            raise HTTPException(403, "La correspondance Celcat est réservée aux administrateurs (écran Celcat).")
        module = codes_celcat.valider_code(state, "cours", code, code_celcat)

    ecrit: dict[str, str | int] = {}
    if propre is not None:
        origine = surcharges_reference.intitule_d_origine(state.sessions, code)
        _poser_ou_retirer("cours", code, "intitule", propre, origine, par)
        if origine is not None and origine == propre:
            surcharges_reference.retablir_intitule(state.sessions, getattr(state, "courses", None), code)
        else:
            surcharges_reference.appliquer_intitules(state.sessions, getattr(state, "courses", None))
        ecrit["intitule"] = propre
    if module is not None:
        codes_celcat.enregistrer_code(state, "cours", code, module, par=par)
        ecrit["code_celcat"] = module
    return ecrit


def effacer_intitule(state: object, code: str, *, par: str = "") -> str:
    """« Revenir à la valeur du fichier » pour l'intitulé d'une matière."""
    from cal_iut.ingestion import surcharges_reference

    code = str(code or "").strip()
    origine = surcharges_reference.intitule_d_origine(state.sessions, code)
    retiree = surcharges_reference.effacer("cours", code, "intitule", par=par, valeur_fichier=origine)
    if retiree is None:
        raise HTTPException(404, f"Aucun intitulé modifié dans l'appli pour {code}.")
    surcharges_reference.retablir_intitule(state.sessions, getattr(state, "courses", None), code)
    return retiree


# ── Nouvel intervenant ──────────────────────────────────────────────────
#
# Demande utilisateur (30/09/2026, admin) : « ajoute la possibilité de créer
# un intervenant ». Jusque-là : une entrée dans
# `enseignants_supplementaires.yaml`, une ligne dans `celcat.yaml`, un
# déploiement. Un intervenant créé ici vit dans `data/state/references.json`
# (`surcharges_reference.intervenants`) et est lu par
# `ingestion/enseignants.py` EXACTEMENT comme une entrée du fichier : il
# apparaît partout où apparaissent les enseignants (annuaire, fiche,
# « Nouvelle séance », Codes Celcat, API v1…).
#
# GARDE-FOUS — cas réel à l'origine : « Anne Grenet », proposée sous AGR
# avec l'identifiant Celcat 3233. Or `celcat.yaml` dit `AGR: "38321"  # Gram
# AMBROISE` (une autre personne : ses séances partiraient en paie sous son
# identifiant) et `AGT: "3233"  # GRENET ANNE` (la même personne, déjà là).
# D'où, en plus des refus (code pris par un enseignant connu, formats,
# adresse déjà attribuée) :
# - un code présent dans `celcat.yaml` pour une AUTRE personne : avertissement ;
# - un code Celcat déjà porté par un autre trigramme : avertissement
#   BLOQUANT (même règle de doublon que l'onglet Codes Celcat) ;
# - un nom qui ressemble à un enseignant connu (accents, casse, ordre
#   prénom/nom, commentaires de `celcat.yaml` compris) : avertissement.
# Un avertissement non bloquant se franchit par `confirmer=true`.

_RE_CODE_INTERVENANT = re.compile(r"^[A-Z]{2,4}$")


def _jetons_nom(nom: str) -> frozenset[str]:
    """« Anne-Sophie DIEHL » -> {"anne", "sophie", "diehl"} : sans accents,
    sans casse, sans ordre."""
    import unicodedata

    texte = unicodedata.normalize("NFD", str(nom or ""))
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    return frozenset(m for m in re.split(r"[^a-z]+", texte) if m)


def noms_proches(a: str, b: str) -> bool:
    """Même personne, vraisemblablement : mêmes mots (dans n'importe quel
    ordre), ou tous les mots de l'un (deux au moins) dans l'autre —
    « Anne Grenet » ~ « GRENET ANNE » ~ « Anne Grenet-Martin »."""
    ja, jb = _jetons_nom(a), _jetons_nom(b)
    if not ja or not jb:
        return False
    if ja == jb:
        return True
    petit, grand = (ja, jb) if len(ja) <= len(jb) else (jb, ja)
    return len(petit) >= 2 and petit <= grand


def _noms_connus(state: object) -> dict[str, str]:
    """Trigramme -> nom affiché, pour tout enseignant connu de l'appli."""
    from cal_iut.api import codes_celcat

    noms: dict[str, str] = {}
    for c in getattr(state, "courses", []) or []:
        for t in [getattr(b, "teacher", None) for b in c.profs or []] + [c.lead]:
            if t is not None and t.code and (t.prenom or t.nom):
                noms.setdefault(t.code.strip().upper(), f"{t.prenom} {t.nom}".strip())
    noms.update({k: v for k, v in codes_celcat._libelles(state, "enseignants").items() if v and v != k})
    return noms


def codes_enseignants_pris(state: object) -> set[str]:
    """Tout trigramme déjà connu : planning, maquette, feuille des
    contraintes, `enseignants_supplementaires.yaml`, intervenants créés dans
    l'appli, disponibilités, annuaire des mails. Un code de cette liste ne
    se crée pas (il existe)."""
    from cal_iut.api import codes_celcat
    from cal_iut.ingestion.config_loader import load_teacher_contacts_yaml

    codes = set(codes_celcat.enseignants_connus(state))
    codes |= {
        str(d.teacher_code).strip().upper()
        for d in getattr(state, "teacher_availability", []) or []
        if getattr(d, "teacher_code", None)
    }
    codes |= {c.strip().upper() for c in load_teacher_contacts_yaml(Path(state.config_dir))}
    return {c for c in codes if c}


def _suggerer_code(nom: str, pris: set[str]) -> str | None:
    """Un trigramme libre tiré du nom (« Prénom Nom » : initiale du prénom,
    puis lettres du nom), ni pris ni présent dans `celcat.yaml`."""
    import unicodedata

    texte = unicodedata.normalize("NFD", nom)
    mots = ["".join(c for c in m if c.isalpha()).upper() for m in texte.split()]
    mots = [m for m in ("".join(ch for ch in m if "A" <= ch <= "Z") for m in mots) if m]
    if len(mots) < 2:
        return None
    prenom, famille = mots[0], "".join(mots[1:])
    candidats = [prenom[0] + famille[0] + famille[1:2], prenom[0] + famille[0] + famille[-1]]
    candidats += [prenom[0] + famille[0] + x for x in famille[2:]]
    candidats += [prenom[:2] + famille[0]]
    candidats += [prenom[0] + famille[0] + x for x in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    for c in candidats:
        if len(c) == 3 and c not in pris:
            return c
    return None


def verifier_intervenant(
    state: object,
    *,
    nom: str,
    code: str,
    code_celcat: str | None = None,
    email: str | None = None,
) -> VerificationIntervenant:
    """Tout ce qui s'oppose à la création, sans rien écrire : erreurs
    (refus) et avertissements. Sert la validation en direct de la modale
    (`POST /reference/enseignants/verifier`) ET la création elle-même :
    une seule règle."""
    from cal_iut.api import codes_celcat
    from cal_iut.ingestion.config_loader import load_teacher_contacts

    config_dir = Path(state.config_dir)
    cfg = codes_celcat._config(config_dir)
    erreurs: list[ErreurIntervenant] = []
    avertissements: list[AvertissementIntervenant] = []
    connus = _noms_connus(state)
    pris = codes_enseignants_pris(state)
    # Ceux qui ont une fiche dans l'appli (lien « Voir sa fiche ») : la
    # liste de l'annuaire, pas toute la maquette.
    fiches = set(codes_celcat._libelles(state, "enseignants"))
    dans_celcat = cfg.noms_fichier_enseignants

    nom_propre = " ".join(str(nom or "").split())
    code_propre = "".join(str(code or "").split()).upper()
    if len(nom_propre) < 3 or not any(ch.isalpha() for ch in nom_propre):
        erreurs.append(ErreurIntervenant(champ="nom", statut=400, message="Le nom complet est obligatoire (« Prénom Nom »)."))
    if not code_propre:
        erreurs.append(ErreurIntervenant(champ="code", statut=400, message="Le code est obligatoire (2 à 4 lettres, ex. AGN)."))
    elif not _RE_CODE_INTERVENANT.match(code_propre):
        erreurs.append(ErreurIntervenant(
            champ="code", statut=400,
            message=f"« {code_propre} » n'est pas un code d'enseignant : 2 à 4 lettres sans accent (ex. AGN).",
        ))
    elif code_propre in pris:
        qui = connus.get(code_propre)
        erreurs.append(ErreurIntervenant(
            champ="code", statut=409, code_existant=code_propre if code_propre in fiches else None,
            message=(
                f"Le code {code_propre} est déjà pris" + (f" par {qui}" if qui else "")
                + " : choisissez-en un autre."
            ),
        ))

    email_propre = None
    if str(email or "").strip():
        try:
            email_propre = normaliser_email(str(email))
        except ValueError as exc:
            erreurs.append(ErreurIntervenant(champ="email", statut=400, message=str(exc)))
        else:
            for autre, adresse in load_teacher_contacts(config_dir).items():
                if adresse.strip().lower() == email_propre:
                    autre = autre.strip().upper()
                    qui = connus.get(autre)
                    erreurs.append(ErreurIntervenant(
                        champ="email", statut=409, code_existant=autre if autre in fiches else None,
                        message=f"L'adresse {email_propre} est déjà celle de {qui + ' ' if qui else ''}({autre}).",
                    ))
                    break

    celcat_propre = None
    if str(code_celcat or "").strip():
        try:
            celcat_propre = codes_celcat._normaliser("enseignants", config_dir, str(code_celcat))
        except HTTPException as exc:
            erreurs.append(ErreurIntervenant(champ="code_celcat", statut=exc.status_code, message=str(exc.detail)))

    def libelle_celcat(autre: str) -> str:
        """Le nom sous lequel Celcat connaît `autre` : le commentaire de
        `celcat.yaml` d'abord (c'est lui qui dit à qui va la paie)."""
        commentaire = dans_celcat.get(autre)
        return commentaire if commentaire and commentaire != autre else connus.get(autre, autre)

    # ── Le code est-il celui de quelqu'un d'autre dans Celcat ? ──
    code_valide = bool(code_propre) and not any(e.champ == "code" for e in erreurs)
    if code_valide and code_propre in dans_celcat:
        nom_celcat = dans_celcat[code_propre]
        meme_personne = nom_celcat != code_propre and bool(nom_propre) and noms_proches(nom_celcat, nom_propre)
        ident = (cfg.connus.get("enseignants") or {}).get(code_propre)
        if not meme_personne:
            qui = nom_celcat if nom_celcat != code_propre else "une autre entrée"
            if ident:
                message = (
                    f"celcat.yaml associe déjà {code_propre} à {qui} (identifiant Celcat {ident}) : créé sous ce "
                    f"code, l'intervenant partirait dans Celcat — et en paie — sous l'identifiant de {qui}. "
                    "Choisissez un autre code si ce n'est pas la même personne."
                )
            else:
                message = (
                    f"celcat.yaml réserve déjà {code_propre} à {qui} (sans identifiant Celcat pour l'instant). "
                    "Choisissez un autre code si ce n'est pas la même personne."
                )
            bloquant = bool(celcat_propre and ident and celcat_propre != ident)
            if bloquant:
                message += f" Le code Celcat saisi ({celcat_propre}) ne peut pas remplacer celui du fichier."
            avertissements.append(AvertissementIntervenant(
                type="code_dans_celcat", titre=f"{code_propre} est {qui} dans Celcat", message=message,
                code_existant=code_propre, nom_existant=nom_celcat if nom_celcat != code_propre else None,
                fiche=False, bloquant=bloquant,
            ))
        elif celcat_propre and ident and celcat_propre != ident:
            erreurs.append(ErreurIntervenant(
                champ="code_celcat", statut=409, code_existant=code_propre,
                message=(
                    f"celcat.yaml donne déjà l'identifiant {ident} à {code_propre} ({nom_celcat}) : "
                    "laissez le code Celcat vide, il sera repris du fichier."
                ),
            ))

    # ── Le code Celcat est-il déjà celui d'un autre trigramme ? ──
    if celcat_propre:
        for autre, valeur in sorted(cfg.enseignants.items()):
            if autre == code_propre or str(valeur).strip() != celcat_propre:
                continue
            qui = libelle_celcat(autre)
            avertissements.append(AvertissementIntervenant(
                type="code_celcat_pris", titre=f"{celcat_propre} est déjà {autre} ({qui})",
                message=(
                    f"Ce code Celcat est déjà celui de {autre} ({qui}) — c'est peut-être la même personne ? "
                    "Deux enseignants ne partagent pas un identifiant Celcat : ouvrez sa fiche, "
                    "ou créez sans code Celcat."
                ),
                code_existant=autre, nom_existant=qui, fiche=autre in fiches, bloquant=True,
            ))

    # ── Le nom ressemble-t-il à quelqu'un de connu ? ──
    if len(nom_propre) >= 3:
        vus: set[str] = set()
        candidats = [(c, n) for c, n in connus.items()] + [
            (c, n) for c, n in dans_celcat.items() if n and n != c
        ]
        for autre, nom_autre in candidats:
            if autre == code_propre or autre in vus or not noms_proches(nom_autre, nom_propre):
                continue
            vus.add(autre)
            fiche = autre in fiches
            if autre in pris:
                message = (
                    f"{connus.get(autre, nom_autre)} ({autre}) est déjà dans l'appli. "
                    "Ouvrez sa fiche plutôt que de créer un doublon."
                )
            else:
                ident = cfg.enseignants.get(autre)
                message = (
                    f"celcat.yaml connaît {nom_autre} sous {autre}"
                    + (f" (identifiant Celcat {ident})" if ident else "")
                    + f" : si c'est la même personne, créez-la sous le code {autre}."
                )
            avertissements.append(AvertissementIntervenant(
                type="nom_proche", titre=f"Cette personne existe peut-être déjà sous le code {autre}",
                message=message, code_existant=autre, nom_existant=connus.get(autre, nom_autre), fiche=fiche,
            ))

    suggestion = None
    if nom_propre and (not code_valide or code_propre in dans_celcat):
        suggestion = _suggerer_code(nom_propre, pris | set(dans_celcat))
    return VerificationIntervenant(
        code=code_propre, nom=nom_propre, email=email_propre, code_celcat=celcat_propre,
        erreurs=erreurs, avertissements=avertissements, suggestion_code=suggestion,
        peut_creer=not erreurs and not any(a.bloquant for a in avertissements),
    )


def creer_intervenant(
    state: object,
    *,
    nom: str,
    code: str,
    code_celcat: str | None = None,
    email: str | None = None,
    confirmer: bool = False,
    par: str = "",
) -> IntervenantCree:
    """LA création d'un intervenant (admin). Refus : 400 (saisie), 409
    (déjà pris). Avertissements : 409 avec `{"message", "avertissements"}`
    tant que `confirmer` n'est pas vrai — toujours pour un bloquant.

    Écrit l'intervenant ET son mail en une seule écriture atomique
    (`surcharges_reference.creer_intervenant`), puis son code Celcat par
    l'écriture de l'onglet Codes Celcat (`codes_celcat.valider_code` /
    `enregistrer_code` : même format, même refus des doublons, même trace) ;
    un code Celcat refusé à ce dernier moment défait la création."""
    from cal_iut.api import codes_celcat
    from cal_iut.ingestion import surcharges_reference

    v = verifier_intervenant(state, nom=nom, code=code, code_celcat=code_celcat, email=email)
    if v.erreurs:
        # Le plus grave d'abord : un « déjà pris » (409) avant un format (400).
        premiere = sorted(v.erreurs, key=lambda e: -e.statut)[0]
        raise HTTPException(premiere.statut, premiere.message)
    bloquants = [a for a in v.avertissements if a.bloquant]
    if bloquants or (v.avertissements and not confirmer):
        raise HTTPException(409, {
            "message": (
                "À corriger avant de créer : " + " ; ".join(a.titre for a in bloquants) + "."
                if bloquants else
                "À vérifier avant de créer : " + " ; ".join(a.titre for a in v.avertissements)
                + ". Renvoyez avec « confirmer » pour créer quand même."
            ),
            "avertissements": [a.model_dump() for a in v.avertissements],
            "suggestion_code": v.suggestion_code,
        })

    cfg = codes_celcat._config(Path(state.config_dir))
    ecrire_celcat = v.code_celcat is not None and (cfg.connus.get("enseignants") or {}).get(v.code) != v.code_celcat
    if ecrire_celcat:
        # Dernière vérification, la même que l'onglet (verrou, doublon).
        codes_celcat.valider_code(state, "enseignants", v.code, v.code_celcat)
    try:
        fiche = surcharges_reference.creer_intervenant(v.code, v.nom, email=v.email, par=par)
    except ValueError:
        raise HTTPException(409, f"Le code {v.code} est déjà pris : choisissez-en un autre.") from None
    if ecrire_celcat:
        try:
            codes_celcat.enregistrer_code(state, "enseignants", v.code, v.code_celcat, par=par)
        except Exception:
            surcharges_reference.supprimer_intervenant(v.code, par=par)
            raise
    rev = revision.incrementer(f"reference:enseignant:{v.code}:creation")
    return IntervenantCree(
        code=v.code, nom=v.nom, email=v.email, code_celcat=v.code_celcat, cree_le=str(fiche["cree_le"]),
        avertissements_confirmes=v.avertissements, message="Intervenant créé.", revision=rev.numero,
    )


def seances_de(state: object, code: str) -> int:
    """Séances (placées ou non, maquette ou créées à la main) de `code`."""
    ids = {s.id for s in getattr(state, "sessions", []) or [] if code in (s.teacher_codes or [])}
    ids |= {p.session_id for p in getattr(state, "timetable", []) or [] if code in (p.teacher_codes or [])}
    return len(ids)


def supprimer_intervenant(state: object, code: str, *, par: str = "") -> str:
    """Retire un intervenant créé dans l'appli, s'il n'a AUCUNE séance —
    avec son mail, son nom corrigé et son code Celcat saisis. Rend son nom."""
    from cal_iut.celcat import mappings
    from cal_iut.ingestion import surcharges_reference

    code = str(code or "").strip().upper()
    fiche = surcharges_reference.intervenants().get(code)
    if fiche is None:
        raise HTTPException(
            404, f"{code} n'a pas été créé dans l'appli : il vient de la configuration, il ne se supprime pas ici."
        )
    n = seances_de(state, code)
    if n:
        raise HTTPException(
            409,
            f"{fiche['nom']} ({code}) a {n} séance{'s' if n > 1 else ''} : "
            "retirez-les ou changez-en l'enseignant avant de le supprimer.",
        )
    surcharges_reference.supprimer_intervenant(code, par=par)
    if code in mappings.table("enseignants"):
        from cal_iut.api import codes_celcat

        codes_celcat.effacer_code(state, "enseignants", code, par=par)
    mappings.retirer_sans_code("enseignants", code)
    return str(fiche["nom"])


def intervenants_pour_payload(state: object) -> dict[str, dict[str, object]]:
    """Intervenants créés dans l'appli, pour la fiche (« ajouté dans l'appli
    par X le JJ/MM », « Supprimer » sans séance). Réservé aux comptes
    (`_CLES_PRIVEES_PAYLOAD` : adresse de l'auteur)."""
    from cal_iut.ingestion import surcharges_reference

    return {
        code: {
            "nom": fiche.get("nom"), "cree_le": fiche.get("cree_le"), "cree_par": fiche.get("cree_par") or "",
            "nb_seances": seances_de(state, code),
        }
        for code, fiche in sorted(surcharges_reference.intervenants().items())
    }


def _reponse(famille: str, cle: str, ecrit: dict[str, str | int], message: str) -> ReferenceEnregistree:
    rev = revision.incrementer(f"reference:{famille}:{cle}")
    return ReferenceEnregistree(famille=famille, cle=cle, valeurs=ecrit, message=message, revision=rev.numero)


# ── Routes ──────────────────────────────────────────────────────────────


@router.get("/manques", response_model=ManquesV1, dependencies=[Depends(accounts.require_role("read_only"))])
def lister_manques() -> ManquesV1:
    """Tout ce qui manque, pour tout compte actif (lecture seule comprise :
    le manque reste affiché, sans bouton). Aucune valeur n'y figure — ni
    adresse, ni code : seulement ce qui manque, et où."""
    return manques()


@router.put(
    "/enseignants/{code}/contact",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def completer_contact(code: str, body: ContactEnseignantRequest, request: Request) -> ReferenceEnregistree:
    state = _main().get_state()
    ecrit = completer_enseignant(state, code, email=body.email, par=_par(request))
    return _reponse("enseignant", code.strip().upper(), ecrit, "Adresse enregistrée.")


@router.put(
    "/enseignants/{code}",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def completer_fiche_enseignant(code: str, body: EnseignantReferenceRequest, request: Request) -> ReferenceEnregistree:
    state = _main().get_state()
    ecrit = completer_enseignant(
        state, code, nom=body.nom, code_celcat=body.code_celcat, par=_par(request), admin=_est_admin(request)
    )
    return _reponse("enseignant", code.strip().upper(), ecrit, "Enregistré.")


@router.put(
    "/salles/{room_id}",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def completer_fiche_salle(room_id: str, body: SalleReferenceRequest, request: Request) -> ReferenceEnregistree:
    state = _main().get_state()
    ecrit = completer_salle(
        state, room_id, capacite=body.capacite, type_salle=body.type, code_celcat=body.code_celcat,
        par=_par(request), admin=_est_admin(request),
    )
    return _reponse("salle", room_id, ecrit, "Enregistré.")


@router.put(
    "/cours/{code}",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def completer_fiche_cours(code: str, body: CoursReferenceRequest, request: Request) -> ReferenceEnregistree:
    state = _main().get_state()
    ecrit = completer_cours(
        state, code, intitule=body.intitule, code_celcat=body.code_celcat, par=_par(request),
        admin=_est_admin(request),
    )
    return _reponse("cours", code.strip(), ecrit, "Enregistré.")


# « Revenir à la valeur du fichier » : retire une saisie faite dans l'appli
# (mail, nom, intitulé). Tracé au journal comme une saisie.


@router.delete(
    "/enseignants/{code}/contact",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def effacer_contact(code: str, request: Request) -> ReferenceEnregistree:
    retiree = effacer_enseignant(_main().get_state(), code, "email", par=_par(request))
    return _reponse("enseignant", code.strip().upper(), {"email": retiree}, "Valeur du fichier rétablie.")


@router.delete(
    "/enseignants/{code}/nom",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def effacer_nom(code: str, request: Request) -> ReferenceEnregistree:
    retiree = effacer_enseignant(_main().get_state(), code, "nom", par=_par(request))
    return _reponse("enseignant", code.strip().upper(), {"nom": retiree}, "Valeur du fichier rétablie.")


@router.delete(
    "/cours/{code}/intitule",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("edit"))],
)
@ecriture_planning
def effacer_intitule_cours(code: str, request: Request) -> ReferenceEnregistree:
    retiree = effacer_intitule(_main().get_state(), code, par=_par(request))
    return _reponse("cours", code.strip(), {"intitule": retiree}, "Valeur du fichier rétablie.")


# « Nouvel intervenant » (30/09/2026) : administrateurs — même règle que le
# reste des données Celcat (un intervenant, c'est d'abord un trigramme et un
# identifiant Celcat, donc une paie).


@router.post(
    "/enseignants/verifier",
    response_model=VerificationIntervenant,
    dependencies=[Depends(accounts.require_role("admin"))],
)
def verifier_nouvel_intervenant(body: NouvelIntervenantRequest) -> VerificationIntervenant:
    """Validation en direct de la modale : erreurs et avertissements, sans
    rien écrire."""
    return verifier_intervenant(
        _main().get_state(), nom=body.nom, code=body.code, code_celcat=body.code_celcat, email=body.email
    )


@router.post(
    "/enseignants",
    response_model=IntervenantCree,
    status_code=201,
    dependencies=[Depends(accounts.require_role("admin"))],
)
@ecriture_planning
def creer_nouvel_intervenant(body: NouvelIntervenantRequest, request: Request) -> IntervenantCree:
    return creer_intervenant(
        _main().get_state(), nom=body.nom, code=body.code, code_celcat=body.code_celcat, email=body.email,
        confirmer=body.confirmer, par=_par(request),
    )


@router.delete(
    "/enseignants/{code}",
    response_model=ReferenceEnregistree,
    dependencies=[Depends(accounts.require_role("admin"))],
)
@ecriture_planning
def supprimer_nouvel_intervenant(code: str, request: Request) -> ReferenceEnregistree:
    nom = supprimer_intervenant(_main().get_state(), code, par=_par(request))
    return _reponse("enseignant", code.strip().upper(), {"nom": nom}, f"{nom} supprimé.")
