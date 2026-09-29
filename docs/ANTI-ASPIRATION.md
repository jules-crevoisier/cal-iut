# Anti-aspiration — limiter et bloquer ceux qui aspirent le serveur

Mis en place le 29/09/2026, à la suite de ce constat : des clients
interrogent le serveur en boucle. **Tout est livré désactivé** : tant que la
variable `CAL_IUT_ANTI_ASPIRATION` n'est pas posée, rien ne change (le
mécanisme ne compte même pas). Ce document dit comment diagnostiquer,
activer pas à pas, et revenir en arrière.

Code : `src/cal_iut/api/anti_aspiration.py` (middleware, budgets, liste de
blocage, compteurs), `src/cal_iut/api/admin_trafic.py` (routes d'admin),
écran **Administration → Trafic**, commandes `cal-iut trafic | bloquer |
debloquer`, script `scripts/analyser_acces.py`.

---

## 1. Le constat

Les liens personnels publics (`?t=<n'importe quoi>`) ouvrent sans aucune
vérification `/app-state`, `/meta`, `/timetable`, `/api/v1/version` et les
flux `/ics/…` (`api/auth.py::verify_personal_link_param` : « la seule
présence d'une valeur suffit », décision du 28/08/2026, **inchangée ici**).
Un aspirateur n'a donc besoin d'aucun compte : `?t=x` suffit, et
`/app-state` rend tout le planning.

Conséquence : on ne peut pas refuser « par jeton ». On identifie le client
par son **adresse IP réelle** (et son User-Agent), on **limite son débit**, et
on le **bloque** s'il insiste. Les options qui changeraient le modèle des
liens (liens signés et révocables) sont décrites au § 7, avec ce qu'elles
coûtent.

## 2. Les couches

| Couche | Où | Actif par défaut ? |
|---|---|---|
| Robots polis : `robots.txt` (`Disallow: /`) et `X-Robots-Tag: noindex, nofollow` | `frontend/public/robots.txt`, nginx, `EnTeteNoIndex` | **Oui** (inoffensif) |
| IP réelle du client (non falsifiable) | nginx `real_ip`, `cal-iut serve` | **Oui**, part au prochain déploiement (§ 2.1) |
| Comptage du trafic par IP (15 min / 1 h / 24 h) | mémoire du backend | Non — à partir de `observe` |
| Limitation de débit (seau à jetons par client et par catégorie) | middleware | Non — journalise en `observe`, refuse (429) en `enforce` |
| Blocage manuel (IP, plage CIDR, motif de User-Agent) → 403 | `data/state/blocages.json` | Non — appliqué en `observe` **et** `enforce` |
| Bannissement automatique temporaire d'une IP qui insiste | liste de blocage | Non — `enforce` seulement |

### 2.1 IP réelle — le prérequis de tout le reste

Chemin d'une requête : **Traefik** (Dokploy) → **nginx** (conteneur
frontend) → **uvicorn** (conteneur backend).

Avant ce correctif :
- nginx ne connaissait que l'IP de Traefik (`$remote_addr`) : son journal
  d'accès attribuait **toutes** les requêtes à la même adresse privée ;
- nginx **ajoutait** à l'en-tête `X-Forwarded-For` reçu
  (`$proxy_add_x_forwarded_for`) ;
- uvicorn tournait avec `FORWARDED_ALLOW_IPS=*`. Vérifié sur uvicorn 0.54 :
  avec `*`, il retient la **première** adresse de l'en-tête — celle que le
  client écrit lui-même. `curl -H "X-Forwarded-For: 1.2.3.4" …` suffisait à
  changer d'IP à chaque requête, donc à passer sous tout plafond par IP
  (y compris celui de `/auth/login`).

Après :
- nginx calcule l'IP réelle : `set_real_ip_from` pour les plages privées
  Docker (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1, fc00::/7),
  `real_ip_header X-Forwarded-For`, `real_ip_recursive on` — l'en-tête est lu
  de droite à gauche en sautant les proxys ; une adresse inventée par le
  client reste à gauche et n'est jamais retenue. Son journal d'accès montre
  enfin les vraies IP ;
- nginx **écrase** l'en-tête : `proxy_set_header X-Forwarded-For $remote_addr;` ;
- `cal-iut serve` passe à uvicorn la liste des proxys de confiance
  (`CAL_IUT_PROXYS_DE_CONFIANCE`, par défaut les plages privées) : uvicorn
  lit l'en-tête de droite à gauche et s'arrête sur la première adresse qui
  n'est pas un proxy. `FORWARDED_ALLOW_IPS` n'est plus lue (retirée du
  Dockerfile).

Sans risque de blocage : au pire (proxy hors des plages privées), l'IP vue
est celle du proxy, comme dans le journal nginx aujourd'hui. **À déployer
avant, ou en même temps que l'activation** (étape 2 du § 4) : sans lui, la
limitation par IP est contournable et un blocage d'IP ne vise rien.
Les deux conteneurs doivent partir ensemble (frontend pour nginx, backend
pour uvicorn). Vérifié par `tests/test_anti_aspiration_2026_09_29.py`
(`test_ip_reelle_non_falsifiable`, `test_nginx_ecrase_x_forwarded_for…`).

### 2.2 Catégories et identité

Chaque requête est rangée dans une catégorie, avec un seau à jetons **par
identité** :

| Catégorie | Quoi | Identité |
|---|---|---|
| `statique` | `/assets/…`, `/favicon.svg`, `/robots.txt`, `/health`, `/healthz` | jamais limitée ni comptée |
| `sonde` | `/api/v1/version`, `/ics/version`, `/auth/status`, `/auth/me` sans compte | l'IP |
| `ics` | flux d'agenda `/ics/…` sans compte | l'IP |
| `public` | tout le reste sans compte : liens `?t=`, `/app-state`, `/meta`, `/timetable`, pages | l'IP |
| `appli` | cookie de session authentique (signature vérifiée) | le **compte** |
| `api` | `Authorization: Bearer caliut_…` valide (ou le jeton MCP d'environnement) | le **compte** |

Un compte a des budgets plus larges qu'une IP anonyme, et n'est **jamais
banni** automatiquement (on ne bannit pas un administrateur de son propre
outil) : il reçoit des 429, rien de plus. Un cookie ou une clé inventés ne
donnent pas le budget d'un compte (signature HMAC / clé relue en base).

Un blocage manuel (IP, plage, User-Agent) vise **tout le monde**, compte
connecté compris — sauf `/health`, pour ne jamais faire échouer le
`HEALTHCHECK` Docker.

## 3. Variables d'environnement (service **backend**)

| Variable | Défaut | Rôle |
|---|---|---|
| `CAL_IUT_ANTI_ASPIRATION` | `off` | `off` : rien du tout. `observe` : compte, journalise, applique les blocages manuels, ne refuse rien d'autre. `enforce` : refuse (429) et bannit. Valeur inconnue = `off`. |
| `CAL_IUT_AA_PUBLIC` / `_BURST` | `120/min` / `120` | lien public, pages (par IP) |
| `CAL_IUT_AA_ICS` / `_BURST` | `120/min` / `120` | flux `.ics` (par IP) |
| `CAL_IUT_AA_SONDE` / `_BURST` | `60/min` / `30` | numéro de révision (par IP) |
| `CAL_IUT_AA_APPLI` / `_BURST` | `600/min` / `300` | compte connecté |
| `CAL_IUT_AA_API` / `_BURST` | `300/min` / `150` | clé API / MCP |
| `CAL_IUT_AA_BAN_SEUIL` | `30` | refus avant bannissement (IP anonymes, `enforce`) |
| `CAL_IUT_AA_BAN_FENETRE` | `10min` | … dans cette fenêtre |
| `CAL_IUT_AA_BAN_DUREE` | `1h` | durée du bannissement automatique |
| `CAL_IUT_AA_EXEMPTS` | *(vide)* | IP ou plages jamais limitées, séparées par des virgules (ex. l'IP publique de l'IUT). Le blocage manuel s'y applique quand même. |
| `CAL_IUT_PROXYS_DE_CONFIANCE` | `127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7` | proxys dont uvicorn accepte `X-Forwarded-For` |

Formats : débit `N/s`, `N/min`, `N/h` (un nombre seul = par minute) ;
rafale = nombre de requêtes acceptées d'un coup, seau plein ; durées `30s`,
`10min`, `1h`, `24h`, `7j`. Une valeur illisible garde la valeur par défaut
(avec un avertissement dans le journal), jamais un plantage.

**Pourquoi ces valeurs** (détail dans `_BUDGETS_DEFAUT`) :
- un humain sur un lien public fait 3-4 requêtes à l'ouverture, puis plus
  rien (la navigation entre semaines est locale) ; mais une IP peut cacher
  tout un réseau (**NAT de l'IUT**, opérateur mobile) — 120 d'un coup puis
  2/s, c'est 30 ouvertures simultanées puis une toutes les deux secondes ;
- l'appli sonde `/api/v1/version` toutes les 30 s (connecté) ou toutes les
  3 min (lien public), onglet visible seulement ;
- les agendas (Google, Outlook, Apple) relisent chaque flux à intervalle
  fixe, **depuis quelques IP partagées par tous leurs utilisateurs** —
  d'où un seau `ics` séparé, à surveiller en observation ;
- un client légitime de l'API v1 revalide avec `If-None-Match` (304 sans
  corps) et n'a aucune raison de dépasser 5/s en continu.

Toutes ces valeurs sont **à calibrer en observation** avant tout `enforce`.

## 4. Plan d'activation, pas à pas

### Étape 1 — Diagnostiquer sans rien déployer

Récupérer les journaux et les passer à `scripts/analyser_acces.py`
(bibliothèque standard uniquement : il tourne tel quel sur l'hôte avec
`python3`).

**Quel journal ?** Aujourd'hui (correctif d'IP réelle pas encore déployé) :
- le journal **nginx** (conteneur frontend) montre l'IP de Traefik pour
  tout le monde — le script le détecte et prévient ; il reste utile pour les
  User-Agents, les chemins et les heures ;
- le journal **uvicorn** (conteneur backend) montre la première adresse
  de `X-Forwarded-For` : l'IP réelle du client (sauf s'il la falsifie), sans
  User-Agent. C'est la meilleure source pour les IP **avant** l'étape 2 ;
