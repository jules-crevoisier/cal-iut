"""Régénère `contraintes/*.json` à partir des fichiers sources de `contraintes_update/`.

Les fichiers sources (CSV Google Sheets exportés, `maquette.json`,
`progression.json`) font foi. Ce script est la SEULE façon de produire
`contraintes/*.json` : ne jamais éditer ces JSON à la main, ré-exécuter

    python scripts/build_contraintes.py

après chaque mise à jour d'un fichier source.

Arbitrages humains câblés ici (confirmés par l'utilisateur le 10/08/2026,
cf. `_ARBITRAGES` en bas de fichier pour la liste complète et sourcée) :
ils sont volontairement regroupés en constantes nommées plutôt que dispersés,
pour qu'un futur relecteur voie d'un coup d'œil ce qui vient du fichier source
et ce qui vient d'une décision.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "contraintes_update"
OUT = ROOT / "contraintes"

MONTH_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "nvembre": 11, "décembre": 12, "decembre": 12,
}
DAY_FR = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4}
DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

_DATE_RE = re.compile(
    r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)?\s*(\d{1,2})\s*"
    r"(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|"
    r"octobre|novembre|nvembre|décembre|decembre)\s*(\d{4})?",
    re.IGNORECASE,
)


def find_source(fragment: str) -> Path:
    """Retrouve un fichier source par fragment de nom (les vrais noms portent
    des accents que l'encodage de la console Windows ne restitue pas)."""
    matches = [p for p in SRC.iterdir() if fragment.lower() in p.name.lower()]
    if not matches:
        raise SystemExit(f"Source introuvable dans {SRC} : *{fragment}*")
    return min(matches)


def parse_fr_date(text: str, default_year: int | None = None) -> tuple[date | None, str | None]:
    """"lundi 26 octobre 2026" -> (date(2026,10,26), "lundi"). Année déduite du
    mois si absente (sept.-déc. = 2026, janv.-août = 2027, calage année
    universitaire)."""
    m = _DATE_RE.search(text)
    if not m:
        return None, None
    day = int(m.group(2))
    month = MONTH_FR[m.group(3).lower()]
    if m.group(4):
        year = int(m.group(4))
    elif default_year is not None:
        year = default_year
    else:
        year = 2026 if month >= 9 else 2027
    try:
        return date(year, month, day), (m.group(1).lower() if m.group(1) else None)
    except ValueError:
        return None, None


def read_text_csv(path: Path) -> list[str]:
    """Les CSV « liste de dates » n'ont qu'une colonne utile : on les lit en
    lignes de texte brut, pas en tableau."""
    return path.read_text(encoding="utf-8").splitlines()


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ---------------------------------------------------------------------------
# 02 — calendrier IUT (vacances, fériés, jalons)
# ---------------------------------------------------------------------------


def build_calendrier_iut() -> dict:
    path = find_source("INDISPONIBILIT")
    lines = read_text_csv(path)

    feries: dict[date, str] = {}
    jalons: list[dict] = []
    pause_blocks: list[list[date]] = []
    current: list[date] = []
    in_modele = False
    # Le fichier se termine par une section "JOURS FÉRIÉS :" dont les dates sont
    # nues (sans " : jour férié"). Sans ce suivi de section, elles seraient
    # lues comme une pause pédagogique de 3 jours répartis sur 6 mois.
    section = "pauses"

    for raw in lines:
        line = raw.strip().strip(",").strip()
        if line.upper().startswith("MODÈLE"):
            in_modele = True
            continue
        if in_modele:
            if line.startswith(")"):
                in_modele = False
            continue
        if not line:
            if current:
                pause_blocks.append(current)
                current = []
            continue

        # "Mercredi 11 novembre 2026 : jour férié" / "Lundi 4 janvier 2027 : Début du semestre 2"
        annotation = None
        if ":" in line:
            head, _, tail = line.partition(":")
            d, _ = parse_fr_date(head)
            if d is not None:
                annotation = tail.strip()
                line = head
            else:
                # en-tête de section ("JOURS FÉRIÉS :", "Pause pédagogique de l'ascension :")
                if "FÉRI" in head.upper() or "FERI" in head.upper():
                    section = "feries"
                    if current:
                        pause_blocks.append(current)
                        current = []
                else:
                    section = "pauses"
                continue

        d, _ = parse_fr_date(line)
        if d is None:
            continue

        if annotation is None and section == "feries":
            feries.setdefault(d, "jour férié")
            continue

        if annotation is not None:
            if "férié" in annotation.lower() or "ferie" in annotation.lower():
                feries.setdefault(d, annotation)
            else:
                jalons.append({"dates": [d.isoformat()], "debut": d.isoformat(),
                               "fin": d.isoformat(), "nom": annotation})
            if current:
                pause_blocks.append(current)
                current = []
            continue

        current.append(d)

    if current:
        pause_blocks.append(current)

    vacances = []
    for block in pause_blocks:
        block = sorted(set(block))
        entry = {
            "debut": block[0].isoformat(),
            "fin": block[-1].isoformat(),
            "dates": [d.isoformat() for d in block],
        }
        if any(d in feries for d in block):
            noms = ", ".join(f"{d.strftime('%d/%m/%Y')} = {feries[d]}" for d in block if d in feries)
            entry["note"] = f"Contient un jour férié : {noms}"
        vacances.append(entry)

    return {
        "source_fichier": path.name,
        "genere_par": "scripts/build_contraintes.py",
        "vacances_et_pauses_pedagogiques": vacances,
        "jours_feries": [
            {"date": d.isoformat(), "nom": nom} for d, nom in sorted(feries.items())
        ],
        "jalons_et_evenements": sorted(jalons, key=lambda e: e["debut"]),
    }


# ---------------------------------------------------------------------------
# 03 — calendrier d'alternance FC
# ---------------------------------------------------------------------------

_ALTERNANCE_BLOCKS = {
    "BUT2_FC_S3_S4": ("BUT2", ["S3-DEV-FC", "S4-DEV-FC", "S3-CREACOM-FC", "S4-CREACOM-FC"]),
    "BUT3_FC_S5_S6": ("BUT3", ["S5-DEV-FC", "S6-DEV-FC", "S5-CREACOM-FC", "S6-CREACOM-FC"]),
}
# Un libellé de date porteur d'un de ces mots décrit un ÉVÉNEMENT ponctuel
# (soutenance, fin de formation), pas une semaine de cours à l'IUT.
_EVENT_MARKERS = ("soutenance", "fin de formation")


def _parse_presence_file(path: Path) -> tuple[list[dict], list[str]]:
    blocks: list[list[tuple[date, str]]] = []
    current: list[tuple[date, str]] = []
    events: list[str] = []
    in_modele = False
    started = False

    for raw in read_text_csv(path):
        line = raw.strip().strip(",").strip()
        if line.upper().startswith("MODÈLE"):
            in_modele = True
            continue
        if in_modele:
            if line.startswith(")"):
                in_modele = False
            continue
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue

        d, _ = parse_fr_date(line)
        if d is None:
            continue
        started = True
        note = ""
        for sep in (" : ", " mais ", " pourtant "):
            if sep in line:
                note = line.split(sep, 1)[1].strip()
                if sep != " : ":
                    note = f"{sep.strip()} {note}"
                break

        if any(marker in line.lower() for marker in _EVENT_MARKERS):
            events.append(line)
            continue
        current.append((d, note))

    if current:
        blocks.append(current)
    if not started:
        raise SystemExit(f"Aucune date lue dans {path.name}")

    semaines = []
    for block in blocks:
        dates = sorted({d for d, _ in block})
        notes = [n for _, n in block if n]
        semaines.append({
            "debut": dates[0].isoformat(),
            "fin": dates[-1].isoformat(),
            "dates": [d.isoformat() for d in dates],
            "notes": notes,
        })
    return semaines, events


def build_alternance(calendrier: dict) -> dict:
    fermetures: set[date] = set()
    for entry in calendrier["vacances_et_pauses_pedagogiques"]:
        fermetures.update(date.fromisoformat(d) for d in entry["dates"])
    fermetures.update(date.fromisoformat(e["date"]) for e in calendrier["jours_feries"])

    out: dict = {
        "source": "DISPONIBILITÉS ÉTUDIANTS BUT2 / BUT3 (fichiers officiels)",
        "genere_par": "scripts/build_contraintes.py",
        "regle_lecture": (
            "Chaque entree = une semaine ou les etudiants FC concernes sont A "
            "L'IUT (donc disponibles pour y placer des cours). En dehors de ces "
            "semaines, ils sont en entreprise."
        ),
    }
    conflits: dict[str, list] = {}

    for key, (_, parcours) in _ALTERNANCE_BLOCKS.items():
        fragment = "BUT2 - S3-FC" if key.startswith("BUT2") else "BUT3 - S5-FC"
        semaines, events = _parse_presence_file(find_source(fragment))
        block: dict = {"parcours_concernes": parcours, "semaines_iut": semaines}
        if events:
            block["evenements_speciaux"] = events
        out[key] = block

        conflits[key] = [
            {
                "semaine_debut": w["debut"],
                "semaine_fin": w["fin"],
                "jours_en_conflit_avec_fermeture_iut": [
                    d for d in w["dates"] if date.fromisoformat(d) in fermetures
                ],
                "notes_source": w["notes"],
            }
            for w in semaines
            if any(date.fromisoformat(d) in fermetures for d in w["dates"])
        ]

    out["conflits_detectes_automatiquement"] = {
        "regle": (
            "Un conflit signifie qu'une semaine listee comme 'semaine IUT' pour "
            "les alternants contient au moins un jour marque ferme dans le "
            "calendrier officiel de l'IUT. Regle absolue : la fermeture IUT "
            "prevaut toujours."
        ),
        **conflits,
    }
    return out


# ---------------------------------------------------------------------------
# 05 — contraintes enseignants
# ---------------------------------------------------------------------------

# Décisions humaines (10/08/2026) — cf. `_ARBITRAGES`.
#
# `disponibilites_exclusives` : un enseignant qui déclare des DISPONIBILITÉS
# n'est plaçable QUE là. Confirmé explicitement ("Oui, jours non listés
# interdits" + "Liste blanche dure" pour MNI).
_DISPOS_EXCLUSIVES = {"MNI", "VBU", "KNG", "EHU"}

# Indisponibilités présentes uniquement dans la colonne EXPLICATIONS (texte
# libre), que le tokeniseur ne peut pas extraire de façon fiable.
_EXTRA_INDISPO_TOKENS: dict[str, list[dict]] = {
    # "du mardi 19 octobre 2026 au vendredi 22 octobre 2026" : le 19/10/2026
    # est un LUNDI et le 22 un JEUDI — noms de jours et dates se contredisent.
    # Arbitrage utilisateur : bloquer toute la semaine (19 -> 23 octobre).
    "RHU": [{
        "raw": "du lundi 19 octobre 2026 au vendredi 23 octobre 2026",
        "type": "date_specifique",
        "source": "EXPLICATIONS (conférence Marseille) + arbitrage utilisateur 10/08/2026",
    }],
}

# Disponibilités affinées par la colonne EXPLICATIONS : quand celle-ci donne
# une plage horaire précise, elle l'emporte sur le "toute la journée" de la
# colonne DISPONIBILITÉS (strictement plus informative, non contradictoire).
_REFINED_DISPO_TOKENS: dict[str, list[dict]] = {
    "KNG": [
        {"raw": "lundi de 9h30 à 18h30", "type": "recurrent_hebdomadaire",
         "jour": "lundi", "moment": "plage_horaire_precisee_dans_raw"},
        {"raw": "mardi de 8h00 à 18h30", "type": "recurrent_hebdomadaire",
         "jour": "mardi", "moment": "toute_la_journee"},
        {"raw": "mercredi de 8h00 à 18h30", "type": "recurrent_hebdomadaire",
         "jour": "mercredi", "moment": "toute_la_journee"},
        {"raw": "jeudi à partir de 14h00", "type": "recurrent_hebdomadaire",
         "jour": "jeudi", "moment": "plage_horaire_precisee_dans_raw"},
    ],
}

# Contraintes structurées qui n'existent dans le CSV que sous forme de prose.
_PARITY_RULES: dict[str, list[dict]] = {
    # "Semaines paires : mercredi pas dispo, jeudi max 17h. Semaines impaires :
    # lundi, mardi, vendredi max 17h." Parité = numéro de semaine DÉPARTEMENT
    # (semaine 1 = ISO 35 2026), basculable via `parity_reference`.
    "TCA": [
        {"parite": "paire", "jour": "mercredi", "moment": "toute_la_journee"},
        {"parite": "paire", "jour": "jeudi", "moment": "apres_17h"},
        {"parite": "impaire", "jour": "lundi", "moment": "apres_17h"},
        {"parite": "impaire", "jour": "mardi", "moment": "apres_17h"},
        {"parite": "impaire", "jour": "vendredi", "moment": "apres_17h"},
    ],
}

# "Regrouper ses cours sur une ou deux semaines successives par mois" (ARA) /
# "condenser les interventions" (JHU, basée à Paris) -> objectif MOU.
_MONTHLY_CLUSTERING: dict[str, int] = {"ARA": 2, "JHU": 2}


def _split_fragments(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"\s+-\s+|\n", text.replace("\r", ""))
    return [p.strip(" -\t") for p in parts if p.strip(" -\t")]


def _moment_for(fragment: str) -> str | None:
    low = (fragment.lower()
           .replace("é", "e").replace("è", "e").replace("ê", "e"))
    if re.search(r"\d\s*h", low):
        return "plage_horaire_precisee_dans_raw"
    if "toute la journee" in low or "journee" in low:
        return "toute_la_journee"
    if "apres-midi" in low or "apres midi" in low:
        return "apres_midi"
    if "matin" in low:
        return "matin"
    return None


def _tokenize(text: str) -> list[dict]:
    tokens: list[dict] = []
    for fragment in _split_fragments(text):
        low = fragment.lower()

        # Plage "du X au Y" ou date isolée
        if re.search(r"\bdu\b.+\bau\b", low) or re.search(r"semaine du", low):
            tokens.append({"raw": fragment, "type": "date_specifique"})
            continue
        d, _ = parse_fr_date(fragment)
        if d is not None:
            tokens.append({"raw": fragment, "type": "date_specifique"})
            continue

        jour = next((name for name in DAY_FR if name in low), None)
        if jour is not None:
            moment = _moment_for(fragment) or "toute_la_journee"
            tokens.append({"raw": fragment, "type": "recurrent_hebdomadaire",
                           "jour": jour, "moment": moment})
            continue

        tokens.append({"raw": fragment, "type": "autre_a_interpreter"})
    return tokens


def build_enseignants(maquette: list[dict]) -> list[dict]:
    path = find_source("CONTRAINTES ENSEIGNANTS")
    noms_par_code: dict[str, str] = {}
    for module in maquette:
        for prof in module.get("profs") or []:
            code = str(prof.get("code") or "").strip()
            if code and code not in noms_par_code:
                prenom = str(prof.get("prenom") or "").strip().title()
                nom = str(prof.get("nom") or "").strip().title()
                noms_par_code[code] = f"{prenom} {nom}".strip()

    entries: list[dict] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("DIMINUTIF") or "").strip()
            if not code:
                continue
            nom_complet = (row.get("ENSEIGNANT") or "").strip() or noms_par_code.get(code)

            indispo_raw = (row.get("INDISPONIBILITÉS") or "").strip() or None
            dispo_raw = (row.get("DISPONIBILITÉS") or "").strip() or None
            indispo_tokens = _tokenize(indispo_raw or "")
            indispo_tokens.extend(_EXTRA_INDISPO_TOKENS.get(code, []))
            dispo_tokens = _REFINED_DISPO_TOKENS.get(code) or _tokenize(dispo_raw or "")

            entry = {
                "nom_complet": nom_complet,
                "trigramme": code,
                "contraintes_pedagogiques_raw": (row.get("CONTRAINTES") or "").strip() or None,
                "indisponibilites_raw": indispo_raw,
                "indisponibilites_tokens": indispo_tokens,
                "disponibilites_raw": dispo_raw,
                "disponibilites_tokens": dispo_tokens,
                # Liste blanche dure : hors de ces créneaux/dates, l'enseignant
                # n'est pas plaçable du tout (arbitrage utilisateur 10/08/2026).
                "disponibilites_exclusives": code in _DISPOS_EXCLUSIVES,
                "explications_raw": (row.get("EXPLICATIONS") or "").strip() or None,
            }
            if code in _PARITY_RULES:
                entry["regles_parite_semaine"] = _PARITY_RULES[code]
                entry["parity_reference"] = "departement"
            if code in _MONTHLY_CLUSTERING:
                entry["regroupement_mensuel_max_semaines"] = _MONTHLY_CLUSTERING[code]
            entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# 07 — modules (maquette x progression)
