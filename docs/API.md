# API v1 — lecture de l'emploi du temps

Doc à donner telle quelle à qui veut lire l'emploi du temps MMI depuis un
script, une appli ou un tableau de bord. Base : `https://cal-iut-mmi.srko.fr`.

L'API v1 est en **lecture seule** et expose tout ce que montrent les écrans :
planning, séances restant à placer, SAE (semaines de projet et cours), liste
« À traiter », doublons, contraintes, charges, modifications manuelles,
tâches, calendrier, état Celcat. Les modifications passent par l'interface web (ou le serveur MCP, cf.
`docs/MCP.md`). Pour un simple agenda, les flux `.ics` suffisent (cf.
`docs/ICS.md`).

**Documentation interactive** (schémas exacts, exemples, bouton « Try it
out ») : **`/api/v1/docs`**, schéma OpenAPI brut : **`/api/v1/openapi.json`**
— cf. §4.

## En un coup d'œil

| Endpoint (`GET`) | Contenu | Droits | Filtre `semaine=` |
|---|---|---|---|
| `/api/v1/version` | Numéro de révision — à sonder | compte, clé API **ou lien public** | — |
| `/api/v1/export` | Tout d'un coup (données, pas les vues calculées) | compte actif | — |
| `/api/v1/semaines` | Semaines de l'année, bloquées comprises, statut passée / en cours / future | compte actif | — |
| `/api/v1/creneaux` | 5 jours × 6 créneaux horaires | compte actif | — |
| `/api/v1/enseignants[/{code}]` | Enseignants (adresse de contact), nombre de séances, cours | compte actif | — |
| `/api/v1/groupes[/{id}]` | Groupes, groupes liés, cohorte | compte actif | — |
| `/api/v1/salles[/{id}]` | Catalogue des salles | compte actif | — |
| `/api/v1/cours[/{code}]` | Maquette par parcours (champ `sae`) ; la fiche ajoute la **progression** | compte actif | — |
| `/api/v1/parcours[/{id}]` | Parcours, semestres, groupes | compte actif | — |
| `/api/v1/seances` (+ `/{enseignants,groupes,salles,cours,parcours}/{id}/seances`) | Séances placées, filtrables, paginables | compte actif | oui |
| `/api/v1/seances/non-placees` | Séances restant à placer (panneau « À placer ») ; `inclure_sae=true` pour les cours de SAE | compte actif | oui ¹ |
| `/api/v1/salles/libres` | Salles libres à un créneau précis | compte actif | obligatoire |
| `/api/v1/calendrier` | Fériés, vacances, évènements, jours SAE, réservations de salles | compte actif | oui |
| `/api/v1/sae/periodes` | Semaines de projet SAÉ (les évènements journée entière des `.ics`) | compte actif | oui (+ `du`/`au`) |
| `/api/v1/sae/journees` | Journées SAE, une par jour et par parcours, avec les cours de SAE placés ce jour-là | compte actif | oui (+ `du`/`au`) |
| `/api/v1/sae[/{code}]` | Cours de SAE : maquette, encadrants, placés (dans / hors journée SAE), non placés | compte actif | oui |
| `/api/v1/a-traiter` | Écran « À traiter » : points à corriger / à revoir | compte actif ² | oui |
| `/api/v1/controles/doublons` | Salle ou enseignant pris deux fois | rôle **edit** | oui |
| `/api/v1/manques` | Données de référence à compléter (mail, nom, Celcat, type de salle, intitulé) | compte actif | — |
| `/api/v1/contraintes` | Règles globales + contrainte et verdict de chaque enseignant | compte actif | — |
| `/api/v1/enseignants/{code}/contraintes` | La même chose pour un enseignant | compte actif | — |
| `/api/v1/charges` | Heures par enseignant, groupe, cours, parcours ; occupation des salles | compte actif | oui ³ |
| `/api/v1/modifications` | Séances déplacées à la main depuis la génération | compte actif | oui |
| `/api/v1/taches` | Cartes du tableau de suivi | compte actif | — |
| `/api/v1/celcat/etat` | Synchronisation Celcat et file d'attente | rôle **admin** | — |
| `/api/v1/docs`, `/api/v1/openapi.json` | Documentation interactive, schéma | compte actif | — |

¹ celles qui *peuvent* aller dans cette semaine. ² les doublons n'y figurent
que pour un rôle `edit` ou `admin`. ³ en plus du détail de toutes les
semaines, toujours présent (`heures_par_semaine`).

« Compte actif » = cookie de compte ou clé API d'un compte activé, quel que
soit son rôle (`read_only`, `edit`, `admin`).

---

## Obtenir une clé API

1. Se connecter à l'appli avec son compte (un administrateur doit l'avoir
   activé).
2. Ouvrir le **menu du compte** (avatar, en bas de la barre latérale) →
   **Clé API** → « Générer une clé ».
3. Copier la clé `caliut_…` **tout de suite** : elle n'est affichée qu'une
   fois (seule son empreinte est gardée côté serveur).
4. L'envoyer dans chaque requête : `Authorization: Bearer caliut_…`.

