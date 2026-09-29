"""Anti-aspiration : limiter et bloquer les clients qui aspirent le serveur
(29/09/2026, cf. docs/ANTI-ASPIRATION.md pour l'exploitation).

Constat : les liens personnels publics (`?t=<n'importe quoi>`, cf.
`api/auth.py::verify_personal_link_param`) ouvrent `/app-state`, `/meta`,
`/timetable`, `/api/v1/version` et les flux `/ics/…` sans aucune
vérification — décision utilisateur du 28/08/2026, NON remise en cause ici.
On ne peut donc pas refuser « par jeton » : on identifie le client par son
IP réelle (plus son User-Agent), on limite son débit, on le bloque.

Trois modes, variable `CAL_IUT_ANTI_ASPIRATION` :
- `off` (DÉFAUT) : le middleware ne fait RIEN, pas même compter. Aucun
  changement de comportement tant que la variable n'est pas posée.
- `observe` : compte, journalise les dépassements (logger
  `cal_iut.anti_aspiration`), laisse tout passer. Les blocages MANUELS
  s'appliquent déjà (un blocage manuel est une décision explicite).
- `enforce` : 429 + `Retry-After` au-delà du budget, et bannissement
  temporaire automatique d'une IP qui insiste.

Identité et catégorie d'une requête (cf. `classer`) :
- clé API (`Authorization: Bearer caliut_…`, ou le jeton MCP
  d'environnement) → catégorie `api`, identité = le compte ;
- cookie de session signé → catégorie `appli`, identité = le compte ;
- sinon anonyme, identité = l'IP : `sonde` (numéro de révision), `ics`
  (flux d'agenda), `public` (tout le reste : liens `?t=`, pages) ;
- `statique` (`/assets/`, `/favicon.svg`, `/robots.txt`, `/health`,
  `/healthz`) : jamais limité ni compté.

Un compte a des budgets plus larges qu'une IP anonyme : il a fallu un
mot de passe pour l'obtenir, et un utilisateur connecté fait beaucoup plus
de requêtes (glisser-déposer, vérifications au survol).

Un seul processus uvicorn sert l'API (cf. Dockerfile) : tout vit en
mémoire, sauf la liste de blocage, persistée dans `data/state/
blocages.json`. Un redémarrage remet compteurs et seaux à zéro — sans
importance pour un frein.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cal_iut.api.limiteur import SeauxAJetons

logger = logging.getLogger("cal_iut.anti_aspiration")

MODE_ENV = "CAL_IUT_ANTI_ASPIRATION"
MODES = ("off", "observe", "enforce")

# Plages privées : les proxys (Traefik, nginx) vivent sur le réseau Docker
# interne. Utilisé par `cal-iut serve` pour dire à uvicorn à QUI il peut
# faire confiance pour `X-Forwarded-For` (cf. `proxys_de_confiance`).
PROXYS_ENV = "CAL_IUT_PROXYS_DE_CONFIANCE"
PROXYS_DEFAUT = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"


def proxys_de_confiance() -> str:
    """Adresses (ou plages) dont uvicorn accepte `X-Forwarded-For`.

    Auparavant `FORWARDED_ALLOW_IPS=*` (Dockerfile) : uvicorn prenait alors
    la PREMIÈRE adresse de l'en-tête, que le client écrit lui-même — un
    `curl -H "X-Forwarded-For: 1.2.3.4"` suffisait à changer d'IP à chaque
    requête et à passer sous tout plafond par IP. Avec une liste, uvicorn
    lit l'en-tête de DROITE à gauche et s'arrête sur la première adresse
    qui n'est pas un proxy de confiance : celle qu'a vue le dernier proxy,
    qu'aucun client ne peut choisir. nginx écrase de plus l'en-tête avec
    l'IP qu'il a lui-même calculée (cf. `frontend/nginx.conf.template`)."""
    return (os.environ.get(PROXYS_ENV) or "").strip() or PROXYS_DEFAUT


def mode() -> str:
    """Mode courant — relu à chaque requête (un `os.environ.get`, rien de
    plus) : les tests le changent à chaud, et une valeur inconnue retombe
    sur `off`, jamais sur un blocage."""
    valeur = (os.environ.get(MODE_ENV) or "off").strip().lower()
    return valeur if valeur in MODES else "off"


# ---------------------------------------------------------------------------
# Configuration : budgets par catégorie, bannissement, IP exemptées.
# ---------------------------------------------------------------------------

_UNITES = {
    "s": 1, "sec": 1, "seconde": 1, "secondes": 1,
    "m": 60, "min": 60, "minute": 60, "minutes": 60,
    "h": 3600, "heure": 3600, "heures": 3600,
    "j": 86400, "jour": 86400, "jours": 86400, "d": 86400,
}
_DUREE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([a-z]*)\s*$")


def lire_duree(texte: str) -> float:
    """`"30s"`, `"10min"`, `"1h"`, `"24h"`, `"7j"` → secondes. Un nombre seul
    est en secondes. Lève `ValueError` sur toute autre forme."""
    m = _DUREE_RE.match(str(texte).lower())
    if not m:
        raise ValueError(f"durée illisible : {texte!r} (ex. 30s, 10min, 1h, 7j)")
    unite = m.group(2) or "s"
    if unite not in _UNITES:
        raise ValueError(f"unité de durée inconnue : {unite!r} (s, min, h, j)")
    secondes = float(m.group(1).replace(",", ".")) * _UNITES[unite]
    if secondes <= 0:
        raise ValueError("une durée doit être positive")
    return secondes


def lire_debit(texte: str) -> tuple[int, float]:
    """`"120/min"`, `"2/s"`, `"3000/h"` → (nombre, période en s). Un nombre
    seul s'entend par minute."""
    brut = str(texte).strip().lower()
    nombre, _, periode = brut.partition("/")
    n = int(nombre)
    if n <= 0:
        raise ValueError("un budget doit être positif")
    return n, (lire_duree(f"1{periode}") if periode else 60.0)