# ---------------------------------------------------------------------------

_MODE_SOLO = "solo"
_MODE_SYM = "symetrique_ou_tournant (volumes identiques, verifier si rotation ou blocs fixes)"
_MODE_TOUR = "tournant_ou_mixte (blocks differents, a verifier)"
_MODE_INEG = "repartition_inegale (a verifier manuellement)"


def _mode_repartition(profs: list[dict]) -> str | None:
    if len(profs) <= 1:
        return _MODE_SOLO
    volumes = {(p.get("cm"), p.get("td"), p.get("tp")) for p in profs}
    if len(volumes) == 1:
        return _MODE_SYM
    if len({p.get("block") for p in profs}) > 1:
        return _MODE_TOUR
    return _MODE_INEG


def build_modules(maquette: list[dict], progression: list[dict]) -> list[dict]:
    prog_by_code = {p["code_matiere"]: p for p in progression}
    modules: list[dict] = []
    for module in maquette:
        code = module["code_matiere"]
        prog = prog_by_code.get(code, {})
        is_admin = module.get("parcours") == "admin"
        total = module.get("total") or {}
        modules.append({
            "code_matiere": code,
            "nom_matiere": module.get("nom_matiere"),
            "semestre": module.get("semestre"),
            "parcours": module.get("parcours"),
            "is_admin_non_enseignement": is_admin,
            "lead": module.get("lead"),
            "volumes_etudiant_seances": {k: total.get(k, 0) for k in ("cm", "td", "tp")},
            "profs": module.get("profs") or [],
            "mode_repartition_suggere": None if is_admin else _mode_repartition(module.get("profs") or []),
            "groupes_total_module": (module.get("maquette") or {}).get("groupes"),
            "codelement_celcat": (module.get("maquette") or {}).get("codelement"),
            "bloque": (module.get("maquette") or {}).get("bloque", False),
            "hors_service": (module.get("maquette") or {}).get("hors_service", False),
            "progression": prog.get("progression", {"definie": False, "nb_seances": 0, "seances": []}),
            "ordonnancement_relatif": prog.get("ordonnancement", []),
            "commentaire_edt": prog.get("commentaire_edt"),
        })
    return modules


