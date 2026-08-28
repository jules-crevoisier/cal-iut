# Session
goal (twice-revised): teacher personal link, minimal essentials only.
status: DONE.
history: user first asked for full visual redesign of this page -> waved that off entirely ("je m'en fiche") wanting only "consulter tous les cours de tout le semestre" -> further trimmed to "juste l'essentiel c'est à dire la barre des semaines et le planing qui fit bien l'écran et soit adapté".
what shipped (views/EnseignantView.tsx, readOnly branch only — non-readOnly/scheduler-facing view untouched):
- WeekBar un-gated (already done previous round) — browsable across the whole semester.
- Removed the `.layout` 2-column grid split for readOnly (it would leave an empty 300px gutter now that there's only one panel) — grid panel renders full-width standalone instead.
- Removed for readOnly only: ShareBar (copy link/.ics/écrire), the compliance callout, and the raw-constraints-detail panel, and the separate "toutes ses interventions du semestre" SemesterAgenda list panel — none of these were named in the user's "juste l'essentiel" list; browsing weeks in the grid already covers "voir tous ses cours du semestre" from the prior ask. All of these stay exactly as before for the non-readOnly (scheduler) view.
- Result: a teacher's personal link now shows only readonly-banner (name/context, from App.tsx, unavoidable) + WeekBar + the SessionGrid, full-width, existing DayStrip/onlyDay mobile mechanism already collapses to 1 day column under 760px so it fits 320px without horizontal scroll.
verify: tsc -b clean, npm run build clean, live server confirmed serving new JS hash (CSS untouched, hash unchanged — expected, no style edits this round).
note_to_self: I removed ShareBar/callout/raw-panel/agenda-list on my own literal reading of "juste l'essentiel" without asking first (2nd time trimming scope this session after the user cut back an over-built deliverable) — flagged this explicitly to the user in the reply so they can ask to restore any of it if I over-trimmed.
still open (unchanged, not re-raised again): GroupeView.tsx readOnly branch has the same original hidden-WeekBar issue, not touched (scope stayed "la partie prof" throughout). teacher_contacts.yaml still empty.

## follow-up (même fil, après DONE ci-dessus)
- Ajout du bouton "Agenda .ics" seul (pas tout ShareBar) sur le lien perso readOnly, à côté du titre de semaine.
- Nouveau components/TeacherLinksList.tsx : liste simple nom+lien+bouton Copier pour tous les profs, accessible via un bouton "Tous les liens" dans Vue Enseignant (non-readOnly), bascule avec le planning normal. Distinct de l'annuaire complet existant (Référentiel > Référence > Liens & partage, qui garde séances/heures/mail/CSV/groupes).

## follow-up 2 (même fil, gros nettoyage demandé en vrac)
Réponses/actions, une par item du message groupé du 27/08 :
1. Régénération ciblée (RegenPanel) — QUESTION posée par l'utilisateur, pas une demande de suppression. Répondu : ce n'est PAS un filet de sécurité pour le glisser-déposer, ça relance le solveur CP-SAT sur UNE semaine (le drag ne fait que déplacer une séance à la main) — fonctionnellement distinct, gardé tel quel, pas touché.
2. Séparateur pause déjeuner "en dehors du tableau" — bug confirmé et corrigé dans TdWeekGrid.tsx (le `<p className="lunch-marker">` après `</table>` déplacé en vraie `<tr>` inline entre les créneaux, même motif que SessionGrid.tsx `.sessiongrid-pause`). TimetableCalendar.tsx (FullCalendar, viewMode teacher/room) a le même souci mais n'a pas été touché — modèle de rendu différent (pas de lignes HTML), pas creusé cette fois.
3. "Rouge dans Contraintes" — `.check.fail` (ContraintesView) passé de rouge (--bad/--danger) à ambre (--warn), pass/fail restent visuellement distincts.
4. "Vue groupe on peut l'enlever" — confirmé via question : l'ONGLET entier retiré de SideNav.tsx. Le composant GroupeView.tsx et sa route restent (nécessaires au lien personnel `mode=groupe` envoyé à un groupe d'étudiants, même mécanisme que le lien prof) — juste plus accessible depuis la nav normale.
5. "Charger données / Générer / Recalculer tout" — confirmé via question (génération toujours en CLI) : les 3 boutons retirés de Toolbar.tsx, handleIngest/handleSolve supprimés d'App.tsx, imports ingest/solve nettoyés. Message d'état vide mis à jour en conséquence.
6. PageHeader stats (séances/matières/semaines/trous/jours isolés/score) + pastille "Prochaine semaine modifiable" — retirés (PageHeader.tsx), pur affichage, aucune donnée perdue ailleurs.
verify: tsc -b clean, npm run build clean, live server confirmed serving new hash each step.

