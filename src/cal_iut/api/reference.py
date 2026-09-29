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
  (`ingestion/surcharges_reference.py`), fusionné SOUS la config au
  chargement — la config garde le dernier mot ;
- capacité et type d'une salle créée dans l'appli : `data/state/
  custom_rooms.json` (`api/custom_rooms.py`, déjà sa persistance) ;
- code Celcat d'une salle ou d'un enseignant : `data/state/
  celcat_mappings.json` (`celcat/mappings.py`, déjà sa persistance, lue par
  le worker à son passage suivant).

Droits : le rôle `edit` complète mail, nom, intitulé, capacité et type ; ce
qui touche à Celcat reste `admin`, comme l'écran Celcat. Les identifiants
Celcat des groupes et des matières ne se saisissent pas ici : ce sont des
numéros internes relevés par balayage (cf. `celcat_groupes.yaml`), qu'aucun
utilisateur ne peut lire dans Celcat — ils sont listés, avec l'endroit où
les ajouter, mais `role_requis` vaut `None`.
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
    intitule: str = Field(max_length=160)


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
    for code, n in sorted(seances_par_prof.items()):
        if code.upper() not in cfg.enseignants:
            ajouter(
                famille="enseignant", cle=code, libelle=libelles.get(code, code), champ="code_celcat",
                gravite="bloque_celcat", nb_seances=n, role_requis="admin",
                ou_completer="Écran Celcat, ou ici pour un administrateur.",
                ecran={"vue": "celcat"},
            )

    # ── Salles : code Celcat, type imposé à la création ──
    imposes = custom_rooms.types_imposes()
    for room in sorted(getattr(state, "rooms", []) or [], key=lambda r: r.label.lower()):
        if room.room_type == RoomType.RESERVE:
            continue
        n = seances_par_salle.get(room.id, 0)
        if room.id not in cfg.salles:
            ajouter(
                famille="salle", cle=room.id, libelle=room.label, champ="code_celcat", gravite="bloque_celcat",
                nb_seances=n, role_requis="admin",
                ou_completer="Fiche de la salle ou écran Celcat (administrateurs).",
                ecran={"vue": "salle", "salle": room.id},
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
    matieres_connues = {str(k).strip().upper() for k in _lire_table_yaml(config_dir / "celcat_matieres.yaml")}
    groupes_connus = {str(k).strip().upper() for k in _lire_table_yaml(config_dir / "celcat_groupes.yaml")}
    modules_manquants: Counter[str] = Counter()
    groupes_manquants: Counter[str] = Counter()
    for entree in entrees_pour_state(state).values():
        code_module = cfg.modules.get(entree.course_code.upper())
        if not code_module or code_module.strip().upper() not in matieres_connues:
            modules_manquants[entree.course_code] += 1
        # Plusieurs groupes : bloqué pour une autre raison (un seul onglet
        # Celcat à la fois), pas faute d'identifiant.
        un_seul_groupe = entree.semestre and entree.groupe and "," not in entree.groupe
        if un_seul_groupe and entree.nom_groupe_celcat.strip().upper() not in groupes_connus:
            groupes_manquants[entree.nom_groupe_celcat] += 1
    for code, n in sorted(modules_manquants.items()):
        sans_code = not cfg.modules.get(code.upper())
        ajouter(
            famille="cours", cle=code, libelle=intitules.get(code) or code, champ="code_celcat",
            gravite="bloque_celcat", nb_seances=n, role_requis=None,
            ou_completer=(
                "data/config/celcat.yaml (section modules), puis celcat_matieres.yaml — déploiement."
                if sans_code
                else f"data/config/celcat_matieres.yaml : identifiant de « {cfg.modules[code.upper()]} » à relever — déploiement."
            ),
            ecran={"vue": "celcat"},
        )
    for nom, n in sorted(groupes_manquants.items()):
        ajouter(
            famille="groupe", cle=nom, libelle=nom, champ="id_celcat", gravite="bloque_celcat",
            nb_seances=n, role_requis=None,
            ou_completer="data/config/celcat_groupes.yaml : identifiant à relever dans Celcat — déploiement.",
            ecran={"vue": "celcat"},
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
    """Complète mail, nom et/ou code Celcat d'un enseignant CONNU.

    - mail : format validé, minuscules, refusé s'il est déjà celui d'un
      autre enseignant (un lien personnel partirait chez quelqu'un d'autre)
      ou si `teacher_contacts.yaml` en donne déjà un (il se corrige là) ;
    - nom : refusé si la maquette ou la feuille officielle en donne un ;
    - code Celcat : administrateurs, `celcat/mappings.py` (le worker le lit
      à son passage suivant).
    Une saisie faite ICI se corrige ici : elle n'est pas « déjà connue »."""
    from cal_iut.celcat import mappings
    from cal_iut.export.html_view import _teacher_names
    from cal_iut.ingestion import surcharges_reference
    from cal_iut.ingestion.config_loader import load_teacher_contacts, load_teacher_contacts_yaml
    from cal_iut.ingestion.enseignants import enseignants_declares, noms_officiels

    code = str(code or "").strip().upper()
    if code not in _codes_enseignants(state):
        raise HTTPException(404, f"Enseignant « {code} » inconnu.")
    if email is None and nom is None and code_celcat is None:
        raise HTTPException(400, "Rien à enregistrer : indiquez une adresse, un nom ou un code Celcat.")
    config_dir = Path(state.config_dir)
    noms = {**enseignants_declares(config_dir), **{k: v for k, v in _teacher_names(state.sessions).items() if v != k}}
    libelle = noms.get(code, code)
    ecrit: dict[str, str | int] = {}

    # Tout est validé AVANT la première écriture : une requête à deux champs
    # dont le second est refusé ne doit rien laisser à moitié enregistré.
    email_propre = None
    if email is not None:
        try:
            email_propre = normaliser_email(email)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        du_fichier = load_teacher_contacts_yaml(config_dir).get(code)
        if du_fichier:
            raise HTTPException(
                409,
                f"L'adresse de {libelle} vient de data/config/teacher_contacts.yaml ({du_fichier}) : "
                "elle se corrige dans ce fichier.",
            )
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
        officiel = {**noms_officiels(config_dir), **_teacher_names(state.sessions)}.get(code, code)
        if officiel.strip().upper() != code:
            raise HTTPException(
                409, f"Le nom de {code} est déjà connu de la maquette ou de la feuille des contraintes : « {officiel} »."
            )
    celcat_propre = None
    if code_celcat is not None:
        if not admin:
            raise HTTPException(403, "La correspondance Celcat est réservée aux administrateurs (écran Celcat).")
        celcat_propre = str(code_celcat).strip()
        if not celcat_propre or celcat_propre == "0":
            raise HTTPException(400, "Le code Celcat est vide.")

    if email_propre is not None:
        surcharges_reference.definir("enseignants", code, "email", email_propre, par=par)
        ecrit["email"] = email_propre
    if nom_propre is not None:
        surcharges_reference.definir("enseignants", code, "nom", nom_propre, par=par)
        ecrit["nom"] = nom_propre
    if celcat_propre is not None:
        avant = mappings.table("enseignants").get(code)
        mappings.definir("enseignants", code, celcat_propre, par=par)
        surcharges_reference.journaliser("enseignants", code, "code_celcat", avant, celcat_propre, par=par)
        ecrit["code_celcat"] = celcat_propre
    return ecrit


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
    Celcat : administrateurs, toute salle (`celcat/mappings.py`)."""
    from cal_iut.api import custom_rooms
    from cal_iut.celcat import mappings
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
        celcat_propre = str(code_celcat).strip()
        if not celcat_propre:
            raise HTTPException(400, "Le nom Celcat de la salle est vide.")

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
        avant_celcat = mappings.table("salles").get(room_id)
        mappings.definir("salles", room_id, celcat_propre, par=par)
        surcharges_reference.journaliser("salles", room_id, "code_celcat", avant_celcat, celcat_propre, par=par)
        ecrit["code_celcat"] = celcat_propre
    return ecrit


def completer_cours(state: object, code: str, *, intitule: str, par: str = "") -> dict[str, str | int]:
    """Complète l'intitulé d'une matière qui n'en a pas (maquette muette,
    ou qui ne rend que le code). Les séances en mémoire le prennent tout de
    suite ; au prochain chargement, `surcharges_reference.appliquer_intitules`
    le repose."""
    from cal_iut.ingestion import surcharges_reference

    code = str(code or "").strip()
    seances = [s for s in getattr(state, "sessions", []) or [] if s.course_code == code]
    if not seances:
        raise HTTPException(404, f"Matière « {code} » inconnue.")
    propre = " ".join(str(intitule or "").split())
    if surcharges_reference.intitule_manquant(code, propre):
        raise HTTPException(400, "L'intitulé est vide (ou n'est que le code).")
    deja_saisi = (surcharges_reference.origine("cours", code, "intitule") or {}).get("valeur")
    actuel = seances[0].course_name
    if not surcharges_reference.intitule_manquant(code, actuel) and actuel != deja_saisi:
        raise HTTPException(409, f"La matière {code} a déjà un intitulé dans la maquette : « {actuel} ».")
    surcharges_reference.definir("cours", code, "intitule", propre, par=par)
    surcharges_reference.appliquer_intitules(
        state.sessions, getattr(state, "courses", None),
        remplacables={code: deja_saisi} if deja_saisi else None,
    )
    return {"intitule": propre}


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
    ecrit = completer_cours(state, code, intitule=body.intitule, par=_par(request))
    return _reponse("cours", code.strip(), ecrit, "Intitulé enregistré.")
