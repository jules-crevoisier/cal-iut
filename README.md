# cal-iut — Générateur d'emplois du temps IUT MMI Troyes

Outil complet de génération, visualisation et ajustement d'emplois du temps pour le département MMI (BUT1–BUT3).

## Stack

| Couche | Techno |
|--------|--------|
| Ingestion | Python, exports JSON officiels MMI |
| Solveur | OR-Tools CP-SAT |
| API | FastAPI + SQLite |
| Frontend | React + TypeScript + FullCalendar |
| Export | CSV / JSON (hors Celcat) |

## Source de vérité des données

Les fichiers officiels vivent dans `contraintes_update/` (CSV Google Sheets,
`maquette.json`, `progression.json`, maquettes `.docx`). Ils sont convertis en
`contraintes/*.json` — la seule chose que lit l'algorithme — par un script
dédié :

```powershell
python scripts/build_contraintes.py
```

**Ne jamais éditer `contraintes/*.json` à la main** : le script les écrase.
Toute décision qui ne se déduit pas d'un fichier source (arbitrage,
désambiguïsation) est câblée dans le script sous forme de constante nommée et
documentée — cf. `_ARBITRAGES` en fin de fichier et `contraintes/00_INDEX.md`.

Périmètre 2026-2027 : **S1/S3/S5 uniquement**. Le fichier officiel
« DATES SAE 2026_2027 » ne date que les SAE de ces semestres ; demander
`--semestre-group even` déclenche un avertissement explicite et produirait des
emplois du temps sans aucune sanctuarisation SAE.

## Installation

```powershell
cd cal-iut
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cd frontend
npm install
npm run build
```

## Démarrage rapide

```powershell
# Terminal 1 — API + UI React intégrée
cal-iut serve
# → API + UI : http://127.0.0.1:8000/
# → page HTML/JS historique (édition, même moteur, autre présentation) : http://127.0.0.1:8000/legacy

# Terminal 2 — dev frontend (hot reload)
cd frontend
npm run dev
# → http://localhost:5173
```

**L'interface par défaut est le frontend React**, servi à la racine
(`http://127.0.0.1:8000/`) — décision du 11/08/2026, qui inverse un choix
antérieur (servir la page HTML/JS à la racine). Cette dernière reste
disponible sur `/legacy` : même moteur de résolution, même données
(`GET /app-state`), juste une présentation différente. `cal-iut export
--format html` continue de produire un fichier autonome distribuable par
mail, indépendant des deux.

## Reprise du projet par quelqu'un d'autre

`GUIDE.md` s'adresse à la personne qui reprend l'outil sans l'avoir écrit :
installation, fichiers à fournir, production d'un emploi du temps, diagnostic.
Trois commandes suffisent à s'en sortir sans lire le code :

```powershell
cal-iut doctor     # est-ce que tout est en place ? que faire ensuite ?
cal-iut refresh    # récupérer maquette + progression officielles, voir ce qui change
cal-iut annee      # tout dérouler : contraintes -> séances -> audit -> emploi du temps
cal-iut regles     # lister en français toutes les règles actives, avec leur raison
```

`refresh` télécharge les deux exports depuis le serveur MMI, **montre ce qui
change** (modules ajoutés, volumes ou enseignants modifiés) et n'écrit qu'avec
`--ecrire`, en sauvegardant l'ancienne version dans `data/sauvegardes/`. En cas
de serveur injoignable, `--depuis <dossier>` lit deux fichiers reçus par mail.

## Audit

```powershell
cal-iut audit                                          # données, config, capacité
cal-iut audit --timetable data/generated/timetable.json  # + vérification du résultat
cal-iut audit --json                                   # sortie machine (code retour 1 si erreur)
```

L'audit ne résout rien : il cherche les quatre familles de défauts qui ont
réellement coûté du temps sur ce projet (cf. docs/DATA.md §63).

| Famille | Exemple trouvé | Contrôle |
|---|---|---|
| Une règle déclarée qui ne s'applique pas | fenêtres de dates absentes du mode `--decomposed` | `couverture.*` |
| Une règle qui pointe dans le vide | code de cours mal orthographié, ignoré en silence | `config.*` |
| Une donnée source mal comprise | « mercredi 23/09/26 » lu comme « tous les mercredis » | `donnees.*` |
| Une impossibilité arithmétique | 22 créneaux FI pour 21 disponibles hors jeudi PAC | `capacite.*` |

