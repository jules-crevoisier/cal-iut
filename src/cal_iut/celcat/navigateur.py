"""Piloter Celcat Timetabler Live — ce que l'exploration du 31/08/2026 a établi.

CE QU'EST CELCAT, CONCRÈTEMENT. Une application qooxdoo : des <div>
absolument positionnés, sans id, sans name, sans role. Aucun sélecteur
Playwright n'a de prise. On repère donc le TEXTE affiché et on clique à ses
coordonnées — c'est ce que fait `cliquer_texte`.

CE QUI VAUT MIEUX QUE CLIQUER. L'application dialogue avec un service
JSON-RPC 2.0 (`/script/CTWebService.dll`). On ne peut pas l'appeler
directement : la session n'est portée ni par un cookie ni par un en-tête —
elle est liée à la CONNEXION, et un `fetch` séparé reçoit `ESessionTimeout`
(vérifié : ni l'URL de session, ni un identifiant séquentiel n'y changent
rien). En revanche, rien n'empêche de LIRE les réponses des appels que
l'application fait elle-même : c'est `Recolteur`, et c'est la seule façon
fiable d'extraire des données complètes plutôt que de relire un tableau
affiché, tronqué et paginé.

Les réponses ne sont pas du JSON strict : l'en-tête `X-Use-Object-Date`
fait renvoyer des `new Date(2026,5,12,...)` que l'application évalue. D'où
`lire_reponse`.

LES RÔLES DÉCIDENT DES DROITS. `985_consultation` est en lecture seule,
`985_T_MMI` autorise l'écriture sur le périmètre MMI. Toute exploration se
fait en consultation : la garantie ne repose alors pas sur la prudence du
script mais sur les droits du compte.

Il existe une base d'entraînement, `URCA_FORMATION`, à côté des bases
annuelles `URCA_2023`..`URCA_2026`. Les essais d'écriture s'y font.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time

# Types de ressources du service, relevés en observant l'application.
TYPE_MATIERES = 601
TYPE_GROUPES = 602
TYPE_PERSONNEL = 603
TYPE_SALLES = 604
TYPE_EQUIPES = 607
TYPE_DEPARTEMENTS = 610
TYPE_CATEGORIES_EVENEMENT = 618

# Titre affiché en haut du panneau de gauche une fois le type ouvert.
# C'est le seul repère fiable : les Y des icônes bougent (01/09/2026 :
# cliquer `ICONES[GROUPES]` ouvrait Départements, type 610).
TITRES_PANNEAU = {
    TYPE_MATIERES: "Matières",
    TYPE_SALLES: "Salles",
    TYPE_PERSONNEL: "Personnel",
    TYPE_EQUIPES: "Équipes",
    TYPE_GROUPES: "Groupes",
    TYPE_DEPARTEMENTS: "Départements",
    TYPE_CATEGORIES_EVENEMENT: "Catégories",
}

# Colonne d'icônes à gauche : premier essai, avant le balayage.
ICONES = {
    TYPE_MATIERES: 72,
    TYPE_SALLES: 122,
    TYPE_PERSONNEL: 168,
    TYPE_EQUIPES: 219,
    TYPE_GROUPES: 266,
    TYPE_DEPARTEMENTS: 326,
    TYPE_CATEGORIES_EVENEMENT: 377,
}

CHAMP_FILTRE = (590, 120)
SUR_LA_LISTE = (400, 500)

ROLE_LECTURE = "985_consultation"
ROLE_ECRITURE = "985_T_MMI"
BASE_PRODUCTION = "URCA_2026"
BASE_ENTRAINEMENT = "URCA_FORMATION"


# --- Lecture des réponses du service --------------------------------------

_DATE_JS = re.compile(r"new Date\(([^)]*)\)")


def _iso(m: re.Match) -> str:
    """`new Date(2026,5,12,11,11,5,0)` -> `"2026-06-12T11:11:05"`.

    Le mois est en base 0 comme en JavaScript : le 5 est JUIN. Se tromper
    ici décalerait toutes les dates d'un mois, sans rien casser de visible.
    """
    try:
        n = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
        if len(n) >= 3:
            reste = (n[3:6] + [0, 0, 0])[:3]
            return '"' + _dt.datetime(n[0], n[1] + 1, n[2], *reste).isoformat() + '"'
    except (ValueError, TypeError):
        pass
    return "null"


def lire_reponse(texte: str):
    """Parse une réponse du service, dates JavaScript comprises."""
    return json.loads(_DATE_JS.sub(_iso, texte))


# --- Repérage à l'écran ---------------------------------------------------

_JS_FEUILLES = """() => {
  const out = [];
  const m = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  while (m.nextNode()) {
    const e = m.currentNode;
    const t = (e.textContent || '').trim();
    if (e.children.length === 0 && t) {
      const r = e.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.x > -1000 && r.y > -1000)
        out.push({texte: t, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)});
    }
  }
  return out;
}"""


def feuilles(page) -> list[dict]:
    return page.evaluate(_JS_FEUILLES)


_NB_SEMAINES_FORMULAIRE = re.compile(r"\[=(\d+)\]")


def nombre_semaines_formulaire(page) -> int | None:
    """Combien de semaines le formulaire d'événement a cochées.

    Relevé le 01/09/2026 sur un événement réel : « Semaines: » est suivi de
    « 4 (1/21/26) [=1] ». Un clic sur `new` sans rien remplir crée un
    événement sur 54 semaines. Enregistrer dans cet état recopierait la
    séance sur toute l'année — et la paierait 54 fois.
    """
    label = trouver(page, "Semaines:", exact=True)
    candidats: list[tuple[int, int]] = []
    for f in feuilles(page):
        m = _NB_SEMAINES_FORMULAIRE.search(f["texte"])
        if not m:
            continue
        n = int(m.group(1))
        if label is None:
            candidats.append((0, n))
            continue
        dist = abs(int(f["y"]) - int(label["y"])) + abs(int(f["x"]) - int(label["x"]))
        candidats.append((dist, n))
    if not candidats:
        return None
    candidats.sort()
    return candidats[0][1]


def trouver(page, texte: str, *, exact: bool = False, sauf: str | None = None):
    for f in feuilles(page):
        if sauf and sauf in f["texte"]:
            continue
        if (f["texte"] == texte) if exact else (texte.lower() in f["texte"].lower()):
            return f
    return None


def attendre_texte(page, texte: str, *, delai: float = 30, exact: bool = False) -> None:
    """Attend qu'un texte soit AFFICHÉ.

    Rien dans cette interface ne signale la fin d'un chargement : ni
    `networkidle`, ni un état DOM. Parier sur un délai fixe donne des échecs
    aléatoires — c'est arrivé pendant l'exploration.
    """
    fin = time.time() + delai
    while time.time() < fin:
        if trouver(page, texte, exact=exact):
            page.wait_for_timeout(400)
            return
        page.wait_for_timeout(500)
    raise TimeoutError(f"texte jamais affiché : {texte!r}")


def cliquer_texte(page, texte: str, *, exact: bool = False, sauf: str | None = None,
                  attendre: int = 1200):
    cible = trouver(page, texte, exact=exact, sauf=sauf)
    if cible is None:
        raise LookupError(f"texte introuvable à l'écran : {texte!r}")
    page.mouse.click(cible["x"], cible["y"])
    page.wait_for_timeout(attendre)
    return cible


def champs_saisie(page) -> list[dict]:
    """qooxdoo crée de vrais <input> pour la saisie clavier."""
    return page.evaluate("""() => [...document.querySelectorAll('input,textarea')]
      .filter(e => e.getClientRects().length)
      .map(e => { const r = e.getBoundingClientRect(); return {
        type: e.type,
        x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}; });""")


# --- Glisser-déposer ------------------------------------------------------

def glisser_deposer(page, depart: tuple[int, int], arrivee: tuple[int, int]) -> None:
    """Traîne une ligne de la liste de ressources vers un champ du formulaire.

    C'EST AINSI QUE LE FORMULAIRE SE REMPLIT. Constat repris de l'ancien
    autoclicker (`clickclick/robot01.js`, juin 2026), qui procède ainsi pour
    les cinq champs de ressource — catégorie, département, enseignant, salle,
    matière : on ne tape pas dans le formulaire, on y dépose l'enregistrement
    depuis la liste de gauche. Aucune autre trace ne le documentait.

    Les pauses ne sont pas décoratives. qooxdoo implémente son propre
    glisser-déposer sur les événements souris : sans un temps d'arrêt après
    l'appui, puis des positions intermédiaires, il ne considère jamais qu'un
    glissement a commencé et le dépôt ne produit rien — c'est exactement le
    réglage que l'ancien clicker avait fini par trouver (appui, pause,
    déplacement, pause, relâchement).
    """
    page.mouse.move(*depart)
    page.wait_for_timeout(400)
    page.mouse.down()
    page.wait_for_timeout(600)
    # `steps` produit les positions intermédiaires dont qooxdoo a besoin pour
    # déclencher son `dragstart` : un saut direct est ignoré.
    page.mouse.move(*arrivee, steps=24)
    page.wait_for_timeout(400)
    page.mouse.up()
    page.wait_for_timeout(600)


# --- Onglets et barre du panneau ------------------------------------------

def onglet(page, nom: str) -> dict:
    """Bascule sur un onglet de l'inspecteur d'événement.

    Cinq onglets relevés le 31/08/2026 : Détails, Ressources, Remarques et
    personnaliser, Critères requis, Historique. Ils portent leur libellé,
    donc le repérage par texte suffit.
    """
    return cliquer_texte(page, nom, exact=True, attendre=900)


# Icônes de la barre du panneau « Emploi du temps », dans l'ordre relevé le
# 01/09/2026 : créer, supprimer, rafraîchir, enregistrer, annuler. qooxdoo ne
# leur donne AUCUN libellé accessible — ni texte, ni title, ni role : elles ne
# sont identifiables que par leur image de fond.
IMAGES_BARRE = {
    "creer": "new",
    "supprimer": "delete",
    "rafraichir": "refresh",
    "enregistrer": "save",
    "annuler": "cancel",
}

_JS_ICONES_BARRE = """(fragment) => {
  const out = [];
  for (const e of document.querySelectorAll('*')) {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.width > 64 || r.height > 64) continue;
    const fond = getComputedStyle(e).backgroundImage || '';
    if (!fond.includes(fragment + '.png')) continue;
    out.push({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), fond});
  }
  return out;
}"""


def icones_barre(page, nom: str) -> list[dict]:
    """Positions des icônes dont l'image de fond porte ce nom."""
    if nom not in IMAGES_BARRE:
        raise KeyError(f"icône inconnue : {nom!r} (attendu : {', '.join(IMAGES_BARRE)})")
    return page.evaluate(_JS_ICONES_BARRE, IMAGES_BARRE[nom])


