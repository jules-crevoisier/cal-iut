"""Vues CALCULÉES de l'API v1 — « À traiter » et annuaires (charges).

Ces deux écrans ne sont pas servis tels quels par le serveur : le frontend
les dérive du payload de `/app-state` (`frontend/src/utils/todo.ts`,
`frontend/src/utils/annuaires.ts`, `frontend/src/utils/sallesLibres.ts`).
Un client de l'API v1 n'a pas ce code ; sans ce module, il lui faudrait
réécrire les mêmes règles (regroupement « ×5 » des séances non placées
identiques, journées trouées à partir de deux créneaux vides, TP jumelés
comptés une seule fois pour un groupe, fusions de salles...) — et chacun les
réécrirait un peu différemment.

Portage FIDÈLE, fonction par fonction, sur les MÊMES données (le payload de
`/app-state`, `main.payload_app_state`) : les tests
(`tests/test_api_v1_complete_2026_09_29.py`) rejouent les fixtures de
`annuaires.test.ts` et `todo.test.ts` et vérifient les mêmes nombres. Une
règle changée dans l'un doit l'être dans l'autre — les deux fichiers TS le
rappellent en tête.

Seul écart VOLONTAIRE : le nombre de séances non placées d'un enseignant.
`annuaireEnseignants` compte `seancesNonPlacees[].profs`, qui porte des NOMS
(« MARINE RIGUET »), sous une clé de CODE (« MRI ») : hors fixture de test,
il rend donc 0. Ici, les noms sont ramenés aux codes exactement comme le
fait `todo.ts::indexNoms` pour le filtre « Enseignant » de l'écran « À
traiter » — même résultat que le frontend sur ses fixtures, bon résultat sur
les vraies données.

Fonctions pures : un payload (dict) en entrée, des dicts en sortie. Les
modèles Pydantic et les routes sont dans `api/v1.py`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, timedelta

HEURES_PAR_CRENEAU = 1.5
NB_CRENEAUX = 6
NB_JOURS = 5
CRENEAUX_SEMAINE = NB_JOURS * NB_CRENEAUX


# ── Outils communs ──────────────────────────────────────────────────────


def cle_fr(texte: str) -> str:
    """Clé de tri proche de `localeCompare(…, "fr")` : sans accents ni casse."""
    decompose = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in decompose if not unicodedata.combining(c)).casefold()


def _cle_numerique(texte: str) -> tuple:
    """`localeCompare(…, { numeric: true })` : « WR2 » avant « WR10 »."""
    return tuple(int(p) if p.isdigit() else cle_fr(p) for p in re.split(r"(\d+)", texte or "") if p != "")


def cle_parcours(parcours: str) -> tuple:
    """`years.ts::compareParcoursForDisplay` : année, FI avant FC, puis nom."""
    m = re.match(r"^BUT(\d)", parcours or "")
    return (m.group(1) if m else "9", "FC" in (parcours or ""), cle_fr(parcours))


def _normaliser_nom(nom: str) -> str:
    return re.sub(r"\s+", " ", cle_fr(nom)).strip()


def index_noms(payload: dict) -> dict[str, str]:
    """`todo.ts::indexNoms` — nom normalisé → code enseignant."""
    return {_normaliser_nom(nom): code for code, nom in (payload.get("teacherLabels") or {}).items()}


def code_enseignant(noms: dict[str, str], nom_ou_code: str) -> str:
    return noms.get(_normaliser_nom(nom_ou_code), nom_ou_code)


def heures_de(rows: Iterable[dict]) -> float:
    """`planning.ts::heuresDe` — somme des durées (mesure d'un enseignant)."""
    return sum(max(1, r.get("dur") or 1) * HEURES_PAR_CRENEAU for r in rows)


def heures_occupees(rows: Iterable[dict]) -> float:
    """`annuaires.ts::heuresOccupees` — chaque créneau compté UNE fois : deux
    TP jumelés en parallèle durent 1 h 30, pas 3 h (mesure d'un groupe)."""
    vus: set[tuple[int, int, int]] = set()
    for r in rows:
        for k in range(max(1, r.get("dur") or 1)):
            vus.add((r["w"], r["d"], r["s"] + k))
    return len(vus) * HEURES_PAR_CRENEAU


def _par_semaine(rows: Iterable[dict], mesure) -> dict[int, float]:
    groupes: dict[int, list[dict]] = {}
    for r in rows:
        groupes.setdefault(int(r["w"]), []).append(r)
    return {w: mesure(rs) for w, rs in sorted(groupes.items())}


def lundis(payload: dict) -> dict[int, date]:
    """Index solveur → lundi, depuis `weekDates` (vide = inconnu)."""
    sortie = {}
    for i, iso in enumerate(payload.get("weekDates") or []):
        if iso:
            sortie[i] = date.fromisoformat(str(iso))
    return sortie


def date_de(payload_lundis: dict[int, date], semaine: int | None, jour: int | None) -> str | None:
    if semaine is None or jour is None or semaine not in payload_lundis:
        return None
    return (payload_lundis[semaine] + timedelta(days=jour)).isoformat()


def semaine_de_date(payload_lundis: dict[int, date], iso: str) -> tuple[int, int] | None:
    """`todo.ts::semaineDeDate` — (semaine solveur, jour) d'une date ISO."""
    try:
        cible = date.fromisoformat(iso)
    except ValueError:
        return None
    for i, lundi in sorted(payload_lundis.items()):
        ecart = (cible - lundi).days
        if 0 <= ecart < 7:
            return i, ecart
    return None


def statuts_semaines(payload: dict) -> dict[int, str]:
    """`weekStatus` : index solveur → past / current / future."""
    return {int(r["week"]): str(r["status"]) for r in payload.get("weekStatus") or []}


# ── « À traiter » (portage de `todo.ts`) ────────────────────────────────

# Ordre = ordre d'importance (`todo.ts::NATURES`). `gravite` : « a_corriger »
# (rouge à l'écran, `sev: "bad"`) ou « a_revoir » (ambre, `sev: "warn"`).
NATURES: list[dict[str, str]] = [
    {
        "id": "non-placee", "titre": "Séances non placées", "gravite": "a_corriger",
        "aide": "Des heures prévues sans aucun créneau. On les rattrape depuis le panneau « À placer » de la Vue Promo.",
    },
    {
        "id": "sans-salle", "titre": "Séances sans salle", "gravite": "a_corriger",
        "aide": "Placées, mais personne ne sait où les suivre. La salle se choisit en Vue Promo.",
    },
    {
        "id": "doublon", "titre": "Doublons salle / enseignant", "gravite": "a_corriger",
        "aide": "Une salle ou un enseignant pris deux fois sur le même créneau. "
                "H.201/H.203 et H.007/H.008 comptent comme une seule salle.",
    },
    {
        "id": "regle", "titre": "Règles globales en échec", "gravite": "a_corriger",
        "aide": "Le détail de chaque règle est dans l'onglet Contraintes.",
    },
    {
        "id": "contrainte", "titre": "Indisponibilités enseignant non respectées", "gravite": "a_corriger",
        "aide": "Une indisponibilité déclarée par l'enseignant tombe sur une de ses séances.",
    },
    {
        # 01/10/2026 : séances déjà placées sur un créneau où l'enseignant ou
        # la salle est pris AILLEURS dans Celcat (relevé du sidecar) — même
        # liste que `payload.occupationsExternes.conflits`
        # (`api/occupations_externes.py::seances_en_conflit`).
        # CONTRAINTE MOLLE depuis le 02/10/2026 (demande de Jules) : « à
        # revoir », plus « à corriger ».
        "id": "occupation-externe", "titre": "Pris ailleurs dans Celcat", "gravite": "a_revoir",
        "aide": "L'enseignant ou la salle est aussi pris dans Celcat (autre département, réunion, réservation) "
                "sur le créneau d'une séance placée. À revoir : rien n'est bloqué.",
    },
    {
        # 29/09/2026 : même règle et même calcul que `/api/v1/sae`
        # (`v1._marquer`, champ `anomalie`) — cf. `points_depuis_sae`.
        "id": "sae-hors-journee", "titre": "Cours de SAE hors journée SAE", "gravite": "a_corriger",
        "aide": "Un cours de SAE n'a lieu que sur une journée SAE de son parcours. Les SAE que la génération "
                "place elle-même (exception déclarée, ex. WSA501D) n'y figurent pas.",
    },
    {
        "id": "compromis-sae", "titre": "Encadrement SAE le même jour", "gravite": "a_revoir",
        "aide": "Compromis accepté : l'enseignant encadre une SAE le jour d'un de ses cours. "
                "À revoir si possible, rien d'interdit.",
    },
    {
        "id": "trouee", "titre": "Journées trouées", "gravite": "a_revoir",
        "aide": "Au moins deux créneaux vides entre deux cours d'un même groupe dans la journée.",
    },
]
GRAVITE_PAR_NATURE = {n["id"]: n["gravite"] for n in NATURES}


def _parcours_des_groupes(payload: dict, groupes: Iterable[str]) -> list[str]:
    parcours_de = payload.get("groupParcours") or {}
    sortie: list[str] = []
    for g in groupes:
        p = parcours_de.get(g)
        if p and p not in sortie:
            sortie.append(p)
    return sortie


def _point(nature: str, cle: str, titre: str, detail: str, *, semaine=None, jour=None, creneau=None,
           parcours=(), enseignants=(), **extra) -> dict:
    return {
        "nature": nature, "gravite": GRAVITE_PAR_NATURE[nature], "cle": cle, "titre": titre, "detail": detail,
        "semaine": semaine, "jour": jour, "creneau": creneau,
        "parcours": list(parcours), "enseignants": list(enseignants), "nombre": 1, **extra,
    }


def points_a_traiter(payload: dict) -> list[dict]:
    """`todo.ts::buildTodoList` — tout sauf les doublons (calculés à part,
    cf. `points_depuis_doublons`)."""
    points: list[dict] = []
    noms = index_noms(payload)
    libelles_groupes = payload.get("groupLabels") or {}
    lundis_ = lundis(payload)

    non_placees: dict[str, dict] = {}
    for s in payload.get("seancesNonPlacees") or []:
        cle = f"np|{s['code']}|{s['type']}|{','.join(s['groupes'])}|{','.join(s['profs'])}"
        if cle in non_placees:
            non_placees[cle]["nombre"] += 1
            continue
        point = _point(
            "non-placee", cle, f"{s['code']} — {s.get('nom') or 'séance non placée'}",
            f"{s['type']} · {', '.join(s['groupes'])} · {', '.join(s['profs'])}",
            parcours=[s["parcours"]] if s.get("parcours") else [],
            enseignants=[code_enseignant(noms, p) for p in s["profs"]],
        )
        non_placees[cle] = point
        points.append(point)

    for r in payload.get("rows") or []:
        if r.get("r"):
            continue
        groupes = ", ".join(libelles_groupes.get(g, g) for g in r["g"])
        points.append(_point(
            "sans-salle", f"ss|{r['id']}", f"{r['c']} — {r.get('n') or r['t']}", f"{r['t']} · {groupes}",
            semaine=r["w"], jour=r["d"], creneau=r["s"],
            parcours=_parcours_des_groupes(payload, r["g"]), enseignants=r["te"], seance_id=r["id"],
        ))

    par_cle: dict[str, dict] = {}
    cours = payload.get("courses") or []
    for t in payload.get("teachers") or []:
        for v in t.get("violations") or []:
            compromis = v.get("reason") == "sae_supervision"
            quand = semaine_de_date(lundis_, v["date"]) if v.get("date") else None
            semaine = v["week"] if v.get("week") is not None else (quand[0] if quand else None)
            jour = v["day"] if v.get("day") is not None else (quand[1] if quand else None)
            creneau = v.get("slot")
            repere = v.get("date") or f"{_js(semaine)}-{_js(jour)}-{_js(creneau)}"
            cle = f"{'sae' if compromis else 'ct'}|{t['code']}|{repere}|{v['course_code']}"
            if cle in par_cle:
                par_cle[cle]["nombre"] += 1
                continue
            parcours: list[str] = []
            for c in cours:
                if c["code"] == v["course_code"] and c.get("parcours") and c["parcours"] not in parcours:
                    parcours.append(c["parcours"])
            point = _point(
                "compromis-sae" if compromis else "contrainte", cle, t["name"], v["course_code"],
                semaine=semaine, jour=jour, creneau=creneau, parcours=parcours, enseignants=[t["code"]],
                motif=v.get("motif"),
            )
            par_cle[cle] = point
            points.append(point)

    par_groupe_jour: dict[tuple[str, int, int], list[int]] = {}
    for r in payload.get("rows") or []:
        for g in r["g"]:
            par_groupe_jour.setdefault((g, r["w"], r["d"]), []).append(r["s"])
    genres = payload.get("groupKind") or {}
    parcours_de = payload.get("groupParcours") or {}
    for (gid, w, d), creneaux in par_groupe_jour.items():
        if genres.get(gid) == "promo":
            continue
        utilises = set(creneaux)
        trou = sum(1 for s in range(min(creneaux), max(creneaux) + 1) if s not in utilises)
        if trou >= 2:
            pc = parcours_de.get(gid)
            libelle = libelles_groupes.get(gid) or gid
            points.append(_point(
                "trouee", f"tr|{gid}|{w}|{d}", f"{pc} · {libelle}" if pc else libelle,
                f"{trou} créneaux vides entre deux cours", semaine=w, jour=d,
                parcours=[pc] if pc else [], groupe=gid,
            ))

    for c in payload.get("ruleChecks") or []:
        if c.get("status") == "fail":
            points.append(_point("regle", f"rg|{c['id']}", c["label"], c.get("detail") or "", regle=c["id"]))

    # Occupés ailleurs dans Celcat (01/10/2026) — `todo.ts::buildTodoList`,
    # même ordre, mêmes clés.
    for c in (payload.get("occupationsExternes") or {}).get("conflits") or []:
        points.append(_point(
            "occupation-externe", f"oe|{c['seance_id']}|{c['ressource_type']}|{c['ressource']}",
            f"{c['course_code']} — {c.get('nom') or c.get('type') or ''}", c["message"],
            semaine=c["semaine"], jour=c["jour"], creneau=c["creneau"],
            parcours=_parcours_des_groupes(payload, c.get("groupes") or []),
            enseignants=list(c.get("enseignants") or []), seance_id=c["seance_id"],
        ))
    return points


def _js(valeur: object) -> str:
    """Rendu d'un nombre dans une clé, comme un gabarit JS (`null` compris)."""
    return "null" if valeur is None else str(valeur)


def points_depuis_doublons(payload: dict, doublons: list[dict]) -> list[dict]:
    """`todo.ts::pointsDepuisDoublons` (sans le badge « nouveau », qui dépend
    du contrôle hebdomadaire et non de l'état du planning)."""
    points = []
    for d in doublons:
        seances = d.get("seances") or []
        codes = list(dict.fromkeys(s["course_code"] for s in seances))
        enseignants: list[str] = []
        for s in seances:
            for e in s.get("enseignants") or []:
                if e not in enseignants:
                    enseignants.append(e)
        points.append(_point(
            "doublon", f"db|{d['semaine']}|{d['jour']}|{d['creneau']}|{d['type']}|{d['ressource']}",
            d["ressource"], " / ".join(codes), semaine=d["semaine"], jour=d["jour"], creneau=d["creneau"],
            parcours=_parcours_des_groupes(payload, [g for s in seances for g in s.get("groupes") or []]),
            enseignants=enseignants, type_doublon="salle" if d["type"] == "salle" else "enseignant",
            seances=[s["session_id"] for s in seances],
        ))
    return points


def points_depuis_sae(payload: dict, anomalies: list[dict]) -> list[dict]:
    """`todo.ts::pointsDepuisSae` : un point par cours de SAE placé hors
    journée SAE SANS exception déclarée — la liste `anomalies` de
    `/api/v1/sae` (`v1._saes`), jamais recalculée ici.

    Les exceptions déclarées (`solver_scheduled_sae`, ex. WSA501D) n'y
    figurent pas : c'est une décision déjà prise, visible avec son motif
    dans `/api/v1/sae` ; la lister en « à revoir » la ferait revenir à
    chaque visite sans qu'aucun geste ne puisse la faire disparaître."""
    points = []
    for a in anomalies:
        groupes = ", ".join(a.get("groupes_libelles") or a.get("groupes") or [])
        points.append(_point(
            "sae-hors-journee", f"sae-hj|{a['id']}", f"{a['cours_code']} — {a.get('cours_nom') or a['cours_code']}",
            f"{a['type']} · {groupes} · hors journée SAE", semaine=a["semaine"], jour=a["jour"],
            creneau=a["creneau"], parcours=[a["parcours"]] if a.get("parcours") else [],
            enseignants=list(a.get("enseignants") or []), seance_id=a["id"],
        ))
    return points


def filtrer_points(points: list[dict], *, semaine: int | None = None, parcours: str | None = None,
                   enseignant: str | None = None, gravite: str | None = None,
                   nature: str | None = None) -> list[dict]:
    """`todo.ts::filtrerPoints` : un point SANS semaine (non placée, règle
    globale) passe le filtre de semaine — il reste toujours important —,
    mais pas ceux de parcours ni d'enseignant."""
    sortie = []
    for p in points:
        if gravite and p["gravite"] != gravite:
            continue
        if nature and p["nature"] != nature:
            continue
        if parcours and parcours not in p["parcours"]:
            continue
        if enseignant and enseignant not in p["enseignants"]:
            continue
        if semaine is not None and p["semaine"] is not None and p["semaine"] != semaine:
            continue
        sortie.append(p)
    return sortie


def trier_par_urgence(points: list[dict], statuts: dict[int, str]) -> list[dict]:
    """`todo.ts::trierParUrgence` : sans semaine, semaine en cours, semaines à
    venir dans l'ordre, puis semaines passées (la plus récente d'abord)."""
    def rang(p: dict) -> tuple:
        w = p["semaine"]
        if w is None:
            groupe, sous = 0, 0
        else:
            s = statuts.get(w, "future")
            groupe, sous = (1, 0) if s == "current" else (2, w) if s == "future" else (3, -w)
        return (groupe, sous, -1 if p["jour"] is None else p["jour"], -1 if p["creneau"] is None else p["creneau"])

    return sorted(points, key=rang)


# ── Annuaires / charges (portage de `annuaires.ts`) ─────────────────────


def _rows_par(payload: dict, cle) -> dict[str, list[dict]]:
    sortie: dict[str, list[dict]] = {}
    for r in payload.get("rows") or []:
        for k in cle(r):
            sortie.setdefault(k, []).append(r)
    return sortie


def charges_enseignants(payload: dict, semaine: int | None) -> list[dict]:
    """`annuaireEnseignants` (cf. docstring du module pour `nb_non_placees`)."""
    rows_par_prof = _rows_par(payload, lambda r: r["te"])
    noms = index_noms(payload)
    non_placees: dict[str, int] = {}
    for s in payload.get("seancesNonPlacees") or []:
        for p in s["profs"]:
            code = code_enseignant(noms, p)
            non_placees[code] = non_placees.get(code, 0) + 1
    infos = {t["code"]: t for t in payload.get("teachers") or []}
    libelles = payload.get("teacherLabels") or {}
    sortie = []
    for code in libelles:
        rows = rows_par_prof.get(code, [])
        info = infos.get(code)
        violations = (info or {}).get("violations") or []
        ecarts = sum(1 for v in violations if v.get("reason") != "sae_supervision")
        sae = len(violations) - ecarts
        if not (info or {}).get("hasConstraint"):
            contrainte = "aucune"
        elif ecarts:
            contrainte = "ecarts"
        elif sae:
            contrainte = "compromis_sae"
        else:
            contrainte = "respectee"
        sortie.append({
            "code": code, "nom": libelles.get(code, code),
            "heures_semaine": heures_de(r for r in rows if r["w"] == semaine) if semaine is not None else None,
            "heures_semestre": heures_de(rows), "heures_par_semaine": _par_semaine(rows, heures_de),
            "nb_seances": len(rows), "nb_matieres": len({r["c"] for r in rows}),
            "nb_non_placees": non_placees.get(code, 0), "contrainte": contrainte, "nb_ecarts": ecarts,
        })
    sortie.sort(key=lambda x: cle_fr(x["nom"]))
    return sortie


_ORDRE_TYPE = {"promo": 0, "cm": 0, "td": 1, "tp": 2}


def charges_groupes(payload: dict, semaine: int | None) -> list[dict]:
    """`annuaireGroupes` : ce que suit un étudiant du groupe (sa cohorte),
    chaque créneau compté une fois."""
    par_groupe = _rows_par(payload, lambda r: r["g"])
    cohortes = payload.get("groupCohort") or {}
    sortie = []
    for gid, libelle in (payload.get("groupLabels") or {}).items():
        rows: dict[str, dict] = {}
        for g in cohortes.get(gid) or [gid]:
            for r in par_groupe.get(g, []):
                rows[r["id"]] = r
        toutes = list(rows.values())
        sortie.append({
            "id": gid, "libelle": libelle or gid, "parcours": (payload.get("groupParcours") or {}).get(gid, ""),
            "type": (payload.get("groupKind") or {}).get(gid, ""), "fc": bool((payload.get("groupIsFc") or {}).get(gid)),
            "heures_semaine": heures_occupees(r for r in toutes if r["w"] == semaine) if semaine is not None else None,
            "heures_semestre": heures_occupees(toutes), "heures_par_semaine": _par_semaine(toutes, heures_occupees),
        })
    sortie.sort(key=lambda x: (cle_parcours(x["parcours"]), _ORDRE_TYPE.get(x["type"], 9), cle_fr(x["libelle"])))
    return sortie


def charges_cours(payload: dict, semaine: int | None) -> list[dict]:
    """`annuaireCours` : une ligne par matière ET par parcours."""
    par_code = _rows_par(payload, lambda r: [r["c"]])
    cours = payload.get("courses") or []
    nb_entrees: dict[str, int] = {}
    for e in cours:
        nb_entrees[e["code"]] = nb_entrees.get(e["code"], 0) + 1
    parcours_de = payload.get("groupParcours") or {}
    non_placees = payload.get("seancesNonPlacees") or []
    sortie = []
    for e in cours:
        toutes = par_code.get(e["code"], [])
        if nb_entrees.get(e["code"], 1) > 1:
            rows = [r for r in toutes if any(parcours_de.get(g) == e["parcours"] for g in r["g"])]
        else:
            rows = toutes
        enseignants = list(dict.fromkeys([*e.get("teachers", []), *(t for r in rows for t in r["te"])]))
        sortie.append({
            "code": e["code"], "nom": e["name"], "parcours": e["parcours"], "semestre": e["semestre"],
            "prevues": e["nCM"] + e["nTD"] + e["nTP"] + e["nEval"], "placees": e["nPlaced"],
            "non_placees": sum(
                1 for s in non_placees
                if s["code"] == e["code"] and (not s.get("parcours") or not e["parcours"] or s["parcours"] == e["parcours"])
            ),
            "heures_semaine": heures_de(r for r in rows if r["w"] == semaine) if semaine is not None else None,
            "heures_placees": heures_de(rows), "heures_par_semaine": _par_semaine(rows, heures_de),
            "enseignants": enseignants,
        })
    sortie.sort(key=lambda x: (cle_parcours(x["parcours"]), cle_fr(x["semestre"]), _cle_numerique(x["code"])))
    return sortie


def _normaliser_libelle_salle(libelle: str) -> str:
    """`sallesLibres.ts::normaliserLibelleSalle` — retire « (Évaluation) »."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", libelle or "").strip()


def occupation_salles(payload: dict) -> dict[str, set[tuple[int, int, int]]]:
    """`sallesLibres.ts::occupationSalles`, pour TOUTES les semaines d'un
    coup : salle → cases (semaine, jour, créneau) occupées. Occuper une salle
    fusionnée occupe chacune de ses parties ; occuper une partie occupe la
    fusion (jamais l'autre partie). Réservations de tiers comprises."""
    salles = payload.get("rooms") or []
    cases: dict[str, set[tuple[int, int, int]]] = {r["id"]: set() for r in salles}
    fusions_par_partie: dict[str, list[str]] = {}
    for r in salles:
        for partie in r.get("combines") or []:
            fusions_par_partie.setdefault(partie, []).append(r["id"])
    par_libelle = {_normaliser_libelle_salle(r["label"]): r for r in salles}
    par_id = {r["id"]: r for r in salles}

    def marquer(salle_id: str, w: int, d: int, s: int) -> None:
        if salle_id in cases and 0 <= s < NB_CRENEAUX:
            cases[salle_id].add((w, d, s))

    def marquer_avec_liees(salle_id: str, w: int, d: int, s: int) -> None:
        marquer(salle_id, w, d, s)
        for partie in (par_id.get(salle_id) or {}).get("combines") or []:
            marquer(partie, w, d, s)
        for fusion in fusions_par_partie.get(salle_id, []):
            marquer(fusion, w, d, s)

    for r in payload.get("rows") or []:
        if not r.get("r") or not 0 <= r["d"] < NB_JOURS:
            continue
        salle = par_libelle.get(_normaliser_libelle_salle(r["r"]))
        if salle is None:
            continue
        for k in range(max(1, r.get("dur") or 1)):
            if r["s"] + k >= NB_CRENEAUX:
                break
            marquer_avec_liees(salle["id"], r["w"], r["d"], r["s"] + k)

    semaine_par_date: dict[str, tuple[int, int]] = {}
    for row in payload.get("weekRows") or []:
        if row.get("weekIndex") is None or not row.get("monday"):
            continue
        lundi = date.fromisoformat(str(row["monday"]))
        for d in range(NB_JOURS):
            semaine_par_date[(lundi + timedelta(days=d)).isoformat()] = (int(row["weekIndex"]), d)
    for resa in payload.get("roomReservations") or []:
        quand = semaine_par_date.get(str(resa.get("date")))
        if quand is None:
            continue
        for s in resa.get("slots") or []:
            marquer_avec_liees(str(resa.get("salle")), quand[0], quand[1], int(s))
    # Salles prises dans Celcat (relevé du sidecar, 01/10/2026) : comme une
    # réservation de tiers.
    for o in (payload.get("occupationsExternes") or {}).get("occupations") or []:
        if o.get("t") != "salle":
            continue
        for s in o.get("s") or []:
            marquer_avec_liees(str(o.get("code")), int(o["w"]), int(o["d"]), int(s))
    return cases


def charges_salles(payload: dict, semaine: int | None) -> list[dict]:
    """`annuaireSalles` : créneaux occupés de la semaine sur 30."""
    occupation = occupation_salles(payload)
    sortie = []
    for r in payload.get("rooms") or []:
        cases = occupation.get(r["id"], set())
        par_semaine: dict[int, float] = {}
        for w, _d, _s in cases:
            par_semaine[w] = par_semaine.get(w, 0) + 1
        n = int(par_semaine.get(semaine, 0)) if semaine is not None else None
        sortie.append({
            "id": r["id"], "libelle": r["label"], "capacite": r["capacity"], "type": r["type"],
            "placement_auto": bool(r.get("placementAuto", True)),
            "creneaux_occupes": n, "taux": (n / CRENEAUX_SEMAINE) if n is not None else None,
            "creneaux_par_semaine": {w: int(v) for w, v in sorted(par_semaine.items())},
            "seances_semestre": r.get("nSessions", 0),
        })
    sortie.sort(key=lambda x: cle_fr(x["libelle"]))
    return sortie


def charges_parcours(payload: dict, semaine: int | None) -> list[dict]:
    """Volume ENSEIGNÉ d'un parcours (somme des séances dont un groupe lui
    appartient, comme `heuresDe`) — pas d'équivalent à l'écran, où la charge
    d'une promo se lit sur son groupe « promo » dans `charges_groupes`."""
    parcours_de = payload.get("groupParcours") or {}
    par_parcours = _rows_par(payload, lambda r: list(dict.fromkeys(p for g in r["g"] if (p := parcours_de.get(g)))))
    sortie = []
    for p in sorted(set(parcours_de.values()), key=cle_parcours):
        rows = par_parcours.get(p, [])
        sortie.append({
            "id": p, "nb_seances": len(rows),
            "heures_semaine": heures_de(r for r in rows if r["w"] == semaine) if semaine is not None else None,
            "heures_semestre": heures_de(rows), "heures_par_semaine": _par_semaine(rows, heures_de),
        })
    return sortie
