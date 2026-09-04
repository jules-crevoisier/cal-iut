"""Teste la réaffectation de SALLE (changement de ressource, pas jour/heure)
sur URCA_FORMATION, à la lumière de la convention découverte le 05/09/2026
pour la suppression (`{"-champ_id": valeur}` dans un tableau de
sous-objets = « retirer cette association », par opposition à ajouter un
sous-objet normal = « ajouter cette association »).

Hypothèse testée : pour changer la salle d'un événement, il faut peut-être
un tableau `rooms` à DEUX entrées — `{"-room_id": ancien}` (retire
l'ancienne association) ET `{"room_id": nouveau, ...}` (ajoute la
nouvelle) — plutôt qu'un tableau à une seule entrée portant le nouvel id
(déjà essayé, sans effet, cf. docs/CELCAT.md).

    python scripts/tester_reaffectation_salle_celcat.py --vpn
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
from cal_iut.celcat.ecriture import creer_manquants  # noqa: E402
from cal_iut.celcat.lecture import evenement_depuis_rpc  # noqa: E402
from cal_iut.celcat.mapping import EntreeCelcat  # noqa: E402
from cal_iut.celcat.modification import localiser_evenement  # noqa: E402
from cal_iut.celcat.rpc import MethodeEcritureAbsente, charger_edt, enregistrer_evenement, masquer_semaine  # noqa: E402
from cal_iut.celcat.rpc_config import charger_methodes  # noqa: E402


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
    if not methodes.methode_ecriture:
        raise MethodeEcritureAbsente("methode_ecriture vide")

    entree = EntreeCelcat(
        session_id="canari-reaffectation-salle",
        semaine=99, jour=5, heure_debut="17:00", heure_fin="18:30",
        code_enseignant="", salle="", code_module="",
        type_seance=4, type_seance_nom="CM", groupe="",
        semestre="S1", lundi="2026-09-07", course_code="WR106-CANARI-SALLE",
    )

    from dataclasses import replace
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
        journal = JournalRpc(page)
        try:
            print(f"Connexion {nav.BASE_ENTRAINEMENT} rôle {args.role}…")
            nav.connexion(page, base=nav.BASE_ENTRAINEMENT, role=args.role)

            _ouvrir_groupes(page)
            nav.filtrer(page, "BUT MMI")
            page.wait_for_timeout(1500)
            textes = [f["texte"] for f in nav.feuilles(page) if "BUT MMI" in f["texte"]]
            nom_groupe = next(
                (t for t in textes if "TD" in t and "BUT MMI" in t),
                next((t for t in textes if "BUT MMI" in t), None),
            )
            avant_ouverture = len(journal.appels)
            nav.double_cliquer_texte(page, nom_groupe)
            nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
            page.wait_for_timeout(1500)
            load_call = next(
                (a for a in journal.appels[avant_ouverture:] if a["methode"] == "udlTimetables.load"),
                None,
            )
            gid = int((load_call.get("params") or [{}])[0].get("GroupIDs")[0])
            print(f"  group_id={gid}")

            existants = [evenement_depuis_rpc(b, group_id=gid, groupe_nom=nom_groupe) for b in charger_edt(page, group_ids=[gid])]
            # Deux salles RÉELLES et DISTINCTES pour tester un vrai changement.
            candidats_salle = {e.salle_id: e for e in existants if e.salle_id and e.module_id and e.staff_id and e.event_cat_id}
            if len(candidats_salle) < 2:
                print("  pas assez de salles distinctes dans ce groupe pour tester", file=sys.stderr)
                return 2
            salles_distinctes = list(candidats_salle.items())
            (salle_a_id, reel), (salle_b_id, _) = salles_distinctes[0], salles_distinctes[1]
            print(f"  salle de départ : {salle_a_id} ({reel.salle}) -> cible : {salle_b_id}")

            ids = {
                "module_id": reel.module_id, "room_id": salle_a_id,
                "staff_id": reel.staff_id, "event_cat_id": reel.event_cat_id,
                "dept_id": reel.dept_id,
            }
            type_par_cat = {"[CM]": "CM", "[TD]": "TD", "[TP]": "TP"}
            entree_finale = replace(entree, type_seance_nom=type_par_cat.get(reel.categorie, "TD"))
            masque = masquer_semaine(longueur=54, indice=0)
            print("Création du canari (salle A)…")
            resultat = creer_manquants(
                page, [entree_finale], group_id=gid, ids=ids, masque=masque,
                methode=methodes.methode_ecriture, base=nav.BASE_ENTRAINEMENT, production_autorisee=False,
            )
            if not resultat.crees:
                print(f"échec création : {resultat.echecs}", file=sys.stderr)
                return 2
            _sid, event_id = resultat.crees[0]
            print(f"  canari créé : event_id={event_id}, salle={salle_a_id}")

            print("Localisation fraîche + tentative de bascule vers salle B avec {'-room_id': ancien} + {'room_id': nouveau}…")
            brut = localiser_evenement(page, event_id, group_ids=[gid])
            fusionne = dict(brut)
            ancienne_association = dict((brut.get("rooms") or [{}])[0])
            ancienne_association["-room_id"] = ancienne_association.pop("room_id", salle_a_id)
            fusionne["rooms"] = [
                ancienne_association,
                {"room_id": salle_b_id, "event_id": event_id, "_type_": "Resource"},
            ]
            avant_appels = len(journal.appels)
            retour = enregistrer_evenement(page, fusionne, methode=methodes.methode_ecriture)
            print(f"  retour save : {json.dumps(retour, ensure_ascii=False)[:500]}")
            nouveaux = [a for a in journal.appels[avant_appels:] if a["methode"] == methodes.methode_ecriture]
            for a in nouveaux:
                print(f"  requête envoyée : {json.dumps(a['params'], ensure_ascii=False)}")

            print("Vérification (relecture fraîche)…")
            relu = localiser_evenement(page, event_id, group_ids=[gid])
            salle_id_relu = (relu.get("rooms") or [{}])[0].get("room_id")
            print(f"\n>>> salle après tentative : {salle_id_relu} (visée : {salle_b_id}) — {'RÉUSSI' if salle_id_relu == salle_b_id else 'ÉCHEC, toujours sans effet'}")

            print("Nettoyage du canari…")
            from cal_iut.celcat.suppression import supprimer_evenement
            supprimer_evenement(
                page, event_id, group_id=gid, methode=methodes.methode_suppression,
                base=nav.BASE_ENTRAINEMENT, production_autorisee=False,
            )
            print("  canari supprimé")
            return 0
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
