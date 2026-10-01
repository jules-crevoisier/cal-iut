"""Occupations HORS MMI (Celcat) appliquées au planning — côté backend.

Le sidecar `celcat-nuit` lit Celcat et dépose
`data/state/celcat_occupations_externes.json` (`celcat/occupations.py`). Le
backend ne joint jamais Celcat : il relit ce fichier (rechargé dès qu'il
change, la révision avance par la sonde enregistrée dans `api/main.py`), et
en tire des indisponibilités sur NOS créneaux.

CONVERSION. Une occupation porte une date et des heures RÉELLES (10h00 à
12h30). Elle bloque chaque créneau qu'elle chevauche vraiment : 10h00-12h30
bloque 9h30-11h00 et 11h00-12h30, pas 8h00-9h30. Une tolérance de cinq
minutes évite qu'un 12h30-14h00 morde sur 11h00-12h30.

OÙ C'EST APPLIQUÉ, comme une séance déjà placée :

- placement manuel (déplacer, échanger, placer, créer, PATCH) :
  `api/main.py::_conflits_deplacement` (enseignant) et
  `appliquer_salle` après `validate_move` (salle). FORÇABLE par défaut —
  le relevé a jusqu'à deux heures, une réunion a pu être annulée — sauf
  `strict: true` dans `celcat_occupations.yaml` ;
- recherche de salle (`_resolve_room`, affectation après génération,
  lissage) : `reservations_effectives`, qui ajoute les salles prises dans
  Celcat aux salles réservées de `salles_reservees.yaml` ;
- générateur (CP-SAT, régénération) et suggestions :
  `disponibilites_avec_externes` ajoute des `TeacherDateSlotRule` —
  contraintes DURES, comme une indisponibilité datée ;
- affichage et « À traiter » : `pour_payload` (blocs « Occupé ailleurs »,
  séances déjà placées en conflit).

FRAÎCHEUR. Fichier absent : aucune contrainte externe (et l'écran Celcat le
dit). Fichier ancien : les contraintes restent appliquées telles quelles,
l'écran signale l'âge (`fraicheur_heures`).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from cal_iut.celcat import occupations as occ

# Créneaux de l'IUT en minutes — `celcat/mapping.py::SLOT_TIMES`.
_CRENEAUX_MIN = [(8 * 60, 9 * 60 + 30), (9 * 60 + 30, 11 * 60), (11 * 60, 12 * 60 + 30),
                 (14 * 60, 15 * 60 + 30), (15 * 60 + 30, 17 * 60), (17 * 60, 18 * 60 + 30)]
TOLERANCE_MIN = 5
_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

_verrou = threading.Lock()
_cache: dict[str, Any] = {}


def creneaux_chevauches(debut: str, fin: str) -> list[int]:
    """Créneaux (0-5) qu'un intervalle réel chevauche VRAIMENT."""
    d, f = occ.minutes(debut), occ.minutes(fin)
    if d is None or f is None or f <= d:
        return []
    return [i for i, (s0, s1) in enumerate(_CRENEAUX_MIN) if d < s1 - TOLERANCE_MIN and f > s0 + TOLERANCE_MIN]


def _signature(chemin: Path) -> tuple | None:
    try:
        st = chemin.stat()
    except OSError:
        return None
    return (str(chemin), st.st_mtime_ns, st.st_size)


def config(config_dir: Path | None = None) -> occ.ConfigOccupations:
    dossier = Path(config_dir) if config_dir else None
    if dossier is None:
        try:
            from cal_iut.api.state import get_state

            dossier = Path(get_state().config_dir)
        except Exception:  # noqa: BLE001
            dossier = None
    chemin = (dossier or Path(".")) / occ.NOM_CONFIG
    cle = ("config", _signature(chemin), str(dossier))
    with _verrou:
        if _cache.get("config_cle") == cle:
            return _cache["config"]
    cfg = occ.charger_config(dossier) if dossier and chemin.exists() else occ.ConfigOccupations()
    with _verrou:
        _cache["config_cle"], _cache["config"] = cle, cfg
    return cfg


@dataclass
class Index:
    """Occupations rangées par ressource puis par (date ISO, créneau)."""

    releve: occ.ReleveOccupations
    par_ressource: dict[tuple[str, str], dict[tuple[str, int], list[dict]]] = field(default_factory=dict)
    signature: tuple | None = None


