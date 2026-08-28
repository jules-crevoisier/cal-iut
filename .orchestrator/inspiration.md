# Inspiration — read-only personal teacher schedule page

siteType: dashboard (closest fit in the registry's taxonomy — no dedicated "personal-itinerary/ticket" type exists; this page is clean utility data-display, mode=read, surface=schedule, not persuade/operate)
dbCount: 19 (harvest DB, type=dashboard) — under the 50 target, so Awwwards was harvested this session per the < 50 rule; will keep growing across future sessions.

Note on the niche: Awwwards has no strong direct category for "personal schedule / boarding-pass-style data delivery." Text searches for `calendar`, `itinerary`, `ticket`, `boarding pass` mostly surfaced dead/decade-old promo microsites (advent calendars, WordPress themes) or off-topic "board"/"pass" homophone noise — none usable as live structural references. Closest real signal came from the `ui-design`, `app-style`, and `mobile-apps` Awwwards listings: clean single-purpose utility apps (budgeting, subscription tracking, prompt tools) that share this page's core problem — show one person their own structured data plainly, with no marketing chrome around it.

## vault
(none) — project `.orchestrator/vault.md` does not exist yet, personal `vault/mine.md` is empty. No pinned references to defer to.

## harvest
Harvested 19 live URLs into the DB this session (type=dashboard) from Awwwards listings `ui-design/`, `app-style/`, `mobile-apps/`, plus a `?text=ticket` search hit. Visited 3 live (one swapped after a dead-domain hit):

- **Grassfeld** — https://www.grassfeld.com (AI budgeting app; source: awwwards/mobile-apps)
  Best structural analog of the three. Layered information density: a top-line summary (balance/remaining) that expands into transaction-list detail, exactly the shape of "week grid → semester agenda list." Ring/progress visualizations for at-a-glance status, colored category badges on list rows, generous whitespace between summary and detail blocks, soft-blue/neutral palette with warm accent colors (orange/yellow/coral) used only for category coding, not brand decoration. Steal: the "summary card sits above a scannable list, both reading the same data at two zoom levels" pattern — maps directly onto the constraint-compliance callout sitting above the SemesterAgenda list.

- **mise** — https://mise.software/ (cinematic sequential-task micro-site; source: awwwards/mobile-apps)
  Opposite end of the density spectrum: sparse, lowercase, narrative copy, a vertical step-list instead of a grid, huge negative space. Steal: permission to let a personal utility page feel authored rather than dashboard-generic — sparse typography and directional flow as an antidote to "admin panel with panels hidden." Avoid: its extreme minimalism (single-step-at-a-time reveal) doesn't fit a page whose job is scanning a whole week/semester at once — this is a mood reference for restraint and tone, not a structural template for the grid.

- **SiteAssist** — https://www.siteassist.com (B2B safety/compliance SaaS; source: awwwards/ui-design)
  Confirmed as a marketing-page structure (hero → features → industries → CTA), explicitly *not* a data-display pattern — flagged by the fetch itself as "not ideal for data-heavy displays." Kept as a negative reference: numbered process sequences (01-04) and icon-led section framing are useful for a possible "how to read your schedule" onboarding strip, but its card/testimonial/CTA scaffolding should not leak into the actual schedule surface.

(Pass App, https://pass.app/, from the `?text=ticket` search — thematically the closest hit, "pass/ticket for one person" — but the domain failed DNS resolution when visited live; dropped as a working reference this session, left in the DB in case it resolves later.)

## catalog
Checked `catalog.json` (Stripe, Linear, Vercel, Raycast, Resend, Clerk, …) — all persuade/operate-mode SaaS marketing or product-nav references, none in `read` mode for a single-person data-delivery surface. Not cited as a direct structural match; useful only at the level of "calm type hierarchy, restraint" already covered by mise/Grassfeld above.

## Synthesis for the design duel
This page is closer to "your itinerary/boarding pass" than to an admin dashboard: one person, their own data, no login chrome, scan-then-drill-down. Carry into both design tracks:
1. Two-tier density (Grassfeld): a compact status/summary layer sitting above the full scrollable/browsable detail (week grid above semester agenda), not all panels competing at once.
2. Editorial restraint (mise): permission to depart from admin-dashboard visual language — sparse type, real whitespace, a page that reads as *for this teacher* rather than a stripped admin screen with `{!readOnly && ...}` gaps.
3. Explicit anti-pattern (SiteAssist): do not let marketing-site scaffolding (feature cards, testimonial rhythm, repeated CTAs) bleed into what is fundamentally a data-lookup tool.
