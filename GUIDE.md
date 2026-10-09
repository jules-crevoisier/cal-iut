# Guide d'utilisation de cal-iut

Ce guide explique comment se servir de l'application, écran par écran.
Il est pour les personnes qui consultent ou corrigent le planning :
secrétariat, responsables, enseignants.
Les tâches d'administration (comptes, Celcat, sauvegardes) sont dans [docs/ADMIN.md](docs/ADMIN.md).

**Sommaire**

1. [Se connecter](#1-se-connecter)
2. [Se repérer dans l'écran](#2-se-repérer-dans-lécran)
3. [Accueil](#3-accueil)
4. [Vue Semaine](#4-vue-semaine)
5. [Vue Enseignant](#5-vue-enseignant)
6. [Vue Promo : déplacer et placer les séances](#6-vue-promo--déplacer-et-placer-les-séances)
7. [Vue TD / TP, Vue Cours, Vue Salle](#7-vue-td--tp-vue-cours-vue-salle)
8. [Salles libres](#8-salles-libres)
9. [Partager un planning](#9-partager-un-planning)
10. [Référence](#10-référence)
11. [Contraintes](#11-contraintes)
12. [À traiter](#12-à-traiter)
13. [Tâches](#13-tâches)
14. [Rechercher, thème, compte](#14-rechercher-thème-compte)
15. [Questions fréquentes](#15-questions-fréquentes)

## 1. Se connecter

### Avec un compte

1. Ouvrir l'adresse de l'appli.
2. Saisir **Email** et **Mot de passe**, puis cliquer sur **Se connecter**.

Pas encore de compte ? Cliquer sur **Créer un compte**, puis **S'inscrire**.
Un mail de confirmation arrive : cliquer sur son lien.
L'écran **En attente d'activation** s'affiche ensuite.
Un administrateur doit vous donner un rôle.
Une fois prévenu, cliquer sur **Vérifier à nouveau**.

Mot de passe perdu ? Cliquer sur **Mot de passe oublié ?** et suivre le mail reçu.

| Rôle | Ce qu'il permet |
|---|---|
| Lecture seule | Consulter tout le planning |
| Édition | Consulter et modifier le planning, les tâches, les données à compléter |
| Admin | Tout, plus les comptes, Celcat, les sauvegardes et le trafic |
| Accès API | Aucune donnée dans l'appli : seulement créer ses clés d'accès (voir [docs/API.md](docs/API.md)) |

### Sans compte : le lien personnel

Chaque enseignant et chaque groupe d'étudiants a un **lien personnel**.
Il ouvre directement son planning, sans compte ni mot de passe, en lecture seule.
On y voit **En cours** ou **Prochain cours**, la semaine et ses heures.
Les flèches ← → changent de semaine ; la touche T revient à la semaine en cours.
Sur téléphone, la grille s'affiche jour par jour.

Deux liens publics existent aussi : **Vue Promo — accès public** et **Occupation des salles — accès public**.
Tous ces liens se trouvent dans **Référence**, onglet **Liens & partage** (voir [section 10](#10-référence)).

## 2. Se repérer dans l'écran

**À gauche**, la navigation, dans cet ordre :
**Accueil**, **Vue Semaine**, **Vue Enseignant**, **Vue Promo**, **Vue TD / TP**,
**Référence**, **Contraintes**, **À traiter**, **Tâches**.
Les administrateurs voient en plus **Comptes**, **Celcat**, **Sauvegardes**, **Trafic**.
Le bouton en bas replie la navigation en icônes seules.
En haut de la navigation, **Rechercher…** ouvre la recherche (Ctrl K).
En bas, votre nom ouvre le menu du compte.

**En haut**, la barre affiche le nom de l'écran et **la semaine affichée**.
Cette semaine est partagée : elle reste la même quand on change d'écran.

- Les flèches à gauche et à droite passent à la semaine précédente ou suivante.
- Un clic sur le nom de la semaine (« Semaine 6 ») ouvre la liste de toutes les semaines.
  Elle indique « vacances », « cette semaine » ou le nombre de séances.
- **Aujourd'hui** revient à la semaine en cours.
- « sem. 40 » rappelle le numéro de semaine du calendrier.

Le planning se met à jour tout seul quand un collègue le modifie (environ toutes les 30 secondes).
Si le serveur ne répond plus, **Hors ligne** s'affiche près de votre nom.

## 3. Accueil

L'Accueil résume la semaine affichée.

- **Chiffres en tête** : **Séances cette semaine**, **À corriger**, **Doublons cette semaine**,
  **Séances non placées**, **Tâches ouvertes**. Un clic ouvre l'écran concerné.
- **Charge de la semaine par promo** : une case par promo et par jour.
  Plus la case est foncée, plus la journée est pleine. Un clic ouvre ce jour dans la Vue Promo.
- **Séances par semaine** : un clic sur une barre change de semaine.
- **À corriger en priorité** : les points les plus graves ; **Tout voir** ouvre À traiter.
- **Tâches de l'équipe** : les tâches ouvertes, les urgentes d'abord.
- **Raccourcis** : **Déplacer des séances cette semaine**, **Placer les séances manquantes**,
  **Liens à envoyer aux enseignants**.

## 4. Vue Semaine

La Vue Semaine montre le planning d'une semaine, en lecture.
Pour déplacer une séance, utiliser la [Vue Promo](#6-vue-promo--déplacer-et-placer-les-séances).

1. Dans **Afficher par**, choisir **Groupe**, **Enseignant** ou **Salle**.
2. Choisir l'année, le parcours, puis le groupe (ou l'enseignant, ou la salle).
   Sans enseignant ni salle choisi, un annuaire s'affiche avec les chiffres de la semaine.
3. Cliquer sur une séance : son détail s'affiche à droite.

Dans le détail d'une séance :

- **Modifier dans la Vue Promo** ouvre le bon jour dans la Vue Promo.
- **Verrouiller ce créneau** fige la séance : elle ne peut plus être déplacée.

> **Attention :** l'appli n'a pas de bouton pour déverrouiller une séance.
> Ne verrouiller que ce qui est définitif.

Le panneau **Modifications et export** liste les séances déplacées à la main.
Un clic sur une ligne affiche sa semaine.
**Exporter en CSV** et **Exporter en JSON** téléchargent le planning.
Le réglage **Couleurs** choisit **Couleurs par type** (CM, TD, TP) ou **Couleurs par matière**.

Raccourcis : Maj+← et Maj+→ changent de semaine, T revient à aujourd'hui.

## 5. Vue Enseignant

Sans enseignant choisi, l'écran montre l'**annuaire** des enseignants.
On peut le filtrer (nom, code, adresse) et le trier.
Le filtre **Afficher** montre par exemple **Adresse mail manquante** ou **Contrainte non respectée**.
Le filtre **Type** garde les **Enseignants**, les **Vacataires** ou le **Type à préciser**.
Cliquer sur un nom ouvre sa **fiche**.

La fiche d'un enseignant contient :

- son nom, son code (ex. KBR), son type (**Enseignant** ou **Vacataire**), son mail et ses heures ;
- son téléphone, seulement pour les comptes qui peuvent modifier (voir [section 10](#enseignants--vacataires)) ;
- **En cours** ou **Prochain cours**, avec **Voir dans la grille** ;
- la grille de la semaine et, au-dessus, les heures de chaque semaine ;
- à droite, **Contrainte déclarée** (le texte qu'il a écrit, ses indisponibilités,
  ses absences), **Ses matières** et ses séances **Non placées** ;
- en bas, **Toutes ses interventions du semestre**, filtrables par **Matière** et **À venir seulement**.

Les boutons de partage (lien, agenda, image, mail) sont décrits en [section 9](#9-partager-un-planning).
**Retour à l'annuaire** revient à la liste.
Dans la fiche, ← et → changent de semaine, T revient à aujourd'hui.

Le bouton **Nouvel intervenant** est réservé aux administrateurs (voir [docs/ADMIN.md](docs/ADMIN.md)).

## 6. Vue Promo : déplacer et placer les séances

La Vue Promo montre toutes les promotions sur une même grille, **un jour à la fois**.
C'est ici qu'on déplace les séances (rôle Édition ou Admin).

### Se déplacer et filtrer

- Choisir le jour avec **Lun.** à **Ven.**
- Filtrer avec **Année**, **Parcours** et **Enseignant** ; **Tout afficher** retire les filtres.
  Les filtres restent mémorisés.
- En tête, quatre chiffres : **Séances cette semaine**, **À corriger**, **Non placées**, **Tâches ouvertes**.
- Chaque carte de séance montre le code, la matière, la salle et l'enseignant.

### Déplacer une séance

1. Glisser la carte vers une autre case de sa colonne.
   Pendant le glisser, les cases possibles sont encadrées (vert : libre, orange : conflit).
2. Relâcher. Si tout va bien, la séance est déplacée.
3. Un message confirme le déplacement (« WR101 déplacée : … → … »).

Pour changer de **jour**, cliquer sur le nom de la promo en tête de colonne.
Sa semaine complète s'ouvre : y glisser la séance sur le bon jour.
Pour changer de **semaine**, glisser la carte sur le ruban des semaines.
La séance attend alors dans la colonne **À placer & déplacer**, rubrique **En cours de déplacement** :
cliquer sa carte, puis une case de la grille.

### Échanger deux séances

Glisser une séance **sur** une autre séance, puis confirmer **Échanger**.
Les deux séances prennent la place l'une de l'autre.

### Changer la salle

1. Cliquer sur le nom de la salle, sur la carte.
2. Choisir une salle dans la liste (sa capacité est indiquée).

Si la salle est prise ou trop petite, un message l'explique.
**Mettre quand même cette salle** confirme le choix.
**+ Créer une salle…** ajoute une salle hors bâtiment (administrateurs).

### Modifier, retirer, supprimer une séance

Au survol d'une carte, de petits boutons apparaissent :

- le crayon **Modifier cette séance** (ou un double-clic sur la carte) :
  type, durée, enseignants, semaine, jour, créneau, salle.
  Sur une séance ajoutée à la main, aussi la matière et les groupes.
  Puis **Enregistrer**.
- **Retirer du planning** : la séance retourne dans **Séances à placer**, sans être supprimée.
- la corbeille **Supprimer cette séance** : seulement pour une séance ajoutée à la main.

### Placer les séances qui manquent

1. Cliquer sur **Séances à placer** : la colonne **À placer & déplacer** s'ouvre.
   La rubrique **Pas encore au planning** liste les séances sans créneau.
2. Commencer par **Tout placer automatiquement**.
   L'appli pose chaque séance qui a un créneau valable, les plus difficiles d'abord.
   Elle ne déplace jamais un cours déjà placé. Cela prend quelques minutes.
3. Pour celles qui restent, cliquer sur une carte.
   L'appli propose des **créneaux vérifiés** : enseignants disponibles, groupe et salle libres, règles respectées.
4. Cliquer sur **Placer ici**.

Autres possibilités sur une carte :

- **Placer sur la grille**, puis cliquer une case encadrée (« + poser ici »).
- **Choisir un autre créneau (hors suggestions)** : choisir **Semaine**, **Jour**, **Horaire**,
  puis **Placer à ce créneau**. Ce créneau n'est pas vérifié à l'avance : les conflits s'affichent avant confirmation.

Une séance marquée **Forcée, à valider** a été posée en passant outre l'ordre des séances.
Vérifier, puis **Valider ce placement** ou **Revenir en arrière (retirer du planning)**.

### Ajouter une séance ou un évènement

- **Nouvelle séance** ajoute une séance à une matière existante et la place tout de suite.
  Remplir **Matière**, **Type**, **Durée**, **Groupe(s)**, **Enseignant(s)**,
  puis **Semaine**, **Jour**, **Créneau** et **Salle** (**Automatique** par défaut).
  Cliquer **Créer et placer**, ou **Créer et en ajouter une autre**.
- L'icône calendrier **Nouvel évènement** ajoute une réunion, une conférence, une présentation…
  sans matière. **Heure de début** et **Heure de fin** sont facultatives.
  Pour la pause de midi, choisir **Pause méridienne** dans **Créneau** (12h30–14h, à ajuster) :
  l'évènement s'affiche alors entre le matin et l'après-midi, dans toutes les vues.
- Pour modifier un évènement, cliquer le crayon sur sa carte en **Vue Promo** (ou double-cliquer la carte).
  La même fenêtre s'ouvre, déjà remplie, avec **Enregistrer** et **Supprimer**.

### Annuler

Après chaque action, un message s'affiche avec **Annuler**.
**Ctrl+Z** (⌘+Z sur Mac) fait la même chose.
Seule la dernière action s'annule.

### Conflits et « Forcer »

Avant chaque déplacement, l'appli vérifie les règles.
Deux cas :

| Message | Ce qu'il veut dire | Que faire |
|---|---|---|
| **Déplacement impossible** (« Impossible (non forçable) ») | Une règle de l'IUT l'interdit | Choisir un autre créneau |
| **Forçable** | Un conflit qu'on peut accepter en connaissance de cause | **Forcer le déplacement**, ou annuler |

Toujours interdit, même en forçant : jeudi après-midi (PAC) en formation initiale,
cours classique un jour de SAE, jour férié ou fermeture, fin de semestre,
jour en entreprise d'un alternant, évènement officiel à cet horaire,
indisponibilité stricte d'un enseignant.

Forçable : salle, enseignant ou groupe déjà pris, indisponibilité déclarée d'un enseignant,
ordre des séances d'un cours, semaine déjà commencée (« Semaine 6 non modifiable »),
enseignant ou salle **déjà pris dans Celcat** (voir ci-dessous).
Toucher une date déjà passée demande une confirmation forte : **Oui, modifier le passé**.

### Occupé ailleurs dans Celcat

Un enseignant peut aussi donner cours dans un autre département, et l'amphi H.018 peut être réservé
par l'administration. L'appli le sait : le robot Celcat relit ces occupations **toutes les 2 heures**.

- Sur la grille (Vue Enseignant, Vue Salle), un bloc hachuré **Occupé ailleurs (TC)** ou
  **Réservé dans Celcat** marque le créneau. Une séance posée dessus affiche **Conflit Celcat**.
- En Vue Promo, pendant un placement, la case indique « AFR déjà occupé ailleurs (TC) ».
- Au déplacement, le message dit pourquoi, par exemple :
  « Enseignant indisponible — Anthony Froli est déjà programmé dans le département TC sur ce créneau
  (lundi 28/09, 10h00–12h30, Celcat). »
  ou « Salle indisponible — H.018 est réservée dans Celcat sur ce créneau (administration, Réunion,
  mardi 29/09, 14h00–17h00). »
- **Forcer** reste possible : la lecture de Celcat peut avoir quelques heures, une réunion a pu être annulée.
  Vérifiez dans Celcat avant de forcer.
- La génération automatique, elle, n'utilise jamais ces créneaux.
- Si la dernière lecture est ancienne, un bandeau le dit (« Occupations Celcat relevées il y a 9 h »).

### Raccourcis clavier

| Touche | Effet |
|---|---|
| ← → | Jour précédent / suivant |
| Maj+← Maj+→ | Semaine précédente / suivante |
| T | Aujourd'hui |
| Échap | Abandonner le placement en cours |
| Ctrl+Z | Annuler la dernière action |

## 7. Vue TD / TP, Vue Cours, Vue Salle

Ces écrans marchent comme la Vue Enseignant : un **annuaire** filtrable, puis une **fiche**.

- **Vue TD / TP** (dans la navigation) : le planning d'un groupe d'étudiants (ex. BUT1 · TD AB).
  La fiche indique les groupes suivis et **Toutes les séances du semestre**.
- **Vue Cours** : toutes les séances d'une matière ou d'une SAE (ex. WR101).
  La fiche montre la **Maquette** (heures prévues et placées), l'**Ordonnancement**,
  les **Intervenants**, les groupes et les salles.
  On y arrive par la recherche ou par **Référence** → **Cours** → **Ouvrir la Vue Cours**.
- **Vue Salle** : l'occupation d'une salle (ex. H.104), son équipement et les cours qui y passent.
  On y arrive par la recherche ou par **Référence** → **Salles** → **Ouvrir la Vue Salle**.
  La case **Proposée au placement automatique** se règle par un administrateur.
  Un créneau pris dans Celcat par un autre département ou l'administration s'affiche
  **Réservé dans Celcat** (voir [Occupé ailleurs dans Celcat](#occupé-ailleurs-dans-celcat)).

## 8. Salles libres

**Salles libres** montre qui occupe quelle salle, créneau par créneau, pour un jour.
On y arrive par le bouton **Salles libres par créneau** de la Vue Salle, ou par la recherche.

- Choisir le **Jour**.
- Filtrer par **Capacité minimum** et **Type de salle**.
- **Inclure les salles hors placement automatique** ajoute les salles réservées à un usage précis.

Une salle réservée dans Celcat (autre département, administration) apparaît occupée (**Celcat**) :
elle n'est pas proposée, ni ici, ni au placement automatique.

## 9. Partager un planning

Dans la fiche d'un enseignant ou d'un groupe, en haut à droite :

| Bouton | Effet |
|---|---|
| **Partager** | Copier l'image de la semaine, l'envoyer par mail ou la télécharger (PNG) |
| **Imprimer** | Imprimer la semaine, sans les boutons |
| **Lien agenda** | Copier l'adresse à coller dans Google Agenda, Apple Calendrier ou Outlook |
| **Écrire un mail** | Préparer un mail à l'enseignant avec son lien |
| **Copier son lien** | Copier le lien personnel, à envoyer tel quel |

L'agenda abonné se met à jour tout seul quand le planning change.
Sur un lien personnel, le bouton s'appelle **Ajouter à mon agenda**.
Détails : [docs/ICS.md](docs/ICS.md).

## 10. Référence

**Référence** regroupe les données de base, en sept onglets :

- **Salles** : capacité, type, équipement, nombre de séances. Tableau filtrable et triable.
- **Cours** : toutes les matières de la maquette, filtrables par parcours et semestre.
- **Codes Celcat** : le code Celcat de chaque cours, salle, enseignant et groupe, et son **Origine**.
  Les filtres **Sans code**, **Sans code (voulu)**, **Saisis dans l’appli**, **Tous** aident à trier.
  Un code « manquant » en rouge bloque l'envoi des séances concernées vers Celcat.
  Pour les autres rôles, cet onglet est en lecture seule ;
  la saisie par les administrateurs est expliquée dans [docs/ADMIN.md](docs/ADMIN.md).
- **Calendrier** : vacances, jours fériés, rentrées et évènements, avec le délai (« dans 3 semaines »).
- **Enseignants & vacataires** : tous les enseignants et vacataires, avec leurs coordonnées
  (voir [ci-dessous](#enseignants--vacataires)).
- **Liens & partage** : les deux liens publics, puis le lien personnel et le **Lien agenda**
  de chaque enseignant et groupe. Boutons **Copier**, **Copier tous les liens**, **Annuaire (.csv)**.
  **Envoyer les liens par mail…** est réservé aux administrateurs.
- **Notifications** : les mails envoyés quand le planning change (réglage par un administrateur).

### Enseignants & vacataires

Cet onglet liste toutes les personnes qui enseignent dans l'outil.
Pour chacune : **Type**, **Prénom**, **Nom**, **Diminutif** (ex. KBR), **Code Celcat**,
**E-mail**, **Téléphone**, nombre de **Séances**, et **Voir la fiche**.

Ce sont les mêmes données que l'annuaire de la Vue Enseignant, la fiche,
**Liens & partage** et « Nouvelle séance ». Une correction faite ici se voit partout.

En haut, des compteurs : **Enseignants**, **Vacataires**, **À préciser**, **Sans mail**, **Sans téléphone**.
Cliquer sur un compteur filtre la liste. Cliquer de nouveau retire le filtre.

Trouver une personne :

1. Taper un nom, un prénom, un diminutif ou une adresse dans le champ de recherche.
2. Choisir au besoin **Tous**, **Enseignants**, **Vacataires** ou **À préciser**.
3. Cliquer sur un en-tête de colonne pour trier. Le tri est gardé sur cet ordinateur.

Modifier une information (comptes « édition » et administrateurs) :

1. Survoler la cellule, puis cliquer sur le crayon (ou **Ajouter** si elle est vide).
2. Saisir la nouvelle valeur. Pour le **Type**, choisir **Enseignant**, **Vacataire** ou **À préciser**.
3. Appuyer sur **Entrée** pour enregistrer, ou **Échap** pour annuler.
4. « Enregistré » s'affiche. En cas d'erreur, le message apparaît sous le champ.

À savoir :

- Le **Diminutif** ne se modifie pas : c'est l'identifiant de la personne partout dans l'outil.
- Le **Téléphone** accepte « 06 12 34 56 78 », « 06.12.34.56.78 » ou « +33 6 12 34 56 78 ».
  Un numéro étranger s'écrit avec « + » et l'indicatif. Vider le champ retire le numéro.
- Le **Nom** est rangé en capitales. Le nom affiché partout devient alors « Prénom NOM ».
- Une valeur corrigée porte la marque **modifiée**. Sa bulle propose **Revenir à la valeur du fichier**.
- Le **Code Celcat** se saisit seulement par un administrateur, comme dans **Codes Celcat**.
  S'il manque, le lien **Codes Celcat →** ouvre la bonne ligne.
- **Annuaire (.csv)** télécharge les lignes affichées. Le téléphone n'y est que pour les comptes qui le voient.
- **Nouvel intervenant** (administrateurs) ajoute une personne, avec son téléphone et son type.

> **Données personnelles :** en lecture seule, le téléphone est masqué (« — »).
> Il n'apparaît jamais sur un lien public ni dans l'API. Voir [docs/ADMIN.md](docs/ADMIN.md).

## 11. Contraintes

**Contraintes** montre chaque règle et son verdict sur le planning actuel.

- En tête : **Règles en échec**, **Indisponibilités non respectées**,
  **Compromis SAE acceptés**, **Contraintes déclarées**. Un clic filtre la liste.
- **Règles globales du solveur** : les règles en échec d'abord.
- **Contraintes enseignants** : le texte déclaré par chaque enseignant et son verdict
  (**Respectée**, **Indisponibilité non respectée**, **Compromis SAE**).
  Cliquer sur un nom ouvre sa Vue Enseignant.

## 12. À traiter

**À traiter** liste ce qui demande une décision. Le nombre rouge dans la navigation compte les points **À corriger**.

Les catégories, de la plus grave à la moins grave :

| Catégorie | Où corriger |
|---|---|
| Séances non placées | Vue Promo, **Séances à placer** |
| Séances sans salle | Vue Promo |
| Doublons salle / enseignant (H.201/H.203 et H.007/H.008 comptent pour une salle) | Vue Promo |
| Conflits Celcat (salle / enseignant) : la salle ou l'enseignant d'une séance placée est déjà pris dans Celcat (autre département, réunion, réservation). La ligne porte l'étiquette **Celcat**, nomme la salle ou l'enseignant, et dit ce qui l'occupe dans Celcat avec l'horaire | Vue Enseignant ou Vue Promo |
| Règles globales en échec | Contraintes |
| Indisponibilités enseignant non respectées | Vue Enseignant |
| Cours de SAE hors journée SAE | Vue Promo |
| Encadrement SAE le même jour (compromis accepté, à revoir si possible) | Vue Enseignant |
| Journées trouées (au moins deux créneaux vides entre deux cours) | Vue TD / TP |

- Cliquer sur une ligne ouvre le bon écran, au bon jour.
- Filtrer par parcours, semaine, enseignant et **Gravité** (**À corriger** ou **À revoir**).
- **Tout déplier** / **Tout replier** ouvre ou ferme les sections.
- Pour les doublons, **Vérifier maintenant** relance le contrôle.

### Données à compléter

La section **Données à compléter** liste les informations absentes :
mail ou nom d'un enseignant, type d'une salle, intitulé d'une matière, code Celcat.

1. Cliquer sur **Ajouter** à côté de la donnée manquante.
2. Saisir la valeur, puis **Entrée** pour enregistrer (**Échap** pour annuler).

Pour corriger une valeur fausse, passer la souris dessus : un crayon **Modifier** apparaît.
La valeur corrigée porte la marque **modifiée**.
La bulle de cette marque propose **Revenir à la valeur du fichier**.
Une adresse déjà utilisée par un autre enseignant est refusée.
Les codes Celcat sont réservés aux administrateurs ; les autres rôles voient le manque sans bouton.

## 13. Tâches

**Tâches** est le tableau de suivi de l'équipe, en trois colonnes : **À faire**, **En cours**, **Fait**.
Deux onglets séparent **Emploi du temps** et **Plateforme**.

- **Ajouter une tâche…** en bas d'une colonne crée une tâche rapide (touche N).
- **Nouvelle tâche** ouvre le formulaire complet : titre, description, catégorie,
  pour qui, enseignant, dates, **Urgent**.
- Glisser une carte d'une colonne à l'autre, ou utiliser ses flèches.
- Cliquer sur le titre d'une carte pour la modifier.
- Filtrer par **Pour qui** ou avec le champ de recherche (touche /).

### Joindre des images

Une tâche peut porter jusqu'à 10 images (capture de Celcat, photo d'une affiche…).

- **Coller une capture** : ouvrir la tâche, puis Ctrl+V (⌘+V sur Mac).
- **Glisser-déposer** des fichiers sur la fenêtre de la tâche, ou **Ajouter une image**.
- **Voir** : cliquer sur une vignette. ← → passent d'une image à l'autre, Échap ferme.
  **Original** ouvre l'image dans un onglet.
- **Retirer** : la croix de la vignette, puis **Retirer**.

Sur une tâche existante, chaque image est enregistrée tout de suite (**Annuler** ne la retire pas).
Sur une nouvelle tâche, les images partent au clic sur **Créer**.
Formats acceptés : PNG, JPEG, WebP, GIF (SVG refusé).
Limites : 8 Mo par image, 40 Mo par tâche.
La position GPS et les autres informations cachées d'une photo sont retirées.
Voir les images demande l'accès à l'onglet Tâches ; en ajouter demande le rôle Édition ou Admin.

## 14. Rechercher, thème, compte

**Rechercher** : Ctrl K (⌘K sur Mac), ou **Rechercher…** en haut de la navigation.
Taper un enseignant, un cours, une salle, un groupe, une promo ou un écran.
↑ ↓ pour choisir, Entrée pour ouvrir, Échap pour fermer.
Les derniers résultats ouverts restent proposés.

**Menu du compte** (votre nom, en bas de la navigation) :

- **Clé API** : créer une clé pour un script ou pour Claude.
  La clé s'affiche une seule fois : la copier aussitôt. 5 clés actives au plus.
  Détails : [docs/API.md](docs/API.md) et [docs/MCP.md](docs/MCP.md).
- **Thème** : **Système**, **Clair** ou **Sombre**.
- **Déconnexion**.

Au premier passage, l'appli demande l'affichage préféré :
**Une couleur par matière** ou **Une couleur par type de séance**.

## 15. Questions fréquentes

**Pourquoi mon déplacement est-il refusé ?**
Le message dit pourquoi. « Impossible (non forçable) » : une règle de l'IUT l'interdit
(PAC, férié…), il faut un autre créneau. Sinon, **Forcer le déplacement** est possible.
Un créneau réservé à une SAE affiche « ⚠ Semaine de SAE » (ou « Journée de SAE ») :
**Forcer le placement** y pose quand même la séance. La génération automatique, elle,
n'y place jamais de cours classique.
Voir [Conflits et « Forcer »](#conflits-et--forcer-).

**On me demande de forcer alors que le créneau semble libre.**
La semaine est sans doute déjà commencée (« Semaine 6 non modifiable »).
Forcer si le changement est bien voulu.

**Je me suis trompé de matière en ajoutant une séance.**
Dans la Vue Promo, ouvrir la séance avec le crayon **Modifier cette séance** (ou un double-clic).
Changer **Matière**, puis **Enregistrer**.
La matière ne se change que sur une séance ajoutée à la main, pas sur une séance de la maquette.

**J'ai déplacé une séance par erreur.**
Cliquer **Annuler** dans le message, ou Ctrl+Z, tout de suite.

**Je ne trouve pas une séance.**
Regarder dans **Séances à placer** (Vue Promo) ou dans **À traiter** → **Séances non placées**.

**Une séance refuse de bouger : « Séance verrouillée ».**
Elle a été verrouillée (bouton **Verrouiller ce créneau** de la Vue Semaine).
L'appli n'a aucun bouton pour la déverrouiller, même pour un administrateur :
signaler le cas à l'équipe technique.

**Un enseignant ne reçoit pas son lien.**
Son adresse manque sans doute : l'ajouter dans son annuaire ou dans **À traiter** → **Données à compléter**.

**Comment un enseignant doit-il écrire ses contraintes ?**
Dans le tableau des contraintes, ces formulations sont bien comprises :
« vendredi après-midi », « lundi toute la journée », « jeudi 12 novembre 2026 »,
« du lundi 2 au vendredi 6 novembre 2026 », « les jeudis après 17h00 », « mardi de 15h30 à 18h30 ».
Écrire le mois en lettres. Séparer deux idées par « - ».
« Si possible » ou « idéalement » ne contraint rien : pour un vrai interdit, écrire une indisponibilité.

**Le planning ne se met pas à jour.**
Si **Hors ligne** s'affiche, le serveur ne répond pas : l'appli réessaie seule.
Sinon, recharger la page.
