# Tool packages, routing and classification — native development profile

M2b.3 adds multiple **bundled stdio MCP servers** and an explicit host-owned
classification file. Python/Desktop is unchanged. This is not a permanent-grant
system, a signed-package verifier, or an MCP registry.
For the current M2b.4 package/skill additions and schema-6 state requirement, see
[coworker packages and skills](COWORKER-PACKAGES-AND-SKILLS.md). The schema-5 details
below describe the earlier M2b.3 checkpoint.

## Three different decisions

1. **Bundle:** which executable supplies which tool? The coworker uses a unique
   alias, resolved to exactly one server ID and remote tool name.
2. **Host policy:** what description should that tool have—`read`, `write_local`,
   `execute`, `egress`, or `external`? Unfamiliar tools default to External.
3. **Session:** Ask, Auto-approve or Bypass decides approval behavior. Classification
   is reviewer context and audit information, not a safety ranking or a grant.

Independent hard checks and the selected execution backend still apply. An override
from Write-local to Read cannot turn off the native writer's workspace restriction.
Read still asks in Ask mode. Bypass skips approval, not an enabled sandbox.

## Two-server bundle

Use the runnable `harness/examples/multi` bundle. Its `tools.json` is:

```json
{
  "version": 2,
  "servers": [
    {"id":"north","program":"$OPENWORKER","args":["mcp-example","--workspace","$WORKSPACE","--label","north"]},
    {"id":"south","program":"$OPENWORKER","args":["mcp-example","--workspace","$WORKSPACE","--label","south"]}
  ],
  "bindings": {
    "north_echo":{"server":"north","tool":"example_echo"},
    "south_echo":{"server":"south","tool":"example_echo"},
    "north_write":{"server":"north","tool":"write_file"}
  }
}
```

`north_echo` cannot fall through to South if North is missing its tool. Both remote
names may be `example_echo`; aliases must be unique. Unknown/duplicate IDs, duplicate
aliases, unbound servers, reserved aliases (`ask_user`, `read_history`) and unknown
manifest fields are rejected. Legacy single-`server` manifests still load.

For proprietary tools, replace `program` with the bundled relative executable
path, such as `bin/example-tools`. No absolute paths, traversal or bundle symlinks.
Arguments are passed directly, not through a shell. Only the exact `$WORKSPACE`
argument is substituted; no environment interpolation or credential inheritance.
An executable must support the negotiated MCP stdio protocol on Linux. No Python
is needed by OpenWorker; partners control dependencies of their own executables.

Limits: 1–8 servers; 1–64 aliases; 128 tools per server; unpaginated catalogs;
64 KB manifest/config files; 256 KB combined exposed schemas. Unsupported schemas
and tools that require MCP task-augmented execution are rejected. Descriptions
and `readOnlyHint` from servers do not establish trust.

## Operator-owned classifications

First inspect the installed bundle without executing it:

```sh
openworker inspect-bundle --bundle /opt/example/coworker
```

Copy its `bundle_digest` into an operator-authored file **outside both the bundle
and every project workspace**. Supply it explicitly to `serve` or `run`:

```json
{
  "version": 1,
  "bundle_digest": "REPLACE_WITH_INSPECTED_BUNDLE_DIGEST",
  "overrides": [
    {"server":"north","tool":"example_echo","category":"read"}
  ]
}
```

```sh
openworker serve --stdio \
  --state-dir /path/to/fresh-private-state \
  --bundle /opt/example/coworker \
  --tool-policy /path/to/operator/tool-policy.json
```

Overrides match **server ID + remote name**, not the model alias, and therefore
apply to every alias for that exact tool. No wildcards, automatic discovery,
`always_allow`, per-server trust hint or runtime/model method to edit the policy.
Only the shipped native example's known tools/exact invocation are recognized as
first-party today; other bundles need operator review to override External.

The installer/operator must protect this file, the runtime and installed bundles.
Path separation is not an OS security boundary. In particular, `--sandbox off`
gives tools host-account access and cannot protect same-user configuration from
malicious code. A policy file is a host trust input, not a sandbox.

## Durable identity and visible state

- Session snapshots carry `tool_policy.digest` and per-alias `category`,
  `base_category`, `source` (`native_builtin`, `unknown_external`, `host_policy`).
- Approval interactions and execution events carry `server`, `remote_tool` and
  `policy_digest`. The interaction's existing package/schema identity remains.
- The session execution identity pins bundle, native runner and policy contents.
  New turns and responses reject an incompatible launch profile. Policy/bundle
  contents are rechecked before authorization and dispatch.
- Changing a policy requires restarting the runtime and creating a new session.
  Even whitespace changes invalidate the content digest. Existing state remains
  inspectable/cancellable; changing the file cannot broaden a pending approval.
  Restoring the exact original profile permits its original pending work to resume.
- Every preparation/resume discovers all server catalogs and checks the pinned
  aggregate schemas/routes/catalogs. A changed catalog fails the turn without
  dispatching the approved call. There is no automatic reapproval or retry.

Catalog pinning is conservative (even a changed description/order can invalidate
it), not a proof of tool semantics. No live hot-reload/list-change subscription is
implemented. A server can lie about effects; kernel policy bounds its resources
only when a sandbox is enabled. Do not assume per-call atomic catalog integrity.

## Execution and cleanup

OpenShell: one sandbox per session, with multiple independent MCP connections.
Servers share workspace/network policy; they are **not isolated from each other**.
Sandbox-off: one native lifecycle supervisor per MCP server; all stop on park,
completion or failure, and restart for continuation. No kernel isolation.

Startup/discovery failure or cancellation cleans up the session's already-started
servers. Each startup/list operation is bounded to 30 seconds, with a 120-second
aggregate discovery budget. OpenShell lifecycle creation has its separate bounded
budget and completes before cancellation cleanup to avoid orphan creation races.

Fresh **schema-5** state is required. No migration or destructive reset of older
development stores. No machine join, HTTP MCP, dynamic libraries or credential
grants in this slice. The partner acceptance suite and reviewer evaluation set
remain the next separately agreed testing work.
