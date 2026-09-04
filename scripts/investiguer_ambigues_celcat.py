"""Investigue le détail des correspondances AMBIGUËS de comparer().

Lecture seule, jamais d'écriture. Réutilise la même lecture que
pousser_manquants_celcat.py mais affiche, pour chaque entrée ambiguë,
la liste complète des événements Celcat qui matchent (module + groupe +
jour + heure) sans salle discriminante — pour distinguer un vrai doublon
Celcat (même salle, même tout, deux event_id) d'une ambiguïté résoluble
(salles différentes, juste notre comparer() qui n'utilise pas la salle
pour apparier).

    python scripts/investiguer_ambigues_celcat.py --lundi 2026-09-07 --vpn --base URCA_2026
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import reseau
from cal_iut.celcat.diff import _apparie, comparer
from cal_iut.celcat.ecriture import resoudre_groupe
from cal_iut.celcat.lecture import evenement_depuis_rpc, indice_depuis_lundi, sur_la_semaine
from cal_iut.celcat.rpc import charger_edt


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--lundi", default="2026-09-07")
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--premiere-semaine-celcat", type=int, default=34)
    args = parseur.parse_args()
    lundi = dt.date.fromisoformat(args.lundi)

    from saisir_semaine_celcat import _charger_entrees
    semaine, entrees = _charger_entrees(lundi)
    indice = indice_depuis_lundi(lundi, premiere_semaine_celcat=args.premiere_semaine_celcat)
    print(f"semaine solveur {semaine} = lundi {lundi} = indice weeks {indice}")

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

    noms = sorted({e.nom_groupe_celcat for e in entrees})
    evenements = []
    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {args.base} rôle lecture…")
            nav.connexion(page, base=args.base, role=nav.ROLE_LECTURE)
            for nom in noms:
                try:
                    gid = resoudre_groupe(page, nom)
                except Exception as exc:  # noqa: BLE001
                    print(f"  groupe introuvable {nom} : {exc}")
                    continue
                for brut in charger_edt(page, group_ids=[gid]):
                    evenements.append(evenement_depuis_rpc(brut, group_id=gid, groupe_nom=nom))

            plan = comparer(entrees, evenements, indice_semaine=indice)
            print(f"{len(plan.ambigu)} entrée(s) ambiguë(s)\n")
            sur_semaine = [ev for ev in evenements if sur_la_semaine(ev, indice)]
            for e in plan.ambigu:
                hits = [ev for ev in sur_semaine if _apparie(e, ev, indice)]
                print(
                    f"AMBIGU {e.nom_groupe_celcat:22} {e.course_code:8} "
                    f"j{e.jour} {e.heure_debut} (voulu salle={e.salle or '—'})"
                )
                salles = {h.salle for h in hits}
                genre = "VRAI DOUBLON (même salle)" if len(salles) < len(hits) or len(salles) == 1 else "salles différentes"
                print(f"  -> {len(hits)} hit(s), {genre}")
                for h in hits:
                    print(
                        f"     event_id={h.event_id:8} salle={h.salle or '—':10} "
                        f"cat={h.categorie:6} module_nom={h.module_nom!r} module_code={h.module_code!r} "
                        f"weeks_Y={h.weeks.count('Y')}"
                    )
                print()
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