# Icônes qui n'existent qu'en un exemplaire à l'écran (relevé du
# 01/09/2026) : elles servent donc à localiser la barre de l'emploi du temps.
# `creer`, lui, apparaît DEUX fois — le « Nouveau » de la liste de gauche en
# (64, 81) et celui de l'emploi du temps en (1802, 83).
ICONES_SANS_DOUBLON = ("supprimer", "rafraichir", "enregistrer", "annuler")

# Une même barre tient dans cette fenêtre autour de son centre : les cinq
# icônes relevées vont de x=1802 à x=1906 pour un même y à 1 px près.
_LARGEUR_BARRE = 220
_HAUTEUR_BARRE = 40


def repere_barre(page) -> dict | None:
    """Où est la barre de l'emploi du temps, d'après ses icônes uniques.

    Sert à départager `creer`, qui existe en deux exemplaires. On ne devine
    pas laquelle est la bonne : on la déduit du voisinage des quatre icônes
    qui, elles, ne sont pas ambiguës.
    """
    positions = [
        trouvees[0]
        for nom in ICONES_SANS_DOUBLON
        if len(trouvees := icones_barre(page, nom)) == 1
    ]
    if not positions:
        return None
    return {
        "x": sum(p["x"] for p in positions) // len(positions),
        "y": sum(p["y"] for p in positions) // len(positions),
    }