@dataclass(frozen=True)
class Budget:
    categorie: str
    nombre: int
    periode_s: float
    rafale: int
    description: str

    @property
    def debit(self) -> float:
        return self.nombre / self.periode_s


# Valeurs par défaut — (nombre, période, rafale). Pensées pour ne JAMAIS
# gêner un usage humain, et à calibrer en mode `observe` avant tout
# `enforce` (cf. docs/ANTI-ASPIRATION.md) :
# - public : un humain sur un lien public fait 3-4 requêtes à l'ouverture
#   (`/app-state`, `/meta`…) puis plus rien (la navigation entre semaines
#   est locale). Mais une IP peut cacher tout un réseau (NAT de l'IUT, 4G) :
#   120/min avec une rafale de 120, c'est 30 ouvertures simultanées puis
#   une ouverture toutes les deux secondes, en continu, depuis une seule IP.
#   Un aspirateur qui relit `/app-state` en boucle dépasse vite.
# - ics : les agendas (Google, Outlook, Apple) relisent chaque flux abonné
#   toutes les 15 min à quelques heures — mais Google et Microsoft le font
#   depuis QUELQUES IP partagées par tous leurs utilisateurs. Même budget
#   que public, compté à part pour qu'un navigateur et un agenda derrière
#   la même IP ne se gênent pas.
# - sonde : `/api/v1/version` et `/ics/version`, sondés toutes les 30 s
#   (connecté) ou toutes les 3 min (lien public), onglet visible seulement.
#   60/min, c'est 30 onglets connectés ou 180 onglets publics derrière une
#   même IP.
# - appli : un compte connecté — l'écran Promo relit, vérifie au survol
#   pendant un glisser-déposer (`/validate`), recharge après chaque action.
#   600/min (10/s) et une rafale de 300 couvrent un chargement complet et
#   plusieurs onglets.
# - api : clé API (scripts, `cal-iut prod …`, Claude via MCP). Un client
#   légitime de l'API v1 revalide avec `If-None-Match` (ETag, 304 sans
#   corps) et n'a aucune raison de dépasser 5/s en continu ; le MCP fait
#   des rafales courtes, d'où une rafale de 150.
_BUDGETS_DEFAUT: dict[str, tuple[str, int, str]] = {
    "public": ("120/min", 120, "Lien public, pages, sans compte (par IP)"),
    "ics": ("120/min", 120, "Flux d'agenda .ics (par IP)"),
    "sonde": ("60/min", 30, "Numéro de révision sondé par les onglets ouverts (par IP)"),
    "appli": ("600/min", 300, "Application connectée (par compte)"),
    "api": ("300/min", 150, "Clé API et MCP (par compte)"),
}
CATEGORIES = tuple(_BUDGETS_DEFAUT)

# Bannissement automatique (mode `enforce`) : une IP anonyme qui reçoit
# `SEUIL` refus en moins de `FENETRE` est bannie `DUREE`. Un client correct
# respecte `Retry-After` et reçoit UN refus par épisode ; 30 refus en
# 10 minutes, c'est un client qui ignore la réponse et insiste. Jamais un
# compte (on ne bannit pas un administrateur de son propre outil) : un
# compte reçoit des 429, rien de plus.
_BAN_DEFAUT = {"seuil": 30, "fenetre": "10min", "duree": "1h"}

_VARIABLES = (
    MODE_ENV, "CAL_IUT_AA_EXEMPTS", "CAL_IUT_AA_BAN_SEUIL", "CAL_IUT_AA_BAN_FENETRE",
    "CAL_IUT_AA_BAN_DUREE",
) + tuple(f"CAL_IUT_AA_{c.upper()}{s}" for c in CATEGORIES for s in ("", "_BURST"))


@dataclass(frozen=True)
class Configuration:
    budgets: dict[str, Budget]
    ban_seuil: int
    ban_fenetre_s: float
    ban_duree_s: float
    exemptes: tuple[Any, ...]  # ip_network
    exemptes_texte: tuple[str, ...]


