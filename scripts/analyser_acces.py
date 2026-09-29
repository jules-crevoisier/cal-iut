#!/usr/bin/env python3
"""Qui aspire le serveur ? Diagnostic à partir des journaux d'accès, SANS
rien déployer (29/09/2026, cf. docs/ANTI-ASPIRATION.md § « Étape 1 »).

Lit un journal (fichier, `.gz`, ou l'entrée standard) et reconnaît, ligne
par ligne, trois formats :
- nginx « combined » (conteneur frontend : `docker logs <frontend>`) ;
- Traefik en JSON (journal d'accès de Dokploy, `access.log`) ;
- uvicorn (conteneur backend : `docker logs --timestamps <backend>`).

Sort : les IP, User-Agents et chemins les plus fréquents, la répartition
par heure, les motifs d'aspiration repérés (cadence régulière, UA de robot
ou vide, balayage de nombreux liens `?t=` différents, volume de nuit) et
les commandes `cal-iut bloquer …` correspondantes — à RELIRE avant de les
lancer : ce script propose, il ne décide pas.

Bibliothèque standard seulement : il tourne tel quel sur l'hôte Dokploy
(`python3 analyser_acces.py …`), sans environnement virtuel.

Exemples :
    docker logs cal-iut-frontend-xxxx --since 48h 2>&1 | python3 scripts/analyser_acces.py
    python3 scripts/analyser_acces.py access.log.1 access.log.2.gz --top 30
"""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import itertools
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

try:
    from zoneinfo import ZoneInfo

    FUSEAU = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001 — pas de base de fuseaux : on reste en UTC
    FUSEAU = UTC

# nginx combined : ip - user [date] "requête" statut octets "référent" "ua"
_NGINX = re.compile(
    r'^(?:\S+\s+)?(?P<ip>[0-9a-fA-F:.]+) \S+ \S+ \[(?P<date>[^\]]+)\] "(?P<req>[^"]*)" (?P<statut>\d{3}) \S+'
    r'(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?'
)
# uvicorn : [horodatage docker] INFO:     1.2.3.4:5678 - "GET /x HTTP/1.1" 200 OK
_UVICORN = re.compile(
    r'^(?:(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\s+)?INFO:\s+(?P<ip>[0-9a-fA-F:.\[\]]+):\d+ - "(?P<req>[^"]*)" (?P<statut>\d{3})'
)
_ROBOT = re.compile(
    r"bot|crawl|spider|scrap|slurp|python|aiohttp|httpx|curl|wget|go-http|java/|okhttp|node-fetch|axios|"
    r"undici|headless|phantom|libwww|httpclient|postman|insomnia|guzzle|ruby|perl|php|powershell|feedparser",
    re.IGNORECASE,
)
# Clients d'agenda : ils relisent les flux .ics à intervalle fixe, souvent
# depuis quelques IP partagées par tous leurs utilisateurs (Google,
# Microsoft). Réguliers par nature : jamais suspects pour ça seul.
_AGENDA = re.compile(
    r"google-calendar|googlecalendar|calendar-importer|outlook|microsoft office|exchange|icalendar|"
    r"dataaccessd|calendaragent|ios/|macos/|thunderbird|davx|icsx|proton|fantastical|busycal|evolution",
    re.IGNORECASE,
)


@dataclass
class Acces:
    ip: str
    quand: datetime | None
    methode: str
    chemin: str
    t: str | None
    statut: int
    ua: str