- le journal d'accès de **Traefik**, s'il est activé dans Dokploy (format
  JSON), contient l'IP réelle ; le User-Agent seulement si les en-têtes sont
  conservés dans sa configuration.

**Dans Dokploy** : projet → application (frontend ou backend) → onglet
**Logs** (choisir le nombre de lignes / la période, copier). Plus complet en
SSH sur l'hôte :

```bash
docker ps --format '{{.Names}}' | grep -i cal-iut        # trouver les conteneurs
docker logs --since 48h <conteneur-frontend> > nginx.log 2>&1
docker logs --timestamps --since 48h <conteneur-backend> > backend.log 2>&1
# Application déployée en service Swarm :
docker service ls | grep -i cal-iut
docker service logs --raw --since 48h <service> > nginx.log 2>&1
```

Puis :

```bash
python3 scripts/analyser_acces.py backend.log nginx.log --top 30
python3 scripts/analyser_acces.py access.log.1 access.log.2.gz   # .gz lus tels quels
docker logs --since 24h <conteneur> 2>&1 | python3 scripts/analyser_acces.py
```

Le script sort les IP, User-Agents et chemins les plus fréquents (codes des
flux masqués), la répartition par heure, et repère : **cadence régulière**
(écart constant entre requêtes), **User-Agent de robot ou vide**
(python-requests, curl, scrapy, headless…), **balayage de liens `?t=`
différents** (un humain en ouvre 1 à 3), **volume de nuit**, **part
écrasante du trafic**. Les clients d'agenda (Google Calendar, Outlook,
Apple…) ne sont jamais signalés pour leur seule régularité. Il propose enfin
des lignes `cal-iut bloquer … --prod` — **à relire** : il propose, il ne
décide pas.

