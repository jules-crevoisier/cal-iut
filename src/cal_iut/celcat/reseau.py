"""Accès réseau à Celcat, derrière le VPN AnyConnect de l'URCA.

Celcat n'est pas exposé sur Internet : sans le VPN, le nom ne résout même
pas. La saisie automatisée doit donc SAVOIR si le réseau est là — avant de
commencer, et pendant.

Pourquoi ce n'est pas un détail. Une coupure en cours de route ne produit
pas une erreur franche : les pages cessent de répondre, et un pilote qui
continue à cliquer enchaîne les échecs sur un formulaire mort. Dans un outil
qui alimente aussi la PAIE des enseignants, mieux vaut s'arrêter net et
reprendre plus tard que laisser un Celcat à moitié rempli.

Trois niveaux, du plus sûr au plus automatique :

1. `verifier(url)` — constate, n'agit pas. C'est le mode par défaut :
   l'utilisateur ouvre AnyConnect lui-même, l'outil refuse de démarrer tant
   que Celcat n'est pas joignable.
2. `connecter()` — monte le VPN via `vpncli.exe`, le CLI livré avec le
   client. Sur option explicite seulement.
3. `deconnecter()` — ne coupe que ce que l'outil a lui-même monté.

Sur l'authentification à deux facteurs : si la passerelle en demande une,
`connecter()` reste utilisable — le processus attend pendant que
l'utilisateur valide sur son téléphone (d'où le délai généreux). Un code à
usage unique peut être fourni par `VPN_CODE`. Ce qui n'est PAS possible,
c'est une saisie entièrement sans humain : c'est le propre du second
facteur, pas une limite de cet outil.

Aucun identifiant n'est écrit ici : ils viennent de l'environnement
(`.env`), comme le mot de passe de l'application.
"""

from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Le binaire a changé de dossier entre AnyConnect et « Cisco Secure Client ».
CHEMINS_VPNCLI = (
    Path(r"C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe"),
    Path(r"C:\Program Files (x86)\Cisco\Cisco Secure Client\vpncli.exe"),
    Path(r"C:\Program Files\Cisco\Cisco Secure Client\vpncli.exe"),
)

# Le serveur de production est un conteneur Linux : il n'y a pas de `.exe`
# Cisco, et il n'y en aura pas — Cisco ne distribue pas AnyConnect pour ce
# cas. OpenConnect, libre, parle le MÊME protocole ; c'est le client des
# machines Linux. La détection couvre donc les deux mondes, sans quoi ce
# module serait utilisable seulement depuis le poste Windows.
CHEMINS_OPENCONNECT = (
    Path("/usr/sbin/openconnect"),
    Path("/usr/bin/openconnect"),
    Path("/usr/local/sbin/openconnect"),
)

PASSERELLE_DEFAUT = "vpn.univ-reims.fr"


class AccesIndisponible(RuntimeError):
    """Celcat n'est pas joignable — le message dit quoi faire."""


@dataclass(frozen=True)
class Diagnostic:
    joignable: bool
    detail: str
    vpn_monte: bool | None = None

    def __bool__(self) -> bool:
        return self.joignable


def chemin_vpncli() -> Path | None:
    for chemin in CHEMINS_VPNCLI:
        if chemin.exists():
            return chemin
    return None


def chemin_openconnect() -> Path | None:
    depuis_le_path = shutil.which("openconnect")
    if depuis_le_path:
        return Path(depuis_le_path)
    for chemin in CHEMINS_OPENCONNECT:
        if chemin.exists():
            return chemin
    return None


def client_disponible() -> tuple[str, Path] | tuple[None, None]:
    """Quel client VPN cette machine a-t-elle ? AnyConnect sur le poste,
    OpenConnect sur un serveur Linux — même protocole, même passerelle."""
    exe = chemin_vpncli()
    if exe is not None:
        return "anyconnect", exe
    exe = chemin_openconnect()
    if exe is not None:
        return "openconnect", exe
    return None, None


def _hote_et_port(url: str) -> tuple[str, int]:
    decoupe = urlparse(url if "//" in url else f"https://{url}")
    if not decoupe.hostname:
        raise ValueError(f"URL Celcat illisible : {url!r}")
    return decoupe.hostname, decoupe.port or (80 if decoupe.scheme == "http" else 443)


