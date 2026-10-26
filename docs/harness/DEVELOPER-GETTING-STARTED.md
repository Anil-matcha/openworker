# Developer getting started with the OpenWorker harness

Build an application around OpenWorker's native agent loop, then deploy the same
server roles locally or on Kubernetes. Your application owns its UI, user identity
and product logic. OpenWorker owns execution state, tool policy, approvals,
session recovery and durable progress. There is no Python runtime in the native
harness or its application images.

This is a development reference, not a production service or stable public SDK.
Use a pinned checkout containing `harness/` and `deploy/helm/openworker/`.
Start with the [desktop QuickStart](QUICKSTART.md) for local applications, or
continue below for server deployments. Review the
[release checklist](RELEASE-CHECKLIST.md) before distribution.

## Choose your integration

For OpenAI/Anthropic selection and server-side agent teams, see
[the providers and teams integration guide](PROVIDERS-AND-TEAMS.md). It includes
role-pinned coworker templates, secret-free API connection references, shared
board/messages, provider-compatible worker routing and the HTTP handoff flow.

| Application                              | Starting point                                                         | State and transport                                                           |
| ---------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Native Rust application                  | [Harness SDK](../../harness/harness-sdk/README.md), [storage/team guide](SDK-STORAGE.md) | Embedded or managed stdio; choose SQLite or PostgreSQL for sessions and teams |
| Application managing its own child       | [Partner protocol](../../harness/partner/PROTOCOL.md), the minimal desktop starters  | Direct stdio JSON-RPC, pushed events and durable local sessions               |
| Web application or multiple server nodes | [Server reference](../../harness/server-reference/README.md), Task Desk | REST commands, SSE progress, PostgreSQL and independently scheduled workers   |
| Partner-owned tools                      | [Tools SDK](../../harness/tools-sdk/README.md)                          | Native Rust registration or explicitly registered MCP providers               |

The Harness SDK and the server REST API are separate integration surfaces.
The Rust SDK does not currently act as a REST client for a distributed deployment.
Neither API is promised to be a drop-in Codex/ACP replacement.

## Understand the server layout

```text
Browser → Your app backend → Any harness API ───────→ S3 artifacts
                                   ↕
                              PostgreSQL
                                   ↕
                           Compatible worker
                                   │ verified mTLS
                             OpenShell gateway
                                   │
                          Sandbox and workspace PVC

API and worker → Optional OpenTelemetry collector → Your observability backend
```

APIs save commands and stream persisted events; they do not proxy a live worker
connection. Any API can read a session or accept its approval/cancellation.
Workers claim compatible work using database leases. No sticky API routing is
needed. The session remains bound to its original execution identity and
environment; moving API traffic does not move sandbox files.

Key code locations:

- `harness/runtime/`: shared native loop, coworker loading, policy and tool execution.
- `harness/harness-sdk/`, `harness/tools-sdk/`: application and tool integration APIs.
- `harness/store-postgres/`: durable commands, leases, approvals, journal and recovery.
- `harness/server-reference/`: API/worker/admin roles and HTTP authorization.
- `harness/artifacts/`, `harness/telemetry/`: durable bytes and optional instrumentation.
- `harness/task-desk/`: small browser application and Node backend using the HTTP API.
- `deploy/reference/`, `deploy/helm/`, `deploy/aws/`, `deploy/recovery/`: deployment,
  operations, qualification and recovery references—not another agent loop.

## Build the native components

Use the pinned Rust 1.96 toolchain, a supported Linux build environment and the
locked dependencies. Node 20.19+ is needed for the reference web app/scripts, not
for the Rust agent loop. Docker, kubectl and Helm are needed for deployment work.

From the repository root:

```sh
cargo build --release --locked --manifest-path harness/Cargo.toml \
  -p openworker-runtime -p openworker-server-reference
node --test harness/task-desk/server.test.mjs
```

The binaries are `harness/target/release/openworker` and
`harness/target/release/openworker-server-reference`, unless you set
`CARGO_TARGET_DIR`. The cloud qualification used a cached, locked release build
on Linux ARM64. A macOS compilation does not produce a Linux tool runner.

For a source-built application image:

```sh
docker build --target runtime -f deploy/containers/Dockerfile \
  --build-arg COWORKER_BUNDLE=harness/examples/task-desk \
  -t openworker-harness:my-build .
docker build -f harness/task-desk/Dockerfile -t openworker-taskdesk:my-build .
```