# ---------------------------------------------------------------------------
# 09 — dates SAE
# ---------------------------------------------------------------------------

# WS502D : le CSV donne "12/1/2027 (AB) & 19/01/2027 (CD)". Arbitrage
# utilisateur (10/08/2026) : ce découpage AB/CD vient d'une année antérieure ;
# BUT3-DEV-FI n'a plus qu'un groupe TD (AB), donc seule la PREMIÈRE date de
# chaque paire est retenue, pour le TD AB.
_SAE_MANUAL_WINDOWS: dict[str, dict] = {
    "WS502D": {
        "fenetres": [{"debut": "2027-01-12", "fin": "2027-01-13"}],
        "groupes_td": ["AB"],
        "note": (
            "Source : '12/1/2027 (AB) & 19/01/2027 (CD)' / '13/1/2027 (AB) & "
            "20/01/2027 (CD)'. Arbitrage utilisateur 10/08/2026 : le groupe CD "
            "n'existe plus en BUT3-DEV-FI (1 seul TD), seules les dates du "
            "groupe AB (12 et 13 janvier 2027) sont retenues."
        ),
    },
}


def _parse_volumes(text: str) -> dict[str, int]:
    out = {"cm": 0, "td": 0, "tp": 0}
    for key, value in re.findall(r"(CM|TD|TP)\s*:\s*(\d+)", text or "", re.IGNORECASE):
        out[key.lower()] = int(value)
    return out


