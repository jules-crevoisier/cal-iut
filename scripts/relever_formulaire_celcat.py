"""Relève les libellés du formulaire d'événement Celcat, sans rien y écrire.

POURQUOI CE SCRIPT EXISTE. `driver.PilotePlaywright` sait remplir le
formulaire de création, mais il refuse de cliquer tant qu'il ne connaît pas
les LIBELLÉS de ses champs — ils ne sont écrits nulle part, et les inventer
reviendrait à cliquer à l'aveugle sur un outil qui alimente la paie. Ce
script va les lire sur le vrai Celcat et les dépose dans un dossier de
relevé, à recopier ensuite dans `data/config/celcat_formulaire.yaml`.

CE QU'IL NE FAIT PAS, DÉLIBÉRÉMENT. Il ne clique jamais l'icône « new ».
Un clic sur `new` crée d'emblée un événement récurrent sur les 54 semaines
de l'année, même sans rien remplir ni enregistrer — c'est l'incident du
01/09/2026, dont l'événement fantôme n'est toujours pas supprimé. Or
l'inspecteur d'événement, lui, s'ouvre par un simple double-clic sur la
grille et porte les mêmes cinq onglets. On lit donc là.

Par défaut il se connecte en `985_consultation` : la garantie qu'aucune
écriture n'est possible ne repose alors pas sur la prudence de ce fichier,
mais sur les droits du compte.

    Lancement (depuis le conteneur de saisie, qui monte le VPN) :

      docker run --rm --cap-add NET_ADMIN --device /dev/net/tun \
        --env-file .env -v "$PWD:/travail" -w /travail cal-iut-celcat \
        python scripts/relever_formulaire_celcat.py

    Options utiles :
      --groupe "BUT MMI S1 TD AB"   groupe dont on ouvre l'emploi du temps
      --base URCA_FORMATION         base d'entraînement plutôt que l'annuelle
      --role 985_T_MMI              pour voir le formulaire tel qu'en écriture
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402

# Les cinq onglets de l'inspecteur, relevés le 31/08/2026.
ONGLETS = [
    "Détails",
    "Ressources",
    "Remarques et personnaliser",
    "Critères requis",
    "Historique",
]


class _EspionRpc:
    """Note les appels JSON-RPC : pour savoir si une recherche est vide
    ou noyée sous `ETooManyRecords`, et si un emploi du temps porte autre
    chose que des jours fériés."""

    def __init__(self, page) -> None:
        self.appels: list[dict] = []
        page.on("response", self._noter)

    def _noter(self, reponse) -> None:
        req = reponse.request
        if req.method != "POST" or "CTWebService.dll" not in reponse.url:
            return
        try:
            envoi = json.loads(req.post_data or "{}")
            corps = nav.lire_reponse(reponse.text())
        except Exception:  # noqa: BLE001
            return
        methode = envoi.get("method")
        params = envoi.get("params") or []
        resultat = corps.get("result")
        erreur = corps.get("error")
        n = len(resultat) if isinstance(resultat, list) else None
        apercu = None
        noms = None
        if methode == "udlTimetables.load" and isinstance(resultat, list):
            apercu = {
                "evenements": n,
                "avec_ressources": sum(
                    1
                    for e in resultat
                    if isinstance(e, dict)
                    and (e.get("staff") or e.get("rooms") or e.get("modules"))
                ),
                "categories": sorted(
                    {
                        str(e.get("evCatName") or "")
                        for e in resultat
                        if isinstance(e, dict) and e.get("evCatName")
                    }
                )[:12],
            }
        if (
            methode == "udlResources.load"
            and params
            and params[0] == nav.TYPE_GROUPES
            and isinstance(resultat, list)
        ):
            noms = [str(r.get("name") or "") for r in resultat if isinstance(r, dict)][:40]
        self.appels.append(
            {
                "methode": methode,
                "params0": params[0] if params else None,
                "n": n,
                "erreur": str(erreur)[:180] if erreur else None,
                "apercu": apercu,
                "noms": noms,
            }
        )


class _ReleveTermine(Exception):
    """Sortie normale d'un relevé partiel : il n'y a plus rien à faire."""



def _ouvrir_liste(page, titre: str) -> None:
    """Ouvre le panneau de gauche qui porte ce titre.

    Les Y des icônes (`navigateur.ICONES`) datent d'un autre agencement :
    cliquer « Groupes » à y=266 ouvre en réalité « Départements » (type 610,
    constaté le 01/09/2026 sur URCA_2025). On clique donc le long de la
    colonne jusqu'à voir le BON titre en haut du panneau.
    """
    hauts = [f["texte"] for f in nav.feuilles(page) if f["y"] < 55 and f["x"] < 220]
    if titre in hauts:
        return
    for y in range(48, 430, 14):
        page.mouse.click(18, y)
        page.wait_for_timeout(700)
        hauts = [f["texte"] for f in nav.feuilles(page) if f["y"] < 55 and f["x"] < 220]
        if titre in hauts:
            page.wait_for_timeout(900)
            return
    raise LookupError(f"panneau « {titre} » introuvable dans la colonne d'icônes.")


def _dossier_releve() -> Path:
    horodatage = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dossier = RACINE / "data" / "releves" / f"celcat-formulaire-{horodatage}"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _photo(page, dossier: Path, nom: str) -> str:
    chemin = dossier / f"{nom}.png"
    page.screenshot(path=str(chemin), full_page=False)
    return chemin.name


def _etat(page) -> dict:
    """Tout ce qui est lisible à l'écran, sans rien toucher."""
    return {
        "textes": nav.feuilles(page),
        "champs": nav.champs_saisie(page),
        "icones": {nom: nav.icones_barre(page, nom) for nom in nav.IMAGES_BARRE},
    }


