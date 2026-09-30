"""Codes module Celcat PRÉENREGISTRÉS depuis la maquette (30/09/2026).

Demande utilisateur : « il faut récupérer les codes de la maquette et les
mettre ; les codes qu'on connaît doivent être préenregistrés dans l'appli ».
La maquette porte, pour chaque cours, son `codelement` (« TSBZ2M01 ») : c'est
le code module Celcat, lisible dans Celcat. Le 30/09/2026, 78 cours de la
maquette n'avaient aucun code dans `celcat.yaml` — dont les S2, S4 et S6,
jamais saisis à la main.

POURQUOI UN FICHIER GÉNÉRÉ ET VERSIONNÉ (`data/config/celcat_modules_
maquette.yaml`) PLUTÔT QU'UN CALCUL AU CHARGEMENT. La maquette n'est pas une
donnée locale sûre : sans cache `contraintes/maquette.json`, le serveur la
RÉCUPÈRE en direct au démarrage, et le worker Celcat (autre conteneur) la
charge de son côté. Un code calculé au chargement pouvait donc différer
entre l'API et le worker, ou changer au redémarrage sans que personne l'ait
décidé — pour une donnée qui sert aussi à la paie. Figé dans un fichier, il
est relu, comparé (diff de revue), identique pour tous, et `load_celcat_
config` le lit comme `celcat.yaml` : une seule logique de lecture.
On le régénère avec `scripts/generer_codes_maquette.py` quand la maquette
ou le relevé des matières change.

RÈGLES (rien n'est deviné) — pour chaque cours SANS code dans `celcat.yaml`
et non marqué « sans code (voulu) » :

1. le `codelement` de la maquette existe TEL QUEL dans le relevé des
   matières (`celcat_matieres.yaml`) -> il devient le code, origine
   « maquette » ;
2. sinon, correction M -> C : le code de la maquette finit par « M », le
   cours est du parcours CREACOM, et la même racine terminée par « C » est
   relevée -> la variante relevée, origine « maquette (corrigé M→C) ».
   Règle établie sur les données : les 21 cours dont `celcat.yaml` portait
   déjà un code ET dont la maquette donnait un code en M (WRA301M…WRA319M,
   WSA301M, WSA302M) ont TOUS, dans le fichier, la variante en C — trois
   confirmées par Kyllian le 04/09/2026 (WRA307M, WRA313M, WRA319M), la règle
   posée par lui : « on écrit sur la C, celle du groupe CREACOM ». La
   variante en D existe parfois aussi dans Celcat : c'est celle du parcours
   DEV, jamais retenue pour un cours CREACOM ;
3. sinon : manquant, et listé par le script.

Un code déjà porté par un autre cours n'est jamais repris (deux cours ne
partagent pas un module) : le cours reste manquant, et le script le dit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FICHIER = "celcat_modules_maquette.yaml"

ORIGINE_MAQUETTE = "maquette"
ORIGINE_CORRIGE = "maquette (corrigé M→C)"


@dataclass
class CodeMaquette:
    cours: str
    code: str
    origine: str
    code_maquette: str
    nom_celcat: str = ""


def lire(config_dir: Path) -> dict[str, dict[str, str]]:
    """`{code de cours: {"code", "origine", "maquette"}}` — vide si le
    fichier manque ou ne se lit pas (un code en moins se voit à l'écran,
    une exception casserait la synchronisation)."""
    chemin = Path(config_dir) / FICHIER
    if not chemin.exists():
        return {}
    try:
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    modules = data.get("modules") if isinstance(data, dict) else None
    sortie: dict[str, dict[str, str]] = {}
    for cle, valeur in (modules or {}).items():
        if isinstance(valeur, dict) and str(valeur.get("code") or "").strip():
            sortie[str(cle).strip().upper()] = {
                "code": str(valeur["code"]).strip().upper(),
                "origine": str(valeur.get("origine") or ORIGINE_MAQUETTE),
                "maquette": str(valeur.get("maquette") or valeur["code"]).strip().upper(),
            }
    return sortie


_LIGNE_RELEVE = re.compile(r'^\s*"?([A-Z0-9]+)"?\s*:\s*\d+\s*(?:#\s*(.*))?$')


def releve_des_matieres(config_dir: Path) -> dict[str, str]:
    """Code module relevé -> nom Celcat (le commentaire de la ligne)."""
    chemin = Path(config_dir) / "celcat_matieres.yaml"
    sortie: dict[str, str] = {}
    if not chemin.exists():
        return sortie
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        trouve = _LIGNE_RELEVE.match(ligne)
        if trouve:
            sortie[trouve.group(1).upper()] = (trouve.group(2) or "").strip()
    return sortie


def calculer(
    cours: list[Any],
    *,
    modules_fichier: dict[str, str],
    sans_code_voulu: set[str],
    releve: dict[str, str],
) -> tuple[list[CodeMaquette], list[tuple[str, str]]]:
    """Les codes à préenregistrer, et les cours laissés manquants (raison).

    `cours` : objets à `code`, `parcours`, `codelement` (les `Course` de la
    maquette). Déterministe : trié par code de cours."""
    pris = {str(v).strip().upper(): k for k, v in modules_fichier.items() if v}
    retenus: list[CodeMaquette] = []
    manquants: list[tuple[str, str]] = []
    vus: set[str] = set()
    for c in sorted(cours, key=lambda c: str(c.code).upper()):
        code_cours = str(c.code).strip().upper()
        if code_cours in vus:
            continue
        vus.add(code_cours)
        if code_cours in {k.upper() for k in modules_fichier} or code_cours in sans_code_voulu:
            continue
        brut = str(getattr(c, "codelement", "") or "").strip().upper()
        parcours = str(getattr(c, "parcours", "") or "").upper()
        if not brut:
            manquants.append((code_cours, "aucun code dans la maquette"))
            continue
        if brut in releve:
            code, origine = brut, ORIGINE_MAQUETTE
        elif brut.endswith("M") and "CREACOM" in parcours and f"{brut[:-1]}C" in releve:
            code, origine = f"{brut[:-1]}C", ORIGINE_CORRIGE
        else:
            manquants.append((code_cours, f"{brut} (maquette) absent du relevé des matières Celcat"))
            continue
        if code in pris:
            manquants.append((code_cours, f"{code} est déjà celui de {pris[code]}"))
            continue
        pris[code] = code_cours
        retenus.append(CodeMaquette(code_cours, code, origine, brut, releve.get(code, "")))
    return retenus, manquants


def a_verifier(retenus: list[CodeMaquette]) -> list[str]:
    """Les codes dont le nom Celcat ne nomme pas le cours (à la lettre
    finale près, pour les corrigés M→C) : repris de la maquette, mais à
    faire confirmer."""
    sortie = []
    for r in retenus:
        nom = r.nom_celcat.split(" ", 1)[0].upper() if r.nom_celcat else ""
        if nom and nom.rstrip("CDM") != r.cours.rstrip("CDM"):
            sortie.append(f"{r.cours} -> {r.code} : Celcat le nomme « {r.nom_celcat} »")
    return sortie


def ecrire(
    chemin: Path,
    retenus: list[CodeMaquette],
    manquants: list[tuple[str, str]],
    *,
    date: str,
    verifier: list[str] | None = None,
) -> None:
    """Le fichier versionné, lisible : une ligne par cours, le nom Celcat en
    commentaire pour vérifier d'un coup d'œil que le code désigne le bon cours."""
    lignes = [
        "# GÉNÉRÉ par scripts/generer_codes_maquette.py — ne pas éditer à la main.",
        f"# Généré le {date}. Règles : src/cal_iut/celcat/codes_maquette.py.",
        "#",
        "# Codes module Celcat PRÉENREGISTRÉS depuis la maquette (`codelement`) pour",
        "# les cours sans code dans celcat.yaml : lus par `load_celcat_config` APRÈS",
        "# celcat.yaml (qui a toujours le dernier mot) et sauf « sans code (voulu) ».",
        "# Un code corrigé garde le code de la maquette (`maquette`).",
        "",
        "modules:",
    ]
    for r in retenus:
        extra = f', maquette: "{r.code_maquette}"' if r.code_maquette != r.code else ""
        commentaire = f"  # Celcat : {r.nom_celcat}" if r.nom_celcat else ""
        lignes.append(f'  {r.cours}: {{code: "{r.code}", origine: "{r.origine}"{extra}}}{commentaire}')
    if verifier:
        lignes += ["", "# À faire confirmer (repris de la maquette, le nom Celcat diffère) :"]
        lignes += [f"#   {ligne}" for ligne in verifier]
    if manquants:
        lignes += ["", "# Laissés manquants (à relever ou à trancher) :"]
        lignes += [f"#   {cours} : {raison}" for cours, raison in manquants]
    Path(chemin).write_text("\n".join(lignes) + "\n", encoding="utf-8")
