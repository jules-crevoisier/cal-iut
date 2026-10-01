# Guide de l'administrateur

Ce document explique comment administrer l'appli : comptes, clés API, codes Celcat, trafic, sauvegardes, déploiement.
Il est pour les personnes qui ont le rôle **Admin**.
Pour l'usage courant du planning, voir [GUIDE.md](../GUIDE.md).

**Sommaire**

1. [Les rôles : qui voit quoi](#1-les-rôles--qui-voit-quoi)
2. [Gérer les comptes](#2-gérer-les-comptes)
3. [Les clés API](#3-les-clés-api)
4. [Les codes Celcat](#4-les-codes-celcat)
5. [Ajouter un intervenant](#5-ajouter-un-intervenant)
6. [Compléter ou corriger une donnée](#6-compléter-ou-corriger-une-donnée)
7. [Liens par mail, notifications, salles : les autres gestes admin](#7-liens-par-mail-notifications-salles--les-autres-gestes-admin)
8. [Surveiller le trafic et bloquer un client](#8-surveiller-le-trafic-et-bloquer-un-client)
9. [Les sauvegardes](#9-les-sauvegardes)
10. [Lisser le planning d'une promo](#10-lisser-le-planning-dune-promo)
11. [Envoyer le planning local vers la production](#11-envoyer-le-planning-local-vers-la-production)
12. [Déployer](#12-déployer)
13. [En cas de problème](#13-en-cas-de-problème)
14. [Pour les techniciens](#14-pour-les-techniciens)

L'écran **Celcat** (envoi du planning dans Celcat) a son propre document : [docs/CELCAT.md](CELCAT.md).
Son bouton **Corriger** ne supprime jamais rien dans Celcat.
Sa section **Occupations hors MMI** montre ce que Celcat contient d'autre sur nos salles et nos enseignants
(autre département, administration) : ces créneaux sont interdits à la génération et signalés au placement
([CELCAT.md § 6](CELCAT.md#6-occupations-hors-mmi)). **Relire maintenant** demande une relecture au robot.
Ce qui reste à vérifier sur le vrai Celcat : [A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md).

---

## 1. Les rôles : qui voit quoi

Chaque compte a un seul rôle. Un admin le choisit à l'activation (écran **Comptes**).

| Rôle | Voit le planning | Modifie le planning | Menu **Administration** | Ses clés API |
|---|---|---|---|---|
| **Lecture seule** | Oui | Non | Non | Lecture |
| **Édition** | Oui | Oui | Non | Droits Édition (MCP compris) |
| **Admin** | Oui | Oui | Oui | Droits Admin |
| **Accès API** | **Non**, aucune donnée | Non | Non | Lecture de `/api/v1/` seulement |

- **Lecture seule** consulte tout : planning, Référence, Contraintes, À traiter, Tâches.
- **Édition** peut aussi déplacer et placer des séances, gérer les tâches, compléter ou corriger un mail, un nom, un intitulé.
  Elle voit et modifie aussi le prénom, le nom, le téléphone et le type (enseignant ou vacataire) d'un enseignant.
- **Admin** a en plus **Comptes**, **Celcat**, **Sauvegardes** et **Trafic**.
  Lui seul saisit les codes Celcat, ajoute un intervenant, bloque un client, lance un lissage.
  Lui seul envoie les liens par mail, règle les notifications, crée une salle, ouvre la page historique `/legacy` ([§ 7](#7-liens-par-mail-notifications-salles--les-autres-gestes-admin)).
- **Accès API** n'a qu'une page, **Accès API**, pour créer et révoquer ses clés. Ni MCP, ni écriture.

> **À savoir :** un changement de rôle ou une désactivation prend effet à la requête suivante de la personne.
> Pas besoin qu'elle se reconnecte.

---

## 2. Gérer les comptes

Une personne crée son compte elle-même (**Créer un compte** sur l'écran de connexion).
Elle confirme son adresse par le lien reçu par mail (valable 48 h).
Elle attend ensuite qu'un admin l'active.

### Activer une demande

1. Ouvrir **Administration → Comptes**.
2. La tuile **En attente d'activation** donne le nombre de demandes. Cliquer sur **Traiter**.
3. Sur la ligne de la personne, cliquer sur **Activer en lecture seule**, **Activer en édition** ou **Activer en accès API**.

Le message « … activé en lecture seule. » s'affiche. La personne peut se connecter.

### Faire de quelqu'un un admin

Il n'y a pas de bouton « Activer en admin ».

1. Activer d'abord la personne (en lecture seule par exemple).
2. Dans le tableau des comptes, colonne **Rôle**, choisir **Admin** dans la liste.

### Changer un rôle

1. **Administration → Comptes**.
2. Trouver le compte (champ **Rechercher une adresse**, ou les filtres **Tous / Actifs / Désactivés / Email non confirmé**).
3. Choisir le nouveau rôle dans la colonne **Rôle**.

### Désactiver ou réactiver un compte

1. Sur la ligne du compte, cliquer sur **Désactiver**.
2. Le message « … désactivé : il ne peut plus se connecter. » propose **Annuler** en cas d'erreur.

La personne ne peut plus se connecter. Ses clés API cessent aussi de fonctionner.
Pour revenir en arrière : filtre **Désactivés**, puis **Réactiver**.

### Supprimer une demande

**Supprimer** n'existe que pour un compte jamais activé (en attente ou email non confirmé).
Un compte déjà utilisé se **désactive**, il ne se supprime pas : il a pu créer des tâches ou des modifications.

> **À savoir :**
> - Deux adresses deviennent admin toutes seules à la confirmation de leur mail : `crevoisier.ju@gmail.com` et `kyllian.bresson@univ-reims.fr`.
>   C'est ce qui permet d'avoir un premier admin.
> - Impossible de retirer le dernier admin actif : l'appli refuse.
> - Une session dure 30 jours. Un changement de mot de passe (lien « Mot de passe oublié ? », valable 1 h) ferme toutes les anciennes sessions.
>   Pour couper l'accès de quelqu'un tout de suite : **Désactiver**.
> - Les tentatives de connexion sont limitées (10 essais en 15 min par adresse). Les mails d'inscription et de mot de passe oublié aussi (3 par heure et par adresse).

---

## 3. Les clés API

Une clé permet à un script ou à une application de lire le planning sans mot de passe.
Elle commence par `caliut_`.

### Qui peut créer une clé ?

**Tout compte actif**, pour lui-même. Chacun ne voit que ses propres clés.

- Compte **Lecture seule / Édition / Admin** : menu du compte (en bas de la barre latérale, votre adresse) → **Clé API**.
  La clé a les droits du compte : une clé d'un compte Édition peut modifier le planning (MCP, `cal-iut prod push`).
- Compte **Accès API** : sa seule page, **Accès API**. La clé ne lit que l'API v1.

### Créer une clé

1. Ouvrir la page des clés (voir ci-dessus).
2. Donner un nom (facultatif) : « écran du hall », « script prod »…
3. Cliquer sur **Générer une clé**.
4. Cliquer sur **Copier la clé** tout de suite. Elle ne sera **plus jamais affichée**.

### Révoquer une clé

Cliquer sur **Révoquer** sur la ligne de la clé, puis confirmer. La clé cesse de marcher aussitôt.
La colonne **Dernière utilisation** aide à repérer une clé oubliée.

### Donner un accès à un développeur externe

1. Lui demander de créer un compte (**Créer un compte**).
2. L'activer avec **Activer en accès API**.
3. Il crée lui-même ses clés et lit la documentation : [docs/API.md](API.md).

Il ne voit aucune donnée dans l'appli, ne peut rien modifier et n'accède pas au MCP.

> **Limites :** 5 clés actives au plus par compte (en révoquer une pour en créer une autre).
> Une clé ne peut pas gérer les clés : cela se fait dans l'appli, connecté.

---

## 4. Les codes Celcat

Pour recopier une séance dans Celcat, l'appli doit connaître le code Celcat du cours, de la salle, de l'enseignant et du groupe.
Tout est dans **Référence → Codes Celcat**.

### Lire la liste

Quatre sous-onglets : **Cours**, **Salles**, **Enseignants**, **Groupes**.
Chaque ligne donne le nombre de séances placées, le code qui partira, et son **origine** :

| Origine | Sens | Modifiable dans l'appli ? |
|---|---|---|
| **Fichier de config** | Écrit dans `data/config/celcat.yaml` | Non (cadenas, « verrouillé ») |
| **Maquette** (ou « corrigé M→C ») | Repris de la maquette officielle | Non (cadenas) |
| **saisi dans l'appli** | Saisi par un admin (date, et auteur pour un admin) | Oui |
| **manquant** (rouge : « manquant — bloque Celcat ») | Pas de code : ces séances ne partent pas vers Celcat | Oui : à saisir |
| **sans code (voulu)** | Ne doit jamais aller dans Celcat, avec un motif | Retirer possible |
| **envoi sans module (règle)** | Cours sans matière Celcat qui part quand même, catégorie imposée (WR100BU) | Non : `celcat.yaml` |

Filtre en haut : **Sans code / Sans code (voulu) / Saisis dans l'appli / Tous**.
La pastille d'un sous-onglet compte ses lignes sans code.

### Saisir un code manquant

1. **Référence → Codes Celcat**, sous-onglet voulu, filtre **Sans code**.
2. Sur la ligne, cliquer sur **Saisir**.
3. Taper le code. Les codes relevés dans Celcat sont proposés sous le champ.
4. **Entrée** pour enregistrer (**Échap** pour annuler).

Le message « … : WR101 enregistré pour Celcat. » s'affiche.
Le code part au **prochain envoi vers Celcat**, sans déploiement.
Pour corriger : le crayon. Pour retirer : **Revenir à manquant**.

Format attendu :

- **cours** : un code module `TSB…` déjà relevé dans Celcat (ex. `TSBZ1M01`) ;
- **salle** : le nom Celcat, avec le point (« H.104 », « Amphi 3 MMI ») ;
- **enseignant** : un nombre (« 0 » ne compte pas).

Refusé, avec un message sous le champ :

- un code déjà connu (fichier, maquette) : « code déjà connu » ;
- un format inattendu ;
- un code déjà porté par un autre cours, une autre salle ou un autre enseignant.
  Seule exception : une salle réunie (H.007-008) peut porter le code d'une de ses moitiés (H.007).

### Marquer « sans code (voulu) »

Pour une entité qui ne doit jamais aller dans Celcat (projets encadrés WS1PJ…, lignes administratives COR, PCA…).

1. Sur la ligne, cliquer sur **Sans code (voulu)…**.
2. Écrire le motif (obligatoire, quelques mots).
3. Cliquer sur **Marquer**.

La ligne ne compte plus comme manquante. Ses séances ne sont **pas envoyées** à Celcat, sans bloquer le reste.
Pour annuler : **Retirer « sans code »**.
Celles décidées avec Kyllian sont écrites dans `celcat.yaml` (section `sans_code_voulu`) : elles portent « se retire dans celcat.yaml ».

### Les règles d'envoi (WR100BU, PTUT)

Certaines séances partent dans Celcat avec une catégorie, une remarque et un département imposés.

- **WR100BU** (visite de la BU, code inventé) : les interventions de Valérie Mariot partent en catégorie **TD0**
  (pondération 0), remarque **WR100BU**, département **T_MMI T29**, **sans matière**.
- **Toute séance PTUT** : catégorie **Projet** (pondération 0), remarque **PTUT**, avec la matière du cours si son code est connu.

> **À savoir :** ces règles sont **inactives** tant que la variable `CAL_IUT_REGLES_ENVOI` ne vaut pas `on`
> (services backend et celcat-nuit). Inactives, ces séances ne partent pas et ne bloquent rien.
> L'écran **Celcat → Réglages** affiche « Règles d'envoi : inactives / actives ».
> Codes Celcat affiche alors « règle d'envoi (inactive) ».

Dans **Codes Celcat**, WR100BU affiche « sans module » et l'origine **envoi sans module (règle)**, avec ce qui part.
Rien ne s'y saisit : les règles sont dans `celcat.yaml` (section `regles_envoi`, voir [DATA.md](DATA.md#envoyer-avec-une-règle-denvoi)).
Une séance WR100BU d'un autre enseignant n'est pas envoyée, sans rien bloquer (motif dans le plan Celcat, `GET /celcat/plan`).
Détails : [docs/CELCAT.md § 5](CELCAT.md#5-règles-denvoi--wr100bu-et-ptut).
Ce qui reste à essayer avec le VPN : [docs/A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md).

### Les groupes : lecture seule

Celcat désigne un groupe par un identifiant interne, qu'on ne lit pas dans Celcat.
Il se règle dans `data/config/celcat_groupes.yaml`, puis on redéploie.
Un identifiant faux crée des doublons dans Celcat : ne jamais le deviner.

### Cas particuliers

- **Codes de la maquette.** Pour un cours sans code dans `celcat.yaml`, le code de la maquette est repris s'il existe dans le relevé des matières Celcat.
  Pour les cours CREACOM dont la maquette écrit le code en **M** alors que Celcat le connaît en **C** (WRA401M…), la variante en C est reprise : origine « corrigé M→C » (règle donnée par Kyllian).
- **Codes à confirmer.** Les cours de `celcat.yaml` → `codes_a_confirmer` (WS103, WS104, WS105) restent **manquants**.
  Le code de la maquette est proposé, avec la raison. Le saisir une fois confirmé.
- **Code de la maquette douteux.** Quand le nom relevé dans Celcat désigne un autre cours (WSA611C → « WSA612C Alternance »), le code n'est pas repris. Même traitement.
- **Ancienne saisie sur un code désormais connu.** Elle reste appliquée, signalée en orange. **Revenir au code connu** la retire.
- **Nouvelle maquette.** Les codes de la maquette sont figés dans `data/config/celcat_modules_maquette.yaml`.
  Pour les recalculer : `python scripts/generer_codes_maquette.py`, puis relire les différences (ces codes servent aussi à la paie).

On arrive aussi sur la bonne ligne depuis **À traiter → Données à compléter** (bouton **Codes Celcat**) et depuis l'écran **Celcat** (**Codes Celcat →**, **Voir dans Codes Celcat →** sur un blocage).

---

## 5. Ajouter un intervenant

Pour un vacataire que la feuille des contraintes ne connaît pas encore. Sans cela, on ne peut pas lui créer de séance.

1. Ouvrir **Vue Enseignant**, **Référence → Enseignants & vacataires**, ou **Référence → Codes Celcat → Enseignants**.
2. Cliquer sur **Nouvel intervenant**.
3. Remplir :
   - **Nom complet** (« Prénom Nom », obligatoire) ;
   - **Code** (2 à 4 lettres, le trigramme du planning, obligatoire ; un code libre est proposé) ;
   - **Code Celcat (facultatif)** : le nombre affiché dans Celcat ;
   - **Mail (facultatif)** : pour lui envoyer son lien personnel ;
   - **Téléphone (facultatif)** : « 06 12 34 56 78 » ou « +33 6 12 34 56 78 » ;
   - **Type** : **Enseignant**, **Vacataire** ou **À préciser**.
4. Lire l'encadré **À corriger avant de créer** / **À vérifier avant de créer**, puis cliquer sur **Créer**.

Sa fiche s'ouvre (« Intervenant créé »). Il apparaît partout : annuaire, **Nouvelle séance**, filtres, Codes Celcat, API.

**Les garde-fous** (vérifiés pendant la saisie) :

| Situation | Ce que fait l'appli |
|---|---|
| Code déjà pris par un enseignant connu | Refusé, avec **Voir sa fiche** |
| Mail déjà attribué à un autre enseignant | Refusé |
| Code que `celcat.yaml` donne à une autre personne (ex. AGR) | Avertissement (1). **Créer quand même** si c'est voulu. |
| Code Celcat déjà porté par un autre enseignant (ex. 3233 = AGT) | À corriger. **Voir sa fiche** ou **Retirer le code Celcat** |
| Nom proche d'une personne connue | Avertissement (2). **Créer quand même** si ce n'est pas elle. |

(1) Sous ce code, il partirait dans Celcat, et en paie, sous l'identité de cette autre personne.
(2) « Cette personne existe peut-être déjà sous le code X ». Accents, majuscules et ordre prénom/nom sont ignorés.

Sa fiche porte **ajouté dans l'appli**. Tant qu'il n'a **aucune séance**, un bouton **Supprimer** le retire.
Il survit aux déploiements. Quand la feuille officielle le connaîtra, son nom officiel prendra le dessus.

---

## 6. Compléter ou corriger une donnée

Un mail, un nom d'enseignant ou un intitulé de cours se corrige dans l'appli, sans toucher aux fichiers.
Rôle **Édition** ou **Admin**.

- **Il manque** : la pastille devient **Ajouter**. Saisir, puis **Entrée** (**Échap** pour annuler).
- **C'est faux** : passer la souris sur la valeur. Un crayon **Modifier** apparaît. Même champ.
- La valeur corrigée passe devant celle du fichier et porte la marque **modifiée**.
  Au survol de la marque : la valeur du fichier et le bouton **Revenir à la valeur du fichier**.

Où : annuaire des enseignants, fiche d'un enseignant, fiche d'une salle (bloc **À compléter**),
**Référence → Enseignants & vacataires**, **Référence → Liens & partage**, **À traiter → Données à compléter**.
Une adresse déjà attribuée à un autre enseignant est refusée.
La correspondance Celcat (salle, enseignant, code module d'un cours) reste réservée aux admins : voir [§ 4](#4-les-codes-celcat).
En lecture seule, le manque et la marque restent affichés, sans bouton.

Ce qui est saisi est gardé dans le volume (`data/state/references.json`) et survit aux déploiements.
L'appli garde qui l'a saisi, quand, et la valeur remplacée.

### Enseignants & vacataires : qui fait quoi

L'onglet **Référence → Enseignants & vacataires** réunit tout ce qui décrit une personne.

| Information | Qui la voit | Qui la modifie |
|---|---|---|
| Prénom, Nom, Type, E-mail | Tous les comptes | **Édition** et **Admin** |
| Téléphone | **Édition** et **Admin** seulement | **Édition** et **Admin** |
| Code Celcat | Tous les comptes | **Admin** (comme dans **Codes Celcat**) |
| Diminutif (ex. KBR) | Tous les comptes | Personne : c'est l'identifiant |

Aucun fichier ne donne le type ni le téléphone. Au départ, tout le monde est donc « à préciser ».
Il suffit de les saisir une fois dans l'onglet.

### Données personnelles : le téléphone

Le téléphone est plus sensible que le mail. Il est protégé ainsi :

- **Lecture seule** : le téléphone est masqué (« — »). Le serveur ne l'envoie pas.
- **Lien public** (lien personnel, Vue Promo publique) : jamais de téléphone, ni de type.
- **Accès API** : rien, ni par l'appli ni par une clé.
- **API v1** (`/api/v1/enseignants`) : jamais de téléphone. Le type y est, pour un compte connecté.
- **Annuaire (.csv)** : la colonne **Téléphone** n'existe que pour les comptes qui le voient.

Le numéro est gardé dans `data/state/references.json`, avec qui l'a saisi et quand.
Vider le champ le retire. La sauvegarde du volume dans Dokploy le contient : la protéger comme le reste.

---

## 7. Liens par mail, notifications, salles : les autres gestes admin

Ces gestes sont réservés aux admins. Un autre compte peut voir certains boutons, mais l'action est refusée.

### Envoyer leur lien personnel aux enseignants

1. Ouvrir **Référence → Liens & partage**.
2. Cliquer sur **Envoyer les liens par mail…**.
3. Dans la fenêtre **Envoyer le lien personnel par mail**, cocher les enseignants (champ **Filtrer…** pour chercher).
4. Cliquer sur **Envoyer à N enseignants**.

Un enseignant sans adresse ne peut pas être coché : compléter d'abord son mail ([§ 6](#6-compléter-ou-corriger-une-donnée)).
L'envoi demande `RESEND_API_KEY`, `RESEND_FROM` et `CAL_IUT_PUBLIC_URL` ([§ 12](#12-déployer)).

### Régler les notifications par mail

**Référence → Notifications** (carte **Notifications par mail**). Rien n'est actif par défaut.

1. **Destinataires** : une ou plusieurs adresses, séparées par une virgule ou un retour à la ligne. Puis **Enregistrer les destinataires**.
2. **Ce qui déclenche un mail** : cocher les évènements voulus.
3. **Regrouper les modifications pendant** : aucun regroupement, 5 minutes, 15 minutes ou 1 heure.
4. **Envoyer un mail de test** pour vérifier.

### Créer une salle

Pour une salle hors du bâtiment (autre site, salle empruntée…).

1. Dans la **Vue Promo**, ouvrir le choix de salle d'une séance.
2. Choisir **+ Créer une salle…**.
3. Remplir la fenêtre **Nouvelle salle**, puis **Créer et utiliser**.

La case **Proposée au placement automatique** dit si l'appli peut la choisir toute seule.

### Retirer une salle du placement automatique

Sur la fiche de la salle, décocher **Proposée au placement automatique**.
La salle reste choisissable à la main. Exemple : la BU, réservée à un seul module.

### La page historique `/legacy`

L'ancienne page de l'appli (mêmes données, autre présentation). Admins seulement : elle montre les mails et les contraintes des enseignants.

---

## 8. Surveiller le trafic et bloquer un client

Écran **Administration → Trafic**. Il sert à repérer un robot qui interroge le serveur en boucle, et à le bloquer.

### Lire l'écran

- En haut : **Protections toujours actives** (normalement « Actives ») et **Limitation de débit** (normalement « Désactivée »).
- Choisir la période : **15 min**, **1 h** ou **24 h**.
- Les tuiles : nombre de requêtes, clients distincts, **Refus 401/403**, **IP bloquées**.
- Le tableau des clients : une ligne par adresse IP, du plus gros au plus petit.
  Colonnes **Public** (part des requêtes sans compte), **User-Agent** (le logiciel qui appelle), **Chemins**, **Refus**.

Un robot se reconnaît : beaucoup de requêtes, souvent la nuit, un User-Agent vide ou de script (`python-requests`, `curl`…), beaucoup de refus.

### Bloquer

1. Sur la ligne du client, cliquer sur **Bloquer…** (ou **Bloquer une adresse…** en haut).
2. Choisir quoi bloquer : **Adresse IP**, **Plage d'adresses** ou **User-Agent**.
3. Choisir la **Durée** : **1 h**, **24 h**, **7 jours** ou **Permanent**.
4. Écrire le motif (ex. « aspire /app-state toutes les 10 s »), puis **Bloquer**.

Le client reçoit aussitôt un refus sur tout. Il apparaît dans la carte **Blocages**.
Si le blocage vous viserait vous-même, l'appli demande de confirmer (**Bloquer quand même**).

> **Attention :** bloquer l'IP de l'IUT ou d'un opérateur mobile coupe tout le monde derrière.
> Préférer une durée courte, ou un User-Agent reconnaissable.

### Débloquer

Dans la carte **Blocages**, cliquer sur **Débloquer**. Effet immédiat.

### Le bannissement automatique

Actif par défaut. Une adresse **sans compte** qui reçoit **30 refus (401/403) en 10 minutes** est bloquée **24 h**.
Elle apparaît dans **Blocages** avec la mention « auto · refus 401/403 ». Elle se débloque comme les autres.
Il ne vise jamais un compte connecté ni une clé API valide.

### En ligne de commande

Mettre dans `.env` l'adresse de la production (`CAL_IUT_PROD_URL`) et une clé d'un compte **admin** (`CAL_IUT_PROD_API_KEY`).

```bash
cal-iut trafic --prod                    # plus gros clients (--fenetre 15min|1h|24h)
cal-iut bloquer 203.0.113.66 --motif "aspire /app-state" --duree 7j --prod
cal-iut bloquer --ua "python-requests" --motif "robot" --duree permanent --prod
cal-iut debloquer <id> --prod            # l'identifiant est donné par cal-iut trafic
```

Durée par défaut : 24 h. Tout le détail (variables, limitation de débit, urgence) : [docs/ANTI-ASPIRATION.md](ANTI-ASPIRATION.md).

---

## 9. Les sauvegardes

### Ce qui est sauvegardé

| Quoi | Quand | Gardé | Où le voir |
|---|---|---|---|
| **Le planning** (1) | 1er changement du jour | 90 jours | **Administration → Sauvegardes**, bouton **Télécharger** |
| **La base** (2) | 1er changement du jour, ou démarrage | 30 jours | Sur le serveur : `data/state/sauvegardes_db/` |

(1) Un fichier JSON : semaines, séances placées, séances ajoutées, retouches.
(2) Comptes, clés API, tâches, placements enregistrés, historique.

L'écran **Sauvegardes** montre une ligne par jour, avec le nombre de **Séances placées** et l'**Écart** avec la veille.
Une chute brutale se voit tout de suite.
**Faire une sauvegarde maintenant** remplace celle du jour. L'écran ne restaure rien.

Pour une sauvegarde immédiate de la base : `cal-iut sauvegarder-base`.

### Ce qui n'est PAS sauvegardé

- **Les images des tâches.** La base garde leur liste (nom, taille), pas les fichiers.
  Les fichiers restent dans `data/state/pieces_jointes/`.
- **La perte du serveur.** Toutes ces sauvegardes sont sur le même disque que la base.

Seule la **sauvegarde du volume dans Dokploy** protège les images et la perte du serveur. L'activer.
À défaut, copier de temps en temps le dossier `data/state/` ailleurs.

### Restaurer la base

Pour revenir à la base d'un jour donné. Tout ce qui a été fait depuis ce jour-là sera perdu dans la base.

1. Arrêter l'appli : le service **backend** et le service **celcat-nuit**.
2. Ouvrir un terminal sur le volume (le dossier monté sur `/app/data/state`).
3. Mettre la base actuelle de côté, sans l'effacer :
   ```bash
   mv data/state/cal-iut.db data/state/cal-iut.db.avant-restauration
   rm -f data/state/cal-iut.db-wal data/state/cal-iut.db-shm
   ```
4. Remettre la sauvegarde choisie :
   ```bash
   cp data/state/sauvegardes_db/cal-iut-2026-09-28.db data/state/cal-iut.db
   ```
5. Vérifier qu'elle est saine (doit afficher `ok`) :
   ```bash
   sqlite3 data/state/cal-iut.db "PRAGMA integrity_check"
   ```
6. Redémarrer les deux services.

Les images des tâches ne bougent pas.
Une image retirée depuis s'affiche « Image indisponible ». Une image ajoutée depuis reste sur le disque sans être listée.
Les sauvegardes JSON du planning (écran **Sauvegardes**, fichiers `data/state/sauvegardes/`) peuvent aider à retrouver les placements perdus.

---

## 10. Lisser le planning d'une promo

Le lissage réorganise les séances **à venir** d'une promo en alternance (FC) : pas de cours à 8 h, pas de trou, journées de charge égale, peu de 17 h.
Seule cette promo bouge. Chaque déplacement passe les mêmes contrôles qu'un glisser-déposer. Rien n'est écrit sans `--appliquer`.

**Il n'y a pas de bouton dans l'appli.** C'est en ligne de commande, réservé aux admins.

```bash
cal-iut lisser                                  # simulation sur la base locale (promo BUT3-DEV-FC)
cal-iut lisser --parcours BUT3-CREACOM-FC       # une autre promo
cal-iut lisser --meme-semaine                   # aucune séance ne change de semaine
cal-iut lisser --prod                           # simulation sur la production
cal-iut lisser --prod --appliquer               # applique en production
```

1. Lancer d'abord **sans** `--appliquer` (environ 1 min 30).
2. Lire le tableau avant/après et la liste des déplacements.
3. Si une « CONTRE-VÉRIFICATION » signale des conflits, la proposition n'est pas applicable.
4. Relancer avec `--appliquer`.

`--prod` utilise `CAL_IUT_PROD_URL` et `CAL_IUT_PROD_API_KEY` (clé d'un compte admin) dans `.env`.
Les séances déplacées partent ensuite vers Celcat comme un déplacement à la main.

---

## 11. Envoyer le planning local vers la production

Un redéploiement ne touche **jamais** la base de production : c'est ce qui protège les modifications faites en ligne.
Une correction faite en local ne part donc pas toute seule.

```bash
cal-iut prod diff                 # ce qui diffère, sans rien changer
cal-iut prod push                 # simulation : ce qui serait envoyé
cal-iut prod push --appliquer     # envoie réellement
cal-iut prod pull --appliquer     # l'inverse : ramène la production en local
```

- Le local est lu directement dans `data/state/cal-iut.db` (le serveur local n'a pas besoin de tourner).
- La production est modifiée par son API, avec les mêmes contrôles qu'une modification à la main.
- Une séance présente d'un seul côté n'est jamais créée ni supprimée : elle est listée, la décision reste humaine.
- Configuration dans `.env` : `CAL_IUT_PROD_URL` et `CAL_IUT_PROD_API_KEY` (recommandé, une clé d'un compte Édition ou Admin).
  À défaut : `CAL_IUT_PROD_EMAIL` et `CAL_IUT_PROD_PASSWORD`.

---

## 12. Déployer

### Comment l'appli est hébergée

L'appli tourne sur **Dokploy**, en trois services :

| Service | Construit depuis | Rôle |
|---|---|---|
| **frontend** | `frontend/Dockerfile` | nginx : sert l'interface et transmet le reste au backend |
| **backend** | `Dockerfile` (racine) | L'API et le solveur. Monte le volume `data/state/` |
| **celcat-nuit** | `deploy/celcat-sidecar/Dockerfile` | Le robot qui envoie les modifications dans Celcat (VPN). Même volume que le backend |

`docker-compose.yml` décrit les trois. Si Dokploy est en mode « Docker Compose » sur ce fichier, tout part ensemble.
En mode « un Dockerfile par service », il faut créer **celcat-nuit** à la main (voir [docs/CELCAT.md](CELCAT.md)).

**Le volume** (`data/state/`, nommé `cal-iut-data`) garde tout ce qui vit : base, comptes, tâches et images, codes saisis, blocages, file Celcat.
Il survit aux déploiements. `data/config/` est hors du volume : il est mis à jour à chaque déploiement.

> **Attention :** ne jamais supprimer le volume pour « repartir propre ».
> On perdrait comptes, clés, tâches, images, saisies et historique.
> Pour mettre la production à jour depuis le local : [§ 11](#11-envoyer-le-planning-local-vers-la-production).

### Déployer une nouvelle version

1. Pousser le code sur la branche suivie par Dokploy (`main`).
2. Dans Dokploy, lancer le déploiement (ou attendre le déploiement automatique).
3. Déployer **frontend et backend ensemble** quand les deux ont changé.
4. Faire les vérifications ci-dessous.

### Les variables d'environnement

À régler dans Dokploy → service → **Environment**, puis redéployer ce service.

| Variable | Service | Obligatoire ? | Rôle |
|---|---|---|---|
| `CAL_IUT_PUBLIC_URL` | backend | Oui, pour les mails | Adresse publique (ex. `https://cal-iut-mmi.srko.fr`), utilisée dans les liens envoyés par mail |
| `RESEND_API_KEY`, `RESEND_FROM` | backend | Oui, pour les mails | Envoi des mails (confirmation, mot de passe, liens enseignants). Sans eux, chaque envoi échoue avec un message clair |
| `CAL_IUT_SECRET_KEY` | backend | Conseillé | Secret de signature des sessions. Sans lui, un secret est créé dans le volume |
| `CAL_IUT_MCP_TOKEN` | backend | Non | Jeton MCP de secours (droits Édition). Sinon, chacun utilise sa clé |
| `CAL_IUT_COOKIE_SECURE` | backend | Non | `0` seulement pour un serveur servi en http ailleurs que sur `localhost` |
| `CAL_IUT_ANTI_ASPIRATION`, `CAL_IUT_AA_*`, `CAL_IUT_PROXYS_DE_CONFIANCE` | backend | Non | Protection contre l'aspiration : voir [docs/ANTI-ASPIRATION.md](ANTI-ASPIRATION.md) |
| `BACKEND_URL` | frontend | Si le backend porte un autre nom | Adresse du backend sur le réseau interne (défaut `http://backend:8000`) |
| `DNS_RESOLVER` | frontend | Non | Résolveur DNS de Docker (défaut `127.0.0.11`) |
| `CELCAT_URL`, `CELCAT_UTILISATEUR`, `CELCAT_MOT_DE_PASSE` | celcat-nuit | Oui | Accès à Celcat (même mot de passe que le VPN) |
| `CAL_IUT_REGLES_ENVOI` | backend **et** celcat-nuit | Non | Règles d'envoi Celcat (WR100BU, PTUT). `off` par défaut ; `on` après les essais ([A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md)) |
| `VPN_PASSERELLE`, `VPN_UTILISATEUR`, `VPN_MOT_DE_PASSE`, `VPN_GROUPE`, `VPN_CODE` | celcat-nuit | Non | Seulement si le compte VPN diffère de celui de Celcat |

Sur le poste local, ces valeurs vont dans `.env` (modèle : `.env.example`, jamais commité).
Côté poste seulement : `CAL_IUT_PROD_URL`, `CAL_IUT_PROD_API_KEY` (ou `CAL_IUT_PROD_EMAIL` / `CAL_IUT_PROD_PASSWORD`) pour les commandes `--prod`.

### Vérifier après un déploiement

1. **L'appli s'ouvre** et on peut se connecter.
2. **Les vraies adresses IP apparaissent dans les journaux.**
   Dokploy → service **frontend** → **Logs** : les lignes récentes montrent des IP publiques variées.
   Si toutes viennent d'une adresse `10.x` ou `172.x`, l'IP réelle est perdue : voir [docs/ANTI-ASPIRATION.md](ANTI-ASPIRATION.md).
3. **L'écran Trafic montre votre IP.** Ouvrir **Administration → Trafic** : votre adresse doit y figurer.
4. **Une image s'ajoute à une tâche.** Onglet **Tâches**, ouvrir une tâche, coller une capture (`Ctrl V`).
   La vignette doit apparaître. Sinon, le frontend n'a pas été redéployé (limite de taille de nginx).
5. **Le schéma de l'API n'est pas public.** `https://<site>/openapi.json` doit répondre 404 (page introuvable).
6. **Celcat** : **Administration → Celcat**, le robot d'envoi est passé récemment.

---

## 13. En cas de problème

| Symptôme | Que faire |
|---|---|
| Une personne ne reçoit pas le mail de confirmation | Vérifier `RESEND_API_KEY`, `RESEND_FROM`, `CAL_IUT_PUBLIC_URL`. Le lien expire au bout de 48 h : elle peut recommencer l'inscription. |
| Une personne dit « En attente d'activation » | L'activer : [§ 2](#2-gérer-les-comptes). |
| « Impossible de retirer le dernier administrateur actif » | Nommer d'abord un autre admin. |
| Une clé API ne marche plus | Compte désactivé, clé révoquée, ou compte **Accès API** qui appelle autre chose que `/api/v1/`. |
| « Limite de 5 clés API actives atteinte » | Révoquer une clé inutile. |
| Des séances ne partent pas dans Celcat | **Référence → Codes Celcat**, filtre **Sans code**. Puis l'écran **Celcat** : [docs/CELCAT.md](CELCAT.md). |
| « Enseignant indisponible — … déjà programmé dans le département TC … (Celcat) » alors qu'il est libre | L'occupation vient de Celcat. **Celcat → Occupations hors MMI** : vérifier la date du relevé, **Relire maintenant**, ou **Forcer** si la réunion est annulée. Détail : [CELCAT.md § 6](CELCAT.md#6-occupations-hors-mmi). |
| Un de nos cours ressort « occupé ailleurs dans Celcat » | Il n'est pas reconnu comme MMI. Faire vérifier par un technicien : [A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md). |
| Un utilisateur légitime reçoit « Accès refusé. » | **Trafic** → carte **Blocages** : débloquer son adresse. |
| Le serveur est saturé par un robot | **Trafic** → **Bloquer…**. Si l'écran ne répond plus : [docs/ANTI-ASPIRATION.md](ANTI-ASPIRATION.md), section urgence. |
| « Trop de requêtes. Réessayez dans N secondes. » | La limitation de débit est active : [docs/ANTI-ASPIRATION.md](ANTI-ASPIRATION.md). |
| Une image de tâche est refusée ou n'arrive pas | PNG, JPEG, WebP ou GIF, 8 Mo au plus, 10 par tâche. Si toutes échouent : redéployer le frontend. |
| « Image indisponible » sur une tâche | Le fichier n'est plus sur le disque (base restaurée, par exemple). Pas récupérable sans sauvegarde du volume. |
| Le planning a perdu beaucoup de séances | **Sauvegardes** : comparer les jours (colonne **Écart**), télécharger le bon jour. Restaurer la base si besoin : [§ 9](#9-les-sauvegardes). |
| Une modification locale n'apparaît pas en production | Normal : `cal-iut prod push` ([§ 11](#11-envoyer-le-planning-local-vers-la-production)). |
| « Séance verrouillée : la déverrouiller d'abord » | Il n'existe **aucun** bouton ni appel d'API pour déverrouiller une séance. Demander à un technicien (le verrou est enregistré côté serveur). |
| Un nouveau vacataire introuvable dans **Nouvelle séance** | L'ajouter : [§ 5](#5-ajouter-un-intervenant). |

---

## 14. Pour les techniciens

**Fichiers du volume `data/state/`** (persistants, jamais dans Git) :

| Fichier | Contenu |
|---|---|
| `cal-iut.db` | Base SQLite : comptes, clés (empreinte SHA-256 seulement), tâches, placements, historique |
| `sauvegardes_db/cal-iut-AAAA-MM-JJ.db` | Copies quotidiennes cohérentes de la base (API de sauvegarde SQLite), 30 jours |
| `sauvegardes/cal-iut-AAAA-MM-JJ.json` | Instantanés JSON du planning, 90 jours |
| `references.json` | Mails, noms, intitulés corrigés dans l'appli ; intervenants ajoutés |
| `celcat_mappings.json` | Codes Celcat saisis et « sans code (voulu) » saisis dans l'appli |
| `blocages.json` | Liste de blocage (IP, plages, User-Agent) |
| `pieces_jointes/taches/<n°>/` | Images des tâches (nom tiré au sort) |
| `.secret_key` | Secret de signature, si `CAL_IUT_SECRET_KEY` n'est pas posée |
| `mail_log.json` | Journal des mails envoyés aux enseignants |
| file et journaux Celcat | Voir [docs/CELCAT.md](CELCAT.md) |
| `celcat_occupations_externes.json` | Occupations hors MMI relevées dans Celcat par le robot ([CELCAT.md § 6](CELCAT.md#6-occupations-hors-mmi)) ; la supprimer lève toutes les contraintes externes |

**Premier déploiement.** L'image backend contient `data/state/cal-iut.db` du poste de build.
Le volume est rempli avec elle une seule fois, à sa création. Ensuite, le volume a toujours la priorité.

**Droits, côté serveur.** Chaque rôle est relu en base à chaque requête (cookie signé HMAC, `user_id` + expiration).
Un compte **Accès API** est limité par le middleware `require_auth` : par cookie, ses clés (`/auth/mcp-keys`) et la documentation `/api/v1/docs` ; par clé, `GET /api/v1/*` seulement.
Les routes d'administration exigent `require_role("admin")`.

**Autres limites.** API v1 : 600 requêtes par minute et par compte. Connexion : 30 essais en 5 min par IP.
Page historique `/legacy` : admins seulement.

**Compte local de test** (base locale, sans mail) :

```bash
python scripts/creer_admin_local.py email@exemple.fr motdepasse --role admin   # ou edit, read_only, api
```

Ne jamais committer la base modifiée par ce script (`git checkout data/state/cal-iut.db`).

**Vérifier la base sans `sqlite3`** (image Python) :

```bash
python -c "import sqlite3; print(sqlite3.connect('data/state/cal-iut.db').execute('PRAGMA integrity_check').fetchone()[0])"
```