Chaque constat dit **où** et **quoi faire**. L'audit liste aussi les règles
qu'il ne sait PAS vérifier : une règle sans vérification est un bug en attente.

## CLI

```powershell
python scripts/build_contraintes.py                    # régénère contraintes/*.json depuis les sources
cal-iut ingest --semestre-group odd                    # normalise les séances (S1+S3+S5)
python scripts/solve_until_ok.py --max-runs 20         # relance jusqu'au meilleur résultat
cal-iut solve --decomposed --semestre-group odd --weeks 24 --fi-max-week 18
cal-iut solve --course WR108 --no-gaps                 # une matière, rapide
cal-iut solve --warm-start data/generated/timetable.json  # relance à partir d'un run précédent (rapide)
cal-iut export --format csv --output export.csv        # export hors Celcat
cal-iut export --format html --output planning.html    # webapp interactive auto-contenue
cal-iut serve                                          # API + frontend
```

`--weeks` n'est pas plafonné : la fin de semestre n'est pas une contrainte dure
(front-loading uniquement), on peut monter au-delà si besoin.

### Pourquoi `--weeks 24 --fi-max-week 18` et pas les valeurs par défaut

Avec le calendrier 2026-2027, **BUT3-CREACOM-FC ne tient pas dans l'horizon
par défaut (19 semaines)** : ce parcours a besoin de 173 créneaux, mais ses
40 jours de présence à l'IUT sur la période, moins les 12 jours sanctuarisés
par les SAE WSA501C et WSA502C, ne laissent que 28 jours × 6 = 168 créneaux.
L'étage 2 du solveur le détecte et retourne `WEEK_ASSIGNMENT_INFEASIBLE` — ce
n'est pas un bug mais une vraie impossibilité arithmétique.

`--fi-max-week 18` étend l'horizon aux seuls parcours en alternance (jusqu'à
la semaine-index 23) en gardant la formation initiale bornée à la semaine 18,
ce qui ramène BUT3-CREACOM-FC à 38 jours libres (228 créneaux). Les parcours FI
ne glissent jamais dans cette marge.

### Vitesse : parallélisme adapté à la machine

Le solveur détecte le nombre de processeurs logiques (`--num-workers` non
fourni) au lieu du `8` codé en dur historiquement, qui n'exploitait que la
moitié d'un CPU 16 threads.

En mode `--decomposed`, ce budget est réparti sur **deux** niveaux de
parallélisme plutôt qu'un seul :

| Niveau | Ce qui tourne en parallèle |
|--------|---------------------------|
| Étage 3 — semaines | 4 semaines résolues simultanément (une par thread CP-SAT distinct) |
| Dans chaque semaine | 4 workers CP-SAT (portefeuille de stratégies de recherche) |

Les semaines de l'étage 3 sont indépendantes par construction une fois
l'affectation semaine (étage 2) figée : chaque modèle hebdomadaire ne lit que
ses propres séances. Les solutions sont collectées puis appliquées dans l'ordre
croissant des semaines, jamais dans l'ordre d'arrivée du pool : le
parallélisme n'introduit donc aucune dépendance à l'ordonnancement des threads.