def cliquer_icone_barre(page, nom: str, *, attendre: int = 1500,
                        infobulle: str | None = None) -> dict:
    """Clique une icône de la barre de l'emploi du temps, ou lève.

    `new.png` sert dans plusieurs barres de l'application, et cliquer la
    mauvaise crée un événement dans un panneau qu'on ne regarde pas — cf.
    l'incident du 01/09/2026, où un clic sur `new` a créé un événement
    récurrent sur les 54 semaines de l'année. Quand plusieurs icônes
    correspondent, on ne tente donc pas sa chance : on ne retient que celle
    qui se trouve dans la barre de l'emploi du temps, repérée par les icônes
    qui n'ont pas de doublon. S'il en reste plusieurs, on lève.

    `infobulle` : si fournie, on survole d'abord et on exige ce texte
    (« Créer un nouvel événement ») avant de cliquer.
    """
    trouvees = icones_barre(page, nom)
    if not trouvees:
        raise LookupError(f"icône « {nom} » absente de l'écran.")
    if len(trouvees) > 1:
        repere = repere_barre(page)
        if repere is None:
            raise LookupError(
                f"{len(trouvees)} icônes « {nom} » à l'écran et aucun repère de barre "
                "pour les départager : impossible de choisir sans risquer d'agir dans "
                "le mauvais panneau."
            )
        trouvees = [
            i for i in trouvees
            if abs(i["x"] - repere["x"]) <= _LARGEUR_BARRE
            and abs(i["y"] - repere["y"]) <= _HAUTEUR_BARRE
        ]
        if len(trouvees) != 1:
            raise LookupError(
                f"{len(trouvees)} icônes « {nom} » dans la barre de l'emploi du temps : "
                "impossible de choisir sans risquer d'agir dans le mauvais panneau."
            )
    cible = trouvees[0]
    if infobulle:
        page.mouse.move(cible["x"], cible["y"])
        page.wait_for_timeout(1500)
        if trouver(page, infobulle) is None:
            vus = [str(f.get("texte") or "") for f in feuilles(page)]
            indices = [
                t for t in vus
                if any(m in t.lower() for m in ("cré", "event", "new", "nouvel", "tooltip"))
            ]
            raise LookupError(
                f"icône « {nom} » sans infobulle « {infobulle} » "
                f"(textes proches : {indices[:15] or 'aucun'}). "
                "rien n'a été cliqué."
            )
    page.mouse.click(cible["x"], cible["y"])
    page.wait_for_timeout(attendre)
    return cible


# --- Format des heures ----------------------------------------------------

def heure_12h(vingt_quatre: str) -> str:
    """« 08:00 » -> « 8:00 AM ». Format d'affichage relevé le 01/09/2026.

    Celcat parle en 12 heures AM/PM alors que nos horaires sont en 24 heures :
    l'inspecteur affiche « 7:00 AM-11:59 PM », la gouttière de la grille
    « 12:00 PM », « 1:30 PM ». Sans conversion, écrire « 14:00 » dans un champ
    qui attend « 2:00 PM » donne au mieux un refus, au pire une heure fausse.

    Pas de zéro de tête sur l'heure — « 8:00 AM », jamais « 08:00 AM » — et
    minuit comme midi s'écrivent 12 (« 12:00 AM » est minuit).
    """
    texte = (vingt_quatre or "").strip()
    try:
        heures, minutes = (int(x) for x in texte.replace("h", ":").split(":")[:2])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"heure illisible : {vingt_quatre!r}") from exc
    if not (0 <= heures <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"heure hors des bornes : {vingt_quatre!r}")
    suffixe = "AM" if heures < 12 else "PM"
    douze = heures % 12 or 12
    return f"{douze}:{minutes:02d} {suffixe}"