def _parse_teachers(text: str) -> list[str]:
    """"AFR : FROLI ANTHONYAHA : HARAOUBIA AMINE" -> ["AFR", "AHA"] (les
    trigrammes sont concaténés sans séparateur dans l'export)."""
    if not text or text.strip().lower() in {"aucun", ""}:
        return []
    return re.findall(r"\b([A-Z]{3})\s*:", text)


def build_dates_sae() -> dict:
    path = find_source("DATES SAE")
    rows = list(csv.reader(path.open(encoding="utf-8", newline="")))
    entries: list[dict] = []

    for row in rows[1:]:
        code = (row[0] or "").strip()
        if not code:
            continue
        manual = _SAE_MANUAL_WINDOWS.get(code)
        fenetres: list[dict] = []
        indetermine = False

        if manual:
            for window in manual["fenetres"]:
                debut = date.fromisoformat(window["debut"])
                fin = date.fromisoformat(window["fin"])
                fenetres.append({
                    "debut": debut.isoformat(), "fin": fin.isoformat(),
                    "dates": [d.isoformat() for d in daterange(debut, fin) if d.weekday() < 5],
                })
        else:
            cells = [c.strip() for c in row[7:]]
            pairs = [(cells[i], cells[i + 1] if i + 1 < len(cells) else "")
                     for i in range(0, len(cells), 2)]
            for start_raw, end_raw in pairs:
                if not start_raw and not end_raw:
                    continue
                if "?" in start_raw or "?" in end_raw:
                    indetermine = True
                    continue
                debut, _ = parse_fr_date(start_raw)
                fin, _ = parse_fr_date(end_raw) if end_raw else (debut, None)
                if debut is None:
                    indetermine = True
                    continue
                if fin is None or fin < debut:
                    fin = debut
                fenetres.append({
                    "debut": debut.isoformat(), "fin": fin.isoformat(),
                    "dates": [d.isoformat() for d in daterange(debut, fin) if d.weekday() < 5],
                })

        entry = {
            "code_matiere": code,
            "nom_matiere": (row[1] or "").strip(),
            "semestre": (row[2] or "").strip(),
            "parcours_source": (row[3] or "").strip(),
            "volumes_etudiant_seances": _parse_volumes(row[4] if len(row) > 4 else ""),
            "lead": (_parse_teachers(row[5]) or [None])[0] if len(row) > 5 else None,
            "autres_enseignants": _parse_teachers(row[6]) if len(row) > 6 else [],
            "fenetres": fenetres,
            "groupes_td": manual["groupes_td"] if manual else None,
            "dates_indeterminees": indetermine,
        }
        if manual:
            entry["note"] = manual["note"]
        entries.append(entry)

    return {
        "source": path.name,
        "genere_par": "scripts/build_contraintes.py",
        "regle_lecture": (
            "Chaque fenetre = des journees ENTIERES consacrees a la SAE pour le "
            "parcours du module. Regle de sanctuarisation (01_regles_generales) : "
            "aucune ressource classique (WR/WRA) ce jour-la pour ce parcours. "
            "`groupes_td` non nul restreint la sanctuarisation a ces groupes TD "
            "seulement ; `dates_indeterminees` signale une SAE dont les dates "
            "restent a fournir (aucune sanctuarisation possible)."
        ),
        "sae": entries,
    }