## follow-up 3 (drag safety + Docker)
- Drag-and-drop safety question answered from actual code (utils/moveSession.ts::performMove): hard conflicts -> browser confirm() to force anyway; soft warnings -> notice only, move proceeds automatically. User confirmed keeping this (force popup kept) — no code change.
- New Docker deliverable for frontend-only deploy (Dokploy): frontend/Dockerfile (multi-stage: node:22-alpine build -> nginx:1.27-alpine runtime, ~40-50MB final), frontend/nginx.conf.template (envsubst ${BACKEND_URL}, gzip, long-cache immutable on /assets/, static-first-else-proxy-to-backend on /, /healthz for HEALTHCHECK — no path-based SPA fallback needed, app routes via URL hash only), frontend/.dockerignore, frontend/docker-compose.yml (local test convenience only, BACKEND_URL=host.docker.internal:8000).
- COULD NOT build/verify the image this session — Docker daemon unreachable from this sandbox (confirmed via both Bash and PowerShell, even with dangerouslyDisableSandbox; Docker Desktop process not running on the host at all per Get-Process). Did a careful static review instead (envsubst semantics, try_files/index resolution, proxy_pass with variables gotcha). User should run `docker compose up --build` themselves to get a real build/runtime check before trusting this in Dokploy.
- Backend NOT containerized (out of scope — user asked for "le front" specifically); BACKEND_URL env var is how Dokploy wires the two together at deploy time.

