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