# ---------------------------------------------------------------------------
# 10 — dates fixes (rentrées, événements horodatés)
# ---------------------------------------------------------------------------

_SEMESTRE_TO_BUT = {"S1": "BUT1", "S2": "BUT1", "S3": "BUT2", "S4": "BUT2", "S5": "BUT3", "S6": "BUT3"}


def _parcours_from_but_column(value: str) -> list[str]:
    """"S5-DEV-FC" -> ["BUT3-DEV-FC"] ; "S1" -> ["BUT1"] ; "ADMIN" -> []."""
    value = (value or "").strip().upper()
    if not value or value == "ADMIN":
        return []
    m = re.match(r"^(S[1-6])(?:-(.+))?$", value)
    if not m:
        return []
    but = _SEMESTRE_TO_BUT.get(m.group(1))
    if but is None:
        return []
    return [f"{but}-{m.group(2)}" if m.group(2) else but]


def _hhmm(text: str) -> int | None:
    m = re.match(r"^\s*(\d{1,2})\s*[h:]\s*(\d{0,2})", text or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)


def build_dates_fixes() -> dict:
    path = find_source("Dates MMI")
    events: list[dict] = []
    a_fixer: list[dict] = []

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            raw_date = (row.get("DATE") or "").strip()
            motif = (row.get("Motif") or "").strip()
            if not raw_date or not motif:
                continue

            m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", raw_date)
            if not m:
                a_fixer.append({
                    "date_brute": raw_date, "motif": motif,
                    "parcours": _parcours_from_but_column(row.get("BUT") or ""),
                    "statut": (row.get("OK RDE") or "").strip(),
                })
                continue

            events.append({
                "date": date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(),
                "debut": (row.get("HEURE DE DÉBUT") or "").strip() or None,
                "fin": (row.get("HEURE DE FIN") or "").strip() or None,
                "debut_minutes": _hhmm(row.get("HEURE DE DÉBUT") or ""),
                "fin_minutes": _hhmm(row.get("HEURE DE FIN") or ""),
                "salle": (row.get("SALLE") or "").strip() or None,
                "parcours": _parcours_from_but_column(row.get("BUT") or ""),
                "parcours_source": (row.get("BUT") or "").strip(),
                "motif": motif,
            })

    events.sort(key=lambda e: (e["date"], e["debut_minutes"] or 0))
    return {
        "source": path.name,
        "genere_par": "scripts/build_contraintes.py",
        "regle_lecture": (
            "Evenement obligatoire a une date/heure fixe. Les creneaux couverts "
            "sont bloques pour les cours classiques des SEULS parcours listes "
            "dans `parcours` (liste vide = information seulement, aucun blocage)."
        ),
        "evenements": events,
        "a_fixer": a_fixer,
    }


