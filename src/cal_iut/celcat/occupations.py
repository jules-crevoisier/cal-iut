"""Occupations HORS MMI relevées dans Celcat — salles et enseignants.

Demande de Kyllian Bresson (responsable, 01/10/2026) : « Lecture de Celcat
pour vérifier les disponibilités des salles et des enseignants ». Deux cas :

1. l'amphi H.018 (« Amphi 3 MMI » dans Celcat) est réservable par
   l'administration, un autre département ou pour un évènement saisi hors de
   l'outil : s'il est pris dans Celcat, il ne l'est pas pour nous ;
2. un enseignant intervient dans plusieurs départements : si le département
   TC programme Anthony Froli (AFR) le lundi de 10h00 à 12h30, le placer chez
   nous à ce moment-là est un conflit, et l'outil doit le dire.

QUI LIT, QUI UTILISE. Celcat n'est joignable que par le VPN de l'URCA, monté
dans le seul conteneur `celcat-nuit` (cf. `celcat/instantane.py` pour le
pourquoi). Ce module est donc coupé en deux, comme l'instantané :

- côté SIDECAR (`relever`, `PageSimulee`) : lecture RPC en rôle consultation
  (`udlTimetables.load` filtré par `RoomIDs` / `StaffIDs`, par lots), tri
  « à nous / pas à nous », dépliage des semaines, et dépôt ATOMIQUE de
  `data/state/celcat_occupations_externes.json` ;
- côté BACKEND (`api/occupations_externes.py`) : relecture de ce fichier
  (rechargé quand il change), conversion en créneaux, contraintes.

Ce qui est ici est PUR (aucun réseau, aucun navigateur importé) : la page est
injectée, ce qui rend tout testable sans VPN.

LECTURE SEULE, TOUJOURS. Aucun import du module d'écriture, de modification
ou de suppression ; seules `rpc.appeler` / `rpc.charger_ressources` servent.

CE QUI EST « À NOUS » (donc ignoré) — `motif_a_nous` :

- un évènement que NOUS avons écrit : son `event_id` est au journal de
  synchronisation (`celcat/sync.py`), ou ses `notes` portent un identifiant
  de séance cal-iut (`ecriture.charge_utile` y met `session_id`) ;
- un COURS (catégorie entre crochets, cf. `lecture.est_cours`) d'un groupe
  « BUT MMI … », ou du département MMI sans groupe : il est (ou devrait
  être) dans notre planning, et la comparaison s'occupe des écarts ;
- un jour férié, un évènement global, suspendu ou sans horaire.

Tout le reste est une occupation EXTERNE : cours d'un autre département,
réunion, jury, réservation administrative — y compris une réunion du
département MMI saisie seulement dans Celcat, qui occupe bel et bien la
salle et l'enseignant.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from cal_iut.celcat.fichiers import ecrire_json
from cal_iut.celcat.lecture import est_cours, est_ferie

# Indice 0 du masque `weeks` de Celcat = cette semaine ISO (cf.
# `nuit.PREMIERE_SEMAINE_CELCAT`, dupliqué ici pour ne pas importer `nuit`,
# qui tire tout le drainage).
PREMIERE_SEMAINE_CELCAT = 34

# Types de ressources (`navigateur.TYPE_*`, recopiés pour ne pas importer le
# pilote d'écran).
TYPE_PERSONNEL = 603
TYPE_SALLES = 604
TYPE_DEPARTEMENTS = 610

VERSION_FICHIER = 1
NOM_FICHIER = "celcat_occupations_externes.json"
NOM_DEMANDE = "celcat_occupations_demande.json"
NOM_CONFIG = "celcat_occupations.yaml"

# Identifiant de séance cal-iut (« WR106-S1-CM-1 », « WS301-S3-TD-2 »,
# « WR118-S1-CUSTOM-… ») : ce que `charge_utile` écrit dans `notes`. La fin
# porte le groupe EN MINUSCULES (« WR305D-S3-TD-1-but2-dev-fi-td-cd ») : sans
# elles, la plupart de nos identifiants n'étaient pas reconnus (relevé réel
# du 02/10/2026).
_RE_SESSION_ID = re.compile(r"^[A-Z]{2}[A-Z0-9]*-S[1-6]-[A-Za-z0-9-]+$")

# Fuseau HISTORIQUE de Paris (avant 1911) : Celcat range ses horaires sur le
# 31/12/1899 ; un navigateur réglé sur Paris les sérialise en UTC avec
# +00:09:21 (cf. `lecture.TOLERANCE_CRENEAU_MINUTES`). 14h00 se lit alors
# « 13:50:39Z ». Un navigateur en UTC (conteneur) rend « 14:00:00Z ».
_DECALAGE_LMT_PARIS = timedelta(minutes=9, seconds=21)
_RE_HEURE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?")


def _racine() -> Path:
    return Path(__file__).resolve().parents[3]


def chemin_fichier() -> Path:
    return _racine() / "data" / "state" / NOM_FICHIER


def chemin_demande() -> Path:
    return _racine() / "data" / "state" / NOM_DEMANDE


# ── Configuration ───────────────────────────────────────────────────────


@dataclass
class ConfigOccupations:
    """`data/config/celcat_occupations.yaml` — versionné, relu à chaque usage."""

    actif: bool = True
    # « toutes » = toutes nos salles qui ont un équivalent Celcat
    # (`celcat.yaml::salles` + saisies de l'appli) ; sinon une liste d'ids.
    salles: str | list[str] = "toutes"
    salles_prioritaires: list[str] = field(
        default_factory=lambda: ["h018", "amphi1_tc_gea", "amphi2_gmp_geii"]
    )
    exclure_salles: list[str] = field(default_factory=list)
    # « tous » = tous nos enseignants qui ont un code Celcat.
    enseignants: str | list[str] = "tous"
    exclure_enseignants: list[str] = field(default_factory=list)
    # Période : « auto » = du lundi de la semaine courante à la fin de
    # l'année universitaire (31 juillet).
    du: str = "auto"
    au: str = "auto"
    # Ce qui est « à nous ».
    prefixes_groupes_mmi: list[str] = field(default_factory=lambda: ["BUT MMI"])
    departements_mmi: list[str] = field(default_factory=lambda: ["T_MMI"])
    # Libellé court d'un département Celcat (« T_TC T27 » -> « TC ») quand la
    # règle automatique ne suffit pas.
    libelles_departements: dict[str, str] = field(default_factory=dict)
    categories_ignorees: list[str] = field(default_factory=list)
    # Une salle GARDÉE par MMI (« Réservation Amphi H MMI » : évènement du
    # département MMI sans catégorie, groupe, enseignant ni matière) n'est
    # pas une occupation hors MMI.
    reservations_mmi_ignorees: bool = True
    # Placement manuel : faux = conflit FORÇABLE (message fort), vrai = refus.
    strict: bool = False
    # Au-delà, l'écran signale un relevé ancien (les contraintes restent).
    fraicheur_heures: float = 6.0
    # Cadence du sidecar (même que l'instantané).
    cadence_heures: float = 2.0
    # Lecture : nombre d'identifiants par `udlTimetables.load`, pause entre
    # deux requêtes, clés de filtre essayées dans l'ordre.
    lot: int = 10
    pause_s: float = 0.3
    cles_filtre_salles: list[str] = field(default_factory=lambda: ["RoomIDs"])
    cles_filtre_enseignants: list[str] = field(default_factory=lambda: ["StaffIDs", "StaffID"])


def _liste(valeur: object) -> list[str]:
    if valeur is None:
        return []
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, Iterable):
        return [str(v) for v in valeur if v not in (None, "")]
    return [str(valeur)]


def charger_config(config_dir: Path | None = None) -> ConfigOccupations:
    """Lit la configuration ; un fichier absent ou illisible rend les valeurs
    par défaut — jamais une exception qui couperait le relevé ou l'API."""
    chemin = Path(config_dir or (_racine() / "data" / "config")) / NOM_CONFIG
    cfg = ConfigOccupations()
    if not chemin.exists():
        return cfg
    try:
        import yaml

        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return cfg
    if not isinstance(data, dict):
        return cfg
    for cle in ("actif", "strict", "reservations_mmi_ignorees"):
        if cle in data:
            setattr(cfg, cle, bool(data[cle]))
    for cle in ("fraicheur_heures", "cadence_heures", "pause_s"):
        if cle in data:
            try:
                setattr(cfg, cle, float(data[cle]))
            except (TypeError, ValueError):
                pass
    if "lot" in data:
        try:
            cfg.lot = max(1, int(data["lot"]))
        except (TypeError, ValueError):
            pass
    salles = data.get("salles", cfg.salles)
    cfg.salles = salles if isinstance(salles, str) else [s.strip().lower() for s in _liste(salles)]
    enseignants = data.get("enseignants", cfg.enseignants)
    cfg.enseignants = (
        enseignants if isinstance(enseignants, str) else [e.strip().upper() for e in _liste(enseignants)]
    )
    for cle in ("salles_prioritaires", "exclure_salles"):
        if cle in data:
            setattr(cfg, cle, [s.strip().lower() for s in _liste(data[cle])])
    if "exclure_enseignants" in data:
        cfg.exclure_enseignants = [e.strip().upper() for e in _liste(data["exclure_enseignants"])]
    periode = data.get("periode") or {}
    if isinstance(periode, dict):
        cfg.du = str(periode.get("du") or "auto")
        cfg.au = str(periode.get("au") or "auto")
    for cle in ("prefixes_groupes_mmi", "departements_mmi", "categories_ignorees",
                "cles_filtre_salles", "cles_filtre_enseignants"):
        if cle in data:
            setattr(cfg, cle, _liste(data[cle]))
    libelles = data.get("libelles_departements") or {}
    if isinstance(libelles, dict):
        cfg.libelles_departements = {str(k): str(v) for k, v in libelles.items()}
    return cfg