def _lire_env(nom: str, defaut: Any, lecteur) -> Any:
    brut = os.environ.get(nom)
    if brut is None or not brut.strip():
        return lecteur(defaut) if isinstance(defaut, str) else defaut
    try:
        return lecteur(brut)
    except (ValueError, TypeError):
        # Jamais un plantage au démarrage pour une faute de frappe dans une
        # variable de frein : la valeur par défaut, et une trace.
        logger.warning("%s=%r illisible, valeur par défaut utilisée (%r)", nom, brut, defaut)
        return lecteur(defaut) if isinstance(defaut, str) else defaut


def _construire_configuration() -> Configuration:
    budgets = {}
    for cat, (debit, rafale, description) in _BUDGETS_DEFAUT.items():
        nombre, periode = _lire_env(f"CAL_IUT_AA_{cat.upper()}", debit, lire_debit)
        r = _lire_env(f"CAL_IUT_AA_{cat.upper()}_BURST", rafale, int)
        budgets[cat] = Budget(cat, nombre, periode, max(1, int(r)), description)
    exemptes, textes = [], []
    for morceau in (os.environ.get("CAL_IUT_AA_EXEMPTS") or "").split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            exemptes.append(ipaddress.ip_network(morceau, strict=False))
            textes.append(morceau)
        except ValueError:
            logger.warning("CAL_IUT_AA_EXEMPTS : %r n'est ni une IP ni une plage, ignoré", morceau)
    return Configuration(
        budgets=budgets,
        ban_seuil=max(1, int(_lire_env("CAL_IUT_AA_BAN_SEUIL", _BAN_DEFAUT["seuil"], int))),
        ban_fenetre_s=_lire_env("CAL_IUT_AA_BAN_FENETRE", _BAN_DEFAUT["fenetre"], lire_duree),
        ban_duree_s=_lire_env("CAL_IUT_AA_BAN_DUREE", _BAN_DEFAUT["duree"], lire_duree),
        exemptes=tuple(exemptes),
        exemptes_texte=tuple(textes),
    )


_config_cache: tuple[tuple, Configuration] | None = None
_config_verrou = threading.Lock()


def configuration() -> Configuration:
    """Relue quand une variable change (signature des valeurs brutes) : une
    quinzaine de `os.environ.get` par requête, le reste en cache."""
    global _config_cache
    signature = tuple(os.environ.get(v) for v in _VARIABLES)
    cache = _config_cache
    if cache is not None and cache[0] == signature:
        return cache[1]
    with _config_verrou:
        conf = _construire_configuration()
        _config_cache = (signature, conf)
        return conf


# ---------------------------------------------------------------------------
# Classement d'une requête : catégorie + identité.
# ---------------------------------------------------------------------------

_STATIQUES_PREFIXES = ("/assets/",)
_STATIQUES = frozenset({"/favicon.svg", "/favicon.ico", "/robots.txt", "/health", "/healthz"})
_SANTE = frozenset({"/health", "/healthz"})
_SONDES = frozenset({"/api/v1/version", "/ics/version", "/auth/status", "/auth/me"})

# Clé API → compte, gardé 2 minutes : sans ce cache, chaque requête d'un
# script ferait une lecture SQLite de plus que `require_auth`. Ne sert qu'à
# CHOISIR UN BUDGET — l'accès lui-même reste décidé par `require_auth`, qui
# relit la clé en base à chaque fois (une clé révoquée est refusée tout de
# suite, elle garde seulement son budget de compte deux minutes de plus).
_CLES_TTL_S = 120.0
_CLES_MAX = 2000
_cles_cache: dict[str, tuple[float, int | None]] = {}
_cles_verrou = threading.Lock()


def _compte_depuis_cle(brut: str) -> int | None:
    from cal_iut.api.mcp_keys import hash_mcp_token

    empreinte = hash_mcp_token(brut)
    maintenant = time.monotonic()
    with _cles_verrou:
        trouve = _cles_cache.get(empreinte)
        if trouve is not None and maintenant - trouve[0] < _CLES_TTL_S:
            return trouve[1]
    compte: int | None = None
    try:
        from cal_iut.api.state import get_state
        from cal_iut.db.accounts_repository import AccountRepository
        from cal_iut.db.session import get_db

        db = get_db(get_state().db_path)
        try:
            cle = AccountRepository(db).get_active_mcp_key_by_hash(empreinte)
            compte = int(cle.user_id) if cle is not None else None
        finally:
            db.close()
    except Exception:
        logger.exception("anti-aspiration : lecture de la clé API impossible")
    with _cles_verrou:
        if len(_cles_cache) >= _CLES_MAX:
            _cles_cache.clear()
        _cles_cache[empreinte] = (maintenant, compte)
    return compte


def _cookie(entete: str, nom: str) -> str | None:
    for morceau in entete.split(";"):
        cle, _, valeur = morceau.strip().partition("=")
        if cle == nom:
            return valeur.strip().strip('"') or None
    return None


