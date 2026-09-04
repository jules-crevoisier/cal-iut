# Celcat : ce qu'on sait, et ce qu'il reste à faire

Relevé les 31 août et 1er septembre 2026, en explorant le vrai Celcat de
l'URCA depuis un conteneur, en **lecture seule** (rôle `985_consultation`).
Tout ce qui suit a été constaté, pas supposé — ce qui n'a pas pu être
vérifié est signalé comme tel.

## L'essentiel en dix lignes

Celcat Timetabler Live est une application **qooxdoo** sur IIS/ASP.NET :
des `<div>` positionnés au pixel, sans `id`, sans `name`, sans `role`.
Aucun sélecteur ne tient. On repère le **texte affiché** et on clique à ses
coordonnées.

Elle s'appuie sur un service **JSON-RPC 2.0** (`/script/CTWebService.dll`)
qu'on ne peut pas appeler directement — mais dont on peut **lire les
réponses**. C'est de loin le meilleur moyen d'extraire des données : complet,
exact, sans dépendre de ce qui est affiché à l'écran.

## Y accéder

`celcat-lv.univ-reims.fr` **ne résout pas** depuis l'extérieur : le VPN est
obligatoire hors site. Sur place, à l'IUT, l'accès est direct — d'où la
règle : **toujours essayer sans VPN d'abord** (`celcat/reseau.py`).

Le VPN AnyConnect fonctionne aussi bien depuis Windows (client Cisco) que
depuis Linux (**OpenConnect**, même protocole). Testé de bout en bout depuis
un conteneur : authentification identifiant + mot de passe, sans second
facteur, `tun0` monté, Celcat joignable.

## Se connecter

1. Choisir une base : `URCA_2023` … `URCA_2026`, et **`URCA_FORMATION`**.
2. Bouton « Connexion » → dialogue « Sécurité CELCAT ».
3. Identifiant + mot de passe : **les mêmes que le VPN**.
4. Champ « Rôle » — décocher « Utiliser le rôle par défaut » :
   - `985_consultation` : **lecture seule** ;
   - `985_T_MMI` : écriture sur le périmètre MMI.

> **Se déconnecter à la fin.** Celcat garde les sessions ouvertes. En
> enchaîner sans rendre la précédente finit par saturer le serveur, qui
> cesse alors d'afficher la liste des bases. Constaté en explorant.

> **Deux garde-fous gratuits.** Explorer en `985_consultation` rend toute
> écriture *impossible*, plutôt que simplement *évitée*. Et `URCA_FORMATION`
> permet d'essayer une saisie sans toucher aux données réelles.

## Les données

Le service expose `udlResources.load(<type>, …)`. Types relevés :

| type | ressource | volume (URCA_2026) |
|-----:|-----------|-------------------:|
| 601 | Matières | trop pour un chargement global |
| 602 | Groupes | trop pour un chargement global |
| 603 | Personnel | 4 975 |
| 604 | **Salles** | 2 444 |
| 607 | Équipes | 300 |
| 610 | Départements | 155 |
| 618 | Catégories d'événements | 38 |

Les catégories d'événements portent une **pondération** (`[CM]` 100,
`[TD]` 100, `[CM bénévole]`, `[CM Capacite]`, `[TD bénévole]`) : c'est par
là que passe la paie. À rapprocher de `types_seance` dans `celcat.yaml`.

### Trois pièges dans les réponses

1. **Ce n'est pas du JSON.** L'en-tête `X-Use-Object-Date: yes` fait
   renvoyer des `new Date(2026,5,12,11,11,5,0)`. `lire_reponse` les
   convertit — attention, le mois est en base 0, le 5 est **juin**.
2. **La session est liée à la connexion.** Ni cookie, ni en-tête, ni jeton :
   un `fetch` séparé reçoit `ESessionTimeout`, même en réutilisant l'URL de
   session ou en poursuivant la numérotation JSON-RPC. Les deux ont été
   essayés. On lit donc les réponses de l'application, on ne la remplace pas.
3. **Le chargement est paresseux.** Seules les lignes visibles sont
   détaillées. Pour en obtenir plus il faut faire défiler **le tableau** —
   `mouse.wheel` agit là où est le pointeur, et laissé sur le champ de
   filtre il ne défile rien du tout. Ça m'a coûté plusieurs essais où une
   seule ligne remontait.

### Chercher

La recherche par **nom exact** est fiable : 21 salles cherchées, 21
retrouvées. Un préfixe trop court déclenche `ETooManyRecords` et
l'application ne charge alors aucun détail. Donc : chercher précis.

Pour un **enseignant**, chercher par le **nom de famille** ; Celcat trouve
mal par le prénom. Ne concerne que les 3 enseignants dont le code Celcat
vaut `0` dans `celcat.yaml` — les 80 autres ont un code numérique.

## Ce que la vérification des salles a donné

19 libellés sur 21 concordent. Trois écarts, tous reportés dans
`celcat.yaml` :

