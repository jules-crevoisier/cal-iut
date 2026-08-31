# Celcat : ce qu'on sait, et ce qu'il reste à faire

Relevé le 31 août 2026, en explorant le vrai Celcat de l'URCA depuis un
conteneur, en **lecture seule** (rôle `985_consultation`). Tout ce qui suit
a été constaté, pas supposé — ce qui n'a pas pu être vérifié est signalé
comme tel.

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

### Le bouton + (création), enfin repéré

Ce n'est PAS un vrai `+` glyphe mais une icône `new.png`, dans la barre du
panneau « Emploi du temps » du groupe (à droite du titre `Enregistrement`) :
5 icônes, dans l'ordre — `new` (créer), `delete` (supprimer), `refresh`,
`save`, `cancel`. Repérées par leur image de fond (`background-image`), pas
par texte : qooxdoo ne leur donne aucun libellé accessible. Un survol
affiche l'infobulle **« Créer un nouvel événement »** sur l'icône `new`.

### Le sélecteur de semaines : l'infobulle au survol donne la vraie date

Le mini calendrier en bas du panneau (`Semaines de l'emploi du temps`) ne
porte AUCUN attribut exploitable (`title`, `qxtooltip`) dans le DOM — ses
infobulles n'existent que le temps d'un survol réel (`mouse.move` + pause),
pas comme un attribut statique. Cliquer une cellule au hasard ne suffit
donc pas à savoir quelle semaine on vient de sélectionner. Capture
utilisateur du 01/09/2026 : survoler une cellule affiche bien
**« 1 (04/01/27–10/01/27) »** — semaine + plage de dates américaine, exact
format attendu. **À faire ensuite** : piloter par `mouse.move` (pas
`mouse.click` seul) sur la cellule visée, lire cette infobulle pour
confirmer la semaine AVANT de cliquer, plutôt que deviner des coordonnées
par tâtonnement (ce qui a été tenté cette nuit, sans succès fiable).

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

## Où en est l'outil

Acquis :

- accès réseau (direct ou VPN), sur poste comme sur serveur ;
- connexion, choix de la base et du rôle ;
- lecture fiable des ressources, et recherche par nom ;
- correspondance des salles vérifiée (y compris l'amphi et les salles
  combinées), convention des groupes établie ;
- l'icône de création (`new`) repérée, ainsi que celles de suppression
  (`delete`), sauvegarde et annulation ;
- lecture fiable des événements d'un groupe (`udlTimetables.load`) ;
- liste complète des 38 catégories d'événement, dont `[CM]` confirmé.

Manquant :

1. **Nettoyer l'événement vide créé par erreur** (`event_id` 1929034, groupe
   `BUT MMI S1 TD AB`) — voir incident ci-dessus, en priorité.
2. **Le formulaire de création rempli pour de vrai** — un clic sur `new`
   crée déjà un événement par défaut (récurrent sur l'année) ; il reste à
   voir le formulaire de saisie (catégorie, horaire, salle, groupe,
   enseignant) qui doit suivre ce clic, jamais atteint cette nuit.
3. **Navigation fiable vers une semaine précise** — l'infobulle au survol
   fonctionne, mais n'a pas encore été pilotée par script (voir section
   dédiée ci-dessus).
4. Le code Celcat exact des CM (position ou `event_cat_id`, à trancher une
   fois le formulaire vu).
5. Les codes Celcat de 3 enseignants (`0` dans `celcat.yaml`) et de
   WSA501D.

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
