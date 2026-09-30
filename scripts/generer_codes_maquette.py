"""Régénère `data/config/celcat_modules_maquette.yaml` : les codes module
Celcat préenregistrés depuis la maquette (`codelement`), cf.
`src/cal_iut/celcat/codes_maquette.py` pour les règles.

    python scripts/generer_codes_maquette.py [--verifier]

À relancer quand la maquette ou le relevé des matières
(`celcat_matieres.yaml`) change, puis relire le diff avant de committer :
ces codes servent aussi à la paie. `--verifier` n'écrit rien et sort en
erreur si le fichier n'est plus à jour.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import yaml

from cal_iut.celcat import codes_maquette


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Codes Celcat préenregistrés depuis la maquette")
    parseur.add_argument("--verifier", action="store_true", help="ne rien écrire ; échouer si le fichier diffère")
    options = parseur.parse_args(argv)

    from cal_iut.ingestion.merge import merge_exports
    from cal_iut.ingestion.pipeline import _load_cached_or_fetch

    config_dir = RACINE / "data" / "config"
    maquette, progression = _load_cached_or_fetch(config_dir)
    cours = merge_exports(maquette, progression)
    data = yaml.safe_load((config_dir / "celcat.yaml").read_text(encoding="utf-8")) or {}
    modules = {str(k).upper(): str(v) for k, v in (data.get("modules") or {}).items() if v}
    voulus = {str(k).upper() for k in ((data.get("sans_code_voulu") or {}).get("cours") or {})}
    releve = codes_maquette.releve_des_matieres(config_dir)
    retenus, manquants = codes_maquette.calculer(
        cours, modules_fichier=modules, sans_code_voulu=voulus, releve=releve
    )

    exacts = sum(1 for r in retenus if r.origine == codes_maquette.ORIGINE_MAQUETTE)
    corriges = len(retenus) - exacts
    print(f"{len(retenus)} code(s) préenregistré(s) : {exacts} tel(s) quel(s), {corriges} corrigé(s) M→C")
    for cours_code, raison in manquants:
        print(f"  manquant : {cours_code} — {raison}")
    # Contrôle de lecture : le nom Celcat doit nommer le cours.
    verifier = codes_maquette.a_verifier(retenus)
    for ligne in verifier:
        print(f"  À VÉRIFIER : {ligne}")

    chemin = config_dir / codes_maquette.FICHIER
    if options.verifier:
        attendu = {r.cours: r.code for r in retenus}
        actuel = {k: v["code"] for k, v in codes_maquette.lire(config_dir).items()}
        if attendu != actuel:
            print("Le fichier n'est plus à jour : relancez sans --verifier.", file=sys.stderr)
            return 1
        return 0
    codes_maquette.ecrire(
        chemin, retenus, manquants, date=datetime.now().astimezone().strftime("%d/%m/%Y"), verifier=verifier
    )
    print(f"Écrit : {chemin.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
