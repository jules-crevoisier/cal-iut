"""Captures d'écran de l'interface, pour relire un changement visuel.

Usage (serveur local déjà lancé, `cal-iut serve --port 8000`) :

    python scripts/creer_admin_local.py            # une fois : compte admin@local.test
    python scripts/captures_ui.py --port 8000 --sortie captures/ --prefixe apres
    python scripts/captures_ui.py --vues promo,prof --largeur 390   # téléphone

Nécessite `pip install playwright` ; le navigateur est celui déjà installé
(`PLAYWRIGHT_BROWSERS_PATH`) ou `--chrome <chemin>`. Outil de développement
uniquement : jamais appelé par l'application.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

VUES = [
    "semaine", "prof", "promo", "groupe", "cours", "salle", "reference", "contraintes",
    "apf", "taches", "comptes", "celcat", "sauvegardes", "mcp",
]
LIENS_PUBLICS = {
    "public-prof": "#vue=prof&prof=KBR&mode=prof",
    "public-groupe": "#vue=groupe&groupe=but3-dev-fc-td-ef&mode=groupe",
    "public-promo": "#mode=promo",
    "public-salles": "#mode=salles",
}
PREFS = json.dumps({"couleursParMatiere": False, "repondu": True})


def _chromium_installe() -> str:
    """Premier Chromium complet trouvé sous `PLAYWRIGHT_BROWSERS_PATH` : la
    version attendue par le paquet `playwright` n'est pas forcément celle
    installée sur la machine, et le télécharger n'est pas toujours possible."""
    import glob
    import os

    racine = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    trouves = sorted(glob.glob(f"{racine}/chromium-*/chrome-linux*/chrome"))
    return trouves[-1] if trouves else ""


async def _main(args: argparse.Namespace) -> None:
    from playwright.async_api import async_playwright

    base = f"http://localhost:{args.port}/"
    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    vues = args.vues.split(",") if args.vues else VUES + list(LIENS_PUBLICS)
    async with async_playwright() as p:
        chrome = args.chrome or _chromium_installe()
        options = {"executable_path": chrome} if chrome else {}
        navigateur = await p.chromium.launch(**options)

        async def contexte():
            ctx = await navigateur.new_context(viewport={"width": args.largeur, "height": args.hauteur})
            await ctx.add_init_script(f"localStorage.setItem('cal-iut:preferences:v1', '{PREFS}')")
            return ctx

        ctx = await contexte()
        page = await ctx.new_page()
        await page.goto(base)
        await page.wait_for_timeout(800)
        if await page.locator("input[type=email]").count():
            await page.fill("input[type=email]", args.email)
            await page.fill("input[type=password]", args.mot_de_passe)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)
        for vue in vues:
            if vue in LIENS_PUBLICS:
                public = await (await contexte()).new_page()
                await public.goto(base + LIENS_PUBLICS[vue])
                await public.wait_for_timeout(args.attente)
                await public.screenshot(path=str(sortie / f"{args.prefixe}-{vue}.png"), full_page=args.pleine_page)
                continue
            # Rechargement complet : chaque vue part d'un état propre.
            await page.goto(f"{base}#vue={vue}")
            await page.reload()
            await page.wait_for_timeout(args.attente)
            await page.screenshot(path=str(sortie / f"{args.prefixe}-{vue}.png"), full_page=args.pleine_page)
        await navigateur.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sortie", default="captures")
    parser.add_argument("--prefixe", default="capture")
    parser.add_argument("--vues", default="", help="liste séparée par des virgules (défaut : toutes)")
    parser.add_argument("--largeur", type=int, default=1440)
    parser.add_argument("--hauteur", type=int, default=900)
    parser.add_argument("--attente", type=int, default=1800, help="ms d'attente après navigation")
    parser.add_argument("--pleine-page", action="store_true")
    parser.add_argument("--email", default="admin@local.test")
    parser.add_argument("--mot-de-passe", default="admin-local-123")
    parser.add_argument("--chrome", default="", help="chemin d'un Chromium à utiliser")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