**En revanche, le RÉSULTAT n'est pas reproductible d'un run à l'autre**, et ce
n'est pas dû au parallélisme des semaines : `max_time_in_seconds` combiné à
plusieurs `num_search_workers` rend CP-SAT lui-même non déterministe (le
résultat dépend de quel worker a fini quoi à l'échéance), malgré
`random_seed=2027`. Deux exécutions identiques peuvent donc donner des
affectations de semaine différentes — et une semaine en échec dans l'une et pas
dans l'autre. Rendre le run reproductible demanderait de passer à
`max_deterministic_time` et de recalibrer tous les budgets ; cf. docs/DATA.md
§63.9ter.

Répartition privilégiant la largeur (4 workers/semaine) parce que le rendement
de `num_search_workers` sature vite sur un modèle d'une seule semaine, alors
que les semaines, elles, sont parfaitement parallèles. Sur 16 threads :
4 × 4 au lieu de 1 × 8.

### Vitesse : `--warm-start`

Un run complet à froid (ex. BUT1-S1, 1437 séances, toutes les règles dures
actives dont la sanctuarisation SAE) peut prendre jusqu'à ~15 min pour trouver
une première solution faisable — c'est un problème de scheduling universitaire
réaliste, pas un bug. `--warm-start <timetable.json>` réinjecte un run
précédent comme point de départ (`CpModel.add_hint`, sans toucher au modèle ni
aux contraintes) : le solveur n'a plus à chercher un premier point faisable
depuis zéro. Mesuré sur BUT1-S1 : ~15 min à froid → **~1 min** en warm-start
pour une qualité équivalente (objectif 179 890 vs 177 924 à froid, 385 vs 380
trous). Recommandé pour toute régénération après un ajustement mineur
(verrouillage de quelques séances, changement d'un enseignant, etc.).

## Workflow UI

1. **Charger données** — ingestion depuis les exports MMI
2. **Générer** — solveur CP-SAT (contraintes dures + objectif trous)
3. **Ajuster** — drag & drop sur le calendrier, validation conflits en temps réel
4. **Verrouiller** — clic séance → « Verrouiller » (conservé à la régénération)
5. **Régénérer** — relance le solveur sur les séances non verrouillées
6. **Diff** — panneau latéral : écarts solveur vs manuel
7. **Appliquer feedback** — ajuste les poids objectif depuis les corrections
8. **Export CSV/JSON/HTML** — fichier exploitable hors Celcat, ou webapp interactive autonome

### Onglets de l'app React (`http://127.0.0.1:8000/`)

- **Vue Semaine** — édition manuelle (glisser-déposer, exceptions, régénération ciblée),
  FullCalendar + verrouillage, panneaux Qualité/Diff/Feedback.
- **Vue Groupe** — calendrier lecture seule par groupe (TD 2 colonnes TP quand les
  sous-groupes divergent) + agenda chronologique du semestre + `.ics`.
- **Vue Enseignant** — calendrier + contrainte déclarée + violations recalculées +
  agenda chronologique + `.ics` + bouton mailto.
- **Vue Promo** — toutes les promotions sur une seule grille (un jour à la fois).
- **Référence** — salles, cours, calendrier institutionnel, **Liens & partage**.
- **Contraintes** — chaque règle (enseignant ou solveur) avec son verdict recalculé
  depuis la sortie brute du solveur (jamais une affirmation pré-écrite).
- **À traiter** — séances non placées, violations, journées trouées : liste de
  travail cliquable.
- **À placer** — les séances que le solveur n'a pas su placer. Un bouton les pose
  toutes d'un coup quand un créneau valable existe (l'essentiel du reliquat) ;
  le reste se place à la main sur des créneaux déjà vérifiés. Sans cet onglet
  elles disparaissaient sans bruit : le planning avait l'air complet alors qu'il
  manquait des heures (cf. docs/DATA.md §66).
- **Recherche globale** (`Ctrl+K`) — enseignant, cours, salle ou groupe, ouvre directement la bonne vue.

Les données des vues en lecture seule viennent d'un unique endpoint,
`GET /app-state` (même fonction Python — `build_payload` — que celle qui
alimente `/legacy`) : le frontend n'invente aucun verdict, il affiche ce que
le serveur a déjà validé.

#### Liens par enseignant / par groupe

Chaque enseignant et chaque groupe étudiant a un **lien personnel** en lecture
seule (onglet Référence > Liens & partage — annuaire complet, .csv exportable,
bouton mailto préparé). Le lien vit dans le fragment d'URL
(`#vue=prof&prof=KBR&mode=prof`), jamais envoyé au serveur : il fonctionne
identiquement que la page soit ouverte via `cal-iut serve` sur le réseau local
ou (pour la variante `--format html`) reçue par mail. Il ouvre directement le
planning de l'intéressé, sans les onglets d'édition ni les autres promotions.

Chaque vue individuelle propose aussi l'export **.ics** (import dans l'agenda
personnel) et l'impression (feuille de style dédiée, sans les contrôles
d'édition). Sur écran étroit (téléphone), la grille bascule automatiquement en
lecture jour par jour.

Adresses mail (pour le bouton « Écrire ») : à saisir dans
`data/config/teacher_contacts.yaml`, absentes de tout fichier source officiel.

### Export HTML autonome (`cal-iut export --format html`)

Fichier auto-contenu (aucune dépendance externe), même moteur et mêmes
fonctions que l'app React (liens, recherche, agenda, `.ics`, mobile) mais dans
une page unique — pour distribuer un planning par mail sans dépendre d'un
serveur en marche :

```powershell
cal-iut export --format html --output planning.html
# alternative plus étanche : un fichier par enseignant, ne contenant que ses séances
cal-iut export --format html --per-teacher data/generated/par-enseignant
```

