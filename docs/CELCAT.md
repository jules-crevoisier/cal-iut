# Celcat : recopier le planning dans Celcat

Ce document explique comment l'appli recopie le planning dans Celcat, l'outil d'emploi du temps de l'université.
Il est pour les administrateurs (écran **Celcat**) et les techniciens.
Les codes Celcat (cours, salles, enseignants) se règlent dans **Référence → Codes Celcat** : voir [docs/ADMIN.md](ADMIN.md).

**Sommaire**

1. [Ce que ça fait](#1-ce-que-ça-fait)
2. [Ce que vous voyez : l'écran Celcat](#2-ce-que-vous-voyez--lécran-celcat)
3. [Que faire quand ça bloque](#3-que-faire-quand-ça-bloque)
4. [Pour les techniciens](#4-pour-les-techniciens)
5. [Règles d'envoi : WR100BU et PTUT](#5-règles-denvoi--wr100bu-et-ptut)
6. [Occupations hors MMI](#6-occupations-hors-mmi)

---

## 1. Ce que ça fait

Quand on déplace, ajoute ou supprime une séance dans l'appli, la modification est **mise en file d'attente**.
Un **robot d'envoi** la recopie ensuite dans Celcat, tout seul.

- Le robot passe **toutes les 30 secondes environ**. Il ne se connecte que s'il a quelque chose à envoyer.
- **Chaque nuit**, il compare les semaines choisies (« balayage de nuit ») avec Celcat et met en file ce qui diffère.
  Il repère aussi les cours présents **seulement dans Celcat**.
- Celcat n'est joignable que par le **VPN de l'université**. Le robot le monte lui-même, puis le rend.
  Ce VPN et le compte Celcat sont **partagés avec l'équipe** : d'où le bouton de pause.

### Ce qui part, ce qui ne part pas

| Cas | Ce qui se passe |
|---|---|
| La séance a tous ses codes Celcat | Elle part. |
| Un code manque (cours, salle, enseignant, groupe) | Elle est **bloquée** : elle ne part pas tant que le code n'est pas saisi. |
| Le cours est marqué **sans code (voulu)** | Elle n'est **pas envoyée**, volontairement, sans rien bloquer. |
| Une **règle d'envoi** la vise (WR100BU de Valérie Mariot, toute séance PTUT) | Elle part avec la catégorie, la remarque et le département de la règle ([§ 5](#5-règles-denvoi--wr100bu-et-ptut)). |
| La semaine n'est pas encore ouverte dans Celcat par l'équipe | Les **créations attendent**. Un admin peut autoriser la semaine. |
| Une séance est retirée de l'appli | Son évènement Celcat est supprimé aussi (jamais un jour férié ni un évènement protégé). |
| Celcat a un évènement **en trop** (qui ne vient pas de l'appli) | Rien n'est supprimé automatiquement. Un admin décide, après vérification. |

---

## 2. Ce que vous voyez : l'écran Celcat

**Administration → Celcat** (admins seulement). L'écran se lit de haut en bas.

1. **L'état du système** : écriture dans Celcat, robot d'envoi, dernière lecture de Celcat.
2. **La semaine comparée** : celle choisie dans la barre du haut (flèches pour changer).
3. **Les compteurs** : **À modifier**, **À créer**, **En trop**, **Identiques**, en file.
4. **Le verdict** : « concorde », « à traiter » ou « bloqué ».
5. **À gauche** : les écarts séance par séance, puis les évènements en trop.
6. **À droite** : la file d'attente (« File d'attente vide — tout est poussé. » quand tout est parti) et ce qui bloque.
7. **Repliés en bas** : **Occupations hors MMI** (ce que Celcat contient d'autre sur nos salles et enseignants, voir [§ 6](#6-occupations-hors-mmi)),
   **Activité récente** (créées, modifiées, supprimées, échecs) et **Réglages**.

### Corriger une semaine

1. Choisir la semaine dans la barre du haut.
2. Lire les écarts.
3. Cliquer sur **Corriger les N écarts** (ou **Corriger l'écart**).
   Les corrections partent en file. L'écran suit leur avancée : mise en file, passage du robot d'envoi, nouvelle lecture de Celcat.
4. Quand la file est vide, cliquer sur **Relire Celcat et vérifier**.

Le verdict doit passer à « concorde ». **Corriger** ne supprime jamais rien.

### Les réglages

| Réglage | Effet |
|---|---|
| **Écriture dans Celcat** (active / coupée) | Coupée : plus rien ne part, et **la file est vidée** (corrections abandonnées). |
| **Robot d'envoi** (actif / en pause) | En pause : le VPN est libre pour l'équipe. La file est **gardée** et repart à la reprise. |
| **Envoi par semaine — balayage de nuit** | Cocher les semaines, puis **Enregistrer la sélection**. **Envoyer maintenant** fait le balayage tout de suite. |
| **Cours présents seulement dans Celcat** | Pour chaque cours : **Ajouter** au planning, ou **Ignorer**. |
| **Reconstruire la file** | Refait la file à partir des seuls écarts réels (après un gros changement). |

**Reconstruire la file** propose deux boutons :
**Reconstruire sans supprimer**, ou **Reconstruire avec suppressions…**, qui supprime **définitivement** ce que Celcat a en trop.

> **Attention :** pour libérer le VPN, mettre le **robot en pause**. Ne pas couper l'écriture : cela vide la file.

---

## 3. Que faire quand ça bloque

### Une séance est bloquée par un code manquant

1. Dans la carte de ce qui bloque, cliquer sur **Mapper…** et saisir le code.
   Ou cliquer sur **Voir dans Codes Celcat →** et le saisir là.
2. Le code part au passage suivant du robot.

Un **groupe** ou une **matière** « identifiant interne » ne se saisit pas dans l'appli.
Il se règle dans `celcat_groupes.yaml` ou `celcat_matieres.yaml`, puis on redéploie. Prévenir un technicien.

### « En attente d'une semaine que Celcat n'a pas encore ouverte »

Le robot ne crée rien dans une semaine que l'équipe n'a pas encore saisie dans Celcat.
Si c'est bien à l'appli de remplir cette semaine : **Autoriser la création sur la semaine affichée**.
Sinon, attendre.

### Celcat a des évènements en trop

1. Vérifier dans Celcat que personne n'est en train de les saisir à la main.
2. Cliquer sur **Supprimer N évènements**, relire la liste, confirmer.

Si l'écran dit « Relisez Celcat d'abord », la dernière lecture est trop ancienne : cliquer sur **Relire Celcat**, attendre, recommencer.

### Le robot ne passe pas, ou la file ne descend pas

- « Le robot d'envoi n'est pas encore passé » depuis longtemps : vérifier qu'il n'est pas en pause (**Réglages**).
  Sinon, regarder les journaux du service **celcat-nuit** dans Dokploy.
- Des **échecs** : ouvrir **Activité récente**. Un échec répété ralentit le robot (jusqu'à 30 min entre deux essais), pour ne pas faire bloquer le compte partagé.
  Prévenir un technicien.

### L'équipe a besoin du VPN

**Réglages → Robot d'envoi** : pause. Le remettre en marche après.

### Un cours existe dans Celcat mais pas dans l'appli

**Réglages → Cours présents seulement dans Celcat** : **Ajouter** ou **Ignorer**.

---

## 4. Pour les techniciens

### 4.1 Architecture

- Le **backend** ne parle jamais à Celcat. Il écrit la file dans le volume partagé `data/state/` (un fichier par job : création, modification, suppression).
- Le service **celcat-nuit** (`deploy/celcat-sidecar/`, OpenConnect + Playwright) lit ce même volume et parle à Celcat.
  Il tourne avec `--cap-add NET_ADMIN --device /dev/net/tun`.
- **Il doit rester séparé du backend** : la passerelle de l'URCA pousse un tunnel complet. Monté dans le conteneur du site, il couperait tout son trafic sortant.
- Sa boucle (`deploy/celcat-sidecar/nuit-quotidienne.sh`) :
  1. toutes les 30 s : `scripts/celcat_immediat.py --ecrire --vpn --production --base URCA_2026` draine la file (sort sans réseau si elle est vide) ;
  2. `scripts/celcat_instantane.py --vpn` relit Celcat si le dernier relevé a plus de 2 h, ou si quelqu'un a demandé **Relire Celcat** ;
     dans la même session, il relit aussi les **occupations hors MMI** ([§ 6](#6-occupations-hors-mmi)) quand elles sont dues ;
  3. une fois par jour (UTC) : `scripts/celcat_nuit.py --ecrire --vpn --production --base URCA_2026` balaie les semaines validées, cherche les cours en trop, et draine aussi la file.
- Le passage quotidien est noté dans `data/state/celcat_nuit_dernier_passage.txt` (dans le volume) : un redémarrage ne le fait ni sauter ni recommencer.
  Il peut donc tourner à n'importe quelle heure de la journée, au premier tour où il n'a pas encore été fait.
- Sur échec, l'attente double à chaque tour, jusqu'à 30 min, puis revient à 30 s au premier succès.
- Le robot dépose son compte rendu (`data/state/celcat_drainage.json`, avec son âge) : c'est ce qu'affiche l'écran.
- La comparaison (`celcat/planification.py`) est la même pour l'écran et pour le robot. Seul ce qui diffère part : identique → rien ; écart → modifier ; absent de Celcat → créer ; en trop → supprimer (sur décision humaine).

**Déploiement du service.**
En mode Dokploy « Docker Compose » sur `docker-compose.yml`, `celcat-nuit` part avec les deux autres.
En mode « un Dockerfile par service », le créer à la main : Dockerfile `deploy/celcat-sidecar/Dockerfile`, même volume que le backend, variables `CELCAT_*` / `VPN_*`, `cap_add NET_ADMIN` et device `/dev/net/tun`.
Repli sans Dokploy, sur la machine qui sert le site :

```bash
docker build -t cal-iut-celcat -f deploy/celcat-sidecar/Dockerfile .
docker run -d --restart unless-stopped --name celcat-nuit \
  --cap-add NET_ADMIN --device /dev/net/tun \
  --env-file /chemin/vers/.env \
  -v cal-iut-data:/app/data/state \
  cal-iut-celcat
docker logs -f celcat-nuit
```

**Le volume est le point critique** : exactement celui du backend, jamais une copie locale. Sinon le robot draine une file que personne ne remplit.

### 4.2 Accès réseau

- `celcat-lv.univ-reims.fr` ne résout pas depuis l'extérieur : VPN obligatoire hors site. Sur place, à l'IUT, l'accès est direct.
  Règle : toujours essayer **sans VPN d'abord** (`celcat/reseau.py`).
- VPN AnyConnect : client Cisco sous Windows, **OpenConnect** sous Linux (même protocole). Identifiant et mot de passe, sans second facteur.
- Diagnostic sans rien envoyer : `cal-iut celcat-reseau` (`--connecter` pour tenter de monter le VPN avec les identifiants `VPN_*`).
- Variables : `CELCAT_URL`, `CELCAT_UTILISATEUR`, `CELCAT_MOT_DE_PASSE` (le même que le VPN) ; facultatives `VPN_PASSERELLE`, `VPN_UTILISATEUR`, `VPN_MOT_DE_PASSE`, `VPN_GROUPE`, `VPN_CODE`.

### 4.3 Se connecter à Celcat à la main

1. Choisir une base : `URCA_2023` … `URCA_2026` (la vraie, pour 2026-2027), ou **`URCA_FORMATION`** (base d'entraînement).
2. **Connexion** → dialogue « Sécurité CELCAT ». Identifiant et mot de passe du VPN.
3. Champ « Rôle » : décocher « Utiliser le rôle par défaut », puis :
   - `985_consultation` : **lecture seule** (toute écriture impossible) ;
   - `985_T_MMI` : écriture sur le périmètre MMI.
   Témoin : en lecture seule, un bandeau dit « Vous avez un accès en lecture seulement à cet emploi du temps ».
4. **Se déconnecter à la fin.** Celcat garde les sessions : trop de sessions ouvertes saturent le serveur, qui n'affiche plus la liste des bases.

Pour essayer : `985_consultation` pour explorer, `URCA_FORMATION` pour écrire sans toucher aux vraies données.

### 4.4 Le service JSON-RPC

Celcat Timetabler Live est une application **qooxdoo** (IIS/ASP.NET) : des `<div>` placés au pixel, sans `id` ni rôle accessible.
Elle s'appuie sur un service **JSON-RPC 2.0** (`/script/CTWebService.dll`).

- **On ne peut pas l'appeler depuis un `fetch` séparé** : la session est liée à la connexion du navigateur (ni cookie, ni jeton). Un appel à part reçoit `ESessionTimeout`.
  L'appli passe donc par le client de la page, `ctweb.io.Rpc.invoke` : Playwright fait seulement la connexion.
- **Les réponses ne sont pas du JSON strict** : l'en-tête `X-Use-Object-Date: yes` renvoie des `new Date(2026,5,12,…)`, mois en base 0 (5 = juin). `lire_reponse` les convertit.
- **Chargement paresseux** dans l'interface : seules les lignes visibles sont détaillées. Pour en voir plus, faire défiler le **tableau** (la molette agit sous le pointeur).
- **Chercher précis** : un préfixe trop court donne `ETooManyRecords` et rien ne se charge. « BUT MMI » suffit pour les groupes ; « MMI » seul échoue.

Ressources (`udlResources.load(<type>, …)`) :

| Type | Ressource | Volume (URCA_2026) |
|---:|---|---:|
| 601 | Matières | trop pour un chargement global |
| 602 | Groupes | trop pour un chargement global |
| 603 | Personnel | 4 975 |
| 604 | Salles | 2 444 |
| 607 | Équipes | 300 |
| 610 | Départements | 155 |
| 618 | Catégories d'évènements | 38 |

Évènements d'un groupe : `udlTimetables.load` avec `{"GroupIDs": [<id>]}`.
Un évènement porte `event_id`, `day_of_week`, `start_time`, `end_time`, `evCatName`, `rooms`, `modules`, `staff`, `weeks` (une lettre par semaine de l'année, `Y` = active), `protected`, `suspended`.

### 4.5 Écrire dans Celcat

Une seule méthode : **`udlTimetables.save`** (`data/config/celcat_rpc.yaml` : `methode_ecriture` et `methode_suppression`).
Il n'existe pas de `udlTimetables.delete` (108 méthodes `udl*` recensées, `scripts/scanner_methodes_udl_celcat.py`).

| Action | Forme | Code |
|---|---|---|
| **Créer** | Enregistrement **sans** `event_id` (`event_id: 0` est refusé), masque `weeks` d'**une seule** semaine | `ecriture.py` |
| **Modifier** | Recharger l'enregistrement **complet** (`udlTimetables.load`), le cloner, n'écraser que les champs voulus, renvoyer | `modification.py` |
| **Supprimer** | Enregistrement minimal `{"-event_id": <id>, "_type_": "Event"}` | `suppression.py` |
| **Changer de salle** | Dans le même appel : retirer l'ancienne `{"-event_id": E, "-room_id": R, "_type_": "Room"}` et poser la nouvelle | `modification.py` |

À savoir :

- Un objet reconstruit à la main (quelques champs + `event_id`) fait échouer une modification : « Cannot locate a record using only a partial key ». Il faut la forme complète.
- Le signe moins devant **tous** les composants de la clé veut dire « retirer ». L'association évènement↔salle se repère par le couple `(event_id, room_id)`.
- `save` **ajoute** une salle au lieu de la remplacer : sans le retrait, le cours se retrouve sur deux salles.
- Pour une nouvelle ressource (salle, enseignant, matière), on recharge son vrai enregistrement (`udlResources.load`), jamais l'ancien sous-objet avec un nouvel id.
- `suspended: "Y"` ne supprime pas (l'évènement reste visible). Un masque `weeks` tout à `N` est refusé par le serveur (contrainte `CK_EVENT_WKLEN`).
- Avant une suppression, l'évènement est **relu** : un jour férié, un évènement protégé (`protected=Y`) ou un « fantôme » est refusé, même si le job a été mis en file avant.
- Garde-fous avant tout envoi : catégorie vérifiée, masque d'une semaine, `--production` exigé pour écrire sur `URCA_2026` (sinon base d'entraînement), journal anti-doublon.

**Catégories CM / TD / TP.** Libellés `[CM]`, `[TD]` (distinct de `TD0`), `[TP]` (`celcat_formulaire.yaml`).
`TD0` (id 465) est réservée aux règles d'envoi ([§ 5](#5-règles-denvoi--wr100bu-et-ptut)) : refusée sur toute autre séance.
Les catégories portent une pondération (`[CM]` 100, `[TD]` 100, `[CM bénévole]`, `[CM Capacite]`…) : c'est par là que passe la paie.
L'id de `[CM]` est **430** : toute charge CM avec un autre `event_cat_id` est refusée (`celcat/categories.py`).
L'ancien autoclicker enregistrait les CM en `[TP]`. Audit et correction :

```powershell
python scripts/corriger_cm_categories_celcat.py --vpn --lundi 2026-09-07 --base URCA_2026
python scripts/corriger_cm_categories_celcat.py --vpn --lundi 2026-09-07 --base URCA_2026 --production --ecrire
```

La comparaison classe aussi en « à modifier » un évènement dont la catégorie ne correspond pas au type de la maquette.

### 4.6 Semaines « posées »

L'équipe saisit Celcat semaine par semaine. Le robot ne **crée** rien dans une semaine que Celcat n'a pas encore ouverte, pour ne pas se mélanger au travail en cours.
Une semaine est « posée » quand Celcat couvre au moins **la moitié** de ce que l'appli prévoit dessus (seuil relatif, pas un nombre fixe : `celcat/semaines_posees.py`).
Un job différé repart au cycle suivant.
L'admin lève la garde semaine par semaine (**Autoriser la création sur la semaine affichée**, `PATCH /celcat/semaines/creation`). Les autres garde-fous restent actifs.

### 4.7 Données de référence relevées dans Celcat

**Groupes.** Nom : `BUT MMI <semestre> <libellé> - <année d'entrée de la cohorte>` (ex. « BUT MMI S1 TD AB - 2024 »).
L'année est celle d'**entrée** de la cohorte, pas celle de la base. Département : `T_MMI T29`.
Le titre de l'emploi du temps d'un groupe montre aussi un code (« [6TSBZ1TD_1] »).
L'appli utilise l'**identifiant interne** (`group_id`, ex. 1661972), relevé dans `data/config/celcat_groupes.yaml`.
Un identifiant faux crée des doublons (une modification localisée sur le mauvais groupe fait croire l'évènement disparu, puis il est recréé).

**Salles.** Recherche par nom exact fiable. Écarts reportés dans `celcat.yaml` :

- H.018 (Amphi MMI) = « **Amphi 3 MMI** » dans Celcat ;
- H.022 s'appelle « **H.022 studio** » (« H.022 » seul ne trouve rien) ;
- H.203 n'existe pas (renvoi vers H.023) ;
- salles réunies (H.007-008, H.201-203) : n'existent pas dans Celcat. On en garde **une seule** : H.007 et H.201.
- Les capacités Celcat diffèrent parfois (H.201 : 10, H.104 : 0) : ce sont les leurs qui jugent un conflit chez eux.

**Enseignants.** Chercher par le **nom de famille** (Celcat trouve mal par le prénom). Un code `0` dans `celcat.yaml` = code inconnu.

**Matières.** Codes module `TSB…`, relevés dans `data/config/celcat_matieres.yaml`. Codes de la maquette : `data/config/celcat_modules_maquette.yaml` (voir [docs/ADMIN.md](ADMIN.md)).

**Semaines.** Le sélecteur en bas à gauche (août → juillet) n'a de texte que sur la semaine sélectionnée.
Son infobulle, au survol seulement, est en anglais, mois/jour : `Week: 37 (9/7/26-9/13/26)`.
D'anciens relevés montraient aussi jour/mois : `navigateur.choisir_semaine` essaie les deux lectures et ne garde que celle qui donne une semaine commençant au lundi visé.
Il place les cellules par géométrie (en fusionnant les `<div>` superposés), et ne clique que si l'infobulle confirme ce lundi.

### 4.8 L'ancien pilotage par l'écran (sans bouton)

Avant le JSON-RPC, l'écriture passait par des clics (Playwright, `driver.PilotePlaywright`), et avant encore par un autoclicker en coordonnées fixes.
Ce chemin existe encore par l'API (`POST /celcat/saisie`, admin : simulation et base d'entraînement par défaut ; refus si une séance est bloquée, si Celcat est injoignable, ou si le formulaire n'est pas relevé).
Aucun bouton de l'appli ne l'utilise. Ce qu'on en a appris :

- l'icône `new` (« Créer un nouvel évènement ») crée **aussitôt** un évènement vide actif sur les 54 semaines, sans rien enregistrer. Ne jamais cliquer dessus pour « voir » ;
- `new.png` apparaît **deux fois** à l'écran (deux barres) : `navigateur.cliquer_icone_barre` exige un repère (`refresh`, `save`) et lève plutôt que choisir au hasard ;
- ordre des icônes de la barre : `new`, `delete`, `refresh`, `save`, `cancel` ;
- le formulaire de création est le même que l'**inspecteur** (double-clic sur un évènement existant) : onglets `Détails`, `Ressources`, `Remarques et personnaliser`, `Critères requis`, `Historique` ;
- le champ est **sous** son libellé (+32 px), pas à droite ; libellés avec deux-points (`Jour:`, `Heure:`, `Catégorie d'événement:`, `Département:`) ;
- un seul champ horaire, en 12 h (« 8:00 AM-9:30 AM ») ; pas de bouton OK, c'est l'icône `save` qui valide ;
- les champs se remplissent par **glisser-déposer** depuis la liste de gauche, avec des pauses (qooxdoo gère son propre glisser) ;
- onglet Ressources : sections `Matières [n]`, `Salles [n]`, `Personnel [n]`, `Groupes [n]` (le chiffre est un compte) ;
- `Échap` ferme tout le panneau : éloigner le pointeur pour fermer une bulle ;
- les séances se détectent par la géométrie (couleur, taille), pas par le texte (les bulles répètent les mêmes mots).

Relever à nouveau le formulaire si Celcat change (jamais l'icône `new`) :

```powershell
docker build -t cal-iut-celcat -f deploy/celcat-sidecar/Dockerfile .
docker run --rm --cap-add NET_ADMIN --device /dev/net/tun `
  --env-file .env -v "${PWD}:/travail" -w /travail cal-iut-celcat `
  python scripts/relever_formulaire_celcat.py --vpn `
    --base URCA_2025 --role 985_consultation --lister-groupes "BUT MMI"
.venv\Scripts\python.exe scripts/lire_releve_celcat.py data/releves/celcat-formulaire-<…>
.venv\Scripts\python.exe -c "from cal_iut.celcat.formulaire import charger_carte; print(charger_carte('data/config').manques())"
```

Options : `--lister-groupes`, `--calendrier` (géométrie du sélecteur de semaines), `--semaines 2026-09-14,2027-03-29` (lundis essayés).
Liste vide à la fin : la carte `celcat_formulaire.yaml` est complète. Fermer l'inspecteur par **Annuler**.

### 4.9 Scripts utiles

| Script | Rôle |
|---|---|
| `scripts/sonder_rpc_celcat.py --vpn --base URCA_FORMATION` | Essayer le RPC sur la base d'entraînement |
| `scripts/pousser_manquants_celcat.py --lundi 2026-09-07 --vpn --base URCA_2026` | Lister ce qui manque (sans `--ecrire`) ; `--limite 1 --production --ecrire` pour envoyer |
| `scripts/verifier_suppression_reelle_celcat.py` | Canari : créer, supprimer, vérifier (base d'entraînement) |
| `scripts/capturer_changement_salle_celcat.py` | Canari du changement de salle |
| `scripts/nettoyer_canaris_formation.py` | Nettoyer les canaris de la base d'entraînement |
| `scripts/celcat_nuit.py`, `celcat_immediat.py`, `celcat_instantane.py` | Les trois étapes du robot (voir § 4.1) |

### 4.10 Points ouverts

- **Évènement vide créé par erreur** (01/09/2026, `event_id` 1929034, groupe `BUT MMI S1 TD AB`, mardi vers 7 h 30, semaine du 17 au 23 août 2026, superposé à un « Jour férié »).
  Aucune trace de sa suppression dans le dépôt : **à vérifier dans Celcat**, puis supprimer à la main si besoin (« Évènement 2 de 2 », sans catégorie ni horaire).
  Le robot le reconnaît comme « fantôme » et refuse d'y toucher.
- Codes Celcat des enseignants à `0` dans `celcat.yaml` : à compléter dans **Codes Celcat** quand ils sont connus.

---

## 5. Règles d'envoi : WR100BU et PTUT

Certaines séances partent dans Celcat avec une **catégorie**, une **remarque** et un **département imposés**.
Deux règles, demandées par Kyllian Bresson le 01/10/2026 :

| Règle | Séances visées | Catégorie | Remarque | Matière (module) |
|---|---|---|---|---|
| **WR100BU** (visite de la BU) | celles de Valérie Mariot (VMA, code 3696) | **TD0** (pondération 0) | `WR100BU` | **aucune** : le code est inventé |
| **PTUT** | **toutes** les séances de type PTUT, quel que soit le cours | **Projet** (pondération 0) | `PTUT` | celle **du cours** si son code est connu, sinon aucune |

Pour les deux : département **T_MMI T29** ; salle, groupe (classe) et enseignant de la séance.

### L'interrupteur : inactives par défaut

Les règles ne s'appliquent que si la variable d'environnement **`CAL_IUT_REGLES_ENVOI=on`** est posée
sur les **deux** services, `backend` et `celcat-nuit` (`docker-compose.yml` : `${CAL_IUT_REGLES_ENVOI:-off}`).

- **`off`** (défaut) : les séances visées ne partent pas et ne bloquent rien.
  Plan, comparaison et robot les montrent « non envoyée — règle d'envoi en attente d'activation (CAL_IUT_REGLES_ENVOI) »
  (journal « non envoyé »). Codes Celcat affiche « règle d'envoi (inactive) ». Rien ne change pour les autres séances.
- **`on`** : elles partent comme décrit ci-dessous.
- L'écran **Celcat → Réglages** affiche « Règles d'envoi (WR100BU, PTUT) : inactives / actives », avec la variable à poser.
- La commande d'essai (`cal-iut celcat-essai-regle`) marche **quelle que soit** la valeur : c'est elle qui sert à valider avant d'activer.

### Ce qui part

- **Remarque** (onglet « Remarques et personnaliser », champ `notes`) : la remarque, puis l'identifiant de la séance.
  Exemple : `WR100BU — WR100BU-S1-TD-1-but1-td-ab`. L'identifiant relie l'évènement à l'appli.
- **Matière.** WR100BU : jamais de matière, jamais cherchée.
  PTUT : la matière du cours (code connu par le fichier, la maquette ou une saisie), cherchée comme pour une séance normale.
  Cours sans code (manquant ou « sans code (voulu) ») : la séance PTUT part **sans matière** au lieu d'être bloquée.
  Jamais une matière « PTUT ». **Point à faire confirmer** par Kyllian : module du cours plutôt qu'aucun.
- **Catégorie et département** : cherchés **par leur nom** dans Celcat.
  Introuvables : la séance est **bloquée** (« catégorie « TD0 » introuvable dans Celcat »), jamais envoyée avec une autre catégorie.
- **Pondération 0** : elle est portée par la catégorie elle-même (« Projet [0%] » dans l'inspecteur). Aucun champ à part n'est écrit.
- **Enseignant** : Celcat n'en reçoit qu'un, le premier de la séance (comme pour toute séance).
- Une séance WR100BU d'un **autre** enseignant ne part pas. Motif : « WR100BU : seules les interventions de VMA sont envoyées ».
- **Priorité** : la règle du cours d'abord (elle décide seule pour ses séances), puis celle du type.
  Une règle passe devant « sans code (voulu) ».
- Le plan Celcat (`GET /celcat/plan`) l'affiche par séance : « sans module (règle WR100BU) »,
  « module du cours (règle PTUT) », « sans module — cours sans code Celcat (règle PTUT) ».
- La comparaison ne signale pas d'écart de matière ni de catégorie sur ces évènements.
  Un évènement au même créneau saisi à la main en « [TD] » ressort en écart **catégorie** : la correction le passe dans la catégorie de la règle.
- Garde-fou : la catégorie TD0 (id 465) n'est acceptée que pour ces séances-là.

Sur le planning actuel : 12 séances WR100BU, toutes de VMA (3 par groupe TD, S1) ; **aucune** séance PTUT.
Avant cette règle, une séance PTUT était bloquée (« type de séance PTUT sans code Celcat »).

### Activer, désactiver

Les règles sont dans `data/config/celcat.yaml`, section `regles_envoi` ([DATA.md](DATA.md#envoyer-avec-une-règle-denvoi)).
Elles ne s'appliquent qu'avec `CAL_IUT_REGLES_ENVOI=on` (voir ci-dessus).

- **Activer** : une fois les essais concluants, poser `CAL_IUT_REGLES_ENVOI=on` sur `backend` et `celcat-nuit`
  (Dokploy : variables d'environnement de chaque service), redéployer, puis vérifier le plan et l'écran **Celcat → Réglages**.
- **Tout couper d'un coup** : remettre `off` (ou retirer la variable), redéployer.

- **Désactiver** : retirer le bloc (`WR100BU:` sous `cours:`, ou `PTUT:` sous `types:`), redéployer.
  Pour que WR100BU ne parte plus du tout, le remettre dans `sans_code_voulu.cours` (avec un motif).
- Les évènements déjà créés dans Celcat y restent : les supprimer à la main si besoin.

### L'essayer sans risque

Commande : `cal-iut celcat-essai-regle` (`--cours WR100BU` ou `--type PTUT`). Elle demande le VPN.
Pas à pas complet, et un prompt pour Claude Code : [docs/A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md).

1. Écran **Celcat → Réglages → Robot d'envoi** : mettre en **pause** (VPN et compte partagés).
2. **Simulation sur la vraie base** (lecture seule, rôle `985_consultation`, rien n'est écrit) :

   ```bash
   docker compose run --rm celcat-nuit \
     cal-iut celcat-essai-regle --cours WR100BU --base URCA_2026 --vpn
   ```

3. **Canari en base d'entraînement** (crée UN évènement dans `URCA_FORMATION`, le relit, le supprime) :

   ```bash
   docker compose run --rm -it celcat-nuit \
     cal-iut celcat-essai-regle --cours WR100BU --vpn --ecrire --attendre
   ```

4. Pour PTUT, sans séance PTUT au planning, prendre une vraie séance comme support :
   `--type PTUT --seance <identifiant> --comme-type` (ex. `--seance WR101-S1-TD-1-but1-td-ab`).
5. Remettre le robot en marche.

Ce que la commande affiche :

1. la règle et le compte des séances (« Séances placées : 12 — envoyées par la règle : 12 … ») ;
2. la séance essayée : groupe, salle, enseignant, date, horaire, règle, module ;
3. le groupe Celcat et les identifiants résolus (`room_id`, `staff_id`, `event_cat_id`, `dept_id`, et `module_id` seulement s'il y a une matière) ;
4. la charge exacte qui serait envoyée (`udlTimetables.save`), après les garde-fous ;
5. avec `--ecrire` : l'`event_id` créé, puis ce que Celcat a gardé — catégorie, pondération, département, remarque,
   champs `custom1` à `custom3`, salles, groupes, enseignants, matières — et « supprimé, absent à la relecture ».

| Option | Effet |
|---|---|
| `--cours` / `--type` | La règle à essayer (l'un ou l'autre). |
| `--base` | `URCA_FORMATION` par défaut. `URCA_2026` accepté **seulement** sans `--ecrire`. |
| `--ecrire` | Crée puis supprime un évènement, en base d'entraînement seulement. Refusé sur `URCA_2026`. |
| `--attendre` | Avec `--ecrire` : attend **Entrée** avant de supprimer, pour regarder l'évènement dans Celcat. |
| `--seance` | Identifiant de séance précis (sinon la première de la règle). |
| `--comme-type` | Avec `--type` et `--seance` : traite cette séance comme si elle était de ce type (essai seulement). |
| `--group-id` | Groupe Celcat imposé. En base d'entraînement, défaut : 47925 (groupe des canaris). |
| `--json` | Écrit la charge et la relecture dans un fichier. |

Codes de sortie : 0 réussi ; 1 bloqué (motif affiché) ou suppression à refaire à la main ; 2 refusé ; 3 Celcat injoignable.
Ancien nom, toujours accepté : `celcat-essai-sans-module`.
## 6. Occupations hors MMI

> **Coupé par défaut.** `data/config/celcat_occupations.yaml` est livré avec `actif: false` :
> le robot ne relève rien et rien ne change tant que les essais ([A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md#occupations-hors-mmi))
> ne sont pas faits. Pour l'allumer : `actif: true`, redéployer, puis **Celcat → Occupations hors MMI → Relire maintenant**.

### À quoi ça sert

Celcat contient plus que nos cours. Deux cas comptent pour nous (demande de Kyllian Bresson, 01/10/2026) :

- **une salle prise ailleurs** : l'amphi H.018 (« Amphi 3 MMI » dans Celcat) est réservable par l'administration,
  un autre département, ou pour un évènement saisi hors de l'appli ;
- **un enseignant pris ailleurs** : le département TC programme Anthony Froli (AFR) le lundi de 10h00 à 12h30.

L'appli relève ces occupations et les traite **comme une séance déjà placée** :

| Où | Effet |
|---|---|
| Génération (`/solve`, régénération de semaine), lissage, suggestions, complétion | Créneau interdit à l'enseignant ; salle jamais attribuée |
| Placement manuel (déplacer, échanger, placer, créer, modifier, changer de salle) | Conflit **forçable** avec le motif exact ; refus si `strict: true` |
| Vue Enseignant, Vue Salle | Bloc hachuré **Occupé ailleurs (TC)** / **Réservé dans Celcat** ; **Conflit Celcat** sur une séance déjà posée |
| Vue Promo (placement en cours) | « AFR déjà occupé ailleurs (TC) » dans la case |
| Salles libres (écran et `/api/v1/salles/libres`) | Salle occupée (**Celcat**) |
| À traiter (écran et `/api/v1/a-traiter`) | Catégorie **Occupés ailleurs dans Celcat** (à corriger) : séances MMI déjà placées sur une occupation externe |

Messages au placement :

> Enseignant indisponible — Anthony Froli est déjà programmé dans le département TC sur ce créneau (lundi 28/09, 10h00–12h30, Celcat).
>
> Salle indisponible — H.018 est réservée dans Celcat sur ce créneau (administration, Conseil de département, mardi 29/09, 14h00–17h00).

**Forçable par défaut** : le relevé a jusqu'à deux heures, une réunion a pu être annulée entre-temps.
Le générateur, lui, ne force jamais. `strict: true` dans `data/config/celcat_occupations.yaml` rend le placement manuel impossible.

### D'où ça vient

Le backend ne joint pas Celcat (§ 4.1). C'est le service **celcat-nuit** qui lit, en **lecture seule** (rôle `985_consultation`) :

1. il résout l'identifiant Celcat de chaque ressource surveillée — **salles** : celles de `celcat.yaml`, en premier H.018 et les amphis partagés « Amphi 1 TC/GEA » et « Amphi 2 GMP/GEII » ;
   **enseignants** : tous ceux qui ont un code Celcat — avec deux catalogues (`udlResources.load` 604 et 603), plus les départements (610) ;
2. il charge leurs évènements par **lots** de 10 identifiants (`udlTimetables.load` avec `{"RoomIDs": [...]}` puis `{"StaffIDs": [...]}`) :
   une vingtaine de requêtes en tout, jamais une par créneau ; un lot refusé est coupé en deux ;
3. il écarte **nos** évènements : `event_id` au journal de synchronisation, `notes` = identifiant de séance cal-iut,
   cours d'un groupe « BUT MMI … », cours du département MMI sans groupe ; puis les fériés, évènements globaux, suspendus ou sans horaire ;
4. il déplie le masque `weeks` en dates, du lundi de la semaine courante au 31 juillet, avec l'**heure réelle**
   (le décalage historique de Paris, +00:09:21, est retiré) ;
5. il écrit **atomiquement** `data/state/celcat_occupations_externes.json` : horodatage, période, ressources surveillées
   (trouvées ou non), occurrences (ressource, date, début, fin, département abrégé, catégorie, intitulé, groupes, `event_id`),
   compteurs d'ignorés. Un relevé raté garde les occupations précédentes et note l'erreur.

Le backend relit ce fichier dès qu'il change (sonde de révision : les écrans se mettent à jour seuls),
et convertit chaque occurrence en **créneaux chevauchés** : 10h00-12h30 bloque 9h30-11h et 11h-12h30 (tolérance de 5 minutes).

### Fréquence

- **Toutes les 2 h** (`cadence_heures`), dans le même passage et la même session que l'instantané Celcat.
- **À la demande** : écran **Celcat → Occupations hors MMI → Relire maintenant** (prise en compte au passage suivant du robot, moins d'une minute).
- **À la main** dans le conteneur : `cal-iut celcat occupations --ecrire-fichier --vpn` (voir [A-TESTER-SUR-CELCAT.md](A-TESTER-SUR-CELCAT.md)).
- Robot en **pause** : rien n'est relu ; le dernier relevé reste appliqué.

### Ce que montre l'écran

**Celcat → Occupations hors MMI** (replié) : date du dernier relevé et son âge, période, ressources surveillées
(trouvées dans Celcat ou non) avec leur nombre d'occupations, séances déjà placées en conflit,
liste filtrable (texte, type, ressource), bouton **Relire maintenant**.

- **Aucun relevé** : rien n'est appliqué ; l'écran le dit.
- **Relevé ancien** (plus de `fraicheur_heures`, 6 h par défaut) : les contraintes restent appliquées telles quelles,
  un bandeau discret le signale dans les vues (« Occupations Celcat relevées il y a 9 h »).

### Que faire si c'est faux

| Constat | Geste |
|---|---|
| Une occupation n'existe plus dans Celcat (réunion annulée) | **Relire maintenant**. En attendant, **Forcer** le placement. |
| Un de NOS cours apparaît comme « occupé ailleurs » | Il n'a été reconnu ni par le journal, ni par ses `notes`, ni par son groupe. Le vérifier avec `cal-iut celcat occupations --ressource AFR --details`, puis ajuster `prefixes_groupes_mmi` / `departements_mmi`. |
| Une salle n'est jamais relue (« introuvable dans Celcat ») | Son libellé Celcat est faux dans `celcat.yaml` (`salles:`). Le corriger dans **Codes Celcat** ou le fichier. |
| Un enseignant n'est jamais relu | Pas de code Celcat (`0`), ou code faux : **Codes Celcat**. |
| Le département s'affiche mal (« Direction IUT » au lieu d'un sigle) | `libelles_departements` dans `celcat_occupations.yaml`. |
| Une catégorie ne devrait pas bloquer (ex. « Réservation BU ») | `categories_ignorees`. |
| Tout couper | `actif: false` (plus de relecture) ; supprimer `data/state/celcat_occupations_externes.json` lève toutes les contraintes. |

Code : `src/cal_iut/celcat/occupations.py` (lecture, sidecar), `src/cal_iut/celcat/session_lecture.py` (session lecture seule),
`src/cal_iut/api/occupations_externes.py` (conversion et application), `src/cal_iut/api/occupations_externes_routes.py` (écran),
`GET /api/v1/occupations-externes` (cf. [API.md](API.md)). Tests : `tests/test_occupations_externes_2026_10_01.py`.