def periode(cfg: ConfigOccupations, aujourdhui: date | None = None) -> tuple[date, date]:
    """(du, au) inclus. « auto » : du lundi de cette semaine — le passé ne
    contraint plus rien — au 31 juillet de l'année universitaire en cours."""
    jour = aujourdhui or date.today()  # noqa: DTZ011
    lundi = jour - timedelta(days=jour.weekday())
    annee_fin = jour.year + 1 if jour.month >= 8 else jour.year
    try:
        du = date.fromisoformat(cfg.du) if cfg.du != "auto" else lundi
    except ValueError:
        du = lundi
    try:
        au = date.fromisoformat(cfg.au) if cfg.au != "auto" else date(annee_fin, 7, 31)
    except ValueError:
        au = date(annee_fin, 7, 31)
    return du, au


# ── Conversion d'un évènement brut ──────────────────────────────────────


def heure_reelle(valeur: object) -> str:
    """L'heure RÉELLE d'un `start_time`/`end_time` Celcat, « HH:MM ».

    - « 1899-12-31T13:50:39.000Z » (navigateur à l'heure de Paris) : le
      décalage LMT est retiré -> « 14:00 » ;
    - « 1899-12-31T14:00:00.000Z » (navigateur en UTC) ou
      « 1899-12-31T14:00:00 » (`lire_reponse`) : tel quel ;
    - « 14:00 », un nombre de minutes : comme `lecture._heure`.

    Règle : des secondes non nulles sur une date pivot de 1899 trahissent le
    fuseau historique (Celcat ne pose que des minutes rondes).
    """
    if isinstance(valeur, str):
        m = _RE_HEURE_ISO.match(valeur.strip())
        if m:
            annee, mois, jour, hh, mm, ss = m.groups()
            instant = datetime(int(annee), int(mois), int(jour), int(hh), int(mm), int(ss or 0))
            if int(annee) < 1912 and int(ss or 0) != 0:
                instant += _DECALAGE_LMT_PARIS
            # Arrondi à la minute la plus proche.
            if instant.second >= 30:
                instant += timedelta(seconds=60 - instant.second)
            return f"{instant.hour:02d}:{instant.minute:02d}"
    from cal_iut.celcat.lecture import _heure

    return _heure(valeur)