def classer(chemin: str, ip: str, authorization: str | None, cookies: str | None) -> tuple[str, str, int | None]:
    """(catégorie, identité, id du compte ou None) d'une requête."""
    if chemin.startswith(_STATIQUES_PREFIXES) or chemin in _STATIQUES:
        return "statique", f"ip:{ip}", None
    if authorization and authorization.startswith("Bearer "):
        brut = authorization[len("Bearer "):].strip()
        if brut:
            jeton_env = (os.environ.get("CAL_IUT_MCP_TOKEN") or "").strip()
            if jeton_env and len(brut) == len(jeton_env) and hmac.compare_digest(brut, jeton_env):
                return "api", "cle:mcp-env", None
            compte = _compte_depuis_cle(brut)
            if compte is not None:
                return "api", f"compte:{compte}", compte
    if cookies:
        from cal_iut.api import accounts

        jeton = _cookie(cookies, accounts.ACCOUNT_SESSION_COOKIE)
        # Signature HMAC seule, sans base : un cookie authentique a été émis
        # par ce serveur à un vrai compte. Suffisant pour choisir un budget.
        compte = accounts.verify_account_session_token(jeton) if jeton else None
        if compte is not None:
            return "appli", f"compte:{compte}", int(compte)
    if chemin in _SONDES:
        return "sonde", f"ip:{ip}", None
    if chemin.startswith("/ics/"):
        return "ics", f"ip:{ip}", None
    return "public", f"ip:{ip}", None


def _ip_normalisee(ip: str) -> tuple[str, Any]:
    try:
        adresse = ipaddress.ip_address(ip)
    except ValueError:
        return ip, None
    if isinstance(adresse, ipaddress.IPv6Address) and adresse.ipv4_mapped is not None:
        adresse = adresse.ipv4_mapped
    return str(adresse), adresse


# ---------------------------------------------------------------------------
# Liste de blocage persistante (data/state/blocages.json).
# ---------------------------------------------------------------------------

TYPES_BLOCAGE = ("ip", "cidr", "user_agent")


def _path() -> Path:
    # `data/state/`, comme le reste de l'état persisté (volume Docker).
    return Path(__file__).resolve().parents[3] / "data" / "state" / "blocages.json"


def _maintenant_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.timestamp()


@dataclass
class Blocage:
    id: str
    type: str
    valeur: str
    motif: str
    auteur: str
    cree_le: str
    expire_le: str | None = None
    automatique: bool = False

    def expire(self, maintenant: float) -> bool:
        fin = _epoch(self.expire_le)
        return fin is not None and fin <= maintenant


class ErreurBlocage(ValueError):
    pass


def valider_cible(type_: str, valeur: str) -> str:
    """Valeur normalisée d'un blocage, ou `ErreurBlocage` explicite."""
    valeur = (valeur or "").strip()
    if type_ == "ip":
        try:
            return _ip_normalisee(str(ipaddress.ip_address(valeur)))[0]
        except ValueError as exc:
            raise ErreurBlocage(f"« {valeur} » n'est pas une adresse IP.") from exc
    if type_ == "cidr":
        try:
            reseau = ipaddress.ip_network(valeur, strict=False)
        except ValueError as exc:
            raise ErreurBlocage(f"« {valeur} » n'est pas une plage d'adresses (ex. 203.0.113.0/24).") from exc
        # Garde-fou : une plage /7 bloque 33 millions d'adresses — faute de
        # frappe bien plus probable qu'intention.
        minimum = 8 if reseau.version == 4 else 32
        if reseau.prefixlen < minimum:
            raise ErreurBlocage(f"Plage trop large (/{reseau.prefixlen}) : /{minimum} au minimum.")
        return str(reseau)
    if type_ == "user_agent":
        if len(valeur) < 3:
            raise ErreurBlocage("Motif de User-Agent trop court (3 caractères au minimum).")
        return valeur
    raise ErreurBlocage(f"Type de blocage inconnu : {type_!r} (ip, cidr, user_agent).")