### Étape 2 — Déployer le correctif d'IP réelle

Déployer **frontend** (nginx) **et backend** (uvicorn) avec ce code, sans
poser aucune variable. Rien ne change pour les utilisateurs.

Vérifier :
1. `docker logs <frontend>` : les nouvelles lignes montrent des IP
   publiques, plus l'IP privée de Traefik ;
2. depuis un poste : `curl -s -H "X-Forwarded-For: 1.2.3.4" https://<site>/auth/status`,
   puis (après l'étape 3) l'écran Trafic doit montrer **votre** IP, jamais
   `1.2.3.4`.

Si Traefik n'est pas sur une plage privée (cas inhabituel), le journal nginx
continue de montrer son IP : ajouter la sienne à `set_real_ip_from`
(`frontend/nginx.conf.template`) et à `CAL_IUT_PROXYS_DE_CONFIANCE`.

### Étape 3 — Observer une semaine

Dokploy → service backend → **Environment** : `CAL_IUT_ANTI_ASPIRATION=observe`,
puis redéployer. Rien n'est refusé (sauf les blocages manuels, s'il y en a).

Regarder **Administration → Trafic** (ou `cal-iut trafic --prod`) sur
15 min / 1 h / 24 h : plus gros clients, part de trafic public, User-Agent,
chemins, nombre de liens `?t=` différents, et surtout la colonne **Refus** —
en observation, ce sont les requêtes qui *auraient* été refusées. Les
dépassements sont aussi dans le journal du backend (logger
`cal_iut.anti_aspiration`, une ligne par épisode et par client, au plus une
toutes les 10 s, avec le nombre de refus tus depuis ; l'IP est la seule
donnée du client qui y figure) :

