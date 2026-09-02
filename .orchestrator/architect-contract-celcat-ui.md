# Architect contract — Celcat admin tab (UI only)

goal: Redesign the admin Celcat tab so status (ÉCRITURE OFF/ON + Live consequence + worker + last validation) and the 3-step path (arm writes → night-lot weeks → extras) are readable in 5 seconds, without changing APIs or leaving the existing cal-iut chrome.

approach: One view file, same fetch/mutation set, restyle with existing `.view` / `.panel` / `.btn` / `.pill` plus a `celcat-*` CSS block in `app.css` (same pattern as AdminUsersView). Hero is a switch (`role="switch"`) plus non-muted meta; weeks are labelled chips with selected vs already-validated states; night-lot CTA is not the word « Valider » alone; extras actions stay a separate panel from the journal.

rejected: Splitting into `features/celcat/` subcomponents (hero, weeks, extras, journal) — no reuse, same data load, AdminUsersView already proves one file + CSS block is the house pattern.

```
goal: Redesign admin Celcat tab for 5-second readability (hero Live status + 3 steps) without new APIs or a new visual world.
approach: Keep AdminCelcatView as the only React module; add celcat-* classes in app.css; reuse view/panel/btn/pill; lock copy, roles, and fetch set.
rejected: Extract 4 feature-folder subviews — unjustified for a single admin tab with one loader.
contract:
- types/interfaces
- APIs / routes
files:
- path — create|edit — purpose
acceptance:
- should ... when ...
order: tdd → build → e2e
risks: ...
done_when: ...
```

---

## Module boundaries

Keep **one React module**: `frontend/src/views/AdminCelcatView.tsx`.

Justified: single admin tab, one `charger()` (`Promise.all` of etat + extras + logs), no shared widgets, AdminUsersView / McpKeysView are already one-file views. Do not create `frontend/src/features/celcat/` or sibling component files.

Allowed inside that file only: small presentational helpers (hero, week chip, extra row) if they stay unexported and do not own fetches.

Do **not** edit:

- `frontend/src/components/SideNav.tsx` — Administration group already has Celcat.
- `frontend/src/views/AdminUsersView.tsx` — chrome reference only.
- `frontend/src/api/client.ts` — types and functions already exist.
- `frontend/src/App.tsx` — already mounts `<AdminCelcatView />` for `activeTab === "celcat"` when `moi?.role === "admin"`.
- Backend, worker, cliqueur, Comptes, MCP.

CSS lives in `frontend/src/styles/app.css` under a Celcat block (mirror the AdminUsersView block). Reuse existing tokens (`--accent`, `--good`, `--bad`, `--warn`, `--surface`, `--border`, `--shadow`). No new font, no new radius language, no new button primitives.

---

## Chrome (locked)

Reuse, do not restyle globally:

| Token | Use |
|---|---|
| `.view` | Root `<section>` |
| `.panel` | Hero + each numbered step + journal |
| `.btn` `.btn--accent` `.btn--sm` `.btn--ghost` `.btn--danger` | Night-lot CTA, Ajouter, Ignorer |
| `.pill` `.pill.good` `.pill.bad` `.pill.warn` `.pill.mini` | Worker / kind badges (same as comptes) |
| `.alerte` + `role="alert"` | Load/action errors |
| `.muted` | Loading, empty extras, empty journal **only** |
| `--font` / existing `h3` in `.panel` | Titles |

`.muted` is **forbidden** on worker status, last validation, Live consequence, and ÉCRITURE OFF/ON.

---

## Component / CSS class names (locked)

Root: `<section className="view celcat">`.

Hero panel: `.panel.celcat-hero` with modifier `.celcat-hero--off` | `.celcat-hero--on`.

| Class | Role |
|---|---|
| `.celcat-hero-statut` | Visible `ÉCRITURE OFF` or `ÉCRITURE ON` |
| `.celcat-hero-consequence` | Live consequence sentence (not `.muted`) |
| `.celcat-hero-meta` | Worker + last validation row |
| `.celcat-switch` | The control with `role="switch"` |
| `.celcat-etape` | Numbered step panel (on `.panel`) |
| `.celcat-etape-num` | Visible `1` / `2` / `3` |
| `.celcat-semaines` | Week chip grid |
| `.celcat-semaine` | One week control |
| `.celcat-semaine--cochee` | In current draft selection |
| `.celcat-semaine--validee` | In `etat.semaines_validees` |
| `.celcat-semaine--retiree` | Validated remotely, deselected locally (pending removal) |
| `.celcat-extras` | Open-extras list |
| `.celcat-extra` | One extra row |
| `.celcat-journal` | Journal list |
| `.celcat-journal-item` | One log line |
| `.celcat-journal-item--created` | kind created |
| `.celcat-journal-item--blocked` | kind blocked |

