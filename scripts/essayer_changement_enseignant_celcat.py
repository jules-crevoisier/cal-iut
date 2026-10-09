"""Changer d'ENSEIGNANT dans Celcat retire-t-il bien l'ancien ? — sur URCA_FORMATION.

Tâche 19 (Kyllian Bresson, 09/10/2026) : un enseignant remplacé dans
cal-iut était AJOUTÉ dans Celcat à côté de l'ancien. `modification.py`
retire désormais l'ancien par la convention du signe moins, prouvée pour les
salles le 09/09/2026 (`capturer_changement_salle_celcat.py`) :

    {"-event_id": E, "-staff_id": S, "_type_": "Staff"}

Ce script vérifie la même chose pour les enseignants, EN PASSANT PAR LE
CODE DU ROBOT (`modifier_evenement`), pas par une charge écrite à la main :

  1. crée un évènement canari jetable avec l'enseignant A ;
  2. le modifie vers l'enseignant B avec `modifier_evenement` ;
  3. relit l'évènement : il doit porter B, et B seul ;
  4. supprime le canari, y compris en cas d'échec.

    python scripts/essayer_changement_enseignant_celcat.py --vpn

Code de sortie 0 si l'évènement porte exactement B, 1 sinon.

REFUS D'AGIR AILLEURS QUE SUR URCA_FORMATION.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import reseau
from cal_iut.celcat.ecriture import creer_manquants
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.mapping import EntreeCelcat
from cal_iut.celcat.modification import localiser_evenement, modifier_evenement
from cal_iut.celcat.rpc import (
    MethodeEcritureAbsente,
    charger_edt,
    masquer_semaine,
    supprimer_evenement_rpc,
)
from cal_iut.celcat.rpc_config import charger_methodes

INDICE_SEMAINE = 0


class JournalRpc:
    """Écoute les appels RPC pour récupérer le group_id que l'interface
    utilise réellement — les identifiants de la base d'entraînement ne sont
    pas ceux de la production, donc `celcat_groupes.yaml` ne sert à rien
    ici."""

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
        self.appels.append(
            {"methode": str(envoi.get("method") or ""), "params": envoi.get("params") or []}
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


def _enseignants_de(page, event_id: int, group_id: int) -> list[str]:
    """Les enseignants que Celcat porte RÉELLEMENT sur cet évènement, relus."""
    brut = localiser_evenement(page, event_id, group_ids=[group_id])
    staff = brut.get("staff") if isinstance(brut.get("staff"), list) else []
    return [
        str(s.get("name") or s.get("staff_id") or s.get("id") or "?")
        for s in staff if isinstance(s, dict)
    ]


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    args = parseur.parse_args()
    if args.base != nav.BASE_ENTRAINEMENT:
        print("refus : vérification uniquement sur URCA_FORMATION", file=sys.stderr)
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

    methodes = charger_methodes(RACINE / "data" / "config")
    if not methodes.methode_ecriture:
        raise MethodeEcritureAbsente("methode_ecriture vide — impossible de créer le canari")

    from playwright.sync_api import sync_playwright

    with reseau.acces(url, monter_le_vpn=args.vpn) as diag:
        if not diag.joignable:
            print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
            return 3

        with sync_playwright() as p:
            navigateur = p.chromium.launch(headless=True)
            page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
            journal = JournalRpc(page)
            event_id = 0
            try:
                print(f"Connexion {args.base} rôle {args.role}…")
                nav.connexion(page, base=args.base, role=args.role)

                _ouvrir_groupes(page)
                nav.filtrer(page, "BUT MMI")
                page.wait_for_timeout(1500)
                textes = [f["texte"] for f in nav.feuilles(page) if "BUT MMI" in f["texte"]]
                nom_groupe = next((t for t in textes if "BUT MMI" in t), None)
                if not nom_groupe:
                    print("aucun groupe « BUT MMI » sur la base d'entraînement", file=sys.stderr)
                    return 2
                avant_ouverture = len(journal.appels)
                nav.double_cliquer_texte(page, nom_groupe)
                nav.attendre_texte(page, "Semaines de l'emploi du temps", delai=40)
                page.wait_for_timeout(1500)
                load = next(
                    (a for a in journal.appels[avant_ouverture:] if a["methode"] == "udlTimetables.load"),
                    None,
                )
                vus = (load.get("params") or [{}])[0].get("GroupIDs") if load else None
                if not vus:
                    print("group_id introuvable dans les appels udlTimetables.load", file=sys.stderr)
                    return 2
                gid = int(vus[0])
                print(f"  group_id={gid}")

                evenements = [
                    evenement_depuis_rpc(b, group_id=gid, groupe_nom=nom_groupe)
                    for b in charger_edt(page, group_ids=[gid])
                ]
                # DEUX enseignants distincts : A pour créer, B pour remplacer.
                enseignants: list[tuple[int, str]] = []
                for ev in evenements:
                    if ev.staff_id and ev.staff_id not in [e[0] for e in enseignants]:
                        enseignants.append((ev.staff_id, ev.enseignant))
                if len(enseignants) < 2:
                    print(f"il faut deux enseignants distincts, trouvé {len(enseignants)}", file=sys.stderr)
                    return 2
                (id_a, nom_a), (id_b, nom_b) = enseignants[0], enseignants[1]
                modele = next(
                    (e for e in evenements if e.module_id and e.event_cat_id and e.dept_id and e.salle_id),
                    None,
                )
                if modele is None:
                    print("aucun évènement complet pour emprunter des ids", file=sys.stderr)
                    return 2
                print(f"  enseignant A = {nom_a} (id={id_a})")
                print(f"  enseignant B = {nom_b} (id={id_b})")

                ids = {
                    "module_id": modele.module_id, "room_id": modele.salle_id,
                    "staff_id": id_a, "event_cat_id": modele.event_cat_id,
                    "dept_id": modele.dept_id,
                }
                entree = EntreeCelcat(
                    session_id="canari-enseignant",
                    semaine=99, jour=5, heure_debut="17:00", heure_fin="18:30",
                    code_enseignant="", salle=modele.salle, code_module="",
                    # Type vide : la catégorie est empruntée au modèle de la
                    # base d'entraînement, dont les ids ne sont pas ceux de
                    # la production (le filet « CM = 430 » ne s'y applique pas).
                    type_seance=None, type_seance_nom="", groupe="",
                    semestre="S1", lundi="2026-09-07", course_code="CANARI-ENSEIGNANT",
                )
                masque = masquer_semaine(longueur=54, indice=INDICE_SEMAINE)

                print("Création du canari avec l'enseignant A…")
                resultat = creer_manquants(
                    page, [entree], group_id=gid, ids=ids, masque=masque,
                    methode=methodes.methode_ecriture, base=args.base,
                    production_autorisee=False,
                )
                if not resultat.crees:
                    print(f"échec création : {resultat.echecs}", file=sys.stderr)
                    return 2
                _sid, event_id = resultat.crees[0]
                print(f"  canari créé : event_id={event_id}, enseignants = {_enseignants_de(page, event_id, gid)}")

                print("Modification vers l'enseignant B (code du robot)…")
                modifier_evenement(
                    page, entree, event_id=event_id, group_id=gid,
                    ids={**ids, "staff_id": id_b}, masque=masque,
                    methode=methodes.methode_ecriture, base=args.base,
                )
                apres = _enseignants_de(page, event_id, gid)
                print(f"  enseignants après modification : {apres}")
                ok = apres == [nom_b] or (len(apres) == 1 and str(id_b) in apres)
                print("\n" + "=" * 60)
                print("OK : un seul enseignant, le bon." if ok else "ÉCHEC : l'ancien enseignant n'a pas été retiré.")
                print("=" * 60)
                return 0 if ok else 1
            finally:
                if event_id:
                    print(f"\nSuppression du canari event_id={event_id}…")
                    try:
                        supprimer_evenement_rpc(page, event_id, methode=methodes.methode_suppression)
                        print("  canari supprimé")
                    except Exception as exc:  # noqa: BLE001
                        print(f"  ATTENTION : canari NON supprimé ({exc}) — à retirer à la main")
                try:
                    nav.deconnexion(page)
                except Exception:  # noqa: BLE001, S110
                    pass
                navigateur.close()


if __name__ == "__main__":
    raise SystemExit(principal())
