"""Comment REMPLACE-t-on la salle d'un évènement Celcat ? — expérience sur URCA_FORMATION.

Constaté en production le 08/09/2026 : nos corrections de salle AJOUTENT la
nouvelle salle au lieu de retirer l'ancienne.

    WR115-S1-TD-1-but1-td-cd   cal-iut H.101   Celcat: H.007 + H.101
    WR314D-S3-TP-1-tp-a        cal-iut H.007   Celcat: H.005 + H.007

Kyllian Bresson avait décrit le mécanisme côté interface le jour même : une
salle glissée dans l'onglet Salle s'AJOUTE ; il faut maintenir Maj, ou
cliquer sur le bouton de retrait, pour qu'elle remplace.

CE QUE FAIT CE SCRIPT. Il ne devine pas : il essaie. Un évènement canari
jetable est créé sur la base d'ENTRAÎNEMENT avec une salle A, puis chaque
charge utile candidate est envoyée et le résultat RELU depuis Celcat. La
bonne est celle après laquelle l'évènement porte exactement une salle, la B.

    python scripts/capturer_changement_salle_celcat.py --vpn

CANDIDATES ÉPROUVÉES, de la plus probable à la moins :

  1. `rooms: [B]` — ce que le code fait aujourd'hui. Attendu : deux salles
     (c'est le défaut qu'on reproduit, et le reproduire est la première
     preuve que l'expérience est valide).
  2. `rooms: [{-room_id: A}, B]` — la convention du signe moins, DÉJÀ
     PROUVÉE pour supprimer un évènement (`rpc.supprimer_evenement_rpc`,
     canari du 05/09/2026). C'est l'hypothèse principale.
  3. `rooms: [B avec l'id de l'association A]` — remplacer la ligne
     existante plutôt que d'en insérer une.
  4. `rooms: []` puis `rooms: [B]` — vider d'abord, poser ensuite.

REFUS D'AGIR AILLEURS QUE SUR URCA_FORMATION. Le script s'arrête si on lui
passe une autre base : l'expérience consiste précisément à écrire des choses
dont on ignore l'effet, et c'est exactement ce qu'il ne faut pas faire sur le
planning des étudiants.

Le canari est supprimé à la fin, y compris si l'expérience échoue.
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
from cal_iut.celcat.modification import localiser_evenement
from cal_iut.celcat.rpc import (
    MethodeEcritureAbsente,
    charger_edt,
    enregistrer_evenement,
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


def _salles_de(page, event_id: int, group_id: int) -> list[str]:
    """Les salles que Celcat porte RÉELLEMENT sur cet évènement, relues."""
    brut = localiser_evenement(page, event_id, group_ids=[group_id])
    rooms = brut.get("rooms") if isinstance(brut.get("rooms"), list) else []
    noms = []
    for item in rooms:
        if isinstance(item, dict):
            noms.append(str(item.get("name") or item.get("room_id") or item.get("id") or "?"))
    return noms


def _candidates(brut_initial: dict, salle_a: dict, id_b: int, reel_b: dict, event_id: int) -> list[tuple[str, list]]:
    """Les formes à essayer pour `rooms`, dans l'ordre de vraisemblance."""
    b_complet = {
        "room_id": id_b,
        "event_id": event_id,
        "dept_id": reel_b.get("dept_id"),
        "unique_name": reel_b.get("unique_name"),
        "name": reel_b.get("name"),
        "weeks": None,
    }
    id_association = salle_a.get("id")
    return [
        ("1. rooms=[B]  (comportement actuel)", [dict(b_complet)]),
        (
            "2. rooms=[{-room_id: A}, B]  (convention du signe moins)",
            [{"-room_id": salle_a.get("room_id") or salle_a.get("id"), "_type_": "Room"}, dict(b_complet)],
        ),
        (
            "3. rooms=[B en réutilisant l'id de l'association A]",
            [{**b_complet, "id": id_association}] if id_association is not None else [],
        ),
        ("4. rooms=[]  (vider, puis reposer B au tour suivant)", []),
    ]


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_ENTRAINEMENT)
    parseur.add_argument("--role", default=nav.ROLE_ECRITURE)
    args = parseur.parse_args()
    if args.base != nav.BASE_ENTRAINEMENT:
        print("refus : expérience uniquement sur URCA_FORMATION", file=sys.stderr)
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
            gid = 0
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

                # `charger_edt` exige une LISTE de groupes : le serveur refuse
                # un filtre nul (« expecting an array but received a variant »).
                # On prend l'identifiant que l'interface vient elle-même
                # d'utiliser.
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

                bruts = charger_edt(page, group_ids=[gid])
                if not bruts:
                    print("emploi du temps vide — impossible d'emprunter des ids", file=sys.stderr)
                    return 2
                evenements = [evenement_depuis_rpc(b, group_id=gid, groupe_nom=nom_groupe) for b in bruts]

                # DEUX salles distinctes sont nécessaires : A pour créer le
                # canari, B pour tenter de la remplacer. Sans deux salles
                # réelles, l'expérience ne prouve rien.
                salles = []
                for ev in evenements:
                    sid = ev.salle_id
                    if sid and sid not in [s["id"] for s in salles]:
                        salles.append({"id": sid, "nom": ev.salle, "brut": ev.brut})
                if len(salles) < 2:
                    print(f"il faut deux salles distinctes, trouvé {len(salles)}", file=sys.stderr)
                    return 2
                salle_a, salle_b = salles[0], salles[1]
                modele = next(
                    (e for e in evenements if e.module_id and e.event_cat_id and e.dept_id), None
                )
                if modele is None:
                    print("aucun évènement complet pour emprunter des ids", file=sys.stderr)
                    return 2
                print(f"  salle A = {salle_a['nom']} (id={salle_a['id']})")
                print(f"  salle B = {salle_b['nom']} (id={salle_b['id']})")

                ids = {
                    "module_id": modele.module_id, "room_id": salle_a["id"],
                    "staff_id": modele.staff_id, "event_cat_id": modele.event_cat_id,
                    "dept_id": modele.dept_id,
                }
                entree = EntreeCelcat(
                    session_id="canari-salle",
                    semaine=99, jour=5, heure_debut="17:00", heure_fin="18:30",
                    code_enseignant="", salle=salle_a["nom"], code_module="",
                    type_seance=4, type_seance_nom="CM", groupe="",
                    semestre="S1", lundi="2026-09-07", course_code="CANARI-SALLE",
                )
                masque = masquer_semaine(longueur=54, indice=INDICE_SEMAINE)

                print("Création du canari avec la salle A…")
                resultat = creer_manquants(
                    page, [entree], group_id=gid, ids=ids, masque=masque,
                    methode=methodes.methode_ecriture, base=args.base,
                    production_autorisee=False,
                )
                if not resultat.crees:
                    print(f"échec création : {resultat.echecs}", file=sys.stderr)
                    return 2
                _sid, event_id = resultat.crees[0]
                print(f"  canari créé : event_id={event_id}, salles = {_salles_de(page, event_id, gid)}")

                brut_initial = localiser_evenement(page, event_id, group_ids=[gid])
                sous_objet_a = (brut_initial.get("rooms") or [{}])[0]
                reel_b = dict(salle_b["brut"].get("rooms", [{}])[0])

                gagnante = None
                for libelle, rooms in _candidates(brut_initial, sous_objet_a, salle_b["id"], reel_b, event_id):
                    if not rooms and "vider" not in libelle:
                        print(f"\n{libelle} — non applicable (pas d'id d'association), passée")
                        continue
                    print(f"\n{libelle}")
                    charge = dict(localiser_evenement(page, event_id, group_ids=[gid]))
                    charge["rooms"] = rooms
                    try:
                        enregistrer_evenement(page, charge, methode=methodes.methode_ecriture)
                    except Exception as exc:  # noqa: BLE001
                        print(f"   -> refusé par Celcat : {exc}")
                        continue
                    apres = _salles_de(page, event_id, gid)
                    print(f"   -> salles après écriture : {apres}")
                    if len(apres) == 1 and str(salle_b["id"]) in str(apres) or (
                        len(apres) == 1 and apres[0] == salle_b["nom"]
                    ):
                        gagnante = libelle
                        print("   *** EXACTEMENT UNE SALLE, LA BONNE ***")
                        break
                    # Remise en état pour que la candidate suivante reparte
                    # du même point : sans ça, la deuxième mesure porterait
                    # sur un évènement déjà abîmé par la première.
                    remise = dict(localiser_evenement(page, event_id, group_ids=[gid]))
                    remise["rooms"] = list(brut_initial.get("rooms") or [])
                    try:
                        enregistrer_evenement(page, remise, methode=methodes.methode_ecriture)
                    except Exception as exc:  # noqa: BLE001
                        print(f"   (remise en état impossible : {exc})")

                print("\n" + "=" * 60)
                if gagnante:
                    print(f"CONVENTION TROUVÉE : {gagnante}")
                else:
                    print("AUCUNE candidate ne laisse une seule salle.")
                    print("Le remplacement passe probablement par un appel SÉPARÉ")
                    print("(retrait de l'association, puis ajout) — à capturer depuis")
                    print("l'interface avec le bouton de retrait décrit par Kyllian.")
                print("=" * 60)
                return 0 if gagnante else 1
            finally:
                if event_id:
                    print(f"\nSuppression du canari event_id={event_id}…")
                    try:
                        supprimer_evenement_rpc(
                            page, event_id, methode=methodes.methode_suppression
                        )
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