Existing button classes only: night-lot uses `.btn.btn--accent`; Ajouter `.btn.btn--sm`; Ignorer `.btn.btn--sm.btn--ghost`.

---

## Types / interfaces (existing — do not extend)

From `frontend/src/api/client.ts` (import only):

```ts
interface CelcatEtat {
  saisie_active: boolean;
  semaines_validees: number[];
  valide_le: string | null;
  dernier_job: Record<string, string> | null;
  compteurs: { created: number; modified: number; deleted: number; blocked: number };
  worker_ok: boolean;
}

interface CelcatExtra {
  id: string;
  statut: string;
  course_code?: string;
  libelle?: string;
  module_nom?: string;
  event_id?: number;
}

interface CelcatLog {
  kind: string;
  motif?: string | null;
  session_id?: string | null;
}
```

Local UI state (same as today, names may stay):

- `etat: CelcatEtat | null`
- `extras: CelcatExtra[]` — open extras only
- `logs: CelcatLog[]`
- `semaines: number[]` — **draft** night-lot selection (initialized from `etat.semaines_validees`)
- `erreur: string | null`
- `enCours: boolean`

Do not add client types. `dernier_job` / `compteurs` may remain unused.

Week range stays `1..30`. Accessible name of every week control is `Semaine N` (never `S. N`).

Draft vs persisted:

- idle: not in `semaines`, not in `etat.semaines_validees`
- cochee: in `semaines`, not in `etat.semaines_validees`
- validee: in both
- retiree: in `etat.semaines_validees`, not in `semaines`

Multi-select: toggling N adds/removes N from `semaines` and sorts ascending. POST body is the full draft array.

---

## APIs / routes (no new endpoints)

Load (once on mount, same `Promise.all`):

1. `fetchCelcatEtat()` → `GET /celcat/etat`
2. `fetchCelcatExtras("ouvert")` → `GET /celcat/extras?statut=ouvert`
3. `fetchCelcatLogs(50)` → `GET /celcat/logs?limit=50`

Mutations (same signatures):

4. `patchCelcatSaisie(active)` → `PATCH /celcat/saisie` `{ active }` — switch only
5. `validerSemainesCelcat(semaines)` → `POST /celcat/valider` `{ semaines }` — night lot persist, not Live push
6. `ajouterExtraCelcat(id)` → `POST /celcat/extras/:id/ajouter`
7. `ignorerExtraCelcat(id)` → `POST /celcat/extras/:id/ignorer`

Forbidden: extra GETs, polling, new query params, calling the cliqueur, enqueueing Live from this tab, rollback UI.

After extras mutate: drop that extra from local list on success (today’s behaviour). Do not refetch unless the existing three-call `charger` is reused on error recovery. Switch and night-lot replace `etat` with the mutation return value.

---

## Layout / copy (locked UX)

### Hero (first panel)

Must show, in this panel (not a later muted line):

- `ÉCRITURE OFF` when `etat.saisie_active === false`
- `ÉCRITURE ON` when `etat.saisie_active === true`
- Consequence when ON: `Chaque modification du planning s’écrit tout de suite dans Celcat.`
- Consequence when OFF: `Les modifications du planning ne s’écrivent pas tout de suite dans Celcat.`
- Worker: `Worker joignable.` (`pill good`) or `Worker injoignable.` (`pill bad`)
- Last validation: if `valide_le` then `Dernière validation : {valide_le}.` else `Aucune validation.`

Switch:

- `role="switch"` (not an anonymous `<input type="checkbox">`)
- `aria-checked` mirrors `etat.saisie_active`
- Accessible name includes `écriture` (e.g. `Écriture Celcat`)
- `disabled` while `enCours`
- Default remains OFF: tests stub `saisie_active: false`; UI does not force ON
- `onClick` / toggle calls `patchCelcatSaisie(!etat.saisie_active)`

