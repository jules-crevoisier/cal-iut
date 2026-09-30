# Protection contre l'aspiration

Ce document explique comment l'appli se protège des robots qui l'interrogent en boucle (« aspiration »).
Il est pour les administrateurs et les techniciens.
L'usage de l'écran **Trafic** au quotidien est aussi résumé dans [docs/ADMIN.md](ADMIN.md).

**Sommaire**

1. [Ce que ça fait](#1-ce-que-ça-fait)
2. [Ce que vous voyez : l'écran Trafic](#2-ce-que-vous-voyez--lécran-trafic)
3. [Que faire quand ça bloque](#3-que-faire-quand-ça-bloque)
4. [Revenir en arrière](#4-revenir-en-arrière)
5. [Activer la limitation de débit, pas à pas](#5-activer-la-limitation-de-débit-pas-à-pas)
6. [Pour les techniciens](#6-pour-les-techniciens)

---

## 1. Ce que ça fait

Les liens personnels (`?t=…`) sont publics : n'importe qui peut lire le planning sans compte.
On ne peut donc pas refuser un robot « parce qu'il n'a pas le droit ».
On le reconnaît à son **adresse IP** (l'adresse de sa machine sur Internet) et à son **User-Agent** (le nom du logiciel qui appelle).
Puis on le **bloque**.

### Actif dès le déploiement, sans rien régler

| Protection | Effet |
|---|---|
| **IP réelle** | L'appli voit la vraie adresse du client. Un robot ne peut pas s'en inventer une. |
| **Liste de blocage** | Une IP, une plage d'adresses ou un User-Agent bloqué reçoit « Accès refusé. » sur tout. |
| **Bannissement automatique** | Une IP **sans compte** qui reçoit **30 refus (401/403) en 10 minutes** est bloquée **24 h**. |
| **Comptage du trafic** | Chaque IP est comptée pour l'écran **Trafic** (sur 24 h glissantes). |
| **Limites de connexion et d'API** | Connexion, inscription, mot de passe oublié et API v1 ont leur propre plafond (voir [§ 6.1](#61-les-couches)). |
| **Robots polis** | `robots.txt` et un en-tête demandent aux moteurs de recherche de ne pas indexer le site. |

Un refus 401 veut dire « pas connecté » ; 403, « pas le droit ».
Un humain ne se prend pas 30 refus en 10 minutes. Un script qui essaie des pages fermées, si.

**Ne sont jamais bannis automatiquement** : un compte connecté, une clé API valide, les adresses de `CAL_IUT_AA_EXEMPTS`.
**Ne comptent pas** comme refus : les pages de connexion (`/auth/…`), les sondes de version, `/health`, les fichiers statiques, les refus de la liste de blocage elle-même.

### Désactivé par défaut

La **limitation de débit** : refuser (code 429) un client qui dépasse un nombre de requêtes par minute.
Elle est coupée tant qu'on ne l'a pas calibrée : voir [§ 5](#5-activer-la-limitation-de-débit-pas-à-pas).

---

## 2. Ce que vous voyez : l'écran Trafic

**Administration → Trafic** (admins seulement).

- **Protections toujours actives** : « Actives » en temps normal.
- **Limitation de débit** : « Désactivée », « Observation » ou « Refus actifs ».
- Période : **15 min**, **1 h**, **24 h**.
- Tuiles : requêtes, **Clients distincts**, **Refus 401/403**, **Refus (429)**, **IP bloquées**.
- Tableau des clients, du plus gros au plus petit : IP (ou compte), nombre de requêtes, part **Public** (sans compte), **User-Agent**, **Chemins**, **Refus**.
  « N liens différents » signale un client qui parcourt beaucoup de liens `?t=` (un humain en ouvre 1 à 3).
- Carte **Blocages** : ce qui est bloqué, le motif, l'auteur, **Jusqu'à**. Un bannissement automatique porte « auto · refus 401/403 » ou « auto · débit ».

Un robot se reconnaît : volume énorme, rythme régulier, activité la nuit, User-Agent vide ou de script (`python-requests`, `curl`, `scrapy`…), beaucoup de refus.
Les agendas (Google, Outlook, Apple) relisent les flux `.ics` à intervalle fixe : c'est normal.

---

## 3. Que faire quand ça bloque

### Un robot aspire le serveur

1. **Administration → Trafic**, période **1 h**.
2. Sur la ligne du robot, cliquer sur **Bloquer…**.
3. Choisir **Adresse IP** (ou **User-Agent** si le robot a un nom reconnaissable).
4. Durée : **1 h**, **24 h**, **7 jours** ou **Permanent**. Motif factuel. Puis **Bloquer**.

Le robot reçoit aussitôt « Accès refusé. » sur tout.

> **Attention :** une IP peut cacher tout un réseau (l'IUT, un opérateur mobile).
> La bloquer coupe tout le monde derrière. Préférer une durée courte, ou le User-Agent.

### Un utilisateur légitime reçoit « Accès refusé. »

1. **Administration → Trafic**, carte **Blocages**.
2. Trouver son adresse, cliquer sur **Débloquer**. Effet immédiat.
3. Si c'est une IP partagée légitime (celle de l'IUT), l'ajouter à `CAL_IUT_AA_EXEMPTS` pour qu'elle ne soit plus bannie automatiquement.

### L'appli est saturée et l'écran Trafic ne répond plus

Dans l'ordre :

1. **Bloquer depuis le conteneur backend** (s'il répond encore) :
   ```bash
   docker exec <conteneur-backend> cal-iut bloquer 203.0.113.66 --motif urgence --duree 24h
   ```
   Le serveur relit la liste seul, en moins de 5 secondes.
2. **Pare-feu de la machine** (effet immédiat, perdu au redémarrage de la machine) :
   ```bash
   sudo iptables -I DOCKER-USER -s 203.0.113.66 -j DROP     # bloquer
   sudo iptables -D DOCKER-USER -s 203.0.113.66 -j DROP     # retirer
   ```
3. **Frein général dans Traefik** (le routeur de Dokploy) : voir [§ 6.8](#68-urgence--frein-dans-traefik-ou-nginx).

### En ligne de commande, depuis un poste

Mettre dans `.env` `CAL_IUT_PROD_URL` et `CAL_IUT_PROD_API_KEY` (clé d'un compte **admin**).

```bash
cal-iut trafic --prod [--fenetre 15min|1h|24h]
cal-iut bloquer 203.0.113.66 --motif "aspire /app-state toutes les 10 s" --duree 7j --prod
cal-iut bloquer 203.0.113.0/24 --motif "hébergeur, 40 IP" --duree 24h --prod
cal-iut bloquer --ua "python-requests" --motif "robot" --duree permanent --prod
cal-iut debloquer <id> --prod
```

Durée par défaut : 24 h. `--forcer` bloque même si la règle vous vise.
Sans `--prod`, les commandes modifient la liste **locale**.

---

## 4. Revenir en arrière

| Je veux… | Faire |
|---|---|
| Lever un blocage de trop | **Débloquer** dans **Trafic**, ou `cal-iut debloquer <id> --prod`. Immédiat. |
| Couper la limitation de débit | `CAL_IUT_ANTI_ASPIRATION=off` (ou retirer la variable), puis redéployer le backend. |
| Refuser moins sans tout couper | Repasser en `observe`, ou relever un budget. Les blocages manuels restent. |
| Couper le bannissement automatique | `CAL_IUT_AA_REFUS=off`, puis redéployer. Les bannissements déjà posés restent jusqu'à leur fin : les lever dans **Trafic**. |
| Tout couper (secours) | `CAL_IUT_AA_PROTECTIONS=off` et `CAL_IUT_ANTI_ASPIRATION=off`, puis redéployer. Plus rien n'est compté ni bloqué ; la liste reste sur le disque, inerte. |

Les variables se règlent dans Dokploy → service **backend** → **Environment**.
Le correctif d'IP réelle n'a pas à être défait.

---

## 5. Activer la limitation de débit, pas à pas

À faire seulement si le blocage manuel ne suffit pas.

1. **Vérifier l'IP réelle.** Dokploy → **frontend** → **Logs** : les lignes récentes doivent montrer des IP publiques variées.
   Si elles montrent toutes une adresse `10.x` ou `172.x`, corriger d'abord ([§ 6.2](#62-lip-réelle)).
2. **Observer une semaine.** Poser `CAL_IUT_ANTI_ASPIRATION=observe` sur le backend, redéployer.
   Rien n'est refusé. L'écran **Trafic** compte ce qui *aurait* été refusé (colonne **Refus**, tuile **Refus (429)**).
3. **Ajuster.** Un usage légitime dépasse (IP de l'IUT un lundi 8 h, agenda Google, script d'un collègue) :
   relever le budget de sa catégorie, ou mettre l'IP dans `CAL_IUT_AA_EXEMPTS`, ou lui donner une clé API.
   Un robot lent qui reste sous les budgets : le bloquer à la main.
   Objectif : **aucun** dépassement légitime sur une semaine entière.
4. **Activer.** `CAL_IUT_ANTI_ASPIRATION=enforce`, redéployer.
   Au-delà du budget, le client reçoit un refus 429. L'interface affiche « Trop de requêtes. Réessayez dans N secondes. ».
   Une IP sans compte qui insiste (30 refus 429 en 10 minutes) est bloquée 1 h (« auto · débit »).
5. **Surveiller** l'écran **Trafic** les premiers jours.

Un compte connecté ou une clé API a des budgets plus larges et n'est jamais banni : il reçoit des 429, rien de plus.

---

## 6. Pour les techniciens

### 6.1 Les couches

| Couche | Où | Actif par défaut ? |
|---|---|---|
| `robots.txt` (`Disallow: /`) et `X-Robots-Tag: noindex, nofollow` | `frontend/public/robots.txt`, nginx, middleware `EnTeteNoIndex` | Oui |
| IP réelle du client | nginx `real_ip`, `cal-iut serve` | Oui |
| Liste de blocage (IP, plage CIDR, sous-chaîne de User-Agent) → 403 | `data/state/blocages.json` | Oui |
| Bannissement sur refus 401/403 répétés | liste de blocage | Oui (`CAL_IUT_AA_REFUS=off` pour couper) |
| Comptage par IP (15 min / 1 h / 24 h) | mémoire du backend | Oui |
| Limitation de débit (seau à jetons par client et par catégorie) | middleware | Non : `observe` journalise, `enforce` refuse (429) |
| Bannissement d'une IP qui insiste malgré les 429 | liste de blocage | Non : `enforce` seulement |

Code : `src/cal_iut/api/anti_aspiration.py` (middleware, budgets, liste, compteurs), `src/cal_iut/api/admin_trafic.py` (routes `/admin/trafic` et `/admin/blocages`, admin seulement), `frontend/src/views/TraficView.tsx`, commandes `cal-iut trafic | bloquer | debloquer`, `scripts/analyser_acces.py`.

**Limiteurs dédiés, toujours actifs** (`src/cal_iut/api/limiteur.py`, fenêtre glissante en mémoire, indépendants de `CAL_IUT_ANTI_ASPIRATION`) :

| Route | Plafond |
|---|---|
| `/auth/login` | 10 essais en 15 min par adresse mail ; 30 en 5 min par IP |
| `/auth/signup`, `/auth/forgot-password` (envoi de mail) | 3 par heure par adresse mail ; 10 par heure par IP |
| `/auth/reset-password` | 10 en 15 min par IP |
| `/api/v1/*` | 600 par minute par compte ; 3 000 par minute par IP sur un lien public |

Un redémarrage remet ces compteurs à zéro : c'est un frein, pas un verrouillage de compte.

Un blocage manuel vise **tout le monde**, compte connecté compris, sauf `/health` et `/healthz` (le contrôle de santé Docker ne doit jamais échouer).
Réponse d'un blocage : `403 {"detail": "Accès refusé."}`, avant tout autre traitement.

### 6.2 L'IP réelle

Chemin d'une requête : **Traefik** (Dokploy) → **nginx** (conteneur frontend) → **uvicorn** (conteneur backend).

- nginx calcule l'IP réelle : `set_real_ip_from` pour les plages privées Docker (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1, fc00::/7), `real_ip_header X-Forwarded-For`, `real_ip_recursive on`.
  L'en-tête est lu de droite à gauche en sautant les proxys : une adresse inventée par le client reste à gauche, jamais retenue.
- nginx **écrase** l'en-tête vers le backend : `proxy_set_header X-Forwarded-For $remote_addr;`.
- `cal-iut serve` passe à uvicorn la liste des proxys de confiance (`CAL_IUT_PROXYS_DE_CONFIANCE`, par défaut les plages privées).
  `FORWARDED_ALLOW_IPS` n'est plus lue : avec `*`, uvicorn retenait la première adresse de l'en-tête, écrite par le client.

Frontend et backend doivent partir ensemble. Si Traefik n'est pas sur une plage privée, ajouter son adresse à `set_real_ip_from` (`frontend/nginx.conf.template`) et à `CAL_IUT_PROXYS_DE_CONFIANCE`.

Vérifier :

```bash
docker logs --since 10m <conteneur-backend> 2>&1 | grep 'INFO: ' | tail
docker logs --since 10m <conteneur-frontend> 2>&1 | tail
curl -s -H "X-Forwarded-For: 1.2.3.4" https://<site>/auth/status   # puis : Trafic montre VOTRE IP, jamais 1.2.3.4
```

Tests : `tests/test_anti_aspiration_2026_09_29.py` (`test_ip_reelle_non_falsifiable`, `test_nginx_ecrase_x_forwarded_for…`).

### 6.3 Catégories et identité

| Catégorie | Requêtes | Identité |
|---|---|---|
| `statique` | `/assets/…`, `/favicon.svg`, `/robots.txt`, `/health`, `/healthz` | jamais limitée ni comptée |
| `sonde` | `/api/v1/version`, `/ics/version`, `/auth/status`, `/auth/me` sans compte | l'IP |
| `ics` | flux `/ics/…` sans compte | l'IP |
| `public` | tout le reste sans compte : liens `?t=`, `/app-state`, `/meta`, `/timetable`, pages | l'IP |
| `appli` | cookie de session authentique (signature vérifiée) | le compte |
| `api` | `Authorization: Bearer caliut_…` valide, ou le jeton MCP d'environnement | le compte |

Un cookie ou une clé inventés ne donnent pas le budget d'un compte (signature HMAC vérifiée, clé relue en base).

### 6.4 Variables d'environnement (service backend)

| Variable | Défaut | Rôle |
|---|---|---|
| `CAL_IUT_AA_PROTECTIONS` | actif | `off` : coupe tout le module (liste, bannissements, comptage) |
| `CAL_IUT_AA_REFUS` | actif | `off` : coupe le seul bannissement sur refus 401/403 |
| `CAL_IUT_AA_REFUS_SEUIL` | `30` | refus 401/403 avant bannissement (jamais moins de 2) |
| `CAL_IUT_AA_REFUS_FENETRE` | `10min` | … dans cette fenêtre |
| `CAL_IUT_AA_REFUS_DUREE` | `24h` | durée de ce bannissement |
| `CAL_IUT_ANTI_ASPIRATION` | `off` | limitation de débit : `off`, `observe` (compte et journalise), `enforce` (429 et bannissement). Valeur inconnue = `off` |
| `CAL_IUT_AA_PUBLIC` / `_BURST` | `120/min` / `120` | lien public, pages (par IP) |
| `CAL_IUT_AA_ICS` / `_BURST` | `120/min` / `120` | flux `.ics` (par IP) |
| `CAL_IUT_AA_SONDE` / `_BURST` | `60/min` / `30` | numéro de révision (par IP) |
| `CAL_IUT_AA_APPLI` / `_BURST` | `600/min` / `300` | compte connecté |
| `CAL_IUT_AA_API` / `_BURST` | `300/min` / `150` | clé API, MCP |
| `CAL_IUT_AA_BAN_SEUIL` | `30` | refus 429 avant bannissement (IP anonymes, `enforce`) |
| `CAL_IUT_AA_BAN_FENETRE` | `10min` | … dans cette fenêtre |
| `CAL_IUT_AA_BAN_DUREE` | `1h` | durée de ce bannissement |
| `CAL_IUT_AA_EXEMPTS` | vide | IP ou plages jamais limitées ni bannies automatiquement, séparées par des virgules. Le blocage manuel s'y applique quand même |
| `CAL_IUT_PROXYS_DE_CONFIANCE` | `127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7` | proxys dont uvicorn accepte `X-Forwarded-For` |

Formats : débit `N/s`, `N/min`, `N/h` (un nombre seul = par minute) ; rafale = requêtes acceptées d'un coup, seau plein ; durées `30s`, `10min`, `1h`, `24h`, `7j`.
Une valeur illisible garde le défaut, avec un avertissement dans le journal. Les variables sont relues à chaud (pas de cache figé au démarrage).

**Pourquoi ces budgets** (`_BUDGETS_DEFAUT`) :

- un humain sur un lien public fait 3 ou 4 requêtes à l'ouverture, puis plus rien (la navigation entre semaines est locale) ;
  mais une IP peut cacher un réseau entier (NAT de l'IUT, opérateur mobile) : 120 d'un coup puis 2/s, c'est 30 ouvertures simultanées ;
- l'appli sonde `/api/v1/version` toutes les 30 s connecté, toutes les 3 min sur un lien public, onglet visible seulement ;
- les agendas relisent les flux depuis quelques IP partagées par tous leurs utilisateurs : d'où un seau `ics` à part ;
- un client correct de l'API v1 revalide avec `If-None-Match` (réponse 304 sans corps) et ne dépasse pas 5/s en continu ; le MCP fait des rafales courtes.

### 6.5 Journal et analyse des journaux

En `observe` ou `enforce`, les dépassements sont journalisés (logger `cal_iut.anti_aspiration`, une ligne par épisode et par client, au plus une toutes les 10 s) :

```
WARNING cal_iut.anti_aspiration : dépassement mode=observe ip=203.0.113.66 catégorie=public identité=ip chemin=/app-state attente=1s
WARNING cal_iut.anti_aspiration : bannissement (observation, non appliqué) ip=203.0.113.66 (30 dépassements)
```

Récupérer les journaux (Dokploy → application → **Logs**, ou en SSH) :

```bash
docker ps --format '{{.Names}}' | grep -i cal-iut
docker logs --since 48h <conteneur-frontend> > nginx.log 2>&1
docker logs --timestamps --since 48h <conteneur-backend> > backend.log 2>&1
docker service logs --raw --since 48h <service> > nginx.log 2>&1      # si déployé en service Swarm
docker logs --since 7d <conteneur-backend> 2>&1 | grep cal_iut.anti_aspiration
```

Les analyser (bibliothèque standard seulement, tourne tel quel avec `python3` sur l'hôte) :

```bash
python3 scripts/analyser_acces.py backend.log nginx.log --top 30
python3 scripts/analyser_acces.py access.log.1 access.log.2.gz       # .gz lus tels quels
docker logs --since 24h <conteneur> 2>&1 | python3 scripts/analyser_acces.py
```

Le script sort les IP, User-Agents et chemins les plus fréquents (codes des flux masqués), la répartition par heure.
Il repère la cadence régulière, les User-Agents de robot ou vides, le balayage de liens `?t=` différents, le volume de nuit, la part écrasante du trafic.
Les clients d'agenda ne sont jamais signalés pour leur seule régularité.
Il propose des lignes `cal-iut bloquer … --prod` : **à relire**, il ne décide pas.

Sources : le journal nginx (frontend) a les User-Agents et, depuis le correctif, les vraies IP ; le journal uvicorn (backend) a les IP sans User-Agent ; le journal d'accès de Traefik, s'il est activé dans Dokploy, a l'IP réelle.

### 6.6 La liste de blocage

Fichier `data/state/blocages.json` (volume, écriture atomique, hors Git) :
`{"version": 1, "blocages": [{id, type: ip|cidr|user_agent, valeur, motif, auteur, cree_le, expire_le, automatique}]}`.

- Relue quand le fichier change (au plus un contrôle toutes les 5 s) : un `cal-iut bloquer` lancé **dans** le conteneur backend (`docker exec -it <backend> cal-iut bloquer …`) s'applique sans redémarrage.
- Les blocages expirés sont ignorés, puis purgés à l'écriture suivante.
- Garde-fous : une plage plus large que /8 (IPv4) ou /32 (IPv6) est refusée ; un motif de User-Agent fait au moins 3 caractères.
- Un blocage qui viserait l'administrateur (son IP, sa plage, son navigateur) est refusé sans confirmation (« Bloquer quand même », ou `--forcer`).

### 6.7 Côté interface

Une session qui expire ne fait pas bannir un vrai utilisateur.
Sur un 401, l'appli revient à l'écran de connexion et cesse de sonder. Un chargement du planning refusé (401/403) n'est pas retenté en boucle.
Code : `App.tsx` (état `refuse`), test `App.refusSansBoucle.test.tsx`.

### 6.8 Urgence : frein dans Traefik ou nginx

**Traefik** (Dokploy → application → **Advanced**, ou **Web Server → Traefik → File System** pour la configuration dynamique) :

```yaml
http:
  middlewares:
    cal-iut-frein:
      rateLimit:
        average: 10    # requêtes par seconde et par IP, en moyenne
        burst: 100
  routers:
    <routeur-de-l-application>:
      middlewares:
        - cal-iut-frein
```

Traefik n'a pas de liste noire d'IP intégrée (seulement une liste blanche `ipAllowList`, ou un plugin) : pour une IP précise, préférer le pare-feu.

**nginx** : `deny 203.0.113.66;` dans `frontend/nginx.conf.template`, puis redéployer le frontend.
Seulement si l'IP réelle fonctionne : sinon `$remote_addr` est l'IP de Traefik et le `deny` coupe tout le monde.

### 6.9 Exemple réel

Dans les journaux de production du 29/09/2026, `79.137.33.236` (un serveur loué) bouclait jusqu'à deux fois par seconde :

```
GET /export/json?t=promo   401
GET /app-state?t=promo     200
GET /meta?t=promo          200
```

Environ 19 401 refus en 90 s. Avec les protections par défaut, il est banni à son 30e refus (≈ 15 s), puis reçoit 403 partout.
Dans les mêmes journaux, des clients légitimes jamais bannis : une appli qui sonde `/api/v1/version` (304) toutes les 2 à 7 minutes, Google Agenda et des box sur `/ics/prof/XXX.ics?t=XXX`, un navigateur sur un lien personnel.
Ces cas sont couverts par `tests/test_bannissement_refus_2026_09_29.py`.

### 6.10 Pistes non réalisées

- **Liens signés et révocables** : `?t=<code>.<signature>` (HMAC avec `CAL_IUT_SECRET_KEY`).
  Un lien inventé serait refusé, un lien fuité révocable, les réponses limitées à ce que la page affiche (aujourd'hui `/app-state` rend tout le planning à n'importe quel lien).
  Coût : tous les liens déjà envoyés cessent de marcher (mails aux enseignants, liens de groupe, **abonnements `.ics`** à refaire). Prévoir une période qui accepte les deux formes.
- **Cloudflare et Turnstile** : filtre à la périphérie et défi invisible.
  Coût : changement de DNS et de TLS ; l'IP réelle arrive dans `CF-Connecting-IP` (adapter `forwardedHeaders.trustedIPs` de Traefik) ; exclure `/ics/` du défi (un agenda ne peut pas le passer).
- **Quotas par clé API** : budget par clé, quota journalier, compteur visible dans l'écran des clés, révocation automatique.
- `limit_req` dans nginx, avant Python.
- Un interrupteur de mode dans l'écran **Trafic**, sans redéploiement.

### 6.11 Données personnelles

Une adresse IP est une donnée personnelle.
Les compteurs vivent en mémoire, 24 h au plus, et sont perdus au redémarrage.
Le journal ne contient que l'IP, la catégorie et le chemin (sans paramètres, codes des flux masqués).
Les liens `?t=` ne sont comptés que par empreinte, jamais stockés.
La liste de blocage garde l'IP, un motif et l'auteur : motifs factuels, expiration dès que possible.