- **H.018 (Amphi MMI) est introuvable.** Ni « H.018 », ni « amphi » côté IUT
  de Troyes. C'est bloquant pour les CM. → **question pour Kyllian**.
- **H.022 s'appelle « H.022 studio »** chez eux. Une recherche sur « H.022 »
  seul ne remonte rien.
- **H.203 n'existe pas**, ce que notre contournement vers H.023 supposait
  déjà. Confirmé.

Restent les deux salles **combinées** (H.007-008, H.201-203) : leurs moitiés
existent séparément dans Celcat, la combinaison non. Il faudra soit saisir
deux séances, soit n'en garder qu'une.

Les capacités Celcat diffèrent parfois des nôtres (H.201 : 10 chez eux,
H.104 : 0). Ce sont les leurs qui décident d'un conflit de leur côté.

## Les groupes

Convention relevée sur S1, S3 et S5, en CM, TD et TP :

```
BUT MMI <semestre> <libellé> - <année de cohorte>     ex. « BUT MMI S1 TD AB - 2024 »
```

L'année est celle d'**entrée de la cohorte**, pas celle de la base : dans
`URCA_2026` les groupes s'appellent encore « - 2024 ». Une recherche sans le
suffixe les retrouve, ce qui évite d'avoir à deviner. Département :
`T_MMI T29`.

## La vue emploi du temps

Un double-clic sur un groupe ouvre son emploi du temps. Le titre porte le
**code Celcat** du groupe : « BUT MMI S1 TD AB - 2024 **[6TSBZ1TD_1]** ». Ce
code est plus stable que le libellé — c'est lui qu'il faudra mémoriser.

En bas à gauche, un sélecteur de **semaines** en grille (Août → Juillet),
avec des numéros de semaine et des infobulles du type « 4 (1/25/27-1/31/27) ».
Les dates y sont au format américain.

> **Celcat contient DÉJÀ nos groupes et leurs séances.** « BUT MMI S1 TD AB »
> affiche 206 h 48 d'emploi du temps. La saisie n'écrit donc pas sur une page
> blanche : elle doit comparer, créer, modifier, supprimer — ce que
> `sync.construire_plan` fait déjà. Ne jamais créer en aveugle.

Avec le rôle `985_consultation`, un bandeau annonce « Vous avez un accès en
lecture seulement à cet emploi du temps ». Avec `985_T_MMI`, il disparaît :
c'est le témoin le plus simple pour vérifier qu'on a bien les droits.

Un double-clic sur une case vide n'ouvre PAS un formulaire de création mais
l'**inspecteur d'événement**, avec cinq onglets :

| onglet | ce qu'on y attend |
|---|---|
| Détails | date, horaire, durée, catégorie |
| Ressources | enseignant, salle, groupe |
| Remarques et personnaliser | libellés libres |
| Critères requis | contraintes de salle |
| Historique | qui a modifié quoi |

**C'est le même formulaire que celui de la création** — voir « Le formulaire,
enfin ouvert » plus bas. C'est ce qui a permis de le relever sans rien créer.

La création passe par le bouton **+** en haut à droite du panneau — repéré
le 01/09/2026, voir la section suivante.

## Session du 01/09/2026 — le bouton +, et un incident

Réponses de Kyllian Bresson à la première exploration :

- Premier écran Celcat (choix de base) : **`URCA_2026`**.
- Rôle à choisir pour écrire : **`985_T_MMI`** (déjà nommé `ROLE_ECRITURE`
  dans le code).
- **H.018 (Amphi MMI) = « Amphi 3 MMI »** dans Celcat — la question
  bloquante de la session précédente est résolue, reporté dans
  `celcat.yaml`.
- Salles combinées (H.007-008, H.201-203) : **une seule des deux retenue**
  (« on en choisit une seule et on met le TD dedans »), pas de double
  saisie. `celcat.yaml` retient H.007 et H.201 (les premières de chaque
  paire).
- Champ Groupe : taper **« BUT MMI »** suffit à retrouver un groupe.

### Les boutons créer et supprimer, enfin repérés

Ce ne sont PAS des glyphes `+` / `−` mais les icônes `new.png` et
`delete.png`, dans la barre du panneau « Emploi du temps » du groupe (à
droite du titre `Enregistrement`) : 5 icônes, dans l'ordre — `new` (créer),
`delete` (supprimer), `refresh`, `save`, `cancel`. Repérées par leur image
de fond (`background-image`), pas par texte : qooxdoo ne leur donne aucun
libellé accessible. Un survol affiche l'infobulle **« Créer un nouvel
événement »** sur l'icône `new`.

