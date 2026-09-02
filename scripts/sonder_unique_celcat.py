"""IDs de modules depuis l'EDT S1 TD AB, puis scan autour. Aucune écriture."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.rpc import charger_edt, charger_ressources  # noqa: E402

CIBLES = {"TSBZ1307", "TSB1507D", "TSBZ5010", "TSB1508D"}
FILTRE = {"customOnly": False, "includedDetails": []}


def principal() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    diag = reseau.exiger_acces(os.environ["CELCAT_URL"], monter_le_vpn=True)
    if not getattr(diag, "joignable", False):
        print(diag.detail, file=sys.stderr)
        return 3
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            nav.connexion(page, base=nav.BASE_PRODUCTION, role=nav.ROLE_ECRITURE)
            evs = charger_edt(page, group_ids=[1661972, 1660025, 1660026, 1660027])
            print(f"{len(evs)} events")
            for ev in evs:
                for m in ev.get("modules") or []:
                    if isinstance(m, dict):
                        print(
                            "mod",
                            m.get("module_id") or m.get("id"),
                            m.get("unique_name"),
                            m.get("name"),
                        )
            restants = set(CIBLES)
            # Plage large autour des IDs vus + IDs groupes.
            for debut, fin, pas in ((1650000, 1670000, 500),):
                for a in range(debut, fin, pas):
                    if not restants:
                        break
                    ids = list(range(a, min(a + pas, fin)))
                    try:
                        lots = charger_ressources(
                            page, nav.TYPE_MATIERES, {**FILTRE, "recordIDs": ids}
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"plage {a} {exc}")
                        continue
                    for r in lots:
                        code = str(r.get("unique_name") or "")
                        if code in restants or (code.startswith("TSB") and "MMI" in str(r.get("name") or "")):
                            mid = r.get("module_id") or r.get("id")
                            print(f"  {mid} {code} {r.get('name')}")
                            restants.discard(code)
            print("manque", restants)
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
