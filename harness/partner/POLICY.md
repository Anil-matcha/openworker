# Coworker code, app authority, session selection

A coworker bundle supplies instructions, skills and a tool selection. V3 uses fully
qualified names resolved through the startup registry; v1/v2 retain exact MCP
bindings. This is the coworker's tool list, not a second crate-owned coworker ACL.
See [the custom host example](../examples/native-tools-runtime/README.md) and
[Tools SDK](../tools-sdk/README.md) for native + MCP registration.
It cannot
grant itself host access, credentials or network privileges. The trusted app
controls --runtime-policy; the session selects a subset of named grants.

Example tools.json for a custom bundled executable (not shipped in this kit):

```json
{"version":2,"servers":[{"id":"desktop","program":"bin/example-tools","args":[]},{"id":"reports","program":"bin/report-tools","args":["--workspace","$WORKSPACE"]}],"bindings":{"desktop_status":{"server":"desktop","tool":"get_status"},"build_report":{"server":"reports","tool":"build_report"}}}
```

The executable must exist in the installed bundle and speak MCP over stdio.
Bindings are exact; catalog discovery does not silently expose extra tools.
coworker/manifest.md has schema_version: 1, id, name, version, requires_folder,
optional bundled skills, then Markdown instructions. The included native example
uses the shipped Rust binary as its MCP process; it is not ExampleApp proprietary code.

Inspect the actual installed bundle with inspect-bundle and pin its digest:

```json
{
  "version":1,
  "bundle_digest":"DIGEST_FROM_INSPECT_BUNDLE",
  "profiles":{
    "daily":{
      "sandbox":"openshell",
      "workspace_roots":["/home/alice/projects"],
      "servers":{"desktop":{"placement":"host"},"reports":{"placement":"sandbox"}},
      "network":{"service":{"host":"api.example.com","port":443}},
      "credentials":{
        "service-token":{
          "version":"operator-v1",
          "source_file":"/private/app-secrets/service-token",
          "delivery":"sandbox_file",
          "target":"/run/openworker/credentials/service-token",
          "requires_network":["service"]
        }
      }
    }
  }
}
```

This illustrates fields, not a useful screen-capture implementation. A host MCP
is trusted code with host-account access: sandbox network/filesystem grants do
NOT constrain it. OS/service consent for screen access is still required. Every
server must have an explicit placement in a configured profile. Use sandbox
placement for an MCP that must be confined; mixed placement is supported.

Launch with --runtime-policy /trusted/runtime-policy.json, then preview:

```json
{"jsonrpc":"2.0","id":2,"method":"policy/resolve","params":{"coworker":"example-assistant","workspace":"/home/alice/projects/task","policy":{"profile":"daily","network":["service"],"credentials":["service-token"]}}}
```

Create the session with that same selection plus expected_policy_digest returned
by policy/resolve. The named coworker must match the custom manifest, not the
included assistant-example. Preview does not launch tools, read credential values or
constitute user approval. Omitted optional selections mean no optional grants.

Raw credential files are visible throughout the session sandbox; they are not
secret from other processes in that sandbox. A tool can disclose a selected key.
Use narrowly scoped account credentials. OpenShell destination allowlists are
not request-level authorization and do not limit harmful payloads to an allowed
host. Host MCP credentials need host/service mechanisms, not sandbox-file delivery.

Keep policy, credential sources, bundles and state protected from agent writes.
Selected material must exist without symlinks. Bundle/policy/resource identity is
pinned and revalidated; do not rotate resources while an affected session is active.
Create a new session after authority changes. No live grant escalation or automatic
fallback from sandbox to host. Bypass skips approval only, not enforced grants.

Unknown tools default to External even if their descriptions claim read-only.
Trusted app-owned --tool-policy classification overrides are separate from grants;
changing a description/category cannot erase hard access checks.

Registered native providers also appear in the `servers` placement map, keyed by
their namespace. They must have `host` placement. In-process Rust is trusted host
code, not kernel-confined by sandbox grants; it shares the harness's process
privileges and must implement relevant OS/service authorization. Approval and
audit apply at the call boundary. Use a sandboxed MCP process for actual isolation.