class ListeBlocages:
    """Liste de blocage : IP exactes (dictionnaire), plages (liste), motifs
    de User-Agent (sous-chaîne insensible à la casse). Relue depuis le
    disque quand le fichier change (au plus un `stat` toutes les 5 s) : un
    `cal-iut bloquer` lancé dans le conteneur prend effet sans redémarrage.
    Écriture atomique (`celcat.fichiers.ecrire_atomique`)."""

    _RELECTURE_S = 5.0

    def __init__(self) -> None:
        self._verrou = threading.RLock()
        self._blocages: list[Blocage] = []
        self._ips: dict[str, Blocage] = {}
        self._reseaux: list[tuple[Any, Blocage]] = []
        self._uas: list[tuple[str, Blocage]] = []
        self._signature: tuple | None = None
        self._chemin_charge: Path | None = None
        self._dernier_controle = -math.inf

    # -- disque --
    def _signature_fichier(self, chemin: Path) -> tuple | None:
        try:
            st = chemin.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _recharger_si_besoin(self, forcer: bool = False) -> None:
        chemin = _path()
        maintenant = time.monotonic()
        if not forcer and chemin == self._chemin_charge and maintenant - self._dernier_controle < self._RELECTURE_S:
            return
        self._dernier_controle = maintenant
        signature = self._signature_fichier(chemin)
        if not forcer and chemin == self._chemin_charge and signature == self._signature:
            return
        blocages: list[Blocage] = []
        if signature is not None:
            try:
                donnees = json.loads(chemin.read_text(encoding="utf-8"))
                for brut in donnees.get("blocages", []):
                    champs = {k: brut.get(k) for k in Blocage.__dataclass_fields__ if k in brut}
                    blocages.append(Blocage(**champs))
            except (OSError, ValueError, TypeError):
                # Fichier illisible : on garde la liste en mémoire plutôt que
                # de tout débloquer d'un coup, et on le dit.
                logger.exception("anti-aspiration : %s illisible, liste précédente conservée", chemin)
                self._signature = signature
                self._chemin_charge = chemin
                return
        self._indexer(blocages)
        self._signature = signature
        self._chemin_charge = chemin

    def _indexer(self, blocages: list[Blocage]) -> None:
        ips, reseaux, uas = {}, [], []
        for b in blocages:
            if b.type == "ip":
                ips[_ip_normalisee(b.valeur)[0]] = b
            elif b.type == "cidr":
                try:
                    reseaux.append((ipaddress.ip_network(b.valeur, strict=False), b))
                except ValueError:
                    continue
            elif b.type == "user_agent":
                uas.append((b.valeur.lower(), b))
        self._blocages, self._ips, self._reseaux, self._uas = blocages, ips, reseaux, uas

    def _ecrire(self, blocages: list[Blocage]) -> None:
        from cal_iut.celcat.fichiers import ecrire_atomique

        chemin = _path()
        texte = json.dumps(
            {"version": 1, "blocages": [asdict(b) for b in blocages]}, ensure_ascii=False, indent=2
        )
        ecrire_atomique(chemin, texte)
        self._indexer(blocages)
        self._signature = self._signature_fichier(chemin)
        self._chemin_charge = chemin

    # -- lecture --
    def lister(self, *, inclure_expires: bool = False) -> list[Blocage]:
        with self._verrou:
            self._recharger_si_besoin(forcer=True)
            maintenant = time.time()
            return [b for b in self._blocages if inclure_expires or not b.expire(maintenant)]

    def correspondance(self, ip: str, user_agent: str, *, inclure_auto: bool) -> Blocage | None:
        """Premier blocage actif qui vise ce client, ou `None`."""
        with self._verrou:
            self._recharger_si_besoin()
            if not self._blocages:
                return None
            maintenant = time.time()

            def actif(b: Blocage) -> bool:
                return (inclure_auto or not b.automatique) and not b.expire(maintenant)

            texte, adresse = _ip_normalisee(ip)
            b = self._ips.get(texte)
            if b is not None and actif(b):
                return b
            if adresse is not None:
                for reseau, b in self._reseaux:
                    if adresse.version == reseau.version and adresse in reseau and actif(b):
                        return b
            if user_agent and self._uas:
                ua = user_agent.lower()
                for motif, b in self._uas:
                    if motif in ua and actif(b):
                        return b
            return None

    # -- écriture --
    def ajouter(
        self, type_: str, valeur: str, motif: str, auteur: str, duree_s: float | None = None,
        *, automatique: bool = False,
    ) -> Blocage:
        valeur = valider_cible(type_, valeur)
        motif = (motif or "").strip()[:200] or "sans motif"
        maintenant = time.time()
        expire_le = (
            datetime.fromtimestamp(maintenant + duree_s, UTC).isoformat(timespec="seconds")
            if duree_s else None
        )
        with self._verrou:
            self._recharger_si_besoin(forcer=True)
            # Expirés purgés à chaque écriture : le fichier ne grossit pas.
            garder = [b for b in self._blocages if not b.expire(maintenant)]
            # Même cible déjà bloquée : on remplace (nouvelle durée, nouveau
            # motif) plutôt que d'empiler des doublons.
            garder = [b for b in garder if not (b.type == type_ and b.valeur.lower() == valeur.lower())]
            nouveau = Blocage(
                id=uuid.uuid4().hex[:10], type=type_, valeur=valeur, motif=motif,
                auteur=(auteur or "inconnu")[:120], cree_le=_maintenant_iso(), expire_le=expire_le,
                automatique=automatique,
            )
            self._ecrire([*garder, nouveau])
            return nouveau

    def retirer(self, blocage_id: str) -> Blocage | None:
        with self._verrou:
            self._recharger_si_besoin(forcer=True)
            cible = next((b for b in self._blocages if b.id == blocage_id), None)
            if cible is None:
                return None
            maintenant = time.time()
            self._ecrire([b for b in self._blocages if b.id != blocage_id and not b.expire(maintenant)])
            return cible

    def vider_cache(self) -> None:
        """Oublie la liste en mémoire (tests) — relue du disque au prochain appel."""
        with self._verrou:
            self._indexer([])
            self._signature = None
            self._chemin_charge = None
            self._dernier_controle = -math.inf


blocages = ListeBlocages()


# ---------------------------------------------------------------------------
# Comptage du trafic, par IP, en mémoire bornée.
# ---------------------------------------------------------------------------