def index() -> Index:
    """Le relevé courant, indexé — recalculé seulement si le fichier change."""
    chemin = occ.chemin_fichier()
    sig = _signature(chemin)
    with _verrou:
        courant = _cache.get("index")
        if courant is not None and courant.signature == sig:
            return courant
    releve = occ.lire(chemin)
    idx = Index(releve=releve, signature=sig)
    for e in releve.evenements:
        cle = (str(e.get("type") or ""), _cle_code(e.get("type"), e.get("code")))
        iso = str(e.get("date") or "")
        if not iso or not cle[1]:
            continue
        for s in creneaux_chevauches(str(e.get("debut") or ""), str(e.get("fin") or "")):
            idx.par_ressource.setdefault(cle, {}).setdefault((iso, s), []).append(e)
    with _verrou:
        _cache["index"] = idx
    return idx


def _cle_code(type_: object, code: object) -> str:
    texte = str(code or "").strip()
    return texte.lower() if type_ == "salle" else texte.upper()


def invalider() -> None:
    """Tests : oublie le relevé et la configuration en cache."""
    with _verrou:
        _cache.clear()


# ── Repères de calendrier ───────────────────────────────────────────────


def _semestre_ancre(state) -> str:
    try:
        from cal_iut.api.regen import resolve_semestre

        return resolve_semestre(state)
    except Exception:  # noqa: BLE001
        return "S1"


def _decalage(state, semestre: str | None = None) -> int:
    from cal_iut.calendar.academic import semester_week_offset

    return semester_week_offset(state.calendar, semestre or _semestre_ancre(state))


def _date_de(state, semestre: str | None, week: int, day: int) -> date | None:
    try:
        return state.calendar.week_day_to_date(_decalage(state, semestre) + int(week), int(day))
    except Exception:  # noqa: BLE001
        return None


def _hm(heure: str) -> str:
    """« 10:00 » -> « 10h00 »."""
    return str(heure or "").replace(":", "h")


def _quand(e: dict) -> str:
    try:
        d = date.fromisoformat(str(e.get("date")))
        jour = f"{_JOURS[d.weekday()]} {d.strftime('%d/%m')}"
    except ValueError:
        jour = str(e.get("date") or "")
    return f"{jour}, {_hm(e.get('debut'))}–{_hm(e.get('fin'))}"


# ── Noms ─────────────────────────────────────────────────────────────────


def nom_enseignant(state, code: str, e: dict | None = None) -> str:
    """« Prénom Nom » comme partout dans l'appli, sinon le nom Celcat
    remis à l'endroit (« FROLI Anthony » -> « Anthony Froli »), sinon le code."""
    cle = ("noms", id(getattr(state, "sessions", None)), len(getattr(state, "sessions", []) or []))
    with _verrou:
        noms = _cache.get("noms") if _cache.get("noms_cle") == cle else None
    if noms is None:
        noms = {}
        try:
            from cal_iut.export.html_view import _teacher_names

            noms.update({k: v for k, v in _teacher_names(state.sessions).items() if v and v != k})
        except Exception:  # noqa: BLE001
            pass
        try:
            from cal_iut.ingestion.enseignants import enseignants_declares

            for k, v in enseignants_declares(Path(state.config_dir)).items():
                noms.setdefault(k, v)
        except Exception:  # noqa: BLE001
            pass
        with _verrou:
            _cache["noms_cle"], _cache["noms"] = cle, noms
    if noms.get(code):
        return noms[code]
    libelle = str((e or {}).get("libelle") or "")
    if libelle and libelle != code:
        return libelle
    return code


def _libelle_salle(state, room_id: str) -> str:
    salle = next((r for r in getattr(state, "rooms", []) or [] if r.id == room_id), None)
    libelle = salle.label if salle else room_id
    return libelle.split("(")[0].strip() or libelle


# ── Messages ─────────────────────────────────────────────────────────────


def _est_sigle(dep: str) -> bool:
    """« TC », « GEA », « MMI » : un département ; « Direction IUT » : non."""
    return bool(re.fullmatch(r"[A-Z0-9]{1,8}", dep))


