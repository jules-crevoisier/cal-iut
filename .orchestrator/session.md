# Session — Vue Promo densite + park multi

**Goal:** Une grille Promo lisible (filtres année/parcours) + file multi-park + un seul panneau latéral (À placer ∪ parkés).
**Done:** Filtrer BUT1 sans voir BUT2/3 ; park N séances, en sélectionner une pour poser ; plus la sensation « deux systèmes ».
**Out of scope:** Celcat, MCP, règles force/blocking, duel Impeccable/Taste.
**Users:** Admin planning (desktop-first, chrome Promo existant).
**Mode:** Operate.
**Locked choices (agent, 03/09/2026):**
1. **C** — filtres année + parcours, option « Tout »
2. **A** — file multi-park, sélection d’une carte pour poser
3. **A** — un panneau latéral unifié À placer + parkés
4. **A** — rester dans le chrome Promo (pas de duel design)
5. Hors scope Celcat/MCP/force confirmé
**Acceptance:**
1. Filtre année BUT1 → colonnes / lignes hors BUT1 absentes ; « Tout » restaure.
2. Filtre parcours affine encore ; combinaison année+parcours OK.
3. `parked[]` peut contenir N séances ; `selectedSessionId` au plus une.
4. Drop semaine ajoute à la file (ne remplace plus) ; Annuler une carte restaure cette séance.
5. Poser une case retire la sélectionnée de la file ; les autres restent.
6. Panneau latéral affiche section Parkés + À placer dans le même panneau.
**Branch:** `feature/promo-filtre-park-multi`
**Go:** 03/09/2026
