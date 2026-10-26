# Durable memory and scheduled work

Enable these capabilities per agent. The same domain logic runs with SQLite or
PostgreSQL and with embedded Rust or managed subprocess SDKs. They are off by
default and use the ordinary tool approval policy.

```typescript
const coder = harness.createAgent({
  name: "coder",
  instructions: "Build and test the learner's project.",
  defaultModel: { provider: "OpenAI", name: modelId },
  tools: ["coding.read_file", "coding.apply_patch", "coding.search_files",
          "coding.run_shell", "coding.git_diff", "coding.web_fetch"],
  memoryScope: learnerWorkspaceId, // Trusted application ID, not model input.
  scheduling: true,
  autoSkipQuestions: true,
  approvals: { mode: "never" }, // Bypass for this isolated learner container.
});
const session = await coder.newSession({ workspace: "/workspace" });
const run = await session.send("Build a quiz and remember my chosen theme.");
for await (const event of run.events()) { /* render progress */ }
const state = await session.state();
// state.timers: [{ id, nextRunAt, remainingRuns }]; times are UTC Unix seconds.
```

```rust,ignore
let coder = harness.create_agent(
    Agent::new("coder")
        .instructions("Build and test the learner's project.")
        .default_model(Model::new("OpenAI", model_id))
        .tools(["coding.read_file", "coding.apply_patch", "coding.search_files",
                "coding.run_shell", "coding.git_diff", "coding.web_fetch"])
        .memory_scope(learner_workspace_id)
        .scheduling(true)
        .auto_skip_questions(true)
        .approvals(Approvals::Never)
).await?;
let session = coder.new_session_in("/workspace").await?;
```

For private memory use `memory: true` / `.memory(true)` without a scope. The harness
assigns that memory to the session. An explicit `memoryScope` / `.memory_scope()`
enables sharing between agents/sessions with exactly the same application-supplied
scope. An evaluator can share the coder's scope, or remain independent. Scope IDs
are 1–128 ASCII letters, digits or `-_:./`. Models cannot change the scope through
tool arguments. Never forward an unvalidated client-supplied tenant/scope ID.

## Memory tools

| Tool | Purpose |
|---|---|
| `memory_remember` | Save a summary and fact/preference; returns ID and revision. |
| `memory_read` | Read a complete entry by ID. |
| `memory_search` | Case-insensitive literal search; empty query lists recent entries. |
| `memory_update` | Replace an entry using its `expected_revision`. |
| `memory_forget` | Delete an entry using its `expected_revision`. |

Limits: 128 entries per scope, 240-byte summaries, 2,000-byte contents, 400 KB
serialized scope size. Search returns at most 20 metadata/excerpt results; use
`memory_read` for full content. Revision checks reject stale writes. A memory
mutation and its tool result/history/event commit in one database transaction.
PostgreSQL locks the scope row to serialize writers across sessions.

This is explicit agent memory, separate from session history, compaction, skills
and credentials. It does not automatically ingest the workspace, embed content
or provide semantic/vector retrieval. Saved facts and fetched web pages are data,
not instructions or human authorization. Tools instruct the model not to save
secrets; memory is **not** a secret vault or an automatic sensitive-data filter.
Forgetting an entry does not erase copies already in execution history. The host
application owns tenant access and retention of the underlying state/history.

## Scheduling tools

| Tool | Purpose |
|---|---|
| `current_time` | Current UTC Unix timestamp in seconds. |
| `schedule_create` | Create work with `prompt`, `run_at`, optional `interval_seconds` and `max_runs`. |
| `schedule_list` | Inspect active, cancelled and completed definitions. |
| `schedule_update` | Change active prompt/next due time at `expected_revision`. |
| `schedule_cancel` | Cancel future occurrences at `expected_revision`. |
| `schedule_delete` | Remove the definition at `expected_revision`; retain execution history. |

Schedules belong to a session. A first due time must be within the next 30 days;
recurrence intervals are 60–86,400 seconds with 1–100 total runs. At most 64
definitions/64 KB per session. Delete completed definitions when capacity is needed.
This is bounded one-shot/interval scheduling, not cron, timezone calendars,
sleep-until tools or event subscriptions.

The **SDK host** dispatches due work while running, for both SQLite and PostgreSQL.
Pending definitions survive shutdown/restart. Busy sessions, pending interactions
and blocked providers delay delivery. Missed recurring intervals coalesce into one
occurrence; the next due time is measured from acceptance. Admission records the
occurrence and starts its turn atomically. Duplicate submission IDs do not double
count it. Closing the session cancels future work; cancelling an active turn or a
schedule does not undo work already admitted.

A scheduled message is tagged as agent-authored context and excluded from direct
human-intent evidence for the auto-approver. Scheduling grants no future tool
permissions. An accepted run interrupted by a crash follows the existing recovery
and unknown-outcome rules; the harness does not promise exactly-once external
effects or silently rerun uncertain actions.

`session.state()` exposes timers for that session (a team lead does not aggregate
member timers). Notifications/events and history remain available through existing
SDK APIs. The standalone multi-node server reference does not yet run this timer
dispatcher; these APIs do not claim distributed scheduling service support.

## Storage and compatibility

Use matching SDK/host versions. The host advertises `memory_tools` and
`scheduled_tasks`; old hosts reject the new agent fields. SQLite installs versioned
extension tables when opened. PostgreSQL uses the existing explicit storage
migration command/API before startup. Unknown extension versions are rejected.
Custom `StateStore` implementations need to implement the atomic `assistant_call`
operation; its default fails explicitly. Memory and schedules do not use workspace
files, so a tool workspace is not the source of their durable state.

## Verification (2026-10-26)

- SQLite and PostgreSQL share the same memory/schedule contract tests: scope
  isolation, revision conflicts, restart persistence and duplicate delivery.
- Fault injection verifies that memory/results and schedule admission roll back
  together. PostgreSQL checks concurrent writers and ownership fencing.
- Rust SDK acceptance tests cover embedded/managed modes with both databases,
  including scheduled work after restart and no duplicate execution.
- TypeScript real-host tests passed on macOS and Linux for shared/private scopes,
  approval denial and scheduled delivery after restart. Linux also passed the
  coding/process, question-policy and forced-child-restart acceptance test.
- Search/patch/Git tests cover ignore rules, malformed/escaping/stale edits,
  CRLF, and repository helpers that must not run. Web tests reject local/private
  destinations; an actual MCP fetch of public `https://example.com` returned 200
  and extracted text.

Tests use scripted models with real tools/storage/processes. This batch does not
claim live-model quality, Windows VM or OpenShell-cluster qualification. One
existing Linux supervisor ownership test failed once during process cleanup and
passed on subsequent full runs; no supervisor behavior was changed here.