```
WARNING cal_iut.anti_aspiration : dépassement mode=observe ip=203.0.113.66 catégorie=public identité=ip chemin=/app-state attente=1s
WARNING cal_iut.anti_aspiration : bannissement (observation, non appliqué) ip=203.0.113.66 (30 dépassements)
```

```bash
docker logs --since 7d <conteneur-backend> 2>&1 | grep cal_iut.anti_aspiration
```

### Étape 4 — Ajuster les budgets

- Un **usage légitime** apparaît en dépassement (IP de l'IUT aux heures de
  cours, agenda Google, script d'un collègue) : relever le budget de sa
  catégorie, ou mettre l'IP dans `CAL_IUT_AA_EXEMPTS`, ou lui donner une
  clé API (budget de compte).
- Un **aspirateur** passe sous les budgets mais tourne toute la journée :
  c'est un cas de blocage manuel (étape 6), pas de budget.
- Viser : **aucun** dépassement légitime sur une semaine entière, incluant
  un lundi 8 h.

### Étape 5 — Passer en `enforce`

`CAL_IUT_ANTI_ASPIRATION=enforce`, redéployer. Au-delà du budget : **429**
avec `Retry-After` (secondes à attendre) ; l'interface web affiche le
message « Trop de requêtes. Réessayez dans N secondes. ». Une IP anonyme
qui reçoit `CAL_IUT_AA_BAN_SEUIL` refus en `CAL_IUT_AA_BAN_FENETRE` est
bannie `CAL_IUT_AA_BAN_DUREE` : elle apparaît dans la liste des blocages
avec la mention **automatique** (débloquable à la main).

Surveiller l'écran Trafic les premiers jours.

### Étape 6 — Blocages manuels

Écran Trafic : bouton **Bloquer…** sur une ligne (IP pré-remplie ; passer
à « User-Agent » reprend celui de la ligne), ou **Bloquer une adresse…** ;
durée 1 h / 24 h / 7 jours / permanent, motif. **Débloquer** dans la liste.
Un blocage qui viserait l'administrateur lui-même (son IP, sa plage ou son
navigateur) est refusé tant qu'on ne confirme pas (« Bloquer quand même »).

En ligne de commande (clé `CAL_IUT_PROD_API_KEY` d'un compte **admin** dans
`.env`, cf. `cal-iut lisser --prod`) :

```bash
cal-iut trafic --prod [--fenetre 15min|1h|24h]
cal-iut bloquer 203.0.113.66 --motif "aspire /app-state toutes les 10 s" --duree 7j --prod
cal-iut bloquer 203.0.113.0/24 --motif "hébergeur, 40 IP" --duree 24h --prod
cal-iut bloquer --ua "python-requests" --motif "robot" --duree permanent --prod
cal-iut debloquer <id> --prod
```

Sans `--prod`, les commandes écrivent la liste **locale**
(`data/state/blocages.json`). Dans le conteneur backend
(`docker exec -it <backend> cal-iut bloquer …`), c'est la liste de
production : le serveur la relit seul en moins de 5 s — utile si
l'interface est injoignable.

La liste est persistante (volume `data/state/`, écriture atomique) :
`{"version": 1, "blocages": [{id, type: ip|cidr|user_agent, valeur, motif,
auteur, cree_le, expire_le, automatique}]}`. Les blocages expirés sont
ignorés, puis purgés à l'écriture suivante. Garde-fous : une plage plus
large que /8 (IPv4) ou /32 (IPv6) est refusée, un motif de User-Agent fait
au moins 3 caractères.

**Prudence avec les IP partagées** : bloquer l'IP publique de l'IUT ou d'un
opérateur mobile coupe tout le monde derrière. Préférer une durée courte et
un motif de User-Agent quand le robot en a un reconnaissable.

## 5. Revenir en arrière

- **Tout couper** : `CAL_IUT_ANTI_ASPIRATION=off` (ou supprimer la variable)
  puis redéployer le backend — effectif dès le redémarrage (quelques
  secondes). En `off`, plus rien n'est compté, limité ni bloqué ; la liste
  de blocage reste en place, inerte, pour plus tard.