La clé **hérite du rôle du compte** (un compte `read_only` n'obtient pas les
doublons, seul un `admin` lit l'état Celcat), et se **révoque** depuis le
même écran à tout moment. C'est la même clé que pour le serveur MCP et la
commande `cal-iut prod`. Ne la mettez jamais dans une page web publique ni
dans un dépôt : quiconque la détient lit tout ce que lit le compte.

```bash
export CLE=caliut_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
curl -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/version
```

---

## Quel endpoint pour quel besoin

| Besoin | Appels |
|---|---|
| **Afficher le planning d'un prof** (semaine en cours) | `/api/v1/semaines` (repérer `statut: "en_cours"` → `semaine`), puis `/api/v1/enseignants/KBR/seances?semaine=5`. Pour un agenda : le flux `.ics` (`docs/ICS.md`). |
| **Planning d'un groupe d'étudiants** | `/api/v1/groupes/but1-tp-a/seances?du=…&au=…` — inclut le CM de la promo et les TD du TD parent. |
| **Écran d'affichage dans un couloir** (séances du jour, salles libres) | `/api/v1/seances?du=2026-10-05&au=2026-10-05` + `/api/v1/salles/libres?semaine=5&jour=0&creneau=2` ; sonder `/api/v1/version` toutes les 1 à 5 min, ne relire que si la révision change. |
| **Afficher les semaines de projet SAÉ** (bandeaux dans un agenda) | `/api/v1/sae/periodes?parcours=BUT1` — ou `sae.periodes` dans `/api/v1/export`. |
| **Savoir ce qui se passe un jour de SAE** (encadrants, cours posés) | `/api/v1/sae/journees?du=…&au=…` |
| **Suivre une SAE** (volumes, encadrants, cours placés ou non, anomalies) | `/api/v1/sae/WS501D`, ou `/api/v1/sae` (`anomalies` en tête). |
| **Trouver une salle** | `/api/v1/salles/libres?semaine=…&jour=…&creneau=…&capacite_min=30`. |
| **Suivre les corrections à faire** | `/api/v1/a-traiter` (filtrable par `semaine`, `parcours`, `enseignant`, `gravite`, `nature`), `/api/v1/seances/non-placees`, `/api/v1/controles/doublons`. |
| **Vérifier les contraintes d'un enseignant** | `/api/v1/enseignants/MRI/contraintes` (texte déclaré, créneaux interdits, verdict, écarts datés, absences). |
| **Tableau de bord des charges** | `/api/v1/charges` — toutes les semaines d'un coup dans `heures_par_semaine`. |
| **Savoir ce qui a bougé à la main** | `/api/v1/modifications` (avant / après). |
| **Reprendre le suivi de l'équipe** | `/api/v1/taches?colonne=a_faire`. |
| **Synchroniser un outil tiers** (tout copier, rester à jour) | Sonder `/api/v1/version` avec `If-None-Match` ; quand elle change, `/api/v1/export` (1 appel, ≈ 60 Ko compressé). Ajouter `/api/v1/a-traiter` et `/api/v1/charges` si l'outil en a besoin. Cf. §6. |
| **Superviser la saisie Celcat** (admin) | `/api/v1/celcat/etat`. |

---

## 1. Principes

### Authentification

Mêmes règles que tout le reste de l'API (préfixe `/api` protégé) — une de ces
deux façons, au choix :

| Méthode | Comment |
|---|---|
| Clé API | En-tête `Authorization: Bearer caliut_…` (cf. « Obtenir une clé API ») |
| Cookie de compte | Session ouverte dans l'appli (`POST /auth/login`) — c'est ce qu'utilise la doc interactive |

Sans rien de tout ça : `401 {"detail": "Authentification requise."}`. Un
compte en attente d'activation reçoit `403`.

Un **lien personnel public** (`?t=…`, celui envoyé aux enseignants et aux
groupes) n'ouvre que ce que sa page affiche (`/app-state`, `/meta`,
`/timetable`, `/ics/…`) et `GET /api/v1/version`, pour se remettre à jour —
**jamais** le reste de l'API v1, ni sa documentation (audit du 29/09/2026 ;
vérifié route par route par `tests/test_lien_perso_perimetre_2026_09_29.py`).

### Droits

Chaque endpoint reprend les droits de l'écran correspondant de l'appli :

- **tout compte actif** : planning, référentiel, non placées, « À traiter »
  (sans les doublons pour `read_only`), contraintes, charges, modifications,
  tâches, calendrier ;
- **rôle `edit` ou `admin`** : `/api/v1/controles/doublons` (comme
  `GET /controles/doublons`) — et la nature `doublon` dans `/a-traiter` ;
