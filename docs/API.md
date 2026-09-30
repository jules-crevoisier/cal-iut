# API v1 — lire l'emploi du temps depuis une autre application

Ce document explique comment lire l'emploi du temps MMI depuis un script ou une application.
Il est pour les développeurs d'applications tierces (écran d'affichage, appli mobile, tableau de bord).
Adresse du serveur : `https://cal-iut-mmi.srko.fr`.

**Sommaire**

1. [En bref](#1-en-bref)
2. [Démarrer en 3 étapes](#2-démarrer-en-3-étapes)
3. [Rester à jour sans surcharger le serveur](#3-rester-à-jour-sans-surcharger-le-serveur)
4. [Quel endpoint pour quel besoin ?](#4-quel-endpoint-pour-quel-besoin-)
5. [Référence des endpoints](#5-référence-des-endpoints)
6. [Les SAE, simplement](#6-les-sae-simplement)
7. [Que veut dire cette erreur ?](#7-que-veut-dire-cette-erreur-)
8. [Limites de débit et bonnes pratiques](#8-limites-de-débit-et-bonnes-pratiques)
9. [Pour les techniciens](#9-pour-les-techniciens)

---

## 1. En bref

- L'API v1 est **en lecture seule**. Elle donne tout ce que montrent les écrans de l'appli.
- Elle répond en **JSON** (texte structuré, lisible par tous les langages).
- Chaque appel porte une **clé API** (`caliut_…`), liée à un compte de l'appli.
- Un appel minuscule, `GET /api/v1/version`, dit si quelque chose a changé. Tout le reste se relit seulement alors.
- Pour un simple agenda, pas besoin de l'API : les liens `.ics` suffisent ([ICS.md](ICS.md)).
  Pour **modifier** le planning : l'appli web, ou le serveur MCP ([MCP.md](MCP.md)).

---

## 2. Démarrer en 3 étapes

### Étape 1 — Obtenir un compte « Accès API »

1. Ouvrir `https://cal-iut-mmi.srko.fr` et cliquer sur **Créer un compte**.
2. Confirmer son adresse mail (lien reçu par mail).
3. Demander à un administrateur de l'activer avec le rôle **Accès API** (cf. [ADMIN.md](ADMIN.md)).

Ce compte ne voit **aucune donnée** dans l'appli. Sa seule page, **Accès API**, sert à gérer ses clés.

> **À savoir :** un compte ordinaire (lecture seule, édition, admin) peut aussi créer des clés.
> Menu du compte (avatar, en bas de la barre latérale) → **Clé API**.

### Étape 2 — Générer une clé

1. Se connecter. Ouvrir la page **Accès API** (ou **Clé API** pour un compte ordinaire).
2. Donner un nom à la clé (facultatif : « Écran du hall », « Script agenda »…).
3. Cliquer sur **Générer une clé**.
4. Cliquer sur **Copier la clé** tout de suite. Elle ne sera **plus jamais affichée**.

La clé commence par `caliut_`. La page propose aussi l'en-tête prêt à coller et deux exemples `curl`.

### Étape 3 — Premier appel

```bash
export CLE=caliut_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
curl -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/version
```

Réponse attendue :

```json
{"revision": 1790676457688, "modifie_le": "2026-09-29T10:07:37.688427+00:00"}
```

La clé s'envoie dans l'en-tête `Authorization: Bearer <clé>` de **chaque** requête.

### Règles des clés

| Règle | Détail |
|---|---|
| Droits | La clé a les droits de son compte. Une clé « Accès API » lit v1 comme un compte **lecture seule**. |
| Nombre | 5 clés actives au plus par compte. Prévoir une clé par usage. |
| Révocation | Bouton **Révoquer** sur la même page. Effet immédiat (erreur 401 ensuite). |
| Gestion | Seulement depuis l'appli connectée. Une clé ne peut ni lister, ni créer, ni révoquer de clé (403). |
| Rôle changé | Le nouveau rôle s'applique aux clés existantes dès la requête suivante. |
| Secret | Jamais dans une page web publique, un dépôt de code, un chat ou une capture. |

---

## 3. Rester à jour sans surcharger le serveur

Le serveur tient un **numéro de révision**. Il augmente à chaque changement visible. Il ne recule jamais.

La bonne méthode, en 3 temps :

1. **Sonder** `GET /api/v1/version` toutes les 1 à 5 minutes, avec l'en-tête `If-None-Match`.
2. Réponse **304** (« rien n'a changé », sans contenu) : ne rien faire.
3. Réponse **200** (la révision a bougé) : relire `GET /api/v1/export` (tout en un appel).

`If-None-Match` renvoie l'**ETag** reçu la fois précédente. L'ETag est une étiquette de version posée sur chaque réponse.

```bash
curl -si -H "Authorization: Bearer $CLE" -H 'If-None-Match: W/"5f74e80c369acde6fe61"' \
  https://cal-iut-mmi.srko.fr/api/v1/version
# HTTP/1.1 304 Not Modified   ← rien n'a changé, pas de corps
```

Exemple complet en Python (bibliothèque `httpx`) :

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
    if r.status_code == 429:             # trop de requêtes : attendre
        time.sleep(int(r.headers.get("Retry-After", "60")))
        return None
    r.raise_for_status()
    etags[chemin] = r.headers["ETag"]
    return r.json()

while True:
    if lire("/api/v1/version") is not None:   # la révision a bougé
        donnees = lire("/api/v1/export") or donnees
        a_traiter = lire("/api/v1/a-traiter")  # seulement si l'outil en a besoin
    time.sleep(60)
```

C'est le schéma d'une appli comme « MMI Troyes EDT » : elle sonde `/version`, puis lit `/export`.

---

## 4. Quel endpoint pour quel besoin ?

| Besoin | Appels |
|---|---|
| Tout copier et rester à jour | `/api/v1/version` (avec `If-None-Match`), puis `/api/v1/export` s'il a changé. |
| Planning d'un enseignant cette semaine | `/api/v1/semaines` (repérer `"statut": "en_cours"`), puis `/api/v1/enseignants/KBR/seances?semaine=5`. |
| Planning d'un groupe d'étudiants | `/api/v1/groupes/but1-tp-a/seances?du=…&au=…` (inclut le CM de la promo et les TD du TD parent). |
| Écran d'affichage dans un couloir | `/api/v1/seances?du=2026-10-05&au=2026-10-05` et `/api/v1/salles/libres?semaine=5&jour=0&creneau=2`. |
| Trouver une salle libre | `/api/v1/salles/libres?semaine=…&jour=…&creneau=…&capacite_min=30` |
| Bandeaux « semaine de projet SAE » | `/api/v1/sae/periodes?parcours=BUT1` (ou `sae.periodes` dans l'export). |
| Ce qui se passe un jour de SAE | `/api/v1/sae/journees?du=…&au=…` |
| Suivre une SAE | `/api/v1/sae/WS501D`, ou `/api/v1/sae` (anomalies en tête). |
| Corrections à faire | `/api/v1/a-traiter`, `/api/v1/seances/non-placees`, `/api/v1/controles/doublons`. |
| Données de référence manquantes | `/api/v1/manques` |
| Contraintes d'un enseignant | `/api/v1/enseignants/MRI/contraintes` |
| Tableau de bord des charges | `/api/v1/charges` (toutes les semaines d'un coup dans `heures_par_semaine`). |
| Ce qui a été déplacé à la main | `/api/v1/modifications` |
| Tâches de l'équipe | `/api/v1/taches?colonne=a_faire` |
| Superviser Celcat (admin) | `/api/v1/celcat/etat` |

---

## 5. Référence des endpoints

Tous les endpoints sont en `GET`. Dans les exemples, `$CLE` est votre clé.
Les exemples de réponse sont **raccourcis** (`…`). Les schémas complets sont dans la
documentation interactive : [`/api/v1/docs`](#documentation-interactive).

### Tableau récapitulatif

« Compte actif » = toute clé ou session d'un compte activé, quel que soit son rôle (Accès API compris).

| Endpoint | Contenu | Droits | `semaine=` |
|---|---|---|---|
| `/api/v1/version` | Numéro de révision, à sonder | compte actif **ou lien public** `?t=` | — |
| `/api/v1/export` | Toutes les données en un appel | compte actif | — |
| `/api/v1/semaines` | Semaines de l'année, statut passée / en cours / future | compte actif | — |
| `/api/v1/creneaux` | 5 jours × 6 créneaux horaires | compte actif | — |
| `/api/v1/enseignants[/{code}]` | Enseignants, mail de contact, séances, cours | compte actif | — |
| `/api/v1/groupes[/{id}]` | Groupes, groupes liés, cohorte | compte actif | — |
| `/api/v1/salles[/{id}]` | Catalogue des salles | compte actif | — |
| `/api/v1/salles/libres` | Salles libres à un créneau | compte actif | obligatoire |
| `/api/v1/cours[/{code}]` | Maquette ; la fiche ajoute la progression | compte actif | — |
| `/api/v1/parcours[/{id}]` | Parcours, semestres, groupes | compte actif | — |
| `/api/v1/seances` | Séances placées, filtrables, paginées | compte actif | oui |
| `/api/v1/{enseignants,groupes,salles,cours,parcours}/{id}/seances` | Séances d'une ressource | compte actif | oui |
| `/api/v1/seances/non-placees` | Séances restant à placer | compte actif | oui ¹ |
| `/api/v1/calendrier` | Fériés, vacances, évènements, jours SAE, réservations | compte actif | oui |
| `/api/v1/sae/periodes` | Semaines de projet SAE | compte actif | oui (+ `du`/`au`) |
| `/api/v1/sae/journees` | Journées SAE, jour par jour | compte actif | oui (+ `du`/`au`) |
| `/api/v1/sae[/{code}]` | Cours de SAE : placés, non placés, anomalies | compte actif | oui |
| `/api/v1/a-traiter` | Écran « À traiter » | compte actif ² | oui |
| `/api/v1/controles/doublons` | Salle ou enseignant pris deux fois | rôle **édition** ou **admin** | oui |
| `/api/v1/manques` | Données de référence à compléter | compte actif | — |
| `/api/v1/contraintes` | Règles globales et contraintes des enseignants | compte actif | — |
| `/api/v1/enseignants/{code}/contraintes` | Contraintes d'un enseignant | compte actif | — |
| `/api/v1/charges` | Heures et occupation des salles | compte actif | oui ³ |
| `/api/v1/modifications` | Séances déplacées à la main | compte actif | oui |
| `/api/v1/taches` | Cartes du tableau Tâches | compte actif | — |
| `/api/v1/taches/{id}/images/{image_id}` | Image jointe à une tâche | compte actif | — |
| `/api/v1/celcat/etat` | Synchronisation Celcat | rôle **admin** | — |
| `/api/v1/docs`, `/api/v1/openapi.json` | Documentation interactive, schéma | compte actif | — |

¹ celles qui *peuvent* aller dans cette semaine. ² les doublons n'y figurent que pour un rôle édition ou admin.
³ en plus du détail de toutes les semaines, toujours présent.

Le paramètre `semaine=` attend l'**index de semaine** (0, 1, 2…), pas le « Semaine N » affiché.
Voir [Numéros de semaine](#numéros-de-semaine).

### Paramètres des listes de séances

Valables pour `/api/v1/seances` et les `…/{id}/seances`. Tous sont facultatifs et se cumulent.

| Paramètre | Effet |
|---|---|
| `semaine` | index de semaine (cf. `/api/v1/semaines`) |
| `du`, `au` | dates `AAAA-MM-JJ`, incluses |
| `limite`, `decalage` | pagination (`limite` de 1 à 10 000 ; sans `limite`, tout) |
| `enseignant` | code enseignant (`KBR`) — `/api/v1/seances` seulement |
| `groupe` | id de groupe ; inclut la promo et le TD parent — idem |
| `salle` | id de salle (`h018`) — idem |
| `cours` | code du cours (`WR101`) — idem |
| `parcours` | parcours (`BUT2-DEV-FI`) — idem |
| `sae` | `true` : seulement les cours de SAE ; `false` : sans eux — idem |

---

### État

#### `GET /api/v1/version`

**But :** savoir si quelque chose a changé. Quelques dizaines d'octets.
**Droits :** compte actif, ou lien public `?t=` (celui des enseignants et des groupes).

```json
{"revision": 1790676457688, "modifie_le": "2026-09-29T10:07:37.688427+00:00"}
```

#### `GET /api/v1/export`

**But :** tout copier en un appel. Environ 2 Mo, moins de 100 Ko compressé.
**Contenu :** `revision`, `modifie_le`, `jours`, `creneaux`, `semaines`, `parcours`, `groupes`, `enseignants`,
`salles`, `cours`, `seances`, `seances_non_placees`, `contraintes`, `calendrier`, `modifications`, `taches`, `sae`.
Chaque partie a la même forme que l'endpoint dédié.

```json
"sae": {
  "periodes": ["… comme /api/v1/sae/periodes (tous parcours) …"],
  "journees": ["… comme /api/v1/sae/journees …"],
  "cours":    ["… comme la liste `sae` de /api/v1/sae …"]
}
```

**Absents de l'export :** `/a-traiter`, `/charges`, `/controles/doublons`, `/manques` et `/celcat/etat`.
Ce sont des vues calculées, qui dépendent du rôle ou d'un paramètre. Elles se relisent en 304 de la même façon.

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  -H "If-None-Match: $ETAG_PRECEDENT" -D entetes.txt -o export.json \
  https://cal-iut-mmi.srko.fr/api/v1/export
```

### Référentiel

#### `GET /api/v1/semaines`

**But :** toutes les semaines de l'année, y compris les semaines de vacances (`semaine: null`).

```json
[
  {"semaine": 0, "numero": 2, "semaine_iso": 36, "lundi": "2026-08-31",
   "libelle": "Semaine 2 (31 août–4 sept. 2026)", "bloquee": false, "statut": "passee"},
  {"semaine": 5, "numero": 7, "semaine_iso": 41, "lundi": "2026-10-05",
   "libelle": "Semaine 7 (5–9 oct. 2026)", "bloquee": false, "statut": "future"}
]
```

`statut` : `passee`, `en_cours` ou `future`. Seules les semaines futures sont modifiables dans l'appli.

#### `GET /api/v1/creneaux`

**But :** les jours (0 = lundi … 4 = vendredi) et les 6 créneaux de 1 h 30.

```json
{"jours": [{"index": 0, "nom": "lundi"}, "…"],
 "creneaux": [{"index": 0, "debut": "08:00", "fin": "09:30", "libelle": "08:00–09:30"}, "…"]}
```

#### `GET /api/v1/enseignants` · `/enseignants/{code}` · `/enseignants/{code}/seances`

```json
{"code": "KBR", "nom": "KYLLIAN BRESSON", "email": "kyllian.bresson@univ-reims.fr",
 "nb_seances": 153, "cours": ["WR107", "WR110", "WR119"]}
```

- `email` : adresse de **contact** de l'enseignant, pas celle d'un compte.
- La liste comprend aussi les enseignants sans séance (`nb_seances: 0`), dont les intervenants ajoutés dans l'appli.
- `cours` n'apparaît que sur la fiche `/enseignants/{code}`.

#### `GET /api/v1/groupes` · `/groupes/{id}` · `/groupes/{id}/seances`

```json
{"id": "but1-td-ab", "libelle": "TD AB", "parcours": "BUT1", "annee": "BUT1", "type": "td",
 "groupes_lies": ["but1-tp-a", "but1-tp-b"],
 "cohorte": ["but1-promo", "but1-td-ab", "but1-tp-a", "but1-tp-b"]}
```

- `type` : `promo`, `td` ou `tp`.
- `cohorte` : tous les groupes dont les séances concernent ce groupe.
  Les séances d'un groupe incluent donc le CM de la promo et, pour un TP, les TD du TD parent.
  C'est exactement ce qu'un étudiant voit sur son planning.

#### `GET /api/v1/salles` · `/salles/{id}` · `/salles/{id}/seances`

```json
{"id": "h018", "libelle": "H.018 (Amphi MMI)", "capacite": 150, "type": "amphi",
 "equipements": ["videoprojecteur", "sonorisation"], "placement_auto": true,
 "fusionne": [], "nb_seances": 70}
```

- `fusionne` : pour une salle réunie (ex. `h007_h008`), les salles qu'elle recouvre.
- `placement_auto: false` : jamais choisie par la génération automatique, mais choisissable à la main.

#### `GET /api/v1/salles/libres?semaine=&jour=&creneau=`

**But :** les salles libres à un créneau précis, de la plus petite à la plus grande.
**Paramètres :** `semaine`, `jour` (0–4) et `creneau` (0–5) obligatoires ; `capacite_min` facultatif.

```json
{"semaine": 5, "jour": 1, "creneau": 2, "date": "2026-10-06",
 "libres": [{"id": "h101", "libelle": "H.101", "capacite": 32, "type": "standard", "…": "…"}],
 "occupees": [
   {"salle_id": "h018", "motif": "seance", "seance_id": "WR118-S1-CM-3", "cours_code": "WR118"},
   {"salle_id": "h018", "motif": "reservation", "detail": "Besoin de la Direction"},
   {"salle_id": "h008", "motif": "salle_liee", "detail": "h007"}]}
```

Une salle est occupée par :

- une séance (y compris un bloc de 3 h commencé au créneau d'avant) ;
- une réservation d'un tiers ;
- une salle **liée** occupée (`salle_liee`) : H.007 prise rend H.008 et H.007+H.008 indisponibles.

Une salle annoncée libre ici est une salle que le serveur acceptera.

#### `GET /api/v1/cours` · `/cours/{code}` · `/cours/{code}/seances`

**But :** la maquette. Une entrée par (code, semestre, parcours). La fiche ajoute la **progression** :
toutes les séances dans l'ordre pédagogique, placées ou non.

```json
{"code": "WR101", "nom": "Anglais",
 "declinaisons": [{"code": "WR101", "nom": "Anglais", "semestre": "S1", "parcours": "BUT1",
                   "nb_cm": 1, "nb_td": 12, "nb_tp": 48, "nb_evaluations": 1, "nb_placees": 61,
                   "enseignants": ["TPA"], "progression_definie": true, "sae": false,
                   "ordonnancement": [{"position": "after", "cible": "WR102"}]}],
 "progression": [
   {"seance_id": "WR101-S1-CM-1", "ordre": 1, "type": "CM", "groupes": ["but1-promo"],
    "duree_creneaux": 1, "placee": true, "semaine": 0, "date": "2026-09-01", "debut": "08:00", "…": "…"},
   {"seance_id": "WR101-S1-TD-12-but1-td-ab", "ordre": 12, "placee": false, "semaine": null, "…": "…"}]}
```

- `ordre` : rang dans la progression (`null` si la maquette n'en fixe pas).
- `ordonnancement` : ordre imposé avec d'autres cours (`before`, `same` ou `after` le cours `cible`).

#### `GET /api/v1/parcours` · `/parcours/{id}` · `/parcours/{id}/seances`

```json
{"id": "BUT1", "annee": 1, "semestres": ["S1", "S2"],
 "groupes": ["but1-promo", "but1-td-ab", "but1-td-cd", "but1-tp-a", "…"]}
```

### Séances

#### `GET /api/v1/seances`

**But :** les séances placées, triées par date puis heure. Filtres : cf. [tableau plus haut](#paramètres-des-listes-de-séances).

```bash
curl --compressed -H "Authorization: Bearer $CLE" \
  "https://cal-iut-mmi.srko.fr/api/v1/seances?groupe=but1-tp-a&du=2026-10-05&au=2026-10-09&limite=1"
```

```json
{"total": 21, "decalage": 0, "limite": 1,
 "seances": [{
   "id": "WR106-S1-TP-1-but1-tp-a", "cours_code": "WR106",
   "cours_nom": "Expression, communication et rhétorique", "type": "TP",
   "parcours": "BUT1", "semestre": "S1", "groupes": ["but1-tp-a"], "groupes_libelles": ["TP A"],
   "enseignants": ["MRI"], "enseignants_noms": ["…"], "salle_id": "h005", "salle_libelle": "H.005",
   "semaine": 5, "numero_semaine": 7, "date": "2026-10-05", "jour": 0, "jour_nom": "lundi",
   "creneau": 0, "duree_creneaux": 1, "debut": "08:00", "fin": "09:30", "horaire_libre": false,
   "evaluation": false, "verrouillee": false, "personnalisee": false, "evenement": false,
   "sae": false, "dans_journee_sae": null}]}
```

| Champ | Sens |
|---|---|
| `duree_creneaux` | `2` pour un bloc de 3 h ; `fin` en tient compte |
| `horaire_libre` | `true` : évènement hors des 6 créneaux (ex. 13h15–14h). `debut`/`fin` sont les vrais horaires ; `creneau` n'est qu'une case de rangement |
| `personnalisee` | séance ajoutée dans l'appli, hors maquette |
| `evenement` | évènement hors maquette (réunion, conférence…) ; toujours `personnalisee` aussi |
| `sae` | cours d'une SAE (code `WS…`) |
| `dans_journee_sae` | pour un cours de SAE : tombe-t-il sur une journée SAE de son parcours ? (`null` sinon) |

#### `GET /api/v1/seances/non-placees`

**But :** les séances de la maquette absentes du planning (panneau « À placer » de la Vue Promo).
**Filtres :** `parcours`, `cours`, `enseignant`, `semaine` (celles qui peuvent aller dans cette semaine),
`inclure_sae=true` (ajoute les cours de SAE, cf. [§ 6](#6-les-sae-simplement)).

```json
{"total": 1, "total_a_placer": 3093, "total_placees": 2384, "par_parcours": {"BUT2-DEV-FI": 1},
 "resume": "14 séance(s) sur 3093 restent à placer à la main. …",
 "seances": [{
   "id": "WR305-S3-TD-4-but2-dev-td", "cours_code": "WR305", "type": "TD", "parcours": "BUT2-DEV-FI",
   "duree_creneaux": 1, "duree_libelle": "1h30", "groupes": ["but2-dev-td"], "enseignants": ["KBR"],
   "ordre": 4, "semaines_possibles": [6, 7, 8],
   "raison": "Aucun créneau commun libre pour le groupe et l'enseignant.",
   "placee_provisoirement": false, "semaine_actuelle": null, "jour_actuel": null, "creneau_actuel": null,
   "sae": false, "statut": "a_placer", "…": "…"}]}
```

- `statut` : `a_placer`, `en_attente_validation` (posée en forçant l'ordre pédagogique, position dans
  `semaine_actuelle`…) ou `hors_solveur` (cours de SAE, seulement avec `inclure_sae=true`).
- `total_a_placer` compte toute la maquette, SAE comprises ; `total_placees`, le planning.

### Calendrier

#### `GET /api/v1/calendrier`

**But :** tout ce que les grilles affichent en plus des séances. Filtre `semaine`.

```json
{"jours_sans_cours": [{"semaine": 9, "numero_semaine": 12, "date": "2026-11-11", "jour": 2,
                       "type": "ferie", "libelle": "Armistice"}],
 "evenements_jour": [],
 "evenements_creneau": [{"semaine": 0, "date": "2026-08-31", "creneau": 3, "debut": "14:00", "fin": "15:30",
                         "libelle": "14h00–15h30 Rentrée", "parcours": ["BUT3-DEV-FC"], "salle": "H.018", "…": "…"}],
 "jours_sae": [{"semaine": 3, "date": "2026-09-24", "jour": 3, "parcours": "BUT3-CREACOM-FC",
                "cours": ["WSA501C"], "…": "…"}],
 "reservations_salles": [{"salle_id": "h018", "date": "2026-09-11", "creneaux": [1, 2],
                          "motif": "Besoin de la Direction (amphi H, 9h30-12h30)", "…": "…"}],
 "periodes_institutionnelles": [{"libelle": "Vacances de la Toussaint", "debut": "2026-10-24",
                                 "fin": "2026-11-01", "type": "vacances"}]}
```

| Clé | Contenu |
|---|---|
| `jours_sans_cours` | fériés (`ferie`) et jours de vacances (`vacances`) tombant dans une semaine de cours |
| `evenements_jour` | évènements du département, à la journée |
| `evenements_creneau` | évènements sur un créneau précis (salle éventuelle) |
| `jours_sae` | jours réservés aux SAE, par parcours (le bandeau de la Vue Promo) |
| `reservations_salles` | salles prises par des tiers |
| `periodes_institutionnelles` | calendrier de l'université ; jamais filtré par `semaine` |

Absences d'enseignants et salles indisponibles saisies dans l'appli : dans `/api/v1/contraintes` (`exceptions`).

### SAE

Les trois endpoints SAE sont décrits au [§ 6](#6-les-sae-simplement).

### Contrôles

#### `GET /api/v1/a-traiter`

**But :** le même contenu, les mêmes catégories et le même ordre que l'écran **À traiter**.
**Droits :** compte actif. La nature `doublon` n'y est que pour un rôle édition ou admin (`doublons_inclus`).
**Filtres :** `semaine`, `parcours`, `enseignant`, `gravite`, `nature`.

| `nature` | Titre à l'écran | `gravite` |
|---|---|---|
| `non-placee` | Séances non placées (regroupées : `nombre: 5` = « ×5 ») | `a_corriger` |
| `sans-salle` | Séances sans salle | `a_corriger` |
| `doublon` | Doublons salle / enseignant | `a_corriger` |
| `regle` | Règles globales en échec | `a_corriger` |
| `contrainte` | Indisponibilités enseignant non respectées | `a_corriger` |
| `sae-hors-journee` | Cours de SAE placés hors journée SAE (les `anomalies` de `/api/v1/sae`) | `a_corriger` |
| `compromis-sae` | Encadrement SAE le même jour (compromis accepté) | `a_revoir` |
| `trouee` | Journées trouées (≥ 2 créneaux vides entre deux cours d'un groupe) | `a_revoir` |

`a_corriger` = rouge à l'écran ; `a_revoir` = ambre.

```json
{"total": 3, "a_corriger": 3, "a_revoir": 0, "doublons_inclus": true,
 "natures": [{"id": "non-placee", "titre": "Séances non placées", "gravite": "a_corriger",
              "aide": "Des heures prévues sans aucun créneau. …", "nombre": 2}, "…"],
 "points": [
   {"nature": "sans-salle", "gravite": "a_corriger", "cle": "ss|WR118-S1-CM-3",
    "titre": "WR118 — Gestion de projet", "detail": "CM · Promo BUT1",
    "semaine": 5, "numero_semaine": 7, "date": "2026-10-06", "jour": 1, "jour_nom": "mardi",
    "creneau": 0, "debut": "08:00", "parcours": ["BUT1"], "enseignants": ["KBR"], "nombre": 1,
    "seance_id": "WR118-S1-CM-3", "seances": []}]}
```

- Les compteurs comptent des **occurrences** (un point « ×5 » compte 5), après filtres.
- `cle` : identifiant stable d'un point, pour voir ce qui apparaît ou disparaît.
- Champs selon la nature : `seance_id` (sans salle), `seances` et `type_doublon` (doublon), `groupe` (journée
  trouée), `regle` (règle), `motif` (contrainte, compromis SAE).
- Tri : sans semaine, semaine en cours, semaines à venir, puis semaines passées (la plus récente d'abord).
  Avec `semaine=`, les points sans semaine restent inclus, comme à l'écran.
- Le badge « nouveau » de l'écran n'est pas repris.

#### `GET /api/v1/controles/doublons`

**But :** une salle ou un enseignant pris par deux séances au même créneau.
**Droits :** rôle **édition** ou **admin**. Filtre `semaine`.

H.007 / H.008 / H.007-008 et H.201 / H.203 comptent comme une seule salle. Un bloc de 3 h compte sur ses deux créneaux.

```json
{"total": 1, "doublons": [{
  "semaine": 5, "numero_semaine": 7, "date": "2026-10-06", "jour": 1, "creneau": 3,
  "debut": "14:00", "fin": "15:30", "type": "salle", "ressource": "H.201 / H.203",
  "seances": [
    {"seance_id": "WR101-S1-TD-3-but1-td-ab", "cours_code": "WR101", "groupes": ["but1-td-ab"],
     "salle": "H.201", "enseignants": ["TPA"]}, "…"], "…": "…"}]}
```

`ressource` : nom de l'enseignant (`type: "enseignant"`) ou salle(s).

#### `GET /api/v1/manques`

**But :** ce qui **manque** dans les données de référence. Même liste que « Données à compléter » dans **À traiter**.
Aucune valeur n'y figure : seulement ce qui manque, et où le compléter. Trié du plus grave au moins grave.

| `famille` | `champ` | Manque | `gravite` | `role_requis` |
|---|---|---|---|---|
| `enseignant` | `email` | adresse mail | `bloque_envoi_liens` | `edit` |
| `enseignant` | `nom` | nom complet | `cosmetique` | `edit` |
| `enseignant` | `code_celcat` | code Celcat (enseignant avec séances) | `bloque_celcat` | `admin` |
| `salle` | `code_celcat` | code Celcat | `bloque_celcat` | `admin` |
| `salle` | `type` | type d'une salle ajoutée à la main | `cosmetique` | `edit` |
| `cours` | `intitule` | intitulé (vide ou égal au code) | `cosmetique` | `edit` |
| `cours` | `code_celcat` | code module Celcat (`TSB…`) | `bloque_celcat` | `admin` |
| `cours` | `id_celcat` | identifiant interne Celcat du module | `bloque_celcat` | `null` |
| `groupe` | `id_celcat` | identifiant interne Celcat du groupe | `bloque_celcat` | `null` |
| `seance` | `salle` | séance placée sans salle | `bloque_celcat` | `edit` |

- `role_requis: null` : ne se complète pas dans l'appli, mais dans un fichier de configuration (`ou_completer`).
- `ecran` : où compléter dans l'appli (ex. `{"vue": "prof", "prof": "KBR"}`).
  Un code Celcat pointe sur **Référence → Codes Celcat**.

```json
{"revision": 1790000000000, "modifie_le": "2026-09-29T10:12:03+00:00", "total": 2,
 "par_gravite": {"bloque_celcat": 1, "bloque_envoi_liens": 1}, "par_famille": {"enseignant": 2},
 "manques": [
  {"id": "enseignant:JHU:code_celcat", "famille": "enseignant", "cle": "JHU", "libelle": "Jules Huet",
   "champ": "code_celcat", "champ_libelle": "Correspondance Celcat", "gravite": "bloque_celcat",
   "usage": "36 séances placées", "nb_seances": 36, "role_requis": "admin",
   "ou_completer": "Référence → Codes Celcat, ou ici pour un administrateur.",
   "ecran": {"vue": "reference", "onglet": "codes-celcat", "famille": "enseignants", "cle": "JHU"}}, "…"]}
```

#### `GET /api/v1/contraintes` · `/enseignants/{code}/contraintes`

**But :** l'écran **Contraintes**. Les règles globales et leur verdict (échecs d'abord), puis chaque enseignant
(écarts d'abord), puis les absences et salles indisponibles saisies dans l'appli (`exceptions`).

```json
{"code": "MRI", "nom": "MARINE RIGUET", "contrainte_declaree": true,
 "indisponibilites": "mercredi toute la journée", "disponibilites": "", "remarques": "",
 "creneaux_interdits": [{"jour": 2, "creneau": 0}, "…"], "dates_interdites": [], "nb_seances": 96,
 "verdict": "compromis_sae", "nb_ecarts": 0, "nb_compromis_sae": 1,
 "ecarts": [{"nature": "compromis_sae", "motif": "encadrement_sae", "cours_code": "WR106",
             "semaine": 6, "numero_semaine": 8, "date": "2026-10-13", "jour": 1, "creneau": null}],
 "exceptions": []}
```

`/api/v1/contraintes` renvoie `{"regles": […], "enseignants": […], "exceptions": […]}` :

```json
{"regles": [{"id": "weekly_cap", "libelle": "Plafond horaire hebdomadaire (33h FI / ~35h FC)",
             "statut": "echec", "detail": "11 cohorte(s) au-dessus du plafond : …"}],
 "enseignants": ["… même forme que ci-dessus …"],
 "exceptions": [{"id": 3, "type": "absence_enseignant", "date": "2026-10-14", "enseignant": "KBR",
                 "salle_id": null, "creneaux": null, "motif": "Jury"}]}
```

| Champ | Valeurs |
|---|---|
| `verdict` | `ecarts` (une indisponibilité non respectée), `compromis_sae` (seulement des compromis SAE), `respectee`, `aucune` |
| `ecarts[].nature` | `indisponibilite` (vraie violation) ou `compromis_sae` (encadre une SAE le même jour, accepté) |
| `ecarts[].motif` | `creneau_interdit`, `hors_liste_blanche`, `date_declaree`, `encadrement_sae`, `hors_dates_de_venue` |
| `ecarts[].creneau` | renseigné seulement pour un créneau récurrent interdit |
| `exceptions[].type` | `absence_enseignant` ou `salle_indisponible` ; `creneaux: null` = journée entière |

Les textes déclarés (`indisponibilites`, `disponibilites`, `remarques`) sont tels que l'enseignant les a saisis.

### Statistiques

#### `GET /api/v1/charges`

**But :** les chiffres des annuaires (Vue Enseignant, Vue TD / TP, cours, salles), par semaine et au semestre.
Avec `semaine=`, les champs `heures_semaine` / `creneaux_occupes` sont remplis (sinon `null`).
`heures_par_semaine` (ou `creneaux_par_semaine`) donne **toujours** toutes les semaines : un seul appel suffit.

```json
{"semaine": 5, "heures_par_creneau": 1.5, "creneaux_par_semaine": 30,
 "enseignants": [{"code": "KBR", "heures_semaine": 27.0, "heures_semestre": 247.5,
                  "heures_par_semaine": {"4": 19.5, "5": 27.0, "…": "…"}, "nb_seances": 153,
                  "nb_matieres": 6, "nb_non_placees": 2, "contrainte": "compromis_sae", "nb_ecarts": 0, "…": "…"}],
 "groupes": [{"id": "but1-tp-a", "type": "tp", "fc": false, "heures_semaine": 31.5, "heures_semestre": 322.5, "…": "…"}],
 "cours": [{"code": "WR101", "parcours": "BUT1", "prevues": 62, "placees": 61, "non_placees": 1,
            "heures_semaine": 6.0, "heures_placees": 91.5, "…": "…"}],
 "salles": [{"id": "h018", "creneaux_occupes": 11, "taux": 0.367,
             "creneaux_par_semaine": {"4": 9, "5": 11, "…": "…"}, "seances_semestre": 70, "…": "…"}],
 "parcours": [{"id": "BUT1", "nb_seances": 1009, "heures_semaine": 160.5, "heures_semestre": 1599.0, "…": "…"}]}
```

Comment c'est compté (mêmes règles que l'écran) :

- **enseignant** : heures additionnées (un bloc de 3 h = 3 h ; deux séances simultanées = 3 h).
  `contrainte` suit l'annuaire : `aucune` sans contrainte déclarée. Le verdict complet est dans `/contraintes`.
- **groupe** : ce que suit un étudiant du groupe (CM, TD parent, TP), chaque créneau compté **une fois**.
- **cours** : `prevues` (CM + TD + TP + évaluations) face à `placees` et `non_placees` ; une ligne par parcours.
- **salle** : créneaux occupés sur 30 par semaine (`taux` = occupés / 30), salles réunies et réservations comprises.
- **parcours** : volume **enseigné** (séances dont un groupe appartient au parcours).

Les clés de `heures_par_semaine` sont des index de semaine, écrits en texte. Seules les semaines non vides y figurent.

### Suivi

#### `GET /api/v1/modifications`

**But :** les séances déplacées à la main depuis la dernière génération. Où elles étaient, où elles sont.
**Filtre :** `semaine` (semaine de départ **ou** d'arrivée).

```json
{"total_suivies": 2384, "nb_modifiees": 97,
 "modifications": [{
   "seance_id": "WR106-S1-TP-1-but1-tp-a", "cours_code": "WR106",
   "generation": {"semaine": 5, "date": "2026-10-05", "jour": 0, "creneau": 0, "debut": "08:00", "…": "…"},
   "actuelle":   {"semaine": 5, "date": "2026-10-07", "jour": 2, "creneau": 0, "debut": "08:00", "…": "…"},
   "verrouillee": true, "…": "…"}]}
```

`nb_modifiees` compte avant filtre. Les séances créées dans l'appli n'y sont pas (voir `personnalisee` dans `/seances`).

#### `GET /api/v1/taches`

**But :** les cartes de l'écran **Tâches**.
**Filtres :** `colonne` (`a_faire`, `en_cours`, `fait`), `categorie` (`edt`, `plateforme`), `enseignant`.

```json
[{"id": 12, "titre": "Déplacer le TP de WR106 du groupe A", "description": "Salle Mac indisponible le 14/10.",
  "colonne": "en_cours", "ordre": 2.0, "enseignant": "MRI", "concerne": "Jules", "categorie": "edt",
  "priorite": "urgente", "date_debut": "2026-10-12", "date_fin": "2026-10-14",
  "cree_le": "2026-09-28T08:12:03", "maj_le": "2026-09-29T09:40:11", "fait_le": null,
  "images": [{"id": 7, "nom": "capture-2026-09-29-09h38.png", "type": "image/png", "taille": 184233,
              "largeur": 1440, "hauteur": 900, "cree_le": "2026-09-29T09:38:52",
              "url": "/api/v1/taches/12/images/7"}]}]
```

- `concerne` : à qui la carte est attribuée (prénom libre).
- L'**auteur** d'une carte ou d'une image n'est pas exposé : c'est l'adresse mail d'un compte.
- `images` : dans l'ordre d'ajout ; `taille` en octets, `largeur`/`hauteur` en pixels.

#### `GET /api/v1/taches/{id}/images/{image_id}`

**But :** le fichier d'une image jointe, avec la même clé.

```bash
curl -H "Authorization: Bearer $CLE" -o capture.png "https://cal-iut-mmi.srko.fr/api/v1/taches/12/images/7"
```

- Type réel : `image/png`, `image/jpeg`, `image/webp` ou `image/gif`. Métadonnées (GPS, appareil) retirées à l'envoi.
- Mise en cache 24 h possible : une image ne change jamais (`Cache-Control: private, max-age=86400`, ETag, 304).
- `404` si la tâche, l'image ou le fichier n'existe pas.
- Mêmes droits que `/api/v1/taches`. Un lien public `?t=` n'y a jamais accès.
- Ajouter ou retirer une image se fait dans l'appli.

### Administration

#### `GET /api/v1/celcat/etat`

**But :** l'état de la recopie automatique dans Celcat (compteurs et dates seulement).
**Droits :** rôle **admin**. Les semaines suivent la numérotation de l'écran Celcat. Voir [CELCAT.md](CELCAT.md).

```json
{"saisie_active": true, "worker_actif": true, "worker_ok": true,
 "semaines_validees": [1, 2, 3, 4, 5, 6], "semaines_lancees": [5, 6], "semaines_passees": [1, 2, 3, 4],
 "semaines_completes": [1, 2, 3, 4, 5], "semaines_creation_autorisee": [],
 "valide_le": "2026-09-28T17:02:11+00:00", "dernier_job_lance_le": "2026-09-29T02:00:04+00:00",
 "derniere_ecriture_celcat": "2026-09-29T09:31:40+00:00",
 "compteurs": {"creees": 812, "modifiees": 140, "supprimees": 12, "bloquees": 3},
 "file": {"en_attente": 2, "par_action": {"modifier": 2}, "dernier_passage_le": "2026-09-29T10:05:00+00:00",
          "age_secondes": 42.0, "reussis": 5, "echecs": 0, "ignores": 0, "differes": 2,
          "resume": "5 réussis, 2 en attente d'une semaine ouverte."}}
```

- `worker_actif` : pas en pause volontaire. `worker_ok` : a donné signe de vie récemment.
- `derniere_ecriture_celcat` : dernière écriture **réellement faite** dans Celcat.
- `file.differes` : en attente qu'une semaine soit ouverte dans Celcat (différent de `echecs`).

### Documentation interactive

| Adresse | Contenu |
|---|---|
| `/api/v1/docs` | Page Swagger : chaque endpoint, ses paramètres, un exemple, et un bouton « Try it out » |
| `/api/v1/openapi.json` | Schéma OpenAPI 3.1 des routes `/api/v1` (pour générer un client) |

Réservées à un compte actif. Ouvrir `/api/v1/docs` dans un navigateur connecté à l'appli (compte « Accès API » compris),
ou lire le schéma avec une clé :

```bash
curl --compressed -H "Authorization: Bearer $CLE" https://cal-iut-mmi.srko.fr/api/v1/openapi.json -o openapi.json
```

La page Swagger charge ses fichiers depuis le site jsDelivr : il faut un accès à internet. Le schéma, lui, est autonome.

---

## 6. Les SAE, simplement

Le mot « SAE » désigne deux choses différentes.

| | Journée SAE (calendrier) | Cours de SAE (séance) |
|---|---|---|
| C'est quoi | Un jour entier réservé à un parcours pour ses projets. Aucun cours classique du parcours n'y est placé. | Une séance de la maquette d'une SAE (code `WS…`) : type, groupes, enseignants, durée. |
| D'où ça vient | Calendrier officiel des SAE, plus des corrections locales | La maquette |
| Endpoints | `/api/v1/sae/periodes`, `/api/v1/sae/journees` | `/api/v1/sae`, `/api/v1/sae/{code}`, `/api/v1/seances?sae=true` |
| Dans les `.ics` de groupe | Évènement journée entière « Semaine de projet/évaluation SAE — WS501D » | Séance ordinaire, si elle est placée |

**La règle :** un cours de SAE a lieu seulement sur une journée SAE de son parcours.

- Exception déclarée : quelques SAE placées par la génération elle-même (ex. WSA501D, sans date au calendrier officiel).
- Un cours de SAE placé hors journée SAE, sans exception, est une **anomalie**. Elle apparaît dans `/api/v1/sae`
  (`anomalies`) et dans `/api/v1/a-traiter` (nature `sae-hors-journee`).
- La plupart des cours de SAE ne sont **pas placés** : les enseignants les organisent sur les journées SAE.
  Ils restent visibles dans `/api/v1/sae` (`non_placees`, `statut: "hors_solveur"`).

### `GET /api/v1/sae/periodes` — semaines de projet

**But :** les bandeaux « semaine de projet ». Une période = des jours SAE qui se suivent pour une même SAE
(le week-end ne coupe pas). Ce sont exactement les évènements journée entière des flux `.ics` de groupe.
**Filtres :** `parcours`, `semaine`, `du`, `au` (période qui chevauche).
Une SAE sans parcours connu (`parcours: null`) concerne tout le monde : elle est toujours incluse.

```json
[{"id": "WS501D-2026-10-19", "code": "WS501D",
  "intitule": "Développer pour le web ou Concevoir un dispositif interactif",
  "libelle": "WS501D", "titre": "SAE WS501D", "description": "Semaine de projet/évaluation SAE — WS501D",
  "parcours": "BUT3-DEV-FI", "groupes": [],
  "date_debut": "2026-10-19", "date_fin": "2026-10-22",
  "jours": ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"], "nb_jours": 4,
  "semaines": [7], "numeros_semaine": [9]}]
```

- `date_debut` et `date_fin` sont **incluses**.
- `groupes` : TD concernés (ex. `["AB"]`) si la SAE ne réserve le jour qu'à une partie de la promo ; vide = tout le parcours.

### `GET /api/v1/sae/journees` — journées SAE

**But :** les mêmes périodes, **jour par jour et par parcours**. Pour chaque journée : les SAE, leur origine
(`calendrier_officiel` ou `correction_locale` + motif), les groupes, les encadrants attendus ce jour-là,
et les cours de SAE placés ce jour-là. Une journée SAE bloque les 6 créneaux.
**Filtres :** `parcours`, `semaine`, `du`, `au`.

```json
{"total": 1, "par_parcours": {"BUT3-CREACOM-FC": 1}, "journees": [{
  "id": "BUT3-CREACOM-FC|2026-09-24", "date": "2026-09-24", "semaine": 3, "numero_semaine": 5,
  "jour": 3, "jour_nom": "jeudi", "parcours": "BUT3-CREACOM-FC", "groupes": [],
  "journee_entiere": true, "creneaux": [0, 1, 2, 3, 4, 5],
  "sae": [{"code": "WSA501C", "intitule": "Création engagée et communication d'acceptabilité",
           "origine": "correction_locale", "motif": "Les journées SAE de l'établissement ne coïncidaient pas …"}],
  "encadrants": [], "seances": []}]}
```

### `GET /api/v1/sae` · `/sae/{code}` — cours de SAE

**But :** une entrée par SAE (code, semestre, parcours) : volumes, enseignants, encadrants et leurs phases,
jours réservés, cours placés, cours non placés. En tête : les totaux et la liste des anomalies.
**Filtres :** `parcours`, `semaine` (listes réduites à cette semaine, sauf `non_placees`).
`/sae/{code}` renvoie `{"code", "intitule", "declinaisons": […]}` (une déclinaison par parcours).

```json
{"total": 2, "nb_seances_maquette": 26, "nb_placees": 17, "nb_non_placees": 9,
 "nb_dans_journee_sae": 0, "nb_exceptions": 17, "nb_anomalies": 0, "anomalies": [],
 "sae": [{
   "code": "WSA501D", "intitule": "…", "parcours": "BUT3-DEV-FC", "semestre": "S5", "annee": "BUT3",
   "planifiee_par_solveur": true, "commentaire_edt": null,
   "nb_seances_maquette": 17, "nb_placees": 17, "nb_non_placees": 0,
   "enseignants": ["BTO", "JSA"], "encadrants": [], "jours_reserves": [],
   "seances": [{"id": "…", "cours_code": "WSA501D", "date": "2026-08-31", "debut": "15:30", "fin": "18:30",
                "…": "… (mêmes champs que /api/v1/seances)",
                "dans_journee_sae": false, "journee_sae": null,
                "exception": true, "motif_exception": "SAE placée par la génération …", "anomalie": false}],
   "non_placees": [], "…": "…"}]}
```

- Chaque cours de SAE apparaît **une seule fois** : dans `seances` ou dans `non_placees`.
- `encadrants[].jours` : jours où l'enseignant encadre. Ils produisent les compromis « Encadrement SAE » des contraintes.
- `non_placees[].statut` : `hors_solveur` (organisé par les enseignants), `a_placer` (SAE placée par la génération,
  cours manquant), `en_attente_validation`.
- `commentaire_edt` : commentaire de la maquette à l'attention de l'emploi du temps.

---

## 7. Que veut dire cette erreur ?

| Code | Sens | Que faire |
|---|---|---|
| `304` | Rien n'a changé depuis l'ETag envoyé. Pas de contenu. | Garder les données déjà lues. Ce n'est pas une erreur. |
| `401` | Pas de clé, clé fausse ou clé révoquée. `{"detail": "Authentification requise."}` | Vérifier l'en-tête `Authorization: Bearer caliut_…`. Générer une nouvelle clé. |
| `403` | Compte pas encore activé, rôle insuffisant (`Permissions insuffisantes pour cette action.`), ou adresse IP bloquée. | Demander l'activation ou le bon rôle à un administrateur. |
| `404` | Ressource inconnue (code, id), ou aucun planning chargé sur le serveur. | Vérifier l'identifiant (cf. `/api/v1/enseignants`, `/groupes`…). |
| `422` | Paramètre invalide (ex. `jour=7`). | Corriger le paramètre ; le message dit lequel. |
| `429` | Trop de requêtes. En-tête `Retry-After` (secondes). | Attendre la durée indiquée. Sonder `/version` plutôt que les données. |

> **Attention :** une clé révoquée qui continue d'appeler reçoit des `401` en série.
> Au-delà de 30 refus en 10 minutes, l'adresse IP est bloquée 24 h. Arrêter le script dès un `401`.
> Détails : [ANTI-ASPIRATION.md](ANTI-ASPIRATION.md).

---

## 8. Limites de débit et bonnes pratiques

| Qui | Plafond |
|---|---|
| Clé API ou session de compte | 600 requêtes par minute et par compte |
| Lien public `?t=` (ne lit que `/version`) | 3 000 requêtes par minute et par adresse IP |

Si la protection anti-aspiration est en mode `enforce`, un plafond plus bas s'ajoute :
300 requêtes par minute par compte pour une clé API (rafale de 150). Voir [ANTI-ASPIRATION.md](ANTI-ASPIRATION.md).

Un `304` compte comme une requête. Ces plafonds ne gênent aucun usage normal. L'appli elle-même sonde
`/version` toutes les 30 s, et seulement quand l'onglet est visible.

**Bonnes pratiques :**

1. Sonder `/api/v1/version`, **pas** les données. Toutes les 30 s à 5 min selon le besoin.
2. Toujours envoyer `If-None-Match` avec l'ETag reçu.
3. Relire les données seulement quand la révision change. `/api/v1/export` donne tout en un appel.
4. Demander la compression : en-tête `Accept-Encoding: gzip` (`curl --compressed`).
5. Respecter `Retry-After` après un `429`.
6. Arrêter après un `401` ou un `403` : insister fait bloquer l'adresse IP.
7. Pour un agenda, utiliser les flux `.ics` ([ICS.md](ICS.md)), qui répondent eux aussi en `304`.

---

## 9. Pour les techniciens

### Authentification

| Méthode | Comment |
|---|---|
| Clé API | En-tête `Authorization: Bearer caliut_…` |
| Session de compte | Cookie de l'appli (`POST /auth/login`) ; c'est ce qu'utilise la documentation interactive |

- Compte « Accès API » (rôle `api`) : sa **clé** lit `GET /api/v1/*` avec les droits `read_only`, rien d'autre
  (ni routes internes, ni serveur MCP, ni écriture : `403`). Son **cookie** n'ouvre que la gestion de ses clés,
  `/api/v1/docs` et `/api/v1/openapi.json`.
- Pour un compte ordinaire, la même clé sert au serveur MCP et à la commande `cal-iut prod diff/pull/push`.
- Lien personnel public `?t=` (celui des enseignants et des groupes) : il n'ouvre que `/app-state`, `/meta`,
  `/timetable`, `/ics/…` et `GET /api/v1/version`. **Jamais** le reste de v1, ni sa documentation.

### Droits et données jamais exposées

- Tout compte actif : planning, référentiel, non placées, « À traiter » (sans doublons en lecture seule),
  contraintes, charges, modifications, tâches, calendrier, SAE, manques.
- Rôle `edit` ou `admin` : `/controles/doublons` et la nature `doublon` de `/a-traiter`.
- Rôle `admin` : `/celcat/etat`.

L'API ne sort **jamais** : comptes, adresses mail de comptes, mots de passe, clés API, jetons de session,
identifiants ou journaux bruts Celcat, chemins sur le disque. Les mails de **contact** des enseignants et leurs
contraintes déclarées sont lisibles par tout compte actif, comme dans l'appli.

Volontairement hors de v1 :

| Donnée | Pourquoi |
|---|---|
| Comptes, rôles, clés API | Administration et données personnelles |
| Auteur d'une tâche ou d'une image | C'est l'adresse mail d'un compte |
| Journal Celcat détaillé, correspondances, relevé, plan de saisie | Données de travail de l'écran Celcat ; seul l'état synthétique est exposé |
| Sauvegardes | Fichiers d'état complets (admin) |
| Notifications, mails aux enseignants | Administration, et contiennent des adresses |
| Historique du contrôle hebdomadaire des doublons (badge « nouveau ») | Ne dépend pas de l'état du planning |
| Poids du solveur, analyse des corrections, statut des calculs | Réglage interne de la génération |
| Créneaux libres pour placer une séance | Outil d'édition |

### Révision, ETag et cache

- La révision part de l'heure de démarrage en millisecondes, puis ne fait qu'augmenter, même après un redémarrage.
- Elle avance à chaque écriture visible : séance déplacée, créée, supprimée, salle changée, tâche, exception,
  régénération, écriture MCP. Elle avance aussi au passage de minuit (statut des semaines) et quand un fichier de
  configuration change (fenêtres SAE comprises).
- Toute réponse v1 (et `/app-state`, `/meta`, `/timetable`, `/diff`, `/ics/*`) porte un `ETag: W/"…"` et
  `Cache-Control: private, no-cache` (`no-cache` pour les `.ics`).
- L'ETag dépend de la révision, de l'URL avec ses paramètres, de la variante (complète ou publique) et,
  pour `/a-traiter`, du rôle. Une variante n'est jamais servie à la place d'une autre.
- Exception : `/celcat/etat`. Le worker Celcat écrit sans faire avancer la révision : l'ETag y est calculé sur
  le **contenu**, et la réponse est recalculée à chaque appel. Ne pas la sonder plus d'une fois par minute.

### Compression

Toute réponse d'au moins 1 Ko part en gzip si le client envoie `Accept-Encoding: gzip`.
Ordre de grandeur : l'export complet passe d'environ 2 Mo à moins de 100 Ko ; `/app-state` de 590 Ko à 48 Ko.

### Conventions

- Noms de champs en français, `snake_case`.
- Dates `AAAA-MM-JJ` ; horodatages ISO 8601 en UTC.
- Horaires lisibles `"HH:MM"` (`debut`, `fin`) **en plus** des index.
- Jours : `0` = lundi … `4` = vendredi. Créneaux : `0` = 08:00, `1` = 09:30, `2` = 11:00, `3` = 14:00,
  `4` = 15:30, `5` = 17:00. Un créneau dure 1 h 30 ; un bloc de 3 h compte 2 créneaux.

#### Numéros de semaine

Trois numérotations coexistent, toujours nommées explicitement :

| Champ | Sens | Exemple |
|---|---|---|
| `semaine` | index (0, 1, 2… sans trou pour les vacances) — celui qu'attendent les paramètres `semaine=` | `5` |
| `numero` / `numero_semaine` | « Semaine N » affichée dans l'appli (semaine 1 = semaine ISO 35 de 2026) | `7` |
| `semaine_iso` | semaine du calendrier ISO | `41` |

Seule exception : `/api/v1/celcat/etat`, dont les listes suivent la numérotation de l'écran Celcat.

### Côté serveur

| Sujet | Où |
|---|---|
| Routes v1 | `src/cal_iut/api/v1.py` — aucune règle métier propre : tout est relu dans les fonctions existantes |
| Vues calculées (« À traiter », charges) | `src/cal_iut/api/v1_vues.py`, portage de `frontend/src/utils/todo.ts`, `annuaires.ts`, `sallesLibres.ts`. Une règle changée d'un côté doit l'être de l'autre ; `tests/test_api_v1_complete_2026_09_29.py` vérifie les mêmes nombres |
| Révision | `src/cal_iut/api/revision.py` ; avancée par `main.py::_apres_ecriture_planning` et les autres écritures, un middleware filet (`_RevisionApresEcriture`) sur toute écriture 2xx protégée, et des sondes (jour, fichiers, état remplacé) |
| Cache et ETag | `src/cal_iut/api/cache_http.py` : une réponse est construite une fois par (révision, URL, variante), puis resservie déjà sérialisée et compressée |
| Droits | `dependencies=[Depends(accounts.require_role(...))]` sur la route ; une réponse qui dépend du rôle passe le rôle dans la clé de cache (`_repondre(..., en_plus=...)`) |
| Débit | dépendance `_limiter_v1` sur tout le routeur (`LIMITE_V1`, `LIMITE_V1_LIEN_PUBLIC`) |

Règles pour une nouvelle route :

- Une route de **lecture** qui dépend de l'état passe par `cache_http.repondre` (ou `v1._repondre`).
  Si ses données changent hors révision (comme Celcat), son ETag se calcule sur le contenu.
- Une route d'**écriture** hors POST/PATCH/PUT/DELETE classique (thread, appel direct) appelle
  `revision.incrementer(...)` elle-même.
- Toute route v1 est couverte automatiquement par le test du lien public
  (`tests/test_lien_perso_perimetre_2026_09_29.py`) et par le contrôle de couverture d'authentification au démarrage.

### Compléter une donnée de référence (routes internes, hors v1)

v1 ne fait que lire. L'appli écrit par ses routes internes (`src/cal_iut/api/reference.py`,
`src/cal_iut/api/codes_celcat.py`). Les écritures vont dans `data/state/` (jamais `data/config/`, figé dans l'image),
sous le verrou d'écriture, avec un journal (qui, quand, valeur d'avant) dans `data/state/references.json`.
La révision avance.

| Route | Corps | Droits | Fichier |
|---|---|---|---|
| `GET /reference/manques` | — | compte actif | — |
| `PUT /reference/enseignants/{code}/contact` | `{"email"}` : format validé, minuscules, refus d'une adresse déjà prise | `edit` | `references.json` |
| `PUT /reference/enseignants/{code}` | `{"nom"}` (`edit`) ou `{"code_celcat"}` (`admin`) | selon corps | `references.json`, `celcat_mappings.json` |
| `PUT /reference/salles/{id}` | `{"capacite", "type"}` d'une salle ajoutée à la main (`edit`), `{"code_celcat"}` (`admin`) | selon corps | `custom_rooms.json`, `celcat_mappings.json` |
| `PUT /reference/cours/{code}` | `{"intitule"}` (`edit`), `{"code_celcat"}` code module `TSB…` (`admin`) | selon corps | `references.json`, `celcat_mappings.json` |
| `DELETE /reference/enseignants/{code}/contact`, `…/{code}/nom`, `/reference/cours/{code}/intitule` | « Revenir à la valeur du fichier » | `edit` | `references.json` |
| `POST /reference/enseignants` | « Nouvel intervenant » : `{"nom", "code", "code_celcat"?, "email"?, "confirmer"?}` (détail ci-dessous) | `admin` | `references.json`, `celcat_mappings.json` |
| `POST /reference/enseignants/verifier` | même corps : erreurs et avertissements, sans rien écrire | `admin` | — |
| `DELETE /reference/enseignants/{code}` | intervenant créé dans l'appli et sans séance (404 s'il vient de la configuration, 409 s'il a des séances) ; retire aussi son mail et son code Celcat saisis | `admin` | `references.json`, `celcat_mappings.json` |
| `GET /reference/codes-celcat[?famille=…]` | entités par famille : code, origine (`fichier`/`appli`/`manquant`), séances, suggestions | compte actif | — |
| `PUT /reference/codes-celcat` | `{"famille", "cle", "code"}`, seulement pour une entité **sans** code connu | `admin` | `celcat_mappings.json` |
| `DELETE /reference/codes-celcat?famille=…&cle=…` | « Revenir à manquant » (ou au code connu pour une saisie antérieure au verrou) ; 404 sans saisie | `admin` | idem |
| `PUT /reference/codes-celcat/sans-code` | `{"famille", "cle", "motif"}` : « sans code (voulu) », motif obligatoire | `admin` | idem (`sans_code_voulu`) |
| `DELETE /reference/codes-celcat/sans-code?famille=…&cle=…` | retire celui saisi dans l'appli (celui de `celcat.yaml` : 409) | `admin` | idem |

**Nouvel intervenant** (`POST /reference/enseignants`) : code de 2 à 4 lettres majuscules.
`400` format invalide. `409` code déjà pris (planning, maquette, feuille, suppléments, appli, disponibilités,
annuaire des mails) ou adresse déjà attribuée. `409 {"message", "avertissements", "suggestion_code"}` tant qu'un
avertissement n'est pas confirmé (`confirmer: true`) : code présent dans `celcat.yaml` pour une autre personne,
nom proche d'un enseignant connu. Un code Celcat déjà porté par un autre trigramme bloque. Réponse `201`
`{"code", "nom", "email", "code_celcat", "cree_le", "avertissements_confirmes", "message", "revision"}`.

**Codes Celcat** (`PUT /reference/codes-celcat`) : `409` si le code est déjà connu (fichier ou maquette), si l'entité
est « sans code (voulu) », ou si le code est déjà porté par une autre entité de la famille (sauf salle réunie et
sa moitié). Format vérifié par famille. Les groupes sont refusés (`409`, fichier `celcat_groupes.yaml`).
L'auteur d'une saisie n'est rendu qu'aux admins.

Autres règles :

- La saisie a le dernier mot : elle complète une valeur absente ou **corrige** celle du fichier.
  Chaque ligne du journal garde `avant`, `apres` et `valeur_fichier`. Re-saisir la valeur du fichier retire la surcharge.
- `/app-state` (comptes seulement) porte `surchargesReference` (valeur, valeur d'origine, qui, quand) pour la
  marque « modifiée dans l'appli ».
- Une seule fonction d'écriture par famille (`definir_code` / `effacer_code`), appelée par `PUT /reference/codes-celcat`,
  par le `code_celcat` des routes ci-dessus et par `PUT/DELETE /celcat/mappings`. Même format, mêmes refus,
  même trace (`valeur`, `ajoute_le`, `ajoute_par`, `valeur_avant`, `valeur_fichier`).
- `load_celcat_config` lit aussi les codes préenregistrés de la maquette (`data/config/celcat_modules_maquette.yaml`,
  généré par `scripts/generer_codes_maquette.py`) et les « sans code (voulu) » (`celcat.yaml`, puis l'appli).
- Une séance dont le cours, l'enseignant ou la salle est « sans code (voulu) » n'est pas envoyée à Celcat.
  `/celcat/plan` la compte dans `non_envoyees` / `motifs_non_envoi`, pas dans `bloquees`. `/reference/manques`
  ne la liste plus. Voir [CELCAT.md](CELCAT.md).
