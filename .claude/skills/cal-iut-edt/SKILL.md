---
name: cal-iut-edt
description: >-
  Edits the IUT MMI timetable via the cal-iut MCP tools inspect, plan, and
  apply (place, move, swap, unplace, salle, seance, custom_create/patch/delete).
  Use when placing or moving seances, changing a room, patching a seance,
  reading the MCP journal, mapping weekIndex to Semaine N, or working on
  cal-iut-mmi.srko.fr/mcp / emploi du temps / planning.
---

# cal-iut EDT (MCP)

The live timetable and **all constraints** (teachers, rooms, PAC/SAE, week locks)
already live on the server. Read them with `inspect`. Validate a change with
`plan`. Write only after a human **confirm** in chat, with `apply`.

Call MCP tools `inspect` / `plan` / `apply` (aliases `inspect_edt` / `plan_edt` /
`apply_edt`). Do not curl `/mcp`. Do not read `.env`, `CAL_IUT_MCP_TOKEN`, or
account cookies. Do not invent a Bearer header. Do not edit SQLite or YAML.

## Always

1. `inspect` with `teacher_code` or `course_code`. No filter → compact `index`
   only (`course_codes`, `teacher_codes`, `n_weeks`) — **not** the EDT.
2. `plan` with explicit `ops`. Show each item: `ok` / `blocked` / `forceable`.
3. Wait for a human **confirm**, then `apply` with `confirm=true`,
   `ops=<plan.items>` (the evaluated list), and `plan_id`.

Do not invent teachers, rooms, or week numbers. Do not write YAML under
`data/config`. Do not call regen / solve / ingest / mail.

`read_only` keys: `inspect` only. `plan` / `apply` return an error — stop and
say the account cannot write.

## What inspect gives you

Filtered inspect returns:

- `sessions` — placed and unplaced seances (ids, teachers, groups, slot)
- `catalog.teachers` / `rooms` / `groups` / `weeks` / `slots` / `days`
- `catalog.unplaced`
- `catalog.constraints.teacher_availability` for teachers in scope
- `journal` — previous MCP applies

Room reservations, PAC/SAE, pedagogical order, and clashes are **enforced in
`plan`**, even when they are not listed as a catalog dump. If `plan` says
`blocked`, trust it and pick another slot.

## Slots and weeks

- Days: 0=Lundi … 4=Vendredi.
- Slots: 0=8h–9h30, 1=9h30–11h, 2=11h–12h30, 3=14h–15h30, 4=15h30–17h,
  5=17h–18h30. No 12h30–14h.
- `week` is the 0-based solver index `catalog.weeks[].index`.
  User “Semaine N” is the department number inside `label`
  (e.g. index `1` → `Semaine 3 (…)`). Resolve N via that list; **never** pass
  N as `week`. Unfiltered inspect has no `weeks` — filter first.
- Ignore `Semaine {n}` in error text; that is `week+1`, not the label.

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

`plan` with `duration_slots`/`slot` and no `ops` still emits `reshape` (legacy).
Prefer `seance` or `move`.

## Hard vs forceable vs blocking

- **blocking_conflicts** (PAC / SAE / institutional / declared teacher indispo):
  `status=blocked`. Never force. Apply refuses the whole batch.
- **forceable** (resource clash, week lock, pedagogical order): plan stays `ok`
  with `forceable=true`. Apply with `force=true` on that item only after the
  human confirmed the warning.
- Soft prefs = `warnings` only.

`plan_id` hashes the exact `ops` payload. After `plan`, do not strip `status` /
`forceable` / `blocking_conflicts`. To force: copy the plan item, set
`force=true` on that item only, `apply` with `confirm=true` and **omit
`plan_id`** (or re-`plan` with `force` already on the op). Never set `force` on
`status=blocked`. Check `apply`’s `ok`; silent `{ok: false}` means confirm /
empty ops / blocked item / `plan_id` mismatch.

## Example

User: “Place the unplaced TP of WRA507C.”

1. `inspect` `{ "course_code": "WRA507C" }`
2. Read `catalog.unplaced`, `catalog.weeks`, sessions, constraints.
3. Propose a slot in chat (week index + day + slot + why).
4. `plan` `{ "ops": [{ "op": "place", "session_id": "…", "week": 4, "day": 1, "slot": 3 }] }`
5. If `blocked`: explain the conflict, try another slot. If `forceable`: ask.
6. After “oui” / “applique”: `apply` `{ "confirm": true, "plan_id": "…", "ops": <plan.items> }`.
7. Report `ok`.

More worked ops: [examples.md](examples.md).

## Journal

Read history from inspect’s `journal` key. Do not open
`data/state/mcp_journal.json`. Placements live in SQLite + overlays; the next
regen already sees them. Do not invent a solver constraint type.