def _remplir_sous_libelle(page, libelle: str, valeur: str, *, dy: int = 32) -> None:
    """Clique le champ sous ce libellé, sélectionne tout, tape `valeur`."""
    cible = trouver(page, libelle, exact=True)
    if cible is None:
        raise LookupError(f"libellé « {libelle} » absent de l'écran.")
    page.mouse.click(cible["x"], cible["y"] + dy)
    page.wait_for_timeout(200)
    page.keyboard.press("Home")
    page.keyboard.press("Shift+End")
    page.keyboard.type(valeur, delay=35)
    page.wait_for_timeout(200)


def saisir_horaire(page, debut: str, fin: str, *, champ_heure: str = "Heure:",
                   dy: int = 32) -> None:
    """Renseigne l'horaire, via le dialogue « Sélectionner les heures » s'il s'ouvre.

    Cliquer le champ « Heure: » n'écrit pas l'intervalle : Celcat ouvre un
    dialogue à deux champs (« Heure de début », « Heure de fin ») et un OK
    (constaté le 01/09/2026 sur l'événement 1933212). Taper « 8:00 AM-9:30 AM »
    dans le début produit « 1 AM - 11:00 AM » et grise OK.
    """
    cible = trouver(page, champ_heure, exact=True)
    if cible is None:
        raise LookupError(f"libellé « {champ_heure} » absent du formulaire.")
    page.mouse.click(cible["x"], cible["y"] + dy)
    page.wait_for_timeout(700)
    if trouver(page, "Heure de début") or trouver(page, "Sélectionner les heures"):
        _remplir_sous_libelle(page, "Heure de début", heure_12h(debut), dy=dy)
        _remplir_sous_libelle(page, "Heure de fin", heure_12h(fin), dy=dy)
        ok = trouver(page, "OK", exact=True)
        if ok is None:
            raise LookupError("bouton OK du sélecteur d'heures introuvable.")
        page.mouse.click(ok["x"], ok["y"])
        page.wait_for_timeout(500)
        return
    page.keyboard.press("Home")
    page.keyboard.press("Shift+End")
    page.keyboard.type(intervalle_12h(debut, fin), delay=35)
    page.wait_for_timeout(200)


def intervalle_12h(debut: str, fin: str) -> str:
    """« 08:00 », « 10:00 » -> « 8:00 AM-10:00 AM ».

    Le champ « Heure: » de l'inspecteur porte l'intervalle ENTIER en une
    seule valeur, séparateur `-` sans espace : « 7:00 AM-11:59 PM ». Il n'y a
    pas deux champs à remplir.
    """
    return f"{heure_12h(debut)}-{heure_12h(fin)}"


# --- Choix de la semaine --------------------------------------------------

_TRIPLETS = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})")


def _dates_possibles(a: int, b: int, annee: int) -> list[_dt.date]:
    """Les lectures plausibles de `a/b/annee`, mois/jour ET jour/mois.

    Les deux relevés de `docs/CELCAT.md` se CONTREDISENT sur le format :
    « 4 (1/25/27-1/31/27) » ne se lit qu'en mois/jour, « 1 (04/01/27–10/01/27) »
    ne se lit qu'en jour/mois (avril→octobre ne serait pas une semaine). On ne
    tranche donc pas : on garde les deux, et c'est la cohérence de
    l'INTERVALLE qui départage (cf. `infobulle_designe_la_semaine`).
    """
    if annee < 100:
        annee += 2000
    sorties: list[_dt.date] = []
    for mois, jour in ((a, b), (b, a)):
        try:
            sorties.append(_dt.date(annee, mois, jour))
        except ValueError:
            continue
    return sorties


def infobulle_designe_la_semaine(texte: str, lundi: _dt.date) -> bool:
    """L'infobulle d'une cellule du mini-calendrier vise-t-elle CETTE semaine ?

    Format relevé : « <numéro> (<début>-<fin>) », dates en notation
    ambiguë. La règle qui lève l'ambiguïté sans rien supposer : il faut une
    lecture COHÉRENTE des deux dates telle que l'intervalle couvre six jours
    (lundi→dimanche) ET commence au lundi visé.

    Cette double exigence suffit. Pour la semaine du 4 janvier 2027,
    « 04/01/27–10/01/27 » ne tient qu'en jour/mois (4→10 janvier, six jours) ;
    la cellule du 1er avril, « 01/04/27–07/04/27 », est rejetée par les deux
    lectures — en mois/jour elle irait de janvier à juillet, en jour/mois elle
    commence au 1er avril. Aucune cellule voisine ne peut donc être prise pour
    la bonne, ce qui serait le pire des cas : saisir une semaine entière au
    mauvais endroit.
    """
    trouves = _TRIPLETS.findall(texte or "")
    if len(trouves) < 2:
        return False
    for i in range(len(trouves) - 1):
        debuts = _dates_possibles(*(int(x) for x in trouves[i]))
        fins = _dates_possibles(*(int(x) for x in trouves[i + 1]))
        for debut in debuts:
            if debut != lundi:
                continue
            if any((fin - debut).days == 6 for fin in fins):
                return True
    return False


# Le sélecteur de semaines occupe le bas du panneau de gauche, sous le titre
# « Semaines de l'emploi du temps » : six rangées de cellules d'environ 77 px,
# espacées de 79 (85 au passage d'un mois), encadrées par les noms de mois.
ZONE_SEMAINES = {"x_min": 0, "x_max": 940, "y_min": 855, "y_max": 1065}