def message_enseignant(nom: str, e: dict) -> str:
    """« Enseignant indisponible — Anthony Froli est déjà programmé dans le
    département TC sur ce créneau (lundi 28/09, 10h00–12h30, Celcat). »"""
    dep = str(e.get("departement") or "").strip()
    if _est_sigle(dep):
        ou = f"dans le département {dep}"
    else:
        ou = f"dans Celcat ({dep or 'hors département'})"
    return f"Enseignant indisponible — {nom} est déjà programmé {ou} sur ce créneau ({_quand(e)}, Celcat)."


def message_salle(libelle: str, e: dict) -> str:
    """« Salle indisponible — H.018 est réservée dans Celcat sur ce créneau
    (département TC, [CM] Marketing, lundi 28/09, 10h00–12h30). » Sans
    département : « (administration, Réunion, …) »."""
    dep = str(e.get("departement") or "").strip()
    qui = f"département {dep}" if _est_sigle(dep) else (dep or "administration")
    quoi = str(e.get("intitule") or e.get("categorie") or "").strip()
    morceaux = [qui] + ([quoi] if quoi else []) + [_quand(e)]
    return f"Salle indisponible — {libelle} est réservée dans Celcat sur ce créneau ({', '.join(morceaux)})."


# ── Requêtes ─────────────────────────────────────────────────────────────


def occupations_a(type_: str, code: str, iso: str, slot: int) -> list[dict]:
    return list(index().par_ressource.get((type_, _cle_code(type_, code)), {}).get((iso, slot), []))


def _uniques(evs: list[dict]) -> list[dict]:
    vus, sortie = set(), []
    for e in evs:
        cle = (e.get("event_id"), e.get("date"), e.get("debut"), e.get("code"))
        if cle not in vus:
            vus.add(cle)
            sortie.append(e)
    return sortie


def _creneaux_de(session, slot: int) -> list[int]:
    duree = max(1, int(getattr(session, "duration_slots", 1) or 1))
    return [slot + k for k in range(duree) if 0 <= slot + k < len(_CRENEAUX_MIN)]


def conflits_enseignant(state, session, week: int, day: int, slot: int, codes: list[str] | None = None) -> list[str]:
    """Messages pour chaque enseignant de la séance occupé dans Celcat."""
    codes = list(codes if codes is not None else (getattr(session, "teacher_codes", None) or []))
    if not codes or not index().par_ressource:
        return []
    d = _date_de(state, getattr(session, "semestre", None), week, day)
    if d is None:
        return []
    iso = d.isoformat()
    messages: list[str] = []
    for code in codes:
        evs = _uniques([e for s in _creneaux_de(session, slot) for e in occupations_a("enseignant", code, iso, s)])
        for e in evs:
            messages.append(message_enseignant(nom_enseignant(state, code, e), e))
    return messages


def _salles_liees(state, room_id: str) -> set[str]:
    from cal_iut.solver.rooms import build_manual_conflict_map

    cle = ("liees", id(state.rooms), len(state.rooms))
    with _verrou:
        carte = _cache.get("liees") if _cache.get("liees_cle") == cle else None
    if carte is None:
        carte = build_manual_conflict_map(state.rooms)
        with _verrou:
            _cache["liees_cle"], _cache["liees"] = cle, carte
    return {room_id} | set(carte.get(room_id, set()))


def conflits_salle(state, session, room_id: str | None, week: int, day: int, slot: int) -> list[str]:
    """Messages si la salle (ou une salle liée : H.007 ↔ H.007-008) est prise
    dans Celcat sur l'un des créneaux de la séance."""
    if not room_id or not index().par_ressource:
        return []
    d = _date_de(state, getattr(session, "semestre", None), week, day)
    if d is None:
        return []
    iso = d.isoformat()
    evs = _uniques([
        e for rid in sorted(_salles_liees(state, room_id)) for s in _creneaux_de(session, slot)
        for e in occupations_a("salle", rid, iso, s)
    ])
    libelle = _libelle_salle(state, room_id)
    return [message_salle(libelle, e) for e in evs]


def strict() -> bool:
    return config().strict


def appliquer_salle(state, session, room_id: str | None, week: int, day: int, slot: int, validation) -> list[str]:
    """Ajoute le conflit « salle prise dans Celcat » au résultat de
    `validate_move` (forçable, comme un conflit de salle) — ou, en mode
    `strict`, le RENVOIE pour que l'appelant refuse sans appel."""
    messages = conflits_salle(state, session, room_id, week, day, slot) if session is not None else []
    if not messages:
        return []
    if strict():
        return messages
    validation.hard_conflicts.extend(messages)
    validation.valid = False
    return []


