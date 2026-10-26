# Rust SDK with selectable storage

The Rust SDK runs the same agent and team logic with SQLite or PostgreSQL, either
embedded in the application or in a managed private-stdio child. The database is
an explicit configuration choice, not a prerequisite for using Teams. No REST
server is needed for this integration.

## Import and configure

The development crate is `openworker-sdk` in `harness/harness-sdk`. Import it using
a pinned Git revision of the private repository or a local path dependency; it
is not yet a published crates.io release. Partners need repository access. For
example, replace the revision placeholder with the handoff's full commit:

```toml
[dependencies]
openworker-sdk = { git = "ssh://git@github.com/andrewyng/openworker.git", rev = "PINNED_COMMIT" }
tokio = { version = "1", features = ["full"] }
serde_json = "1"
```

Use `HostConfig` for storage selection and one or more trusted coworker profiles.
The older `RuntimeConfig` single-coworker/local constructors remain compatible.
Both configurations use the same `HarnessClient` application methods.

```rust,ignore
use openworker_sdk::*;

let config = HostConfig {
    state_dir,                  // Stable absolute private controller directory.
    runner: runner_binary,      // Absolute compatible OpenWorker helper binary.
    storage: Storage::Postgres {
        connection_env: "MY_APP_DATABASE_URL".into(),
        schema: "ow_my_product".into(),
        ca_file: Some(postgres_ca),
        loopback_plaintext: false,
    },
    coworkers: vec![
        CoworkerConfig {
            bundle: lead_bundle,
            model: "gpt-6-sol".into(),
            provider: ModelProvider::Openai,
            servers: None, tool_policy: None, runtime_policy: None,
        },
        CoworkerConfig {
            bundle: worker_bundle,
            model: "claude-sonnet-5-5".into(),
            provider: ModelProvider::Anthropic,
            servers: None, tool_policy: None, runtime_policy: None,
        },
    ],
    sandbox: Sandbox::Openshell,
    scripted: false,
    agents: vec![],             // Using the hand-written coworkers above.
    telemetry: None,
};

// Operator setup before starting a new/upgraded PostgreSQL installation.
// Run deliberately, not as an unreviewed side effect of every request.
config.storage.migrate()?;

let client = HarnessClient::embedded(
    config, my_native_tool_registry, ClientOptions::default()
).await?;
```

For SQLite, change only `storage` to `Storage::Sqlite`; its database is under
`state_dir`. This chooses where new state lives—it does not migrate existing
sessions between databases.

To use a child process instead, pass the same `HostConfig` to:

```rust,ignore
let client = HarnessClient::managed_stdio(HostProcessConfig {
    program: partner_harness_binary,
    host: config,
    restart: RestartPolicy::default(),
}, ClientOptions::default()).await?;
```

Build the default MCP-capable child with
`cargo build --locked -p openworker-sdk --bin openworker-harness`. For native
partner tools, link them into a partner child using this entry point:

```rust,ignore
fn main() {
    let mut tools = openworker_sdk::ToolRegistry::default();
    my_tools::register(&mut tools).expect("register tools");
    openworker_sdk::cli::main_with_registry(tools);
}
```

That entry point supports the SDK host protocol plus existing helper commands.
Existing binaries using only `openworker_runtime::cli` retain their old interface;
they do not silently acquire the new multi-coworker host launcher. Embedded native
tools come from the supplied registry; Rust implementations are never transferred
over stdio. Keep the runner/partner binary and tool implementation versions pinned.

## Credentials and application operations

The PostgreSQL connection string is read from the explicitly named environment
variable, never from the serialized launch configuration or executable arguments.
The managed SDK forwards only that declared database variable plus the normal
OS/runtime allowlist. Do not log process environments. Model credentials use the
existing private `connection/set` protocol, separately for each coworker:

```rust,ignore
client.request("connection/set", serde_json::json!({
    "coworker": "team-worker", "id": "anthropic", "label": "Worker provider",
    "provider": "anthropic", "api_key": key_from_private_input,
    "persistence": "memory"
})).await?;
```

