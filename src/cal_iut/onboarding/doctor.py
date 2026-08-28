"""« Est-ce que tout est en place ? » — et si non, quoi faire, en une phrase.

Destiné à quelqu'un qui vient d'ouvrir le dossier et ne sait pas par où
commencer. Chaque contrôle répond à trois questions dans cet ordre : qu'est-ce
qui est vérifié, est-ce bon, et — si ce n'est pas bon — quelle commande taper.

C'est délibérément séparé de `cal-iut audit` : le docteur regarde l'INSTALLATION
(fichiers présents, environnement, étapes déjà faites), l'audit regarde le
CONTENU (données cohérentes, règles appliquées). On ne peut pas auditer ce qui
n'est pas encore installé.
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Check:
    libelle: str
    ok: bool
    detail: str = ""
    action: str = ""  # commande à taper si ce n'est pas bon
    bloquant: bool = True


def _fmt_age(path: Path) -> str:
    delta = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    if delta.days >= 1:
        return f"il y a {delta.days} jour(s)"
    heures = delta.seconds // 3600
    return f"il y a {heures} h" if heures else "il y a moins d'une heure"


def run_doctor(project_root: Path) -> tuple[list[Check], list[str]]:
    """Retourne `(contrôles, prochaines étapes)`."""
    checks: list[Check] = []
    src = project_root / "contraintes_update"
    gen = project_root / "contraintes"
    out = project_root / "data" / "generated"
    config = project_root / "data" / "config"

    checks.append(Check(
        "Version de Python",
        sys.version_info >= (3, 13),
        detail=f"{sys.version_info.major}.{sys.version_info.minor}",
        action="Installer Python 3.13 puis recréer l'environnement : py -3.13 -m venv .venv",
    ))

    try:
        import ortools  # noqa: F401

        ortools_ok, ortools_detail = True, "installé"
    except ImportError:
        ortools_ok, ortools_detail = False, "absent"
    checks.append(Check(
        "Solveur OR-Tools", ortools_ok, detail=ortools_detail,
        action='Activer l\'environnement puis : pip install -e ".[dev]"',
    ))

    # --- Fichiers sources officiels ---
    attendus = {
        "maquette.json": "export officiel des modules et volumes",
        "progression.json": "ordre des séances de chaque module",
        "CONTRAINTES ENSEIGNANTS": "disponibilités des enseignants (CSV)",
        "INDISPONIBILIT": "calendrier IUT : vacances et fériés (CSV)",
        "DATES SAE": "dates des SAE (CSV)",
        "Dates MMI": "événements fixes : rentrées, interventions (CSV)",
        "DISPONIBILITÉS ÉTUDIANTS BUT2": "semaines IUT des alternants BUT2 (CSV)",
        "DISPONIBILITÉS ÉTUDIANTS BUT3": "semaines IUT des alternants BUT3 (CSV)",
    }
    # Comparaison SANS accents ni casse : sous Windows, un nom de fichier
    # contenant « É » peut être stocké en forme décomposée (E + accent
    # combinant) et ne correspond alors pas au littéral écrit ici. Le docteur
    # annonçait « fichier manquant » sur des fichiers bien présents.
    def _plat(texte: str) -> str:
        sans_accent = unicodedata.normalize("NFKD", texte)
        return "".join(c for c in sans_accent if not unicodedata.combining(c)).lower()

    presents = [_plat(p.name) for p in src.iterdir()] if src.is_dir() else []
    manquants = [
        f"{frag} ({desc})"
        for frag, desc in attendus.items()
        if not any(_plat(frag) in n for n in presents)
    ]
    checks.append(Check(
        "Fichiers sources officiels",
        not manquants,
        detail=f"{len(attendus) - len(manquants)}/{len(attendus)} présents dans contraintes_update/",
        action=(
            "Déposer les fichiers manquants dans contraintes_update/ : "
            + " ; ".join(manquants)
            if manquants
            else ""
        ),
    ))

    # --- Contraintes générées ---
    generes = sorted(gen.glob("*.json")) if gen.is_dir() else []
    numerotes = [p for p in generes if p.name[0].isdigit()]
    checks.append(Check(
        "Contraintes générées",
        len(numerotes) >= 6,
        detail=(f"{len(numerotes)} fichiers, dernier généré {_fmt_age(max(numerotes, key=lambda p: p.stat().st_mtime))}"
                if numerotes else "aucun"),
        action="python scripts/build_contraintes.py",
    ))

    if numerotes and src.is_dir():
        plus_recent = max(p.stat().st_mtime for p in numerotes)
        # Une date plus récente ne prouve pas un contenu différent : un export
        # retéléchargé à l'identique, ou un fichier simplement rouvert, suffit
        # à la faire avancer. Pour les deux exports recopiés tels quels dans
        # `contraintes/`, on tranche sur le CONTENU — le seul critère qui dise
        # vraiment s'il faut regénérer (cf. docs/DATA.md §66.7).
        en_retard = []
        for p in sorted(src.iterdir()):
            if not p.is_file() or p.stat().st_mtime <= plus_recent:
                continue
            copie = gen / p.name
            if copie.exists() and copie.read_bytes() == p.read_bytes():
                continue
            en_retard.append(p.name)
        checks.append(Check(
            "Contraintes à jour avec les sources",
            not en_retard,
            detail=(f"{len(en_retard)} source(s) modifiée(s) depuis : {', '.join(sorted(en_retard)[:3])}"
                    if en_retard else "à jour"),
            action="python scripts/build_contraintes.py",
        ))

    # --- Séances ingérées ---
    sessions = out / "sessions.json"
    checks.append(Check(
        "Séances préparées",
        sessions.exists(),
        detail=_fmt_age(sessions) if sessions.exists() else "aucune",
        action="cal-iut ingest --semestre-group odd",
    ))
    if sessions.exists() and numerotes:
        a_jour = sessions.stat().st_mtime >= max(p.stat().st_mtime for p in numerotes)
        checks.append(Check(
            "Séances à jour avec les contraintes",
            a_jour,
            detail="à jour" if a_jour else "les contraintes ont changé depuis la préparation",
            action="cal-iut ingest --semestre-group odd",
        ))

    # --- Configuration métier ---
    yamls = sorted(config.glob("*.yaml")) if config.is_dir() else []
    checks.append(Check(
        "Configuration métier",
        len(yamls) >= 5,
        detail=f"{len(yamls)} fichier(s) dans data/config/",
        action="Le dossier data/config/ doit contenir groups.yaml, rooms.yaml, etc. — dépôt incomplet ?",
    ))

    # --- Emploi du temps produit ---
    candidats = [p for p in (out / "timetable.json", out / "timetable_best.json") if p.exists()]
    checks.append(Check(
        "Emploi du temps produit",
        bool(candidats),
        detail=(", ".join(f"{p.name} ({_fmt_age(p)})" for p in candidats) if candidats else "aucun"),
        action="cal-iut solve --decomposed --semestre-group odd --weeks 24 --fi-max-week 18",
        bloquant=False,
    ))

    # --- Interface web (facultative) ---
    dist = project_root / "frontend" / "dist" / "index.html"
    checks.append(Check(
        "Interface web compilée",
        dist.exists(),
        detail="prête" if dist.exists() else "non compilée",
        action="cd frontend && npm install && npm run build",
        bloquant=False,
    ))

    # --- Prochaine étape : le premier contrôle bloquant en échec ---
    etapes: list[str] = []
    premier_ko = next((c for c in checks if not c.ok and c.bloquant), None)
    if premier_ko is not None:
        etapes.append(f"À FAIRE MAINTENANT : {premier_ko.action}")
        etapes.append(f"  (pour corriger : {premier_ko.libelle.lower()})")
    else:
        etapes.append("Tout est en place. Enchaînement habituel :")
        etapes.append("  1. cal-iut audit                     -> vérifier les données")
        etapes.append("  2. cal-iut annee                     -> tout dérouler jusqu'à l'EDT")
        etapes.append("  3. cal-iut serve                     -> ouvrir l'interface web")
        facultatifs = [c for c in checks if not c.ok and not c.bloquant]
        for c in facultatifs:
            etapes.append(f"  (facultatif) {c.libelle} : {c.action}")
    return checks, etapes
