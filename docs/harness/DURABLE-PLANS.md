# Durable session plans

An opted-in native coworker can maintain a bounded checklist while it works.
Applications read the current plan from a session snapshot and receive updates
through the existing event stream. This is progress reporting, not a workflow
scheduler or independent proof that the work succeeded.

## Enable planning

Add `planning: true` to the coworker's `manifest.md` frontmatter. The harness then
exposes its internal `update_plan` tool. Omission defaults to false and keeps the
existing tool catalog unchanged. Applications cannot enable an unselected
capability through session creation. The package remains pinned to the session.

See `harness/examples/planner` for a complete coworker bundle. Planning itself is
platform-independent; its workspace tools follow the selected execution backend.
No desktop UI or existing example application has been changed to render plans.

## Tool input

```json
{
  "expected_revision": 0,
  "explanation": "Investigate before changing the implementation",
  "steps": [
    {"id": "inspect", "description": "Read the relevant code", "status": "in_progress"},
    {"id": "verify", "description": "Run the focused tests", "status": "pending"}
  ]
}
```

The complete list replaces the previous one. Use stable step IDs when revising.
Statuses are `pending`, `in_progress`, and `completed`; at most one step can be
in progress. There are at most 32 steps, each with a unique ASCII identifier of
1–64 bytes and a nonblank description of at most 240 UTF-8 bytes. Explanation is
at most 500 UTF-8 bytes. Text cannot contain control characters. `steps: []`
explicitly clears the plan while advancing its revision.

The initial revision is zero. Every accepted replacement increments it and
records the originating `turn_id` and `call_id`. Stale revisions and semantically
invalid lists return `isError: true` with no plan change. Malformed tool-schema
arguments follow the existing runtime validation/failure behavior. A later turn
can revise the same session plan; a new session starts independently.

## Application integration

Initialization advertises `capabilities.durable_plans: true` as runtime support.
Coworker metadata identifies whether planning is enabled for that coworker.
For enabled sessions, snapshots include top-level `plan`, initially `null`:

```json
{
  "plan": {
    "revision": 1,
    "turn_id": "t_example",
    "call_id": "call_example",
    "explanation": "Investigate before changing the implementation",
    "steps": [
      {"id": "inspect", "description": "Read the relevant code", "status": "in_progress"},
      {"id": "verify", "description": "Run the focused tests", "status": "pending"}
    ]
  }
}
```

`plan_updated` is the successful operation's terminal event. Its data includes
`name: "update_plan"`, `call_id`, the full `plan`, `result`, and
`enforcement: "session-metadata-only"`. It has no preceding approval or
`tool_started` event because it performs no external action. Semantic rejection
instead emits `tool_finished` with an error result; there is no `plan_updated`.

Use the same snapshot/cursor protocol as other progress:

- Direct stdio or Rust SDK: attach to the session, consume notifications, and
  replay `event/read` from the last processed cursor on a gap. SDK clients use
  `snapshot`, `attach`, and `subscribe`; there is no second planning transport.
- Server: authorized `GET /sessions/:sid` and its existing events SSE/replay
  endpoint expose the same plan. Plans inherit session read authorization.
- Apply a snapshot at its cursor and only later events. Track plan revision to
  avoid older/replayed events replacing newer state. Render descriptions as text,
  never executable HTML. Model-authored content is untrusted.

There is no public plan-edit endpoint in this checkpoint. The application can ask
for revisions through an ordinary user message. No client or model-supplied
session ID is accepted by the planning tool itself.

## Durability and safety

Plan metadata, the model tool result, queue removal and the event commit in one
SQLite/PostgreSQL transaction. A failed commit emits nothing. PostgreSQL uses its
existing revision/owner fencing; a failed connection must be replaced and durable
state reconciled, not blindly retried. Restart and compaction preserve the plan;
the current bounded plan is refreshed in model context as agent-authored data.

Planning requires no human approval because it only changes this session's
bounded progress metadata. It grants no file, network, tool or credential access,
creates no reusable approval, and is excluded from the auto-approver's evidence
of user intent. Real actions still pass through all existing policy checks.
The reserved tool name cannot be replaced by a partner/MCP binding.

Cancellation or a changed turn/queue prevents a late plan update. If an update
commits before cancellation, that committed progress remains visible. Completed
steps do not automatically complete a turn, and turn completion does not silently
complete its steps. UI wording should say the agent marked a step complete, not
that the harness independently verified it.

No database migration is needed for this additive optional metadata. Existing
version-pinned worker rollout rules still apply; do not move a planning session
to an older worker that does not implement the capability.

## Python relationship

Reviewed public main `7e20213dc88faaaaccace59461876c76e76b134a` on 2026-10-12.
`coworker/tools/todo.py` is unchanged from this worktree's Python reference. Both
implement a replace-all advisory list without approval. Intentional Rust
differences: durable state/events, stable step IDs and revisions, explicit bounds,
strict statuses instead of Python's permissive normalization, `completed` instead
of `done`, and an opt-in native manifest field. Neither implementation schedules
work by updating the list. The native tool uses `steps`, avoiding Python's known
provider-template conflict with a top-level argument called `items`.

See the [release checklist](RELEASE-CHECKLIST.md) for this source snapshot's
qualification boundaries.
