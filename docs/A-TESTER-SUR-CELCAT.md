# À tester sur Celcat

Ce document liste ce qui n'a **pas pu être essayé** contre le vrai Celcat pendant le développement (pas de VPN de l'université).
Il est pour l'administrateur qui fera les essais, avec le VPN.
Chaque section est indépendante : une fonctionnalité, ses essais, ce qu'on doit voir, et un prompt prêt pour Claude Code.

**Règle commune à toutes les sections : ne jamais écrire dans `URCA_2026`** (la vraie base, celle de la paie).
Les écritures d'essai se font dans `URCA_FORMATION` (base d'entraînement). La lecture de `URCA_2026` est permise.

**Sommaire**

- [Envoi sans module (WR100BU / Valérie Mariot)](#envoi-sans-module-wr100bu--valérie-mariot)
- [Séances PTUT (catégorie Projet)](#séances-ptut-catégorie-projet)

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
| Remarque | `WR100BU — <identifiant de séance>`, ex. `WR100BU — WR100BU-S1-TD-1-but1-td-ab` |
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

`--ecrire` avec `--base URCA_2026` est **refusé** avant toute connexion (code de sortie 2).

### 3. Ce qu'on doit voir

Simulation (1 et 2) :

- « Séances placées : 12 — envoyées par la règle : 12, autres : 0 » ;
- « Identifiants résolus » : `room_id`, `staff_id`, `event_cat_id`, `dept_id` — **pas** de `module_id` ;
- `event_cat_id` = **465** (TD0). Un autre nombre est refusé par le garde-fou, avec un message ;
- la séance : « sans module (règle WR100BU), module aucun » ;
- la charge : `"modules": []`, `"notes": "WR100BU — WR100BU-S1-TD-1-but1-td-ab"`, une seule semaine (`weeks` avec un seul `Y`) ;
- « SIMULATION — rien n'a été écrit ».

Canari (3), bloc « Relu dans Celcat » :

| Ligne | Attendu |
|---|---|
| `categorie` | `TD0` (éventuellement suivi d'une pondération) |
| `ponderation` | 0 (portée par la catégorie) |
| `departement` | `T_MMI T29` |
| `remarque (notes)` | `WR100BU — WR100BU-S1-TD-1-but1-td-ab` |
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
- **Remarques et personnaliser** : `WR100BU — WR100BU-S1-TD-1-but1-td-ab` dans « Remarques ».

### 4. Points incertains à vérifier dans Celcat

1. **Le champ de la Remarque.** L'appli écrit dans `notes` (le seul champ texte de l'évènement prouvé en écriture, canari du 01/09/2026).
   À confirmer : c'est bien la zone « Remarques » de l'onglet « Remarques et personnaliser ».
   Si Kyllian attend `WR100BU` dans un champ « personnaliser » (`custom1`…), le dire : la relecture affiche `custom1` à `custom3`.
2. **La forme de la Remarque.** `WR100BU — <identifiant>` et non `WR100BU` seul : l'identifiant y relie l'évènement à l'appli.
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
enseignant 3696, catégorie TD0, salle et groupe de la séance, AUCUNE matière, remarque « WR100BU — <id> »,
département T_MMI T29.

À lire d'abord : docs/A-TESTER-SUR-CELCAT.md (section « Envoi sans module »), docs/CELCAT.md § 5,
data/config/celcat.yaml (section regles_envoi), src/cal_iut/celcat/essai_regle.py,
src/cal_iut/celcat/ecriture.py (resoudre_ids, charge_utile), src/cal_iut/celcat/categories.py
(verifier_charge_categorie, CATEGORIE_IDS_REGLES), tests/test_celcat_regles_envoi_2026_10_01.py.

RÈGLE ABSOLUE : ne jamais écrire dans URCA_2026. Lecture seule sur URCA_2026 (simulation, rôle
985_consultation). Toute écriture se fait dans URCA_FORMATION, via la commande d'essai, qui supprime
son évènement à la fin. Ne pas lancer le robot (celcat_nuit.py, celcat_immediat.py) ni --production.

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
- canari URCA_FORMATION : relu avec catégorie TD0, département T_MMI T29, remarque « WR100BU — <id> »
  visible dans l'onglet « Remarques et personnaliser », enseignant 3696, salle et groupe de la séance,
  aucune matière, une seule semaine ; puis « supprimé, absent à la relecture » ;
- aucune écriture dans URCA_2026 ; tests verts.
Commits en français, préfixe « add | ». Ne pas pousser sur main.
```

### Résultats

_À remplir après les essais : date, base, sortie de la commande, captures de l'inspecteur, décision de Kyllian sur la forme de la Remarque._

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
| Remarque | `PTUT — <identifiant de séance>` |
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
| `remarque (notes)` | `PTUT — WR101-S1-TD-1-but1-td-ab` |
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
toute séance de type PTUT part dans Celcat en catégorie « Projet » (pondération 0), remarque « PTUT — <id> »,
département T_MMI T29, enseignant/salle/groupe de la séance, et la matière DU COURS si son code est connu
(aucune sinon ; jamais une matière « PTUT »).

À lire : docs/A-TESTER-SUR-CELCAT.md (section « Séances PTUT »), docs/CELCAT.md § 5, data/config/celcat.yaml
(regles_envoi.types.PTUT), src/cal_iut/celcat/mapping.py (regle_pour, RegleEnvoi), src/cal_iut/celcat/ecriture.py
(_resoudre_ids_regle), src/cal_iut/celcat/essai_regle.py, tests/test_celcat_regles_envoi_2026_10_01.py.

RÈGLE ABSOLUE : ne jamais écrire dans URCA_2026 (lecture seule permise). Écritures d'essai uniquement dans
URCA_FORMATION, par la commande d'essai, qui supprime son évènement. Ne pas lancer le robot ni --production.

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
avec code et absent sinon ; aucune recherche de matière « PTUT » ; remarque « PTUT — <id> » visible dans l'onglet
« Remarques et personnaliser » ; évènement supprimé à la relecture ; aucune écriture dans URCA_2026 ; tests verts.
Commits en français, préfixe « add | ». Ne pas pousser sur main.
```

### Résultats (PTUT)

_À remplir après les essais._