# La grille horaire occupe la moitié droite du panneau : colonnes Mon→Sun à
# partir de x≈1000. Deux bordures à exclure, faute de quoi on double-clique
# à côté : la gouttière des heures (x≈945, « 2:30 PM ») et la ligne des noms
# de jours (y≈134). Les avoir prises pour des séances a fait ouvrir un
# inspecteur vide au premier essai — « Sélectionner un événement pour voir
# ses détails », cinq onglets et aucun champ.
GRILLE = {"x_min": 980, "x_max": 1910, "y_min": 150, "y_max": 900}
JOURS_ENTETE = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


# Un événement est un bloc COLORÉ dans la grille. Le repérer par son texte
# ne marche pas : cliquer un événement ouvre une bulle « Événement 1 de 1 »
# qui se superpose à la grille, et ses propres textes se font alors passer
# pour des séances — on double-clique dans la bulle, l'inspecteur s'ouvre
# vide (« Sélectionner un événement pour voir ses détails »).
_JS_BLOCS_SEANCE = """(zone) => {
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
    if ((aa === undefined ? 1 : aa) < 0.05) continue;      // transparent
    if (rr > 245 && vv > 245 && bb > 245) continue;        // fond blanc
    out.push({
      x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
      largeur: Math.round(r.width), hauteur: Math.round(r.height),
      couleur: fond, texte: (e.textContent || '').trim().slice(0, 40),
    });
  }
  return out;
}"""


def _seances_visibles(page) -> list[dict]:
    """Les blocs colorés posés DANS la grille : les séances affichées.

    On écarte d'abord le pointeur de la grille pour laisser retomber toute
    bulle de survol. Surtout PAS d'Échap ici : cette touche referme l'emploi
    du temps lui-même, et le sélecteur de semaines disparaît avec lui
    (constaté le 01/09/2026, panneau droit vide).
    """
    page.mouse.move(*nav.SUR_LA_LISTE)
    page.wait_for_timeout(500)
    blocs = page.evaluate(_JS_BLOCS_SEANCE, GRILLE)
    # Les plus hauts d'abord : un bloc large et haut est une séance, un bloc
    # plat est plus souvent une bordure ou un fond de colonne.
    return sorted(blocs, key=lambda b: -(b["hauteur"] * b["largeur"]))