# ---------------------------------------------------------------------------
# 08 — alertes qualité
# ---------------------------------------------------------------------------


def build_alertes(maquette: list[dict], alternance: dict, dates_sae: dict,
                  dates_fixes: dict, enseignants: list[dict]) -> dict:
    incoherences: list[str] = []
    for module in maquette:
        code = module["code_matiere"]
        groupes = (module.get("maquette") or {}).get("groupes") or {}
        profs = module.get("profs") or []
        for champ, cle in (("nbGpTd", "td"), ("nbGpTp", "tp")):
            somme = sum(int(p.get(champ) or 0) for p in profs)
            declare = groupes.get(cle)
            if declare is not None and somme and somme != declare:
                incoherences.append(
                    f"{code}: somme {champ} des profs ({somme}) != groupes.{cle} declare ({declare})"
                )

    volumes_sans_prof: list[str] = []
    for module in maquette:
        total = module.get("total") or {}
        profs = module.get("profs") or []
        for kind in ("cm", "td", "tp"):
            if (total.get(kind) or 0) > 0 and not sum(int(p.get(kind) or 0) for p in profs):
                volumes_sans_prof.append(
                    f"{module['code_matiere']}: {int(total[kind])} {kind.upper()} declares par etudiant "
                    f"mais 0 {kind.upper()} reparti sur les enseignants"
                )

    sae_sans_dates = [
        s["code_matiere"] for s in dates_sae["sae"]
        if not s["fenetres"] and (s["volumes_etudiant_seances"]["cm"]
                                  or s["volumes_etudiant_seances"]["td"]
                                  or s["volumes_etudiant_seances"]["tp"])
    ]
    sae_indeterminees = [s["code_matiere"] for s in dates_sae["sae"] if s["dates_indeterminees"]]

    codes_maquette = {
        str(p.get("code")).strip()
        for module in maquette for p in (module.get("profs") or []) if p.get("code")
    }
    codes_contraintes = {e["trigramme"] for e in enseignants}

    return {
        "meta": (
            "Points a verifier manuellement / conflits detectes automatiquement "
            "dans les donnees sources. Ne pas 'corriger' sans validation humaine "
            "(regle de la donnee fraiche). Genere par scripts/build_contraintes.py."
        ),
        "conflits_calendrier_alternance_vs_fermeture_iut":
            {k: v for k, v in alternance["conflits_detectes_automatiquement"].items() if k != "regle"},
        "incoherences_nbGroupes_maquette": {
            "regle_verifiee": (
                "somme des nbGpTd/nbGpTp declares par les enseignants d'un module "
                "vs nombre total de groupes declare dans maquette.groupes"
            ),
            "note": (
                "Frequent sur les SAE/PTUT/modules a volumes cumules : le champ "
                "nbGp peut compter autre chose que des groupes concurrents. A "
                "verifier au cas par cas, ne pas corriger automatiquement."
            ),
            "liste": incoherences,
        },
        "volumes_declares_sans_enseignant": {
            "note": (
                "Volume annonce par etudiant mais aucun enseignant n'en porte le "
                "volume : la seance ne sera jamais generee."
            ),
            "liste": volumes_sans_prof,
        },
        "sae_sans_dates": {
            "note": (
                "SAE avec volume mais sans date dans le fichier DATES SAE : aucune "
                "sanctuarisation possible, les cours classiques restent placables "
                "librement pour ce parcours."
            ),
            "liste": sorted(sae_sans_dates),
            "dates_explicitement_indeterminees": sorted(sae_indeterminees),
        },
        "dates_a_fixer": dates_fixes["a_fixer"],
        "points_ouverts_hors_fichiers_sources": [
            (
                f"{len(codes_contraintes)} enseignants ont une ligne de contraintes ; "
                f"{len(codes_maquette)} apparaissent dans la maquette. Les "
                f"{len(codes_maquette - codes_contraintes)} sans ligne sont presumes "
                "sans contrainte connue, a confirmer plutot que suppose : "
                + ", ".join(sorted(codes_maquette - codes_contraintes))
            ),
            (
                "Aucun fichier source ne couvre les salles : la section 'rooms' de "
                "01_regles_generales.json et data/config/rooms.yaml viennent de la "
                "conversation preparatoire, pas d'un fichier officiel."
            ),
            (
                "S2/S4/S6 sont hors perimetre pour 2026-2027 (arbitrage utilisateur "
                "10/08/2026) : le fichier DATES SAE ne date que les SAE de S1/S3/S5."
            ),
            (
                "BUT2-DEV-FC (S3/S4-DEV-FC) est gele cette annee (effectif alternants "
                "insuffisant, cf. 'Maquette 2026 BUT2 S3-DEV-FC.docx') : aucun module "
                "dans la maquette, le solveur l'ignore naturellement."
            ),
        ],
    }


