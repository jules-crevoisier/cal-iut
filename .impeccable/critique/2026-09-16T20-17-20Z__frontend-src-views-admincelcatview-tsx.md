---
target: onglet Celcat
total_score: 16
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
timestamp: 2026-09-16T20-17-20Z
slug: frontend-src-views-admincelcatview-tsx
---
Method: dual-agent (A : revue design isolée · B : détecteur + navigateur isolé)

# Critique design — onglet Celcat (16/09/2026)

## Note de santé design

| # | Heuristique | Note | Problème clé |
|---|---|---|---|
| 1 | Visibilité de l'état | 1 | « Rafraîchir » ne relit rien ; relevé et état jamais rechargés sans F5 ; « Tout concorde » en gris ; file masquée quand tout va bien. |
| 2 | Monde réel | 2 | Sélecteur daté, pastilles « Semaine 1…30 » non datées ; jargon Live/armer/worker/lot/extras/relevé. |
| 3 | Contrôle et liberté | 2 | Couper « Écriture » vide la file sans confirmation ; aucun retrait de job. |
| 4 | Cohérence | 1 | Écriture/Live armé/saisie ; boutons natifs et stylés mélangés ; hex en dur ; --bordure indéfini. |
| 5 | Prévention des erreurs | 2 | Bouton principal « Corriger » inclut les suppressions ; confirmation = un nombre sans liste. |
| 6 | Reconnaître vs rappeler | 1 | Âge du relevé loin de la comparaison ; horodatages au survol ; onglet et semaine oubliés. |
| 7 | Flexibilité | 1 | Pas de lien direct, pas d'état URL, 30 pastilles une par une. |
| 8 | Minimalisme | 2 | « Contenu Celcat » empile tout. |
| 9 | Récupération d'erreur | 2 | Causes groupées bien ; une erreur efface le tableau ; file disparaît si son appel échoue. |
| 10 | Aide | 2 | Aide sur place ; aucune légende des 6 états de pastille. |
| **Total** | | **16/40** | **Faible** |

## Spécificité
Spécifique dans les mots, générique dans la forme : la structure suit la tuyauterie (écriture, worker, lot, extras, file, relevé, comparaison, journal), pas la question « est-ce que ça concorde ? ». Détecteur : CLI propre (0) ; injecté 5-12 constats/onglet surtout globaux (Roboto, ombre .panel, H1→H3 du shell, lignes longues à 1440) ; réels propres à Celcat : pastilles de verdict 10,9 px, 14 tirets cadratins ; faux positif : text-occlusion (étiquettes du détecteur). Pas de superposition visible chez l'utilisateur (Chromium sans affichage, données simulées).

## Priorités
- [P0] L'écran ne boucle jamais sur le résultat : Rafraîchir n'attend rien, Corriger relit la comparaison contre le même relevé, verdict gris, file masquée si conforme. Correctif : sonder l'instantané jusqu'au changement de releve_le puis recharger comparaison + état, progression affichée, verdict en tête coloré, file toujours visible. → /impeccable harden
- [P1] Boutons d'écriture en prod = natifs 21 px collés (Corriger, Corriger sans supprimer, Rafraîchir, Reconstruire ×2), select 19 px ; « Copier » seul stylé ; défaut inclut suppressions ; confirmation sans liste. Correctif : primaire .btn--accent « Corriger (sans supprimer) », suppressions séparées .btn--danger « Examiner les N suppressions » avec liste, Reconstruire hors Activité. → /impeccable layout
- [P1] Deux interrupteurs rouges identiques aux effets opposés ; couper l'écriture vide la file sans confirmation ; libellé du second perdu à 320 px ; ÉCRITURE ON en rouge alarme. Correctif : confirmation chiffrée, aria-describedby, ON neutre/vert, rouge réservé aux pannes. → /impeccable clarify
- [P1] Arrivée sur Pilotage ; 30 pastilles = 1100 px à 320 px, CTA à y≈1950 ; pastilles non datées ; états retirée/cochée à la couleur seule ; file dupliquée dans 2 onglets. Correctif : ouvrir sur le verdict de la semaine en cours, réglages repliés, libellés datés, mot par état + légende ≤4, un seul emplacement file. → /impeccable distill
- [P2] .bad/.good inexistants hors pastilles (périmé, échec relevé, corrections en attente en noir) ; 3 verdicts même pastille rouge ; --bordure indéfini ; dates ISO brutes ; pas d'aria-live. → /impeccable harden

## Personas
Alex : Pilotage à chaque visite, pas de compteurs d'onglet, Rafraîchir + F5, Lancer maintenant grisé sans raison, 30 pastilles une à une, ancienne comparaison affichée pendant le chargement.
Sam : onglets pas en tablist, aucun aria-live, h4 « Créées 1 Copier », H1→H3, horodatages en title, semaines passées disabled hors tabulation, cibles <44 px (Corriger 21, Rafraîchir 21, select 19, Ajouter/Ignorer/Copier 28).

## Mineures
(s) au lieu de pluriel() ; identiques sans date ; « Extras Live » non défini, numérotation 1-2-3 trompeuse ; onglet actif peu contrasté ; lignes >130 caractères à 1440 ; « Échecs 0 » des captures = artefact des données simulées.

## Questions
- Lot de nuit et Lancer maintenant sont-ils encore des idées d'utilisateur une fois la réconciliation automatique ?
- Verdict gris + seul rouge fort sur ÉCRITURE ON : « tout va bien » ou « danger » ?
- Pourquoi l'irréversible se valide sur un nombre, et le réversible a sa liste ?
