"""Prouve le RPC in-page et capture un Enregistrer sur URCA_FORMATION.

Aucun `new`. Lecture d'abord (catégories + éventuellement un EDT).
Si `--sauver` : double-clic sur un événement EXISTANT, icône save, on
note la méthode JSON-RPC. Rien n'est créé. Base imposée : FORMATION.

    python scripts/capturer_save_celcat.py --vpn --sauver
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.rpc import SessionCelcatTimeout, appeler  # noqa: E402

_JS_METHODES = """async () => {
  const noms = new Set();
  const srcs = [...document.querySelectorAll('script[src]')].map(s => s.src);
  for (const src of srcs) {
    try {
      const t = await fetch(src).then(r => r.text());
      for (const m of t.matchAll(/udl[A-Za-z]+\\.[a-zA-Z]+/g)) noms.add(m[0]);
    } catch (e) {}
  }
  return [...noms].sort();
}"""

GRILLE = {"x_min": 980, "x_max": 1910, "y_min": 150, "y_max": 900}
_JS_BLOCS = """(zone) => {
  const out = [];
  for (const e of document.querySelectorAll('div')) {
    const r = e.getBoundingClientRect();
    if (r.x < zone.x_min || r.x > zone.x_max) continue;
    if (r.y < zone.y_min || r.y > zone.y_max) continue;
    if (r.width < 24 || r.width > 320 || r.height < 10) continue;
    const fond = getComputedStyle(e).backgroundColor || '';
    const m = fond.match(/rgba?\\(([^)]+)\\)/);
    if (!m) continue;
    const [rr, vv, bb, aa] = m[1].split(',').map(v => parseFloat(v));
    if ((aa === undefined ? 1 : aa) < 0.05) continue;
    if (rr > 245 && vv > 245 && bb > 245) continue;
    out.push({
      x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
      largeur: Math.round(r.width), hauteur: Math.round(r.height),
    });
  }
  return out;
}"""

IGNORER = {
    "system.getOptions",
    "login.getRoles",
    "login.login",
    "udlResources.load",
    "udlTimetables.load",
}


class JournalRpc:
    def __init__(self, page) -> None:
        self.appels: list[dict] = []
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
        params = envoi.get("params") or []
        try:
            corps = nav.lire_reponse(reponse.text())
        except Exception:  # noqa: BLE001
            corps = {}
        self.appels.append({
            "methode": methode,
            "params": params,
            "params0": params[0] if params else None,
            "jsonrpc_id": envoi.get("id"),
            "erreur": corps.get("error") if isinstance(corps, dict) else None,
            "n": len(corps["result"]) if isinstance(corps, dict) and isinstance(corps.get("result"), list) else None,
        })


def _ecrire_yaml(methode: str) -> None:
    chemin = RACINE / "data" / "config" / "celcat_rpc.yaml"
    chemin.write_text(
        "# Méthode d'écriture JSON-RPC relevée sur URCA_FORMATION.\n"
        f"methode_ecriture: {methode}\n"
        "event_id_create: 0\n",
        encoding="utf-8",
    )


def _ouvrir_groupes(page) -> None:
    hauts = [f["texte"] for f in nav.feuilles(page) if f["y"] < 55 and f["x"] < 220]
    if "Groupes" in hauts:
        return
    for y in range(48, 430, 14):
        page.mouse.click(18, y)
        page.wait_for_timeout(700)
        hauts = [f["texte"] for f in nav.feuilles(page) if f["y"] < 55 and f["x"] < 220]
        if "Groupes" in hauts:
            page.wait_for_timeout(900)
            return
    nav.ouvrir_ressource(page, nav.TYPE_GROUPES)


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    parseur.add_argument("--sauver", action="store_true")
    parseur.add_argument("--filtre-groupe", default="BUT MMI")
    args = parseur.parse_args()
    if args.base != nav.BASE_ENTRAINEMENT:
        print("refus : capture uniquement sur URCA_FORMATION", file=sys.stderr)
        return 2
    if args.sauver and args.role == nav.ROLE_LECTURE:
        print("refus : --sauver exige un rôle d'écriture (985_T_MMI)", file=sys.stderr)
        return 2

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

    preuve: dict = {
        "base": args.base,
        "role": args.role,
        "rpc_in_page": None,
        "scripts_udl": [],
        "methodes_post": [],
        "methodes_save": [],
        "groupe": None,
        "ids_identiques": None,
    }

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        journal = JournalRpc(page)
        try:
            print(f"Connexion {args.base} rôle {args.role} (aucun new)…")
            nav.connexion(page, base=args.base, role=args.role)

            print("RPC in-page : udlResources.load(618)…")
            try:
                cats = appeler(page, "udlResources.load", [nav.TYPE_CATEGORIES_EVENEMENT])
                n = len(cats) if isinstance(cats, list) else None
                preuve["rpc_in_page"] = {"ok": True, "n": n}
                print(f"  OK, {n} catégorie(s)")
            except SessionCelcatTimeout as exc:
                preuve["rpc_in_page"] = {"ok": False, "erreur": "ESessionTimeout"}
                print(f"  ESessionTimeout : {exc}")
            except Exception as exc:  # noqa: BLE001
                preuve["rpc_in_page"] = {"ok": False, "erreur": str(exc)[:300]}
                print(f"  échec : {exc}")

            try:
                noms = page.evaluate(_JS_METHODES)
                preuve["scripts_udl"] = noms
                print(f"méthodes udl* scripts : {noms}")
                if "udlTimetables.save" in noms:
                    _ecrire_yaml("udlTimetables.save")
                    print("  methode_ecriture = udlTimetables.save (scripts)")
            except Exception as exc:  # noqa: BLE001
                print(f"scan scripts : {exc}")

            print(f"Liste groupes « {args.filtre_groupe} »…")
            _ouvrir_groupes(page)
            nav.filtrer(page, args.filtre_groupe)
            page.wait_for_timeout(2000)
            groupes = [
                a for a in journal.appels
                if a["methode"] == "udlResources.load" and a.get("noms" ) is None
            ]
            # Noms visibles à l'écran
            textes = [
                f["texte"] for f in nav.feuilles(page)
                if "MMI" in f["texte"] or "BUT" in f["texte"]
            ]
            print(f"  textes MMI/BUT : {textes[:12]}")
            preuve["textes_groupes"] = textes[:20]
            res_ok = next(
                (
                    a for a in reversed(journal.appels)
                    if a["methode"] == "udlResources.load" and (a.get("n") or 0) > 0
                ),
                None,
            )
            if res_ok:
                preuve["resource_load_params"] = res_ok.get("params")
                print(f"  resources.load params={res_ok.get('params')!r} n={res_ok.get('n')}")
            nom_groupe = next(
                (t for t in textes if "TD" in t and "BUT MMI" in t),
                next((t for t in textes if "BUT MMI" in t), None),
            )
            if nom_groupe:
                preuve["groupe"] = nom_groupe
                print(f"Ouverture « {nom_groupe} »…")
                nav.double_cliquer_texte(page, nom_groupe)
                try:
                    nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
                except TimeoutError as exc:
                    print(f"  EDT non ouvert : {exc}")
                    nom_groupe = None
            if nom_groupe:
                try:
                    nav.cliquer_icone_barre(page, "rafraichir")
                except LookupError:
                    pass
                page.wait_for_timeout(2000)
                load = next(
                    (a for a in reversed(journal.appels) if a["methode"] == "udlTimetables.load"),
                    None,
                )
                if load:
                    preuve["load_params"] = load.get("params")
                    print(f"  load intercepté params={load.get('params')!r} n={load.get('n')}")
                    try:
                        rejoue = appeler(page, "udlTimetables.load", list(load.get("params") or []))
                        n = len(rejoue) if isinstance(rejoue, list) else None
                        preuve["ids_identiques"] = n == load.get("n")
                        preuve["n_evenements"] = n
                        print(f"  fetch in-page EDT (params copiés) : {n} événement(s)")
                    except Exception as exc:  # noqa: BLE001
                        preuve["ids_identiques"] = False
                        preuve["load_in_page_erreur"] = str(exc)[:300]
                        print(f"  fetch in-page EDT : {exc}")

                if args.sauver:
                    page.mouse.move(*nav.SUR_LA_LISTE)
                    page.wait_for_timeout(400)
                    blocs = sorted(
                        page.evaluate(_JS_BLOCS, GRILLE),
                        key=lambda b: -(b["hauteur"] * b["largeur"]),
                    )
                    print(f"  {len(blocs)} bloc(s) coloré(s)")
                    avant = len(journal.appels)
                    ouvert = False
                    for bloc in blocs[:8]:
                        page.mouse.click(bloc["x"], bloc["y"], click_count=2)
                        page.wait_for_timeout(2500)
                        textes_ecran = {f["texte"] for f in nav.feuilles(page)}
                        if ("Jour:" in textes_ecran or "Heure:" in textes_ecran) and (
                            "Sélectionner un événement pour voir ses détails" not in textes_ecran
                        ):
                            ouvert = True
                            break
                    if not ouvert:
                        print("  inspecteur non ouvert — pas de save")
                    else:
                        print("  inspecteur ouvert, clic Enregistrer…")
                        nav.cliquer_icone_barre(page, "enregistrer")
                        page.wait_for_timeout(4000)
                        nouveaux = journal.appels[avant:]
                        saves = [
                            a for a in nouveaux
                            if a["methode"] and a["methode"] not in IGNORER
                        ]
                        preuve["methodes_save"] = [
                            {
                                "methode": a["methode"],
                                "n_params": len(a.get("params") or []),
                                "params0_type": type(a.get("params0")).__name__,
                                "params0_cles": sorted(a["params0"].keys()) if isinstance(a.get("params0"), dict) else None,
                                "erreur": a.get("erreur"),
                            }
                            for a in saves
                        ]
                        if saves:
                            brut_save = RACINE / "data" / "releves" / "celcat-rpc-save.json"
                            brut_save.write_text(
                                json.dumps(saves, ensure_ascii=False, indent=2, default=str),
                                encoding="utf-8",
                            )
                            print(f"  payload save -> {brut_save}")
                        print(f"  POST hors load : {[a['methode'] for a in saves]}")
                        for a in saves:
                            nom = str(a["methode"])
                            if any(m in nom.lower() for m in ("save", "update", "commit", "store")):
                                _ecrire_yaml(nom)
                                print(f"  methode_ecriture = {nom}")
                                break

        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()

    preuve["methodes_post"] = sorted({
        str(a["methode"]) for a in journal.appels if a.get("methode")
    })
    dossier = RACINE / "data" / "releves"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "celcat-rpc-preuve.json"
    chemin.write_text(json.dumps(preuve, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"écrit {chemin}")
    if preuve.get("rpc_in_page", {}).get("ok"):
        return 0
    return 5


if __name__ == "__main__":
    raise SystemExit(principal())