# Les cellules NE PORTENT AUCUN TEXTE : seule celle en cours affiche son
# numéro. Les chercher par leur contenu — ce que faisait la première version
# — ne pouvait donc retrouver que la semaine DÉJÀ sélectionnée, et levait
# pour toutes les autres (constaté le 01/09/2026 : « semaine du 2026-09-07
# introuvable », alors qu'elle était à l'écran). On les énumère par leur
# géométrie, et c'est l'infobulle au survol qui dit laquelle est laquelle.
_JS_CELLULES_SEMAINE = """(zone) => {
  const out = [];
  for (const e of document.querySelectorAll('div')) {
    if (e.children.length) continue;
    const r = e.getBoundingClientRect();
    if (r.y < zone.y_min || r.y > zone.y_max) continue;
    if (r.x < zone.x_min || r.x > zone.x_max) continue;
    // Une cellule de semaine est large et plate ; les pastilles de 13 px et
    // les libellés de mois sont écartés par ces bornes.
    if (r.width < 40 || r.width > 90 || r.height < 6 || r.height > 30) continue;
    out.push({
      x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
      gauche: Math.round(r.x), haut: Math.round(r.y),
    });
  }
  return out;
}"""


# Deux `div` empilés pour une même cellule sont distants de 3 px ; deux
# cellules voisines de 79 en largeur et 26 en hauteur. Tout écart inférieur à
# cette marge désigne donc le même repère à l'écran.
_MARGE_CELLULE = 10


# Mini-calendrier de l'INSPECTEUR (relevé 01/09/2026) : mois Aug→Aug à
# y≈678, au-dessus de « Semaines: ». Distinct du sélecteur du panneau
# gauche (`ZONE_SEMAINES`, y 855–1065). C'est ici qu'on restreint l'événement
# après un `new` qui a coché 1-54.
ZONE_SEMAINES_FORMULAIRE = {"x_min": 900, "x_max": 1920, "y_min": 630, "y_max": 720}


def cellules_semaines(page, zone: dict | None = None) -> list[dict]:
    """Cellules du sélecteur, ordonnées comme elles se lisent.

    qooxdoo empile deux `div` par cellule (relevé : mêmes colonnes à y=869 et
    y=872). On les fusionne par PROXIMITÉ plutôt qu'en arrondissant : 869 et
    872 tombent de part et d'autre d'une borne d'arrondi, et deux cellules
    comptées pour une seule feraient sauter une semaine sur deux dans le
    calcul d'indice.
    """
    brutes = sorted(
        page.evaluate(_JS_CELLULES_SEMAINE, zone or ZONE_SEMAINES),
        key=lambda c: (c["haut"], c["gauche"]),
    )
    gardees: list[dict] = []
    for cellule in brutes:
        if any(
            abs(cellule["haut"] - g["haut"]) <= _MARGE_CELLULE
            and abs(cellule["gauche"] - g["gauche"]) <= _MARGE_CELLULE
            for g in gardees
        ):
            continue
        gardees.append(cellule)
    return gardees


def _infobulle(page, cellule: dict, *, connus: set[str], attente: int = 650) -> str:
    """Survole une cellule et rend l'infobulle apparue, s'il y en a une.

    L'infobulle n'est NI un `title`, NI un attribut qooxdoo : elle n'existe
    que le temps d'un survol réel. On compare donc les textes de la page
    avant/après pour isoler celui qui vient d'apparaître.
    """
    page.mouse.move(cellule["x"], cellule["y"])
    page.wait_for_timeout(attente)
    for f in feuilles(page):
        texte = f["texte"]
        if "/" in texte and texte not in connus:
            return texte
    return ""


def _lundi_de_l_infobulle(texte: str) -> _dt.date | None:
    """Le lundi que désigne une infobulle, ou rien si elle reste ambiguë.

    Format relevé le 01/09/2026 : « Week: 37 (9/7/26-9/13/26) », en
    mois/jour/an. On ne s'y fie pas pour autant : on retient la lecture — sur
    les deux possibles — qui donne un intervalle de six jours, exactement
    comme `infobulle_designe_la_semaine`, et on refuse quand les deux
    tiennent.
    """
    trouves = _TRIPLETS.findall(texte or "")
    if len(trouves) < 2:
        return None
    debuts = _dates_possibles(*(int(x) for x in trouves[0]))
    fins = _dates_possibles(*(int(x) for x in trouves[1]))
    coherents = {d for d in debuts if any((f - d).days == 6 for f in fins)}
    return coherents.pop() if len(coherents) == 1 else None


