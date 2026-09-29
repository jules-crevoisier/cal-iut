# API v1 — lecture de l'emploi du temps

Doc à donner telle quelle à qui veut lire l'emploi du temps MMI depuis un
script, une appli ou un tableau de bord. Base : `https://cal-iut-mmi.srko.fr`.

L'API v1 est en **lecture seule**. Les modifications passent par l'interface
web (ou le serveur MCP, cf. `docs/MCP.md`). Pour un simple agenda, les flux
`.ics` suffisent (cf. `docs/ICS.md`).

Documentation interactive générée (schémas exacts de chaque réponse) :
`/docs` (Swagger) et `/openapi.json`, sections « v1 · … ».

---

## 1. Principes

### Authentification

Mêmes règles que tout le reste de l'API (préfixe `/api` protégé) — une de ces
deux façons, au choix :

| Méthode | Comment |
|---|---|
| Clé API | En-tête `Authorization: Bearer caliut_…` (créée dans l'onglet « Clé API » de l'interface) |
| Cookie de compte | Session ouverte par `POST /auth/login` |

Sans rien de tout ça : `401 {"detail": "Authentification requise."}`.

Un **lien personnel public** (`?t=…`, celui envoyé aux enseignants et aux
groupes) n'ouvre que ce que sa page affiche (`/app-state`, `/meta`,
`/timetable`, `/ics/…`) et `GET /api/v1/version`, pour se remettre à jour —
jamais le reste de l'API v1 (audit du 29/09/2026). Une clé API est liée à un
compte : elle hérite de son rôle, et elle est révocable à tout moment depuis
l'interface.

### Révision de l'état

Le serveur tient un **numéro de révision** : un entier qui augmente à chaque
modification visible (séance déplacée, créée, supprimée, salle changée, tâche,
exception, régénération, configuration rechargée, changement de jour — le
statut « passée / en cours / future » des semaines en dépend). Il ne revient
jamais en arrière, même après un redémarrage du serveur.

```
GET /api/v1/version
```

C'est **le** point d'entrée pour savoir si quelque chose a changé : quelques
dizaines d'octets. Tant que `revision` ne bouge pas, rien n'a changé, et il est
inutile de relire quoi que ce soit.

### ETag et 304

Toutes les réponses v1 (ainsi que `/app-state`, `/meta`, `/timetable`,
`/diff`, `/ics/*`) portent :

```
ETag: W/"3b1f0c…"
Cache-Control: private, no-cache        (no-cache pour les flux .ics)
```

Renvoyez l'ETag reçu dans `If-None-Match` : si rien n'a changé, le serveur
répond **`304 Not Modified` sans corps**, sans rien recalculer. Un navigateur
le fait tout seul ; avec `curl` ou un script, c'est à vous de garder l'ETag.

L'ETag dépend de la révision, de l'URL (paramètres compris) et de la variante
(complète ou publique) : la variante publique ne peut jamais être servie à la
place de la complète, ni l'inverse.

### Compression

Toute réponse d'au moins 1 Ko part compressée en gzip si le client envoie
`Accept-Encoding: gzip` (`curl --compressed`). Ordre de grandeur : l'export
complet passe de 1,3 Mo à ≈ 60 Ko, `/app-state` de 590 Ko à ≈ 48 Ko.

### Conseils de sondage

- Sondez `GET /api/v1/version` (avec `If-None-Match`), **pas** les données.
  Toutes les 30 s à 5 min selon le besoin ; l'interface web le fait toutes
  les 30 s quand l'onglet est visible, et **pas du tout** quand il est caché.