> **`new.png` apparaît DEUX fois à l'écran**, et c'est un piège coûteux : la
> barre du panneau de gauche (liste de ressources) porte la même image. Le
> relevé du 01/09 en a compté deux, à 460 px d'écart horizontal. Cliquer la
> mauvaise, c'est créer un objet dans la mauvaise fenêtre.
>
> `navigateur.cliquer_icone_barre` exige donc un **repère** : on lui nomme
> une icône présente une seule fois dans la barre visée (`refresh`, `save`),
> il en déduit la barre, et ne retient que les icônes qui s'y trouvent. Sans
> repère, une icône ambiguë fait **lever** plutôt que choisir au hasard.
> Verrouillé par deux tests.

### Le sélecteur de semaines : l'infobulle au survol donne la vraie date

Le mini calendrier en bas du panneau (`Semaines de l'emploi du temps`) ne
porte AUCUN attribut exploitable (`title`, `qxtooltip`) dans le DOM — ses
infobulles n'existent que le temps d'un survol réel (`mouse.move` + pause),
pas comme un attribut statique. Cliquer une cellule au hasard ne suffit
donc pas à savoir quelle semaine on vient de sélectionner. Capture
utilisateur du 01/09/2026 : survoler une cellule affiche bien
**« 1 (04/01/27–10/01/27) »** — semaine + plage de dates, exact format
attendu.

**Fait** (`navigateur.choisir_semaine`) : le pilote survole chaque cellule,
lit l'infobulle, et ne clique que celle qui désigne la semaine visée —
sinon il lève. Plus aucune coordonnée devinée.

Une subtilité qui a demandé une décision. Les deux relevés se
**contredisent** sur le format de date : « 4 (1/25/27-1/31/27) » ne se lit
qu'en mois/jour, « 1 (04/01/27–10/01/27) » ne se lit qu'en jour/mois (avril
→ octobre ne serait pas une semaine). Plutôt que de trancher au hasard, les
deux lectures sont essayées, et c'est la **cohérence de l'intervalle** qui
départage : il faut une lecture donnant six jours pleins commençant au lundi
visé. Cela suffit à écarter le seul cas dangereux — prendre la semaine du
1er avril (`01/04/27–07/04/27`) pour celle du 4 janvier, les mêmes chiffres
inversés. Verrouillé par `tests/test_celcat_pilote_2026_09_01.py`.

### Incident : un événement vide créé par erreur

