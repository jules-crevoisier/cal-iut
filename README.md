# cal-iut — emplois du temps du département MMI (IUT de Troyes)

Ce document présente l'application et dit quel document lire.
Il est pour tout le monde : utilisateurs, administrateurs et développeurs.

cal-iut fabrique, affiche et corrige les emplois du temps de BUT1, BUT2 et BUT3.
Un calcul automatique place les séances en respectant les règles.
L'équipe corrige ensuite à la main, dans l'application web.
L'application recopie les changements dans Celcat.

**Sommaire**

- [Qui lit quoi ?](#qui-lit-quoi-)
- [Démarrer en local](#démarrer-en-local)
- [Où est quoi dans le dépôt ?](#où-est-quoi-dans-le-dépôt-)
- [Commandes principales](#commandes-principales)
- [Règles de placement](#règles-de-placement)

## Qui lit quoi ?

| Vous êtes… | Lisez |
|---|---|
| Utilisateur de l'appli (secrétariat, responsable, enseignant) | [GUIDE.md](GUIDE.md) : mode d'emploi, écran par écran |
| Enseignant ou étudiant qui veut son agenda sur téléphone | [docs/ICS.md](docs/ICS.md) : s'abonner à son agenda |
| Administrateur de l'appli | [docs/ADMIN.md](docs/ADMIN.md) : comptes, codes Celcat, sauvegardes, déploiement |
| Administrateur, pour Celcat | [docs/CELCAT.md](docs/CELCAT.md) : comment l'appli recopie dans Celcat |
| Administrateur, contre les robots | [docs/ANTI-ASPIRATION.md](docs/ANTI-ASPIRATION.md) : bloquer un aspirateur |
| Développeur d'une application tierce | [docs/API.md](docs/API.md) : lire l'emploi du temps avec une clé |
| Technicien qui pilote le planning avec Claude | [docs/MCP.md](docs/MCP.md) : connecteur MCP |
| Technicien (fichiers de données, calcul, règles) | [docs/DATA.md](docs/DATA.md) : référence des données et de la configuration |
| Développeur de l'interface | [docs/DESIGN.md](docs/DESIGN.md) : charte visuelle |

[docs/AUDIT-2026-09.md](docs/AUDIT-2026-09.md) est un rapport daté, gardé en archive.

## Démarrer en local

Il faut Python 3.13 (3.11 au minimum) et Node.js.
Ouvrir un terminal dans le dossier du projet, puis :

1. Créer l'environnement Python :
   `python -m venv .venv` puis l'activer
   (`.\.venv\Scripts\Activate.ps1` sous Windows, `source .venv/bin/activate` ailleurs).
2. Installer l'outil : `pip install -e ".[dev]"`.
3. Construire l'interface : `cd frontend`, `npm install`, `npm run build`, puis `cd ..`.
4. Créer un compte local : `python scripts/creer_admin_local.py moi@exemple.fr monmotdepasse`.
5. Lancer le serveur : `cal-iut serve`, puis ouvrir <http://localhost:8000/>.

L'appli s'ouvre avec le planning de la base fournie (`data/state/cal-iut.db`).
`cal-iut doctor` dit ce qui manque et quelle commande taper ensuite.

> **À savoir :** pour modifier l'interface avec rechargement automatique,
> lancer aussi `npm run dev` dans `frontend/` et ouvrir <http://localhost:5173>.
> Le serveur `cal-iut serve` doit rester lancé à côté.

La mise en production (Dokploy, variables d'environnement) est dans [docs/ADMIN.md](docs/ADMIN.md).

## Où est quoi dans le dépôt ?

| Dossier | Contenu |
|---|---|
| `contraintes_update/` | Fichiers officiels reçus (maquette, progression, CSV des contraintes) |
| `contraintes/` | Leur traduction, régénérée par script : ne jamais la modifier à la main |
| `data/config/` | Règles et réglages (salles, groupes, Celcat…) en YAML |
| `data/state/` | Base de l'appli et saisies faites en ligne |
| `src/cal_iut/` | Serveur Python : calcul, API, Celcat, ligne de commande |
| `frontend/` | Interface web (React) |
| `scripts/`, `tests/` | Scripts d'entretien, tests automatiques |
| `deploy/`, `Dockerfile`, `docker-compose.yml` | Déploiement (voir [docs/ADMIN.md](docs/ADMIN.md)) |

Le détail de chaque fichier de données est dans [docs/DATA.md](docs/DATA.md).

## Commandes principales

| Commande | À quoi elle sert |
|---|---|
| `cal-iut doctor` | Vérifier que tout est en place et dire quoi faire ensuite |
| `cal-iut refresh` | Récupérer maquette et progression officielles, montrer ce qui change (`--ecrire` pour appliquer) |
| `cal-iut regles` | Lister en français les règles actives, avec leur raison |
| `cal-iut audit` | Vérifier données, réglages et résultat, sans rien calculer |
| `cal-iut annee` | Tout enchaîner : contraintes, séances, audit, calcul de l'emploi du temps |
| `cal-iut completer` | Placer les séances qu'un calcul a laissées de côté |
| `cal-iut serve` | Lancer l'appli web et l'API |
| `cal-iut export` | Exporter le planning en CSV, JSON ou page HTML autonome |
| `cal-iut prod diff` / `push` / `pull` | Comparer ou synchroniser la base locale et la production |
| `cal-iut sauvegarder-base` | Sauvegarder la base tout de suite |

Commandes plus techniques (`ingest`, `solve`, `load-run`, `fetch`) : voir [docs/DATA.md](docs/DATA.md).
Commandes d'administration (`lisser`, `trafic`, `bloquer`, `debloquer`, `celcat-reseau`) :
voir [docs/ADMIN.md](docs/ADMIN.md) et [docs/ANTI-ASPIRATION.md](docs/ANTI-ASPIRATION.md).
Chaque commande accepte `--help`.

## Règles de placement

Une journée compte 6 créneaux de 1h30 : 8h00, 9h30, 11h00, puis 14h00, 15h30, 17h00.
Une règle **dure** n'est jamais enfreinte par le calcul.
Une règle **souple** est respectée autant que possible.

| Règle | Type |
|---|---|
| 33 h par semaine au plus en formation initiale (FI), environ 35 h en alternance (FC) | Dure |
| Jeudi après-midi réservé aux PAC pour la FI | Dure |
| Jour de SAE : pas de cours classique ce jour-là (par parcours ou par groupe TD) | Dure |
| Pas de cours de S1 avant le lundi 7 septembre 2026 (semaine 3) | Dure |
| Indisponibilités déclarées par les enseignants | Dure |
| Évènements à heure fixe du planning officiel (rentrée, intervention) | Dure |
| Dates imposées à une séance (ex. visite de la BU WR100BU avant le 15 septembre) | Dure |
| Évaluations en salle A.018 ; une salle n'accueille qu'un cours à la fois | Dure |
| Ordre vu par l'étudiant : le CM avant les TD et TP qui le suivent | Dure dans la semaine, souple entre semaines |
| Ordonnancement entre matières (une matière avant une autre) | Souple |
| Regrouper les évaluations et les venues des intervenants extérieurs | Souple |
| Remplir d'abord autour de midi ; éviter lundi 8h et vendredi 17h | Souple |
| Limiter les trous dans les journées | Souple |

`cal-iut regles` donne la liste complète et à jour.
Les réglages exacts (fichiers, paramètres) sont dans [docs/DATA.md](docs/DATA.md).