- **Un blocage de trop** : « Débloquer » dans l'écran Trafic ou
  `cal-iut debloquer <id> --prod` — immédiat, sans redémarrage.
- **Refuser moins sans tout couper** : repasser en `observe` (les bans
  automatiques cessent aussitôt de s'appliquer ; les blocages manuels
  restent), ou relever un budget.
- **Le correctif d'IP réelle** n'a pas à être défait : sans activation, il
  ne change rien d'autre que l'IP vue.

## 6. Urgence : l'application est saturée

Si le backend ne répond plus, l'écran Trafic non plus. Par ordre de
préférence :

1. **Liste de blocage depuis le conteneur** (si le conteneur répond encore
   à `docker exec`) — nécessite `observe` ou `enforce` :
   `docker exec <backend> cal-iut bloquer <ip> --motif urgence --duree 24h`.
2. **Pare-feu de l'hôte**, avant tout conteneur (effet immédiat, perdu au
   redémarrage de la machine) :
   ```bash
   sudo iptables -I DOCKER-USER -s 203.0.113.66 -j DROP     # bloquer
   sudo iptables -D DOCKER-USER -s 203.0.113.66 -j DROP     # retirer
   ```
3. **Traefik (Dokploy)** : un middleware `rateLimit` par IP devant le
   routeur de l'application (Dokploy → application → **Advanced** →
   configuration Traefik, ou **Web Server → Traefik → File System** pour la
   configuration dynamique) :
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
   Traefik n'a pas de liste noire d'IP intégrée (seulement une liste
   blanche `ipAllowList`, ou un plugin) : pour refuser une IP précise à ce
   niveau, préférer le pare-feu ci-dessus.
4. **nginx** (`deny 203.0.113.66;` dans `frontend/nginx.conf.template`,
   puis redéployer le frontend) — **seulement une fois l'IP réelle
   déployée** : avant, `$remote_addr` est l'IP de Traefik et un `deny`
   couperait tout le monde.

## 7. Options futures (non faites)

### Liens signés et révocables

Remplacer `?t=<code>` par `?t=<code>.<signature>` (HMAC du code et d'une
version, avec le secret `CAL_IUT_SECRET_KEY` déjà en place) — un jeton de
ce genre a existé avant le 28/08/2026 et a été retiré par décision. Gains :
un lien inventé ou deviné est refusé ; un lien fuité se révoque (on avance
sa version) ; les réponses pourraient être restreintes à ce que la page
affiche (aujourd'hui `/app-state` rend tout le planning à n'importe quel
lien). **Conséquences** : tous les liens déjà envoyés cessent de
fonctionner — mails aux enseignants (à renvoyer, l'envoi groupé existe),
liens de groupe transmis aux étudiants, **abonnements `.ics` dans les
agendas** (chacun doit se réabonner). Prévoir une période de transition
qui accepte les deux formes en journalisant l'ancienne, puis la couper.

### Cloudflare (proxy) et Turnstile

Cloudflare devant le domaine absorbe le trafic, filtre les robots connus et
permet des règles de débit à la périphérie ; Turnstile ajoute un défi
invisible sur les pages publiques. **Conséquences** : changement de DNS et
de terminaison TLS ; l'IP réelle arrive alors dans `CF-Connecting-IP` et
toutes les requêtes viennent des IP de Cloudflare — adapter Traefik
(`forwardedHeaders.trustedIPs` = plages Cloudflare) et vérifier l'étape 2,
sinon tout le monde partage quelques IP. Un défi est impossible pour un
client d'agenda : exclure `/ics/` de Turnstile.

### Quotas par clé API

Budget par clé (et non plus par compte), quota journalier, compteur
d'usage visible dans l'écran « Clé API » ; révocation automatique d'une
clé qui dépasse durablement.

### Autres

- `limit_req` dans nginx, avant Python, une fois l'IP réelle en place.
- Un interrupteur de mode dans l'écran Trafic (sans redéploiement).

## 8. Données personnelles

Une adresse IP est une donnée personnelle. Les compteurs vivent en mémoire
24 h au plus (perdus au redémarrage) ; le journal ne contient que l'IP, la
catégorie et le chemin (sans paramètres, codes des flux masqués) ; les
liens `?t=` ne sont comptés que par empreinte, jamais stockés. La liste de
blocage conserve l'IP, un motif et l'auteur : motifs factuels, et une
expiration dès que possible.
