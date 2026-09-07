"""Audit LECTURE SEULE des catégories d'événement Celcat — les TROIS types.

Signalement de David Annebicque, 07/09/2026 : « ce qui est dans Celcat est
faux ! Les TD sont aléatoirement indiqués en TD ou en CM dans le type de
cours (premier onglet), ça casse la synchro et ça posera souci sur OMEGA ».

Pourquoi un script de plus. `corriger_cm_categories_celcat.py` ne peut pas
répondre à ça : il pose `types = {sid: "CM" for sid in journal}`, c'est-à-
dire qu'il DÉCLARE tout le journal en CM. Utile pour le défaut historique
qu'il vise (le CM retombé en [TP] du temps de l'autoclicker), mais aveugle
par construction à un TD mal catégorisé. Ici le type attendu vient de la
maquette, séance par séance, via `entrees_pour_state`.

Ce script n'écrit RIEN, jamais : ni Celcat, ni le journal. Pas de
`--ecrire`, aucun import du module de modification. Il sert à CHIFFRER
avant de décider quoi corriger — sur un sujet qui alimente OMEGA, et donc
la paie, on regarde avant de toucher.

Il relève aussi le catalogue des catégories (identifiant et libellé). C'est
ce qui manque aujourd'hui pour rendre le garde-fou d'écriture symétrique :
`categories.CATEGORIE_IDS` ne connaît que `CM: 430`, donc un TD envoyé
avec l'identifiant du CM passe sans être refusé — la forme même du
symptôme signalé.

    python scripts/auditer_categories_celcat.py --vpn
    python scripts/auditer_categories_celcat.py --vpn --json releve.json
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat import reseau
from cal_iut.celcat.categories import inventaire_ecarts_categorie, type_depuis_identifiant
from cal_iut.celcat.ecriture import resoudre_groupe
from cal_iut.celcat.etat import charger
from cal_iut.celcat.lecture import evenement_depuis_rpc
from cal_iut.celcat.mapping import entrees_pour_state
from cal_iut.celcat.navigateur import TYPE_CATEGORIES_EVENEMENT
from cal_iut.celcat.rpc import charger_edt, charger_ressources


# Repli quand l'état cal-iut n'est pas chargé (hors serveur) : les groupes
# Celcat du S1, tels que `corriger_cm_categories_celcat.py` les nomme déjà.
# Une liste écrite à la main est un choix assumé — la déduire des
# identifiants du journal demanderait de deviner le libellé Celcat depuis un
# suffixe (« but1-td-ab » -> « TD AB »), et un nom mal deviné ne produit pas
# une erreur : il produit un groupe introuvable, donc un audit qui ne lit
# rien en annonçant tout de même « aucun écart ».
GROUPES_S1_PAR_DEFAUT = (
    "BUT MMI S1 CM",
    "BUT MMI S1 TD AB",
    "BUT MMI S1 TD CD",
    "BUT MMI S1 TD EF",
    "BUT MMI S1 TD GH",
)


def _types_attendus(journal: dict) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    """Type attendu et nom de groupe Celcat, pour les séances journalisées.

    Rend aussi le compte par origine du type (maquette / identifiant /
    aucune) : un audit dont la moitié des types viennent du repli ne se lit
    pas comme un audit adossé à la maquette, et le dire évite de confondre
    « rien à signaler » avec « rien de jugé ».
    """
    from cal_iut.api.state import get_state

    entrees = entrees_pour_state(get_state())
    types: dict[str, str] = {}
    groupes: dict[str, str] = {}
    origines: dict[str, int] = {"maquette": 0, "identifiant": 0, "aucune": 0}
    for session_id in journal:
        entree = entrees.get(session_id)
        nom = (getattr(entree, "type_seance_nom", "") or "").strip().upper() if entree else ""
        if entree is not None and nom:
            origines["maquette"] += 1
        else:
            nom = type_depuis_identifiant(session_id)
            origines["identifiant" if nom else "aucune"] += 1
        if nom:
            types[session_id] = nom
        if entree is not None:
            groupes[session_id] = entree.nom_groupe_celcat
    return types, groupes, origines


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--base", default=nav.BASE_PRODUCTION)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    parseur.add_argument("--json", default="", help="chemin d'un relevé JSON à écrire")
    parseur.add_argument(
        "--groupes",
        default="",
        help=(
            "noms Celcat des groupes à lire, séparés par des virgules. Nécessaire "
            "seulement hors du serveur, là où l'état cal-iut est vide et ne peut "
            f"donc pas les fournir. Défaut si omis : {', '.join(GROUPES_S1_PAR_DEFAUT)}"
        ),
    )
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

    journal = charger().get("journal") or {}
    if not journal:
        print("journal vide — rien à auditer")
        return 0
    types, groupes, origines = _types_attendus(journal)
    print(
        f"{len(journal)} séance(s) journalisée(s) — type connu pour {len(types)} "
        f"(maquette : {origines['maquette']}, repli sur l'identifiant : "
        f"{origines['identifiant']}, indéterminé : {origines['aucune']})"
    )
    noms_groupes = sorted(set(groupes.values()))
    if not noms_groupes:
        # Sans maquette chargée, on ne sait pas QUELS groupes lire sur Celcat
        # et l'audit ne verrait rien : on prend le repli explicite, jamais le
        # silence — un « aucun écart » faute d'avoir rien lu se lirait comme
        # une bonne nouvelle.
        noms_groupes = (
            [n.strip() for n in args.groupes.split(",") if n.strip()]
            if args.groupes
            else list(GROUPES_S1_PAR_DEFAUT)
        )
        print(
            "état cal-iut vide (hors serveur) : lecture des groupes indiqués — "
            + ", ".join(noms_groupes)
        )

    from playwright.sync_api import sync_playwright

    # `reseau.acces` rend le tunnel en sortant : un audit ne doit pas garder
    # la session du compte partagé (cf. `celcat/reseau.py`).
    with reseau.acces(url, monter_le_vpn=args.vpn) as diag:
        if not diag.joignable:
            print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
            return 3
        with sync_playwright() as p:
            navigateur = p.chromium.launch(headless=True, args=_args_resolution(url))
            page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
            try:
                print(f"Connexion {args.base} rôle {args.role} (lecture seule)…")
                nav.connexion(page, base=args.base, role=args.role)
                catalogue = _catalogue_categories(page)
                live = _lire_live(page, noms_groupes)
            finally:
                try:
                    nav.deconnexion(page)
                except Exception:  # noqa: BLE001, S110
                    pass
                navigateur.close()

    ecarts = inventaire_ecarts_categorie(
        journal=journal, live_par_event_id=live, type_par_session=types
    )
    comparees = _comparees(journal, types, live)
    _afficher(catalogue, live, types, ecarts, comparees)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "catalogue_categories": catalogue,
                    "evenements_lus": len(live),
                    "seances_jugees": len(types),
                    "seances_confrontees": len(comparees),
                    "origine_des_types": origines,
                    "ecarts": [vars(e) for e in ecarts],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nrelevé écrit dans {args.json}")
    return 0


def _args_resolution(url: str) -> list[str]:
    """Impose à Chromium la résolution que Python vient déjà de valider.

    Chromium n'utilise pas le résolveur du système mais le sien : sur un
    poste Windows, il ignore donc le serveur DNS poussé par le VPN et rend
    `ERR_NAME_NOT_RESOLVED` sur un nom que Python résout parfaitement au
    même instant (constaté le 07/09/2026, tunnel monté, `celcat-lv.univ-
    reims.fr` -> 10.5.1.153 côté socket, introuvable côté navigateur).

    Plutôt qu'une adresse écrite en dur, on réutilise la résolution que
    `reseau.verifier` a déjà faite pour accepter de continuer : si elle est
    fausse, le script n'aurait de toute façon pas dépassé le contrôle
    d'accès. Sans résolution possible, on ne force rien et Chromium se
    débrouille — c'est le cas du conteneur Linux, où le DNS du VPN est
    celui du système et où ce contournement n'a pas lieu d'être.
    """
    import socket
    import time
    from urllib.parse import urlparse

    hote = urlparse(url if "//" in url else f"https://{url}").hostname or ""
    if not hote:
        return []
    # Quelques essais : le tunnel vient d'être monté et `vpnc-script` peut
    # n'avoir pas fini de réécrire la configuration DNS. Un échec transitoire
    # ici ne se verrait pas — il rendrait juste une liste vide, et Chromium
    # échouerait plus loin sur un ERR_NAME_NOT_RESOLVED sans rapport apparent
    # (constaté : la même commande marche une fois sur deux).
    for tentative in range(5):
        try:
            adresse = socket.getaddrinfo(hote, 443, proto=socket.IPPROTO_TCP)[0][4][0]
        except OSError:
            time.sleep(1.5)
            continue
        return [f"--host-resolver-rules=MAP {hote} {adresse}"]
    print(f"  ({hote} irrésolu : Chromium tentera sa propre résolution)")
    return []


def _catalogue_categories(page) -> dict[str, int]:
    """Libellé Celcat → identifiant, pour compléter `CATEGORIE_IDS`."""
    catalogue: dict[str, int] = {}
    try:
        for enreg in charger_ressources(page, TYPE_CATEGORIES_EVENEMENT, {}):
            libelle = str(enreg.get("unique_name") or enreg.get("name") or "").strip()
            identifiant = enreg.get("event_cat_id") or enreg.get("id")
            if libelle and identifiant is not None:
                catalogue[libelle] = int(identifiant)
    except Exception as exc:  # noqa: BLE001 — l'audit vaut sans le catalogue
        print(f"  (catalogue des catégories illisible : {exc})")
    return catalogue


def _lire_live(page, noms_groupes: list[str]) -> dict[int, object]:
    live: dict[int, object] = {}
    for nom in noms_groupes:
        if not nom:
            continue
        try:
            gid = resoudre_groupe(page, nom)
        except Exception as exc:  # noqa: BLE001
            print(f"  groupe « {nom} » introuvable : {exc}")
            continue
        for brut in charger_edt(page, group_ids=[gid]):
            ev = evenement_depuis_rpc(brut, group_id=gid, groupe_nom=nom)
            live[ev.event_id] = ev
    return live


def _comparees(journal: dict, types: dict, live: dict) -> list[str]:
    """Séances RÉELLEMENT confrontées : type connu ET retrouvées dans Celcat.

    `inventaire_ecarts_categorie` ignore en silence une séance dont
    l'`event_id` n'a pas été lu — et une comparaison portant sur zéro séance
    rend « aucun écart », exactement comme une comparaison réussie. Compter
    ce qui a été confronté est donc la seule façon de distinguer « tout va
    bien » de « on n'a rien regardé ».
    """
    comparees: list[str] = []
    for session_id, row in journal.items():
        if not isinstance(row, dict) or session_id not in types:
            continue
        brut = row.get("event_id")
        try:
            event_id = int(brut) if brut not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            continue
        if event_id is not None and event_id in live:
            comparees.append(session_id)
    return comparees


def _afficher(catalogue: dict, live: dict, types: dict, ecarts: list, comparees: list) -> None:
    print(f"\ncatalogue des catégories Celcat : {catalogue or '(illisible)'}")
    print(f"{len(live)} événement(s) lus sur Celcat")
    print(
        f"{len(comparees)} séance(s) réellement confrontée(s) "
        f"sur {len(types)} au type connu ({len(types) - len(comparees)} absente(s) du Live lu)"
    )

    if not comparees:
        print(
            "\nRIEN N'A ÉTÉ COMPARÉ : aucune séance du journal ne figure parmi les "
            "événements lus. L'absence d'écart ci-dessous ne prouve rien — élargir "
            "les groupes (--groupes) avant de conclure quoi que ce soit.",
        )
        return

    if not ecarts:
        print(
            f"\nAucun écart sur les {len(comparees)} séance(s) confrontée(s) : "
            "elles portent toutes la bonne catégorie."
        )
        return

    croises = collections.Counter((e.type_attendu, e.categorie_live) for e in ecarts)
    print(f"\n{len(ecarts)} ÉCART(S) sur {len(types)} séance(s) jugée(s) :\n")
    print(f"  {'maquette':<10} {'Celcat affiche':<18} n")
    for (attendu, vu), n in sorted(croises.items(), key=lambda kv: -kv[1]):
        print(f"  {attendu:<10} {vu:<18} {n}")

    print("\n  détail :")
    for e in sorted(ecarts, key=lambda e: (e.type_attendu, e.session_id)):
        print(f"    {e.session_id:<40} event_id={e.event_id:<10} {e.motif}")


if __name__ == "__main__":
    raise SystemExit(principal())