def _date_nginx(texte: str) -> datetime | None:
    try:
        return datetime.strptime(texte, "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None


def _date_iso(texte: str | None) -> datetime | None:
    if not texte:
        return None
    texte = texte.strip().replace("Z", "+00:00")
    # Docker écrit des nanosecondes : Python n'en lit que six chiffres.
    texte = re.sub(r"(\.\d{6})\d+", r"\1", texte)
    try:
        d = datetime.fromisoformat(texte)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _requete(req: str) -> tuple[str, str, str | None]:
    morceaux = req.split()
    if len(morceaux) < 2:
        return "?", req[:80] or "?", None
    methode, cible = morceaux[0], morceaux[1]
    url = urlsplit(cible)
    t = parse_qs(url.query).get("t", [None])[0]
    return methode, url.path or "/", t


# Préfixe de `docker service logs` (Swarm, Dokploy) : « nom.1.abc@hote | ».
_PREFIXE_SWARM = re.compile(r"^\S+@\S+\s+\|\s?")


def lire_ligne(ligne: str) -> Acces | None:
    ligne = _PREFIXE_SWARM.sub("", ligne.strip())
    if not ligne:
        return None
    if ligne.startswith("{"):
        try:
            d = json.loads(ligne)
        except ValueError:
            return None
        ip = d.get("ClientHost") or (d.get("ClientAddr") or "").rsplit(":", 1)[0]
        methode = d.get("RequestMethod", "?")
        _, chemin, t = _requete(f"{methode} {d.get('RequestPath', '/')}")
        return Acces(
            ip=ip.strip("[]"), quand=_date_iso(d.get("StartUTC") or d.get("time")), methode=methode,
            chemin=chemin, t=t, statut=int(d.get("DownstreamStatus") or 0),
            ua=d.get("request_User-Agent") or "",
        )
    m = _NGINX.match(ligne)
    if m:
        methode, chemin, t = _requete(m.group("req"))
        ua = m.group("ua") or ""
        return Acces(
            ip=m.group("ip"), quand=_date_nginx(m.group("date")), methode=methode, chemin=chemin, t=t,
            statut=int(m.group("statut")), ua="" if ua == "-" else ua,
        )
    m = _UVICORN.match(ligne)
    if m:
        methode, chemin, t = _requete(m.group("req"))
        return Acces(
            ip=m.group("ip").strip("[]"), quand=_date_iso(m.group("ts")), methode=methode, chemin=chemin,
            t=t, statut=int(m.group("statut")), ua="",
        )
    return None


def _ouvrir(nom: str):
    if nom == "-":
        return sys.stdin
    if nom.endswith(".gz"):
        return gzip.open(nom, "rt", encoding="utf-8", errors="replace")
    return open(nom, encoding="utf-8", errors="replace")


# Réseaux internes (Docker, loopback) : là où vivent les proxys. Liste
# explicite plutôt que `is_private`, qui range aussi dans « privé » les
# plages de documentation et quelques plages réservées.
_INTERNES = tuple(
    ipaddress.ip_network(r)
    for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")
)


def _prive(ip: str) -> bool:
    try:
        adresse = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(adresse.version == r.version and adresse in r for r in _INTERNES)


def _gabarit(chemin: str) -> str:
    """`/ics/prof/KBR.ics` → `/ics/prof/{code}.ics` : on compte des routes."""
    chemin = re.sub(r"^/ics/(prof|groupe)/[^/]+\.ics$", r"/ics/\1/{code}.ics", chemin)
    chemin = re.sub(r"^/assets/.+", "/assets/…", chemin)
    return re.sub(r"/\d+(?=/|$)", "/{n}", chemin)


@dataclass
class ParIp:
    n: int = 0
    uas: Counter = field(default_factory=Counter)
    chemins: Counter = field(default_factory=Counter)
    t: set = field(default_factory=set)
    instants: list = field(default_factory=list)
    nuit: int = 0
    erreurs: int = 0


def analyser(lignes, *, top: int = 20, sortie=None) -> dict:
    sortie = sortie or sys.stdout
    ips: dict[str, ParIp] = defaultdict(ParIp)
    uas, chemins, heures = Counter(), Counter(), Counter()
    total = illisibles = 0
    debut = fin = None
    for ligne in lignes:
        a = lire_ligne(ligne)
        if a is None:
            illisibles += 1
            continue
        if a.chemin.startswith("/assets/") or a.chemin in ("/healthz", "/health", "/favicon.svg"):
            continue
        total += 1
        p = ips[a.ip]
        p.n += 1
        p.uas[a.ua or "(vide)"] += 1
        p.chemins[_gabarit(a.chemin)] += 1
        if a.t:
            p.t.add(a.t)
        if a.statut >= 400:
            p.erreurs += 1
        uas[a.ua or "(vide)"] += 1
        chemins[_gabarit(a.chemin)] += 1
        if a.quand is not None:
            local = a.quand.astimezone(FUSEAU)
            heures[local.hour] += 1
            if local.hour < 6:
                p.nuit += 1
            p.instants.append(a.quand.timestamp())
            debut = a.quand if debut is None or a.quand < debut else debut
            fin = a.quand if fin is None or a.quand > fin else fin

    def ecrire(texte: str = "") -> None:
        print(texte, file=sortie)

    if total == 0:
        ecrire(f"Aucune requête reconnue ({illisibles} lignes ignorées). Formats lus : nginx combined, "
               "Traefik JSON, uvicorn.")
        return {"total": 0, "suspects": []}

    ecrire(f"{total} requêtes analysées ({illisibles} lignes ignorées), {len(ips)} IP distinctes")
    if debut and fin:
        ecrire(f"Du {debut.astimezone(FUSEAU):%d/%m/%Y %H:%M} au {fin.astimezone(FUSEAU):%d/%m/%Y %H:%M} (heure de Paris)")

    part_privee = sum(p.n for ip, p in ips.items() if _prive(ip)) / total
    if part_privee > 0.8:
        ecrire(
            "\n/!\\ Plus de 80 % des requêtes viennent d'adresses PRIVÉES : ce journal voit l'IP du proxy "
            "(Traefik), pas celle des clients.\n    Utiliser plutôt les journaux du backend (uvicorn) ou de "
            "Traefik, ou déployer d'abord le correctif d'IP réelle de nginx (docs/ANTI-ASPIRATION.md, étape 2)."
        )

    ecrire(f"\n── {top} IP les plus actives ──")
    ecrire(f"{'IP':<40} {'requêtes':>9} {'part':>6} {'liens t':>8} {'nuit':>6}  User-Agent principal")
    for ip, p in sorted(ips.items(), key=lambda kv: -kv[1].n)[:top]:
        ua = p.uas.most_common(1)[0][0]
        ecrire(f"{ip:<40} {p.n:>9} {p.n / total:>6.1%} {len(p.t):>8} {p.nuit / p.n:>6.0%}  {ua[:70]}")

    ecrire(f"\n── {top} User-Agents ──")
    for ua, n in uas.most_common(top):
        ecrire(f"{n:>9}  {ua[:110]}")

    ecrire(f"\n── {top} chemins (codes masqués) ──")
    for ch, n in chemins.most_common(top):
        ecrire(f"{n:>9}  {ch}")

    if heures:
        ecrire("\n── Requêtes par heure (heure de Paris) ──")
        maxi = max(heures.values())
        for h in range(24):
            n = heures.get(h, 0)
            ecrire(f"  {h:02d} h {n:>8}  {'█' * round(40 * n / maxi) if maxi else ''}")

    # Motifs d'aspiration, IP par IP.
    suspects = []
    for ip, p in ips.items():
        if p.n < 20 or _prive(ip):
            continue
        ua = p.uas.most_common(1)[0][0]
        agenda = bool(_AGENDA.search(ua))
        raisons = []
        if ua == "(vide)" and p.uas[ua] / p.n > 0.5:
            raisons.append("User-Agent vide")
        elif _ROBOT.search(ua) and not agenda:
            raisons.append(f"User-Agent de robot ({ua[:40]})")
        if len(p.t) >= 10:
            raisons.append(f"{len(p.t)} liens ?t= différents (un humain en ouvre 1 à 3)")
        if len(p.instants) >= 20 and not agenda:
            instants = sorted(p.instants)
            ecarts = [b - a for a, b in itertools.pairwise(instants) if b > a]
            if len(ecarts) >= 10:
                moyenne = statistics.fmean(ecarts)
                if moyenne > 0 and statistics.pstdev(ecarts) / moyenne < 0.15:
                    raisons.append(f"cadence régulière (toutes les {moyenne:.0f} s)")
        if p.n >= 50 and p.nuit / p.n >= 0.5:
            raisons.append(f"{p.nuit / p.n:.0%} du volume entre 0 h et 6 h")
        if p.n / total >= 0.2 and p.n >= 500:
            raisons.append(f"{p.n / total:.0%} de tout le trafic")
        if raisons:
            suspects.append((ip, p, ua, raisons, agenda))

    ecrire("\n── Motifs d'aspiration repérés ──")
    if not suspects:
        ecrire("Aucun motif net. Regarder quand même le haut du classement des IP.")
    commandes = []
    for ip, p, ua, raisons, agenda in sorted(suspects, key=lambda s: (-len(s[3]), -s[1].n)):
        ecrire(f"{ip} — {p.n} requêtes : " + " ; ".join(raisons) + (" [client d'agenda]" if agenda else ""))
        if len(raisons) >= 2 or any("robot" in r or "liens ?t=" in r for r in raisons):
            motif = raisons[0].replace('"', "'")
            commandes.append(f'cal-iut bloquer {ip} --motif "aspiration : {motif}" --duree 7j --prod')

    # Un même UA de robot sur plusieurs IP : un blocage par motif d'UA.
    par_ua = defaultdict(set)
    for ip, _p, ua, raisons, _agenda in suspects:
        if any(r.startswith("User-Agent de robot") for r in raisons):
            par_ua[ua].add(ip)
    for ua, adresses in par_ua.items():
        if len(adresses) >= 3:
            motif = re.split(r"[/ ;(]", ua)[0][:40]
            if len(motif) >= 3:
                commandes.append(
                    f'cal-iut bloquer --ua "{motif}" --motif "robot sur {len(adresses)} IP" --duree 7j --prod'
                )

    if commandes:
        ecrire("\n── Commandes proposées (à relire avant de lancer) ──")
        for c in commandes:
            ecrire(c)
        ecrire("\nRappel : la liste de blocage ne s'applique qu'avec CAL_IUT_ANTI_ASPIRATION=observe ou enforce.")
    return {"total": total, "suspects": [s[0] for s in suspects], "commandes": commandes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fichiers", nargs="*", default=["-"], help="journaux (.log, .gz) ; « - » ou rien = entrée standard")
    parser.add_argument("--top", type=int, default=20, help="lignes par classement (défaut 20)")
    args = parser.parse_args(argv)

    def toutes_les_lignes():
        for nom in args.fichiers:
            flux = _ouvrir(nom)
            try:
                yield from flux
            finally:
                if flux is not sys.stdin:
                    flux.close()

    analyser(toutes_les_lignes(), top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