## API

| Endpoint | Description |
|----------|-------------|
| `POST /ingest` | Charge maquette + progression |
| `POST /solve` | Génère planning + salles + persiste SQLite |
| `GET /timetable` | Planning courant (filtres groupe/prof/salle/semaine) |
| `GET /app-state` | État complet pour le frontend React (Groupe/Enseignant/Promo/Référence/Contraintes/À traiter) |
| `GET /placements/manquantes` | Séances absentes du planning, calculées par différence |
| `GET /placements/{id}/creneaux-libres` | Créneaux où cette séance peut réellement aller |
| `POST /placements/{id}/placer` | Pose une séance non placée — mêmes contrôles que le glisser-déposer |
| `POST /placements/completer` | Pose d'un coup tout le reliquat pour lequel un créneau valable existe |
| `GET /diff` | Diff solveur vs manuel |
| `PATCH /placements/{id}` | Déplacement + verrouillage |
| `POST /feedback/apply` | Réinjection poids objectif |
| `GET /export/csv` | Export CSV |
| `GET /export/json` | Export JSON |
| `GET /legacy` | Page HTML/JS historique (même données, autre présentation) |

## Architecture

```
Exports JSON → ingestion → SessionToPlace
                              ↓
                    Solveur CP-SAT (16 sem.)
                              ↓
                    Affectation salles (YAML rules)
                              ↓
              SQLite (snapshots + corrections + poids)
                              ↓
                    API FastAPI ↔ Frontend React (build_payload → /app-state)
```

`app.mount("/", StaticFiles(frontend/dist))` est déclaré en TOUT DERNIER dans
`api/main.py` — Starlette essaie les routes dans l'ordre du fichier, et ce
mount matche n'importe quel chemin ; placé plus tôt, il intercepterait
`/meta`, `/solve`, `/app-state`, etc. avant qu'elles n'atteignent leur handler
Python.

## Grille horaire

6 créneaux/jour × 5 jours × 19 semaines (défaut) = 570 positions/groupe/semestre.
`--weeks` n'est pas une limite dure : la fin de semestre n'est pas bloquée,
seul le front-loading (§5) pousse à compacter tôt.

| Slot | Horaire |
|------|---------|
| 0 | 8h00–9h30 |
| 1 | 9h30–11h00 |
| 2 | 11h00–12h30 |
| — | *pause 12h30–14h* |
| 3 | 14h00–15h30 |
| 4 | 15h30–17h00 |
| 5 | 17h00–18h30 |

Règles dures/molles issues du cahier des charges (`SolverConfig`, `solver/cpsat.py`) :

