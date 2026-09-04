"""Vérifie le VRAI chemin de code (`suppression.py::supprimer_evenement`,
pas le script de capture ad-hoc) sur un canari frais — RPC pur, aucun clic
UI nécessaire une fois `methode_suppression` connue.

    python scripts/verifier_suppression_reelle_celcat.py --vpn
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
from cal_iut.celcat.rpc_config import charger_methodes  # noqa: E402
from cal_iut.celcat.suppression import supprimer_evenement  # noqa: E402


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
        self.appels.append({"methode": str(envoi.get("method") or ""), "params": envoi.get("params") or []})


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
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
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

    methodes = charger_methodes(RACINE / "data" / "config")
    if not methodes.methode_ecriture or not methodes.methode_suppression:
        raise MethodeEcritureAbsente("methodes vides")
    print(f"methode_ecriture={methodes.methode_ecriture!r} methode_suppression={methodes.methode_suppression!r}")

    entree = EntreeCelcat(
        session_id="canari-verif-suppression",
        semaine=99, jour=5, heure_debut="17:00", heure_fin="18:30",
        code_enseignant="", salle="", code_module="",
        type_seance=4, type_seance_nom="CM", groupe="",
        semestre="S1", lundi="2026-09-07", course_code="WR106-CANARI-VERIF",
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        journal = JournalRpc(page)
        try:
            print(f"Connexion {nav.BASE_ENTRAINEMENT} rôle {args.role}…")
            nav.connexion(page, base=nav.BASE_ENTRAINEMENT, role=args.role)

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
                print("  aucun groupe « BUT MMI » trouvé", file=sys.stderr)
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
                print("  aucun événement réel pour emprunter des ids", file=sys.stderr)
                return 2
            ids = {
                "module_id": reel.module_id, "room_id": reel.salle_id,
                "staff_id": reel.staff_id, "event_cat_id": reel.event_cat_id,
                "dept_id": reel.dept_id,
            }
            type_par_cat = {"[CM]": "CM", "[TD]": "TD", "[TP]": "TP"}
            entree_finale = replace(entree, type_seance_nom=type_par_cat.get(reel.categorie, "TD"))

            masque = masquer_semaine(longueur=54, indice=0)
            print("Création du canari…")
            resultat = creer_manquants(
                page, [entree_finale], group_id=gid, ids=ids, masque=masque,
                methode=methodes.methode_ecriture, base=nav.BASE_ENTRAINEMENT, production_autorisee=False,
            )
            if not resultat.crees:
                print(f"échec création : {resultat.echecs}", file=sys.stderr)
                return 2
            _sid, event_id = resultat.crees[0]
            print(f"  canari créé : event_id={event_id}")

            avant = {int(e.get("event_id") or e.get("id")) for e in charger_edt(page, group_ids=[gid]) if (e.get("event_id") or e.get("id")) is not None}
            print(f"  présent avant suppression : {event_id in avant}")

            print("Appel du VRAI suppression.py::supprimer_evenement()…")
            supprimer_evenement(
                page, event_id, group_id=gid, methode=methodes.methode_suppression,
                base=nav.BASE_ENTRAINEMENT, production_autorisee=False,
            )

            apres = {int(e.get("event_id") or e.get("id")) for e in charger_edt(page, group_ids=[gid]) if (e.get("event_id") or e.get("id")) is not None}
            disparu = event_id not in apres
            print(f"\n>>> event_id={event_id} {'SUPPRIMÉ (vrai chemin de code confirmé)' if disparu else 'TOUJOURS LÀ — problème dans le vrai chemin'}")
            return 0 if disparu else 1
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
