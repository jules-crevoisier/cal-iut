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
    exe = chemin_vpncli()
    if exe is None:
        return "client AnyConnect introuvable"
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
    exe = chemin_vpncli()
    if exe is None:
        return Diagnostic(False, "Client AnyConnect introuvable — montez le VPN à la main.")

    passerelle = passerelle or os.environ.get("VPN_PASSERELLE") or PASSERELLE_DEFAUT
    utilisateur = utilisateur or os.environ.get("VPN_UTILISATEUR") or ""
    mot_de_passe = mot_de_passe or os.environ.get("VPN_MOT_DE_PASSE") or ""
    groupe = groupe if groupe is not None else os.environ.get("VPN_GROUPE", "")
    code = code if code is not None else os.environ.get("VPN_CODE", "")
    if not utilisateur or not mot_de_passe:
        return Diagnostic(
            False,
            "VPN_UTILISATEUR / VPN_MOT_DE_PASSE absents de l'environnement (.env).",
        )

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


def deconnecter() -> str:
    exe = chemin_vpncli()
    if exe is None:
        return "client AnyConnect introuvable"
    try:
        subprocess.run([str(exe), "disconnect"], capture_output=True, text=True, timeout=60)
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
    """Garantit l'accès, ou lève. C'est le point d'entrée de la saisie."""
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