Build the OpenShell runner image with the **same Linux `openworker` executable**
contained in the harness image. Follow the extraction/build steps in the
[Helm guide](../../deploy/helm/README.md#build-and-import-images), then publish
both images and use their registry manifest digests. Do not substitute a Docker
configuration ID or an unrelated executable. The tested cloud path used the
`prebuilt` image target; the cold Docker release build is not the evidence for
this qualification. Signing, SBOMs and release publishing remain deployment work.

## Run a local server reference first

Start with a dedicated development environment, not an existing user deployment.
Provision the [local Kubernetes/OpenShell reference](../../deploy/local/README.md)
and verify its network policies. The server profile uses OpenShell 0.1.3,
authenticated TLS, persistent workspace storage and a matching Linux runner.
Do not use the older desktop `sandbox setup` recipe as a Kubernetes installer.

Copy [connection.example.json](../../deploy/reference/connection.example.json)
to a private location. Fill in the actual gateway endpoint, client certificate
directory, gateway identity, runner path and immutable runner image. Then:

```sh
export OW_SERVER_BINARY="$PWD/harness/target/release/openworker-server-reference"
node deploy/reference/stack.mjs init .ow-stack/myapp /private/connection.json
node deploy/reference/stack.mjs up .ow-stack/myapp
node deploy/reference/stack.mjs run .ow-stack/myapp
```

`init` creates private deployment state and refuses to overwrite an existing
directory. `run` builds on the same native server roles, explicitly prepares the
database and starts two APIs, two workers and the read-only console. Supply
`OW_SERVER_BINARY` if using your release binary instead of the default build path.
Optional Grafana/LGTM is a local development bundle. The
[local guide](../../deploy/reference/README.md) lists ports, generated credential
files, `--no-observability`, multiple-instance offsets and shutdown behavior.

Stop `run` before executing the destructive-to-this-fixture qualification:

```sh
node deploy/reference/qualify.mjs .ow-stack/myapp
node deploy/reference/stack.mjs run .ow-stack/myapp
```

Save the returned environment ID. This fixture uses a deterministic model but
real PostgreSQL, artifacts and sandbox tools. A shared fixture workspace is not
tenant isolation. Do not use a shared environment for mutually untrusted users.

## Define your coworker and tools

Keep the trusted bundle outside agent-writable workspaces. The
[`harness/examples/task-desk/`](../../harness/examples/task-desk/coworker/manifest.md)
bundle supplies a coworker ID, version, instructions and explicit file/shell MCP
routes. The server configuration loads that bundle; session creation selects its
coworker ID. One runtime instance loads one bundle, so use separate compatible
worker pools when hosting different releases.

For a partner executable or embedded application, the Tools SDK also supports
native Rust tool registration and qualified names such as `example.web_search`.
The coworker selects names; registration tells the harness where to resolve them.
Tool visibility is not permission to bypass approvals or filesystem/network policy.
Credentials belong to the host's connection/policy configuration, not instructions.
See [tools and routing](../../harness/tools-sdk/README.md) and
[coworker packages and skills](COWORKER-PACKAGES-AND-SKILLS.md).

The supplied cloud server reference exercises remote OpenShell/MCP execution.
It is not a general native-plugin loader. Additional host-native integrations
require a reviewed embedding/server extension; do not assume that adding a crate
name to a coworker manifest dynamically loads its implementation.

## Submit your first task

For a manually deployed server, use a host-owned reference configuration based on
[config.example.json](../../harness/server-reference/config.example.json).
Run `migrate`, `auth-bootstrap` and `environment-create` explicitly on first
installation, as described in the server guide. The local launcher above already
prepares its schema/authentication; reuse its saved environment instead of
bootstrapping it again. For an uncertain provisioning
result, inspect/reconcile the original request and object—do not create another
sandbox simply because the initial request timed out.

Issue an application **operator** credential with `owned` scope and the exact
environment grant. Keep the administrator and observer/probe credentials separate.
[Authorization examples](../../harness/server-reference/AUTHORIZATION.md) cover
issuance, rotation and revocation. Store keys in private files or your secret
manager; never put them in command arguments, URLs or frontend bundles.

For the local server's default ports and bundled `assistant-example` coworker, the
Node CLI demonstrates the complete interaction. Replace `ENV_ID` with the saved
environment ID and use the operator key issued above:

```sh
export OW_API_TOKEN_FILE=/private/application-operator
export OW_API_URLS=http://127.0.0.1:58181,http://127.0.0.1:58182
node harness/server-reference/client.mjs \
  --environment ENV_ID --coworker assistant-example --request-id first-task-001 --fixture
```

Choose Allow Once, Allow for this Session or Deny when asked. For a live-model
cohort, use `--text 'Write and verify a short packing checklist'` instead of
`--fixture`. Configure `scripted: false`, an available model ID and the worker's
provider credential deliberately. Preserve existing model/version pools for
already-created sessions; changing every worker's model is not a session migration.

For a Helm TLS tunnel, instead set `OW_API_URLS=https://127.0.0.1:9443` and
`NODE_EXTRA_CA_CERTS=/private/api-ca.crt`. The qualified AWS image bundles coworker
`task-desk`; use that ID only against a server configured with that bundle.

Reconnect without submitting another task:

```sh
node harness/server-reference/client.mjs --session SESSION_ID
```

## Add your application UI

[Task Desk](../../harness/task-desk/README.md) is the smallest complete server
integration. Its Node backend holds the operator credential; its browser uses a
separate workspace key and HttpOnly cookie. It has no agent loop or direct
database access. Run it with a private configuration:

```json
{
  "apis": ["http://127.0.0.1:58181", "http://127.0.0.1:58182"],
  "api_token_file": "/private/application-operator",
  "access_key_file": "/private/task-desk-access",
  "environment_id": "ENV_ID",
  "coworker": "assistant-example",
  "workspace": "/sandbox",
  "port": 54350,
  "mode": "scripted-test"
}
```

```sh
node harness/task-desk/server.mjs /private/task-desk.json
```

Open `http://127.0.0.1:54350`. Set `mode` to `live` only when the selected server
cohort really uses a live model. The app is single-operator/single-replica; its
login cookie is process-local. Restarting the app may require sign-in again,
but does not erase the harness's sessions.
For Kubernetes, replace the upstream addresses/coworker with that deployment's
values and configure `NODE_EXTRA_CA_CERTS` for a private API certificate authority.

When replacing Task Desk with your own UI, preserve these contracts:

1. Persist request/submission IDs before sending mutations. After response loss,
   inspect the original receipt or retry the identical request—not a new task ID.
2. Save the session ID and processed event cursor. Reconnect SSE from that cursor,
   deduplicate events, and reconcile snapshots when a gap is detected.
3. Show the actual pending tool/action and send the user's decision with its
   interaction ID and four saved identity/policy digests. Never manufacture a
   broader approval because the UI was reloaded.
4. Send answers and cancellation through `/sessions/:id/controls`. Accepted is
   not the same as applied; observe the resulting durable state.
5. Register selected outputs with size/SHA-256, upload the bytes, then wait for
   ready metadata. Task Desk's Save response exports assistant text; a sandbox
   filename alone is not a published artifact.

See the [HTTP contract](../../harness/server-reference/README.md#http-contract-reference-v0)
and [artifact API](../../harness/artifacts/README.md). Browser authentication,
SSO, tenant admission, quotas and public ingress are your application's duties.

## Deploy on Kubernetes or AWS

The reusable chart is `deploy/helm/openworker/`. It installs separate API/worker
Deployments, a private TLS Service, readiness probes and NetworkPolicies. It does
not install the cluster, database, object store, OpenShell, CNI or public ingress.

For your own account, provision those dependencies independently. The tested AWS
reference uses EKS, RDS PostgreSQL, S3/ECR, workload identity, an independent
OpenShell release and a dedicated VPC. Start with:

1. An enforcing CNI and Agent Sandbox controller. Wait for healthy cluster
   add-ons before installing application controllers; verify real deny/allow
   behavior rather than trusting the existence of a NetworkPolicy object.
   Prefer controller-managed helper workloads: AWS documents unreliable policy
   enforcement for standalone pods without owner references.
   [EKS network policy considerations](https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html).
2. A private PostgreSQL database, TLS trust bundle and least-privilege database
   identity. The disposable AWS fixture uses the RDS managed master credential;
   that is not a recommended production application role.
3. A private artifact bucket and API workload role limited to its deployment
   prefix. AWS Pod Identity was tested; no permanent AWS key is required in pods.
4. A separately installed, authenticated OpenShell gateway, storage class,
   persistent workspace volumes, matching runner image and explicit resource policy.
5. API TLS certificates and separate database, probe, gateway and model Secrets.
   The [chart secret contract](../../deploy/helm/README.md#using-the-chart-with-existing-infrastructure)
   gives exact key names. Secret values do not belong in Helm values.

Supply your reviewed values and explicit kubeconfig/context:

```sh
helm upgrade --install ow deploy/helm/openworker \
  --kubeconfig /private/cluster.kubeconfig --kube-context YOUR_CONTEXT \
  --namespace YOUR_NAMESPACE --values /private/harness-values.json --wait
```

On first installation, keep API/worker replicas at zero while the trusted
deployment operator runs schema/auth/environment bootstrap Jobs. Issue the probe
and application credentials, verify the original environment is ready, then
enable replicas. Normal startup does not reset or silently migrate old state.

Keep API S3 authority separate from worker model/gateway credentials. API pods
receive only the gateway CA, not its private client key. Configure necessary
database, model, object-store and telemetry egress explicitly. The chart's
NetworkPolicy is not an end-user or physical tenant boundary.

For private inspection, forward the TLS Service to loopback. For Task Desk in
the chart, forward its pod's loopback port. If using `54351:54350`, configure
`taskDesk.config.origin: http://127.0.0.1:54351`; the readiness probe still connects
locally with the configured Host. Public exposure requires a separate reviewed
ingress, TLS/user authentication and app security design.

### The disposable AWS experiment

[`deploy/aws/README.md`](../../deploy/aws/README.md) contains the exact qualified
workflow and teardown commands. Its scripts are intentionally locked to one
approved account, region and dated resource scope. They are **not a general
customer-account installer**. Do not remove ownership checks to repoint them at
an existing environment. Reuse the chart and architecture, and review new
infrastructure automation for your account.

The experiment has fixed capacity, a $100 budget alert and an independent
24-hour cleanup guard. **The guard deletes its disposable stack and data.** Budget
alerts are delayed, not a billing cap. Never use that expiry policy for production.
There is no turnkey AWS/Azure account-provisioning service in this release.

## Operate and recover

| Situation                             | Action                                                                                                                                                                       |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API replacement or browser disconnect | Reconnect through any API using the original session and cursor.                                                                                                             |
| Worker loss after a tool started      | Inspect its unknown outcome in the original environment. Never automatically repeat the effect.                                                                              |
| Planned rollout                       | Let the harness drain; readiness fails immediately, then active work finishes or is boundedly interrupted.                                                                   |
| New binary, bundle or model cohort    | Keep compatible old workers for old open sessions. Use `worker-pools` diagnostics; API-only creation rollback does not retire other pools.                                   |
| Database outage                       | Restore database health and explicitly restart poisoned connections. Do not reset sessions to make requests succeed.                                                         |
| Restore from backup                   | Restore into isolation with `recovery_read_only: true`, zero workers and no model/gateway credentials. Verify IDs, events and artifacts before an operator-approved cutover. |
| Collector unavailable                 | Execution continues; telemetry loss/export counters are diagnostic. Telemetry is not the durable audit journal.                                                              |

Default worker shutdown allows 300 seconds to drain plus 45 seconds for cleanup;
Helm's 360-second grace covers both. A second termination signal requests
interruption. Kubernetes sends the lifecycle signal; the harness owns admission,
lease renewal and handling uncertain effects. This is different from assuming
every restart is safe. See [draining](../../deploy/reference/DRAINING.md),
[upgrades](../../deploy/reference/UPGRADES.md) and [sizing](../../deploy/reference/SIZING.md).

For observability, configure `telemetry.endpoint` explicitly. Use HTTPS for a
remote collector; plaintext HTTP is allowed only for loopback, such as a collector
sidecar. No collector is implicitly installed by the chart. Use your existing
backend or the optional [local operations dashboard](../../deploy/reference/OPERATIONS.md).
The AWS test verified real OTLP traces, metrics and lifecycle logs, not production
Grafana retention, paging or an end-to-end distributed trace across workers.

Back up PostgreSQL **and** referenced artifact objects; preserve their binding
identities. Workspace/PVC recovery, deployment secrets, key revocations and old
worker fencing are separate concerns. The cloud restore test retained original
S3 bytes; the [local archive drill](../../deploy/recovery/README.md) separately
tests copying/verifying immutable objects. Neither proves a full production DR
cutover, PITR, multi-AZ availability or exactly-once external actions.

Before production, complete your tenant isolation, least-privilege roles,
certificate/secret rotation, ingress/SSO, resource quotas, encrypted offsite
backups, release signing and alerting work. Run qualification against your actual
infrastructure. Four concurrent fixture sessions are correctness evidence—not a
production throughput guarantee.