### Three numbered steps (visible 1 / 2 / 3)

1. **Armer l’écriture** — contains the switch (switch may live in the hero; step 1 must still be numbered and explain arming). If the switch stays in the hero, step 1 copy still says to arm writes here / points at the interrupteur. Preferred: switch in hero **and** step 1 is that same hero (hero = étape 1). **Lock: hero panel is étape 1** (`celcat-etape-num` = 1).
2. **Semaines du lot de nuit** — explains that the CTA records the **night** lot, not an immediate Live push. Chip grid + CTA.
3. **Extras** — open extras only: Ajouter au planning / Ignorer.

Journal is a **fourth** panel, not step 4, titled `Journal`. No Ajouter/Ignorer there.

### Night-lot CTA

Accessible name (and visible label) **must include** `lot de nuit`. Locked string:

`Enregistrer le lot de nuit`

Must **not** be only `Valider`. `.btn.btn--accent`, `disabled={enCours}`, calls `validerSemainesCelcat(semaines)`.

### Extras

- Label: `course_code || libelle || module_nom || id`
- Empty: `Aucun extra ouvert.` (`.muted` allowed)
- Each open extra: `Ajouter` (`aria-label={`Ajouter ${label}`}`) and `Ignorer` (`aria-label={`Ignorer ${label}`}`)
- Actions must not appear in the journal

### Journal

- Empty: `Aucune entrée.` (`.muted` allowed)
- Each item: French kind + motif
  - `created` → visible `créé` (or `Créé`)
  - `blocked` → visible `bloqué` (or `Bloqué`)
  - other `kind` values: still rendered, not dropped
- Motif: ` — {motif}` when present (e.g. `WR314D sans code Celcat`)

### Loading / error

- No etat yet, no error: `.panel` + `Chargement…` (`.muted`)
- Error and no etat: `.alerte` `role="alert"` only
- Error after etat loaded: alert panel above, rest of UI remains

---

## files

- `frontend/src/views/AdminCelcatView.test.tsx` — **edit** — TDD first: replace the old « Valider » / anonymous checkbox spec with the acceptance below
- `frontend/src/views/AdminCelcatView.tsx` — **edit** — markup, roles, copy, chip states; same fetches
- `frontend/src/styles/app.css` — **edit** — append `/* Celcat (AdminCelcatView) */` block (`celcat-*` only; do not change `.sidenav`, `.btn` defaults, or `.admin-users-*`)

Create: nothing.
Do not edit: `client.ts`, `App.tsx`, `SideNav.tsx`, `AdminUsersView.tsx`, backend.

---

## acceptance

Session acceptance, as testable behaviors (TDD spec):

- should show `ÉCRITURE OFF` and the OFF consequence and worker and last validation in the hero when `saisie_active` is false and `worker_ok` is true and `valide_le` is set
- should show `ÉCRITURE ON` and the Live consequence (`s’écrit tout de suite` / `ecrit tout de suite`) in the hero when `saisie_active` is true
- should expose the writing control as `role="switch"` with `aria-checked="false"` by default given the stub etat (`saisie_active: false`); must not be an unlabelled checkbox
- should not change the default off: first paint with stub etat must not call `PATCH /celcat/saisie`
- should call `PATCH /celcat/saisie` with `{ active: true }` when the switch is turned on
- should show numbered steps `1`, `2`, and `3` in the document
- should explain the night lot in step 2 (copy includes `lot de nuit` or equivalent night wording)
- should render a night-lot submit whose accessible name matches `/lot de nuit/i` and must not expose a button named only `/^valider$/i`
- should label weeks `Semaine 1` … `Semaine N` (query `getByRole` / `getByLabelText(/semaine 1/i)` still works for 1 and 2)
- should keep multi-select: toggling semaine 2 adds it; toggling again removes it; both can be selected together with semaine 1
- should distinguish validated vs checked: semaine 1 starts in `semaines_validees` and exposes a validated state (`celcat-semaine--validee` or accessible description / text `validée`); a newly toggled week that is not in `semaines_validees` exposes checked-not-validated (`celcat-semaine--cochee` without `--validee`)
- should POST `/celcat/valider` with the current draft `semaines` when the night-lot button is pressed
- should show Ajouter and Ignorer for an open extra (`WR106`) and call the matching `/celcat/extras/:id/ajouter` or `/ignorer` POST
- should show `Aucun extra ouvert.` and no Ajouter/Ignorer when extras list is empty
- should render journal in a separate panel from extras, with kinds lisibles (`créé` / `bloqué`) and motif (`WR314D` + `sans code Celcat`)
- should not issue any fetch beyond etat, extras (`statut=ouvert`), logs (`limit=50`), saisie PATCH, valider POST, extra ajouter/ignorer POST (assert mock `fetch` URLs)
- should keep the same load trio on mount: `/celcat/etat`, `/celcat/extras`, `/celcat/logs`

