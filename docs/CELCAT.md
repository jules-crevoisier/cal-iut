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

La création passe par le bouton **+** en haut à droite du panneau. Il reste à
le relever — voir plus bas.

## Où en est l'outil

Acquis :

- accès réseau (direct ou VPN), sur poste comme sur serveur ;
- connexion, choix de la base et du rôle ;
- lecture fiable des ressources, et recherche par nom ;
- correspondance des salles vérifiée, convention des groupes établie.

Manquant :

1. **Le nom Celcat de l'amphi MMI** — bloque les CM.
2. **Le formulaire de création d'une séance**, derrière le bouton **+**.
   L'inspecteur d'événement a été relevé, pas le formulaire lui-même :
   il n'a pas été ouvert de nuit, sans surveillance, sur une base qui
   contient déjà des séances réelles. `URCA_FORMATION` ne peut pas servir
   de répétition — elle ne contient AUCUN groupe MMI (vérifié).
3. **Le code Celcat des CM** (`types_seance`), toujours à confirmer : les
   `.bat` d'origine ne montraient que TD=4 et TP=6.
4. Les codes Celcat de 3 enseignants (`0` dans `celcat.yaml`) et de
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