# ---------------------------------------------------------------------------

_ARBITRAGES = """
Arbitrages utilisateur du 10/08/2026 câblés dans ce script :
1. DATES SAE fait foi ; pas de repli sur l'ancien 04_planning (supprimé).
   S2/S4/S6 hors périmètre (aucune date fournie pour leurs SAE).
2. WS502D : seules les dates du groupe AB (12-13 janvier 2027) sont retenues,
   le groupe CD n'existant plus en BUT3-DEV-FI.
3. Événements fixes = "Dates MMI" uniquement. Les repères de l'ancien planning
   (Intégration, Clés de Troyes, Conseil, Rattrapages, Stages...) disparaissent.
   S1 ne démarre pas avant le lundi de la semaine 3 (7 septembre 2026).
4. Parité TCA = numéro de semaine département (basculable en ISO).
5. Disponibilités = liste blanche dure (MNI, VBU, KNG, EHU).
6. RHU indisponible du lundi 19 au vendredi 23 octobre 2026 (semaine entière).
7. ARA (et JHU) : regroupement mensuel en objectif mou fortement pondéré.
8. WS501D : plan enseignant d'ALO ignoré, seules les dates du CSV comptent.
9. WRA505C : ALO avant AFR en objectif mou.
10. WRA308M : bloc de 4h30 sur les 3 derniers TD uniquement.
11. WR100BU : fenêtres de dates dures par séance.
"""


