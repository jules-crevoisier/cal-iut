# Session
goal: MCP has the same live catalog a Promo admin sees, plus a repo skill; Claude can place/move/swap/unplace/room/patch seance/custom exactly like the UI, after a visible plan.
out_of_scope: WhatsApp inbox; inventing a replacement teacher; personal-link chrome; design duel; solver/regen/ingest/mails as MCP tools; writing YAML under data/config; silent force of PAC/SAE/declared indispo.
users: admin (Kyllian) on desktop + Claude.ai / Cursor on https://cal-iut-mmi.srko.fr/mcp
branch: feature/mcp-edt-agent
design_pick: da_now (MCP + skill, no new visual world)
inspiration: skip
locked:
- Context live via MCP (not only a local skill): inspect returns sessions AND catalog slices (teachers, rooms, groups, weeks, unplaced, constraints/availability relevant to the filter). Same source as /app-state, never raw YAML dumps of secrets (celcat passwords, mail keys).
- Context durable via a repo skill (`.cursor/skills/cal-iut-edt/SKILL.md`): IUT MMI slots, weekIndex vs label, hard vs forceable vs blocking, how to call inspect/plan/apply, how to read the MCP journal. Claude.ai still works from MCP tools alone.
- Tools stay inspect / plan / apply. Plan is dry-run with ok | blocked | soft warning. Apply only if confirm=true, ops non-empty, plan_id matches if given, no blocked items.
- Apply ops = human Promo actions: place, move (week/day/slot), swap, unplace, salle, patch seance (teachers, type, duration 1|2, week/day/slot, room, is_eval on CM), custom create/patch/delete. Same conflict stack as REST. Never invent teachers.
- Force: only when the plan item already showed a forceable conflict and the human confirmed apply. Never force blocking_conflicts (PAC/SAE/institutional/declared indispo). Soft prefs = warnings in the plan.
- Journal: each successful apply appends data/state/mcp_journal.json (gitignored). inspect can return it. Persistence of the EDT itself is the same SQLite + overlays + custom_sessions as the UI so the next regen/week/solve generation sees the new placements — no separate solver constraint type.
open:
- none
acceptance:
- inspect without filter is too big to be the default; with teacher_code or course_code returns sessions + matching catalog (labels, rooms usable, unplaced for that course/teacher).
- inspect of WRA507C lists those sessions with week/day/slot/room/teachers; catalog includes week labels and rooms.
- plan+apply can place, move across weeks, swap, unplace, change room, patch teachers/type/duration/eval, create a custom session — 409 structured if blocked; force only on confirm after a forceable warning.
- apply writes mcp_journal.json; a second inspect shows that entry; timetable/overlays match the UI APIs.
- Unauthenticated / wrong token cannot mutate. No MCP token → 503.
- Skill file exists in the repo and names the tools, journal, and hard vs forceable rules. No new Promo UI.
