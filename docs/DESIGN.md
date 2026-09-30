# Charte visuelle de l'interface

Ce document fixe les règles visuelles communes à tous les écrans.
Il est pour les développeurs de l'interface (`frontend/`).
Une décision prise avec les utilisateurs et notée dans le code l'emporte sur cette charte.

**Sommaire**

- [Principes](#principes)
- [Direction « Lumière / Nuit »](#direction--lumière--nuit-)
- [Jetons](#jetons)
- [Typographie](#typographie)
- [Coque de l'application](#coque-de-lapplication)
- [Gabarit de page](#gabarit-de-page)
- [Composants](#composants)
- [Ranger le CSS](#ranger-le-css)

## Principes

Les utilisateurs : l'équipe du planning (sur ordinateur, des heures par semaine),
enseignants et étudiants (lien personnel, souvent sur téléphone), collègues en lecture seule.
Ils connaissent l'outil : ne pas déplacer les fonctions, ne pas renommer les écrans, ne pas changer les raccourcis.

1. **Un outil, pas une vitrine.** Pas de dégradé, d'ombre sur les panneaux (bordure 1 px),
   d'effet verre, d'emoji, d'icône décorative, de titre « héro », de carte arrondie à 16 px.
2. **Une action principale par écran** (`.btn--primary`), le reste en `.btn` ou `.btn--ghost`.
   Action destructrice : `.btn--danger`, jamais par défaut, toujours confirmée avec ce qui sera touché.
3. **La couleur porte du sens.** `--accent` : sélection, action principale, focus.
   `--good`, `--warn`, `--bad` : états. `--type-*` ou couleur de matière : données.
   Un état a toujours aussi un mot ou un symbole.
4. **Le texte dit la chose.** Français courant, pas de jargon interne (« job », « payload », « slot »).
   Boutons à l'infinitif (« Placer »). Dates lisibles (« lun. 12 oct. »).
5. **Rien ne disparaît en silence.** Chaque action a un retour visible.
   Pendant un chargement, l'ancien contenu reste lisible. Une erreur dit quoi faire.
6. **Clavier et accessibilité.** Focus visible (`--focus`), `aria-live` sur les retours,
   cibles de 32 px (44 px au doigt), contrastes AA. Échap ferme une modale, Entrée valide.

## Direction « Lumière / Nuit »

Clair « Lumière », sombre « Nuit » ; par défaut, le réglage du poste.

- Presque monochrome : fonds blancs (noir profond en sombre), bordures très légères.
  La couleur est réservée aux séances et aux états.
- Aucune ombre sur les cartes. `--shadow-pop` seulement pour ce qui flotte (modale, menu, bulle).
- Bouton principal noir en clair, blanc en sombre ; boutons secondaires blancs bordés.
- Contrôles segmentés : piste `--surface-3`, élément actif blanc à anneau fin.
  Filtres en pastilles arrondies (999 px), pastille active noire.
- **Carte de séance** : aplat pastel du type (`--td-bg`, `--td-bd`, `--td-fg`), rayon 8, pas de barre latérale.
  Ligne 1 : code (Geist Mono 600) et type. Ligne 2 : matière. Ligne 3 : salle · enseignant abrégé.
- **Chiffre clé** : 28 px, graisse 600, tuile blanche bordée ; la couleur d'état sur la valeur seulement.

## Jetons

Dans `frontend/src/styles/app.css`. **Aucune couleur en dur dans un composant.**

| Jeton | Usage |
|---|---|
| `--bg`, `--surface`, `--surface-2`, `--surface-3` | Fond de page, panneaux, zones secondaires, survol |
| `--ink`, `--ink-soft`, `--ink-faint` | Texte principal, secondaire, tertiaire |
| `--border`, `--border-strong` | Séparateurs, contours de champs et boutons |
| `--accent`, `--accent-hover`, `--accent-soft` | Action principale, sélection |
| `--good`, `--warn`, `--bad` (+ `-soft`, `-text`) | États |
| `--type-cm`, `--type-td`, `--type-tp`, `--type-eval` | Marque du type (point, légende) |
| `--cm-*`, `--td-*`, `--tp-*`, `--ev-*` (`-bg`, `-fg`, `-bd`) | Cartes de séance |
| `--pri-bg`, `--pri-fg` ; `--rail-*` | Bouton principal ; navigation latérale |
| `--radius-sm` 6 px, `--radius` 8 px, `--radius-lg` 12 px | Contrôles, cartes de séance, cartes de contenu |
| `--control-h` 32 px | Hauteur des champs et boutons |
| `--shadow-pop` | Ce qui flotte, rien d'autre |
| `--scrim-apercu`, `--on-scrim` | Aperçu d'image : seul fond sombre dans les deux thèmes |

Chaque jeton est défini trois fois : `:root` (clair),
`@media (prefers-color-scheme: dark)` sous `:root:not([data-theme="light"])` (sombre du poste),
et `:root[data-theme="dark"]` (sombre choisi).
Le choix Système / Clair / Sombre est dans le menu du compte (`utils/theme.ts`, clé `cal-iut:theme`).

## Typographie

- **Geist Sans** pour le texte, **Geist Mono** (`--mono`) pour les codes et raccourcis,
  embarquées via `@fontsource`.
- Corps 14 px, interlignage 1,45, chiffres tabulaires.
- Titres en graisse 600, 1,2 rem au plus dans une vue ; le `h1` est dans la barre du haut.
- Pas de capitales forcées, sauf les libellés de groupe de la navigation.

## Coque de l'application

- **Navigation** (`components/SideNav.tsx`) : rail clair, actif blanc à anneau, icônes Lucide et libellés,
  repliable en icônes seules (mémorisé). Recherche en tête, compte en pied.
- **Barre du haut** (`components/TopBar.tsx`) : nom de la vue et une ligne,
  **semaine partagée** (flèches, liste des semaines, « Aujourd'hui »), actions de la page.
- Une vue ne dessine **jamais** son titre ni sa navigation de semaine.
  Elle lit `useSemaineGlobale()` (index d'affichage dans `weekRows`)
  et pose ses boutons avec `ActionsDePage`.
  Sous la barre, `WeekStepper` s'efface (sauf `toujours`, pour une modale à semaine propre)
  et `NavSemaine` ne garde que l'histogramme. Les liens publics gardent leur navigation.
- **Accueil** (`views/AccueilView.tsx`) : indicateurs cliquables, charge par promo
  (carte de chaleur d'une teinte), séances par semaine, priorités, tâches, raccourcis.

## Gabarit de page

Chaque vue est une colonne `.view`, dans cet ordre :

1. **Barre d'outils à plat** (`.page-outils`, sans carte) : à gauche ce qu'on regarde,
   à droite les actions (`.page-outils-actions`), la principale en dernier. Une ligne, contrôles de 32–34 px.
2. **Bandeau d'identité** facultatif (`.page-identite`) : nom en 1,25 rem, puis une ligne de faits.
3. **Contenu** : une carte `.panel` par bloc, **jamais de carte dans une carte**.
   Grilles pleine largeur ; colonne latérale `minmax(280px, 340px)` seulement pour une fiche.
4. **Sans sélection** : jamais « choisissez… » dans une boîte vide,
   mais l'**annuaire** filtrable et trié, avec les chiffres de la semaine.

Espacements : 16 px entre blocs, 12 px dans une carte, 8 px entre contrôles.
Titre de carte 0,98 rem graisse 600. Tableaux : en-tête collant, lignes de 36 px, nombres à droite.

## Composants

**Stylés globalement** (`app.css`) — ne pas les restyler dans une vue, sauf la largeur :

- champs `input`, `select`, `textarea` ;
- boutons `.btn`, `.btn--primary` (= `.btn--accent`), `.btn--ghost`, `.btn--danger`, `.btn--sm`, `.btn--icon` ;
- `.panel` (bordure, rayon 8, marges 14/16 px), `.view` ;
- `.pill` (+ `.good`, `.warn`, `.bad`, `.dot`) ; `table.ref` (nombres en `.num`) ;
- `.empty-state`, `.banner--error`, `.banner--info`.

**Briques partagées :**

- `components/Tuile.tsx` (`<Tuiles>`, `<Tuile>`) : libellé, chiffre 28 px, détail, action facultative.
  `ton` colore la valeur, `onClick` en fait un bouton, `actif` un filtre enfoncé.
- `components/Onglets.tsx` : contrôle segmenté, ← → d'un onglet à l'autre.
- `styles/outils.css` : `.segmente`, `.pastille`, `.carte-tableau` + `.carte-tete`
  (`--haute` pour une liste qui défile dans sa carte), `.page-retour`, `.page-note`.
- `components/ChampEnLigne.tsx`, `ValeursReference.tsx` (compléter ou corriger en ligne) :
  donnée absente = pastille « Ajouter » (point orange) ; donnée présente = valeur + crayon
  (visible au survol et au focus). Entrée enregistre, Échap annule, erreur sous le champ,
  « Enregistré » annoncé, jamais d'alerte bloquante.
  Valeur modifiée = marque « modifiée » (pastille pointillée) dont la bulle propose
  « Revenir à la valeur du fichier ». Lecture seule : valeur et marque, sans bouton.
- `components/ImagesTache.tsx` : vignettes carrées à plat (bord 1 px, rayon 8).
  Retrait confirmé **dans** la vignette (« Retirer » / « Garder »), pas dans une modale.
  Pendant un glisser, cadre pointillé `--accent`. Aperçu : Échap ferme, ← → naviguent.
  Sur une carte de tâche : compteur icône + nombre, jamais d'emoji.

## Ranger le CSS

- `app.css` : jetons, base, composants partagés.
- Styles d'un écran : fichier à côté de l'écran (`views/PromoView.css`…), importé par le composant.
- En sortant un bloc d'`app.css`, le supprimer d'`app.css` : pas de doublon.
