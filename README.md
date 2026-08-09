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
# Terminal 1 — API + UI intégrée
cal-iut serve
# → API : http://127.0.0.1:8000
# → UI  : http://127.0.0.1:8000/app/

# Terminal 2 — dev frontend (hot reload)
cd frontend
npm run dev
# → http://localhost:5173
```

## CLI

```powershell
cal-iut fetch                                          # télécharge maquette + progression
cal-iut ingest --parcours BUT1 --semestre S1           # normalise les séances
cal-iut solve --weeks 16                               # génère le planning
cal-iut solve --course WR108 --no-gaps                 # une matière, rapide
cal-iut solve --warm-start data/generated/timetable.json  # relance à partir d'un run précédent (rapide)
cal-iut export --format csv --output export.csv        # export hors Celcat
cal-iut export --format html --output planning.html    # webapp interactive auto-contenue
cal-iut serve                                          # API + frontend
```

`--weeks` n'est pas plafonné à 16 : la fin de semestre n'est pas une contrainte
dure (front-loading uniquement), on peut monter au-delà si besoin.

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

### Export HTML (`cal-iut export --format html`)

Webapp à 3 onglets, auto-contenue (aucune dépendance externe) :
- **Vue Groupe** — calendrier par groupe (TD 2 colonnes TP quand les sous-groupes divergent).
- **Vue Enseignant** — calendrier par enseignant + rappel de sa contrainte déclarée.
- **Contraintes** — tableau de bord : chaque règle (enseignant ou solveur) avec son verdict
  recalculé depuis la sortie brute du solveur (jamais une affirmation pré-écrite), plus un
  bandeau calendrier institutionnel (vacances, jours fériés, rentrées, dates fixes).

## API

| Endpoint | Description |
|----------|-------------|
| `POST /ingest` | Charge maquette + progression |
| `POST /solve` | Génère planning + salles + persiste SQLite |
| `GET /timetable` | Planning courant (filtres groupe/prof/salle/semaine) |
| `GET /diff` | Diff solveur vs manuel |
| `PATCH /placements/{id}` | Déplacement + verrouillage |
| `POST /feedback/apply` | Réinjection poids objectif |
| `GET /export/csv` | Export CSV |
| `GET /export/json` | Export JSON |

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
                    API FastAPI ↔ Frontend FullCalendar
```

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
| Semaine d'intégration BUT1 (semaine-index 0, S1) sans cours classique | Dure | `enforce_s1_integration_week_lock` |
| Sanctuarisation SAE (jour SAE ⇒ pas de ressource classique ce jour, ce parcours) | Dure | `enforce_sae_sanctuarization` |
| Toute séance `is_eval` affectée en salle A.018 | Dure | `data/config/rooms.yaml` (règle `is_eval: true`) |
| Ordonnancement `before`/`after` par groupe étudiant (position moyenne) | Molle | `enforce_ordonnancement` |
| Regroupement des évaluations sur une même semaine | Molle | `optimize_eval_clustering`, `eval_clustering_weight` |
| Remplissage centré sur la pause méridienne (11h/14h avant 8h/17h) | Molle | `optimize_midday_fill`, `midday_fill_weight` |
| Lundi 8h / vendredi 17h = zones à éviter (dernier recours) | Molle | `optimize_avoid_zones`, `avoid_zone_weight` |

Numéro de semaine "département" corrélé au calendrier réel (semaine 1 =
ISO-week 35 2026) via `AcademicCalendar.department_week_label` — utilisé dans
l'export HTML pour afficher "Semaine 3 (7–11 sept. 2026)" plutôt qu'un index nu.

## Configuration & contraintes métier

- `data/config/groups.yaml` — groupes TD/TP + effectifs (BUT1 : 4 TD × 8 TP ; BUT2/3-DEV-FI : 2 TD × 4 TP ; FC : 1 TD × 1 TP)
- `data/config/rooms.yaml` — inventaire réel bâtiment H (H.005–H.205, A.018) + règles d'affectation par module
- `data/config/teacher_availability.yaml` — dispos profs + poids initiaux
- `CONTRAINTES ENSEIGNANTS MMI … .csv` — indispos / préférences enseignants
- `INDISPONIBILITÉS IUT TROYES … .csv` — vacances & jours fériés
- `DISPONIBILITÉS ÉTUDIANTS S3-FC…` / `S5-FC…` — calendrier alternance FC
- `docs/DATA.md` — analyse détaillée des règles extraites
- `data/cal-iut.db` — persistance (runs, diff, corrections, poids appris)

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