- Quand `revision` a changé : relisez ce dont vous avez besoin (idéalement
  avec `If-None-Match` aussi — ce qui n'a pas changé revient en 304).
- Pour tout synchroniser d'un coup : `GET /api/v1/export`.
- Pour un agenda : les flux `.ics` (cf. `docs/ICS.md`), qui revalident eux
  aussi en 304.
- Un client trop bavard peut être limité (429 + `Retry-After`, à respecter)
  ou bloqué (403) : cf. [`docs/ANTI-ASPIRATION.md`](ANTI-ASPIRATION.md).

### Conventions

- Noms de champs en français, `snake_case`.
- Dates ISO `AAAA-MM-JJ`, horodatages ISO 8601 en UTC.
- Horaires lisibles `"HH:MM"` (`debut`, `fin`) **en plus** des index.
- Trois numérotations de semaine coexistent, toujours nommées explicitement :

| Champ | Sens | Exemple |
|---|---|---|
| `semaine` | index « solveur » (0, 1, 2…, sans trou pour les vacances) — celui qu'attendent les paramètres `semaine=` | `5` |
| `numero` / `numero_semaine` | « Semaine N » du département (semaine 1 = semaine ISO 35 de 2026) | `7` |
| `semaine_iso` | semaine calendaire ISO | `41` |

- Jours : `0` = lundi … `4` = vendredi. Créneaux : `0` = 08:00 … `5` = 17:00
  (cf. `/api/v1/creneaux`).
- Erreurs : `401` sans authentification, `404` pour une ressource inconnue ou
  tant qu'aucun planning n'est chargé, `422` pour un paramètre invalide.

---

## 2. Endpoints

Dans les exemples, `$CLE` est une clé API (`caliut_…`).

### `GET /api/v1/version`

```bash
curl -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/version
```

```json
{"revision": 1790676457688, "modifie_le": "2026-09-29T10:07:37.688427+00:00"}
```

Sondage économique, en gardant l'ETag :

```bash
curl -si -H "Authorization: Bearer $CLE" -H 'If-None-Match: W/"5f74e80c369acde6fe61"' \
  https://cal-iut-mmi.srko.fr/api/v1/version
# HTTP/1.1 304 Not Modified   ← rien n'a changé, pas de corps
```

### `GET /api/v1/semaines`

Toutes les semaines de l'année affichée, y compris les semaines bloquées
(vacances : `semaine` vaut alors `null`).

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/semaines
```

```json
[
  {"semaine": 0, "numero": 2, "semaine_iso": 36, "lundi": "2026-08-31",
   "libelle": "Semaine 2 (31 août–4 sept. 2026)", "bloquee": false, "statut": "passee"},
  {"semaine": 4, "numero": 6, "semaine_iso": 40, "lundi": "2026-09-28",
   "libelle": "Semaine 6 (28 sept.–2 oct. 2026)", "bloquee": false, "statut": "en_cours"}
]
```

`statut` : `passee`, `en_cours` ou `future` (seules les semaines futures sont
modifiables depuis l'interface).

### `GET /api/v1/creneaux`

```json
{
  "jours": [{"index": 0, "nom": "lundi"}, {"index": 1, "nom": "mardi"}, "…"],
  "creneaux": [
    {"index": 0, "debut": "08:00", "fin": "09:30", "libelle": "08:00–09:30"},
    {"index": 3, "debut": "14:00", "fin": "15:30", "libelle": "14:00–15:30"}
  ]
}
```

### `GET /api/v1/enseignants` · `GET /api/v1/enseignants/{code}` · `GET /api/v1/enseignants/{code}/seances`

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/enseignants/KBR
```

```json
{"code": "KBR", "nom": "KYLLIAN BRESSON", "email": "kyllian.bresson@univ-reims.fr",
 "nb_seances": 153, "cours": ["WR107", "WR110", "WR119"]}
```

La liste comprend aussi les
enseignants déclarés qui n'ont encore aucune séance (`nb_seances: 0`).

`/seances` accepte les mêmes paramètres que `GET /api/v1/seances` (`semaine`,
`du`, `au`, `limite`, `decalage`).

### `GET /api/v1/groupes` · `GET /api/v1/groupes/{id}` · `GET /api/v1/groupes/{id}/seances`

```json
{"id": "but1-td-ab", "libelle": "TD AB", "parcours": "BUT1", "annee": "BUT1", "type": "td",
 "groupes_lies": ["but1-tp-a", "but1-tp-b"],
 "cohorte": ["but1-promo", "but1-td-ab", "but1-tp-a", "but1-tp-b"]}
```

`cohorte` = tous les groupes dont les séances concernent ce groupe. Les
séances d'un groupe (`/groupes/{id}/seances`, ou `/seances?groupe=`)
incluent donc les CM de sa promo et, pour un TP, les TD de son TD parent —
exactement ce qu'un étudiant de ce groupe voit sur son planning.

### `GET /api/v1/salles` · `GET /api/v1/salles/{id}` · `GET /api/v1/salles/{id}/seances`

```json
{"id": "h018", "libelle": "H.018 (Amphi MMI)", "capacite": 150, "type": "amphi",
 "equipements": ["videoprojecteur", "sonorisation"], "placement_auto": true,
 "fusionne": [], "nb_seances": 70}
```

`fusionne` : pour une salle fusionnée (ex. `h007_h008`), les salles qu'elle
recouvre. `placement_auto: false` = jamais choisie par la génération
automatique, mais toujours choisissable à la main.

### `GET /api/v1/salles/libres?semaine=&jour=&creneau=`

Salles libres à un créneau précis, triées par capacité croissante (la plus
juste d'abord), et ce qui occupe les autres. Paramètre optionnel :
`capacite_min`.

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/salles/libres?semaine=5&jour=1&creneau=2&capacite_min=30"
```

```json
{
  "semaine": 5, "jour": 1, "creneau": 2, "date": "2026-10-06",
  "libres": [{"id": "h101", "libelle": "H.101", "capacite": 32, "type": "standard", "…": "…"}],
  "occupees": [
    {"salle_id": "h018", "motif": "seance", "seance_id": "WR118-S1-CM-3", "cours_code": "WR118"},
    {"salle_id": "h018", "motif": "reservation", "detail": "Besoin de la Direction"},
    {"salle_id": "h008", "motif": "salle_liee", "detail": "h007"}
  ]
}
```

Une salle est occupée par une séance qui la couvre (y compris une séance de
3 h commencée au créneau précédent), par une réservation d'un tiers
(`data/config/salles_reservees.yaml`), ou parce qu'une salle **liée** l'est
(`salle_liee` : H.007 occupée rend H.008 et H.007+H.008 indisponibles — même
règle que celle que le serveur applique à un changement de salle manuel). Une
salle annoncée libre ici est donc une salle que le serveur acceptera.

### `GET /api/v1/cours` · `GET /api/v1/cours/{code}` · `GET /api/v1/cours/{code}/seances`

Une entrée par (code, semestre, parcours) : un même module peut être décliné
dans plusieurs parcours.

```json
{"code": "WR101", "nom": "Anglais",
 "declinaisons": [{"code": "WR101", "nom": "Anglais", "semestre": "S1", "parcours": "BUT1",
                   "nb_cm": 1, "nb_td": 12, "nb_tp": 48, "nb_evaluations": 1, "nb_placees": 61,
                   "enseignants": ["TPA"]}]}
```

### `GET /api/v1/parcours` · `GET /api/v1/parcours/{id}` · `GET /api/v1/parcours/{id}/seances`

```json
{"id": "BUT1", "annee": 1, "semestres": ["S1", "S2"],
 "groupes": ["but1-promo", "but1-td-ab", "but1-td-cd", "but1-tp-a", "…"]}
```

### `GET /api/v1/seances`

Séances placées, triées par date puis heure de début. Tous les filtres sont
optionnels et se cumulent :

| Paramètre | Effet |
|---|---|
| `semaine` | index solveur (cf. `/api/v1/semaines`) |
| `enseignant` | code enseignant (`KBR`) |
| `groupe` | id de groupe — inclut la promo et le TD parent (cf. `cohorte`) |
| `salle` | id de salle (`h018`) |
| `cours` | code du cours (`WR101`) |
| `parcours` | parcours (`BUT2-DEV-FI`) |
| `du`, `au` | dates ISO incluses |
| `limite`, `decalage` | pagination (1 à 10 000 ; sans `limite`, tout) |

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/seances?groupe=but1-tp-a&du=2026-10-05&au=2026-10-09&limite=1"
```

```json
{
  "total": 21, "decalage": 0, "limite": 1,
  "seances": [{
    "id": "WR106-S1-TP-1-but1-tp-a", "cours_code": "WR106",
    "cours_nom": "Expression, communication et rhétorique", "type": "TP",
    "parcours": "BUT1", "semestre": "S1",
    "groupes": ["but1-tp-a"], "groupes_libelles": ["TP A"],
    "enseignants": ["MRI"], "enseignants_noms": ["…"],
    "salle_id": "h005", "salle_libelle": "H.005",
    "semaine": 5, "numero_semaine": 7, "date": "2026-10-05",
    "jour": 0, "jour_nom": "lundi", "creneau": 0, "duree_creneaux": 1,
    "debut": "08:00", "fin": "09:30", "horaire_libre": false,
    "evaluation": false, "verrouillee": false, "personnalisee": false
  }]
}
```

- `duree_creneaux` : `2` pour un bloc de 3 h — `fin` en tient compte.
- `horaire_libre: true` : événement à horaire libre (ex. 13h15–14h pendant la
  pause méridienne) ; `debut`/`fin` sont alors ses horaires RÉELS, `creneau`
  n'est que sa case de rangement.
- `personnalisee` : séance ajoutée depuis l'interface, hors maquette.

### `GET /api/v1/export`

Tout en un seul appel : `revision`, `modifie_le`, `jours`, `creneaux`,
`semaines`, `parcours`, `groupes`, `enseignants`, `salles`, `cours`,
`seances` (mêmes formats qu'aux routes dédiées). ≈ 1,3 Mo, ≈ 60 Ko
compressé.

```bash
# Synchronisation complète, seulement si quelque chose a changé
curl --compressed -H "Authorization: Bearer $CLE" \
  -H "If-None-Match: $ETAG_PRECEDENT" -D entetes.txt -o export.json \
  https://cal-iut-mmi.srko.fr/api/v1/export
```

---

## 3. Exemple : client qui reste à jour sans surcharger le serveur

```python
import time
import httpx

client = httpx.Client(
    base_url="https://cal-iut-mmi.srko.fr",
    headers={"Authorization": "Bearer caliut_…"},
)
etags: dict[str, str] = {}
donnees = None

def lire(chemin: str):
    entetes = {"If-None-Match": etags[chemin]} if chemin in etags else {}
    r = client.get(chemin, headers=entetes)
    if r.status_code == 304:
        return None                      # inchangé
    r.raise_for_status()
    etags[chemin] = r.headers["ETag"]
    return r.json()

while True:
    if lire("/api/v1/version") is not None:   # la révision a bougé
        donnees = lire("/api/v1/export") or donnees
    time.sleep(60)
```

---

## 4. Côté serveur (pour qui maintient le projet)

- Révision : `src/cal_iut/api/revision.py`. Avancée explicitement par
  `api/main.py::_apres_ecriture_planning` et les autres chemins d'écriture
  (ingest, solve, régénération, exceptions, tâches, salles, forçages, MCP
  `apply`), plus un middleware filet (`_RevisionApresEcriture`) sur toute
  écriture 2xx d'un préfixe protégé, et des sondes (jour, fichiers de
  configuration, état remplacé à la main).
- Cache + ETag : `src/cal_iut/api/cache_http.py` — une réponse n'est
  construite qu'une fois par (révision, URL, variante), puis resservie déjà
  sérialisée et, à la demande, déjà compressée.
- Routes v1 : `src/cal_iut/api/v1.py` — aucune règle métier propre : tout est
  relu depuis le payload de `/app-state` et les fonctions existantes
  (`_filter_timetable`, `_to_placement`, `_date_iso`…).
- Une nouvelle route de LECTURE qui dépend de l'état doit passer par
  `cache_http.repondre` ; une nouvelle route d'ÉCRITURE qui n'est pas un POST/
  PATCH/PUT/DELETE HTTP classique (thread, appel direct) doit appeler
  `revision.incrementer(...)` elle-même.
