# Session — polish placements Vue Promo

**Goal:** Unifier warnings/force, SAE placeables, click À placer, Celcat enqueue MCP, Retirer visible.
**Out of scope:** Design duel (chrome Promo existant), Live Celcat write.
**Stack:** FastAPI + React PromoView / APlacerView / MCP tools.
**Acceptance:**
1. Cellules SAE (et bandeaux férié/événement) restent cliquables si placement/park actif.
2. WS* apparaissent dans `/placements/manquantes` et se placent un jour SAE ; WR* restent bloqués.
3. 409 / validate renvoient blocking + hard + soft ensemble ; UI affiche tout ; Forcer seulement si blocking vide.
4. Copy : pedago + indispo forçables ; PAC/SAE/férié non.
5. MCP `unplace` passe par `deposer_placement` (file Celcat delete).
6. Bouton Retirer sur chip Promo (+ confirm).
7. Suggestions À placer utilisent `placerAvecConfirmation`.
**Branch:** `feature/promo-placement-polish`
**Go:** user confirmed 03/09/2026.