# Le sélecteur de semaines (« Semaines de l'emploi du temps ») occupe le bas
# du panneau de gauche : six rangées de petites cellules, encadrées par les
# noms de mois. Ses cellules NE PORTENT AUCUN TEXTE — seule celle en cours
# affiche son numéro. Les repérer par leur contenu, comme le faisait
# `navigateur.choisir_semaine`, ne peut donc trouver que la semaine déjà
# sélectionnée : il faut passer par la géométrie.
_JS_CELLULES_CALENDRIER = """(zone) => {
  const out = [];
  for (const e of document.querySelectorAll('div')) {
    if (e.children.length) continue;
    const r = e.getBoundingClientRect();
    if (r.y < zone.y_min || r.y > zone.y_max) continue;
    if (r.x < zone.x_min || r.x > zone.x_max) continue;
    if (r.width < 8 || r.width > 90 || r.height < 6 || r.height > 30) continue;
    out.push({
      x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
      gauche: Math.round(r.x), haut: Math.round(r.y),
      largeur: Math.round(r.width), hauteur: Math.round(r.height),
      texte: (e.textContent || '').trim(),
      classe: (e.className || '').toString().slice(0, 60),
    });
  }
  return out;
}"""

ZONE_CALENDRIER = {"x_min": 0, "x_max": 940, "y_min": 855, "y_max": 1065}


def _relever_calendrier(page, dossier: Path, limite: int) -> dict:
    """Géométrie du sélecteur de semaines + infobulle de chaque cellule.

    L'infobulle n'existe que le temps d'un survol RÉEL : ni `title`, ni
    attribut qooxdoo à lire dans le DOM. On survole donc, on attend, et on
    relit les textes de la page pour capter celui qui vient d'apparaître.
    """
    cellules = page.evaluate(_JS_CELLULES_CALENDRIER, ZONE_CALENDRIER)
    cellules.sort(key=lambda c: (c["haut"], c["gauche"]))
    print(f"{len(cellules)} cellules candidates dans le sélecteur de semaines.")

    avant = {f["texte"] for f in nav.feuilles(page)}
    releves = []
    for index, cellule in enumerate(cellules[:limite]):
        page.mouse.move(cellule["x"], cellule["y"])
        page.wait_for_timeout(650)
        apparus = [
            f["texte"] for f in nav.feuilles(page)
            if f["texte"] not in avant and "/" in f["texte"]
        ]
        releves.append({**cellule, "infobulles": apparus})
        if index < 12:
            print(f"  ({cellule['x']:>4},{cellule['y']:>5}) -> {apparus or '—'}")
    _photo(page, dossier, "05-selecteur-de-semaines")
    return {"zone": ZONE_CALENDRIER, "cellules": releves}


