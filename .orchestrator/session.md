# Session

goal: rendre l’onglet admin Celcat lisible en 5 s — bandeau statut Live + 3 étapes (armer, semaines nuit, extras), chrome cal-iut inchangé.

out_of_scope: nouveaux endpoints ; cliqueur ; push immédiat Live ; rollback ; onglets Comptes/MCP ; changer les actions API (ON/OFF, valider semaines, Ajouter/Ignorer, logs).

users: admin, desktop Administration. Mobile-first 320px.

branch: feature/celcat-admin-ui

locked:
- Bandeau héros : ÉCRITURE OFF / ON. Texte clair : si ON, chaque edit planning écrit Celcat tout de suite.
- Worker joignable / injoignable + dernière validation visibles dans le bandeau (plus du muted).
- Interrupteur, pas une case à cocher anodine (paie enseignants).
- Parcours 3 étapes : 1 armer l’écriture → 2 choisir les semaines du lot de nuit → 3 traiter les extras.
- Semaines : distinguer sélection en cours vs déjà validées. Plus un mur de 30 cases identiques.
- « Valider » relabel : enregistre le lot de NUIT, pas un envoi immédiat.
- Extras : quoi faire (Ajouter au planning / Ignorer) vs journal : ce qui s’est passé (créé / bloqué + motif).
- UI only. Mêmes fetch : etat, saisie, valider, extras, logs.
- Chrome Administration inchangé (panels, boutons, pills comme Comptes). Pas de nouveau monde, pas de duel.

open: none

design_pick: incumbent-admin

acceptance:
- Bandeau affiche OFF ou ON + conséquence Live + worker + dernière validation.
- L’interrupteur a un rôle switch (pas une checkbox anonyme) ; OFF par défaut inchangé.
- Étapes 1/2/3 visibles ; étape 2 explique lot de nuit ; bouton n’est plus juste « Valider ».
- Semaines : libellé Semaine N, état validé vs coché, multi-select conservé.
- Extra ouvert : Ajouter + Ignorer ; vide : aucun extra ouvert.
- Journal séparé, kinds + motifs lisibles (créé / bloqué).
- Aucun nouvel appel réseau. Tests TDD puis E2E 320px.