# ── Générateur et affectation ───────────────────────────────────────────


def disponibilites_avec_externes(state, base: list) -> list:
    """`base` + une `TeacherDateSlotRule` par (enseignant, date) occupée dans
    Celcat — même mécanisme qu'une indisponibilité datée, donc dur pour le
    solveur (`add_teacher_availability_constraints`) et respecté par les
    suggestions (`_teacher_free_at`). Ne modifie jamais `base`."""
    from cal_iut.models.entities import TeacherAvailability, TeacherDateSlotRule

    idx = index()
    if not idx.par_ressource:
        return base
    cle = ("dispos", idx.signature, id(base), len(base), config().strict)
    with _verrou:
        if _cache.get("dispos_cle") == cle:
            return _cache["dispos"]
    par_code: dict[str, dict[str, set[int]]] = {}
    motifs: dict[tuple[str, str], str] = {}
    for (type_, code), cases in idx.par_ressource.items():
        if type_ != "enseignant":
            continue
        for (iso, s), evs in cases.items():
            par_code.setdefault(code, {}).setdefault(iso, set()).add(s)
            motifs.setdefault((code, iso), ", ".join(sorted({str(e.get("departement") or "hors dép.") for e in evs})))
    if not par_code:
        return base
    est_strict = config().strict
    fusion: dict[str, Any] = {a.teacher_code: a for a in base}
    sortie = list(base)
    for code, dates in par_code.items():
        regles = [
            TeacherDateSlotRule(date=iso, slots=sorted(slots), note=f"Celcat : occupé ailleurs ({motifs[(code, iso)]})",
                                stricte=est_strict)
            for iso, slots in sorted(dates.items())
        ]
        existant = fusion.get(code)
        if existant is not None:
            nouveau = existant.model_copy(update={"forbidden_date_slots": list(existant.forbidden_date_slots) + regles})
            sortie[sortie.index(existant)] = nouveau
        else:
            sortie.append(TeacherAvailability(teacher_code=code, forbidden_date_slots=regles))
    with _verrou:
        _cache["dispos_cle"], _cache["dispos"] = cle, sortie
    return sortie


def reservations_effectives(state) -> dict[str, set[int]]:
    """`state.room_reservations` (salles_reservees.yaml) + salles prises dans
    Celcat, au même format : {room_id: {index de créneau absolu}} — ce que
    `find_room_for_slot` / `assign_rooms` reçoivent en `reserved`."""
    base = getattr(state, "room_reservations", None)
    idx = index()
    if not idx.par_ressource:
        return base
    from cal_iut.models.timetable import DAYS_PER_WEEK, SLOTS_PER_DAY

    calendrier = getattr(state, "calendar", None)
    if calendrier is None:
        return base
    decalage = _decalage(state)
    cle = ("resa", idx.signature, id(base), id(calendrier), decalage)
    with _verrou:
        if _cache.get("resa_cle") == cle:
            return _cache["resa"]
    sortie: dict[str, set[int]] = {k: set(v) for k, v in (base or {}).items()}
    par_semaine = DAYS_PER_WEEK * SLOTS_PER_DAY
    for (type_, code), cases in idx.par_ressource.items():
        if type_ != "salle":
            continue
        for iso, s in cases:
            try:
                quand = calendrier.date_to_week_day_any(date.fromisoformat(iso))
            except ValueError:
                continue
            if quand is None:
                continue
            rel = quand[0] - decalage
            if rel < 0 or quand[1] >= DAYS_PER_WEEK:
                continue
            sortie.setdefault(code, set()).add(rel * par_semaine + quand[1] * SLOTS_PER_DAY + s)
    with _verrou:
        _cache["resa_cle"], _cache["resa"] = cle, sortie
    return sortie


# ── Séances déjà placées en conflit (« À traiter ») ─────────────────────