En sélectionnant une case vide (mardi 9h, groupe test **BUT MMI S1 TD AB**,
Celcat `group_id` 1661972) puis en cliquant l'icône `new`, le total
d'heures affiché du groupe est passé de 208h18 à **235h18 (+27h)**, sans
qu'aucun champ n'ait été rempli ni « Enregistrer » cliqué. Confirmé réel
(pas un brouillon d'écran) par une reconnexion **complètement neuve, en
rôle lecture seule** (`985_consultation`) : le total restait à 235h18.

Diagnostic complet obtenu via `udlTimetables.load` (méthode JSON-RPC qui
charge les événements d'un groupe — `params: [{"GroupIDs": [<id>]}]`,
jusque-là non documentée ici) :

```json
{
  "event_id": 1929034,
  "day_of_week": 1,
  "start_time": null, "end_time": null,
  "evCatName": null, "rooms": [], "modules": [], "staff": [],
  "weeks": "YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY",
  "date_change": "2026-09-01T00:50:53",
  "userName": "bres0026", "user_id_change": 107817,
  "protected": "N", "suspended": "N"
}
```

Un événement réel, sans horaire ni salle ni catégorie ni module, mais
**actif sur les 54 semaines de l'année** (`weeks`, une chaîne de `Y`) — ce
qui explique le total : cliquer `new` sans rien remplir crée d'emblée un
événement récurrent par défaut, reconduit sur toute l'année, plutôt qu'une
occurrence isolée à la date sélectionnée.

Repéré visuellement : rendu quasi invisible (`rgba(255,207,118,0.1)`, 10 %
d'opacité — sans catégorie, sans couleur assignée) vers 7h30 le mardi de la
semaine affichée, superposé à un « Jour férié » existant au même endroit
(l'application affichait alors « Événement 1 de 2 » avec un chevron pour
passer au 2e).

**Non résolu, non supprimé.** Les tentatives de sélectionner précisément
cet événement (au lieu du jour férié superposé) puis de le supprimer via
l'icône `delete` ont été bloquées à plusieurs reprises par le
classificateur de sécurité de l'environnement d'exécution — un signal pris
au sérieux plutôt que contourné, pour ne pas risquer de supprimer par
erreur le jour férié protégé qui se trouve au même endroit à la place.

**À faire en priorité, avec supervision** : ouvrir `BUT MMI S1 TD AB` dans
Celcat (rôle `985_T_MMI`), aller sur la case mardi ~7h30 de la semaine du
17-23 août 2026, cliquer dessus, passer à « Événement 2 de 2 » via le
chevron, vérifier qu'il s'agit bien de l'événement sans catégorie/horaire
(`event_id` 1929034 si l'identifiant est visible quelque part dans
l'inspecteur), puis le supprimer. Le total du groupe doit revenir à 208h18.

## Le formulaire, enfin ouvert — sans rien créer

Le point de blocage était circulaire : pour connaître les libellés du
formulaire il fallait l'ouvrir, et l'ouvrir par `new` créait un événement.

**La sortie tenait en une phrase du relevé précédent** : « un double-clic sur
une case vide ouvre l'inspecteur d'événement ». Cet inspecteur *est* le
formulaire de création — mêmes onglets, mêmes champs, en lecture. On le lit
donc sur un événement **existant**, sans jamais toucher `new`. Le script
`scripts/relever_formulaire_celcat.py` ne clique cette icône à aucun moment.

```powershell
docker build -t cal-iut-celcat deploy/celcat-sidecar
docker run --rm --cap-add NET_ADMIN --device /dev/net/tun `
  --env-file .env -v "${PWD}:/travail" -w /travail cal-iut-celcat `
  python scripts/relever_formulaire_celcat.py --vpn `
    --base URCA_2026 --role 985_consultation `
    --semaines 2026-09-14,2027-03-29
.venv\Scripts\python.exe scripts/lire_releve_celcat.py data/releves/celcat-formulaire-<…>
```

Options utiles : `--lister-groupes MMI` (les libellés exacts, plutôt que les
deviner), `--calendrier` (la géométrie du sélecteur de semaines et ses
infobulles), `--semaines` (plusieurs lundis essayés jusqu'à en trouver un qui
porte des séances).

### Ce que ça a donné

| repère | valeur relevée |
|---|---|
| Onglets | `Détails`, `Ressources`, `Remarques et personnaliser`, `Critères requis`, `Historique` |
| Jour | libellé `Jour:` — les deux points font partie du texte |
| Heure | libellé `Heure:` |
| Catégorie | `Catégorie d'événement:` (onglet Détails) |
| Département | `Département:` (onglet Détails) |

Trois corrections que le relevé impose, et qu'aucun raisonnement n'aurait
données :

**1. Le champ est SOUS son libellé, pas à sa droite.** « Jour: » en
(952, 737), sa valeur « Mon » en (956, 770). Même écart pour « Heure: » et
« Temps de pause: » : **+32 px vers le bas, à x quasi constant**. On avait
supposé 120 px vers la droite, d'après les coordonnées de l'ancien
autoclicker. Cette supposition visait (1072, 737) — soit le libellé
« Heure: » à 18 px près : on aurait saisi l'heure dans le champ du jour, et
le formulaire aurait accepté.

**2. Il n'y a qu'UN champ d'horaire, en 12 heures.** L'écran affiche
« 7:00 AM-11:59 PM » : un intervalle entier dans un seul champ, pas un début
et une fin. `heure_debut` / `heure_fin` ont disparu de la carte, et
`navigateur.intervalle_12h` convertit nos `08:00`/`09:30` en
`8:00 AM-9:30 AM`.

**3. Il n'y a pas de bouton texte pour valider l'horaire.** Aucun « OK »
n'existe à l'écran ; c'est l'icône `save` de la barre qui commet.
`validation_horaire` reste vide, volontairement.

### Le sélecteur de semaines : deuxième correction

La méthode « survoler chaque cellule et lire son infobulle » supposait des
cellules identifiables. En vrai, **seule la semaine sélectionnée porte du
texte** ; les autres sont des `<div>` vides. Et le format réel de l'infobulle
n'est ni l'un ni l'autre des deux relevés précédents : c'est
**`Week: 37 (9/7/26-9/13/26)`**, en anglais, mois/jour.

`choisir_semaine` procède donc géométriquement : il énumère les cellules par
position, **fusionne celles qui se superposent** (qooxdoo empile plusieurs
`<div>` par case — sans cette fusion on comptait 3 fois trop de cellules),
calcule où devrait tomber la semaine visée, y saute directement, et corrige
au survol suivant. Il ne clique que sur une cellule dont l'infobulle confirme
le lundi attendu ; sinon il lève.

### Détecter les séances : ni par le texte, ni par l'Échap

Deux impasses, notées pour ne pas y retomber :

- Chercher les séances par leur **texte** remonte aussi les en-têtes de
  colonnes et, pire, les **bulles de survol** — qui contiennent les mêmes
  mots. Les blocs sont donc détectés **géométriquement**, par leur couleur de
  fond et leur taille.
- Fermer une bulle de survol par `Échap` ferme **tout le panneau** emploi du
  temps. On éloigne le pointeur (`mouse.move` vers la liste) et la bulle
  s'efface d'elle-même.

### Onglet Ressources — relevé le 01/09/2026 sur URCA_2025

`URCA_2026` n'avait que des jours fériés : pas d'onglet Ressources à lire.
Sur `URCA_2025`, groupe `BUT MMI S1 CM - 2024` (78 événements, 67 avec
ressources), l'onglet affiche des **sections** :

| à l'écran | champ chez nous |
|---|---|
| `Matières [0]` | `champs.matiere` = `Matières` |
| `Salles [1]` | `champs.salle` = `Salles` |
| `Personnel [1]` | `champs.enseignant` = `Personnel` |
| `Groupes [1]` | (le groupe est déjà celui de l'emploi du temps) |

Le chiffre entre crochets est un compte, il change. On dépose sur le nom.

Catégories lues dans `udlTimetables.load` des groupes CM / TD / TP :

- CM → `[CM]`
- TD → `[TD]` (distinct de `TD0`)
- TP → `[TP]`

Piège en chemin : cliquer l'icône « Groupes » aux Y de 2026 ouvrait
**Départements** (type 610). `ouvrir_ressource` vérifie maintenant le titre
du panneau et balaie la colonne si ce n'est pas le bon.

`carte.manques()` est vide. `POST /celcat/saisie` n'est plus bloqué par le
formulaire.

### Catégories d'événement — la liste complète

Relevée en entier cette nuit (38 catégories, `TYPE_CATEGORIES_EVENEMENT`
= 618) : **`[CM]` existe bel et bien**, distinct de `[CM bénévole]`
(`event_cat_id` 845) et de `[CM Capacite]`. Mais `TD: 4` / `TP: 6` dans
`celcat.yaml::types_seance` sont des INDEX DE POSITION dans un menu
déroulant (hérités des `.bat` d'origine), pas des `event_cat_id` réels —
ceux-ci sont des nombres à trois chiffres (845 pour CM bénévole). Le
formulaire de création n'ayant pas pu être rempli pour de vrai cette nuit
(incident ci-dessus), on ne sait toujours pas laquelle des deux formes
(position ou id) il attend pour la catégorie.

## Ce que l'ancien autoclicker a appris

`~/Desktop/clickclick/` est l'autoclicker nut-js qui précédait cet outil :
23 étapes en coordonnées absolues, calibrées pour un écran 2560×1440 à 75 %
de zoom sous macOS. Inutilisable tel quel — c'est justement ce que le
pilotage par TEXTE remplace. Mais il consignait une chose qu'aucune autre
trace ne documentait, et qui manquait pour finir le travail :

**Les champs du formulaire se remplissent par GLISSER-DÉPOSER** depuis la
liste de ressources de gauche. On ne tape pas dedans : on y dépose une
ligne. Il procède ainsi pour les cinq champs — catégorie, département,
enseignant, salle, matière. Les pauses comptent : qooxdoo implémente son
propre glisser-déposer sur les événements souris, et sans temps d'arrêt
après l'appui puis positions intermédiaires, aucun glissement ne démarre
(`navigateur.glisser_deposer`).

Accessoirement, l'ordre de ses icônes de barre latérale correspond
exactement à `navigateur.ICONES`, ce qui confirme cette table de position.

## Où en est l'outil

Acquis :

- accès réseau (direct ou VPN), sur poste comme sur serveur ;
- connexion, choix de la base et du rôle ;
- lecture fiable des ressources, et recherche par nom ;
- correspondance des salles vérifiée (y compris l'amphi et les salles
  combinées), convention des groupes établie ;
- l'icône de création (`new`) repérée, ainsi que celles de suppression
  (`delete`), sauvegarde et annulation — et la levée d'ambiguïté quand la
  même image apparaît dans deux barres ;
- **le formulaire ouvert et relevé sans rien créer** (double-clic sur un
  événement existant) : onglets, libellés du jour, de l'heure, de la
  catégorie et du département, écart libellé→champ, format d'horaire ;
- lecture fiable des événements d'un groupe (`udlTimetables.load`) ;
- liste complète des 38 catégories d'événement, dont `[CM]` confirmé ;
- **le pilote lui-même** (`driver.PilotePlaywright`) : connexion, ouverture
  d'un groupe par son nom Celcat, choix de la semaine confirmé par
  infobulle, glisser-déposer, onglets, icônes de barre — vérifié hors ligne
  contre une fausse page qui enregistre la séquence ;
- **le lancement** : `POST /celcat/saisie`, simulation par défaut, base
  d'entraînement par défaut, refus avant tout clic si une séance est bloquée,
  si Celcat est injoignable, ou si le formulaire n'est pas relevé.

## Catégories CM / TD / TP

Les libellés Celcat sont `[CM]`, `[TD]`, `[TP]` (`celcat_formulaire.yaml`).
L'id numérique de `[CM]` est **430** (canari).

**Bug historique** : l'ancien autoclicker (`clickclick`) ne connaissait que
TD=4 sinon TP — un CM était donc enregistré en `[TP]` (ex. WR116 mardi
8 sept. 14h). Le chemin RPC actuel résout `[CM]` par libellé ; un filet
refuse toute charge CM dont `event_cat_id ≠ 430`
(`cal_iut.celcat.categories`).

Audit / correctif Live (VPN URCA requis) :

```powershell
python scripts/corriger_cm_categories_celcat.py --vpn --lundi 2026-09-07 --base URCA_2026
python scripts/corriger_cm_categories_celcat.py --vpn --lundi 2026-09-07 `
  --base URCA_2026 --production --ecrire
```

Le diff `comparer` envoie aussi en `a_modifier` un événement dont la
catégorie Live ne correspond pas au type maquette (salle OK mais [TP] pour un CM).

## Voie durable : JSON-RPC dans la page (pas le clicker)

Le `new` / glisser-déposer n'est **pas** le chemin d'écriture. Après `new`,
Conflits s'ouvre, Détails n'apparaît souvent pas, et l'événement naît sur
**54 semaines**. Un `fetch` Python à part reçoit `ESessionTimeout` : la
session est la connexion du navigateur.

La suite : Playwright ne fait que le login ; les appels passent par le
client qooxdoo `ctweb.io.Rpc.invoke` (événement `result`) — un `fetch` /
XHR neuf reçoit `ESessionTimeout` sur `udlTimetables.load`. Méthode
d'écriture relevée dans les scripts : **`udlTimetables.save`**. Premier
write : `URCA_FORMATION`. Production seulement après un canari 1 semaine
là-bas.

Preuve du 01/09/2026 (FORMATION, `985_T_MMI`) :

- `udlTimetables.load` `{GroupIDs:[47925]}` → **266 événements**.
- `udlTimetables.save` **create** (sans `event_id`) a créé l'événement
  **1523405**, 1 semaine, notes `cal-iut-create` (clone WR113).
  `event_id: 0` est refusé (« l'enregistrement n'existe pas »).
- Un `fetch`/`XHR` séparé sur la même page timeoute.

```powershell
python scripts/sonder_rpc_celcat.py --vpn --base URCA_FORMATION
python scripts/pousser_manquants_celcat.py --lundi 2026-09-07 --vpn --base URCA_2026
```

Le second, sans `--ecrire`, liste ce qui manque (WR107 AB, etc.) en lisant
Live. `--ecrire` est refusé tant que `methode_ecriture` est vide.

Manquant :

1. **Nettoyer l'événement vide créé par erreur** (`event_id` 1929034, groupe
   `BUT MMI S1 TD AB`) — voir incident ci-dessus, en priorité. À la main.
2. **Pousser les manquants** en production (`--limite 1 --production --ecrire`
   d'abord, WR107 AB mercredi). Create RPC prouvé sur FORMATION (1523405).
3. Les codes Celcat de 3 enseignants (`0` dans `celcat.yaml`) et de
   WSA501D.

## Modifier / supprimer une séance déjà posée (cause racine du « partial key »)

Le bug historique **`EUDLDSError: Cannot locate a record using only a
partial key`** sur un update RPC n'était pas un champ manquant isolé — la
tentation naturelle (« il manque `original_id` », « il manque
`accessRights` »...) était fausse. Le canari du 01/09/2026 (event_id
202985, FORMATION) l'a prouvé par comparaison : **c'est la DIFFÉRENCE
STRUCTURELLE** entre un objet reconstruit à la main (quelques champs +
`event_id` accroché dessus, comme le fait `charge_utile()` pour une
création) et l'enregistrement **complet** que `udlTimetables.load` renvoie,
qui fait échouer `save`. Un update Celcat n'accepte que sa propre forme
complète, avec seulement les champs voulus modifiés dessus.

Le correctif (`src/cal_iut/celcat/modification.py`) :

1. `localiser_evenement(page, event_id, group_ids=...)` recharge l'EDT des
   groupes concernés via `udlTimetables.load` et renvoie le dict **brut**
   portant `event_id` — jamais un `EvenementCelcat` normalisé qui aurait
   perdu des clés.
2. `fusionner_deltas(brut, ...)` **clone** ce dict et n'écrase QUE
   `day_of_week` / `start_time` / `end_time` / `weeks` / `event_cat_id` /
   `dept_id` / `modules` / `rooms` / `staff` / `groups` / `notes` — le même
   jeu de champs que `ecriture.charge_utile()`, mais superposé sur
   l'enregistrement complet plutôt qu'à la place de rien.
3. `modifier_evenement(...)` enchaîne localiser → fusionner → revérifier
   (`categories.verifier_charge_categorie`, `ecriture.verifier_avant_envoi`
   — mêmes garde-fous que la création : CM sans catégorie refusé,
   masque semaines à 1×Y, `--production` exigé sur URCA_2026) → `save`.

`modifier_seance`/`supprimer_seance` (RPC) sont désormais **branchés** :
`nuit.py::executer_job_nuit(page=...)` consomme les jobs `update` de
`celcat_file_attente.json` via `modification.modifier_manquants`, aux
côtés des `create` (`ecriture.creer_manquants`, inchangé).

**La suppression suit la même cause racine** (`suppression.py`) : on
localise l'événement AVANT de le supprimer, jamais un `event_id` nu. Le
garde-fou `file_attente.autoriser_suppression` (jour férié protégé,
fantôme, `protected=Y`, Celcat-en-plus) est réévalué sur l'enregistrement
**frais** rechargé, jamais sur l'instantané porté par le job en file — un
jour férié devenu protégé après la mise en file bloque quand même.

**La méthode RPC de suppression reste NON PROUVÉE.** Contrairement à
`udlTimetables.save` (capturé au canari du 01/09/2026), aucune capture
n'a encore établi le nom réel de la méthode `delete`/`remove`.
`data/config/celcat_rpc.yaml::methode_suppression` reste donc
**volontairement vide** tant qu'un canari ne l'a pas prouvée — comme
`methode_ecriture` l'était avant le 01/09/2026. `MethodeSuppressionAbsente`
refuse proprement plutôt que de deviner un nom : `supprimer_manquants`
classe alors chaque job en échec (RPC), pas en refus (garde-fou), et il
reste en file pour la prochaine nuit une fois la méthode capturée.

**Tentatives du 05/09/2026, deux hypothèses ÉCARTÉES avec preuve, une piste
UI non aboutie :**

1. *Capture par clic UI* (`scripts/capturer_suppression_celcat.py`, retiré
   après coup — pas assez fiable pour rester) : crée un canari (RPC, prouvé,
   ok), MAIS le repérage du bloc correspondant sur la grille (double-clic
   sur un `<div>` coloré, même technique que `capturer_save_celcat.py`) n'a
   jamais réussi en environnement **headless** — 5 tentatives, jamais le bon
   bloc identifié. Reste à retenter avec un navigateur non-headless (ou une
   autre méthode de sélection) pour aller jusqu'au clic « Supprimer » et
   capturer le RPC qu'il déclenche.
2. *Hypothèse `suspended: "Y"`* — ÉCARTÉE, testée et prouvée fausse.
   `udlTimetables.save` accepte et persiste `suspended: "Y"` sans erreur,
   mais l'événement **reste visible** dans `udlTimetables.load` ensuite
   (`scripts/tester_suspended_celcat.py --event-id … --group-id …`, sans
   `--weeks-all-n`). Ce champ existe (posé à `"N"` à la création,
   `ecriture.py::charge_utile`) mais ne fait pas ce qu'on espérait.
3. *Hypothèse `weeks` tout à `N`* — ÉCARTÉE, refusée par le SERVEUR
   lui-même : `EUDLDSError` sur la contrainte `CK_EVENT_WKLEN` de la table
   `dbo.CT_EVENT` (`--weeks-all-n` du même script). Celcat interdit par
   construction qu'un événement existant n'ait plus aucune semaine active —
   confirme qu'une vraie suppression retire la LIGNE, pas seulement son
   masque de semaines.
4. *Scan statique des méthodes JS* (`scripts/scanner_methodes_udl_celcat.py`)
   — 108 méthodes `udl*.*` recensées sur URCA_FORMATION, **aucune**
   `udlTimetables.delete`/`.remove`. Les seules pistes portant "delete"
   (`udlExclusivity.deleteExclusivityRequest`, `udlRoomBooker.deleteEvents`)
   appartiennent à d'autres sous-systèmes (accès exclusif, réservation de
   salle libre-service), pas au planning enseignant. Le scan élargi (tout
   motif proche de delete/remove/suppr/cancel, pas seulement `udl*`) trouve
   `this.deleteSelected` / `this._onDeleteBtnClick` / `this.undoDelete` —
   de vrais gestionnaires de clic côté client, mais leur appel RPC réel
   n'a jamais été observé (bloqué par le point 1 ci-dessus). Hypothèse la
   plus probable pour la suite : le nom de méthode est construit
   dynamiquement au clic plutôt qu'écrit en toutes lettres dans le JS
   scanné — seule une capture réseau pendant un vrai clic peut trancher.

**Reste de côté sur URCA_FORMATION**, laissés par ces tentatives (aucune
suppression n'ayant marché, impossible de les retirer par API) : trois
canaris `event_id` 1523406/1523407/1523408 sur le groupe « BUT MMI S1 TD
AB - 2024 » (group_id 47925), `notes="canari-suppression"` — inoffensifs
(base d'entraînement), à nettoyer à la main dans l'UI Celcat si besoin, ou
via `methode_suppression` une fois prouvée.

### Ce qui est PROUVÉ en direct vs ce qui ne l'est PAS (02/09/2026)

Deux cas très différents se cachaient derrière la même erreur « partial
key », et ils n'ont pas le même niveau de preuve :

- **Catégorie / horaire / semaines, ressources INCHANGÉES** — prouvé en
  direct à deux reprises : sur URCA_FORMATION (canari 202985, aller-retour
  notes), puis en production sur URCA_2026 (les 2 CM WR116, `event_id`
  1931709 et 1933218, `[TP] → [CM]`, confirmé par une relecture d'audit à
  0 écart). **C'est le seul chemin qu'on peut recommander aujourd'hui.**
- **Changement de RESSOURCE (salle/enseignant/matière)** — la première
  version de `fusionner_deltas` (greffer le nouvel id sur le sous-objet de
  l'ANCIENNE ressource) écrivait **sans erreur mais sans effet** : `save`
  répond succès, la ressource ne change pas (constaté sur le canari
  202985, salle A.018 → une autre salle, ça a marché ; le retour vers
  A.018 est resté silencieusement bloqué). Une deuxième version (recharger
  le VRAI enregistrement de la ressource visée via `udlResources.load`)
  s'est heurtée à un « partial key » sur le sous-objet lui-même — corrigé
  en y incluant `event_id` (l'association événement↔ressource se localise
  par les DEUX, pas par le seul id de la ressource). Après ce correctif,
  le retour vers A.018 est **resté silencieusement sans effet, à nouveau**
  — aucune erreur, la salle ne change toujours pas. Hypothèse non vérifiée :
  la salle visée (A.018, dept `iut Troyes T00`, site 101287) est hors du
  périmètre d'écriture du rôle utilisé, et Celcat ignore l'affectation au
  lieu de la refuser explicitement — mais ce n'est PAS confirmé.
  **Ne pas activer ce chemin pour un déplacement de salle/enseignant/matière
  avant d'avoir compris ce dernier silencieux.** L'événement canari
  (202985, URCA_FORMATION) est resté sur la mauvaise salle après ce test —
  base d'entraînement, pas de production concernée.

## Relire le formulaire (si Celcat change)

Le relevé du 01/09/2026 a rempli `celcat_formulaire.yaml`. Pour le
recommencer sans rien créer (jamais l'icône `new`) :

```powershell
docker run --rm --cap-add NET_ADMIN --device /dev/net/tun `
  --env-file .env -v "${PWD}:/travail" -w /travail cal-iut-celcat `
  python scripts/relever_formulaire_celcat.py --vpn `
    --base URCA_2025 --role 985_consultation --lister-groupes "BUT MMI"
.venv\Scripts\python.exe scripts/lire_releve_celcat.py data/releves/celcat-formulaire-<…>
.venv\Scripts\python.exe -c "from cal_iut.celcat.formulaire import charger_carte; print(charger_carte('data/config').manques())"
```

`--lister-groupes "MMI"` seul ne marche pas (`ETooManyRecords`). « BUT MMI »
si. Le script enchaîne sur le premier groupe TD trouvé.

Liste vide → la carte est complète. Fermer l'inspecteur par **Annuler**.

## L'architecture qui va avec

`deploy/celcat-sidecar/` contient l'image utilisée pour toute cette
exploration : OpenConnect + Playwright, lancée avec `--cap-add NET_ADMIN
--device /dev/net/tun`.

**Ce conteneur doit rester séparé de l'application.** La passerelle URCA
pousse un tunnel *complet* : monter ce VPN dans le conteneur qui sert
cal-iut détournerait tout son trafic sortant et couperait le site public.

Pour un déploiement sur site, ce même conteneur tourne sans VPN du tout —
d'où la règle de l'accès direct d'abord, qui rend les deux cas identiques
au lancement près.

### Le drain de nuit tournait pour personne (trouvé le 04/09/2026)

`POST /celcat/lancer-nuit` (bouton admin de l'application) appelle
`executer_job_nuit()` **sans `page`** : ça empile bien les jobs
create/update/delete dans `celcat_file_attente.json` et scanne les extras,
mais ça n'envoie jamais rien à Celcat — `_consommer_file` exige un `page`
Playwright connecté en VPN, que l'application déployée n'a justement
jamais (cf. ci-dessus). Sans un processus À PART qui relance
`scripts/celcat_nuit.py --ecrire --vpn --production` régulièrement, la
file grossit sans jamais se vider — cause directe d'un déplacement de
séance jamais remonté sur Celcat (retour Kyllian Bresson, 04/09/2026).

**Fix : `deploy/celcat-sidecar/nuit-quotidienne.sh`** — une boucle qui
reste vivante dans CE conteneur (jamais celui de l'appli) et relance le
job de nuit chaque 00h00 :

```bash
docker build -t cal-iut-celcat deploy/celcat-sidecar
docker run -d --restart unless-stopped --name celcat-nuit \
  --cap-add NET_ADMIN --device /dev/net/tun \
  --env-file /chemin/vers/.env \
  -v /chemin/vers/le/VRAI/depot/cal-iut:/travail \
  cal-iut-celcat /travail/deploy/celcat-sidecar/nuit-quotidienne.sh
```

**Le `-v` est le point critique** : il doit pointer sur le `data/state/`
que l'application déployée utilise VRAIMENT (celui qui reçoit les
déplacements faits sur le site), jamais une copie locale de dev — sans
quoi ce conteneur drainerait une file que personne ne remplit. Pas encore
branché en production au moment d'écrire ceci : quelqu'un avec accès au
serveur doit lancer cette commande une fois (le conteneur tourne ensuite
tout seul, `--restart unless-stopped` le relance au reboot).
Suivre : `docker logs -f celcat-nuit`.
