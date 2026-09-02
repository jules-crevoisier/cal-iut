"""Méthodes RPC Celcat lues depuis `data/config/celcat_rpc.yaml`.

Remplace la fonction `_methode_yaml()` dupliquée dans
`scripts/pousser_manquants_celcat.py` et
`scripts/corriger_cm_categories_celcat.py` — une seule lecture, un seul
format de retour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RpcConfig:
    methode_ecriture: str = ""
    methode_suppression: str = ""


def charger_methodes(config_dir: Path) -> RpcConfig:
    """Lit `celcat_rpc.yaml`. Absent ou vide = méthodes vides, jamais devinées."""
    chemin = Path(config_dir) / "celcat_rpc.yaml"
    if not chemin.exists():
        return RpcConfig()
    data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return RpcConfig()
    return RpcConfig(
        methode_ecriture=str(data.get("methode_ecriture") or ""),
        methode_suppression=str(data.get("methode_suppression") or ""),
    )
