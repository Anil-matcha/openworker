# OpenAI and Anthropic teams integration

The Linux/PostgreSQL server supports teams of independently configured coworker
sessions. A lead assigns work, workers discuss results on a durable message board,
and the lead accepts reviewed work. Each member retains its own provider/model,
tools, permissions, environment and transcript. The application owns the UI.

This is a developer-preview interface. Pin the supplied source revision.
For SQLite or PostgreSQL through the Rust SDK, use the
[storage-selectable SDK host](SDK-STORAGE.md). The HTTP deployment below remains
PostgreSQL-backed. Windows team qualification, automatic Git worktrees, recursive
teams and third-party agent participation are outside these checkpoints.

## Configure providers without distributing keys to API nodes

Direct native execution accepts `--provider openai|anthropic` with an explicit
`--model`. OpenAI uses Responses; Anthropic uses Messages. The fallback environment
variables are `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. The local Rust SDK exposes
`RuntimeConfig.provider`; connection-managed sessions select provider through
their named connection. Existing OpenAI connections default to OpenAI.

For servers, add trusted connection declarations to the reference configuration:

```json
{
  "model_provider": "openai",
  "model": "gpt-6-sol",
  "scripted": false,
  "model_connections": [
    {"id": "openai", "provider": "openai", "identity": "my-deployment-openai-v1", "key_env": "OPENAI_API_KEY"},
    {"id": "anthropic", "provider": "anthropic", "identity": "my-deployment-anthropic-v1", "key_env": "ANTHROPIC_API_KEY"}
  ]
}
```

Merge these fields with the existing database, bundle, runner and OpenShell
configuration; this fragment is not a complete server configuration. Use model
IDs available to your account. Live acceptance used `gpt-6-sol` and
`claude-sonnet-5-5`, as selected in the example coworker manifests.

The identities are non-secret deployment-owned values, identical on corresponding
API/worker configurations. API processes register references without reading model
keys. Workers resolve the declared environment variables into memory. PostgreSQL
stores connection/provider/model identity, never the key. Mount provider secrets
only into workers. The Helm `secrets.model` Secret can contain both variables;
the existing chart mounts that Secret only on worker pods. Permit worker HTTPS
egress to the selected provider endpoints through your deployment's controls.
This does not broaden network access for tools inside OpenShell.

Rotate the key without changing the connection identity when retaining the same
logical provider/account connection. Changing identity or provider is an explicit
new connection/release, not a transparent fallback. Worker selectors match both
working-agent and reviewer connection identities; incompatible pools leave the
session queued rather than stealing it. Configure a separate reviewer choice
when using managed connections with auto-approve. If it cannot decide, ask a human.

## Start member sessions and create the team

Use `harness/examples/team-lead` and `harness/examples/team-worker` as templates.
Their manifests select the named provider connections and declare `team_role`.
They are ordinary coworker bundles; register your product tools as usual.

The current server loads one bundle per instance. Deploy a creation API and
compatible worker pool for each coworker profile, sharing the same PostgreSQL
schema. API replicas serving an identical profile are interchangeable. An API
configured for the lead does not create arbitrary worker bundles supplied by a
request. Reads, controls and team coordination work across API nodes.

Run the existing explicit `migrate` command before starting the new server build.
It installs the versioned team extension alongside the existing session schema.
Create fresh sessions with their matching coworker roles before either starts a
turn. The same application principal must own the members; a session belongs to
one team. Use session IDs for identity; display names are unique within a team.

The following are HTTP request bodies. Supply the application operator credential
in an Authorization header from your backend, not from a browser bundle or URL.

```text
POST /sessions  [lead profile API]
{"request_id":"my-task-lead","parameters":{"name":"Lead","coworker":"team-lead","environment_id":"LEAD_ENV"}}

POST /sessions  [worker profile API]
{"request_id":"my-task-worker","parameters":{"name":"Analyst","coworker":"team-worker","environment_id":"WORKER_ENV"}}

POST /teams  [either API]
{"request_id":"my-task-team","name":"Investigation","members":[
  {"session_id":"LEAD_SESSION","name":"Lead","role":"lead"},
  {"session_id":"WORKER_SESSION","name":"Analyst","role":"worker"}
]}