PAS_S = 300  # tranches de 5 minutes
_TRANCHES_24H = 86400 // PAS_S
FENETRES = {"15min": 900, "1h": 3600, "24h": 86400}
_MAX_CLIENTS = 20_000
_MAX_UA, _MAX_CHEMINS, _MAX_T = 5, 8, 200

# Indices des compteurs d'une tranche.
_REQ, _DEPASSE, _REFUS403, _PUBLIQUES = 0, 1, 2, 3


def _incrementer_borne(compteurs: dict[str, int], cle: str, maximum: int) -> None:
    """Compteur à taille bornée (algorithme « space-saving ») : une clé
    nouvelle remplace la moins vue, en héritant de son compte. Les clés
    fréquentes restent, coût constant (`maximum` est petit)."""
    if cle in compteurs:
        compteurs[cle] += 1
    elif len(compteurs) < maximum:
        compteurs[cle] = 1
    else:
        moindre = min(compteurs, key=compteurs.__getitem__)
        compteurs[cle] = compteurs.pop(moindre) + 1


class _Client:
    __slots__ = ("categories", "chemins", "compte", "dernier", "ordre", "refus", "t_vus", "tranches", "ua")

    def __init__(self) -> None:
        self.tranches: dict[int, list[int]] = {}
        self.ordre: deque[int] = deque()
        self.ua: dict[str, int] = {}
        self.chemins: dict[str, int] = {}
        self.categories: dict[str, int] = {}
        self.dernier = 0.0
        self.t_vus: set[str] = set()
        self.compte: int | None = None
        # Instants (monotones) des derniers refus, pour le bannissement.
        self.refus: deque[float] = deque()


def _chemin_affiche(chemin: str) -> str:
    return chemin if len(chemin) <= 80 else chemin[:77] + "…"


