# Local process integration, protocol 0.1

ExampleApp owns a private stdin/stdout pipe. Start one runtime for an installed coworker
bundle. stdout is newline-delimited JSON-RPC 2.0 only; stderr is diagnostics.
Do not merge the streams or forward raw diagnostics/tool results to telemetry.

```sh
bin/openworker serve --stdio --state-dir /private/app-state/runtime \
  --bundle /trusted/kit/coworker --model gpt-6-sol --sandbox openshell
```

Use a stable absolute state path. A new runtime process can reattach to sessions
from that directory, but two simultaneous processes must not share it.

Model defaults, per-session overrides, and managed credentials are documented in
[model connections](MODEL-CONNECTIONS.md). Gate these on `model_connections`;
secure persistence currently supports Windows DPAPI only. Keys are control-plane
inputs and must never be journalled or made model-visible.

The provider extension supports OpenAI and Anthropic (`model_providers` in
initialize); the process fallback accepts `--provider openai|anthropic`.
The [SDK host](../../docs/harness/SDK-STORAGE.md) exposes `team/create`,
`team/snapshot`, `team/command` and `team/events` on private stdio with either
SQLite or PostgreSQL. Use the SDK host launcher rather than the legacy single-
coworker `serve` command for team provisioning and automatic delivery scheduling.
The [PostgreSQL REST/SSE team API](../../docs/harness/PROVIDERS-AND-TEAMS.md)
remains the distributed server integration. Member sessions retain their ordinary
tool/approval event protocol.

