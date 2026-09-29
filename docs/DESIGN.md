# Charte d'interface cal-iut

Refonte du 29/09/2026. Ce document fixe les règles communes à tous les écrans.
Il ne remplace pas les décisions prises avec les utilisateurs et consignées dans
les commentaires du code (« retour utilisateur du … ») : **une décision
utilisateur documentée l'emporte toujours sur cette charte**. En cas de doute,
on garde ce que l'utilisateur a demandé et on le rend plus propre.

## Pour qui

L'équipe qui fabrique et corrige les emplois du temps (quelques personnes, sur
poste de travail, plusieurs heures par semaine), les enseignants et étudiants
qui consultent leur planning (liens publics, souvent sur téléphone), et les
collègues en lecture seule. Les utilisateurs connaissent déjà l'outil : on
**ne déplace pas** les fonctions, on ne renomme pas les onglets, on ne change
pas les raccourcis. On range, on clarifie, on accélère.

## Principes

1. **Outil, pas vitrine.** Densité maîtrisée, alignements nets, aucun élément
   décoratif. Pas de dégradé, pas d'ombre portée sur les panneaux (bordure
   1 px), pas de glassmorphisme, pas d'emoji dans l'interface, pas d'icônes
   décoratives, pas de gros titres « héro », pas de cartes arrondies à 16 px.
2. **Une action principale par écran** (`.btn--primary`). Le reste en
   `.btn` (secondaire) ou `.btn--ghost`. Les actions destructrices en
   `.btn--danger`, jamais par défaut, toujours confirmées avec la liste de
   ce qui sera touché.
3. **La couleur porte du sens.** L'accent bleu encre (`--accent`) = sélection,
   action principale, focus. Vert/orange/rouge (`--good`/`--warn`/`--bad`) =
   états. Les couleurs de séance (`--type-cm`, `--type-td`, `--type-tp`,
   `--type-eval`) ou de matière = données. Jamais de couleur « pour faire
   joli ». Un état n'est jamais porté par la couleur seule (mot ou symbole).
4. **Le texte dit la chose.** Français courant, pas de jargon interne
   (« worker », « job », « payload », « CACHED », « slot »). Libellés courts,
   verbes à l'infinitif pour les boutons (« Placer », « Copier le lien »).
   Dates lisibles (« lun. 12 oct. ») plutôt qu'ISO. Pluriels corrects.
5. **Rien ne disparaît en silence.** Chaque action donne un retour visible
   (état du bouton, message, mise à jour de la grille). Chargement : état
   explicite, l'ancien contenu reste lisible. Erreur : message utile + quoi faire.
6. **Clavier et accessibilité.** Focus visible (`--focus`), ordre de tabulation
   logique, `aria-live` sur les retours, cibles ≥ 32 px (44 px au tactile),
   contrastes AA. Échap ferme les modales, Entrée valide.

## Jetons (`frontend/src/styles/app.css`, `:root`)

| Jeton | Usage |
|---|---|
| `--bg` | fond de page |
| `--surface`, `--surface-2`, `--surface-3` | panneaux, zones secondaires, survol/pressé |
| `--ink`, `--ink-soft`, `--ink-faint` | texte principal, secondaire, tertiaire (placeholder) |
| `--border`, `--border-strong` | séparateurs, contours de champs/boutons |
| `--accent`, `--accent-hover`, `--accent-soft` | action principale, sélection |
| `--good`, `--warn`, `--bad` (+ `-soft`, `-text`) | états |
| `--type-cm`, `--type-td`, `--type-tp`, `--type-eval` | types de séance |
| `--radius-sm` (4), `--radius` (6), `--radius-lg` (8) | rayons — rien au-delà de 8 px |
| `--control-h` (32 px) | hauteur des champs et boutons |
| `--shadow-pop` | UNIQUEMENT pour ce qui flotte (modale, menu, infobulle) |

Aucune couleur en dur dans les composants : toujours un jeton. Le mode sombre
suit automatiquement si l'on n'utilise que des jetons.

## Composants de base (déjà stylés globalement)

- Champs : `input`, `select`, `textarea` sont stylés au niveau élément — ne pas
  les restyler par vue sauf besoin réel (largeur).
- Boutons : `.btn`, `.btn--primary` (= `.btn--accent`), `.btn--ghost`,
  `.btn--danger`, `.btn--sm`, `.btn--icon`.
- Conteneurs : `.panel` (bordure, rayon 8, padding 14/16), `.view` (colonne,
  gap). En-tête de page : `PageHeader` (titre + une ligne), déjà rendu par
  `App.tsx` — ne pas ajouter de second grand titre dans la vue.
- Étiquettes : `.pill` (+ `.good`/`.warn`/`.bad`, `.dot`).
- Tableaux : `table.ref` (en-tête collant, survol de ligne, alignement à
  gauche ; nombres alignés à droite avec `.num`).
- Vide : `.empty-state`. Bandeaux : `.banner--error` / `.banner--info`.

## Typographie

Police système, corps 14 px, interlignage 1,45, chiffres tabulaires. Titres en
graisse 600, jamais plus de 1,2 rem dans une vue (le `h1` de page est dans
`PageHeader`). Codes de cours en `--mono`. Pas de capitales forcées sauf les
libellés de groupe de la navigation.

## Organisation du CSS

`app.css` contient les jetons, la base et les composants partagés. Les styles
propres à un écran vont dans un fichier à côté de l'écran
(`views/PromoView.css`, `components/SessionGrid.css`…), importé par le
composant. En déplaçant un bloc hors d'`app.css`, le supprimer d'`app.css` :
pas de doublon.