| Règle | Type | Config |
|-------|------|--------|
| Plafond 33h/sem FI (22 créneaux) / ~35h/sem FC (23 créneaux) | Dure | `enforce_weekly_hour_cap`, `fi_weekly_cap_slots`, `fc_weekly_cap_slots` |
| Jeudi après-midi verrouillé (PAC) pour la FI | Dure | `enforce_thursday_pac_lock` |
| Pas de cours S1 avant le lundi 7 septembre 2026 (semaine 3) | Dure | `enforce_s1_integration_week_lock` |
| Sanctuarisation SAE (jour SAE ⇒ pas de ressource classique ce jour), par parcours **ou par groupe TD** | Dure | `enforce_sae_sanctuarization` |
| Événement fixe horodaté (rentrée, intervention) — **au parcours près** | Dure | `enforce_planning_events` |
| Indisponibilités enseignant (créneaux récurrents + dates) | Dure | `contraintes/05_enseignants_contraintes.json` |
| **Disponibilités enseignant en liste blanche** (jours non listés interdits) | Dure | `allowed_slots` / `allowed_dates` |
| **Indisponibilité à parité de semaine** (TCA : mercredi les semaines paires…) | Dure | `week_parity_rules`, `parity_reference` |
| **Fenêtre de dates civiles par séance** (WR100BU : visite BU avant le 15 sept.) | Dure | `enforce_session_date_windows` |
| Toute séance `is_eval` affectée en salle A.018 | Dure | `data/config/rooms.yaml` (règle `is_eval: true`) |
| **Ordre pédagogique vu par l'étudiant** (CM promo ↔ TD/TP de sous-groupe) | Dure à l'étage 3, molle graduée à l'étage 2 | `cohort_order_weight`, `cohort_sequence_pairs` |
| **Borne de FIN par cours** (ex. WRA507D doit finir en janvier) | Dure | `max_week_rules` (`course_scheduling_rules.yaml`) |
| **SAE planifiée par le solveur** (ex. WSA501D, sans dates officielles) | — | `solver_scheduled_sae` (`course_scheduling_rules.yaml`) |
| **Répartition des jours d'une SAE entre ses enseignants** (WS501D) | Dure (restreint l'indispo « référent SAE ») | `data/config/sae_teacher_phases.yaml` |
| **Liste explicite de dates pour une séance** (WRA505C conjointe) | Dure | `dates:` dans `session_date_windows` |
| **Répartition alternée des enseignants d'un module** (WRA507D : BTO/JSA une séance sur deux) | — (ingestion) | `teacher_distribution` (`course_scheduling_rules.yaml`) |
| Ordonnancement `before`/`after` par groupe étudiant (position moyenne) | Molle | `enforce_ordonnancement` |
| **Ordonnancement strict « A fini avant que B commence », par cohorte** | Molle graduée (poids × semaines de chevauchement) | `strict_ordonnancement_weight` |
| **Regroupement mensuel des interventions** (ARA, JHU : 1-2 semaines/mois) | Molle | `optimize_teacher_clustering`, `teacher_clustering_weight` |
| **Ordre entre enseignants d'un module** (WRA505C : ALO puis AFR) | Molle | `optimize_teacher_order` |
| Regroupement des évaluations sur une même semaine | Molle | `optimize_eval_clustering`, `eval_clustering_weight` |
| Remplissage centré sur la pause méridienne (11h/14h avant 8h/17h) | Molle | `optimize_midday_fill`, `midday_fill_weight` |
| Lundi 8h / vendredi 17h = zones à éviter (dernier recours) | Molle | `optimize_avoid_zones`, `avoid_zone_weight` |

Numéro de semaine "département" corrélé au calendrier réel (semaine 1 =
ISO-week 35 2026) via `AcademicCalendar.department_week_label` — utilisé dans
l'export HTML pour afficher "Semaine 3 (7–11 sept. 2026)" plutôt qu'un index nu.

## Configuration & contraintes métier

- `data/config/groups.yaml` — groupes TD/TP + effectifs (BUT1 : 4 TD × 8 TP ; BUT2-DEV-FI : 2 TD × 4 TP ; BUT3-DEV-FI : 1 TD × 2 TP ; FC : 1 TD × 1 TP, nommés TD EF/TP E et TD GH/TP G)
- `data/config/rooms.yaml` — inventaire réel bâtiment H (H.005–H.205, A.018) + règles d'affectation par module
- `data/config/course_scheduling_rules.yaml` — démarrage minimum, **borne de fin par cours**, **fenêtres de dates par séance** (plage continue ou liste explicite), **ordre entre enseignants d'un module**, **SAE planifiées par le solveur**
- `data/config/sae_teacher_phases.yaml` — qui encadre une SAE et quand (WS501D) : restreint l'indisponibilité « référent SAE » aux seuls jours réellement concernés
- `data/config/double_sessions.yaml` — blocs de N créneaux collés (`max_blocks` pour n'en former qu'un seul, ex. WRA308M)
- `data/config/teacher_availability.yaml` — dispos profs + poids initiaux
- `contraintes/00_INDEX.md` — provenance de chaque fichier et **liste des arbitrages humains**
- `docs/DATA.md` — analyse détaillée des règles extraites
- `data/state/cal-iut.db` — persistance (runs, diff, corrections, poids appris)

BUT2-DEV-FC (S3/S4) est **gelé** pour 2026-2027 (effectif d'alternants
insuffisant) : aucun module dans la maquette, le solveur l'ignore de lui-même.

## Fonctionnalités livrées

- [x] Ingestion maquette + progression
- [x] Solveur OR-Tools (NoOverlap, ordonnancement, dispos, objectif trous)
- [x] Affectation salles paramétrable
- [x] API REST complète
- [x] Frontend calendrier + drag & drop
- [x] Validation conflits temps réel
- [x] Persistance SQLite
- [x] Vue diff solveur/manuel
- [x] Boucle feedback (poids + préférences apprises)
- [x] Export CSV/JSON

## Sources

- https://mmi23x02.mmi-troyes.fr/export/maquette
- https://mmi23x02.mmi-troyes.fr/export/progression