def minutes(heure: str) -> int | None:
    morceaux = str(heure or "").split(":")
    if len(morceaux) < 2:
        return None
    try:
        return int(morceaux[0]) * 60 + int(morceaux[1])
    except ValueError:
        return None


def lundi_reference(jour: date, *, premiere_semaine: int = PREMIERE_SEMAINE_CELCAT) -> date:
    """Lundi de l'indice 0 du masque `weeks` pour l'année universitaire qui
    contient `jour` (même règle que `lecture.indice_depuis_lundi`)."""
    annee_iso, semaine_iso, _ = jour.isocalendar()
    annee = annee_iso if semaine_iso >= premiere_semaine else annee_iso - 1
    return date.fromisocalendar(annee, premiere_semaine, 1)


def dates_actives(brut: dict, *, lundi_ref: date, du: date, au: date) -> list[date]:
    """Les dates où l'évènement a lieu entre `du` et `au` (inclus)."""
    try:
        jour = int(brut.get("day_of_week"))
    except (TypeError, ValueError):
        return []
    if not 0 <= jour <= 6:
        return []
    masque = str(brut.get("weeks") or "")
    sortie = []
    for i, c in enumerate(masque):
        if c != "Y":
            continue
        d = lundi_ref + timedelta(days=7 * i + jour)
        if du <= d <= au:
            sortie.append(d)
    return sortie


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texte or "")) if not unicodedata.combining(c)
    ).casefold().strip()


def libelle_departement(nom: str, cfg: ConfigOccupations | None = None) -> str:
    """« T_TC T27 » -> « TC » ; « T_MMI T29 » -> « MMI » ; « T_ CJ T41 » (saisi
    avec une espace dans Celcat) -> « CJ ». Un nom inconnu reste tel quel ; la
    configuration peut le préciser."""
    nom = str(nom or "").strip()
    if not nom:
        return ""
    if cfg and nom in cfg.libelles_departements:
        return cfg.libelles_departements[nom]
    m = re.match(r"^[A-Z]_ ?([A-Za-z0-9]+)\b", nom)
    if m:
        return m.group(1)
    return nom


def _noms(valeurs: object, *cles: str) -> list[str]:
    sortie = []
    for item in valeurs if isinstance(valeurs, list) else []:
        if isinstance(item, dict):
            for cle in cles:
                val = item.get(cle)
                if val not in (None, ""):
                    sortie.append(str(val))
                    break
        elif item not in (None, ""):
            sortie.append(str(item))
    return sortie


def _ids(item: dict, *cles: str) -> set[int]:
    sortie = set()
    for cle in cles:
        val = item.get(cle)
        if val in (None, ""):
            continue
        try:
            sortie.add(int(val))
        except (TypeError, ValueError):
            continue
    return sortie


@dataclass
class ContexteNous:
    """Ce qui permet de reconnaître NOS évènements."""

    event_ids: set[int] = field(default_factory=set)
    session_ids: set[str] = field(default_factory=set)
    depts_mmi_ids: set[int] = field(default_factory=set)
    noms_departements: dict[int, str] = field(default_factory=dict)


def nom_departement(brut: dict, ctx: ContexteNous) -> str:
    nom = str(brut.get("deptName") or "").strip()
    if nom:
        return nom
    try:
        return ctx.noms_departements.get(int(brut.get("dept_id")), "")
    except (TypeError, ValueError):
        return ""


