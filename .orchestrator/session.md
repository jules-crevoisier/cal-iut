# Session
goal: Search lands on admin fiches (matière / prof / salle / groupe) with all known data + week grid; À placer moves into Vue Promo; Promo uses full width on large screens.
out_of_scope: personal links (mode=prof/groupe) stay essential-only; no design duel; no cell stretching; no multi-day Promo; no new backend data invented.
users: admin desktop (operate); mobile already has drawer; personal-link audience unchanged.
branch: feature/search-fiches-promo
design_pick: da_now (existing panels / tokens)
inspiration: skip (DA locked)
locked:
- Search kinds stay Enseignant / Groupe / Cours / Salle. Index from full catalogs (teachers, groups, courses, rooms), not only placed rows — so unplaced courses and unused rooms still appear.
- Click → full page fiche (hash): vue=prof&prof=CODE | vue=salle&salle=ID | vue=cours&cours=CODE | vue=groupe&groupe=ID (groupe still hidden from SideNav).
- Fiche layout (admin only): identity header + all existing payload facts + week grid below. Same DA as current panels.
- Prof fiche = enrich EnseignantView (keep WeekBar + SessionGrid). Add better course list, volumes, constraints/dispos/violations, unplaced for that teacher, contacts/link already there.
- Matière fiche (new): name/code, type volumes, teachers, groups, rooms used, placed vs missing sessions, constraints that mention the course if any, week grid filtered to that course.
- Salle fiche (new): label, capacity, type, equipment, combined-with, occupation week grid, sessions using it, empty slots that week.
- Groupe fiche = enrich GroupeView the same way (search already lands there).
- Failure: unknown id → fiche with “introuvable” + link back to search; empty week is a real empty week, not a wrong filter.
- À placer tab removed from SideNav. Placement lives as a panel in Vue Promo (list of manquantes + click séance then click cell — reuse existing placer / force / valider / undo).
- Deep links #vue=aplacer and À traiter items redirect to vue=promo with panel open.
- Promo large screen: lift .view max-width:1400px for Promo only; keep one-day + horizontal scroll; do not stretch cell min-widths.
open:
- none
acceptance:
- Search “WR106” opens matière fiche with name, volumes, teachers, sessions; week grid shows that course, not a blank Semaine.
- Search a teacher opens enriched Enseignant fiche (courses list + constraints + grid).
- Search a room opens salle fiche with occupation grid, not Référence catalog.
- Search a group still opens groupe fiche (enriched).
- Rooms/courses with 0 placements still appear in search.
- SideNav has no “À placer”. Vue Promo shows the à-placer panel; placing a session updates other views.
- #vue=aplacer opens Promo with that panel.
- Promo at ≥1440px uses full content width (no 1400 cap); cells not stretched; 320px still no page overflow.
- mode=prof / mode=groupe unchanged (no new fiche chrome).