POST /sessions/LEAD_SESSION/turns
{"submission_id":"my-task-start","text":"Investigate the supplied evidence with your worker. Define clear criteria, assign the work and review the result."}
```

Replace IDs with returned values. Persist request IDs before sending. Retry an
uncertain creation/submission with the same ID and identical body, not a new task.
Different request content under an existing ID is rejected.

An explicit session model override uses the existing shape:
`"model":{"connection":"anthropic","model":"YOUR_MODEL_ID"}`. The coworker
default is used when omitted; the resolved provider/model stays with the session.

The host chooses separate or shared OpenShell environments. Separate environments
do not share files merely because sessions share a board. A shared environment
must be provisioned explicitly with the existing shared-environment contract and
used only where that shared access is intended. A board is not a filesystem or a
tenant-isolation mechanism. Use durable comments/artifact references for handoff.

## Board and message protocol

| Endpoint | Purpose |
| --- | --- |
| `POST /teams` | Idempotently register fresh, role-pinned member sessions. |
| `GET /teams/:id` | Coherent board snapshot and cursor. |
| `POST /teams/:id/commands` | Idempotent app-owned board operation. |
| `GET /teams/:id/events` | SSE `team_progress`; reconnect with `Last-Event-ID`. |
| `GET /teams/:id/events/page?after=N` | Bounded replay with `next_after` and `has_more`. |

Applications keep the board cursor separately from each member's session cursor.
Deduplicate events, recover gaps, and use snapshots to restore current state.
Descriptions and messages are untrusted text: escape them in the UI. Store reads
recheck authorization, including while streaming; revocation closes the stream
with a reconcile signal. Existing session SSE carries model/tool activity and
pending approvals/questions. Team messages never replace the approval protocol.

Both lead and workers receive `team_get_board`, `team_get_item`,
`team_create_item`, `team_transition`, `team_post_message` and
`team_read_messages`. Only the lead receives `team_assign`. Tool identity and role
come from the fenced session, not from arguments. Solo coworkers get none.

Work states are `open`, `in_progress`, `blocked`, `review`, `done`, `cancelled`.
Creating a work item schedules nothing. Assignment queues work only after its
dependencies are done. Workers progress their own current assignment; only the
lead/app can accept reviewed work. Acceptance is a verdict, not automatic proof
that tests passed. Completed items are terminal; new work needs a new item.

A work item includes stable ID, full description, criteria, dependency IDs,
assignee, item revision and assignment generation. Mutations use
`expected_revision`; stale changes reject. Reassignment requires the previous
assignment turn to be terminal: cancel/wait first rather than overlapping two
workers. Moving reviewed/blocked work back to `in_progress` as lead/app creates a
new assignment turn. It never replays the old tool effects.

Messages contain store-attributed sender identity and optional item/recipient
references. Empty recipient means a passive comment. An explicit recipient queues
a new bounded turn; no broadcast fan-out or self-wake. Worker turn completion uses
a durable outbox to notify the lead after terminal state is committed. Filtered
message reads advance their scan cursor even when the page contains no matches.

Example app command:

```json
{
  "request_id": "comment-001",
  "operation": "team_post_message",
  "arguments": {"body": "Please inspect this evidence.", "item_id": "ITEM_ID", "recipient": "WORKER_SESSION"}
}
```

For staffing changes, the app first creates another fresh worker session, then
sends `team_add_member` with `{"session_id":"ID","name":"Verifier","role":"worker"}`
as arguments. Existing team/member sessions and work are retained. This is an
application provisioning operation, not a model's permission to spawn arbitrary
bundles or environments. `team_cancel` with `{}` cancels queued team deliveries
and submits ordinary cancellation controls to active member turns. Completed
effects cannot be undone, and cancellation is not proof an external action stopped.

## Durability and limits

Board changes, delivery admission, call results and event/audit records commit
transactionally. Worker/session owner fencing remains authoritative. A lost
response requires reconciliation; no automatic replay of uncertain effects.
Completion outbox processing is idempotent and does not run inside another
session's execution lock. A worker failure blocks/reports the assignment rather
than silently claiming it succeeded. Current assignment facts are refreshed from
storage before model requests, including after compaction.

This first profile bounds a team to one lead plus 15 workers, 64 work items,
16 dependencies per item, 200,000 serialized bytes per board, 4,000 UTF-8 bytes
per message, 50 events per read page,
10,000 board events, 20,000 app idempotency records and 128 automatic deliveries
for the team's lifetime. Agent records are additionally bounded by session history.
Concurrency is additionally bounded by worker slots. Exhaustion fails explicitly;
an undeliverable completion notification records `attention_required` on the board.
The app can inspect the board and explicitly submit a human follow-up to the lead.
No hidden unbounded wake loop or financial-budget guarantee is implied.

The Rust SDK's `HostConfig` supports the same team domain on SQLite or PostgreSQL,
embedded or over managed stdio, without requiring the HTTP server. See
[SDK storage](SDK-STORAGE.md) for ownership and integration details.
General guardrail hooks, OAuth MCP, cross-provider fallback and
cross-binary session migration remain outside this deliverable.

## Validation

The work ledger and [handoff plan](RELEASE-CHECKLIST.md) record exact
test scope. Live acceptance uses only synthetic content and a narrow test tool,
not customer data. It runs two independently configured HTTP API instances in one
Linux test process, a real PostgreSQL server, and production worker loops with
sandbox off. It replaces a worker loop while an approval is parked, answers via
the other API, then verifies one file effect and retained board/message results.
Separate existing Linux process-death regressions exercise actual child crashes;
the live team test is not itself a multi-host or OS-process-isolation test.
It does not claim a newly qualified OpenShell, Kubernetes, AWS or Windows release.

### Reproduce the acceptance checks

Use a disposable PostgreSQL database, never customer data. Set `OW_PG_TEST_URL`
through your private test environment. From `harness/` on Linux:

```sh
cargo test --locked -j 2 -p openworker-runtime -p openworker-sdk \
  --features openworker-sdk/test-support -- --test-threads=1
cargo test --locked -j 2 -p openworker-store-postgres --features test-support \
  --test teams --test scheduling --test worker_recovery -- --ignored --test-threads=1
cargo test --locked -j 2 -p openworker-server-reference --features team-test \
  --test teams http_team_loop -- --ignored --nocapture
```

For an explicitly authorized billable live test, also supply `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY` through the private test process environment, then replace
`http_team_loop` with `live_openai_anthropic_team` in the last command. Optional
`OW_OPENAI_TEST_MODEL` and `OW_ANTHROPIC_TEST_MODEL` select account-available models.
Never put keys in arguments, source, test reports or bundles. `team-test` permits
unsandboxed synthetic execution; do not enable it in production server builds.
This test API has a fixed synthetic credential and is strictly loopback/private.