def motif_a_nous(brut: dict, ctx: ContexteNous, cfg: ConfigOccupations) -> str | None:
    """Pourquoi cet évènement n'est PAS une occupation externe — ou `None`
    s'il en est une."""
    if str(brut.get("suspended") or "N").upper() == "Y":
        return "suspendu"
    categorie = str(brut.get("evCatName") or "")
    from cal_iut.celcat.lecture import evenement_depuis_rpc

    ev = evenement_depuis_rpc(brut, group_id=0, groupe_nom="")
    if est_ferie(ev):
        return "jour férié"
    if str(brut.get("global_event") or "N").upper() == "Y":
        return "évènement global"
    if any(_sans_accents(categorie) == _sans_accents(c) for c in cfg.categories_ignorees):
        return "catégorie ignorée"
    if minutes(heure_reelle(brut.get("start_time"))) is None or minutes(heure_reelle(brut.get("end_time"))) is None:
        return "sans horaire"
    try:
        event_id = int(brut.get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0
    if event_id and event_id in ctx.event_ids:
        return "écrit par cal-iut (journal)"
    # `session_id_depuis_notes` : une séance envoyée par une règle porte la
    # remarque « WR100BU - <identifiant> », pas l'identifiant seul.
    from cal_iut.celcat.mapping import session_id_depuis_notes

    notes = session_id_depuis_notes(str(brut.get("notes") or ""))
    if notes and (notes in ctx.session_ids or _RE_SESSION_ID.match(notes)):
        return "écrit par cal-iut (notes)"
    groupes = _noms(brut.get("groups"), "name", "unique_name")
    dept = nom_departement(brut, ctx)
    dept_mmi = any(dept.upper().startswith(p.upper()) for p in cfg.departements_mmi if dept)
    try:
        dept_mmi = dept_mmi or int(brut.get("dept_id")) in ctx.depts_mmi_ids
    except (TypeError, ValueError):
        pass
    if est_cours(ev):
        if any(
            _sans_accents(g).startswith(_sans_accents(p)) for g in groupes for p in cfg.prefixes_groupes_mmi
        ):
            return "cours d'un groupe MMI"
        if dept_mmi and not groupes:
            return "cours du département MMI"
    # MMI qui GARDE une salle (« Réservation Amphi H MMI », 8h00–20h00 sur 22
    # semaines au relevé du 02/10/2026). Jules Crevoisier, le même jour : « on
    # a fait des réservations sur toutes les semaines pour que si d'autres
    # parcours veulent réserver l'amphi, elles doivent demander. Mais il faut
    # qu'en aucun cas ça nous bloque, nous. » Deux façons de la reconnaître,
    # toujours dans le département MMI, sans groupe ni matière : rien d'autre
    # n'est posé (ni catégorie ni enseignant), ou sa remarque commence par
    # « Réservation » — pour qu'une catégorie ou un responsable ajoutés plus
    # tard ne la transforment pas en occupation. Une activité MMI saisie à la
    # main (Réunion, Conférence…) reste une occupation.
    if cfg.reservations_mmi_ignorees and dept_mmi and not groupes and not brut.get("modules"):
        remarque = _sans_accents(str(brut.get("notes") or ""))
        if remarque.startswith("reservation") or (not categorie.strip() and not brut.get("staff")):
            return "réservation du département MMI"
    return None


# ── Ressources surveillées ──────────────────────────────────────────────


@dataclass
class RessourceSurveillee:
    type: str  # « salle » | « enseignant »
    code: str  # notre identifiant : « h018 », « AFR »
    celcat: str  # libellé (salle) ou code (enseignant) côté Celcat
    libelle: str = ""  # « H.018 », « Anthony Froli »
    celcat_id: int | None = None
    noms_celcat: set[str] = field(default_factory=set)
    trouvee: bool = False

    def resume(self) -> dict:
        return {
            "type": self.type, "code": self.code, "libelle": self.libelle or self.code,
            "celcat": self.celcat, "celcat_id": self.celcat_id, "trouvee": self.trouvee,
        }


def normaliser_code_salle(texte: str) -> str:
    """« H018 », « H.018 », « h018 » -> « h018 »."""
    return re.sub(r"[^a-z0-9_]", "", str(texte or "").lower())


def ressources_a_surveiller(
    cfg: ConfigOccupations,
    *,
    salles_celcat: dict[str, str],
    enseignants_celcat: dict[str, str],
    libelles_salles: dict[str, str] | None = None,
    noms_enseignants: dict[str, str] | None = None,
    filtre: list[str] | None = None,
) -> list[RessourceSurveillee]:
    """La liste des ressources à lire, dans l'ordre (prioritaires d'abord).

    `salles_celcat` : {notre id de salle -> libellé Celcat} ;
    `enseignants_celcat` : {trigramme -> code Celcat}. Une salle COMBINÉE
    (h007_h008) partage son libellé Celcat avec l'une de ses moitiés : on ne
    lit le libellé qu'une fois, sous l'id de la moitié.
    `filtre` (CLI `--ressource`) : « H018 », « AFR »… — restreint la liste.
    """
    libelles_salles = libelles_salles or {}
    noms_enseignants = noms_enseignants or {}
    filtre_norm = {normaliser_code_salle(f) for f in filtre or []}
    filtre_upper = {str(f).strip().upper() for f in filtre or []}

    par_libelle: dict[str, list[str]] = {}
    for rid, libelle in salles_celcat.items():
        if libelle:
            par_libelle.setdefault(libelle, []).append(str(rid).lower())
    salles: list[RessourceSurveillee] = []
    for libelle, ids in par_libelle.items():
        simples = [i for i in ids if "_" not in i] or ids
        rid = sorted(simples)[0]
        # Une salle PRIORITAIRE est toujours surveillée, même quand `salles`
        # est une liste qui ne la nomme pas (amphis partagés).
        voulues = set(cfg.salles) | set(cfg.salles_prioritaires) if isinstance(cfg.salles, list) else None
        if cfg.salles != "toutes" and voulues is not None and not set(ids) & voulues:
            continue
        if set(ids) & set(cfg.exclure_salles):
            continue
        if filtre and not (set(ids) & filtre_norm or normaliser_code_salle(libelle) in filtre_norm):
            continue
        salles.append(RessourceSurveillee("salle", rid, libelle, libelles_salles.get(rid, rid)))
    prioritaires = [p.lower() for p in cfg.salles_prioritaires]
    salles.sort(key=lambda r: (prioritaires.index(r.code) if r.code in prioritaires else len(prioritaires), r.code))

    enseignants: list[RessourceSurveillee] = []
    for code, celcat in sorted(enseignants_celcat.items()):
        code = str(code).upper()
        if not celcat or str(celcat).strip() in ("", "0"):
            continue
        if cfg.enseignants != "tous" and isinstance(cfg.enseignants, list) and code not in cfg.enseignants:
            continue
        if code in cfg.exclure_enseignants:
            continue
        if filtre and code not in filtre_upper:
            continue
        enseignants.append(RessourceSurveillee("enseignant", code, str(celcat), noms_enseignants.get(code, code)))
    return salles + enseignants


def _catalogue(page, type_id: int) -> list[dict]:
    from cal_iut.celcat.rpc import charger_ressources

    return charger_ressources(page, type_id, {"customOnly": False, "includedDetails": []})


def resoudre(page, ressources: list[RessourceSurveillee], *, journal: Callable[[str], None] = print) -> int:
    """Cherche l'identifiant Celcat de chaque ressource. Deux catalogues au
    plus (salles : 2 444 fiches, personnel : 4 975), chargés une fois.
    Rend le nombre de requêtes faites."""
    requetes = 0
    if any(r.type == "salle" for r in ressources):
        catalogue = _catalogue(page, TYPE_SALLES)
        requetes += 1
        par_nom: dict[str, dict] = {}
        for enreg in catalogue:
            for cle in ("name", "unique_name"):
                val = enreg.get(cle)
                if val:
                    par_nom.setdefault(_sans_accents(str(val)), enreg)
        for r in ressources:
            if r.type != "salle":
                continue
            enreg = par_nom.get(_sans_accents(r.celcat))
            if enreg is None:
                journal(f"  salle « {r.celcat} » ({r.code}) introuvable dans Celcat")
                continue
            ids = _ids(enreg, "id", "room_id")
            r.celcat_id = min(ids) if ids else None
            r.noms_celcat = {_sans_accents(str(enreg.get(c))) for c in ("name", "unique_name") if enreg.get(c)}
            r.trouvee = r.celcat_id is not None
    if any(r.type == "enseignant" for r in ressources):
        catalogue = _catalogue(page, TYPE_PERSONNEL)
        requetes += 1
        par_code = {str(e.get("unique_name") or "").strip().upper(): e for e in catalogue if e.get("unique_name")}
        for r in ressources:
            if r.type != "enseignant":
                continue
            enreg = par_code.get(r.celcat.strip().upper())
            if enreg is None:
                journal(f"  enseignant {r.code} (code Celcat {r.celcat}) introuvable dans Celcat")
                continue
            ids = _ids(enreg, "id", "staff_id")
            r.celcat_id = min(ids) if ids else None
            r.noms_celcat = {_sans_accents(str(enreg.get(c))) for c in ("name", "unique_name") if enreg.get(c)}
            r.trouvee = r.celcat_id is not None
    return requetes


def _contexte_departements(page, ctx: ContexteNous, cfg: ConfigOccupations) -> int:
    """Noms des départements (155 fiches, une requête) — `deptName` peut
    manquer sur un évènement ; l'id, lui, y est."""
    try:
        catalogue = _catalogue(page, TYPE_DEPARTEMENTS)
    except Exception:  # noqa: BLE001 — un catalogue manquant n'empêche pas le relevé
        return 1
    for enreg in catalogue:
        ids = _ids(enreg, "id", "dept_id")
        nom = str(enreg.get("name") or enreg.get("unique_name") or "").strip()
        for i in ids:
            if nom:
                ctx.noms_departements[i] = nom
            if any(nom.upper().startswith(p.upper()) for p in cfg.departements_mmi):
                ctx.depts_mmi_ids.add(i)
    return 1


def _charger_lot(page, cles: list[str], ids: list[int], *, pause_s: float, compteur: list[int],
                 journal: Callable[[str], None]) -> list[dict]:
    """`udlTimetables.load` sur un lot d'identifiants. Sur refus d'un lot de
    plusieurs (ETooManyRecords…), le coupe en deux — jamais une requête par
    créneau, au pire une par ressource."""
    from cal_iut.celcat.rpc import SessionCelcatTimeout, appeler

    derniere: Exception | None = None
    for cle in cles:
        try:
            compteur[0] += 1
            resultat = appeler(page, "udlTimetables.load", [{cle: list(ids)}])
            if pause_s:
                time.sleep(pause_s)
            if resultat is None:
                return []
            if not isinstance(resultat, list):
                raise TypeError("udlTimetables.load n'a pas renvoyé une liste")
            return [e for e in resultat if isinstance(e, dict)]
        except SessionCelcatTimeout:
            raise
        except Exception as exc:  # noqa: BLE001
            derniere = exc
            continue
    if len(ids) > 1:
        moitie = len(ids) // 2
        journal(f"  lot de {len(ids)} refusé ({derniere}) : découpé en deux")
        return _charger_lot(page, cles, ids[:moitie], pause_s=pause_s, compteur=compteur, journal=journal) + \
            _charger_lot(page, cles, ids[moitie:], pause_s=pause_s, compteur=compteur, journal=journal)
    raise RuntimeError(f"udlTimetables.load {cles} [{ids[0]}] : {derniere}")


def _concerne(brut: dict, r: RessourceSurveillee) -> bool:
    cle_liste, cles_id = ("rooms", ("id", "room_id")) if r.type == "salle" else ("staff", ("id", "staff_id"))
    for item in brut.get(cle_liste) or []:
        if not isinstance(item, dict):
            continue
        if r.celcat_id is not None and r.celcat_id in _ids(item, *cles_id):
            return True
        noms = {_sans_accents(str(item.get(c))) for c in ("name", "unique_name") if item.get(c)}
        if noms & r.noms_celcat:
            return True
        if r.type == "enseignant" and _sans_accents(str(item.get("unique_name") or "")) == _sans_accents(r.celcat):
            return True
        if r.type == "salle" and noms & {_sans_accents(r.celcat)}:
            return True
    return False


def _occurrence(brut: dict, r: RessourceSurveillee, d: date, ctx: ContexteNous, cfg: ConfigOccupations) -> dict:
    dept_nom = nom_departement(brut, ctx)
    modules = _noms(brut.get("modules"), "name", "unique_name")
    categorie = str(brut.get("evCatName") or "")
    intitule = modules[0] if modules else str(brut.get("event_name") or "").strip() or categorie
    return {
        "type": r.type,
        "code": r.code,
        "libelle": r.libelle or r.code,
        "date": d.isoformat(),
        "debut": heure_reelle(brut.get("start_time")),
        "fin": heure_reelle(brut.get("end_time")),
        "departement": libelle_departement(dept_nom, cfg),
        "departement_nom": dept_nom,
        "categorie": categorie,
        "intitule": intitule,
        "modules": modules,
        "groupes": _noms(brut.get("groups"), "name", "unique_name"),
        "enseignants": _noms(brut.get("staff"), "name", "unique_name"),
        "salles": _noms(brut.get("rooms"), "name", "unique_name"),
        "event_id": int(brut.get("event_id") or 0) or None,
    }


@dataclass
class ResultatReleve:
    evenements: list[dict] = field(default_factory=list)
    ressources: list[RessourceSurveillee] = field(default_factory=list)
    ignores: dict[str, int] = field(default_factory=dict)
    ignores_detail: list[dict] = field(default_factory=list)
    requetes: int = 0
    du: date | None = None
    au: date | None = None
    erreurs: list[str] = field(default_factory=list)

    def document(self, *, releve_le: str | None = None, base: str = "", duree_s: float | None = None,
                 erreur: str | None = None) -> dict:
        return {
            "version": VERSION_FICHIER,
            "releve_le": releve_le or datetime.now(UTC).isoformat(),
            "base": base,
            "periode": {"du": self.du.isoformat() if self.du else None, "au": self.au.isoformat() if self.au else None},
            "ressources": [r.resume() for r in self.ressources],
            "evenements": self.evenements,
            "ignores": self.ignores,
            "requetes": self.requetes,
            "duree_s": duree_s,
            "erreurs": self.erreurs,
            "erreur": erreur,
        }


def relever(
    page,
    cfg: ConfigOccupations,
    ressources: list[RessourceSurveillee],
    *,
    ctx: ContexteNous,
    du: date,
    au: date,
    journal: Callable[[str], None] = print,
) -> ResultatReleve:
    """Lit Celcat (lecture seule) et rend les occupations EXTERNES des
    ressources données, dépliées en dates entre `du` et `au`."""
    res = ResultatReleve(ressources=ressources, du=du, au=au)
    compteur = [0]
    compteur[0] += resoudre(page, ressources, journal=journal)
    compteur[0] += _contexte_departements(page, ctx, cfg)
    lundi_ref = lundi_reference(du)

    vus: dict[tuple[int, str, str], bool] = {}
    for type_, cles in (("salle", cfg.cles_filtre_salles), ("enseignant", cfg.cles_filtre_enseignants)):
        cibles = [r for r in ressources if r.type == type_ and r.trouvee and r.celcat_id is not None]
        for i in range(0, len(cibles), max(1, cfg.lot)):
            lot = cibles[i : i + max(1, cfg.lot)]
            try:
                bruts = _charger_lot(page, cles, [r.celcat_id for r in lot], pause_s=cfg.pause_s,
                                     compteur=compteur, journal=journal)
            except Exception as exc:
                from cal_iut.celcat.rpc import SessionCelcatTimeout

                if isinstance(exc, SessionCelcatTimeout):
                    raise
                message = f"{type_} {', '.join(r.code for r in lot)} : {exc}"
                res.erreurs.append(message)
                journal(f"  ÉCHEC {message}")
                continue
            for brut in bruts:
                # Évènements GLOBAUX (jours fériés) : Celcat les renvoie avec
                # chaque chargement, sans salle ni enseignant. Comptés une
                # fois, sous leur motif — pas « non attribué » une fois par
                # lot (× 88 au relevé complet du 02/10/2026).
                if str(brut.get("global_event") or "N").upper() == "Y":
                    cle = (int(brut.get("event_id") or 0), "global", "")
                    if cle not in vus:
                        vus[cle] = False
                        motif = motif_a_nous(brut, ctx, cfg) or "évènement global"
                        res.ignores[motif] = res.ignores.get(motif, 0) + 1
                    continue
                concernees = [r for r in lot if _concerne(brut, r)]
                if not concernees and len(lot) == 1:
                    concernees = list(lot)
                if not concernees:
                    res.ignores["non attribué"] = res.ignores.get("non attribué", 0) + 1
                    continue
                motif = motif_a_nous(brut, ctx, cfg)
                if motif:
                    for r in concernees:
                        cle = (int(brut.get("event_id") or 0), r.type, r.code)
                        if cle in vus:
                            continue
                        vus[cle] = False
                        res.ignores[motif] = res.ignores.get(motif, 0) + 1
                        if len(res.ignores_detail) < 500:
                            res.ignores_detail.append({
                                "type": r.type, "code": r.code, "event_id": brut.get("event_id"), "motif": motif,
                                "categorie": brut.get("evCatName"),
                                "module": (_noms(brut.get("modules"), "name") or [""])[0],
                                "groupes": _noms(brut.get("groups"), "name"),
                            })
                    continue
                for r in concernees:
                    cle = (int(brut.get("event_id") or 0), r.type, r.code)
                    if cle in vus:
                        continue
                    vus[cle] = True
                    for d in dates_actives(brut, lundi_ref=lundi_ref, du=du, au=au):
                        res.evenements.append(_occurrence(brut, r, d, ctx, cfg))
    res.evenements.sort(key=lambda e: (e["date"], e["debut"], e["type"], e["code"], e["event_id"] or 0))
    res.requetes = compteur[0]
    return res


# ── Fichier d'état (sidecar écrit, backend lit) ─────────────────────────


@dataclass
class ReleveOccupations:
    evenements: list[dict] = field(default_factory=list)
    ressources: list[dict] = field(default_factory=list)
    releve_le: str | None = None
    age_secondes: float | None = None
    periode: dict = field(default_factory=dict)
    ignores: dict = field(default_factory=dict)
    requetes: int | None = None
    erreurs: list[str] = field(default_factory=list)
    erreur: str | None = None
    base: str = ""

    @property
    def absent(self) -> bool:
        return self.releve_le is None


def enregistrer(document: dict, chemin: Path | None = None) -> None:
    """Dépôt ATOMIQUE : le backend relit ce fichier pendant que le sidecar
    l'écrit (deux conteneurs, un volume). Une lecture à mi-écriture ne doit
    jamais rendre « aucune occupation »."""
    ecrire_json(chemin or chemin_fichier(), document)


def enregistrer_echec(erreur: str, chemin: Path | None = None) -> None:
    """Un relevé raté GARDE les occupations précédentes (mieux vaut une
    contrainte un peu ancienne, signalée comme telle, que plus aucune) et y
    note l'erreur."""
    cible = chemin or chemin_fichier()
    precedent = _lire_json(cible) or {}
    precedent["erreur"] = erreur
    precedent["echec_le"] = datetime.now(UTC).isoformat()
    precedent.setdefault("version", VERSION_FICHIER)
    precedent.setdefault("evenements", [])
    ecrire_json(cible, precedent)


def _lire_json(chemin: Path) -> dict | None:
    if not chemin.exists():
        return None
    try:
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return contenu if isinstance(contenu, dict) else None


def age_depuis(releve_le: str | None, maintenant: datetime | None = None) -> float | None:
    if not isinstance(releve_le, str):
        return None
    try:
        instant = datetime.fromisoformat(releve_le)
    except ValueError:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return ((maintenant or datetime.now(UTC)) - instant).total_seconds()


def lire(chemin: Path | None = None) -> ReleveOccupations:
    contenu = _lire_json(chemin or chemin_fichier())
    if contenu is None:
        return ReleveOccupations()
    evenements = contenu.get("evenements")
    releve_le = contenu.get("releve_le") if isinstance(contenu.get("releve_le"), str) else None
    return ReleveOccupations(
        evenements=[e for e in evenements if isinstance(e, dict)] if isinstance(evenements, list) else [],
        ressources=[r for r in contenu.get("ressources") or [] if isinstance(r, dict)],
        releve_le=releve_le,
        age_secondes=age_depuis(releve_le),
        periode=contenu.get("periode") if isinstance(contenu.get("periode"), dict) else {},
        ignores=contenu.get("ignores") if isinstance(contenu.get("ignores"), dict) else {},
        requetes=contenu.get("requetes") if isinstance(contenu.get("requetes"), int) else None,
        erreurs=[str(e) for e in contenu.get("erreurs") or []],
        erreur=str(contenu["erreur"]) if contenu.get("erreur") else None,
        base=str(contenu.get("base") or ""),
    )


def demander(chemin: Path | None = None) -> None:
    """« Relire maintenant » : une DEMANDE au sidecar, honorée à son prochain
    passage (même mécanisme que `instantane.demander`)."""
    ecrire_json(chemin or chemin_demande(), {"demande_le": datetime.now(UTC).isoformat()}, indent=None)


def demande_en_cours(chemin: Path | None = None) -> bool:
    return (chemin or chemin_demande()).exists()


def consommer_demande(chemin: Path | None = None) -> bool:
    cible = chemin or chemin_demande()
    if not cible.exists():
        return False
    try:
        cible.unlink()
    except OSError:
        return False
    return True


def releve_du(cfg: ConfigOccupations | None = None) -> bool:
    """Oui si demandé, absent, ou plus vieux que la cadence (2 h)."""
    cfg = cfg or charger_config()
    if not cfg.actif:
        return False
    if demande_en_cours():
        return True
    releve = lire()
    return releve.age_secondes is None or releve.age_secondes > cfg.cadence_heures * 3600


# ── Contexte côté sidecar ───────────────────────────────────────────────


def contexte_depuis_journal() -> ContexteNous:
    """Event_ids et séances que NOUS avons écrits (`celcat/sync.py`)."""
    ctx = ContexteNous()
    try:
        from cal_iut.celcat.sync import journal

        for session_id, entree in journal().items():
            ctx.session_ids.add(str(session_id))
            if isinstance(entree, dict) and entree.get("event_id"):
                try:
                    ctx.event_ids.add(int(entree["event_id"]))
                except (TypeError, ValueError):
                    continue
    except Exception:  # noqa: BLE001 — sans journal, les autres règles restent
        pass
    return ctx


def ressources_depuis_config(
    cfg: ConfigOccupations, config_dir: Path | None = None, *, filtre: list[str] | None = None
) -> list[RessourceSurveillee]:
    """Liste des ressources à lire, depuis `celcat.yaml` + saisies de
    l'appli (`load_celcat_config`, LECTURE seule) et `rooms.yaml`."""
    from cal_iut.celcat.mapping import load_celcat_config

    dossier = Path(config_dir or (_racine() / "data" / "config"))
    cc = load_celcat_config(dossier)
    libelles: dict[str, str] = {}
    try:
        import yaml

        data = yaml.safe_load((dossier / "rooms.yaml").read_text(encoding="utf-8")) or {}
        for salle in data.get("rooms") or []:
            if isinstance(salle, dict) and salle.get("id"):
                libelles[str(salle["id"]).lower()] = str(salle.get("label") or salle["id"])
    except Exception:  # noqa: BLE001
        pass
    noms = {code: nom for code, nom in cc.noms_fichier_enseignants.items() if nom and nom != code}
    try:
        from cal_iut.ingestion.enseignants import enseignants_declares

        noms.update(enseignants_declares(dossier))
    except Exception:  # noqa: BLE001
        pass
    return ressources_a_surveiller(
        cfg, salles_celcat=cc.salles, enseignants_celcat=cc.enseignants,
        libelles_salles=libelles, noms_enseignants=noms, filtre=filtre,
    )


# ── Page simulée (CLI `--simulation`, tests) ────────────────────────────


class PageSimulee:
    """Une « page » qui répond au RPC comme Celcat, depuis un JSON :

        {"ressources": {"603": [...], "604": [...], "610": [...]},
         "evenements": [<évènements bruts udlTimetables.load>]}

    `udlTimetables.load` filtre par `RoomIDs` / `StaffIDs` sur les ids des
    sous-objets `rooms` / `staff`. Rien n'est jamais écrit : toute autre
    méthode répond une erreur.
    """

    def __init__(self, donnees: dict) -> None:
        self.donnees = donnees
        self.appels: list[tuple[str, list]] = []

    @classmethod
    def depuis_fichier(cls, chemin: Path) -> PageSimulee:
        return cls(json.loads(Path(chemin).read_text(encoding="utf-8")))

    def evaluate(self, _js, arg=None):
        methode = (arg or {}).get("methode")
        params = (arg or {}).get("params") or []
        self.appels.append((str(methode), params))
        if methode == "udlResources.load":
            lots = (self.donnees.get("ressources") or {}).get(str(params[0])) or []
            return self._ok(lots)
        if methode == "udlTimetables.load":
            filtre = params[0] if params and isinstance(params[0], dict) else {}
            # Comme Celcat : les évènements globaux (jours fériés) accompagnent
            # chaque chargement, quel que soit le filtre (constaté le 02/10/2026).
            sortie = [ev for ev in self.donnees.get("evenements") or []
                      if str(ev.get("global_event") or "N").upper() == "Y"]
            for cle, cle_liste in (("RoomIDs", "rooms"), ("StaffIDs", "staff"), ("StaffID", "staff")):
                ids = {int(i) for i in filtre.get(cle) or []}
                if not ids:
                    continue
                for ev in self.donnees.get("evenements") or []:
                    if any(_ids(x, "id", "room_id", "staff_id") & ids for x in ev.get(cle_liste) or [] if isinstance(x, dict)):
                        if ev not in sortie:
                            sortie.append(ev)
            return self._ok(sortie)
        return {"status": 200, "texte": json.dumps({"jsonrpc": "2.0", "id": 0, "error": {
            "code": "refus", "message": f"méthode {methode} non simulée (lecture seule)"}})}

    @staticmethod
    def _ok(result: object) -> dict:
        return {"status": 200, "texte": json.dumps({"jsonrpc": "2.0", "id": 0, "result": result}, ensure_ascii=False)}


# ── Affichage (CLI) ─────────────────────────────────────────────────────

_JOURS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def ligne_occurrence(e: dict) -> str:
    d = date.fromisoformat(e["date"])
    dept = e.get("departement") or "hors département"
    quoi = " · ".join(x for x in (e.get("categorie"), e.get("intitule")) if x)
    groupes = f" · {', '.join(e['groupes'])}" if e.get("groupes") else ""
    return (
        f"    {_JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')} {e.get('debut')}–{e.get('fin')} · {dept} · {quoi}"
        f"{groupes} · event {e.get('event_id')}"
    )


def afficher(res: ResultatReleve, *, details: bool = False, sortie: Callable[[str], None] = print) -> None:
    sortie(f"Période : {res.du} → {res.au} · {res.requetes} requête(s) RPC")
    par_ressource: dict[tuple[str, str], list[dict]] = {}
    for e in res.evenements:
        par_ressource.setdefault((e["type"], e["code"]), []).append(e)
    for r in res.ressources:
        evs = par_ressource.get((r.type, r.code), [])
        etat = f"id Celcat {r.celcat_id}" if r.trouvee else "INTROUVABLE dans Celcat"
        sortie(f"\n{r.type} {r.code} ({r.libelle} — Celcat « {r.celcat} », {etat}) : "
               f"{len(evs)} occupation(s) hors MMI")
        for e in evs:
            sortie(ligne_occurrence(e))
    if res.ignores:
        sortie("\nIgnorés (à nous, ou non pertinents) : "
               + ", ".join(f"{motif} × {n}" for motif, n in sorted(res.ignores.items())))
    if details and res.ignores_detail:
        sortie("Détail des ignorés :")
        for i in res.ignores_detail:
            sortie(f"    {i['type']} {i['code']} · event {i['event_id']} · {i['motif']} · "
                   f"{i.get('categorie') or ''} · {i.get('module') or ''} · {', '.join(i.get('groupes') or [])}")
    for err in res.erreurs:
        sortie(f"ERREUR : {err}")


def executer(
    page,
    *,
    cfg: ConfigOccupations | None = None,
    filtre: list[str] | None = None,
    du: date | None = None,
    au: date | None = None,
    ecrire_fichier: bool = False,
    base: str = "",
    details: bool = False,
    config_dir: Path | None = None,
    chemin: Path | None = None,
    sortie: Callable[[str], None] = print,
) -> ResultatReleve:
    """Le cœur commun du sidecar et de la CLI : lit, affiche, écrit si demandé.

    Un relevé FILTRÉ (`--ressource`) n'écrase jamais le fichier complet : il
    ne couvrirait qu'une partie des ressources, et le backend lirait alors
    toutes les autres comme libres."""
    cfg = cfg or charger_config(config_dir)
    debut = time.monotonic()
    p_du, p_au = periode(cfg)
    du, au = du or p_du, au or p_au
    ressources = ressources_depuis_config(cfg, config_dir, filtre=filtre)
    if filtre and not ressources:
        sortie(f"Aucune ressource surveillée ne correspond à {', '.join(filtre)} "
               "(salle sans équivalent Celcat, ou enseignant sans code Celcat).")
    res = relever(page, cfg, ressources, ctx=contexte_depuis_journal(), du=du, au=au, journal=sortie)
    afficher(res, details=details, sortie=sortie)
    if ecrire_fichier:
        if filtre:
            sortie("\n--ecrire-fichier ignoré : relevé filtré (il écraserait les autres ressources).")
        else:
            enregistrer(res.document(base=base, duree_s=round(time.monotonic() - debut, 1)), chemin)
            sortie(f"\nÉcrit : {chemin or chemin_fichier()} ({len(res.evenements)} occupation(s))")
    return res