def verifier(url: str, *, delai: float = 4.0) -> Diagnostic:
    """Celcat répond-il ? Distingue les deux échecs, qui n'appellent pas le
    même geste : un nom qui ne résout pas signale un VPN absent, une
    connexion refusée signale un VPN présent mais un service en panne."""
    try:
        hote, port = _hote_et_port(url)
    except ValueError as exc:
        return Diagnostic(False, str(exc))

    try:
        socket.getaddrinfo(hote, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return Diagnostic(
            False,
            f"« {hote} » ne résout pas : le VPN n'est probablement pas monté. "
            "Connectez-vous au VPN URCA (AnyConnect), puis relancez.",
            vpn_monte=False,
        )

    try:
        with socket.create_connection((hote, port), timeout=delai):
            return Diagnostic(True, f"{hote}:{port} répond.", vpn_monte=True)
    except OSError as exc:
        return Diagnostic(
            False,
            f"{hote}:{port} ne répond pas ({exc}). Le nom résout, donc le VPN "
            "semble monté : c'est Celcat lui-même qui est injoignable.",
            vpn_monte=True,
        )


def etat_vpn() -> str:
    """« connecté », « déconnecté », ou une explication."""
    outil, exe = client_disponible()
    if outil is None:
        return "aucun client VPN (ni AnyConnect ni OpenConnect)"
    if outil == "openconnect":
        # OpenConnect n'expose aucune commande d'état : il tourne, ou pas.
        # Son processus est donc la seule source de vérité disponible.
        try:
            actif = (
                subprocess.run(
                    ["pgrep", "-x", "openconnect"], capture_output=True, text=True, timeout=10
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            return "état indéterminé (openconnect)"
        return "connecté" if actif else "déconnecté"
    try:
        sortie = subprocess.run(
            [str(exe), "state"], capture_output=True, text=True, timeout=30
        ).stdout.lower()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"état illisible ({exc})"
    if "state: connected" in sortie:
        return "connecté"
    if "state: disconnected" in sortie:
        return "déconnecté"
    return "état indéterminé"


def connecter(
    *,
    passerelle: str | None = None,
    utilisateur: str | None = None,
    mot_de_passe: str | None = None,
    groupe: str | None = None,
    code: str | None = None,
    delai: float = 180.0,
) -> Diagnostic:
    """Monte le VPN via `vpncli.exe`. Les valeurs manquantes sont lues dans
    l'environnement : `VPN_PASSERELLE`, `VPN_UTILISATEUR`,
    `VPN_MOT_DE_PASSE`, `VPN_GROUPE`, `VPN_CODE`.

    Le délai est volontairement long : si la passerelle demande une
    validation sur téléphone, c'est le temps qu'il faut pour l'accorder.
    """
    outil, exe = client_disponible()
    if outil is None:
        return Diagnostic(
            False,
            "Aucun client VPN. Sur Windows : AnyConnect. Sur un serveur Linux : "
            "`apt install openconnect` (même protocole, même passerelle).",
        )

    passerelle = passerelle or os.environ.get("VPN_PASSERELLE") or PASSERELLE_DEFAUT
    # Le VPN et Celcat partagent le même compte (indiqué le 31/08/2026) :
    # les clés VPN_* ne servent qu'à DÉROGER à ce cas normal. Les répéter
    # serait deux endroits à corriger le jour du changement de mot de passe.
    utilisateur = utilisateur or os.environ.get("VPN_UTILISATEUR") or os.environ.get("CELCAT_UTILISATEUR") or ""
    mot_de_passe = (
        mot_de_passe or os.environ.get("VPN_MOT_DE_PASSE") or os.environ.get("CELCAT_MOT_DE_PASSE") or ""
    )
    groupe = groupe if groupe is not None else os.environ.get("VPN_GROUPE", "")
    code = code if code is not None else os.environ.get("VPN_CODE", "")
    if not utilisateur or not mot_de_passe:
        return Diagnostic(
            False,
            "Identifiants absents de l'environnement (.env) : renseignez "
            "CELCAT_UTILISATEUR / CELCAT_MOT_DE_PASSE (ou VPN_* pour un compte distinct).",
        )

    if outil == "openconnect":
        return _connecter_openconnect(exe, passerelle, utilisateur, mot_de_passe, groupe, delai)

    # `vpncli` pose ses questions dans l'ordre : groupe (si la passerelle en
    # propose plusieurs), identifiant, mot de passe, éventuel second facteur,
    # puis la bannière à accepter. Les lignes vides sautent une question qui
    # n'est pas posée — d'où un script tolérant plutôt qu'un dialogue exact.
    reponses = "\n".join([groupe, utilisateur, mot_de_passe, code, "y", ""])
    try:
        acheve = subprocess.run(
            [str(exe), "-s", "connect", passerelle],
            input=reponses,
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except subprocess.TimeoutExpired:
        return Diagnostic(False, f"Connexion au VPN abandonnée après {delai:.0f} s.")
    except OSError as exc:
        return Diagnostic(False, f"Lancement de vpncli impossible : {exc}")

    if etat_vpn() == "connecté":
        return Diagnostic(True, f"VPN monté sur {passerelle}.", vpn_monte=True)
    return Diagnostic(False, f"VPN non monté. {_sans_secret(acheve.stdout, mot_de_passe, code)}")


def _connecter_openconnect(
    exe: Path, passerelle: str, utilisateur: str, mot_de_passe: str, groupe: str, delai: float
) -> Diagnostic:
    """Montage du VPN côté serveur Linux.

    AVERTISSEMENT DE DÉPLOIEMENT. OpenConnect a besoin de `/dev/net/tun` et
    de la capacité `NET_ADMIN`, et la passerelle pousse en général un tunnel
    COMPLET : monter ce VPN dans le conteneur de l'application détournerait
    tout son trafic sortant, et couperait le site public. Il doit donc
    tourner dans un conteneur DÉDIÉ à la saisie, jamais dans celui qui sert
    l'application.
    """
    commande = [
        str(exe),
        "--protocol=anyconnect",
        f"--user={utilisateur}",
        "--passwd-on-stdin",
        "--background",
        "--non-inter",  # rien à demander : ni bannière, ni confirmation
        passerelle if "//" in passerelle else f"https://{passerelle}",
    ]
    if groupe:
        commande.insert(-1, f"--authgroup={groupe}")
    try:
        acheve = subprocess.run(
            commande, input=f"{mot_de_passe}\n", capture_output=True, text=True, timeout=delai
        )
    except subprocess.TimeoutExpired:
        return Diagnostic(False, f"OpenConnect abandonné après {delai:.0f} s.")
    except OSError as exc:
        return Diagnostic(False, f"Lancement d'openconnect impossible : {exc}")
    if acheve.returncode == 0:
        return Diagnostic(True, f"VPN monté sur {passerelle} (openconnect).", vpn_monte=True)
    return Diagnostic(
        False,
        "OpenConnect a échoué. "
        + _sans_secret(acheve.stderr or acheve.stdout, mot_de_passe)
        + " — vérifiez /dev/net/tun et la capacité NET_ADMIN du conteneur.",
    )


def deconnecter() -> str:
    outil, exe = client_disponible()
    if outil is None:
        return "aucun client VPN"
    commande = [str(exe), "disconnect"] if outil == "anyconnect" else ["pkill", "-x", "openconnect"]
    try:
        subprocess.run(commande, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"déconnexion impossible ({exc})"
    return etat_vpn()


def _sans_secret(texte: str, *secrets: str) -> str:
    """`vpncli` ne réaffiche pas le mot de passe, mais son texte finit dans
    des journaux et des messages d'erreur : on ne prend pas le risque."""
    for secret in secrets:
        if secret:
            texte = texte.replace(secret, "«masqué»")
    return " ".join(texte.split())[-400:]


def exiger_acces(url: str, *, monter_le_vpn: bool = False) -> Diagnostic:
    """Garantit l'accès, ou lève. C'est le point d'entrée de la saisie.

    L'accès DIRECT est toujours essayé en premier, même quand le montage
    automatique est demandé : sur place, à l'IUT, Celcat répond sans VPN, et
    monter un tunnel dont personne n'a besoin ne ferait que ralentir la
    saisie et risquer une coupure inutile (retour utilisateur 31/08/2026 :
    « toujours tester si on peut accéder à Celcat sans le VPN au cas où on
    soit sur site, avant de passer par le VPN »).
    """
    diagnostic = verifier(url)
    if diagnostic:
        return diagnostic
    if monter_le_vpn and diagnostic.vpn_monte is False:
        montage = connecter()
        if not montage:
            raise AccesIndisponible(f"{diagnostic.detail} {montage.detail}")
        diagnostic = verifier(url)
        if diagnostic:
            return diagnostic
    raise AccesIndisponible(diagnostic.detail)
