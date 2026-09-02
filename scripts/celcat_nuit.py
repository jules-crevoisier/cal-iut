"""Job de nuit Celcat : file d'attente des semaines validées + extras.

Ne se connecte pas à Live tout seul. Lance `executer_job_nuit` (queue +
rapport extras). Le sidecar Docker (VPN + RPC) consomme ensuite la file.

    python scripts/celcat_nuit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat.etat import charger  # noqa: E402
from cal_iut.celcat.nuit import executer_job_nuit  # noqa: E402


def principal() -> int:
    doc = charger()
    if not doc.get("saisie_active"):
        print("saisie inactive — rien à faire")
        return 0
    executer_job_nuit()
    print("job nuit : file d'attente + extras mis à jour")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
