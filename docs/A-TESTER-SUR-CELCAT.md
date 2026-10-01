## Occupations hors MMI

Demande de Kyllian Bresson (01/10/2026) : lire Celcat pour savoir si une salle (surtout l'amphi H.018) ou un enseignant
est déjà pris **hors MMI** (autre département, administration, réunion), et en tenir compte au placement et à la génération.
Fonctionnement complet : [CELCAT.md § 5](CELCAT.md#5-occupations-hors-mmi).
Tout est en **lecture seule** (rôle `985_consultation`, `udlResources.load` et `udlTimetables.load` uniquement) :
ne jamais écrire dans `URCA_2026` pendant ces essais.
Salles surveillées en priorité : H.018 (« Amphi 3 MMI »), « Amphi 1 TC/GEA », « Amphi 2 GMP/GEII » ; puis toutes nos salles
qui ont un libellé Celcat ; enseignants : tous ceux qui ont un code Celcat.

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
7. Mets à jour docs/A-TESTER-SUR-CELCAT.md (ce qui est confirmé, ce qui reste) et docs/CELCAT.md § 5.

Critères de réussite : H.018, les deux amphis partagés et AFR trouvés ; leurs occupations hors MMI correspondent à Celcat (jour, heure
réelle, département) ; aucun de nos évènements dans la liste ; `cal-iut celcat occupations --ecrire-fichier`
produit un fichier que l'écran Celcat → Occupations hors MMI affiche ; tests verts ; aucun appel d'écriture.
Commits en français au style du dépôt (`add | …`, `fix | …`).
```
