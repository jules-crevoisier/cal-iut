"""Récupération des exports officiels et comparaison avec la version en place.

Les deux exports vivent à des adresses stables :

    https://mmi23x02.mmi-troyes.fr/export/maquette
    https://mmi23x02.mmi-troyes.fr/export/progression

Ce module les télécharge, DIT CE QUI CHANGE, puis écrit — dans cet ordre, parce
que l'inverse (écrire puis découvrir) est exactement ce qui rend un outil
inutilisable par quelqu'un qui n'ose pas revenir en arrière. L'ancienne version
est sauvegardée horodatée avant tout remplacement.

La comparaison est faite au niveau MÉTIER (modules ajoutés, retirés, volumes ou
enseignants modifiés) et pas ligne à ligne : un diff textuel sur un JSON d'une
seule ligne n'apprend rien à personne.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ChangeSummary:
    """Ce qui distingue la version téléchargée de celle en place."""

    fichier: str
    ajoutes: list[str] = field(default_factory=list)
    retires: list[str] = field(default_factory=list)
    modifies: list[str] = field(default_factory=list)
    identique: bool = False
    erreur: str | None = None

    def total(self) -> int:
        return len(self.ajoutes) + len(self.retires) + len(self.modifies)

    def to_text(self) -> str:
        if self.erreur:
            return f"  {self.fichier} : {self.erreur}"
        if self.identique:
            return f"  {self.fichier} : aucun changement"
        lines = [f"  {self.fichier} : {self.total()} changement(s)"]
        for titre, items in (
            ("ajouté(s)", self.ajoutes),
            ("retiré(s)", self.retires),
            ("modifié(s)", self.modifies),
        ):
            if not items:
                continue
            apercu = ", ".join(items[:10])
            suite = f" … (+{len(items) - 10})" if len(items) > 10 else ""
            lines.append(f"      {len(items)} {titre} : {apercu}{suite}")
        return "\n".join(lines)


def _key(entry: dict) -> str:
    code = str(entry.get("code_matiere", "?"))
    semestre = str(entry.get("semestre", "?"))
    parcours = str(entry.get("parcours", "?"))
    return f"{code} ({semestre} {parcours})"


def _signature(entry: dict) -> str:
    """Ce qui compte métier : volumes, enseignants, progression.

    Volontairement PAS l'objet entier — les exports contiennent des horodatages
    de commentaires qui changent sans que rien de planifiable ne bouge, et
    signaler ces changements-là ferait passer les vrais pour du bruit.
    """
    interesting = {
        "total": entry.get("total"),
        "volumes": entry.get("volumes"),
        "groupes": (entry.get("maquette") or {}).get("groupes") or entry.get("groupes"),
        "profs": [
            {k: p.get(k) for k in ("code", "cm", "td", "tp", "nbGpTd", "nbGpTp")}
            for p in (entry.get("profs") or [])
        ],
        "lead": (entry.get("lead") or {}).get("code"),
        "progression": (entry.get("progression") or {}).get("seances"),
        "ordonnancement": entry.get("ordonnancement"),
    }
    return json.dumps(interesting, sort_keys=True, ensure_ascii=False)


def compare_exports(ancien: list[dict], nouveau: list[dict], fichier: str) -> ChangeSummary:
    a = {_key(e): _signature(e) for e in ancien}
    b = {_key(e): _signature(e) for e in nouveau}
    summary = ChangeSummary(fichier=fichier)
    summary.ajoutes = sorted(set(b) - set(a))
    summary.retires = sorted(set(a) - set(b))
    summary.modifies = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    summary.identique = not summary.total()
    return summary


def refresh_sources(
    project_root: Path,
    *,
    ecrire: bool = False,
    depuis_fichiers: Path | None = None,
) -> tuple[list[ChangeSummary], list[str]]:
    """Télécharge (ou relit) maquette + progression et compare à l'existant.

    `ecrire=False` (défaut) : ne touche à rien, se contente de dire ce qui
    changerait. C'est le mode qu'un utilisateur qui découvre l'outil peut lancer
    sans crainte.

    `depuis_fichiers` : dossier local contenant `maquette.json` et
    `progression.json`, pour le cas — fréquent — où quelqu'un les a reçus par
    mail plutôt que de pouvoir joindre le serveur.

    Retourne `(résumés, messages)`.
    """
    from cal_iut.ingestion.fetch import MAQUETTE_URL, PROGRESSION_URL

    src = project_root / "contraintes_update"
    messages: list[str] = []
    resumes: list[ChangeSummary] = []

    sources: dict[str, list[dict]] = {}
    if depuis_fichiers is not None:
        for nom in ("maquette.json", "progression.json"):
            chemin = depuis_fichiers / nom
            if not chemin.exists():
                messages.append(
                    f"ERREUR : {chemin} est introuvable. Le dossier doit contenir "
                    "maquette.json ET progression.json."
                )
                return resumes, messages
            try:
                sources[nom] = json.loads(chemin.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                messages.append(
                    f"ERREUR : {nom} n'est pas un JSON valide ({exc.msg}, ligne {exc.lineno}). "
                    "Le fichier a probablement été ouvert et réenregistré par un tableur."
                )
                return resumes, messages
        messages.append(f"Lu depuis {depuis_fichiers}")
    else:
        import httpx

        from cal_iut.ingestion.fetch import fetch_export_sync

        for nom, url in (("maquette.json", MAQUETTE_URL), ("progression.json", PROGRESSION_URL)):
            try:
                sources[nom] = fetch_export_sync(url)
            except httpx.HTTPError as exc:
                messages.append(
                    f"ERREUR : impossible de télécharger {url}\n"
                    f"         ({exc.__class__.__name__})\n"
                    "         Vérifiez votre connexion, ou récupérez les deux fichiers à la "
                    "main et relancez avec --depuis <dossier>."
                )
                return resumes, messages
            except ValueError as exc:
                messages.append(
                    f"ERREUR : {url} n'a pas renvoyé la liste attendue ({exc}). "
                    "L'adresse d'export a peut-être changé."
                )
                return resumes, messages
        messages.append(f"Téléchargé depuis {MAQUETTE_URL} et {PROGRESSION_URL}")

    for nom, nouveau in sources.items():
        actuel_path = src / nom
        if actuel_path.exists():
            try:
                ancien = json.loads(actuel_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                ancien = []
        else:
            ancien = []
        resumes.append(compare_exports(ancien, nouveau, nom))

    if not ecrire:
        messages.append("")
        messages.append("Rien n'a été écrit (mode aperçu). Pour appliquer : ajoutez --ecrire")
        return resumes, messages

    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    sauvegardes = project_root / "data" / "sauvegardes" / horodatage
    sauvegardes.mkdir(parents=True, exist_ok=True)
    src.mkdir(parents=True, exist_ok=True)
    ecrits: list[str] = []
    for nom, nouveau in sources.items():
        cible = src / nom
        contenu = json.dumps(nouveau, ensure_ascii=False)
        # Ne PAS réécrire un fichier identique. Une réécriture inutile change sa
        # date de modification, et tous les contrôles de fraîcheur en aval
        # (`cal-iut doctor`, `audit_generated_freshness`) annoncent alors des
        # contraintes « à regénérer » alors que rien n'a bougé — constaté le
        # 26/08/2026 : les deux exports étaient à l'octet près identiques, à
        # 6 millisecondes près de la génération. Un contrôle qui crie à tort
        # finit ignoré.
        if cible.exists() and cible.read_text(encoding="utf-8") == contenu:
            continue
        if cible.exists():
            shutil.copyfile(cible, sauvegardes / nom)
        cible.write_text(contenu, encoding="utf-8")
        ecrits.append(nom)

    if ecrits:
        messages.append(f"Ancienne version sauvegardée dans {sauvegardes}")
        messages.append(f"Fichiers mis à jour dans contraintes_update/ : {', '.join(ecrits)}")
    else:
        messages.append("Aucun changement : les fichiers sources sont déjà à jour.")
    return resumes, messages
