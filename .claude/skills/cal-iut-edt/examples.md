# cal-iut MCP examples

Assume a prior filtered `inspect` (`course_code` or `teacher_code`). `week` is
always `catalog.weeks[].index`, never the department “Semaine N”.

## Place one unplaced seance

```json
{
  "ops": [
    {
      "op": "place",
      "session_id": "WRA507C-TP-B-03",
      "week": 4,
      "day": 1,
      "slot": 3,
      "room_id": "H.205"
    }
  ]
}
```

Show the plan. Wait for confirm. Then `apply` with `confirm=true`, that
`plan.items` list, and `plan_id`.

## Move after a clash

If `plan` is `blocked`, do not force. Inspect the teacher (or the room) and
pick another `week`/`day`/`slot`.

```json
{
  "ops": [
    {
      "op": "move",
      "session_id": "WRA507C-TP-B-03",
      "week": 5,
      "day": 2,
      "slot": 3
    }
  ]
}
```

## Swap two seances

```json
{
  "ops": [
    {
      "op": "swap",
      "session_id": "WRA507C-TP-B-03",
      "session_b": "WRA508C-TD-AB-01"
    }
  ]
}
```

## Change room only

```json
{
  "ops": [{ "op": "salle", "session_id": "WRA507C-TP-B-03", "room_id": "H.009" }]
}
```

## Forceable item (human already confirmed the warning)

Copy the **evaluated** plan item, set `force=true` on that item only, `apply`
with `confirm=true`, **omit `plan_id`**. Never if `status` is `blocked`.
