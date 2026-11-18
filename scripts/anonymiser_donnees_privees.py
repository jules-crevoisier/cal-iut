"""Fabrique les versions ANONYMISÉES des fichiers de contraintes enseignants.

Les vrais fichiers (e-mails, texte libre des contraintes, commentaires,
noms) ne sont plus dans le dépôt : ils vivent dans le volume de production,
sous `data/state/prive/` (voir docs/DONNEES-PRIVEES.md). Le dépôt ne garde que
des copies sans donnée personnelle, de même structure, pour que les tests et
la CI tournent.

Usage :  python scripts/anonymiser_donnees_privees.py <dossier_prive> [<racine_depot>]

`<dossier_prive>` reprend les chemins relatifs du dépôt (data/config/...,
contraintes/..., contraintes_update/...). Ce que fait le script :
  * e-mails -> `<code>@example.invalid` ;
  * noms : remplacés par « Prenom <trigramme> » ;
  * commentaires YAML et champs `notes` : supprimés ;
  * noms et prénoms d'enseignants : remplacés par le trigramme ;
  * champs de texte libre (contraintes, explications, commentaires) : vidés.
Les trigrammes et les créneaux (jours, dates) sont conservés : les tests
s'appuient dessus.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

YAML_FICHIERS = [
    "data/config/teacher_contacts.yaml",
    "data/config/teacher_availability.yaml",
    "data/config/teacher_duos.yaml",
    "data/config/sae_teacher_phases.yaml",
    "data/config/enseignants_supplementaires.yaml",
]
CSV_ENSEIGNANTS = "contraintes_update/CONTRAINTES ENSEIGNANTS MMI 2026_2027 - Feuille 1(1).csv"
JSON_FICHIERS = [
    "contraintes/05_enseignants_contraintes.json",
    "contraintes/maquette.json",
    "contraintes/progression.json",
    "contraintes_update/maquette.json",
    "contraintes_update/progression.json",
]
JSON_PUBLIC_A_NETTOYER = ["contraintes/07_modules_maquette_progression.json"]

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CHAMPS_LIBRES = {
    "contraintes_pedagogiques_raw", "explications_raw", "commentaire_edt",
    "commentaires", "notes", "demande_par",
}


def _sans_commentaire_yaml(ligne: str) -> str:
    """Retire un commentaire `# ...` hors guillemets ; ligne vide si tout est commentaire."""
    if ligne.lstrip().startswith("#"):
        return ""
    guillemet = None
    for i, c in enumerate(ligne):
        if guillemet:
            if c == guillemet and ligne[i - 1] != "\\":
                guillemet = None
        elif c in "\"'":
            guillemet = c
        elif c == "#" and i > 0 and ligne[i - 1] in " \t":
            return ligne[:i].rstrip()
    return ligne


def anonymiser_yaml(texte: str, noms: dict[str, str]) -> str:
    lignes = []
    cle = None
    ligne_code = None
    for brut in texte.splitlines():
        mc = re.match(r"^([A-Z]{2,4}):\s*$", brut)
        if mc:
            ligne_code = mc.group(1)
        ligne = _sans_commentaire_yaml(brut)
        if not ligne.strip():
            if brut.strip() == "" and lignes and lignes[-1] != "":
                lignes.append("")
            continue
        m = re.match(r"^(\s*)(?:-\s+)?([\w]+):", ligne)
        if m:
            cle = m.group(2)
            if cle in ("notes", "demande_par"):
                ligne = re.sub(r":\s*.*$", ': ""', ligne)
        if re.match(r"^\s*(?:-\s+)?nom:", ligne) and ligne_code:
            ligne = re.sub(r":\s*.*$", f': "{pseudonyme(ligne_code)}"', ligne)
        lignes.append(ligne)
    sortie = "\n".join(lignes).strip() + "\n"
    # e-mail -> code@example.invalid (le code est la clé YAML de la ligne)
    def remplacer_ligne(ligne: str) -> str:
        m = re.match(r"^(\s*)([A-Za-z0-9_]+):\s*[\"']?(.+?)[\"']?\s*$", ligne)
        if m and EMAIL.fullmatch(m.group(3)):
            return f"{m.group(1)}{m.group(2)}: {m.group(2).lower()}@example.invalid"
        return EMAIL.sub("enseignant@example.invalid", ligne)
    sortie = "\n".join(remplacer_ligne(l) for l in sortie.splitlines()) + "\n"
    return remplacer_noms(sortie, noms)


def pseudonyme(code: str) -> str:
    """Nom fictif stable : « Prenom CODE » (prénom = Prenom, nom = trigramme)."""
    return f"Prenom {code}"


def remplacer_noms(texte: str, noms: dict[str, str]) -> str:
    for nom, code in sorted(noms.items(), key=lambda kv: -len(kv[0])):
        texte = re.sub(re.escape(nom), pseudonyme(code), texte, flags=re.IGNORECASE)
    return texte


def _noms_depuis_json(racine_privee: Path) -> dict[str, str]:
    """Nom complet -> trigramme (tous les ordres et casses utiles)."""
    noms: dict[str, str] = {}
    chemin = racine_privee / "contraintes/05_enseignants_contraintes.json"
    for t in json.loads(chemin.read_text(encoding="utf-8")):
        if t.get("nom_complet") and t.get("trigramme"):
            noms[t["nom_complet"]] = t["trigramme"]

    def parcourir(o):
        if isinstance(o, dict):
            if {"code", "nom", "prenom"} <= o.keys() and o["code"]:
                noms.setdefault(f'{o["prenom"]} {o["nom"]}', o["code"])
                noms.setdefault(f'{o["nom"]} {o["prenom"]}', o["code"])
            for v in o.values():
                parcourir(v)
        elif isinstance(o, list):
            for v in o:
                parcourir(v)
    for f in ("contraintes/maquette.json", "contraintes/progression.json"):
        p = racine_privee / f
        if p.exists():
            parcourir(json.loads(p.read_text(encoding="utf-8")))
    return noms


def anonymiser_json(objet, noms: dict[str, str]):
    if isinstance(objet, dict):
        sortie = {}
        for k, v in objet.items():
            if k in CHAMPS_LIBRES:
                sortie[k] = [] if isinstance(v, list) else None
            elif k == "nom" and "code" in objet and objet.get("code"):
                sortie[k] = objet["code"]
            elif k == "prenom" and "code" in objet and objet.get("code"):
                sortie[k] = "PRENOM"
            elif k == "nom_complet" and objet.get("trigramme"):
                sortie[k] = pseudonyme(objet["trigramme"])
            else:
                sortie[k] = anonymiser_json(v, noms)
        return sortie
    if isinstance(objet, list):
        return [anonymiser_json(v, noms) for v in objet]
    if isinstance(objet, str):
        return EMAIL.sub("enseignant@example.invalid", remplacer_noms(objet, noms))
    return objet


def anonymiser_csv(texte: str, noms: dict[str, str]) -> str:
    lecteur = csv.DictReader(io.StringIO(texte))
    sortie = io.StringIO()
    ecrivain = csv.DictWriter(sortie, fieldnames=lecteur.fieldnames, lineterminator="\n")
    ecrivain.writeheader()
    for ligne in lecteur:
        code = (ligne.get("DIMINUTIF") or "").strip()
        ligne["ENSEIGNANT"] = pseudonyme(code)
        ligne["CONTRAINTES"] = ""
        ligne["EXPLICATIONS"] = ""
        ecrivain.writerow(ligne)
    return remplacer_noms(sortie.getvalue(), noms)


def main() -> None:
    privee = Path(sys.argv[1]).resolve()
    depot = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).resolve().parents[1]
    noms = _noms_depuis_json(privee)
    for rel in YAML_FICHIERS:
        (depot / rel).write_text(anonymiser_yaml((privee / rel).read_text(encoding="utf-8"), noms), encoding="utf-8")
    (depot / CSV_ENSEIGNANTS).write_text(
        anonymiser_csv((privee / CSV_ENSEIGNANTS).read_text(encoding="utf-8"), noms), encoding="utf-8")
    for rel in JSON_FICHIERS:
        donnees = json.loads((privee / rel).read_text(encoding="utf-8"))
        (depot / rel).write_text(
            json.dumps(anonymiser_json(donnees, noms), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for rel in JSON_PUBLIC_A_NETTOYER:
        source = privee / rel if (privee / rel).exists() else depot / rel
        donnees = json.loads(source.read_text(encoding="utf-8"))
        (depot / rel).write_text(
            json.dumps(anonymiser_json(donnees, noms), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