- **rôle `admin`** : `/api/v1/celcat/etat` (comme l'onglet Celcat).

Un rôle insuffisant reçoit `403 {"detail": "Permissions insuffisantes pour
cette action."}`.

Ce que l'API ne sort **jamais** : comptes et utilisateurs, adresses mail de
comptes (l'auteur d'une tâche n'est pas exposé pour cette raison), mots de
passe ou empreintes, clés API, jetons de session, identifiants ou journaux
bruts Celcat, chemins sur le disque. Les adresses de **contact** des
enseignants (`/api/v1/enseignants`, fichier `teacher_contacts.yaml`) et
leurs contraintes déclarées sont lisibles par tout compte actif, comme dans
l'appli.

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

L'ETag dépend de la révision, de l'URL (paramètres compris), de la variante
(complète ou publique) et, pour `/a-traiter`, du rôle (doublons inclus ou
non) : une variante ne peut jamais être servie à la place d'une autre.

Exception : `/api/v1/celcat/etat`. Le worker Celcat écrit sans passer par
l'API, donc sans faire avancer la révision ; son ETag est celui du
**contenu**. Le 304 marche aussi, mais la réponse est recalculée à chaque
appel — ne la sondez pas plus d'une fois par minute.

### Compression

Toute réponse d'au moins 1 Ko part compressée en gzip si le client envoie
`Accept-Encoding: gzip` (`curl --compressed`). Ordre de grandeur : l'export
complet passe d'environ 1,5 Mo à ≈ 70 Ko, `/app-state` de 590 Ko à ≈ 48 Ko.

### Limitation de débit

**600 requêtes par minute et par compte** (clé API ou cookie ; 3 000 par
adresse IP pour un lien public, qui ne lit que `/version` — toute une salle
peut partager la même adresse). Au-delà :
`429 Too Many Requests` avec un en-tête `Retry-After` (secondes). Un 304
compte comme une requête. Ce plafond ne gêne aucun usage normal (l'appli
elle-même sonde `/version` toutes les 30 s) : il arrête un script qui boucle
sans pause.

### Conseils de sondage

- Sondez `GET /api/v1/version` (avec `If-None-Match`), **pas** les données.
  Toutes les 30 s à 5 min selon le besoin ; l'interface web le fait toutes
  les 30 s quand l'onglet est visible, et **pas du tout** quand il est caché.
- Quand `revision` a changé : relisez ce dont vous avez besoin (idéalement
  avec `If-None-Match` aussi — ce qui n'a pas changé revient en 304).
- Pour tout synchroniser d'un coup : `GET /api/v1/export`.
- Pour un agenda : les flux `.ics` (cf. `docs/ICS.md`), qui revalident eux
  aussi en 304.

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

  Seule exception : `/api/v1/celcat/etat`, dont les listes de semaines
  suivent la numérotation de l'onglet Celcat.
- Jours : `0` = lundi … `4` = vendredi. Créneaux : `0` = 08:00 … `5` = 17:00
  (cf. `/api/v1/creneaux`). Un créneau dure 1 h 30 ; un bloc de 3 h compte
  2 créneaux (`duree_creneaux: 2`).
- Gravité (`/a-traiter`) : `a_corriger` (rouge à l'écran) ou `a_revoir`
  (ambre).
- Erreurs : `401` sans authentification, `403` rôle insuffisant, `404` pour
  une ressource inconnue ou tant qu'aucun planning n'est chargé, `422` pour un
  paramètre invalide, `429` débit dépassé.

---

## 2. Endpoints — planning et référentiel

Dans les exemples, `$CLE` est une clé API (`caliut_…`). Tous les endpoints
sont en `GET` ; droits : **tout compte actif** sauf mention contraire.

### `GET /api/v1/version`

Droits : compte actif, clé API **ou lien public** `?t=`.

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
  {"semaine": 5, "numero": 7, "semaine_iso": 41, "lundi": "2026-10-05",
   "libelle": "Semaine 7 (5–9 oct. 2026)", "bloquee": false, "statut": "future"}
]
```

`statut` : `passee`, `en_cours` ou `future` (seules les semaines futures sont
modifiables depuis l'interface).

### `GET /api/v1/creneaux`

```bash
curl -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/creneaux
```

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

`email` : adresse de **contact** de l'enseignant (saisie dans la
configuration), pas celle d'un compte. La liste comprend aussi les
enseignants déclarés qui n'ont encore aucune séance (`nb_seances: 0`).

`/seances` accepte les mêmes paramètres que `GET /api/v1/seances` (`semaine`,
`du`, `au`, `limite`, `decalage`). Contraintes de l'enseignant :
`/api/v1/enseignants/{code}/contraintes` (§3).

### `GET /api/v1/groupes` · `GET /api/v1/groupes/{id}` · `GET /api/v1/groupes/{id}/seances`

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/groupes/but1-td-ab
```

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

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/salles/h018
```

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
dans plusieurs parcours. La fiche `/cours/{code}` ajoute la **progression** :
toutes les séances de la maquette dans l'ordre pédagogique, placées ou non.

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/cours/WR101
```

```json
{"code": "WR101", "nom": "Anglais",
 "declinaisons": [{"code": "WR101", "nom": "Anglais", "semestre": "S1", "parcours": "BUT1",
                   "nb_cm": 1, "nb_td": 12, "nb_tp": 48, "nb_evaluations": 1, "nb_placees": 61,
                   "enseignants": ["TPA"], "progression_definie": true,
                   "ordonnancement": [{"position": "after", "cible": "WR102"}]}],
 "progression": [
   {"seance_id": "WR101-S1-CM-1", "ordre": 1, "type": "CM", "semestre": "S1", "parcours": "BUT1",
    "groupes": ["but1-promo"], "enseignants": ["TPA"], "duree_creneaux": 1, "evaluation": false,
    "placee": true, "semaine": 0, "date": "2026-09-01", "debut": "08:00"},
   {"seance_id": "WR101-S1-TD-12-but1-td-ab", "ordre": 12, "type": "TD", "…": "…",
    "placee": false, "semaine": null, "date": null, "debut": null}
 ]}
```

`ordre` : rang dans la progression (`null` si la maquette n'en fixe pas).
`ordonnancement` : contraintes d'ordre avec d'autres cours (`position` :
`before`, `same` ou `after` le cours `cible`).

### `GET /api/v1/parcours` · `GET /api/v1/parcours/{id}` · `GET /api/v1/parcours/{id}/seances`

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/parcours/BUT1
```

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
| `sae` | `true` : seulement les cours de SAE ; `false` : sans eux |
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
    "evaluation": false, "verrouillee": false, "personnalisee": false, "evenement": false,
    "sae": false, "dans_journee_sae": null
  }]
}
```

- `duree_creneaux` : `2` pour un bloc de 3 h — `fin` en tient compte.
- `horaire_libre: true` : événement à horaire libre (ex. 13h15–14h pendant la
  pause méridienne) ; `debut`/`fin` sont alors ses horaires RÉELS, `creneau`
  n'est que sa case de rangement.
- `personnalisee` : séance ajoutée depuis l'interface, hors maquette.
- `evenement` : évènement hors maquette (réunion, conférence…) créé depuis
  l'interface — toujours `personnalisee` aussi.
- `sae` : cours d'une SAE (code `WS…`) ; `dans_journee_sae` : pour un cours
  de SAE, tombe-t-il sur une journée SAE de son parcours (`null` si ce n'est
  pas une SAE) — cf. §2 bis.

### `GET /api/v1/seances/non-placees`

Séances de la maquette absentes du planning — le panneau « À placer » de la
Vue Promo, calculé par différence (maquette − planning ; les SAE que le
solveur ne place pas sont exclues). Filtres : `parcours`, `cours`,
`enseignant`, et `semaine` (celles qui *peuvent* aller dans cette semaine,
d'après l'ordre pédagogique).

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/seances/non-placees?parcours=BUT2-DEV-FI"
```

```json
{
  "total": 1, "total_a_placer": 3093, "total_placees": 2384, "par_parcours": {"BUT2-DEV-FI": 1},
  "resume": "14 séance(s) sur 3093 restent à placer à la main. …",
  "seances": [{
    "id": "WR305-S3-TD-4-but2-dev-td", "cours_code": "WR305", "cours_nom": "Développement back",
    "type": "TD", "semestre": "S3", "parcours": "BUT2-DEV-FI", "annee": "BUT2",
    "duree_creneaux": 1, "duree_libelle": "1h30",
    "groupes": ["but2-dev-td"], "groupes_libelles": ["TD DEV"],
    "enseignants": ["KBR"], "enseignants_noms": ["KYLLIAN BRESSON"],
    "ordre": 4, "semaines_possibles": [6, 7, 8],
    "raison": "Aucun créneau commun libre pour le groupe et l'enseignant.",
    "placee_provisoirement": false, "semaine_actuelle": null, "jour_actuel": null, "creneau_actuel": null,
    "sae": false, "statut": "a_placer"
  }]
}
```

`placee_provisoirement: true` : séance posée en forçant l'ordre pédagogique,
en attente de validation — elle reste listée (avec sa position actuelle),
comme à l'écran (`statut: "en_attente_validation"`, sinon `"a_placer"`).

**Cours de SAE** : comme l'écran « À placer », la liste n'inclut PAS par
défaut les cours de SAE que la génération ne place pas (ils s'organisent sur
les journées SAE, cf. §2 bis). `inclure_sae=true` les ajoute, avec
`statut: "hors_solveur"`, `sae: true` et, en `semaines_possibles`, les
semaines des journées SAE du parcours. `total_a_placer` compte toutes les séances de la maquette
(SAE comprises), `total_placees` celles du planning.

### `GET /api/v1/calendrier`

Tout ce que les grilles affichent en plus des séances. Filtre `semaine`
(sauf `periodes_institutionnelles`, toujours complètes).

```bash
curl --compressed -H "Authorization: Bearer $CLE" "https://cal-iut-mmi.srko.fr/api/v1/calendrier?semaine=9"
```

```json
{
  "jours_sans_cours": [{"semaine": 9, "numero_semaine": 12, "date": "2026-11-11", "jour": 2,
                        "type": "ferie", "libelle": "Armistice"}],
  "evenements_jour": [],
  "evenements_creneau": [{"semaine": 0, "numero_semaine": 2, "date": "2026-08-31", "jour": 0, "creneau": 3,
                          "debut": "14:00", "fin": "15:30", "libelle": "14h00–15h30 Rentrée",
                          "parcours": ["BUT3-DEV-FC"], "salle": "H.018"}],
  "jours_sae": [{"semaine": 3, "numero_semaine": 5, "date": "2026-09-24", "jour": 3,
                 "parcours": "BUT3-CREACOM-FC", "cours": ["WSA501C"]}],
  "reservations_salles": [{"salle_id": "h018", "date": "2026-09-11", "semaine": 1, "jour": 4,
                           "creneaux": [1, 2], "motif": "Besoin de la Direction (amphi H, 9h30-12h30)"}],
  "periodes_institutionnelles": [{"libelle": "Vacances de la Toussaint", "debut": "2026-10-24",
                                  "fin": "2026-11-01", "type": "vacances"}]
}
```

| Clé | Contenu |
|---|---|
| `jours_sans_cours` | jours fériés (`ferie`) et de vacances (`vacances`) tombant dans une semaine de cours |
| `evenements_jour` | évènements du planning du département, à la journée |
| `evenements_creneau` | évènements du planning sur un créneau précis (salle éventuelle) |
| `jours_sae` | jours réservés aux SAE, par parcours (repère : pas de salle ni d'horaire) |
| `reservations_salles` | salles prises par des tiers (`salles_reservees.yaml`) |
| `periodes_institutionnelles` | calendrier de l'université (rentrée, vacances, fériés) |

Les absences ponctuelles d'enseignants et les salles indisponibles saisies
dans l'appli sont dans `/api/v1/contraintes` (`exceptions`). `jours_sae` est
le bandeau de la Vue Promo ; pour les SAE en détail (périodes, journées,
encadrants, cours), voir §2 bis.

---

## 2 bis. SAE : semaines de projet et cours

Deux choses différentes portent le nom de SAE :

| | Journée / période SAE | Cours de SAE |
|---|---|---|
| Quoi | Un **bloc de calendrier** réservé à un parcours (journée entière) : aucun cours classique du parcours n'y est placé | Une **séance** de la maquette d'une SAE (code `WS…`), avec type, groupes, enseignants, durée |
| D'où | Calendrier officiel des SAE de l'établissement (`contraintes/09_dates_sae.json`), corrigé par `data/config/sae_corrections.yaml` | Maquette (`progression.json`) |
| Où dans l'API | `/api/v1/sae/periodes`, `/api/v1/sae/journees` | `/api/v1/sae`, `/api/v1/sae/{code}`, `/api/v1/seances?sae=true` |
| Dans les `.ics` | Évènement journée entière « Semaine de projet/évaluation SAE — WS501D » | Séance ordinaire, si elle est placée |

**Règle** : un cours de SAE n'a lieu **que sur une journée SAE** de son
parcours. Exception déclarée : les rares SAE que la génération place
elle-même (`solver_scheduled_sae` dans `course_scheduling_rules.yaml`, ex.
WSA501D, qui n'a aucune date au calendrier officiel). Un cours de SAE placé
hors journée SAE sans exception déclarée est une **anomalie**, listée par
`/api/v1/sae` (`anomalies`, `nb_anomalies`). L'écran « À traiter » n'a pas
(encore) cette catégorie.

La plupart des cours de SAE ne sont **pas placés** : la génération ne les
place pas, les enseignants les organisent sur les journées SAE. Ils restent
visibles dans `/api/v1/sae` (`non_placees`, `statut: "hors_solveur"`).

### `GET /api/v1/sae/periodes` — semaines de projet SAÉ

Équivalent exact des **évènements journée entière des flux `.ics`** : même
source (`ics_feed.periodes_sae`), même découpage, même `id` (l'UID de
l'évènement). Une période = une suite de jours SAE consécutifs d'une même SAE
(le week-end ne coupe pas). Filtres : `parcours` (les SAE au parcours
introuvable, `parcours: null`, concernent tout le monde et sont toujours
incluses — comme dans les `.ics`), `semaine`, `du`, `au` (chevauchement).

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/sae/periodes?parcours=BUT3-DEV-FI"
```

```json
[{"id": "WS501D-2026-10-19", "code": "WS501D",
  "intitule": "Développer pour le web ou Concevoir un dispositif interactif",
  "libelle": "WS501D", "titre": "SAE WS501D", "description": "Semaine de projet/évaluation SAE — WS501D",
  "parcours": "BUT3-DEV-FI", "groupes": [],
  "date_debut": "2026-10-19", "date_fin": "2026-10-22",
  "jours": ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"], "nb_jours": 4,
  "semaines": [7], "numeros_semaine": [9]}]
```

`date_debut` et `date_fin` sont **incluses**. `groupes` : TD concernés
(libellés courts, ex. `["AB"]`) quand la SAE ne réserve le jour qu'à une
partie de la promo ; vide = tout le parcours.

### `GET /api/v1/sae/journees` — journées SAE

Les mêmes périodes dépliées **jour par jour et par parcours**, avec pour
chaque journée : la ou les SAE concernées et leur origine
(`calendrier_officiel` ou `correction_locale` + motif), les groupes
concernés, les encadrants attendus ce jour-là (d'après
`sae_teacher_phases.yaml`), et les **cours de SAE effectivement placés** ce
jour-là. Une journée SAE bloque les 6 créneaux (`journee_entiere: true`).
Filtres : `parcours`, `semaine`, `du`, `au`.

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/sae/journees?parcours=BUT3-CREACOM-FC&du=2026-09-24&au=2026-09-24"
```

```json
{"total": 1, "par_parcours": {"BUT3-CREACOM-FC": 1}, "journees": [{
  "id": "BUT3-CREACOM-FC|2026-09-24", "date": "2026-09-24", "semaine": 3, "numero_semaine": 5,
  "jour": 3, "jour_nom": "jeudi", "parcours": "BUT3-CREACOM-FC", "groupes": [],
  "journee_entiere": true, "creneaux": [0, 1, 2, 3, 4, 5],
  "sae": [{"code": "WSA501C", "intitule": "Création engagée et communication d'acceptabilité",
           "origine": "correction_locale",
           "motif": "Les journées SAE de l'établissement ne coïncidaient pas avec les disponibilités déclarées du vacataire : …"}],
  "encadrants": [], "seances": []}]}
```

### `GET /api/v1/sae` · `GET /api/v1/sae/{code}` — cours de SAE

Une entrée par SAE (code, semestre, parcours) : volumes de la maquette,
enseignants, référents et leurs phases d'encadrement, journées réservées,
cours **placés** (chacun marqué `dans_journee_sae`, `exception`, `anomalie`)
et cours **non placés** (avec `statut` et `raison`). En tête, les totaux et la
liste des anomalies. Filtres : `parcours`, `semaine` (SAE ayant une journée
ou un cours placé cette semaine ; listes réduites à cette semaine, sauf
`non_placees`). `/sae/{code}` renvoie `{"code", "intitule", "declinaisons":
[…]}` (une déclinaison par parcours).

```bash
curl --compressed -H "Authorization: Bearer $CLE" "https://cal-iut-mmi.srko.fr/api/v1/sae?parcours=BUT3-DEV-FC"
```

```json
{
  "total": 2, "nb_seances_maquette": 26, "nb_placees": 17, "nb_non_placees": 9,
  "nb_dans_journee_sae": 0, "nb_exceptions": 17, "nb_anomalies": 0, "anomalies": [],
  "sae": [{
    "code": "WSA501D", "intitule": "…", "parcours": "BUT3-DEV-FC", "semestre": "S5", "annee": "BUT3",
    "planifiee_par_solveur": true, "commentaire_edt": null,
    "nb_cm": 0, "nb_td": 34, "nb_tp": 0, "nb_evaluations": 0,
    "nb_seances_maquette": 17, "nb_placees": 17, "nb_non_placees": 0,
    "enseignants": ["BTO", "JSA"], "enseignants_noms": ["…"], "encadrants": [], "jours_reserves": [],
    "nb_dans_journee_sae": 0, "nb_exceptions": 17, "nb_anomalies": 0,
    "seances": [{"id": "…", "cours_code": "WSA501D", "date": "2026-08-31", "debut": "15:30", "fin": "18:30",
                 "…": "… (mêmes champs que /api/v1/seances)",
                 "sae": true, "dans_journee_sae": false, "journee_sae": null,
                 "exception": true, "motif_exception": "SAE placée par la génération (`solver_scheduled_sae`) : …",
                 "anomalie": false}],
    "non_placees": []
  }]
}
```

- `encadrants[].jours` : jours où l'enseignant est compté comme encadrant
  (tous les jours de la SAE, ou ceux de ses phases déclarées) — ce qui
  produit les compromis « Encadrement SAE » de `/api/v1/contraintes`.
- `non_placees[].statut` : `hors_solveur` (organisé par les enseignants sur
  les journées SAE), `a_placer` (SAE placée par la génération, cours
  manquant), `en_attente_validation`.
- `commentaire_edt` : commentaire de la maquette à l'attention de l'EDT.
- Chaque cours de SAE de la maquette apparaît **une seule fois**, soit dans
  `seances`, soit dans `non_placees`.

---

## 3. Endpoints — contrôles, suivi, statistiques

### `GET /api/v1/a-traiter`

Droits : tout compte actif ; la nature `doublon` n'est incluse que pour un
rôle `edit` ou `admin` (`doublons_inclus`).

Même contenu, mêmes catégories et même ordre que l'écran **« À traiter »** :

| `nature` | Titre à l'écran | `gravite` |
|---|---|---|
| `non-placee` | Séances non placées (regroupées : `nombre: 5` = « ×5 ») | `a_corriger` |
| `sans-salle` | Séances sans salle | `a_corriger` |
| `doublon` | Doublons salle / enseignant | `a_corriger` |
| `regle` | Règles globales en échec | `a_corriger` |
| `contrainte` | Indisponibilités enseignant non respectées | `a_corriger` |
| `compromis-sae` | Encadrement SAE le même jour (compromis accepté) | `a_revoir` |
| `trouee` | Journées trouées (≥ 2 créneaux vides entre deux cours d'un groupe) | `a_revoir` |

Filtres (se cumulent) : `semaine` (les points sans semaine — non placées,
règles — restent inclus, comme à l'écran), `parcours`, `enseignant` (code),
`gravite`, `nature`. Tri par urgence : sans semaine, semaine en cours,
semaines à venir dans l'ordre, puis semaines passées (la plus récente
d'abord).

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/a-traiter?parcours=BUT1&gravite=a_corriger"
```

```json
{
  "total": 3, "a_corriger": 3, "a_revoir": 0, "doublons_inclus": true,
  "natures": [
    {"id": "non-placee", "titre": "Séances non placées", "gravite": "a_corriger",
     "aide": "Des heures prévues sans aucun créneau. …", "nombre": 2},
    {"id": "sans-salle", "titre": "Séances sans salle", "gravite": "a_corriger", "aide": "…", "nombre": 1}
  ],
  "points": [
    {"nature": "non-placee", "gravite": "a_corriger", "cle": "np|WR106|CM|Promo BUT1|MARINE RIGUET",
     "titre": "WR106 — Expression, communication et rhétorique", "detail": "CM · Promo BUT1 · MARINE RIGUET",
     "semaine": null, "numero_semaine": null, "date": null, "jour": null, "jour_nom": null,
     "creneau": null, "debut": null, "parcours": ["BUT1"], "enseignants": ["MRI"], "nombre": 2,
     "seances": []},
    {"nature": "sans-salle", "gravite": "a_corriger", "cle": "ss|WR118-S1-CM-3",
     "titre": "WR118 — Gestion de projet", "detail": "CM · Promo BUT1",
     "semaine": 5, "numero_semaine": 7, "date": "2026-10-06", "jour": 1, "jour_nom": "mardi",
     "creneau": 0, "debut": "08:00", "parcours": ["BUT1"], "enseignants": ["KBR"], "nombre": 1,
     "seance_id": "WR118-S1-CM-3", "seances": []}
  ]
}
```

- `total`, `a_corriger`, `a_revoir` et `natures[].nombre` comptent des
  **occurrences** (un point « ×5 » compte 5), après filtres.
- `cle` : identifiant stable d'un point d'une révision à l'autre — pour
  savoir ce qui est apparu ou a disparu.
- Champs selon la nature : `seance_id` (sans salle), `seances` et
  `type_doublon` (doublon), `groupe` (journée trouée), `regle` (règle),
  `motif` (contrainte, compromis SAE).
- Le badge « nouveau » de l'écran (doublon apparu depuis le contrôle
  hebdomadaire) n'est pas repris : il ne dépend pas de l'état du planning.

### `GET /api/v1/controles/doublons`

Droits : rôle **`edit`** ou **`admin`**. Filtre `semaine`.

Une salle ou un enseignant mobilisé par deux séances sur un même créneau.
H.007 / H.008 / H.007-008 et H.201 / H.203 comptent comme une seule salle ;
une séance de 3 h compte sur chacun de ses créneaux.

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/controles/doublons?semaine=5"
```

```json
{"total": 1, "doublons": [{
  "semaine": 5, "numero_semaine": 7, "date": "2026-10-06", "jour": 1, "jour_nom": "mardi",
  "creneau": 3, "debut": "14:00", "fin": "15:30", "type": "salle", "ressource": "H.201 / H.203",
  "seances": [
    {"seance_id": "WR101-S1-TD-3-but1-td-ab", "cours_code": "WR101", "groupes": ["but1-td-ab"],
     "salle": "H.201", "enseignants": ["TPA"]},
    {"seance_id": "WR205-S1-TD-2-but1-td-cd", "cours_code": "WR205", "groupes": ["but1-td-cd"],
     "salle": "H.203", "enseignants": ["MRI"]}
  ]}]}
```

`ressource` : nom de l'enseignant (`type: "enseignant"`) ou salle(s).

### `GET /api/v1/manques`

Droits : compte actif (tout rôle). Pas de filtre.

Tout ce que l'appli signale comme **manquant** dans les données de
référence — la même liste que la section « Données à compléter » de l'écran
« À traiter » et que les fiches enseignant et salle :

| `famille` | `champ` | Manque | `gravite` | `role_requis` |
|---|---|---|---|---|
| `enseignant` | `email` | adresse mail | `bloque_envoi_liens` | `edit` |
| `enseignant` | `nom` | nom complet (seul le code est connu) | `cosmetique` | `edit` |
| `enseignant` | `code_celcat` | correspondance Celcat (enseignant qui a des séances placées) | `bloque_celcat` | `admin` |
| `salle` | `code_celcat` | correspondance Celcat | `bloque_celcat` | `admin` |
| `salle` | `type` | type d'une salle ajoutée à la main (posé d'office à « standard ») | `cosmetique` | `edit` |
| `cours` | `intitule` | intitulé (vide ou égal au code) | `cosmetique` | `edit` |
| `cours` | `code_celcat` | code Celcat de la matière, ou son identifiant interne | `bloque_celcat` | `null` |
| `groupe` | `id_celcat` | identifiant interne Celcat du groupe | `bloque_celcat` | `null` |
| `seance` | `salle` | séance placée sans salle (« salle à définir ») | `bloque_celcat` | `edit` |

- `role_requis: null` : ne se complète pas depuis l'appli — identifiant
  interne relevé dans Celcat, à ajouter au fichier de configuration indiqué
  par `ou_completer` (déploiement).
- `ecran` : où compléter dans l'appli (champs du fragment d'URL, ex.
  `{"vue": "prof", "prof": "KBR"}`).
- **Aucune valeur n'y figure** — ni adresse, ni code Celcat : seulement ce
  qui manque, et où. Trié du plus grave au moins grave.

```bash
curl --compressed -H "Authorization: Bearer $CLE" "https://cal-iut-mmi.srko.fr/api/v1/manques"
```

```json
{"revision": 1790000000000, "modifie_le": "2026-09-29T10:12:03+00:00", "total": 2,
 "par_gravite": {"bloque_celcat": 1, "bloque_envoi_liens": 1}, "par_famille": {"enseignant": 2},
 "manques": [
  {"id": "enseignant:JHU:code_celcat", "famille": "enseignant", "cle": "JHU", "libelle": "Jules Huet",
   "champ": "code_celcat", "champ_libelle": "Correspondance Celcat", "gravite": "bloque_celcat",
   "usage": "36 séances placées", "nb_seances": 36, "role_requis": "admin",
   "ou_completer": "Écran Celcat, ou ici pour un administrateur.", "ecran": {"vue": "celcat"}},
  {"id": "enseignant:MNI:email", "famille": "enseignant", "cle": "MNI", "libelle": "Marc Nino",
   "champ": "email", "champ_libelle": "Adresse mail", "gravite": "bloque_envoi_liens",
   "usage": "4 séances placées", "nb_seances": 4, "role_requis": "edit",
   "ou_completer": "Annuaire des enseignants, fiche de l'enseignant ou « À traiter ».",
   "ecran": {"vue": "prof", "prof": "MNI"}}]}
```

Compléter une donnée n'est **pas** dans v1 (lecture seule) : c'est l'appli
qui écrit, par ses routes internes `PUT /reference/…` (cf. §7).

### `GET /api/v1/contraintes` · `GET /api/v1/enseignants/{code}/contraintes`

L'écran **Contraintes** : chaque règle institutionnelle avec son verdict
(échecs d'abord), puis, par enseignant, sa contrainte déclarée et le verdict
recalculé sur le planning (écarts d'abord), enfin les absences ponctuelles
et salles indisponibles saisies dans l'appli (`exceptions`).

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/enseignants/MRI/contraintes
```

```json
{
  "code": "MRI", "nom": "MARINE RIGUET", "contrainte_declaree": true,
  "indisponibilites": "mercredi toute la journée", "disponibilites": "", "remarques": "",
  "creneaux_interdits": [{"jour": 2, "creneau": 0}, {"jour": 2, "creneau": 1}, "…"],
  "dates_interdites": [], "nb_seances": 96,
  "verdict": "compromis_sae", "nb_ecarts": 0, "nb_compromis_sae": 1,
  "ecarts": [{"nature": "compromis_sae", "motif": "encadrement_sae", "cours_code": "WR106",
              "semaine": 6, "numero_semaine": 8, "date": "2026-10-13", "jour": 1, "creneau": null}],
  "exceptions": []
}
```

`/api/v1/contraintes` renvoie `{"regles": […], "enseignants": […],
"exceptions": […]}` :

```json
{
  "regles": [{"id": "weekly_cap", "libelle": "Plafond horaire hebdomadaire (33h FI / ~35h FC)",
              "statut": "echec", "detail": "11 cohorte(s) au-dessus du plafond : …"}],
  "enseignants": ["… même forme que ci-dessus …"],
  "exceptions": [{"id": 3, "type": "absence_enseignant", "date": "2026-10-14", "enseignant": "KBR",
                  "salle_id": null, "creneaux": null, "motif": "Jury"}]
}
```

- `verdict` (même règle que l'écran) : `ecarts` dès qu'une indisponibilité
  déclarée n'est pas respectée, `compromis_sae` s'il n'y a que des compromis
  SAE, `respectee`, ou `aucune` (pas de contrainte déclarée ni d'écart).
- `ecarts[].nature` : `indisponibilite` (vraie violation) ou `compromis_sae`
  (l'enseignant encadre une SAE le même jour, accepté). `motif` :
  `creneau_interdit`, `hors_liste_blanche`, `date_declaree`,
  `encadrement_sae`, `hors_dates_de_venue`. `creneau` n'est renseigné que
  pour un créneau récurrent interdit.
- Textes déclarés (`indisponibilites`, `disponibilites`, `remarques`) : tels
  que l'enseignant les a saisis.
- `exceptions[].creneaux: null` = journée entière ; `type` :
  `absence_enseignant` ou `salle_indisponible`.

### `GET /api/v1/charges`

Les chiffres des **annuaires** (Vue Enseignant, TD / TP, Cours, Salle), par
semaine et au semestre. `semaine=` remplit `heures_semaine` /
`creneaux_occupes` ; sans lui, ces champs valent `null`, mais
`heures_par_semaine` (ou `creneaux_par_semaine`) donne **toutes** les
semaines d'un coup : inutile d'appeler une fois par semaine.

```bash
curl --compressed -H "Authorization: Bearer $CLE" "https://cal-iut-mmi.srko.fr/api/v1/charges?semaine=5"
```

```json
{
  "semaine": 5, "heures_par_creneau": 1.5, "creneaux_par_semaine": 30,
  "enseignants": [{"code": "KBR", "nom": "KYLLIAN BRESSON", "heures_semaine": 27.0, "heures_semestre": 247.5,
                   "heures_par_semaine": {"4": 19.5, "5": 27.0, "6": 22.5, "…": "…"},
                   "nb_seances": 153, "nb_matieres": 6, "nb_non_placees": 2,
                   "contrainte": "compromis_sae", "nb_ecarts": 0}],
  "groupes": [{"id": "but1-tp-a", "libelle": "TP A", "parcours": "BUT1", "type": "tp", "fc": false,
               "heures_semaine": 31.5, "heures_semestre": 322.5, "heures_par_semaine": {"5": 31.5, "…": "…"}}],
  "cours": [{"code": "WR101", "nom": "Anglais", "parcours": "BUT1", "semestre": "S1", "prevues": 62,
             "placees": 61, "non_placees": 1, "heures_semaine": 6.0, "heures_placees": 91.5,
             "heures_par_semaine": {"5": 6.0, "…": "…"}, "enseignants": ["TPA"]}],
  "salles": [{"id": "h018", "libelle": "H.018 (Amphi MMI)", "capacite": 150, "type": "amphi",
              "placement_auto": true, "creneaux_occupes": 11, "taux": 0.367,
              "creneaux_par_semaine": {"4": 9, "5": 11, "…": "…"}, "seances_semestre": 70}],
  "parcours": [{"id": "BUT1", "nb_seances": 1009, "heures_semaine": 160.5, "heures_semestre": 1599.0,
                "heures_par_semaine": {"5": 160.5, "…": "…"}}]
}
```

Comment c'est compté (mêmes règles que l'écran) :

- **enseignant** : heures **additionnées** de ses séances (un bloc de 3 h =
  3 h ; deux séances simultanées = 3 h). `contrainte` suit l'annuaire :
  `aucune` sans contrainte déclarée, même avec un compromis SAE — c'est
  `/contraintes` qui donne le verdict complet ;
- **groupe** : heures de ce que suit un étudiant du groupe (sa cohorte : CM de
  promo, TD parent, TP), **chaque créneau compté une seule fois** — deux TP
  jumelés en parallèle durent 1 h 30, pas 3 h ;
- **cours** : `prevues` (CM + TD + TP + évaluations de la maquette) face à
  `placees` et `non_placees` ; une ligne par parcours ;
- **salle** : créneaux occupés sur 30 par semaine (`taux` = occupés / 30),
  en comptant les salles fusionnées (occuper H.007-008 occupe H.007 et H.008,
  occuper H.007 occupe H.007-008) et les réservations de tiers ;
- **parcours** : volume **enseigné** (somme des séances dont un groupe
  appartient au parcours). Le temps passé par un étudiant se lit sur les
  groupes.

Les clés de `heures_par_semaine` sont des index solveur (en texte, JSON
oblige) ; seules les semaines non vides y figurent.

### `GET /api/v1/modifications`

Séances déplacées à la main depuis la dernière génération automatique
(panneau « Modifications ») : où la génération les avait mises, où elles
sont. Filtre `semaine` : semaine de départ **ou** d'arrivée.

```bash
curl --compressed -H "Authorization: Bearer $CLE" "https://cal-iut-mmi.srko.fr/api/v1/modifications?semaine=5"
```

```json
{
  "total_suivies": 2384, "nb_modifiees": 97,
  "modifications": [{
    "seance_id": "WR106-S1-TP-1-but1-tp-a", "cours_code": "WR106",
    "cours_nom": "Expression, communication et rhétorique",
    "generation": {"semaine": 5, "numero_semaine": 7, "date": "2026-10-05", "jour": 0,
                   "jour_nom": "lundi", "creneau": 0, "debut": "08:00"},
    "actuelle": {"semaine": 5, "numero_semaine": 7, "date": "2026-10-07", "jour": 2,
                 "jour_nom": "mercredi", "creneau": 0, "debut": "08:00"},
    "verrouillee": true
  }]
}
```

`nb_modifiees` compte toutes les séances déplacées (avant filtre). Les
séances créées depuis l'interface n'y sont pas (elles n'ont pas de position
« générée ») : cf. `personnalisee` dans `/api/v1/seances`.

### `GET /api/v1/taches`

Cartes du tableau de suivi de l'équipe (onglet Tâches). Filtres : `colonne`
(`a_faire`, `en_cours`, `fait`), `categorie` (`edt`, `plateforme`),
`enseignant` (code).

```bash
curl --compressed -H "Authorization: Bearer $CLE" "https://cal-iut-mmi.srko.fr/api/v1/taches?colonne=en_cours"
```

```json
[{"id": 12, "titre": "Déplacer le TP de WR106 du groupe A", "description": "Salle Mac indisponible le 14/10.",
  "colonne": "en_cours", "ordre": 2.0, "enseignant": "MRI", "concerne": "Jules", "categorie": "edt",
  "priorite": "urgente", "date_debut": "2026-10-12", "date_fin": "2026-10-14",
  "cree_le": "2026-09-28T08:12:03", "maj_le": "2026-09-29T09:40:11", "fait_le": null}]
```

`concerne` : à qui la carte est attribuée (prénom libre). L'**auteur** d'une
carte n'est volontairement pas exposé : c'est l'adresse mail de son compte.

### `GET /api/v1/celcat/etat`

Droits : rôle **`admin`** (comme l'onglet Celcat).

État de la saisie automatique dans Celcat et de sa file d'attente —
compteurs et dates seulement. Semaines dans la numérotation de l'onglet
Celcat. ETag calculé sur le contenu (cf. §1).

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/celcat/etat
```

```json
{
  "saisie_active": true, "worker_actif": true, "worker_ok": true,
  "semaines_validees": [1, 2, 3, 4, 5, 6], "semaines_lancees": [5, 6], "semaines_passees": [1, 2, 3, 4],
  "semaines_completes": [1, 2, 3, 4, 5], "semaines_creation_autorisee": [],
  "valide_le": "2026-09-28T17:02:11+00:00", "dernier_job_lance_le": "2026-09-29T02:00:04+00:00",
  "derniere_ecriture_celcat": "2026-09-29T09:31:40+00:00",
  "compteurs": {"creees": 812, "modifiees": 140, "supprimees": 12, "bloquees": 3},
  "file": {"en_attente": 2, "par_action": {"modifier": 2}, "dernier_passage_le": "2026-09-29T10:05:00+00:00",
           "age_secondes": 42.0, "reussis": 5, "echecs": 0, "ignores": 0, "differes": 2,
           "resume": "5 réussis, 2 en attente d'une semaine ouverte."}
}
```

- `worker_actif` : le worker n'est pas en pause volontaire ; `worker_ok` : il
  a donné signe de vie récemment (sinon, il est arrêté).
- `derniere_ecriture_celcat` : dernière écriture **réellement faite** dans
  Celcat (création, modification ou suppression).
- `file.differes` : jobs qui attendent qu'une semaine soit ouverte dans
  Celcat — à distinguer de `echecs`.

### `GET /api/v1/export`

Tout en un seul appel : `revision`, `modifie_le`, `jours`, `creneaux`,
`semaines`, `parcours`, `groupes`, `enseignants`, `salles`, `cours`,
`seances`, `seances_non_placees`, `contraintes` (règles, enseignants,
absences), `calendrier`, `modifications`, `taches`, et **`sae`** :

```json
"sae": {
  "periodes": ["… comme /api/v1/sae/periodes (tous parcours) …"],
  "journees": ["… comme /api/v1/sae/journees …"],
  "cours":    ["… comme la liste `sae` de /api/v1/sae …"]
}
```

Mêmes formats qu'aux routes dédiées. ≈ 2,2 Mo, ≈ 95 Ko compressé. Une
modification des fenêtres SAE (`contraintes/09_dates_sae.json`,
`sae_corrections.yaml`, `sae_teacher_phases.yaml`) fait avancer la révision,
donc change l'ETag de l'export.

N'y sont **pas** : les vues **calculées** à partir de ces données
(`/a-traiter`, `/charges`, `/controles/doublons`) — elles dépendent du rôle
ou d'un paramètre, et se relisent en 304 de la même façon — ni l'état Celcat
(admin, hors révision).

```bash
# Synchronisation complète, seulement si quelque chose a changé
curl --compressed -H "Authorization: Bearer $CLE" \
  -H "If-None-Match: $ETAG_PRECEDENT" -D entetes.txt -o export.json \
  https://cal-iut-mmi.srko.fr/api/v1/export
```

---

## 4. Documentation interactive

| Adresse | Contenu |
|---|---|
| `/api/v1/docs` | Swagger UI : chaque endpoint, ses paramètres, ses schémas, un exemple de réponse, et « Try it out » |
| `/api/v1/openapi.json` | Schéma OpenAPI 3.1 des seules routes `/api/v1` (pour générer un client) |

Réservées, comme les données, à un **compte actif** : ouvrez `/api/v1/docs`
dans un navigateur connecté à l'appli (le cookie suffit pour « Try it out »),
ou lisez le schéma avec une clé API :

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/openapi.json -o openapi.json
```

Choix de sécurité (audit du 29/09/2026, P2-5) : le schéma de **toute** l'appli
(`/openapi.json`, `/docs`, `/redoc`) était public — la carte complète des
routes internes, sans compte. Il est désactivé ; seul le schéma v1 est
servi, derrière l'authentification. Un lien public `?t=` n'y a pas accès.

La page Swagger UI charge ses fichiers JavaScript et CSS depuis le CDN
jsDelivr (comportement par défaut de FastAPI) : il faut un accès internet
côté navigateur. Le schéma `openapi.json`, lui, ne dépend de rien d'externe.

---

## 5. Hors API (volontairement)

| Donnée de l'appli | Pourquoi elle n'est pas dans v1 |
|---|---|
| Comptes, rôles, adresses de comptes, clés API | Données d'administration et personnelles (onglet Comptes, admin) |
| Auteur d'une tâche (`cree_par`) | C'est l'adresse mail du compte |
| Journal Celcat détaillé, correspondances, relevé Celcat, plan de saisie | Journaux bruts et données de travail de l'onglet Celcat ; seul l'état synthétique est exposé |
| Sauvegardes | Fichiers d'état complets (admin), pas des données de lecture |
| Notifications, mails aux enseignants (aperçus, liens, suivi d'ouverture) | Administration, et contiennent des adresses |
| Historique du contrôle hebdomadaire des doublons (badge « nouveau ») | Dépend d'un fichier de contrôle, pas de l'état du planning ; les doublons actuels sont dans `/controles/doublons` |
| Poids du solveur, analyse des corrections (`/weights`, `/feedback/*`), statut des calculs (`/solve/status`, `/regen/status`, lissage) | Réglage interne de la génération, sans intérêt pour un lecteur |
| Créneaux libres pour placer une séance (`/placements/{id}/creneaux-libres`) | Outil d'édition, lié au placement (non en lecture seule) |

---

## 6. Exemple : client qui reste à jour sans surcharger le serveur

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
        a_traiter = lire("/api/v1/a-traiter")  # si l'outil en a besoin
    time.sleep(60)
```

---

## 7. Côté serveur (pour qui maintient le projet)

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
  (`_filter_timetable`, `_to_placement`, `_date_iso`, `seances_manquantes`,
  `doublons.doublons`, `_calculer_diff`, `list_taches`, `_celcat_etat_public`,
  `celcat_file`…).
- Vues calculées côté écran : `src/cal_iut/api/v1_vues.py` porte
  `frontend/src/utils/todo.ts` (« À traiter ») et `annuaires.ts` /
  `sallesLibres.ts` (charges). Une règle changée d'un côté doit l'être de
  l'autre ; `tests/test_api_v1_complete_2026_09_29.py` rejoue les fixtures
  des tests frontend et vérifie les mêmes nombres.
- Droits : `dependencies=[Depends(accounts.require_role(...))]` sur la route,
  comme dans `main.py`. Une réponse qui dépend du rôle passe le rôle dans la
  clé de cache (`_repondre(..., en_plus=...)`).
- Débit : dépendance `_limiter_v1` sur tout le routeur (`LIMITE_V1`).
- Une nouvelle route de LECTURE qui dépend de l'état doit passer par
  `cache_http.repondre` (ou `v1._repondre`) ; une route dont les données
  changent HORS révision (Celcat) calcule son ETag sur le contenu. Une
  nouvelle route d'ÉCRITURE qui n'est pas un POST/PATCH/PUT/DELETE HTTP
  classique (thread, appel direct) doit appeler `revision.incrementer(...)`
  elle-même.
- Toute nouvelle route v1 est automatiquement couverte par le test du lien
  public (`tests/test_lien_perso_perimetre_2026_09_29.py`, qui parcourt
  toutes les routes effectives) et par le contrôle de couverture
  d'authentification au démarrage.

### Compléter une donnée de référence (routes internes, hors v1)

`api/reference.py` — une fonction par famille, une seule liste des manques.
Écritures dans le volume `data/state/` (jamais `data/config/`, figé dans
l'image), sous le verrou d'écriture, journalisées (qui, quand, valeur
d'avant, `data/state/references.json`) ; la révision avance.

| Route | Corps | Droits | Persistance |
|---|---|---|---|
| `GET /reference/manques` | — | compte actif | — |
| `PUT /reference/enseignants/{code}/contact` | `{"email"}` — format validé, minuscules, refus d'une adresse déjà attribuée ou déjà dans `teacher_contacts.yaml` | `edit` | `references.json` |
| `PUT /reference/enseignants/{code}` | `{"nom"}` (`edit`), `{"code_celcat"}` (`admin`) | voir corps | `references.json`, `celcat_mappings.json` |
| `PUT /reference/salles/{id}` | `{"capacite", "type"}` (salle ajoutée à la main, `edit`), `{"code_celcat"}` (`admin`) | voir corps | `custom_rooms.json`, `celcat_mappings.json` |
| `PUT /reference/cours/{code}` | `{"intitule"}` | `edit` | `references.json` |

La configuration garde le dernier mot : une saisie ne sert que tant que le
fichier (ou la maquette, la feuille des contraintes) ne fournit pas la
valeur ; une donnée déjà fournie par eux est refusée (409) et se corrige
dans le fichier. Seules les correspondances Celcat, comme sur l'écran
Celcat, passent par-dessus `celcat.yaml`.
