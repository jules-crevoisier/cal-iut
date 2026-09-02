"""Premier sondage : le JSON-RPC depuis la page égale-t-il l'interception ?

Connexion lecture seule. Aucun `new`. Compare `udlTimetables.load` injecté
dans la page au POST que l'application fait elle-même.

    python scripts/sonder_rpc_celcat.py --vpn --groupe "S1 TD AB"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.lecture import evenement_depuis_rpc  # noqa: E402
from cal_iut.celcat.rpc import charger_edt  # noqa: E402

_JS_METHODES = """async () => {
  const noms = new Set();
  const srcs = [...document.querySelectorAll('script[src]')].map(s => s.src);
  for (const src of srcs) {
    try {
      const t = await fetch(src).then(r => r.text());
      for (const m of t.matchAll(/"(udl[A-Za-z]+\\.[a-zA-Z]+)"/g)) noms.add(m[1]);
    } catch (e) {}
  }
  return [...noms].sort();
}"""


class Espion:
    def __init__(self, page) -> None:
        self.dernier: list[dict] = []
        self.params: object = None
        self.methodes: list[str] = []
        page.on("response", self._noter)

    def _noter(self, reponse) -> None:
        req = reponse.request
        if req.method != "POST" or "CTWebService.dll" not in reponse.url:
            return
        try:
            envoi = json.loads(req.post_data or "{}")
        except json.JSONDecodeError:
            return
        methode = str(envoi.get("method") or "")
        if methode:
            self.methodes.append(methode)
        if methode != "udlTimetables.load":
            return
        self.params = envoi.get("params")
        try:
            corps = nav.lire_reponse(reponse.text())
        except Exception:  # noqa: BLE001
            return
        res = corps.get("result")
        if isinstance(res, list):
            self.dernier = [e for e in res if isinstance(e, dict)]


def _ouvrir_groupe(page, nom: str, lundi: dt.date) -> None:
    nav.ouvrir_ressource(page, nav.TYPE_GROUPES)
    nav.filtrer(page, nom)
    nav.double_cliquer_texte(page, nom)
    nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
    try:
        nav.cliquer_icone_barre(page, "rafraichir")
    except LookupError:
        pass
    nav.choisir_semaine(page, lundi)
    page.wait_for_timeout(2000)


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--lundi", default="2026-09-07")
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    parseur.add_argument("--groupe", default="BUT MMI S1 TD AB")
    args = parseur.parse_args()
    lundi = dt.date.fromisoformat(args.lundi)

    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ.get("CELCAT_URL", "")
    if not url:
        print("CELCAT_URL absent", file=sys.stderr)
        return 2
    diag = reseau.exiger_acces(url, monter_le_vpn=args.vpn) if args.vpn else reseau.verifier(url)
    if not getattr(diag, "joignable", False):
        print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
        return 3

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        espion = Espion(page)
        try:
            print(f"Connexion {args.base} rôle {args.role} (lecture, aucun new)…")
            nav.connexion(page, base=args.base, role=args.role)
            _ouvrir_groupe(page, args.groupe, lundi)
            interceptes = list(espion.dernier)
            group_ids: list[int] = []
            if isinstance(espion.params, list) and espion.params:
                tete = espion.params[0]
                if isinstance(tete, dict):
                    group_ids = [int(x) for x in (tete.get("GroupIDs") or [])]
            print(f"interception : {len(interceptes)} événement(s), GroupIDs={group_ids}")
            print(f"méthodes vues : {sorted(set(espion.methodes))}")
            if not group_ids:
                print("aucun GroupIDs dans le POST — impossible de comparer le fetch in-page")
                return 4
            depuis_page = charger_edt(page, group_ids=group_ids)
            ids_i = {e.get("event_id") for e in interceptes}
            ids_p = {e.get("event_id") for e in depuis_page}
            print(f"fetch in-page : {len(depuis_page)} événement(s)")
            print(f"ids identiques : {ids_i == ids_p} (intercept {len(ids_i)}, page {len(ids_p)})")
            if interceptes:
                ev = evenement_depuis_rpc(
                    interceptes[0], group_id=group_ids[0], groupe_nom=args.groupe
                )
                brut = interceptes[0]
                print(
                    f"exemple id={ev.event_id} jour={ev.jour} "
                    f"start_brut={brut.get('start_time')!r} heure={ev.heure_debut!r} "
                    f"module={ev.module_nom!r} weeks_Y={ev.weeks.count('Y')}"
                )
            try:
                noms = page.evaluate(_JS_METHODES)
                print(f"méthodes udl* dans les scripts : {noms}")
            except Exception as exc:  # noqa: BLE001
                print(f"scan scripts : {exc}")
            return 0 if ids_i == ids_p else 5
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
