"""Scanne le JS chargé par Celcat pour toutes les méthodes `udl*.*` —
même technique que `capturer_save_celcat.py` (qui a trouvé
"udlTimetables.save" par ce biais), pour repérer une méthode de
suppression candidate sans cliquer dans l'UI (plus fiable qu'un
repérage de bloc par double-clic, qui a échoué à plusieurs reprises en
environnement headless).

    python scripts/scanner_methodes_udl_celcat.py --vpn --base URCA_FORMATION
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402

_JS_METHODES = """async () => {
  const noms = new Set();
  const srcs = [...document.querySelectorAll('script[src]')].map(s => s.src);
  for (const src of srcs) {
    try {
      const t = await fetch(src).then(r => r.text());
      for (const m of t.matchAll(/udl[A-Za-z]+\\.[a-zA-Z]+/g)) noms.add(m[0]);
      // Recherche large, au cas où la suppression ne passerait pas par un
      // service udl* : tout littéral contenant delete/remove/suppr proche
      // d'un point (motif "Service.methode"), casse ignorée.
      for (const m of t.matchAll(/[A-Za-z_]{2,30}\\.[a-zA-Z_]*(?:[Dd]elete|[Rr]emove|[Ss]uppr|[Cc]ancel)[a-zA-Z_]*/g)) {
        noms.add("LARGE:" + m[0]);
      }
    } catch (e) {}
  }
  return [...noms].sort();
}"""


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    args = parseur.parse_args()

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
        try:
            print(f"Connexion {args.base} rôle {args.role}…")
            nav.connexion(page, base=args.base, role=args.role)
            print("Scan des scripts udl*…")
            noms = page.evaluate(_JS_METHODES)
            print(f"{len(noms)} méthode(s) udl* trouvée(s) :")
            for n in noms:
                marque = "  <---" if any(
                    mot in n.lower() for mot in ("delete", "remove", "suppr", "cancel", "drop")
                ) else ""
                print(f"  {n}{marque}")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
