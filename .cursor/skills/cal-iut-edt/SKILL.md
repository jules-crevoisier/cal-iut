---
name: cal-iut-edt
description: >-
  Edits the IUT MMI EDT via cal-iut MCP inspect, plan, and apply
  (place, move, swap, unplace, salle, seance, custom_create/patch/delete).
  Use when placing, moving, depositing, swapping, or forcing seances,
  changing salle, patching a seance, reading mcp_journal, mapping
  weekIndex to Semaine N, or working on cal-iut-mmi.srko.fr/mcp /
  emploi du temps / planning.
---

# cal-iut EDT (MCP)

Call MCP tools `inspect` / `plan` / `apply` (aliases `inspect_edt` / `plan_edt` / `apply_edt`). Do not curl `/mcp`, do not read `CAL_IUT_MCP_TOKEN`, do not edit SQLite or YAML.

## Always

1. `inspect` with `teacher_code` or `course_code`. No filter returns a compact index (`course_codes`, `teacher_codes`, `n_weeks`) — not the whole EDT.
2. `plan` with explicit `ops`. Show each item: `ok` / `blocked` / `forceable`.
3. Wait for a human **confirm** in chat, then `apply` with `confirm=true`, `ops=<plan.items>` (the evaluated list), and `plan_id`.

Do not invent teachers. Do not write YAML under `data/config`. Do not call regen/solve/ingest/mail.

## Slots and weeks

- Days: 0=Lundi … 4=Vendredi.
- Slots: 0=8h–9h30, 1=9h30–11h, 2=11h–12h30, 3=14h–15h30, 4=15h30–17h, 5=17h–18h30. No 12h30–14h.
- `week` is the 0-based solver `catalog.weeks[].index`. User “Semaine N” is the department number in `label` (e.g. index `1` → `Semaine 3 (…)`). Resolve N via that list; never pass N as `week`. Unfiltered `inspect` has no `weeks` — filter first. Ignore `Semaine {n}` in error text; that is `week+1`, not the label.

## Ops (same stack as Vue Promo)

| op | fields |
|---|---|
| `place` | `session_id`, `week`, `day`, `slot`, `room_id`? |
| `move` | `session_id`, `week`, `day`, `slot`, `room_id`? |
| `swap` | `session_id`, `session_b` |
| `unplace` | `session_id` |
| `salle` | `session_id`, `room_id` |
| `seance` | `session_id` + optional `teacher_codes`, `session_type`, `duration_slots` (1\|2), `week`, `day`, `slot`, `room_id`, `is_eval` (CM only) |
| `custom_create` | `course_code`, `session_type`, `group_ids`, `teacher_codes`, `week`, `day`, `slot`, `duration_slots`?, `room_id`?, `is_eval`? |
| `custom_patch` | `session_id` + same optional keys as `seance` plus `group_ids` |
| `custom_delete` | `session_id` |

`plan` with `duration_slots`/`slot` and no `ops` still emits `reshape` (legacy). Prefer `seance` or `move`.

## Hard vs forceable vs blocking

- **blocking_conflicts** (PAC / SAE / institutional / declared teacher indispo): `status=blocked`. Never force. Apply refuses the whole batch.
- **forceable** (resource clash, week lock, pedagogical order): plan stays `ok` with `forceable=true`. Apply with `force=true` on that item only after the human confirmed the warning.
- Soft prefs = `warnings` only.

`plan_id` hashes the exact `ops` payload. After `plan`, do not strip `status` / `forceable` / `blocking_conflicts`. To force: copy the plan item, set `force=true` on that item only, `apply` with `confirm=true` and **omit `plan_id`** (or re-`plan` with `force` already on the op). Never set `force` on `status=blocked`. Check `apply`’s `ok`; silent `{ok: false}` means confirm / empty ops / blocked item / `plan_id` mismatch.

## Journal

Read history from inspect’s `journal` key. Do not open `data/state/mcp_journal.json` (server-side, gitignored). Placements live in SQLite + `session_overrides` + `custom_sessions`; the next regen already sees them. Do not invent a solver constraint type.
