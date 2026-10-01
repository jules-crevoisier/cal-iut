"""Une session Celcat en LECTURE SEULE, le temps d'un bloc.

Même enchaînement que `scripts/celcat_instantane.py` (accès réseau, VPN si
besoin, navigateur, connexion en rôle `985_consultation`, déconnexion et
VPN rendu en sortant), factorisé pour la commande `cal-iut celcat
occupations`. Le rôle n'est PAS un paramètre : cette session ne peut pas
écrire, c'est la garantie que portent les droits du compte et non la
prudence du code appelant.

Playwright et le VPN ne sont importés qu'à l'entrée du bloc : le reste du
paquet (et les tests) n'en dépendent pas.
"""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse


def args_resolution(url: str) -> list[str]:
    """Chromium n'utilise pas le résolveur du système (DNS poussé par le
    VPN ignoré sous Windows) : on lui impose la résolution déjà validée."""
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


class CelcatInjoignable(RuntimeError):
    """Ni accès direct ni VPN : rien n'a été lu."""


@contextmanager
def session_lecture(*, base: str, vpn: bool, url: str | None = None) -> Iterator[object]:
    from cal_iut.celcat import navigateur as nav
    from cal_iut.celcat import reseau

    url = url or os.environ.get("CELCAT_URL", "")
    if not url:
        raise CelcatInjoignable("CELCAT_URL absent (variable d'environnement ou .env)")
    from playwright.sync_api import sync_playwright

    with reseau.acces(url, monter_le_vpn=vpn) as diag:
        if not diag.joignable:
            raise CelcatInjoignable(f"Celcat injoignable : {diag.detail}")
        with sync_playwright() as p:
            navigateur = p.chromium.launch(headless=True, args=args_resolution(url))
            page = navigateur.new_page(viewport={"width": 1920, "height": 1080})
            try:
                nav.connexion(page, base=base, role=nav.ROLE_LECTURE)
                yield page
            finally:
                try:
                    nav.deconnexion(page)
                except Exception:  # noqa: BLE001, S110 — se déconnecter au mieux
                    pass
                navigateur.close()
