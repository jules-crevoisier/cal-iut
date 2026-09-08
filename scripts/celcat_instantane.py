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
from cal_iut.celcat import reseau
from cal_iut.celcat.ecriture import resoudre_groupe
from cal_iut.celcat.instantane import consommer_demande, enregistrer, releve_du
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.rpc import charger_edt

# Groupes relevés. Écrits ici plutôt que déduits : un nom mal deviné ne
# produit pas une erreur mais un groupe introuvable, donc un relevé
# silencieusement incomplet — le genre de demi-vérité qu'on cherche à
# éliminer de cet outil.
GROUPES = (
    "BUT MMI S1 CM",
    "BUT MMI S1 TD AB",
    "BUT MMI S1 TD CD",
    "BUT MMI S1 TD EF",
    "BUT MMI S1 TD GH",
)


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
    for nom in GROUPES:
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
                    "categorie": ev.categorie,
                    "enseignant": ev.enseignant,
                    "module": ev.module_nom,
                    "semaine": ev.indice_semaine,
                    "protected": ev.protected,
                }
            )
    return evenements, groupes_lus


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--forcer", action="store_true", help="ignore la cadence de 2 h")
    args = parseur.parse_args()

    if not args.forcer and not releve_du():
        print("instantané encore frais — rien à faire")
        return 0
    consommer_demande()

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
                enregistrer([], groupes=[], erreur=f"Celcat injoignable : {diag.detail}")
                print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
                return 3
            with sync_playwright() as p:
                navigateur = p.chromium.launch(headless=True, args=_args_resolution(url))
                page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
                try:
                    print(f"Connexion {nav.BASE_PRODUCTION} rôle {nav.ROLE_LECTURE} (lecture)…")
                    nav.connexion(page, base=nav.BASE_PRODUCTION, role=nav.ROLE_LECTURE)
                    evenements, groupes_lus = _relever(page)
                finally:
                    try:
                        nav.deconnexion(page)
                    except Exception:  # noqa: BLE001, S110
                        pass
                    navigateur.close()
    except Exception as exc:  # noqa: BLE001
        # L'échec est ENREGISTRÉ, jamais avalé : un instantané vide sans
        # explication renverrait au silence que tout ce travail répare.
        enregistrer([], groupes=[], erreur=f"{type(exc).__name__} : {exc}")
        print(f"relevé impossible : {exc}", file=sys.stderr)
        return 3

    enregistrer(evenements, groupes=groupes_lus)
    print(f"instantané : {len(evenements)} évènement(s) sur {len(groupes_lus)} groupe(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