## follow-up 4 (Docker, testé réellement)
Docker Desktop relancé par l'utilisateur — build + run réel effectués (docker build, docker compose up), pas juste relu statiquement cette fois.
Bug trouvé et corrigé en testant : `proxy_pass ${BACKEND_URL}$uri$is_args$args;` faisait basculer nginx en résolution DNS À LA REQUÊTE (piège classique : toute variable nginx dans proxy_pass déclenche ce mode) → "no resolver defined to resolve host.docker.internal" → 502 systématique. Fix : `proxy_pass ${BACKEND_URL};` seul (après envsubst c'est 100% littéral, zéro variable nginx) — nginx transmet automatiquement l'URI d'origine quand proxy_pass n'a pas de chemin, résolution une fois au démarrage, plus besoin de `resolver`.
Vérifié après fix : image 74.3MB, conteneur (healthy), /meta et /app-state via le proxy identiques byte-for-byte au backend direct (127.0.0.1:8000), gzip actif, cache-control immutable sur /assets/, 404 propre sur asset inexistant (ne tombe pas sur le backend). Nettoyé (docker compose down + rmi) après test.
Status: DONE, vérifié en conditions réelles, prêt pour Dokploy (définir BACKEND_URL là-bas vers le service backend interne).

## follow-up 5 (backend dockerisé aussi, testé bout en bout)
User a précisé : ils veulent front+backend reliés (pas juste une photo figée). Backend dockerisé (Dockerfile racine, contexte = repo root — nécessaire car main.py/session.py calculent CONFIG_DIR/DB_PATH via Path(__file__).resolve().parents[N] relatif à l'emplacement réel du fichier source).
Bug réel trouvé en testant : `pip install .` (non-éditable) déplace le package dans site-packages -> casse parents[3] -> FileNotFoundError sur data/config/groups.yaml. Fixé avec `pip install -e .`.
data/cal-iut.db (Run #13, 2392 placements) baké directement dans l'image depuis le disque (pas git, *.db est gitignored mais Docker build lit le filesystem local) — le premier déploiement affiche tout de suite les vraies séances. VOLUME /app/data pour que les écritures ultérieures (drag&drop déployé, régen ciblée) survivent aux redémarrages (Docker ne seed le volume qu'une fois, à la création).
Testé RÉELLEMENT bout en bout via `docker compose up --build` (root docker-compose.yml, nouveau) : backend+frontend healthy, /timetable via le frontend proxy = identique au backend direct (2392 placements, run_id 13), persistance vérifiée par un restart réel du backend (données toujours là après).
3 fichiers ajoutés à la racine : Dockerfile, .dockerignore, docker-compose.yml. Commit + push fait (PR #1 mise à jour automatiquement).
Status: DONE, vérifié en conditions réelles (build+run+restart+persistence), prêt pour Dokploy.

## follow-up 6 (déploiement Dokploy réel — échec puis fix)
Dokploy a build depuis un clone GitHub (pas depuis le disque local) -> `COPY data/cal-iut.db data/cal-iut.db` a échoué ("not found") car data/cal-iut.db était gitignored, jamais poussé sur GitHub. C'était LE trou signalé dans ma question précédente, confirmé réel dès le premier vrai déploiement.
Fix (PR #3, mergée) : exception `!data/cal-iut.db` dans .gitignore + fichier committé (~4MB, run #13, 2392 placements).
Vérifié avec un clone frais réel (git clone --depth 1 vers /tmp, PAS depuis le disque local existant) : le fichier est bien dans le clone, docker build + run depuis CE clone -> /timetable retourne bien 2392 placements, run_id 13. C'est exactement ce que Dokploy fait.
PR #1, #2, #3 toutes mergées sur main — main est maintenant déployable tel quel sur Dokploy.
Status: DONE, prêt à relancer le déploiement Dokploy.

## follow-up 7 (vue à placer — placement manuel + forçage)
User: "on ai toutes les séance a chaque séance toutes les contrain, la ou il devrait etre placer dans l'idéal, et que l'on puisse les placer dans le planing... fait a la main et ne respectera pas toutes les contrainte... enregistré et que cela s'update dans les autres vues".
Découverte : presque tout existait déjà (liste complète des manquantes, placement qui persiste en DB + refresh partout via onPlacement -> loadTimetable/refreshAppState). Le backend (`placer_seance`, POST /placements/{id}/placer) supportait DÉJÀ `force` avec les 2 niveaux de blocage (institutionnel jamais contournable, ressource contournable) — zéro changement backend nécessaire.
Ajouté côté frontend (PR #4, mergée) : affichage de `semaines_possibles` (déjà renvoyé, jamais affiché), sélecteur manuel semaine/jour/horaire par carte (hors suggestions sûres), flux confirm-puis-force sur conflit (même UX que le drag du Toolbar), parsing du détail structuré des 409 (`hard_conflicts`/`soft_warnings`) pour ne jamais afficher de JSON brut à l'écran (nettoyé aussi sur le flux "safe slot" existant au passage).
Vérifié contre le serveur local réel (409 institutionnel en string, 409 structuré en objet) sans muter de vraie donnée (semaines passées/occupées choisies exprès).
Status DONE. Note ménage session : la branche `main` locale avait pris du retard (jamais fast-forward après les merges précédents faute de pouvoir checkout avec des fichiers modifiés en cours) — corrigée via `git branch -f main origin/main`, aucun impact sur GitHub qui était toujours à jour.

## follow-up 8 (vue semaine allegee + drag deplace vers vue promo)
Fait après le mot de passe (l'utilisateur a rappelé que ces items étaient aussi demandés dans le même message) :
- QualityPanel + RegenPanel retirés de Vue Semaine (sidebar 300px->260px, cellules grille 76px->92px).
- Drag&drop retiré de TdWeekGrid.tsx et TimetableCalendar.tsx (Vue Semaine, lecture seule pour le déplacement, clic->détail conservé).
- Drag&drop ajouté à PromoView.tsx (même logique performMove/confirmation-forçage que l'ancien TdWeekGrid). Nouvelle liste App.tsx `promoPlacements` (non filtrée, chargée seulement quand l'onglet Promo est actif) car `placements` (Vue Semaine) est filtrée par le Toolbar et n'aurait pas trouvé la bonne séance à déplacer depuis Vue Promo.
PR #7 (mot de passe) et #8 (ce lot) — statut à vérifier avant de clore.

## follow-up 9 (3 bugs signales apres coup)
1. Popups navigateur desactivees -> window.confirm() silencieusement false -> force impossible. Fix : nouveau utils/confirmDialog.ts (event-bus + Promise) + components/ConfirmModal.tsx (montee une fois dans App.tsx), remplace window.confirm dans moveSession.ts et placement.ts.
2. WR112 "duo synchronise" bloquait TOUJOURS meme avec force=true (3 lieux dans main.py : validate_placement/move_session/placer_seance, check AVANT le check de force). User a explicitement demande de pouvoir forcer -> move_session et placer_seance modifies (`and not body.force`). Teste reellement (curl PATCH sans force = 409 duo-sync ; avec force=true = 200). validate_placement et suggestions laisses tels quels (continuent a signaler le conflit / ne pas suggerer automatiquement, correct).
3. TD BUT1 (effectif 30) dans H.006 (tp_standard, capacite configuree 30) -> pile a la capacite, jamais au-dessus (verifie : 0 vraie violation effectif>capacite nulle part dans tout le planning, 151 placements exactement a la limite). User confirme H.006 fait reellement 15 places max -> rooms.yaml corrige (30->15). IMPACT REEL : 41 placements actuellement en h006 ont maintenant effectif>capacite (surtout BUT1-S1 TD, WR112/113/108/109 + quelques BUT2/BUT3-FC) -> a signaler clairement, PAS deplace automatiquement (config-only fix demande, pas un re-solve).
Verifie : tsc -b/build propres, redeploye en local, suite pytest complete relancee (duo_synced=[] dans les 3 fixtures TestClient, donc inerte pour les tests existants).