def _ouvrir_inspecteur(page, dossier: Path, releve: dict, cibles) -> bool:
    """Double-clic dans la grille : l'inspecteur s'ouvre sans rien créer.

    On ne clique JAMAIS l'icône « new » : elle crée d'emblée un événement
    récurrent sur les 54 semaines de l'année, même sans rien remplir
    (incident du 01/09/2026). Le double-clic, lui, ne fait qu'ouvrir.
    """
    for essai, (x, y) in enumerate(cibles, start=1):
        page.mouse.click(x, y, click_count=2)
        page.wait_for_timeout(3000)
        textes = {f["texte"] for f in nav.feuilles(page)}
        trouves = [o for o in ONGLETS if o in textes]
        releve.setdefault("tentatives_inspecteur", []).append(
            {"position": [x, y], "onglets_vus": trouves}
        )
        # Les cinq onglets sont DÉJÀ affichés à vide (« Sélectionner un
        # événement pour voir ses détails ») : les avoir vus ne prouve rien.
        # Un événement est vraiment ouvert quand le champ Jour: est là, et
        # que ce bandeau a disparu.
        inspecteur_vide = "Sélectionner un événement pour voir ses détails" in textes
        formulaire_ouvert = "Jour:" in textes or "Heure:" in textes
        releve["tentatives_inspecteur"][-1]["vide"] = inspecteur_vide
        releve["tentatives_inspecteur"][-1]["formulaire"] = formulaire_ouvert
        if formulaire_ouvert and not inspecteur_vide:
            _photo(page, dossier, f"inspecteur-avec-formulaire-essai{essai}")
            return True
        if len(trouves) >= 2:
            _photo(page, dossier, f"inspecteur-ouvert-essai{essai}")
    return False


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--groupe", default="BUT MMI S1 TD AB")
    parseur.add_argument("--base", default=nav.BASE_PRODUCTION)
    parseur.add_argument("--role", default=nav.ROLE_LECTURE)
    parseur.add_argument("--vpn", action="store_true", help="monter le VPN si besoin")
    parseur.add_argument(
        "--lister-groupes",
        default="",
        metavar="TERME",
        help="liste les groupes dont le nom contient TERME, et s'arrête là. "
        "Sert à savoir sous quel nom un groupe existe dans une base donnée.",
    )
    parseur.add_argument(
        "--calendrier",
        action="store_true",
        help="relève la géométrie du sélecteur de semaines et l'infobulle de "
        "chaque cellule, au lieu d'ouvrir l'inspecteur.",
    )
    parseur.add_argument(
        "--semaines",
        default="",
        help="lundis ISO à essayer, séparés par des virgules : on s'arrête à la "
        "première semaine qui contient des séances (l'onglet « Ressources » "
        "n'existe que sur un événement qui en porte).",
    )
    args = parseur.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(RACINE / ".env")
    except ImportError:
        pass

    url = os.environ.get("CELCAT_URL", "")
    if not url:
        print("CELCAT_URL absent de l'environnement (.env).", file=sys.stderr)
        return 2

    diag = reseau.exiger_acces(url, monter_le_vpn=args.vpn) if args.vpn else reseau.verifier(url)
    if not getattr(diag, "joignable", False):
        print(f"Celcat injoignable : {diag.detail}", file=sys.stderr)
        return 3
    print(f"Celcat joignable ({diag.detail or 'accès direct'}).")

    from playwright.sync_api import sync_playwright

    dossier = _dossier_releve()
    releve: dict = {
        "quand": dt.datetime.now().isoformat(timespec="seconds"),
        "base": args.base,
        "role": args.role,
        "groupe": args.groupe,
        "onglets": {},
    }

    with sync_playwright() as p:
        navigateur_ = p.chromium.launch(headless=True)
        page = navigateur_.new_page(viewport={"width": 1920, "height": 1080})
        espion = _EspionRpc(page)
        try:
            print(f"Connexion à {args.base} en rôle {args.role}…")
            nav.connexion(page, base=args.base, role=args.role)
        except Exception as exc:  # noqa: BLE001 — on veut VOIR pourquoi
            # Sans capture ni liste des textes, un échec ici ne dit rien :
            # l'écran de connexion peut ne pas afficher la liste des bases
            # (serveur saturé de sessions non rendues, 31/08/2026), avoir
            # changé, ou n'avoir simplement pas fini de charger.
            _photo(page, dossier, "00-echec-connexion")
            (dossier / "echec-connexion.json").write_text(
                json.dumps(
                    {"erreur": str(exc), "url": page.url, "textes": nav.feuilles(page)},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            print(f"Connexion impossible : {exc}", file=sys.stderr)
            print(f"Écran capturé dans {dossier}", file=sys.stderr)
            navigateur_.close()
            return 4

        try:
            _photo(page, dossier, "01-connecte")

            _ouvrir_liste(page, "Groupes")

            if args.lister_groupes:
                print(f"Recherche des groupes « {args.lister_groupes} »…")
                trouves = nav.chercher(page, nav.TYPE_GROUPES, args.lister_groupes)
                releve["groupes"] = [
                    {"nom": g.get("name"), "code": g.get("unique_name") or g.get("id")}
                    for g in trouves
                ]
                releve["textes_apres_recherche"] = [
                    f["texte"] for f in nav.feuilles(page) if f["y"] < 250
                ]
                _photo(page, dossier, "01b-liste-groupes")
                for g in sorted(releve["groupes"], key=lambda g: str(g["nom"])):
                    print(f"  {g['nom']}")
                print(f"{len(trouves)} groupe(s).")
                for appel in espion.appels:
                    if appel.get("noms"):
                        print("  exemples :")
                        for nom in appel["noms"][:15]:
                            print(f"    {nom}")
                    if appel.get("erreur") or (
                        appel.get("methode") == "udlResources.load"
                        and appel.get("params0") == nav.TYPE_GROUPES
                    ):
                        print(
                            f"  rpc {appel['methode']} type={appel['params0']} "
                            f"n={appel['n']} err={appel['erreur']}"
                        )
                if not trouves:
                    raise _ReleveTermine
                td = [
                    g["nom"]
                    for g in releve["groupes"]
                    if g.get("nom") and "TD" in str(g["nom"])
                ]
                args.groupe = td[0] if td else releve["groupes"][0]["nom"]
                releve["groupe"] = args.groupe
                if not args.semaines:
                    args.semaines = (
                        "2025-09-08,2025-09-22,2025-10-13,2025-11-03,2026-01-12"
                    )
                print(f"enchaîne sur « {args.groupe} »")

            print(f"Ouverture du groupe « {args.groupe} »…")
            nav.filtrer(page, args.groupe)
            nav.double_cliquer_texte(page, args.groupe)
            _photo(page, dossier, "02-emploi-du-temps")
            releve["emploi_du_temps"] = _etat(page)
            for appel in reversed(espion.appels):
                if appel.get("apercu"):
                    print(f"  emploi du temps : {appel['apercu']}")
                    releve["emploi_rpc"] = appel["apercu"]
                    break

            if args.calendrier:
                releve["calendrier"] = _relever_calendrier(page, dossier, limite=60)
                raise _ReleveTermine

            seances = _seances_visibles(page)
            releve["semaines_essayees"] = []
            for lundi in [s.strip() for s in args.semaines.split(",") if s.strip()]:
                if seances:
                    break
                print(f"Semaine du {lundi}…")
                choisie = nav.choisir_semaine(page, dt.date.fromisoformat(lundi))
                seances = _seances_visibles(page)
                releve["semaines_essayees"].append(
                    {"lundi": lundi, "infobulle": choisie["infobulle"], "seances": len(seances)}
                )
                print(f"  {len(seances)} bloc(s) dans la grille.")
            if seances:
                _photo(page, dossier, "02b-semaine-avec-seances")
            releve["seances_visibles"] = seances[:40]

            # On vise d'abord une séance réelle, puis des positions de repli.
            cibles = [(s["x"], s["y"]) for s in seances[:6]] or []
            cibles += [(1200, 300), (1000, 400), (1400, 250)]

            print("Ouverture de l'inspecteur d'événement (double-clic, aucun `new`)…")
            if not _ouvrir_inspecteur(page, dossier, releve, cibles):
                print("Inspecteur non ouvert : le relevé s'arrête à l'emploi du temps.")
                releve["inspecteur_ouvert"] = False
            else:
                releve["inspecteur_ouvert"] = True
                for index, nom in enumerate(ONGLETS, start=1):
                    try:
                        nav.onglet(page, nom)
                    except LookupError:
                        releve["onglets"][nom] = {"absent": True}
                        continue
                    page.wait_for_timeout(900)
                    releve["onglets"][nom] = _etat(page)
                    _photo(page, dossier, f"03-{index}-{nom[:18].replace(' ', '-')}")
                    print(f"  onglet « {nom} » relevé.")
                # Refermer sans rien valider.
                page.keyboard.press("Escape")
                page.wait_for_timeout(1200)
                _photo(page, dossier, "04-referme")
        except _ReleveTermine:
            pass
        except Exception as exc:  # noqa: BLE001 — un relevé partiel vaut mieux que rien
            releve["erreur"] = str(exc)
            releve["textes_au_moment_de_l_erreur"] = nav.feuilles(page)
            _photo(page, dossier, "99-echec")
            print(f"Interrompu : {exc}", file=sys.stderr)
        finally:
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            releve["rpc"] = espion.appels[-40:]
            navigateur_.close()

    (dossier / "releve.json").write_text(
        json.dumps(releve, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nRelevé écrit dans {dossier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
