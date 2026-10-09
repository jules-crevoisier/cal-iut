"""Relève ce que contient Celcat et le dépose pour l'interface — LECTURE SEULE.

Retour utilisateur 08/09/2026 : « on peut pas faire une vue qui nous permette
de consulter Celcat directement depuis l'outil, avec un bouton qui permette
de refresh quand l'on veut ? », puis, sur la cadence : « l'instantané sur
Celcat c'est un peu chiant pour la libération du VPN, on peut mettre toutes
les 2h et on peut fetch au click ».

Pourquoi ce script vit ici et pas dans l'API. Le conteneur qui sert
l'application n'a ni VPN ni navigateur : la passerelle URCA pousse un tunnel
COMPLET, donc l'y monter détournerait tout son trafic sortant et couperait
le site public (cf. `celcat/reseau.py`). Seul ce sidecar peut lire Celcat ;
il dépose son relevé dans le volume partagé, et l'API le sert tel quel.

N'écrit RIEN dans Celcat : aucun import du module de modification ou de
suppression, et connexion en rôle LECTURE.

Ne relève que si c'est dû (plus de deux heures, ou quelqu'un a cliqué sur
« Rafraîchir ») : appelé à chaque tour de la boucle du sidecar, il se termine
sans toucher au réseau le reste du temps. C'est ce qui garde le VPN
disponible pour l'équipe — il est partagé avec le compte Celcat, et une
session tenue est une session que personne d'autre ne peut ouvrir.

    python scripts/celcat_instantane.py --vpn
    python scripts/celcat_instantane.py --vpn --forcer   # ignore la cadence

Le même passage relève aussi les OCCUPATIONS HORS MMI des salles et des
enseignants surveillés (`celcat/occupations.py`, demande du 01/10/2026) :
même session, même cadence de deux heures, même bouton « Relire » (drapeau
`celcat_occupations_demande.json`). Un échec de ce relevé-là ne fait pas
échouer l'instantané : il est noté dans son propre fichier.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import occupations
from cal_iut.celcat import reseau
from cal_iut.celcat.ecriture import resoudre_groupe
from cal_iut.celcat.etat import worker_en_pause
from cal_iut.celcat.instantane import consommer_demande, enregistrer, releve_du
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.rpc import charger_edt


def _groupes_a_relever() -> list[str]:
    """Tous les groupes Celcat connus (`data/config/celcat_groupes.yaml`).

    Lus depuis le fichier plutôt que devinés : un nom deviné ne produit pas
    une erreur mais un groupe INTROUVABLE, donc un relevé silencieusement
    incomplet — et une comparaison qui annoncerait « absent de Celcat » des
    séances qui y sont. Ce fichier est déjà la source des identifiants pour
    l'écriture (`ecriture.py`), les deux côtés voient donc le même monde.
    """
    import yaml

    chemin = RACINE / "data" / "config" / "celcat_groupes.yaml"
    if not chemin.exists():
        return []
    data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    return sorted(str(k) for k in data) if isinstance(data, dict) else []


def _args_resolution(url: str) -> list[str]:
    """Chromium n'utilise pas le résolveur du système : sur un poste Windows
    il ignore le DNS poussé par le VPN et rend ERR_NAME_NOT_RESOLVED sur un
    nom que Python résout au même instant. On lui impose donc la résolution
    déjà validée par le contrôle d'accès."""
    import time

    hote = urlparse(url if "//" in url else f"https://{url}").hostname or ""
    if not hote:
        return []
    for _ in range(5):
        try:
            adresse = socket.getaddrinfo(hote, 443, proto=socket.IPPROTO_TCP)[0][4][0]
        except OSError:
            time.sleep(1.5)
            continue
        return [f"--host-resolver-rules=MAP {hote} {adresse}"]
    return []


def _relever(page) -> tuple[list[dict], list[str]]:
    evenements: list[dict] = []
    groupes_lus: list[str] = []
    for nom in _groupes_a_relever():
        try:
            gid = resoudre_groupe(page, nom)
        except Exception as exc:  # noqa: BLE001
            print(f"  groupe « {nom} » introuvable : {exc}", file=sys.stderr)
            continue
        groupes_lus.append(nom)
        for brut in charger_edt(page, group_ids=[gid]):
            ev = evenement_depuis_rpc(brut, group_id=gid, groupe_nom=nom)
            evenements.append(
                {
                    "event_id": ev.event_id,
                    "groupe": nom,
                    "jour": brut.get("day_of_week"),
                    "heure_debut": ev.heure_debut,
                    "heure_fin": ev.heure_fin,
                    "salle": ev.salle,
                    # TOUTES les salles : un cours posé sur deux salles à la
                    # fois n'était pas visible, le relevé n'en gardant qu'une
                    # (signalé par Kyllian Bresson le 08/09/2026).
                    "salles": ev.salles,
                    "categorie": ev.categorie,
                    "enseignant": ev.enseignant,
                    # TOUS les enseignants, noms et codes Celcat : un
                    # enseignant remplacé restait à côté du nouveau
                    # (tâche 19, 09/10/2026).
                    "enseignants": ev.enseignants,
                    "enseignants_codes": ev.enseignants_codes,
                    "module": ev.module_nom,
                    "semaine": ev.indice_semaine,
                    "protected": ev.protected,
                }
            )
    return evenements, groupes_lus