def choisir_semaine(page, lundi: _dt.date, *, delai: float = 90) -> dict:
    """Sélectionne la semaine du `lundi` donné dans le mini-calendrier.

    On SURVOLE avant de cliquer. Le sélecteur (« Semaines de l'emploi du
    temps », en bas du panneau) ne porte aucun attribut exploitable : ni
    `title`, ni `qxtooltip`, et ses cellules sont VIDES — seule celle en cours
    affiche son numéro. Survoler pour lire la date, puis cliquer, est le seul
    moyen de savoir sur quelle semaine on atterrit.

    On ne survole pas les 52 cellules pour autant. La première suffit à caler
    l'origine : une cellule vaut une semaine, dans l'ordre de lecture. On saute
    donc directement à la cellule calculée, et on VÉRIFIE son infobulle avant
    de cliquer ; ce n'est qu'en cas de désaccord qu'on balaie.

    Lève plutôt que de cliquer au hasard : une semaine mal choisie déverse
    une promotion entière de séances sur les mauvaises dates.
    """
    cellules = cellules_semaines(page)
    if not cellules:
        raise LookupError("sélecteur de semaines introuvable à l'écran.")

    connus = {f["texte"] for f in feuilles(page) if "/" in f["texte"]}
    origine = _lundi_de_l_infobulle(_infobulle(page, cellules[0], connus=connus))
    if origine is not None:
        indice = (lundi - origine).days // 7
        if 0 <= indice < len(cellules) and (lundi - origine).days % 7 == 0:
            candidate = cellules[indice]
            texte = _infobulle(page, candidate, connus=connus)
            if infobulle_designe_la_semaine(texte, lundi):
                page.mouse.click(candidate["x"], candidate["y"])
                page.wait_for_timeout(2500)
                return {"infobulle": texte, "x": candidate["x"], "y": candidate["y"]}

    # Repli : l'origine n'a pas pu être lue, ou la cellule calculée ne
    # correspond pas (année scolaire qui ne commence pas à la première
    # cellule, rangée incomplète…). On balaie, en s'arrêtant au délai.
    fin = time.time() + delai
    vues: list[str] = []
    for cellule in cellules:
        if time.time() > fin:
            break
        texte = _infobulle(page, cellule, connus=connus)
        if not texte:
            continue
        vues.append(texte)
        if infobulle_designe_la_semaine(texte, lundi):
            page.mouse.click(cellule["x"], cellule["y"])
            page.wait_for_timeout(2500)
            return {"infobulle": texte, "x": cellule["x"], "y": cellule["y"]}
    raise LookupError(
        f"semaine du {lundi.isoformat()} introuvable dans le sélecteur "
        f"(infobulles lues : {', '.join(sorted(set(vues))[:6]) or 'aucune'})."
    )


def restreindre_semaines_formulaire(page, lundi: _dt.date) -> int | None:
    """Coche UNE semaine dans l'inspecteur, celle du `lundi` donné.

    `new` crée un événement sur 54 semaines (`1-54 [=54]`). Enregistrer dans
    cet état recopierait la séance sur l'année (incident du 01/09/2026). Le
    mini-calendrier au-dessus de « Semaines: » est le même mécanisme que le
    sélecteur de gauche : cellules vides, infobulle au survol. Un clic sur
    la cellule de la semaine visée la restreint à `[=1]`.

    Ne lève pas si la restriction échoue : l'appelant relit `[=N]` et refuse
    d'enregistrer. On ne devine pas une semaine.
    """
    n = nombre_semaines_formulaire(page)
    if n == 1:
        return n
    for f in feuilles(page):
        if _NB_SEMAINES_FORMULAIRE.search(f["texte"] or ""):
            page.mouse.click(f["x"], f["y"])
            page.wait_for_timeout(400)
            break
    cellules = cellules_semaines(page, ZONE_SEMAINES_FORMULAIRE)
    if not cellules:
        return nombre_semaines_formulaire(page)

    connus = {f["texte"] for f in feuilles(page) if "/" in f["texte"]}
    origine = _lundi_de_l_infobulle(_infobulle(page, cellules[0], connus=connus))
    if origine is not None:
        indice = (lundi - origine).days // 7
        if 0 <= indice < len(cellules) and (lundi - origine).days % 7 == 0:
            candidate = cellules[indice]
            texte = _infobulle(page, candidate, connus=connus)
            if infobulle_designe_la_semaine(texte, lundi):
                page.mouse.click(candidate["x"], candidate["y"])
                page.wait_for_timeout(800)
                return nombre_semaines_formulaire(page)

    for cellule in cellules:
        texte = _infobulle(page, cellule, connus=connus)
        if texte and infobulle_designe_la_semaine(texte, lundi):
            page.mouse.click(cellule["x"], cellule["y"])
            page.wait_for_timeout(800)
            return nombre_semaines_formulaire(page)
    return nombre_semaines_formulaire(page)


# --- Session --------------------------------------------------------------

def connexion(page, base: str = BASE_PRODUCTION, role: str = ROLE_LECTURE,
              identifiant: str | None = None, mot_de_passe: str | None = None):
    """Base -> identifiants -> rôle -> OK.

    Les identifiants sont passés explicitement par le pilote (`driver.py`),
    qui les tient de l'appelant ; l'environnement ne sert que de repli pour
    une exploration lancée à la main.
    """
    page.goto(os.environ["CELCAT_URL"], wait_until="networkidle", timeout=90_000)
    attendre_texte(page, base, delai=45)
    cliquer_texte(page, base, exact=True, sauf="sur CELCAT-DB")
    cliquer_texte(page, "Connexion", exact=True, attendre=3500)

    ch = champs_saisie(page)
    champ_identifiant = next(c for c in ch if c["type"] == "text")
    champ_motdepasse = next(c for c in ch if c["type"] == "password")
    page.mouse.click(champ_identifiant["x"], champ_identifiant["y"])
    page.keyboard.type(identifiant or os.environ["CELCAT_UTILISATEUR"], delay=40)
    page.mouse.click(champ_motdepasse["x"], champ_motdepasse["y"])
    page.keyboard.type(mot_de_passe or os.environ["CELCAT_MOT_DE_PASSE"], delay=40)
    page.wait_for_timeout(300)

    if role and role != "par défaut":
        try:
            cliquer_texte(page, "Utiliser le rôle par défaut", attendre=800)
        except LookupError:
            # La case n'est pas une feuille du DOM et n'est pas toujours
            # repérable ; le déroulant s'ouvre sans elle.
            pass
        cliquer_texte(page, "par défaut", exact=True, attendre=1200)
        cliquer_texte(page, role, exact=True, attendre=1000)
    cliquer_texte(page, "OK", exact=True, attendre=9000)
    return page