class Trafic:
    """Compteurs par IP sur 24 h glissantes, en tranches de 5 minutes.

    Coût O(1) par requête (une entrée de dictionnaire, quelques compteurs
    bornés, la purge des tranches périmées amortie). Mémoire bornée : au
    plus `_MAX_CLIENTS` IP ; au-delà, les IP muettes depuis 24 h partent,
    puis les plus anciennes. Thread-safe (lu par les routes d'admin, dans le
    pool de threads de Starlette)."""

    def __init__(self) -> None:
        self._clients: dict[str, _Client] = {}
        self._verrou = threading.Lock()

    def noter(
        self, ip: str, *, categorie: str, chemin: str, user_agent: str, compte: int | None = None,
        depassement: bool = False, refus_403: bool = False, t: str | None = None,
        maintenant: float | None = None,
    ) -> None:
        maintenant = time.time() if maintenant is None else maintenant
        tranche = int(maintenant // PAS_S)
        with self._verrou:
            client = self._clients.get(ip)
            if client is None:
                if len(self._clients) >= _MAX_CLIENTS:
                    self._balayer(maintenant)
                client = self._clients[ip] = _Client()
            compteurs = client.tranches.get(tranche)
            if compteurs is None:
                compteurs = client.tranches[tranche] = [0, 0, 0, 0]
                client.ordre.append(tranche)
                while client.ordre and client.ordre[0] <= tranche - _TRANCHES_24H:
                    client.tranches.pop(client.ordre.popleft(), None)
            compteurs[_REQ] += 1
            if depassement:
                compteurs[_DEPASSE] += 1
            if refus_403:
                compteurs[_REFUS403] += 1
            if categorie in ("public", "ics", "sonde"):
                compteurs[_PUBLIQUES] += 1
            client.dernier = maintenant
            if compte is not None:
                client.compte = compte
            _incrementer_borne(client.ua, (user_agent or "")[:200], _MAX_UA)
            _incrementer_borne(client.chemins, _chemin_affiche(chemin), _MAX_CHEMINS)
            client.categories[categorie] = client.categories.get(categorie, 0) + 1
            if t and len(client.t_vus) < _MAX_T:
                # Empreinte courte, jamais la valeur : on veut savoir COMBIEN
                # de liens différents une IP parcourt, pas lesquels.
                client.t_vus.add(hashlib.sha256(t.encode()).hexdigest()[:12])

    def noter_refus(self, ip: str, seuil: int, fenetre_s: float) -> int:
        """Enregistre un refus pour le bannissement ; rend le nombre de refus
        dans la fenêtre (borné à `seuil`)."""
        maintenant = time.monotonic()
        with self._verrou:
            client = self._clients.get(ip)
            if client is None:
                client = self._clients[ip] = _Client()
                client.dernier = time.time()
            file = client.refus
            file.append(maintenant)
            while file and maintenant - file[0] > fenetre_s:
                file.popleft()
            while len(file) > seuil:
                file.popleft()
            return len(file)

    def oublier_refus(self, ip: str) -> None:
        with self._verrou:
            client = self._clients.get(ip)
            if client is not None:
                client.refus.clear()

    def _balayer(self, maintenant: float) -> None:
        limite = maintenant - 86400
        for ip in [ip for ip, c in self._clients.items() if c.dernier < limite]:
            del self._clients[ip]
        if len(self._clients) >= _MAX_CLIENTS:
            # Encore plein : les 10 % les plus anciens partent (rare, amorti).
            anciens = sorted(self._clients, key=lambda ip: self._clients[ip].dernier)
            for ip in anciens[: max(1, _MAX_CLIENTS // 10)]:
                del self._clients[ip]

    def __len__(self) -> int:
        return len(self._clients)

    def vider(self) -> None:
        with self._verrou:
            self._clients.clear()

    def instantane(self, fenetre_s: int, *, limite: int = 50, maintenant: float | None = None) -> dict:
        """Résumé de la fenêtre et les `limite` plus gros clients."""
        maintenant = time.time() if maintenant is None else maintenant
        actuelle = int(maintenant // PAS_S)
        seuils = {nom: actuelle - s // PAS_S + 1 for nom, s in FENETRES.items()}
        seuil_fenetre = actuelle - max(1, fenetre_s // PAS_S) + 1
        lignes = []
        total = {"requetes": 0, "depassements": 0, "refus_403": 0, "clients": 0}
        with self._verrou:
            for ip, c in self._clients.items():
                par = {nom: 0 for nom in FENETRES}
                req = dep = r403 = pub = 0
                for tranche, (n, d, r, p) in c.tranches.items():
                    for nom, seuil in seuils.items():
                        if tranche >= seuil:
                            par[nom] += n
                    if tranche >= seuil_fenetre:
                        req += n
                        dep += d
                        r403 += r
                        pub += p
                if req == 0:
                    continue
                total["requetes"] += req
                total["depassements"] += dep
                total["refus_403"] += r403
                total["clients"] += 1
                ua = max(c.ua, key=c.ua.__getitem__) if c.ua else ""
                chemins = sorted(c.chemins.items(), key=lambda kv: -kv[1])[:5]
                lignes.append({
                    "ip": ip,
                    "requetes": req,
                    "requetes_15min": par["15min"],
                    "requetes_1h": par["1h"],
                    "requetes_24h": par["24h"],
                    "part_publique": round(pub / req, 3) if req else 0.0,
                    "depassements": dep,
                    "refus_403": r403,
                    "user_agent": ua,
                    "user_agents_distincts": len(c.ua),
                    "chemins": [{"chemin": ch, "nb": nb} for ch, nb in chemins],
                    "categorie": max(c.categories, key=c.categories.__getitem__) if c.categories else "",
                    "compte_id": c.compte,
                    "liens_distincts": len(c.t_vus),
                    "dernier_passage": datetime.fromtimestamp(c.dernier, UTC).isoformat(timespec="seconds"),
                })
        lignes.sort(key=lambda ligne: (-ligne["requetes"], ligne["ip"]))
        return {"resume": total, "clients": lignes[: max(1, limite)]}


trafic = Trafic()
seaux = SeauxAJetons()


# ---------------------------------------------------------------------------
# Journal : une ligne par épisode de dépassement.
# ---------------------------------------------------------------------------

# Au plus une ligne par identité toutes les 10 s, avec le nombre de refus
# tus depuis : sous une vraie rafale, une ligne par requête remplirait les
# journaux Docker bien plus vite que l'aspirateur ne remplit le serveur.
_JOURNAL_INTERVALLE_S = 10.0
_journal: dict[str, list[float]] = {}  # identité -> [instant dernière ligne, refus tus]
_journal_verrou = threading.Lock()


def _journaliser_depassement(m: str, ip: str, categorie: str, identite: str, chemin: str, attente: float) -> None:
    maintenant = time.monotonic()
    with _journal_verrou:
        entree = _journal.get(identite)
        if entree is not None and maintenant - entree[0] < _JOURNAL_INTERVALLE_S:
            entree[1] += 1
            return
        tus = int(entree[1]) if entree else 0
        if len(_journal) > 10_000:
            _journal.clear()
        _journal[identite] = [maintenant, 0]
    # Chemin sans paramètres (jamais le `?t=`), code du flux masqué : l'IP
    # est la seule donnée sur le client qui sorte dans le journal.
    chemin = re.sub(r"^/ics/(prof|groupe)/[^/]+$", r"/ics/\1/…", chemin)
    logger.warning(
        "dépassement mode=%s ip=%s catégorie=%s identité=%s chemin=%s attente=%ss%s",
        m, ip, categorie, identite if identite.startswith(("compte:", "cle:")) else "ip",
        _chemin_affiche(chemin), math.ceil(attente), f" (+{tus} refus depuis la ligne précédente)" if tus else "",
    )


def vider_etat_memoire() -> None:
    """Compteurs, seaux, journal, cache des clés — pour les tests."""
    trafic.vider()
    seaux.vider()
    with _journal_verrou:
        _journal.clear()
    with _cles_verrou:
        _cles_cache.clear()
    blocages.vider_cache()


# ---------------------------------------------------------------------------
# Middleware ASGI.
# ---------------------------------------------------------------------------


async def _repondre(send, statut: int, corps: dict, entetes: list[tuple[bytes, bytes]] | None = None) -> None:
    contenu = json.dumps(corps, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": statut,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(contenu)).encode()),
            (b"cache-control", b"no-store"),
            *(entetes or []),
        ],
    })
    await send({"type": "http.response.body", "body": contenu})


def _en_tete(scope: dict, nom: bytes) -> str | None:
    for cle, valeur in scope.get("headers") or ():
        if cle == nom:
            return valeur.decode("latin-1")
    return None


def _parametre_t(scope: dict) -> str | None:
    requete = (scope.get("query_string") or b"").decode("latin-1")
    if "t=" not in requete:
        return None
    from urllib.parse import parse_qs

    valeurs = parse_qs(requete).get("t")
    return valeurs[0] if valeurs else None


class AntiAspiration:
    """Middleware ASGI pur. Placé à l'extérieur de `require_auth` : un
    client bloqué est refusé avant toute lecture de session ou de base."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        m = mode()
        if m == "off":
            # Rien, pas même compter : c'est la promesse du mode par défaut.
            await self.app(scope, receive, send)
            return
        try:
            verdict = self._decider(scope, m)
        except Exception:
            logger.exception("anti-aspiration : erreur interne, requête laissée passer")
            verdict = None
        if verdict is not None:
            await _repondre(send, *verdict)
            return
        await self.app(scope, receive, send)

    def _decider(self, scope: dict, m: str) -> tuple | None:
        chemin = scope.get("path") or "/"
        client = scope.get("client")
        ip = _ip_normalisee(client[0])[0] if client else "inconnue"
        ua = _en_tete(scope, b"user-agent") or ""
        categorie, identite, compte = classer(
            chemin, ip, _en_tete(scope, b"authorization"), _en_tete(scope, b"cookie")
        )
        enforce = m == "enforce"

        if chemin not in _SANTE:
            blocage = blocages.correspondance(ip, ua, inclure_auto=enforce)
            if blocage is not None:
                if categorie != "statique":
                    trafic.noter(ip, categorie=categorie, chemin=chemin, user_agent=ua, compte=compte, refus_403=True)
                return 403, {"detail": "Accès refusé."}
        if categorie == "statique":
            return None

        conf = configuration()
        budget = conf.budgets[categorie]
        exempte = False
        if conf.exemptes:
            adresse = _ip_normalisee(ip)[1]
            exempte = adresse is not None and any(
                adresse.version == r.version and adresse in r for r in conf.exemptes
            )
        attente = None if exempte else seaux.consommer(f"{categorie}|{identite}", budget.debit, budget.rafale)
        t = _parametre_t(scope) if categorie in ("public", "sonde", "ics") else None
        trafic.noter(
            ip, categorie=categorie, chemin=chemin, user_agent=ua, compte=compte,
            depassement=attente is not None, t=t,
        )
        if attente is None:
            return None

        _journaliser_depassement(m, ip, categorie, identite, chemin, attente)
        if identite.startswith("ip:"):
            nb = trafic.noter_refus(ip, conf.ban_seuil, conf.ban_fenetre_s)
            if nb >= conf.ban_seuil:
                trafic.oublier_refus(ip)
                if enforce:
                    blocages.ajouter(
                        "ip", ip, f"{nb} refus en moins de {int(conf.ban_fenetre_s // 60)} min",
                        "automatique", conf.ban_duree_s, automatique=True,
                    )
                    logger.warning(
                        "bannissement ip=%s durée=%ss (%s refus en %ss)", ip, int(conf.ban_duree_s), nb,
                        int(conf.ban_fenetre_s),
                    )
                else:
                    logger.warning("bannissement (observation, non appliqué) ip=%s (%s dépassements)", ip, nb)
        if not enforce:
            return None
        secondes = max(1, math.ceil(attente))
        return 429, {"detail": f"Trop de requêtes. Réessayez dans {secondes} seconde{'s' if secondes > 1 else ''}."}, [
            (b"retry-after", str(secondes).encode())
        ]


class EnTeteNoIndex:
    """`X-Robots-Tag: noindex, nofollow` sur toutes les réponses de l'API —
    toujours actif, quel que soit le mode : un lien public ou un flux .ics
    n'a rien à faire dans un moteur de recherche, et dire aux robots polis
    de passer leur chemin ne coûte rien (cf. aussi `frontend/public/
    robots.txt`)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                entetes = list(message.get("headers") or [])
                if not any(k.lower() == b"x-robots-tag" for k, _ in entetes):
                    entetes.append((b"x-robots-tag", b"noindex, nofollow"))
                    message = {**message, "headers": entetes}
            await send(message)

        await self.app(scope, receive, _send)


def etat_public() -> dict:
    """Mode et réglages actifs, pour l'écran Trafic et `cal-iut trafic`."""
    conf = configuration()
    return {
        "mode": mode(),
        "variable": MODE_ENV,
        "budgets": [
            {
                "categorie": b.categorie, "nombre": b.nombre, "periode_s": b.periode_s, "rafale": b.rafale,
                "description": b.description,
            }
            for b in conf.budgets.values()
        ],
        "bannissement": {
            "seuil": conf.ban_seuil, "fenetre_s": conf.ban_fenetre_s, "duree_s": conf.ban_duree_s,
        },
        "exemptes": list(conf.exemptes_texte),
    }
