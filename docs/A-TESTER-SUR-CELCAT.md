# À tester sur Celcat

Ce document liste ce qui n'a **pas pu être essayé** contre le vrai Celcat pendant le développement (pas de VPN de l'université).
**Essais faits le 02/10/2026** : voir « Résultats » en fin de chaque section. Restent le canari PTUT et l'activation des règles d'envoi dans Dokploy.
Il est pour l'administrateur qui fera les essais, avec le VPN.
Chaque section est indépendante : une fonctionnalité, ses essais, ce qu'on doit voir, et un prompt prêt pour Claude Code.

**Règle commune à toutes les sections : ne jamais écrire dans `URCA_2026`** (la vraie base, celle de la paie).

**Interrupteur.** Les règles d'envoi (WR100BU, PTUT) sont **inactives** en production tant que `CAL_IUT_REGLES_ENVOI`
ne vaut pas `on` : rien ne part par le robot. La commande d'essai `cal-iut celcat-essai-regle` marche quand même.
Les écritures d'essai se font dans `URCA_FORMATION` (base d'entraînement). La lecture de `URCA_2026` est permise.

**Sommaire**

- [Envoi sans module (WR100BU / Valérie Mariot)](#envoi-sans-module-wr100bu--valérie-mariot)
- [Séances PTUT (catégorie Projet)](#séances-ptut-catégorie-projet)
- [Occupations hors MMI](#occupations-hors-mmi)

---

## Envoi sans module (WR100BU / Valérie Mariot)

Demande de Kyllian Bresson (01/10/2026). WR100BU (visite de la BU) est un code **inventé** : Celcat n'a pas de matière en face.
Les interventions de Valérie Mariot doivent quand même partir dans Celcat, ainsi :

| Champ Celcat | Valeur attendue |
|---|---|
| Enseignant | Valérie Mariot, code **3696** |
| Type d'évènement (catégorie) | **TD0** (pondération 0), pas « [TD] » |
| Salle | celle de la séance dans l'appli (H.101 sur le planning actuel) |
| Classe (groupe) | le groupe de la séance (ex. « BUT MMI S1 TD AB - 2024 ») |
| Matière | **aucune** |
| Remarque | `WR100BU - <identifiant de séance>`, ex. `WR100BU - WR100BU-S1-TD-1-but1-td-ab` |
| Département | **T_MMI T29** |

Fonctionnement complet : [CELCAT.md § 5](CELCAT.md#5-règles-denvoi--wr100bu-et-ptut).
Règle : `data/config/celcat.yaml`, section `regles_envoi`, bloc `cours: WR100BU`.

### 1. Où lancer l'essai

**A. Dans le conteneur du robot Celcat** (serveur, VPN monté par le conteneur avec `--vpn`).

D'abord : écran **Celcat → Réglages → Robot d'envoi** → **pause** (le VPN et le compte Celcat sont partagés).

- Code déjà déployé :

  ```bash
  docker compose run --rm -it celcat-nuit cal-iut celcat-essai-regle --cours WR100BU --base URCA_2026 --vpn
  ```

- Code de la branche, pas encore déployé (depuis une copie du dépôt sur le serveur) :

  ```bash
  docker build -t cal-iut-celcat -f deploy/celcat-sidecar/Dockerfile .
  docker run --rm -it --cap-add NET_ADMIN --device /dev/net/tun --env-file .env \
    -v cal-iut-data:/app/data/state cal-iut-celcat \
    cal-iut celcat-essai-regle --cours WR100BU --base URCA_2026 --vpn
  ```

  Le volume doit être **celui du backend** (même nom que dans `docker volume ls`) : l'essai y lit le planning.

**B. Depuis son PC** (VPN de l'université connecté à la main, client Cisco AnyConnect).

1. Copie du dépôt, sur la branche à tester. Python 3.11.
2. Installer : `pip install -e ".[dev]"`, puis `playwright install chromium`.
3. Fichier `.env` à la racine, avec au moins :
   - `CELCAT_URL` (adresse de Celcat) ;
   - `CELCAT_UTILISATEUR`, `CELCAT_MOT_DE_PASSE` (les mêmes que le VPN).
4. Connecter le VPN, puis vérifier l'accès : `cal-iut celcat-reseau` (doit dire « accès direct : OK »).
5. Lancer les commandes ci-dessous **sans** `--vpn` (le VPN est déjà monté).
   Sous Windows : `.venv\Scripts\cal-iut.exe` à la place de `cal-iut`.

Le planning lu est celui de la base locale (`data/state/cal-iut.db`) : il contient les 12 séances WR100BU de VMA.

### 2. Les commandes, dans l'ordre

1. **Simulation sur la vraie base** — lecture seule, rôle `985_consultation`, rien n'est écrit :

   ```bash
   cal-iut celcat-essai-regle --cours WR100BU --base URCA_2026 [--vpn]
   ```

   Elle dit si **TD0** et **T_MMI T29** existent dans `URCA_2026`, et montre la charge exacte qui partirait.

2. **Simulation sur la base d'entraînement** :

   ```bash
   cal-iut celcat-essai-regle --cours WR100BU [--vpn]
   ```

3. **Canari** : crée UN évènement dans `URCA_FORMATION`, attend **Entrée**, le relit, le supprime :

   ```bash
   cal-iut celcat-essai-regle --cours WR100BU --ecrire --attendre --json essai-wr100bu.json [--vpn]
   ```

   Pendant l'attente : ouvrir `URCA_FORMATION` dans Celcat (rôle `985_T_MMI`), groupe « BUT MMI S1 TD AB - 2024 »,
   semaine affichée par la commande, double-clic sur l'évènement.

4. Remettre le robot en marche (cas A).
5. **Une fois les essais concluants** (WR100BU et PTUT) : poser `CAL_IUT_REGLES_ENVOI=on` sur les services **backend**
   et **celcat-nuit** dans Dokploy, redéployer, puis vérifier le plan (`GET /celcat/plan` : « sans module (règle WR100BU) »)
   et l'écran **Celcat → Réglages** (« Règles d'envoi : actives »).

`--ecrire` avec `--base URCA_2026` est **refusé** avant toute connexion (code de sortie 2).

### 3. Ce qu'on doit voir

Simulation (1 et 2) :

- « Séances placées : 12 — envoyées par la règle : 12, autres : 0 » ;
- « Identifiants résolus » : `room_id`, `staff_id`, `event_cat_id`, `dept_id` — **pas** de `module_id` ;
- `event_cat_id` = **465** (TD0). Un autre nombre est refusé par le garde-fou, avec un message ;
- la séance : « sans module (règle WR100BU), module aucun » ;
- la charge : `"modules": []`, `"notes": "WR100BU - WR100BU-S1-TD-1-but1-td-ab"`, une seule semaine (`weeks` avec un seul `Y`) ;
- « SIMULATION — rien n'a été écrit ».

Canari (3), bloc « Relu dans Celcat » :

| Ligne | Attendu |
|---|---|
| `categorie` | `TD0` (éventuellement suivi d'une pondération) |
| `ponderation` | 0 (portée par la catégorie) |
| `departement` | `T_MMI T29` |
| `remarque (notes)` | `WR100BU - WR100BU-S1-TD-1-but1-td-ab` |
| `session_id lu dans notes` | `WR100BU-S1-TD-1-but1-td-ab` |
| `enseignants` | Valérie Mariot (code 3696) |
| `salles` | `H.101` (ou la salle de la séance) |
| `groupes` | le groupe TD AB |
| `matieres` | `[]` (aucune) |
| `semaines (Y)` | `1` |

Puis « Suppression : supprimé, absent à la relecture ». Code de sortie 0.

Dans l'inspecteur Celcat (pendant `--attendre`) :

- **Détails** : catégorie **TD0**, département **T_MMI T29** ;
- **Ressources** : la salle, le groupe, Valérie Mariot, **Matières [0]** ;
- **Remarques et personnaliser** : `WR100BU - WR100BU-S1-TD-1-but1-td-ab` dans « Remarques ».

### 4. Points incertains à vérifier dans Celcat

1. **Le champ de la Remarque.** L'appli écrit dans `notes` (le seul champ texte de l'évènement prouvé en écriture, canari du 01/09/2026).
   À confirmer : c'est bien la zone « Remarques » de l'onglet « Remarques et personnaliser ».
   Si Kyllian attend `WR100BU` dans un champ « personnaliser » (`custom1`…), le dire : la relecture affiche `custom1` à `custom3`.
2. **La forme de la Remarque.** `WR100BU - <identifiant>` et non `WR100BU` seul : l'identifiant y relie l'évènement à l'appli.
   À faire valider par Kyllian.
3. **Le libellé « TD0 ».** Cherché par son nom exact dans le catalogue des catégories. Identifiant relevé : 465 (audit du 07/09/2026 sur `URCA_2026`).
   À confirmer dans `URCA_FORMATION` aussi : sinon le garde-fou refuse le canari (message « attend event_cat_id=465 »).
   Liste complète : `python scripts/investiguer_categories_celcat.py --base URCA_2026 [--vpn]`.
4. **Le libellé « T_MMI T29 ».** Cherché par son nom exact dans le catalogue des départements. Jamais relevé par identifiant.
5. **Un évènement sans matière.** `"modules": []` à la création : jamais essayé. Si Celcat le refuse, le message s'affiche.
6. **Le groupe en base d'entraînement.** Les identifiants de `celcat_groupes.yaml` sont ceux d'`URCA_2026`.
   En `URCA_FORMATION`, l'essai prend le groupe des canaris (47925, « BUT MMI S1 TD AB - 2024 ») ; `--group-id` pour un autre.

### 5. Prompt pour Claude Code (sur le PC, VPN connecté)

À coller tel quel dans Claude Code, ouvert à la racine du dépôt :

```text
Contexte : dépôt cal-iut (FastAPI + SQLite dans src/cal_iut/, React dans frontend/). Je suis sur mon PC,
VPN de l'université CONNECTÉ, fichier .env rempli (CELCAT_URL, CELCAT_UTILISATEUR, CELCAT_MOT_DE_PASSE).

But : finir la mise au point de « l'envoi sans module » de WR100BU (visite de la BU, Valérie Mariot,
code Celcat 3696), demandé par Kyllian Bresson le 01/10/2026. Dans Celcat, chaque séance doit avoir :
enseignant 3696, catégorie TD0, salle et groupe de la séance, AUCUNE matière, remarque « WR100BU - <id> »,
département T_MMI T29.

À lire d'abord : docs/A-TESTER-SUR-CELCAT.md (section « Envoi sans module »), docs/CELCAT.md § 5,
data/config/celcat.yaml (section regles_envoi), src/cal_iut/celcat/essai_regle.py,
src/cal_iut/celcat/ecriture.py (resoudre_ids, charge_utile), src/cal_iut/celcat/categories.py
(verifier_charge_categorie, CATEGORIE_IDS_REGLES), tests/test_celcat_regles_envoi_2026_10_01.py.

RÈGLE ABSOLUE : ne jamais écrire dans URCA_2026. Lecture seule sur URCA_2026 (simulation, rôle
985_consultation). Toute écriture se fait dans URCA_FORMATION, via la commande d'essai, qui supprime
son évènement à la fin. Ne pas lancer le robot (celcat_nuit.py, celcat_immediat.py) ni --production.
Les règles sont inactives (CAL_IUT_REGLES_ENVOI=off) : ne pas les activer ; la commande d'essai les force pour elle seule.

Étapes :
1. cal-iut celcat-reseau : l'accès direct doit être OK.
2. cal-iut celcat-essai-regle --cours WR100BU --base URCA_2026 : lire les identifiants résolus.
   Si « catégorie TD0 introuvable » ou « département T_MMI T29 introuvable » : lancer
   python scripts/investiguer_categories_celcat.py --base URCA_2026, trouver le libellé exact, et proposer
   la correction de celcat.yaml (ne pas inventer d'identifiant).
3. cal-iut celcat-essai-regle --cours WR100BU --ecrire --attendre --json essai-wr100bu.json
   (base URCA_FORMATION). Pendant l'attente, je vérifie l'inspecteur Celcat et je te dis ce que je vois.
4. Analyser essai-wr100bu.json et la sortie. Corriger le code si besoin (champ de la remarque, forme de la
   charge, refus de Celcat), avec des tests dans tests/test_celcat_regles_envoi_2026_10_01.py.
   Lancer : python -m pytest -q -p no:cacheprovider tests/test_celcat_regles_envoi_2026_10_01.py
   puis tous les tests dont le nom contient « celcat ».
5. Recommencer 3 jusqu'à réussite, puis mettre à jour docs/A-TESTER-SUR-CELCAT.md (résultats, date)
   et docs/CELCAT.md.

Critères de réussite :
- simulation URCA_2026 : event_cat_id de TD0 et dept_id de T_MMI T29 résolus par leur nom, aucun module_id,
  aucun appel de recherche de matière ;
- canari URCA_FORMATION : relu avec catégorie TD0, département T_MMI T29, remarque « WR100BU - <id> »
  visible dans l'onglet « Remarques et personnaliser », enseignant 3696, salle et groupe de la séance,
  aucune matière, une seule semaine ; puis « supprimé, absent à la relecture » ;
- aucune écriture dans URCA_2026 ; tests verts.
Commits en français, préfixe « add | ». Ne pas pousser sur main.
```

### Résultats

**Essais du 02/10/2026.** Conteneur du robot lancé sur le poste de Jules (image `cal-iut-celcat`, VPN OpenConnect),
robot de production en pause, planning de la base locale.

| Étape | Résultat |
|---|---|
| 1. Simulation sur `URCA_2026` (lecture seule) | **Conforme.** 12 séances, 12 sous la règle. `event_cat_id` **465** (TD0), `dept_id` 1560615 (T_MMI T29), `room_id` 1604465 (H.101), `staff_id` 1607660 (code 3696), groupe 1661972. Pas de `module_id`, `"modules": []`, un seul `Y`. |
| 2. Simulation sur `URCA_FORMATION` | **Conforme.** TD0 = 465 là aussi ; `dept_id` 936, `room_id` 100907, `staff_id` 2660 ; groupe des canaris 47925. |
| 3. Canari dans `URCA_FORMATION` (sans `--attendre`) | **Conforme**, après un correctif (ci-dessous). Évènement 1523419 créé, relu : catégorie TD0, pondération 0, département T_MMI T29, salle H.101, groupe « BUT MMI S1 TD AB - 2024 », enseignante MARIOT Valerie, `matieres` `[]`, une semaine. Puis « supprimé, absent à la relecture ». Code 0. |

**Le canari a montré un défaut, corrigé.** La remarque était d'abord écrite `WR100BU — <identifiant>`, avec un tiret long.
Celcat l'a gardée sous la forme `WR100BU â€” <identifiant>` : il abîme les caractères hors ASCII à l'écriture,
et l'appli ne retrouvait plus son identifiant dans la remarque. La remarque s'écrit maintenant
**`WR100BU - <identifiant>`** (tiret simple), relue telle quelle, et l'identifiant est lu comme le dernier mot.
Conséquence pour `celcat.yaml` : **pas d'accent ni de caractère spécial dans `remarque:`**.

Points incertains du § 4 :

- **3 levé** : « TD0 » porte l'identifiant 465 dans les deux bases.
- **4 levé** : « T_MMI T29 » est trouvé par son nom (1560615 dans `URCA_2026`, 936 dans `URCA_FORMATION`).
- **5 levé** : Celcat accepte un évènement sans matière.
- **6 confirmé** : en base d'entraînement, le groupe pris est bien celui des canaris.
- **1 et 2 restent ouverts** : personne n'a regardé l'onglet « Remarques et personnaliser » de l'inspecteur
  (le canari a tourné sans `--attendre`), et Kyllian doit dire si `WR100BU - <identifiant>` lui convient
  (sa demande disait « Remarque : WR100BU »). `custom1` à `custom3` sont relus vides.

**Reste à faire pour que les séances partent** : poser `CAL_IUT_REGLES_ENVOI=on` sur les services **backend** et **celcat-nuit**
dans Dokploy, puis redéployer (étape 5 du § 2). Tant que ce n'est pas fait, rien ne part.

À savoir pour refaire l'essai :

- Celcat était lent ce jour-là (page d'accueil en 30 à 45 s). La connexion échouait une fois sur trois ;
  elle recharge maintenant l'accueil et attend l'affichage du rôle.
- Avec le code monté dans le conteneur (`-v "$PWD:/app"`), `data/state` est **vide** : l'image y déclare un volume.
  Ajouter `-v "$PWD/data/state:/app/data/state"`, ou le volume du backend comme au § 1.
- Le message « le robot Celcat n'est pas en pause » lit l'état **local**, pas celui de la production : sans objet sur un PC.

---

## Séances PTUT (catégorie Projet)

Demande de Kyllian Bresson (01/10/2026) : **toutes** les séances de type PTUT, quel que soit le cours, partent dans Celcat ainsi :

| Champ Celcat | Valeur attendue |
|---|---|
| Type d'évènement (catégorie) | **Projet**, pondération 0 (portée par la catégorie : « Projet [0%] ») |
| Enseignant | celui de la séance (Celcat n'en reçoit qu'un : le premier) |
| Salle | celle de la séance |
| Classe (groupe) | le groupe de la séance |
| Matière | celle **du cours** si son code Celcat est connu ; **aucune** sinon. Jamais une matière « PTUT » |
| Remarque | `PTUT - <identifiant de séance>` |
| Département | **T_MMI T29** |

« Oui, on veut pouvoir mettre un module » (réponse du 01/10/2026) : d'où la matière du cours.
Règle : `data/config/celcat.yaml`, section `regles_envoi`, bloc `types: PTUT` (`module: cours`).
Avant cette règle, une séance PTUT était **bloquée** (« type de séance PTUT sans code Celcat »).

**Sur le planning actuel il n'y a aucune séance PTUT.** L'essai prend donc une vraie séance comme support,
traitée « comme une PTUT » (`--comme-type`) : rien ne change pour le plan ni pour le robot.

### 1. Où lancer l'essai

Comme pour WR100BU ([§ 1 ci-dessus](#1-où-lancer-lessai)) : conteneur du robot (robot en **pause**), ou PC avec VPN.

### 2. Les commandes, dans l'ordre

Deux cas à essayer : un cours **avec** code Celcat (matière posée), un cours **sans** code (aucune matière).

1. Choisir les séances support (sans réseau) : un TD d'un cours avec code, par ex. `WR101-S1-TD-1-but1-td-ab`
   (WR101 → `TSBZ1M01`) ; et une séance d'un cours sans code, s'il y en a une (**Référence → Codes Celcat**, filtre **Sans code**).
2. **Simulation sur la vraie base**, cours avec code :

   ```bash
   cal-iut celcat-essai-regle --type PTUT --seance WR101-S1-TD-1-but1-td-ab --comme-type --base URCA_2026 [--vpn]
   ```

   Elle dit si la catégorie **Projet** existe dans `URCA_2026` et montre la charge, avec `"modules": [{"module_id": …}]`.
3. **Simulation**, cours sans code : même commande avec l'autre séance. Attendu : `"modules": []`.
4. **Canari** en base d'entraînement (crée, attend **Entrée**, relit, supprime) :

   ```bash
   cal-iut celcat-essai-regle --type PTUT --seance WR101-S1-TD-1-but1-td-ab --comme-type \
     --ecrire --attendre --json essai-ptut.json [--vpn]
   ```

`--ecrire` avec `--base URCA_2026` est **refusé** avant toute connexion.

Dernière étape, commune aux deux règles : activer avec `CAL_IUT_REGLES_ENVOI=on` ([§ 2 de WR100BU, étape 5](#2-les-commandes-dans-lordre)).

### 3. Ce qu'on doit voir

- La séance : « module du cours (règle PTUT), module TSBZ1M01 » ou « sans module — cours sans code Celcat (règle PTUT), module aucun ».
- Identifiants résolus : `event_cat_id` de **Projet**, `dept_id` de T_MMI T29 ; `module_id` seulement pour le cours avec code.
- Jamais de recherche d'une matière « PTUT ».
- Canari, « Relu dans Celcat » :

| Ligne | Attendu |
|---|---|
| `categorie` | `Projet` (éventuellement `Projet [0%]`) |
| `ponderation` | 0 |
| `departement` | `T_MMI T29` |
| `remarque (notes)` | `PTUT - WR101-S1-TD-1-but1-td-ab` |
| `matieres` | la matière du cours (WR101 Anglais / TSBZ1M01), ou `[]` pour le cours sans code |
| `salles`, `groupes`, `enseignants` | ceux de la séance support |

Puis « supprimé, absent à la relecture ».

### 4. Points incertains à vérifier dans Celcat

1. **Le libellé exact de la catégorie « Projet ».** L'inspecteur affiche « Projet [0%] » ; le catalogue doit porter « Projet ».
   Aucun identifiant relevé. Liste : `python scripts/investiguer_categories_celcat.py --base URCA_2026 [--vpn]`.
   S'il s'appelle autrement, corriger `categorie:` dans `celcat.yaml` (ne jamais mettre un identifiant deviné).
2. **La pondération 0.** Elle doit venir de la catégorie : la relecture affiche `ponderation` (champ `evCatWeighting`, en lecture seule).
   Aucun champ « pondération » n'est écrit par l'appli : il n'existe pas à l'écriture.
3. **Le module du cours.** À faire confirmer par Kyllian : la matière du cours plutôt qu'aucune.
4. **Plusieurs enseignants ou plusieurs groupes.** Celcat ne reçoit qu'un enseignant (le premier) ; une séance à plusieurs groupes reste bloquée,
   comme toute séance. À signaler si des PTUT en ont.
5. Le champ de la Remarque : mêmes questions que pour WR100BU ([§ 4 ci-dessus](#4-points-incertains-à-vérifier-dans-celcat)).

### 5. Prompt pour Claude Code (sur le PC, VPN connecté)

```text
Contexte : dépôt cal-iut, PC avec VPN de l'université CONNECTÉ, .env rempli (CELCAT_URL, CELCAT_UTILISATEUR,
CELCAT_MOT_DE_PASSE). But : finir la mise au point de la règle d'envoi PTUT (Kyllian Bresson, 01/10/2026) :
toute séance de type PTUT part dans Celcat en catégorie « Projet » (pondération 0), remarque « PTUT - <id> »,
département T_MMI T29, enseignant/salle/groupe de la séance, et la matière DU COURS si son code est connu
(aucune sinon ; jamais une matière « PTUT »).

À lire : docs/A-TESTER-SUR-CELCAT.md (section « Séances PTUT »), docs/CELCAT.md § 5, data/config/celcat.yaml
(regles_envoi.types.PTUT), src/cal_iut/celcat/mapping.py (regle_pour, RegleEnvoi), src/cal_iut/celcat/ecriture.py
(_resoudre_ids_regle), src/cal_iut/celcat/essai_regle.py, tests/test_celcat_regles_envoi_2026_10_01.py.

RÈGLE ABSOLUE : ne jamais écrire dans URCA_2026 (lecture seule permise). Écritures d'essai uniquement dans
URCA_FORMATION, par la commande d'essai, qui supprime son évènement. Ne pas lancer le robot ni --production.
Les règles sont inactives (CAL_IUT_REGLES_ENVOI=off) : ne pas les activer ; la commande d'essai les force pour elle seule.

Étapes :
1. cal-iut celcat-reseau (accès direct OK).
2. python scripts/investiguer_categories_celcat.py --base URCA_2026 : relever le libellé et l'id exacts de « Projet ».
3. cal-iut celcat-essai-regle --type PTUT --seance WR101-S1-TD-1-but1-td-ab --comme-type --base URCA_2026
   puis la même avec une séance d'un cours sans code Celcat.
4. cal-iut celcat-essai-regle --type PTUT --seance WR101-S1-TD-1-but1-td-ab --comme-type --ecrire --attendre
   --json essai-ptut.json ; je vérifie l'inspecteur pendant l'attente.
5. Si « Projet » a un autre libellé : corriger celcat.yaml. Si son id est stable, l'ajouter à
   categories.CATEGORIE_IDS_REGLES (contre-vérification) avec un test. Corriger le code si Celcat refuse la charge.
   Tests : python -m pytest -q -p no:cacheprovider tests/test_celcat_regles_envoi_2026_10_01.py, puis ceux « celcat ».
6. Mettre à jour docs/A-TESTER-SUR-CELCAT.md (résultats, date) et docs/CELCAT.md.

Critères de réussite : catégorie Projet résolue par son nom ; pondération relue = 0 ; module_id présent pour le cours
avec code et absent sinon ; aucune recherche de matière « PTUT » ; remarque « PTUT - <id> » visible dans l'onglet
« Remarques et personnaliser » ; évènement supprimé à la relecture ; aucune écriture dans URCA_2026 ; tests verts.
Commits en français, préfixe « add | ». Ne pas pousser sur main.
```

### Résultats (PTUT)

**Essais du 02/10/2026**, mêmes conditions que pour WR100BU.

| Étape | Résultat |
|---|---|
| Catalogue des catégories de `URCA_2026` | 38 catégories. **« Projet » existe sous ce nom exact, id 456.** |
| Simulation sur `URCA_2026`, cours avec code (WR101) | **Conforme.** `event_cat_id` 456, `dept_id` 1560615, `module_id` 1585129 (TSBZ1M01), un seul `Y`. |
| Simulation, cours sans code | **Pas faisable** : aucune des 2 384 séances placées n'appartient à un cours sans code Celcat. Le cas reste couvert par les tests ; l'envoi sans matière, lui, est prouvé par le canari WR100BU. |
| Simulation sur `URCA_FORMATION` | **Bloquée** : « introuvable dans Celcat : matière TSBZ1M01 ». La matière de WR101 n'existe pas en base d'entraînement. |
| Canari | **Pas fait.** Avec WR101 il serait bloqué pour la même raison : prendre comme support une séance dont la matière existe dans `URCA_FORMATION`. |

Points incertains du § 4 :

- **1 levé** pour `URCA_2026` : le libellé est « Projet », rien à corriger dans `celcat.yaml`.
  L'id 456 n'a **pas** été ajouté à `categories.CATEGORIE_IDS_REGLES` : on ne sait pas s'il est le même en base d'entraînement.
- **2 reste ouvert** : la pondération de « Projet » n'a pas été relue (pas de canari).
- **3, 4 et 5** : confirmations de Kyllian. La remarque s'écrit `PTUT - <identifiant>` (tiret simple, voir WR100BU).

Le planning n'a aucune séance PTUT : la règle ne fait rien pour l'instant, même activée.

---

## Occupations hors MMI

Demande de Kyllian Bresson (01/10/2026) : lire Celcat pour savoir si une salle (surtout l'amphi H.018) ou un enseignant
est déjà pris **hors MMI** (autre département, administration, réunion), et en tenir compte au placement et à la génération.
Fonctionnement complet : [CELCAT.md § 6](CELCAT.md#6-occupations-hors-mmi).
Tout est en **lecture seule** (rôle `985_consultation`, `udlResources.load` et `udlTimetables.load` uniquement) :
ne jamais écrire dans `URCA_2026` pendant ces essais.
Salles surveillées en priorité : H.018 (« Amphi 3 MMI »), « Amphi 1 TC/GEA », « Amphi 2 GMP/GEII » ; puis toutes nos salles
qui ont un libellé Celcat ; enseignants : tous ceux qui ont un code Celcat.

**Activé le 02/10/2026** après les essais (`actif: true` dans `data/config/celcat_occupations.yaml`). Pour couper : `actif: false`,
puis redéployer. Après un déploiement : **Celcat → Occupations hors MMI → Relire maintenant**, et vérifier l'écran.

### 1. Se placer là où Celcat est joignable

**Option A — dans le conteneur du robot (recommandé : VPN et identifiants déjà en place).**

Sur la machine qui héberge l'appli (Dokploy) :

```bash
# Nom exact du conteneur (Dokploy le préfixe par le nom du projet)
docker ps --filter "name=celcat-nuit" --format "{{.Names}}"
# Entrer dedans (remplacer <nom> par la ligne affichée, ex. cal-iut-celcat-nuit-1)
docker exec -it <nom> bash
cd /app
```

Avec Docker Compose dans le dossier du projet : `docker compose exec celcat-nuit bash`.
Les variables `CELCAT_URL`, `CELCAT_UTILISATEUR`, `CELCAT_MOT_DE_PASSE` (et `VPN_*` facultatives) sont déjà dans le conteneur.
La boucle du robot continue de tourner à côté : ce n'est pas gênant (lecture seule), mais lancer les essais
**hors des heures de saisie** de l'équipe (le compte et le VPN sont partagés).

**Option B — depuis le PC de l'admin, VPN Cisco AnyConnect déjà connecté (ou sur place à l'IUT).**

```powershell
# Une fois : dépendances et navigateur
.venv\Scripts\pip install -e ".[dev]" playwright python-dotenv
.venv\Scripts\python -m playwright install chromium
# .env à la racine du dépôt (jamais commité) :
#   CELCAT_URL=https://celcat-lv.univ-reims.fr/...
#   CELCAT_UTILISATEUR=...      (identifiant du VPN)
#   CELCAT_MOT_DE_PASSE=...     (mot de passe du VPN)
.venv\Scripts\cal-iut.exe celcat-reseau        # doit dire « accès direct : OK »
```

Sans VPN déjà monté, ajouter `--vpn` aux commandes (OpenConnect, Linux seulement ; variables `VPN_*`).
Sur le PC, le journal de synchronisation (`data/state/celcat_sync.json`) est celui du poste, souvent vide :
la reconnaissance « écrit par cal-iut (journal) » ne jouera pas, les autres règles si.

### 2. Lancer la lecture

```bash
cal-iut celcat occupations --ressource H018
cal-iut celcat occupations --ressource amphi1_tc_gea,amphi2_gmp_geii
cal-iut celcat occupations --ressource AFR
cal-iut celcat occupations --ressource AFR --details     # montre aussi ce qui est ignoré, et pourquoi
cal-iut celcat occupations --ressource H018,AFR --du 2026-10-05 --au 2026-10-31
```

Dans le conteneur, ajouter `--vpn` si le robot n'a pas déjà le tunnel monté (`cal-iut celcat-reseau` le dit).
Une fois satisfait, écrire le fichier complet que l'appli utilise (toutes les ressources) :

```bash
cal-iut celcat occupations --ecrire-fichier --vpn
```

(`--ecrire-fichier` est ignoré avec `--ressource` : un relevé partiel effacerait les autres ressources.)
Sinon, le robot l'écrit tout seul dans les 2 h, ou tout de suite après **Celcat → Occupations hors MMI → Relire maintenant**.

### 3. Ce qu'on doit voir

```
Connecté à URCA_2026 en lecture seule.
Période : 2026-09-28 → 2027-07-31 · 4 requête(s) RPC

salle h018 (H.018 (Amphi MMI) — Celcat « Amphi 3 MMI », id Celcat 1604428) : 3 occupation(s) hors MMI
    mar. 06/10/2026 14:00–17:00 · Direction IUT · Réunion · Conseil de département · event 19xxxxx
    …
Ignorés (à nous, ou non pertinents) : cours d'un groupe MMI × 40, écrit par cal-iut (notes) × 12, jour férié × 3
```

À vérifier, ressource par ressource :

- la ressource est **trouvée** (« id Celcat … ») — sinon son libellé ou son code Celcat est faux ;
- chaque ligne existe bien dans Celcat, **au bon jour et à la bonne heure** (ouvrir l'emploi du temps de la salle ou de
  l'enseignant dans Celcat, rôle consultation) ;
- **aucun de nos cours MMI** n'apparaît dans la liste (il doit être compté dans « Ignorés ») ;
- le **département** affiché est le bon sigle (« TC », « GEA »…) ; sinon, le noter pour `libelles_departements` ;
- dans l'appli, après `--ecrire-fichier` : **Celcat → Occupations hors MMI** affiche la date du relevé et les mêmes nombres,
  et la Vue Enseignant d'AFR montre les blocs « Occupé ailleurs (TC) ».

### 4. Ce qui est incertain (jamais vu sur le vrai Celcat)

1. **La clé de filtre des enseignants.** `udlTimetables.load` avec `{"RoomIDs": [...]}` a été employé une fois
   (`scripts/verifier_conflit_h018.py`, 06/09/2026). `{"StaffIDs": [...]}` vient de `scripts/verifier_planning_huez.py`,
   qui essayait aussi `StaffID` : on ne sait pas laquelle a marché. Le code essaie `StaffIDs` puis `StaffID`
   (`cles_filtre_enseignants` dans `data/config/celcat_occupations.yaml`). Un lot refusé est coupé en deux.
2. **Plusieurs identifiants dans un même appel.** Les lots de 10 (`lot: 10`) n'ont jamais été essayés : si Celcat
   n'accepte qu'un identifiant, mettre `lot: 1` (≈ 100 requêtes au lieu de ≈ 15).
3. **Ce que contient un évènement chargé par salle ou enseignant** : `deptName` (renvoyé par `load` d'après
   `rpc.CHAMPS_CLIENT`) et `dept_id` ; ids dans `rooms[]` / `staff[]` (`id` ou `room_id` / `staff_id`) ;
   `unique_name` du personnel = notre code Celcat (« 37948 »). L'attribution d'un évènement à la bonne ressource
   repose sur ces champs (repli : nom Celcat, puis lot d'une seule ressource).
4. **Les heures.** Le décalage historique de Paris (+00:09:21) est retiré quand les secondes ne sont pas nulles
   (« 13:50:39Z » → 14:00). Dans le conteneur (navigateur en UTC), les heures arrivent sans décalage. À comparer
   avec Celcat sur quelques lignes.
5. **La reconnaissance de nos évènements** : `event_id` au journal, `notes` = identifiant de séance (`charge_utile`),
   cours d'un groupe « BUT MMI … », cours du département « T_MMI » sans groupe. Les évènements MMI saisis à la main
   par l'équipe sans groupe MMI (réunion pédagogique, par exemple) **comptent** comme occupation : c'est voulu,
   à confirmer avec Kyllian.
6. **Les départements** : sigle déduit de « T_TC T27 » → « TC ». Les noms de l'administration (« Direction IUT » ?)
   sont affichés tels quels.
7. **Les évènements à date unique** (sans masque `weeks`, s'il en existe) ne sont pas lus : seul `weeks` est déplié.
8. **Le volume** : nombre d'évènements par enseignant sur l'année, durée du relevé (affichée en fin de commande),
   poids du fichier. Le robot le refait toutes les 2 h dans la même session que l'instantané.

### 5. Prompt à coller dans Claude Code (sur le PC, VPN connecté)

```text
Contexte : dépôt cal-iut (emploi du temps IUT MMI Troyes ; FastAPI + SQLite + OR-Tools dans src/cal_iut/,
React/TS dans frontend/). La fonction « Occupations hors MMI » lit Celcat (lecture seule) pour connaître les
salles et enseignants pris hors MMI et en fait des contraintes. Elle a été écrite SANS accès à Celcat :
il faut la mettre au point sur le vrai Celcat. Je suis connecté au VPN de l'URCA ; .env contient CELCAT_URL,
CELCAT_UTILISATEUR, CELCAT_MOT_DE_PASSE.

Lis d'abord : docs/CELCAT.md (§ 4 et § 5), docs/A-TESTER-SUR-CELCAT.md (section « Occupations hors MMI »),
src/cal_iut/celcat/occupations.py, src/cal_iut/celcat/session_lecture.py, src/cal_iut/celcat/rpc.py,
src/cal_iut/celcat/lecture.py, data/config/celcat_occupations.yaml, data/config/celcat.yaml (salles, enseignants),
tests/test_occupations_externes_2026_10_01.py.

RÈGLE ABSOLUE : ne jamais écrire dans Celcat, et en particulier jamais dans la base URCA_2026. Uniquement le rôle
985_consultation (session_lecture le force), uniquement udlResources.load et udlTimetables.load. N'appelle
jamais udlTimetables.save, ni aucun script d'écriture (celcat_immediat, celcat_nuit, pousser_manquants…).
Déconnecte-toi de Celcat à la fin de chaque essai (session_lecture le fait).

Étapes :
1. `cal-iut celcat-reseau` (accès direct OK ?).
2. `cal-iut celcat occupations --ressource H018 --details`, puis `--ressource amphi1_tc_gea,amphi2_gmp_geii --details`,
   puis `--ressource AFR --details`.
   Si une ressource est « INTROUVABLE » ou si un appel échoue, écris un petit script de diagnostic en lecture
   seule (sur le modèle de scripts/verifier_conflit_h018.py, avec session_lecture) qui affiche les clés brutes
   d'un enregistrement udlResources (603, 604, 610) et d'un évènement udlTimetables.load, puis corrige
   occupations.py (clés d'identifiants, clé de filtre StaffIDs/StaffID, taille de lot, heures).
3. Compare 3 ou 4 lignes avec l'emploi du temps affiché dans Celcat (jour, heures, département).
4. Vérifie qu'aucun cours MMI n'apparaît comme occupation externe ; sinon ajuste motif_a_nous ou la config.
5. Enregistre un relevé réel ANONYMISÉ et réduit (2-3 évènements par cas) en fixture de test
   (tests/fixtures/celcat_occupations_releve.json) et ajoute un test qui le rejoue avec PageSimulee.
6. `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_occupations_externes_2026_10_01.py` doit passer.
7. Mets à jour docs/A-TESTER-SUR-CELCAT.md (ce qui est confirmé, ce qui reste) et docs/CELCAT.md § 6.

Critères de réussite : H.018, les deux amphis partagés et AFR trouvés ; leurs occupations hors MMI correspondent à Celcat (jour, heure
réelle, département) ; aucun de nos évènements dans la liste ; `cal-iut celcat occupations --ecrire-fichier`
produit un fichier que l'écran Celcat → Occupations hors MMI affiche ; tests verts ; aucun appel d'écriture.
Commits en français au style du dépôt (`add | …`, `fix | …`).
```

### Résultats (occupations)

**Essais du 02/10/2026**, mêmes conditions. Lecture seule : `udlResources.load` et `udlTimetables.load` uniquement.
**La lecture est activée depuis ce jour** (`actif: true`).

Relevé complet (`--ecrire-fichier`, dans le conteneur) : **97 ressources, 74 trouvées, 11 requêtes, 61 s** de lecture
(111 s connexion comprise), fichier de 350 Ko, aucune erreur.
**799 occupations hors MMI** une fois la réservation de l'amphi par MMI écartée (909 avant).

| Point du § 4 | Constat |
|---|---|
| 1. Clé de filtre des enseignants | **`StaffIDs` fonctionne. `StaffID` n'existe pas** (« There is no property named 'StaffID' ») : le repli de la configuration ne sert à rien, sans gêner. |
| 2. Plusieurs identifiants par appel | **Accepté** : lots de 10, salles comme enseignants. `lot: 10` peut rester. |
| 3. Contenu d'un évènement | **Confirmé** : `deptName` et `dept_id` ; `room_id` dans `rooms[]`, `staff_id` dans `staff[]` ; `unique_name` du personnel = notre code Celcat. |
| 4. Heures | **Justes dans le conteneur** (`08:00:00.000Z`, sans décalage). Le cas d'un PC réglé sur Paris (décalage de 9 min 21) n'a pas été essayé. |
| 5. Reconnaissance de nos évènements | **Corrigée.** Les identifiants portant des minuscules et les remarques de règle n'étaient pas reconnus par les `notes`. Après correctif : 3 414 évènements reconnus par la remarque, 493 par le journal, 58 par leur groupe MMI. |
| 6. Départements | `T_TC T32` → TC, `T_GEA T22` → GEA, `R_CS R14` → CS. **Corrigé** : `T_ CJ T41` (écrit avec une espace dans Celcat) → CJ. Restent tels quels : `CCC_DROI N01`, `CCC_LET N02`, `CCC_SESG N04`, `droit D00`, `iut Troyes T00`, `EISINE F00` — à abréger dans `libelles_departements` si besoin. |
| 7. Évènements à date unique | Pas rencontré. |
| 8. Volume | Voir ci-dessus. Le plus chargé : 142 occupations pour un seul enseignant. |

**La réservation de l'amphi par MMI n'est plus comptée.** Cinq évènements « Réservation Amphi H MMI »
(département T_MMI T29, sans catégorie, groupe, enseignant ni matière, 8h00–20h00, lundi à vendredi, 22 semaines)
faisaient 110 des 129 occupations de H.018 : l'amphi aurait été interdit à nos propres CM.
Règle retenue (`reservations_mmi_ignorees: true` dans `celcat_occupations.yaml`) : un évènement du département MMI
sans catégorie, groupe, enseignant ni matière est une salle gardée par MMI, pas une occupation.
Une activité MMI saisie à la main avec une catégorie (Réunion, Conférence…) compte toujours. **À confirmer par Kyllian.**

**Effet sur le planning de production**, simulé avant l'activation (2 557 séances placées, lecture seule) :
**11 séances** en conflit avec une occupation hors MMI, toutes plausibles —
A.018 prise par CJ ou TC en même temps qu'un CM (7), H.018 prise par CJ le lundi 11/01 (1),
Régis Huez (2), Kyllian Bresson (1) et Anthony Froli (1) programmés dans un autre département.
Elles apparaîtront dans **À traiter → Occupés ailleurs dans Celcat**. Les 255 séances créées dans l'appli
(hors maquette) n'ont pas pu être simulées.

**23 enseignants n'ont pas de fiche dans le personnel de `URCA_2026`** (ni par code, ni par nom) :
ABE, ADH, AGU, APA, CDE, CMA, CPI, ECO, ENO, GDO, GDR, GLS, JLA, JPI, JSL, MGL, MPI, PCA, RGY, SHN, THE, VDI, VNG.
Leurs occupations ne peuvent pas être lues, et leurs séances ne peuvent pas partir dans Celcat. À signaler à Kyllian.

Pas fait : la comparaison ligne à ligne avec l'emploi du temps **affiché** dans Celcat (étape 3 du prompt),
l'écran **Occupations hors MMI** vu dans un navigateur avec un vrai relevé (ses données ont été calculées sans erreur),
et le relevé réel anonymisé en fixture de test (étape 5).

Corrigé au passage (tests : `tests/test_celcat_essais_reels_2026_10_02.py`) : `cal-iut celcat-reseau --connecter` annonçait
« accès via le VPN : NON » sur un tunnel bon six secondes plus tard ; les jours fériés, que Celcat renvoie avec chaque lot,
étaient comptés « non attribué × 88 » au lieu de « jour férié × 11 ».