The host removes the routing field before calling the normal credential handler.
Keys never enter the session or team database. Memory keys must be resupplied
after a child restart; this does not automatically retry an interrupted turn.
Automatic deliveries stay queued while model credentials are unavailable. Host
snapshots expose `session.model_credentials_ready`; this is not a live provider
health check. Resupplying a key permits still-unstarted deliveries to proceed.
Coworker defaults and explicit session overrides retain their existing precedence.

`create_session`, `start_turn`, `subscribe`, `attach`, `approve`, `answer`,
`cancel_turn`, history, plans, skills, tool controls and model connections use the
same SDK interface for both adapters. Each session routes to its pinned coworker.
Use `coworker/list` to inspect the registered profiles. Workspace and permission
configuration remain per session; choosing PostgreSQL does not grant sandbox,
filesystem, network or credential access.

Team methods are `create_team(TeamCreate)`, `team_snapshot(id)`,
`team_command(id, TeamCommand)` and `team_events(id, after)`. `TeamMember` and
`TeamRole` are exported by the SDK. The work-item/message command bodies are the
same as [the team protocol](PROVIDERS-AND-TEAMS.md). Start fresh role-pinned member
sessions, create the team, then submit the task to its lead. The host consumes
durable deliveries and terminal notifications; the application need not schedule
individual worker turns. Member session progress is pushed through `subscribe`;
board events use the separate cursor-based `team_events` API. Persist those
cursors and reconcile after reconnect rather than treating notifications as
exactly-once delivery.

## Ownership and storage responsibilities

This SDK host is a single execution supervisor with up to 16 coworker profiles
and the existing four active-turn slots per profile. PostgreSQL requires a
multithread Tokio runtime. Both databases provide the
same team semantics. SQLite holds an exclusive state-directory lock. PostgreSQL
uses a dedicated SDK schema, a connection-level host lock, session epochs and
lease renewal. A second host is rejected; after connection/process loss the next
host fences the prior epochs and recovers without replaying uncertain effects.
The local controller directory remains required with PostgreSQL for private
connection metadata and runtime/tool state. Do not share it between live hosts.

Use a fresh PostgreSQL schema for SDK-managed execution. It cannot silently adopt
an existing distributed-server schema, and distributed workers reject SDK-owned
schemas. Multi-node execution remains the existing separately configured server
worker-pool deployment; database choice alone does not enable it. This distinction
concerns who owns execution, not whether an agent can use Teams.

Common validation, work transitions, dependency dispatch and completion decisions
live in `runtime/src/team_service.rs`. Adapters implement transactions, receipts,
event storage, ownership and queue operations. PostgreSQL's HTTP authorization and
multi-node controls remain in its server adapter; SQLite is not represented as a
network-accessible multi-tenant service. The SDK is a trusted backend API, not an
authentication boundary for untrusted callers.

Current parity covers native sessions/teams and the agent features above. Remote
environment provisioning, HTTP authorization administration, artifact-service APIs
and distributed operational metrics remain server-host APIs, not new SDK methods.
This checkpoint does not introduce missing general guardrail hooks or memory tools.

## Verification and example

`harness/harness-sdk/examples/storage_host.rs` is a compilable consumer. It loads a
JSON `HostConfig`, initializes the selected host and shuts down without a model
call. Run from `harness/`:

```sh
cargo run --locked -p openworker-sdk --example storage_host -- embedded /absolute/host.json --migrate
cargo run --locked -p openworker-sdk --example storage_host -- stdio /absolute/host.json
```

The storage/process acceptance matrix is in `harness-sdk/tests/storage_teams.rs`.
It uses synthetic models and real native tools, databases and subprocesses. A lead
assigns work, a worker waits at approval, restart retains that approval, one tool
effect occurs, comments persist and the lead accepts the result. Managed modes kill
the owned child to exercise automatic recovery; both stores reject competing hosts.
The same domain assertions run against SQLite and PostgreSQL. Separate SQLite
tests inject transaction failure and reject an unsupported future team schema.

Linux qualification and exact regression results are recorded in the work ledger.
This is a source SDK checkpoint, not a new Windows, OpenShell/AWS deployment,
signed binary release or stable published API promise.
