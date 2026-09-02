"""Dump l'URL et les en-têtes du POST `udlTimetables.load` que l'app réussit."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402


def principal() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ["CELCAT_URL"]
    diag = reseau.exiger_acces(url, monter_le_vpn=True)
    if not diag:
        print(diag.detail, file=sys.stderr)
        return 3

    from playwright.sync_api import sync_playwright

    vus: list[dict] = []

    def noter(reponse) -> None:
        req = reponse.request
        if req.method != "POST" or "CTWebService" not in reponse.url:
            return
        if envoi.get("method") == "login.login" and isinstance(envoi.get("params"), list):
            params = list(envoi["params"])
            if len(params) > 2:
                params[2] = "***"

    with sync_playwright() as p:
        navg = p.chromium.launch(headless=True)
        page = navg.new_page(viewport={"width": 1920, "height": 1080})
        page.on("response", noter)
        try:
            nav.connexion(page, base=nav.BASE_ENTRAINEMENT, role=nav.ROLE_ECRITURE)
            nav.ouvrir_ressource(page, nav.TYPE_GROUPES)
            nav.filtrer(page, "BUT MMI S1 TD AB")
            page.wait_for_timeout(1500)
            nav.double_cliquer_texte(page, "BUT MMI S1 TD AB - 2024")
            nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
            page.wait_for_timeout(1500)
        finally:
            nav.deconnexion(page)
            navg.close()

    charges = [
        {
            "methode": v["methode"],
            "url": v["url"],
            "id": v["id"],
            "header_keys": sorted(v["headers"]),
            "headers_utiles": {
                k: v["headers"][k]
                for k in v["headers"]
                if k.lower() not in {"cookie", "authorization"}
                and (
                    "session" in k.lower()
                    or "timetable" in k.lower()
                    or k.lower().startswith("x-")
                    or k.lower() in {"referer", "origin", "content-type"}
                )
            },
            "params": v["params"] if v["methode"] != "udlResources.load" else "…",
        }
        for v in vus
        if v["methode"] in {
            "udlTimetables.load", "login.login", "login.getTimetables", "system.getOptions",
        }
    ]
    chemin = RACINE / "data" / "releves" / "celcat-rpc-en-tetes.json"
    chemin.write_text(json.dumps(charges, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(charges, ensure_ascii=False, indent=2)[:4000])
    print(f"écrit {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