## Start and observe

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocol_version":"0.1"}}
{"jsonrpc":"2.0","id":2,"method":"coworker/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"session/create","params":{"name":"Daily task","coworker":"assistant-example","workspace":"/home/alice/projects/task","permissions":{"mode":"ask","auto_skip_questions":false}}}
{"jsonrpc":"2.0","id":4,"method":"session/attach","params":{"session_id":"SESSION_ID"}}
{"jsonrpc":"2.0","id":5,"method":"turn/start","params":{"session_id":"SESSION_ID","submission_id":"APP_STABLE_REQUEST_ID","text":"Prepare a summary in this workspace."}}
```

These are separate lines/requests; wait for responses and substitute returned IDs.
Create the workspace first. initialize advertises capabilities; gate UI features
on them rather than assuming a newer runtime is present.

session/attach returns the snapshot, pending interactions and journal cursor,
and subscribes this connection to session/event notifications. Notifications are
hints to update the UI, not proof of durable state or exactly-once delivery.
stream/gap means recover from the journal.

```json
{"jsonrpc":"2.0","id":6,"method":"event/read","params":{"session_id":"SESSION_ID","after":0}}
```

Page until has_more is false using each returned cursor; deduplicate event_id.
Do not jump a replay cursor forward merely because a later notification arrived.
Snapshots/history are bounded; use history/read for older transcript pages.
Keep displayed text deltas separate from approval state and confirmed tool results.

Planning-enabled runtime builds advertise `durable_plans: true`. Coworker
frontmatter `planning: true` exposes `update_plan`; opted-in session snapshots
include `plan`, and `plan_updated` events carry full bounded replacements. These
are advisory progress records, not execution approvals. See
[durable plans](../../docs/harness/DURABLE-PLANS.md) for schema and replay.

SDK-enabled builds advertise `native_tools_sdk: true` and tool manifest versions
`[1,2,3]`. Native and MCP calls use this same protocol. `tool_started` and
`tool_finished` include `call_id`; native `tool_progress` includes that call ID,
`qualified_name`, `message` and structured `data`. It is a durable, replayable
event, not proof that an external UI displayed it or that the user saw it. Native
results contain `structuredContent` plus a text representation; expected errors
use `isError: true` and an `error` object with `code`/`message`. Image/artifact
streaming is not implemented by this JSON-result contract.

## Durable approvals and questions

Pending interactions have their own IDs and exact call/package/policy identity.
Show the actual action and effects. Only the app/user supplies the answer:

```json
{"jsonrpc":"2.0","id":7,"method":"interaction/respond","params":{"session_id":"SESSION_ID","interaction_id":"INTERACTION_ID","decision":"once"}}
{"jsonrpc":"2.0","id":8,"method":"interaction/respond","params":{"session_id":"SESSION_ID","interaction_id":"QUESTION_ID","answer":"The user’s answer"}}
```

For refusal, decision is deny. For questions, respect their options/schema.
Never fabricate answers to resume execution. Ask, auto-approve and bypass are
independent of headless presentation. Unsure auto-review pauses for a human.
auto_skip_questions skips ordinary questions only; it cannot grant tool permission.
An in-scope consequential action with unsettled consent asks; an explicitly
forbidden or manipulated action is denied.

### Allow for this session

With `capabilities.session_tool_grants:true`, an approval can use `decision:"session"`.
This approves the current call and durably grants the **entire tool** for this
session, with different valid arguments. For `computer.use` it covers all sub-actions,
not only the action currently shown. Clearly explain that scope in the approval UI.

```json
{"jsonrpc":"2.0","id":9,"method":"interaction/respond","params":{"session_id":"SESSION_ID","interaction_id":"INTERACTION_ID","decision":"session"}}
{"jsonrpc":"2.0","id":10,"method":"permissions/list","params":{"session_id":"SESSION_ID"}}
{"jsonrpc":"2.0","id":11,"method":"permissions/revoke","params":{"session_id":"SESSION_ID","grant_id":"GRANT_ID"}}
```

List returns `grants` with `id`, model-facing `tool`, `server`, `remote_tool`
(fully qualified in v3), `scope:"whole_tool_session"`, `active`, and
`created_by_interaction`. Revoke returns `revoked` and `already_absent`. Both are
trusted-app methods, not model tools. Grants are not accepted in session/create.
The human decision, grant and resolution event commit together. Repeating a response
does not create another grant, including after revocation. Revoke by ID is idempotent
and affects only the named session. `session_grant_revoked` records the change.

After hard checks, matching grants skip Ask prompts and AutoApprove review. Bypass
remains independent. `tool_started` records `grant_id` and `approval_origin`; reuse
uses origin `session_grant`. Tools/catalog/routes, execution bundle/runner and both
policy digests are pinned. Changes fail closed under existing session binding rules;
the current harness may require a fresh session, not an automatic upgrade of consent.

Revocation that commits before the durable tool-start checkpoint parks the call
with a fresh approval ID. Already-started calls may finish; use turn/cancel to
request cancellation. Interrupted/uncertain actions are never replayed because a
grant survives. Screen/input leases, sandboxing, path guards and argument validation
remain independent: restoring a computer-use grant does not restore screen access.
Questions and compaction choices cannot mint grants. Implementation/evidence:
[session grants](../../docs/harness/SESSION-GRANTS.md).

## Retry, reconnect and cancel

- Correlation request IDs are not session/turn/interaction/submission IDs.
- Persist submission_id before sending turn/start. Retry identical submissions
  with the same ID, never a new one after an uncertain timeout.
- On pipe loss, restart the runtime with the same binary/bundle/policy/state and
  attach to the original session. Replay journal gaps; don't recreate the task.
- Pending pre-execution approval can recover with the same identity. An action
  whose execution began before a crash is interrupted/uncertain, not replayed.
- Changed bundle, tool schema, runner or effective policy may invalidate old consent.
  Do not auto-accept a new approval because an earlier one looked similar.
- turn/cancel takes session_id and turn_id. session/close takes session_id.
  Cancel/close only the app's intended task. Observe terminal state before
  promising cancellation or cleanup.
- Graceful stdin EOF invokes shutdown. SIGKILL is not instantaneous sandbox cleanup;
  subsequent runtime recovery reclaims recorded resources.

The sample transport does not retry mutations automatically. Its event/disconnected/
gap callbacks are integration points; the app owns UI projections and user decisions.
The smoke driver's synthetic approval allowlist must never be copied as a production
permission policy.

## Current limitations

Optional native-tool controls use `tool/control` with `session_id`, fully qualified
`tool`, and a tool-defined `request` object. This is trusted-app-only, never part of
the model tool catalog. Capabilities: `native_tool_controls` and
`ephemeral_native_images`. See [computer use](COMPUTER-USE.md) for the application's opt-in,
revocation and memory-only image contract. Existing text tool results are unchanged.

One bundle per runtime process; Linux ARM64 and native Windows host execution
are supported (see ../WINDOWS.md for tested architectures and limitations).
Build-time registered native crates are supported in source SDK builds (see
../../docs/harness/PARTNER-SDK-BUILD.md), alongside stdio MCP and connect-only loopback Streamable
HTTP configured through app-owned servers.json. No general remote/authenticated
MCP or arbitrary native-library loading. No machine enrollment,
multi-user network server or Codex drop-in compatibility claim. Transport is
OpenWorker-native; adapters can be added separately.