def seances_en_conflit(state) -> list[dict]:
    """Une entrée par (séance placée, ressource) en conflit avec une
    occupation externe. Même fonction pour l'écran (payload) et l'API v1."""
    if not index().par_ressource:
        return []
    sortie: list[dict] = []
    for p in getattr(state, "timetable", []) or []:
        session = state.sessions_by_id.get(p.session_id)
        if session is None:
            continue
        base = {
            "seance_id": p.session_id, "course_code": p.course_code,
            "nom": getattr(session, "course_name", "") or "",
            "type": getattr(getattr(session, "session_type", None), "value", "") or "",
            "semaine": p.week, "jour": p.day, "creneau": p.slot,
            "groupes": list(p.group_ids or []), "enseignants": list(p.teacher_codes or []),
        }
        for code in p.teacher_codes or []:
            for m in conflits_enseignant(state, session, p.week, p.day, p.slot, codes=[code]):
                sortie.append({**base, "ressource_type": "enseignant", "ressource": code, "message": m})
        rid = getattr(p, "room_id", None)
        for m in conflits_salle(state, session, rid, p.week, p.day, p.slot):
            sortie.append({**base, "ressource_type": "salle", "ressource": rid, "message": m})
    return sortie


# ── Payload / écrans ─────────────────────────────────────────────────────


def etat_releve() -> dict:
    releve = index().releve
    cfg = config()
    age = occ.age_depuis(releve.releve_le)
    return {
        "releveLe": releve.releve_le,
        "ageSecondes": age,
        "absent": releve.absent,
        "perime": releve.absent or (age is not None and age > cfg.fraicheur_heures * 3600),
        "fraicheurHeures": cfg.fraicheur_heures,
        "strict": cfg.strict,
        "erreur": releve.erreur,
    }


def pour_payload(state) -> dict:
    """Ce que l'écran affiche : blocs « Occupé ailleurs (TC) » / « Réservé
    dans Celcat », sur les semaines du planning chargé, et les séances déjà
    placées en conflit. Les clés courtes suivent celles de `rows`."""
    idx = index()
    sortie = {**etat_releve(), "occupations": [], "conflits": []}
    if not idx.par_ressource or getattr(state, "calendar", None) is None:
        return sortie
    decalage = _decalage(state)
    vus: set[tuple] = set()
    for e in idx.releve.evenements:
        slots = creneaux_chevauches(str(e.get("debut") or ""), str(e.get("fin") or ""))
        if not slots:
            continue
        try:
            quand = state.calendar.date_to_week_day_any(date.fromisoformat(str(e.get("date"))))
        except ValueError:
            continue
        if quand is None or quand[0] - decalage < 0:
            continue
        type_ = str(e.get("type") or "")
        code = _cle_code(type_, e.get("code"))
        cle = (type_, code, e.get("date"), e.get("debut"), e.get("fin"), e.get("event_id"))
        if cle in vus:
            continue
        vus.add(cle)
        sortie["occupations"].append({
            "t": type_, "code": code, "w": quand[0] - decalage, "d": quand[1], "s": slots,
            "date": e.get("date"), "debut": e.get("debut"), "fin": e.get("fin"),
            "dep": e.get("departement") or "", "lib": e.get("intitule") or "", "cat": e.get("categorie") or "",
        })
    sortie["conflits"] = seances_en_conflit(state)
    return sortie


def pour_admin(state) -> dict:
    """Écran Celcat → « Occupations hors MMI »."""
    idx = index()
    releve = idx.releve
    par_ressource: dict[tuple[str, str], int] = {}
    for e in releve.evenements:
        cle = (str(e.get("type") or ""), _cle_code(e.get("type"), e.get("code")))
        par_ressource[cle] = par_ressource.get(cle, 0) + 1
    ressources = []
    for r in releve.ressources:
        cle = (str(r.get("type") or ""), _cle_code(r.get("type"), r.get("code")))
        ressources.append({**r, "nombre": par_ressource.get(cle, 0)})
    return {
        **etat_releve(),
        "demandeEnCours": occ.demande_en_cours(),
        # `celcat_occupations.yaml::actif` : faux, le robot ne relève rien.
        "lectureActive": occ.charger_config().actif,
        "periode": releve.periode,
        "base": releve.base,
        "ignores": releve.ignores,
        "erreurs": releve.erreurs,
        "ressources": ressources,
        "evenements": releve.evenements,
        "conflits": seances_en_conflit(state),
    }


def sonde() -> object:
    """Sonde de révision : la signature du fichier d'état."""
    return _signature(occ.chemin_fichier())