def deconnexion(page) -> bool:
    """Rendre la session AVANT de fermer le navigateur.

    Celcat garde les sessions ouvertes ; en enchaîner sans se déconnecter
    finit par saturer le serveur, qui cesse alors d'afficher la liste des
    bases (constaté le 31/08/2026). Ce n'est pas une politesse, c'est une
    condition pour que la saisie suivante démarre.
    """
    try:
        cliquer_texte(page, "Déconnexion", attendre=2500)
        return True
    except LookupError:
        return False


# --- Extraction -----------------------------------------------------------

class Recolteur:
    """Collecte les réponses `udlResources.load` pendant qu'on navigue."""

    def __init__(self, page, type_id: int | None = None) -> None:
        self.page = page
        self.type_id = type_id
        self.lots: list[list[dict]] = []
        page.on("response", self._noter)

    def _noter(self, reponse) -> None:
        req = reponse.request
        if req.method != "POST" or "CTWebService.dll" not in reponse.url:
            return
        try:
            envoi = json.loads(req.post_data or "{}")
            if envoi.get("method") != "udlResources.load":
                return
            params = envoi.get("params") or []
            if self.type_id is not None and params and params[0] != self.type_id:
                return
            corps = lire_reponse(reponse.text())
        except Exception:  # noqa: BLE001 — une réponse illisible ne doit rien casser
            return
        res = corps.get("result")
        if isinstance(res, list) and res and isinstance(res[0], dict):
            self.lots.append(res)

    def enregistrements(self) -> list[dict]:
        vus, sortie = set(), []
        for lot in self.lots:
            for r in lot:
                cle = r.get("id") or json.dumps(r, sort_keys=True)[:80]
                if cle not in vus:
                    vus.add(cle)
                    sortie.append(r)
        return sortie


def filtrer(page, terme: str) -> None:
    """Saisit un terme dans le champ de filtre de la liste affichée.

    La recherche par nom EXACT est fiable — 21 salles sur 21 retrouvées le
    31/08/2026. Un préfixe trop court renvoie `ETooManyRecords` et
    l'application ne charge alors AUCUN détail : il faut chercher précis.
    """
    page.mouse.click(*CHAMP_FILTRE, click_count=3)
    page.keyboard.press("Control+a")
    page.keyboard.type(terme, delay=35)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2600)


def chercher(page, type_id: int, terme: str, *, tours: int = 8) -> list[dict]:
    """Cherche par NOM dans la ressource affichée, et récolte les résultats.

    Le pointeur est déplacé sur la LISTE avant de dérouler. `mouse.wheel`
    agit là où est le pointeur : laissé sur le champ de filtre, il ne fait
    rien défiler, et l'application ne charge que les lignes visibles — d'où
    une seule ligne récoltée par recherche tant que ce détail m'a échappé.
    """
    recolteur = Recolteur(page, type_id=type_id)
    filtrer(page, terme)
    page.mouse.move(*SUR_LA_LISTE)
    for _ in range(tours):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(450)
    return recolteur.enregistrements()


def cliquer_case_vide(page, *, jour: str = "Sun", heure: str = "10:00 AM") -> dict:
    """Sélectionne une case VIDE de la grille avant de cliquer `new`.

    `new` reprend la case courante. Sans cette étape, le 01/09/2026, le
    lundi 7h (événement global / férié) était sélectionné : Celcat a ouvert
    le panneau Conflits à la place du formulaire, et créé l'événement
    1933212. L'ancien autoclicker visait déjà le dimanche pour cette raison.
    """
    colonne = trouver(page, jour, exact=True)
    ligne = trouver(page, heure, exact=True)
    if colonne is None or ligne is None:
        raise LookupError(
            f"case vide {jour} {heure} introuvable dans la grille : "
            "`new` n'a pas été cliqué."
        )
    x, y = int(colonne["x"]), int(ligne["y"]) + 12
    # Simple clic seulement. Un double-clic ouvre l'inspecteur de
    # l'événement DÉJÀ sous la case (1933212 le 01/09/2026) : on modifierait
    # un fantôme au lieu d'en créer un. `new` crée, le double-clic édite.
    page.mouse.click(x, y)
    page.wait_for_timeout(400)
    return {"x": x, "y": y, "jour": jour, "heure": heure}


def fermer_panneau_conflits(page) -> bool:
    """Rend True si le panneau Conflits était ouvert et qu'on est revenu aux groupes.

    Après un `new` sur une case occupée, Celcat remplace la liste de
    ressources par « Conflits ». Le formulaire de droite n'apparaît pas tant
    que ce panneau tient le premier plan. On rétablit Groupes — c'est aussi
    là qu'on prendra les lignes à glisser-déposer.
    """
    if trouver(page, "Conflits", exact=True) is None:
        return False
    ouvrir_ressource(page, TYPE_GROUPES)
    page.wait_for_timeout(600)
    return True