occupations_ecrites = False


def _relever_occupations(page, cfg) -> None:
    """Occupations hors MMI, dans la MÊME session que l'instantané. Un échec
    est noté dans le fichier des occupations (qui garde le relevé précédent)
    et n'interrompt pas l'instantané."""
    global occupations_ecrites
    try:
        res = occupations.executer(page, cfg=cfg, ecrire_fichier=True, base=nav.BASE_PRODUCTION,
                                   sortie=lambda _ligne: None)
        occupations_ecrites = True
        print(f"occupations hors MMI : {len(res.evenements)} occurrence(s), "
              f"{len(res.ressources)} ressource(s), {res.requetes} requête(s)")
    except Exception as exc:  # noqa: BLE001
        occupations.enregistrer_echec(f"{type(exc).__name__} : {exc}")
        occupations_ecrites = True
        print(f"occupations hors MMI : ÉCHEC {exc}", file=sys.stderr)


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--forcer", action="store_true", help="ignore la cadence de 2 h")
    args = parseur.parse_args()

    # Le worker peut être mis en PAUSE depuis l'interface : le VPN et le
    # compte Celcat sont partagés avec l'équipe, et un cycle toutes les 90
    # secondes empêche quiconque d'ouvrir une session durable. La pause ne
    # touche PAS à la file d'attente — elle reprendra telle quelle.
    if worker_en_pause():
        print("worker en pause — VPN non monté")
        return 0

    faire_instantane = args.forcer or releve_du()
    cfg_occupations = occupations.charger_config(RACINE / "data" / "config")
    faire_occupations = cfg_occupations.actif and (args.forcer or occupations.releve_du(cfg_occupations))
    if not faire_instantane and not faire_occupations:
        print("instantané encore frais — rien à faire")
        return 0
    if faire_instantane:
        consommer_demande()
    if faire_occupations:
        occupations.consommer_demande()

    try:
        from dotenv import load_dotenv

        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    url = os.environ.get("CELCAT_URL", "")
    if not url:
        print("CELCAT_URL absent", file=sys.stderr)
        return 2

    from playwright.sync_api import sync_playwright

    try:
        # `reseau.acces` rend le tunnel en sortant : un relevé ne doit pas
        # garder la session du compte partagé (cf. `celcat/reseau.py`).
        with reseau.acces(url, monter_le_vpn=args.vpn) as diag:
            if not diag.joignable:
                if faire_instantane:
                    enregistrer([], groupes=[], erreur=f"Celcat injoignable : {diag.detail}")
                if faire_occupations:
                    occupations.enregistrer_echec(f"Celcat injoignable : {diag.detail}")
                print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
                return 3
            with sync_playwright() as p:
                navigateur = p.chromium.launch(headless=True, args=_args_resolution(url))
                page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
                try:
                    print(f"Connexion {nav.BASE_PRODUCTION} rôle {nav.ROLE_LECTURE} (lecture)…")
                    nav.connexion(page, base=nav.BASE_PRODUCTION, role=nav.ROLE_LECTURE)
                    if faire_instantane:
                        evenements, groupes_lus = _relever(page)
                    if faire_occupations:
                        _relever_occupations(page, cfg_occupations)
                finally:
                    try:
                        nav.deconnexion(page)
                    except Exception:  # noqa: BLE001, S110
                        pass
                    navigateur.close()
    except Exception as exc:  # noqa: BLE001
        # L'échec est ENREGISTRÉ, jamais avalé : un instantané vide sans
        # explication renverrait au silence que tout ce travail répare.
        if faire_instantane:
            enregistrer([], groupes=[], erreur=f"{type(exc).__name__} : {exc}")
        if faire_occupations and not occupations_ecrites:
            occupations.enregistrer_echec(f"{type(exc).__name__} : {exc}")
        print(f"relevé impossible : {exc}", file=sys.stderr)
        return 3

    if faire_instantane:
        enregistrer(evenements, groupes=groupes_lus)
        print(f"instantané : {len(evenements)} évènement(s) sur {len(groupes_lus)} groupe(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
