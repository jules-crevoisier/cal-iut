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

# Colonne d'icônes à gauche : ordonnée de chaque type de ressource.
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


# --- Session --------------------------------------------------------------

def connexion(page, base: str = BASE_PRODUCTION, role: str = ROLE_LECTURE):
    """Base -> identifiants -> rôle -> OK."""
    page.goto(os.environ["CELCAT_URL"], wait_until="networkidle", timeout=90_000)
    attendre_texte(page, base, delai=45)
    cliquer_texte(page, base, exact=True, sauf="sur CELCAT-DB")
    cliquer_texte(page, "Connexion", exact=True, attendre=3500)

    ch = champs_saisie(page)
    identifiant = next(c for c in ch if c["type"] == "text")
    motdepasse = next(c for c in ch if c["type"] == "password")
    page.mouse.click(identifiant["x"], identifiant["y"])
    page.keyboard.type(os.environ["CELCAT_UTILISATEUR"], delay=40)
    page.mouse.click(motdepasse["x"], motdepasse["y"])
    page.keyboard.type(os.environ["CELCAT_MOT_DE_PASSE"], delay=40)
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


def chercher(page, type_id: int, terme: str, *, tours: int = 8) -> list[dict]:
    """Cherche par NOM dans la ressource affichée, et récolte les résultats.

    La recherche par nom EXACT est fiable — 21 salles sur 21 retrouvées le
    31/08/2026. Un préfixe trop court renvoie `ETooManyRecords` et
    l'application ne charge alors AUCUN détail : il faut chercher précis.

    Le pointeur est déplacé sur la LISTE avant de dérouler. `mouse.wheel`
    agit là où est le pointeur : laissé sur le champ de filtre, il ne fait
    rien défiler, et l'application ne charge que les lignes visibles — d'où
    une seule ligne récoltée par recherche tant que ce détail m'a échappé.
    """
    recolteur = Recolteur(page, type_id=type_id)
    page.mouse.click(*CHAMP_FILTRE, click_count=3)
    page.keyboard.press("Control+a")
    page.keyboard.type(terme, delay=35)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2600)
    page.mouse.move(*SUR_LA_LISTE)
    for _ in range(tours):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(450)
    return recolteur.enregistrements()


def ouvrir_ressource(page, type_id: int, *, repere: str = "Département") -> None:
    page.mouse.click(20, ICONES[type_id])
    attendre_texte(page, repere, delai=40)
    page.wait_for_timeout(1200)


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