def premiere_ligne(page, terme: str) -> dict:
    """La ligne de la liste qui porte ce texte, une fois le filtre appliqué.

    Sert de point de PRISE pour un glisser-déposer vers le formulaire, et de
    cible de double-clic pour ouvrir un emploi du temps de groupe. Lève si
    rien ne correspond : déposer une ligne prise au hasard rattacherait la
    séance à la mauvaise ressource, ce qui, sur un outil qui alimente la
    paie, ne se voit qu'au moment de payer.
    """
    cible = trouver(page, terme)
    if cible is None:
        raise LookupError(f"aucune ligne « {terme} » dans la liste affichée.")
    return cible


def double_cliquer_texte(page, texte: str, *, attendre: int = 2500) -> dict:
    """Un double-clic sur un groupe ouvre son emploi du temps (31/08/2026)."""
    cible = premiere_ligne(page, texte)
    page.mouse.click(cible["x"], cible["y"], click_count=2)
    page.wait_for_timeout(attendre)
    return cible


def titre_panneau_gauche(page) -> str:
    """Le titre du panneau de ressources, sous la barre de menu.

    Relevé : « Groupes » / « Départements » vers (78, 40). Les items de
    menu (« Affichage », « Timetabler ») sont plus hauts (y≈15).
    """
    for f in feuilles(page):
        if 28 <= f["y"] <= 52 and 40 <= f["x"] <= 220:
            if f["texte"] not in {"minimize", "Nouveau", "Nom", "I"}:
                return f["texte"]
    return ""


def ouvrir_timetabler(page) -> None:
    """Passe l'écran Bienvenue : tuile Timetabler, puis le dialogue d'ouverture."""
    if titre_panneau_gauche(page) != "Bienvenue":
        return
    cible = None
    for f in feuilles(page):
        if f["texte"] == "Timetabler" and int(f["y"]) > 80 and int(f["x"]) > 0:
            cible = f
            break
    if cible is None:
        raise LookupError("tuile Timetabler introuvable sur Bienvenue")
    page.mouse.click(int(cible["x"]), int(cible["y"]), click_count=2)
    page.wait_for_timeout(1600)
    dialogue = trouver(page, "Ouvrir l'emploi du temps", exact=True)
    if dialogue is not None:
        page.mouse.click(int(dialogue["x"]), int(dialogue["y"]))
        page.wait_for_timeout(1200)
    for label in ("Ouvrir", "OK"):
        bouton = trouver(page, label, exact=True)
        if bouton is None or int(bouton["y"]) <= 80:
            continue
        page.mouse.click(int(bouton["x"]), int(bouton["y"]))
        page.wait_for_timeout(1200)
        break
    fin = time.time() + 20
    while time.time() < fin:
        titre = titre_panneau_gauche(page)
        if titre and titre != "Bienvenue":
            page.wait_for_timeout(800)
            return
        page.wait_for_timeout(400)
    raise TimeoutError("Timetabler ne s'ouvre pas (toujours sur Bienvenue)")


def ouvrir_ressource(page, type_id: int, *, repere: str | None = None) -> None:
    """Ouvre la liste de ressources de ce type, d'après le TITRE du panneau.

    Un clic aux Y figés de `ICONES` ne suffit plus : le 01/09/2026, viser
    Groupes à y=266 a ouvert Départements (type 610). On clique d'abord à
    l'ancienne position, on vérifie le titre, et on balaie la colonne si
    ce n'est pas le bon panneau.
    """
    ouvrir_timetabler(page)
    titre = repere or TITRES_PANNEAU[type_id]
    if titre_panneau_gauche(page) == titre:
        page.wait_for_timeout(400)
        return
    page.mouse.click(20, ICONES[type_id])
    page.wait_for_timeout(900)
    if titre_panneau_gauche(page) == titre:
        page.wait_for_timeout(400)
        return
    for y in range(48, 430, 14):
        page.mouse.click(18, y)
        page.wait_for_timeout(400)
        if titre_panneau_gauche(page) == titre:
            page.wait_for_timeout(400)
            return
    raise LookupError(f"panneau « {titre} » introuvable dans la colonne d'icônes.")


def salles_trouvees(enregistrements: list[dict]) -> list[dict]:
    """Ne garde que les salles, en ne retenant que ce qui nous sert."""
    return [
        {
            "nom": r.get("name"),
            "capacite": r.get("default_capacity"),
            "site": r.get("custom1"),
            "surface": r.get("area"),
            "id": r.get("id"),
        }
        for r in enregistrements
        if r.get("_type_") == "Room" and r.get("name")
    ]


def nom_groupe_celcat(semestre: str, libelle: str, annee: str = "2024") -> str:
    """Nom Celcat d'un groupe : « BUT MMI S1 TD AB - 2024 ».

    Convention vérifiée le 31/08/2026 sur S1, S3 et S5, en CM, TD et TP. Le
    suffixe d'année est celui de la COHORTE, pas celui de la base : dans
    `URCA_2026`, les groupes s'appellent toujours « - 2024 ». Chercher sans
    le suffixe suffit d'ailleurs à les retrouver, ce qui évite d'avoir à
    deviner l'année.
    """
    return f"BUT MMI {semestre} {libelle} - {annee}".strip()