---

## order: tdd → build → e2e

1. **tdd** — rewrite `AdminCelcatView.test.tsx` from acceptance only; confirm red.
2. **build** — implement `AdminCelcatView.tsx` + `app.css` until those tests pass; do not rewrite tests to fit code.
3. **e2e** — blind browser on Administration → Celcat, **320px first**, then 768 / 1024 / 1440: hero OFF/ON copy, switch, three steps, week chips (validated vs selected), night-lot button, extras empty + one extra, journal kinds. No source.
4. **a11y** — switch name + `aria-checked`; week chips keyboard + names; contrast of `--cochee` / `--validee` / `--retiree`; 44px targets at 320px.

Design duel (Impeccable + Taste, pick) may refine spacing/color **within** these class names and chrome. It must not add endpoints, rename the CTA away from `lot de nuit`, or turn the switch back into an anonymous checkbox.

---

## Auth / tenancy / failure / mobile

**Auth:** Tab already admin-only (`App.tsx` + backend `require_role("admin")`). View assumes an authenticated admin cookie; no extra client auth check.

**Tenancy:** Single IUT instance. No org id.

**Failure modes:**

- Network fail on load, no etat → alert, no switch, no writes.
- Mutation fail → previous `etat` / extras stay; `erreur` in `.alerte`; switch/CTA re-enabled after `enCours` clears.
- `worker_ok: false` → hero shows injoignable; switch stays enabled (worker health is status, not a lock).
- Empty extras / logs → dedicated empty copy, not a spinner.

**Mobile-first (320px):**

- Hero stacks: statut, consequence, switch (min 44px), meta. No horizontal page overflow.
- Week chips wrap; each chip min 44×44px; labels stay `Semaine N` (may wrap, must not truncate to `S. N`).
- Extra row: label then buttons wrapping; both actions reachable without horizontal scroll.
- Step numbers remain visible (not icon-only).

---

## risks

**Dangerous Live switch.** `PATCH /celcat/saisie { active: true }` arms immediate Celcat writes on every planning edit (teacher pay). A prettier switch is easier to flick than the old checkbox. Mitigations locked: default OFF unchanged; `role="switch"` + `ÉCRITURE ON/OFF` + consequence sentence in the hero (not muted); disable while `enCours`. Session did **not** lock a confirm modal — do not add one in this pass. Residual: a misclick still arms Live.

**Week-chip a11y.** Thirty lookalike checkboxes were the problem; chips that are color-only (selected vs validated) fail WCAG 1.4.1 and leave AT users unable to tell “already in the night lot” from “just checked”. Mitigations locked: accessible name `Semaine N`; `aria-pressed` or `aria-checked` for the draft; a non-color cue for validated (`validée` in accessible name/description or a `.pill`); keyboard Space/Enter; 44px targets. Residual: a 30-control grid is still long to tab through at 320px — no “select all” in scope.

Other: rewriting tests will drop `/valider/i` as the sole CTA matcher — TDD must use `/lot de nuit/i` or the old green suite will fight the copy lock.

---

## done_when

- TDD file encodes the acceptance list and is green against the view.
- Hero shows OFF or ON + Live consequence + worker + last validation, none of those in `.muted`.
- Switch is `role="switch"`, default OFF, still `patchCelcatSaisie`.
- Steps 1/2/3 visible; step 2 + CTA say night lot; CTA is not just « Valider ».
- Weeks: `Semaine N`, validated vs checked, multi-select kept.
- Open extra: Ajouter + Ignorer; empty extras: `Aucun extra ouvert.`
- Journal separate, créé/bloqué + motif.
- Fetch mock shows only the seven existing calls.
- E2E at 320px passes the same story.
- SideNav, AdminUsersView, and global `.btn` / `.panel` look unchanged.