def main() -> int:
    if not SRC.is_dir():
        raise SystemExit(f"{SRC} introuvable")
    OUT.mkdir(exist_ok=True)

    maquette = json.loads((SRC / "maquette.json").read_text(encoding="utf-8"))
    progression = json.loads((SRC / "progression.json").read_text(encoding="utf-8"))

    calendrier = build_calendrier_iut()
    alternance = build_alternance(calendrier)
    enseignants = build_enseignants(maquette)
    modules = build_modules(maquette, progression)
    dates_sae = build_dates_sae()
    dates_fixes = build_dates_fixes()
    alertes = build_alertes(maquette, alternance, dates_sae, dates_fixes, enseignants)

    written = {
        "02_calendrier_iut.json": calendrier,
        "03_calendrier_alternance_officiel.json": alternance,
        "05_enseignants_contraintes.json": enseignants,
        "07_modules_maquette_progression.json": modules,
        "08_alertes_qualite_donnees.json": alertes,
        "09_dates_sae.json": dates_sae,
        "10_dates_fixes.json": dates_fixes,
    }
    for name, payload in written.items():
        (OUT / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"écrit  contraintes/{name}")

    # Exports bruts copiés à côté : `ingestion/fetch.py` les préfère au
    # téléchargement distant, ce qui fige la source pour un run reproductible.
    for name in ("maquette.json", "progression.json"):
        shutil.copyfile(SRC / name, OUT / name)
        print(f"copié  contraintes/{name}")

    obsolete = OUT / "04_planning_hebdomadaire_par_promo.json"
    if obsolete.exists():
        obsolete.unlink()
        print("supprimé  contraintes/04_planning_hebdomadaire_par_promo.json (remplacé par 09 + 10)")

    print(f"\n{len(enseignants)} enseignants, {len(modules)} modules, "
          f"{len(dates_sae['sae'])} SAE, {len(dates_fixes['evenements'])} événements fixes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
