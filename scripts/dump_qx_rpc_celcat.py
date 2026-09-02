"""Trouve le client RPC qooxdoo après login, sans mot de passe ni new."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402

_JS = """() => {
  const reg = qx.core.ObjectRegistry.getRegistry();
  const classes = {};
  const hits = [];
  for (const h of Object.keys(reg)) {
    const o = reg[h];
    if (!o || !o.classname) continue;
    classes[o.classname] = (classes[o.classname] || 0) + 1;
    if (typeof o.invoke === 'function') hits.push(o.classname + ':' + h);
  }
  const rpcish = Object.keys(classes).filter(c => /rpc|Rpc|Session|ctweb\\.io/i.test(c));
  return { nInvoke: hits.length, hits: hits.slice(0, 25), rpcish, sample: Object.keys(classes).filter(c => c.startsWith('ctweb.io') || c.startsWith('ctweb.model.session') || c.startsWith('ctweb.controller')).slice(0, 40) };
}"""


def principal() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    diag = reseau.exiger_acces(os.environ["CELCAT_URL"], monter_le_vpn=True)
    if not diag:
        print(diag.detail, file=sys.stderr)
        return 3
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        navg = p.chromium.launch(headless=True)
        page = navg.new_page(viewport={"width": 1920, "height": 1080})
        try:
            nav.connexion(page, base=nav.BASE_ENTRAINEMENT, role=nav.ROLE_ECRITURE)
            info = page.evaluate(_JS)
            print(json.dumps(info, ensure_ascii=False, indent=2)[:4000])
            (RACINE / "data" / "releves" / "celcat-qx-rpc.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        finally:
            nav.deconnexion(page)
            navg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
