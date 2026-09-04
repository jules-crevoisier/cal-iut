"""Prouve la méthode RPC de SUPPRESSION Celcat, sur URCA_FORMATION.

Retour utilisateur 05/09/2026 : « la suppression est simple il faut
cliquer sur la séance et il y a un bouton supprimer en haut du planning »
— UN SEUL clic (pas un double-clic pour ouvrir l'inspecteur) sélectionne
la séance, l'icône "supprimer" de la barre agit directement dessus.

Étapes : crée un événement CANARI jetable via le chemin RPC déjà prouvé
(`ecriture.creer_manquants`), le repère sur la grille, clique une fois
dessus (sélection), clique l'icône "supprimer" de la barre, note la
méthode JSON-RPC déclenchée, puis RELIT l'EDT pour confirmer que
l'événement a bien disparu.

    python scripts/capturer_suppression_celcat.py --vpn
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402
from cal_iut.celcat.ecriture import creer_manquants  # noqa: E402
from cal_iut.celcat.lecture import evenement_depuis_rpc  # noqa: E402
from cal_iut.celcat.mapping import EntreeCelcat  # noqa: E402
from cal_iut.celcat.rpc import MethodeEcritureAbsente, charger_edt, masquer_semaine  # noqa: E402

IGNORER = {"system.getOptions", "login.getRoles", "login.login", "udlResources.load", "udlTimetables.load"}
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
        try:
            corps = nav.lire_reponse(reponse.text())
        except Exception:  # noqa: BLE001
            corps = {}
        self.appels.append({
            "methode": str(envoi.get("method") or ""),
            "params": envoi.get("params") or [],
            "erreur": corps.get("error") if isinstance(corps, dict) else None,
        })


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


def _methode_ecriture() -> str:
    chemin = RACINE / "data" / "config" / "celcat_rpc.yaml"
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("methode_ecriture:"):
            return ligne.split(":", 1)[1].strip()
    return ""


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    args = parseur.parse_args()
    if args.base != nav.BASE_ENTRAINEMENT:
        print("refus : capture uniquement sur URCA_FORMATION", file=sys.stderr)
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

    methode_ecriture = _methode_ecriture()
    if not methode_ecriture:
        raise MethodeEcritureAbsente("methode_ecriture vide — impossible de créer le canari")

    entree = EntreeCelcat(
        session_id="canari-suppression",
        semaine=99, jour=5, heure_debut="17:00", heure_fin="18:30",
        code_enseignant="", salle="", code_module="",
        type_seance=4, type_seance_nom="CM", groupe="",
        semestre="S1", lundi="2026-09-07", course_code="WR106-CANARI-SUPPRESSION",
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        journal = JournalRpc(page)
        try:
            print(f"Connexion {args.base} rôle {args.role}…")
            nav.connexion(page, base=args.base, role=args.role)

            print("Résolution du groupe (recherche UI, pas le cache production)…")
            _ouvrir_groupes(page)
            nav.filtrer(page, "BUT MMI")
            page.wait_for_timeout(1500)
            textes = [f["texte"] for f in nav.feuilles(page) if "BUT MMI" in f["texte"]]
            nom_groupe = next(
                (t for t in textes if "TD" in t and "BUT MMI" in t),
                next((t for t in textes if "BUT MMI" in t), None),
            )
            if not nom_groupe:
                print(f"  aucun groupe « BUT MMI » trouvé sur {args.base}", file=sys.stderr)
                return 2
            print(f"  groupe choisi : {nom_groupe!r}")
            avant_ouverture = len(journal.appels)
            nav.double_cliquer_texte(page, nom_groupe)
            nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
            page.wait_for_timeout(1500)
            load_call = next(
                (a for a in journal.appels[avant_ouverture:] if a["methode"] == "udlTimetables.load"),
                None,
            )
            group_ids_vus = (load_call.get("params") or [{}])[0].get("GroupIDs") if load_call else None
            if not group_ids_vus:
                print("  group_id introuvable dans les appels udlTimetables.load", file=sys.stderr)
                return 2
            gid = int(group_ids_vus[0])
            print(f"  group_id={gid}")

            existants = [evenement_depuis_rpc(b, group_id=gid, groupe_nom=nom_groupe) for b in charger_edt(page, group_ids=[gid])]
            reel = next((e for e in existants if e.module_id and e.staff_id and e.salle_id and e.event_cat_id), None)
            if reel is None:
                print("  aucun événement réel dans ce groupe pour emprunter des ids", file=sys.stderr)
                return 2
            print(f"  emprunté à event_id={reel.event_id} : module={reel.module_nom!r} cat={reel.categorie!r}")
            ids = {
                "module_id": reel.module_id, "room_id": reel.salle_id,
                "staff_id": reel.staff_id, "event_cat_id": reel.event_cat_id,
                "dept_id": reel.dept_id,
            }
            type_par_cat = {"[CM]": "CM", "[TD]": "TD", "[TP]": "TP"}
            entree = replace(entree, type_seance_nom=type_par_cat.get(reel.categorie, "TD"))

            INDICE_SEMAINE = 0
            masque = masquer_semaine(longueur=54, indice=INDICE_SEMAINE)
            print("Création du canari…")
            resultat = creer_manquants(
                page, [entree], group_id=gid, ids=ids, masque=masque,
                methode=methode_ecriture, base=args.base, production_autorisee=False,
            )
            if not resultat.crees:
                print(f"échec création : {resultat.echecs}", file=sys.stderr)
                return 2
            _sid, event_id = resultat.crees[0]
            print(f"  canari créé : event_id={event_id}")

            print("Navigation vers la semaine du canari…")
            cellules = nav.cellules_semaines(page)
            if len(cellules) <= INDICE_SEMAINE:
                print(f"  seulement {len(cellules)} cellule(s) — abandon", file=sys.stderr)
                return 2
            cible = cellules[INDICE_SEMAINE]
            page.mouse.click(cible["x"], cible["y"])
            page.wait_for_timeout(2000)
            nav.cliquer_icone_barre(page, "rafraichir")
            page.wait_for_timeout(2000)

            # Vue confirmée par capture d'écran (05/09/2026) : le canari
            # (vendredi 17h-18h30, colonne la plus à droite) est le bloc le
            # plus BAS et le plus à DROITE de la grille — pas besoin de
            # scanner/deviner, on prend directement ce bloc-là.
            page.mouse.move(*nav.SUR_LA_LISTE)
            page.wait_for_timeout(400)
            blocs = page.evaluate(_JS_BLOCS, GRILLE)
            print(f"  {len(blocs)} bloc(s) coloré(s) sur la grille")
            cible_bloc = max(blocs, key=lambda b: (b["y"], b["x"]))
            print(f"  bloc canari (bas-droite) : ({cible_bloc['x']}, {cible_bloc['y']})")

            print("  clic simple (sélection, pas de double-clic)…")
            page.mouse.click(cible_bloc["x"], cible_bloc["y"])
            page.wait_for_timeout(1200)

            capture = RACINE / "scratch_grille_selection.png"
            page.screenshot(path=str(capture))
            print(f"  capture après sélection : {capture}")

            print("  clic sur l'icône Supprimer…")
            avant_appels = len(journal.appels)
            nav.cliquer_icone_barre(page, "supprimer")
            page.wait_for_timeout(1500)
            textes_ecran = [f["texte"] for f in nav.feuilles(page)]
            for candidat in ("Oui", "Yes", "Confirmer", "OK", "Supprimer"):
                if candidat in textes_ecran:
                    print(f"  confirmation « {candidat} » détectée, clic…")
                    for f in nav.feuilles(page):
                        if f["texte"] == candidat:
                            page.mouse.click(f["x"], f["y"])
                            break
                    page.wait_for_timeout(1500)
                    break
            page.wait_for_timeout(2500)

            nouveaux = [a for a in journal.appels[avant_appels:] if a["methode"] and a["methode"] not in IGNORER]
            print(f"  {len(nouveaux)} appel(s) RPC après le clic Supprimer :")
            for a in nouveaux:
                print(f"    méthode={a['methode']!r} erreur={a['erreur']!r}")
                print(f"    params={json.dumps(a['params'], ensure_ascii=False)}")

            print("Vérification : rechargement EDT, l'event_id doit avoir disparu…")
            apres = {
                int(e.get("event_id") or e.get("id"))
                for e in charger_edt(page, group_ids=[gid])
                if (e.get("event_id") or e.get("id")) is not None
            }
            disparu = int(event_id) not in apres
            print(f"  event_id={event_id} {'a bien disparu' if disparu else 'EST TOUJOURS LÀ'}")

            if nouveaux and disparu:
                print(f"\n>>> methode_suppression confirmée : {nouveaux[-1]['methode']}")
            elif not disparu:
                print(
                    f"\n>>> ATTENTION : le canari (event_id={event_id}) est TOUJOURS EN FORMATION, "
                    "à supprimer à la main dans l'UI Celcat.",
                    file=sys.stderr,
                )
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
