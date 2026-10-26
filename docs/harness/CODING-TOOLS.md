# Coding tools and unattended sessions

The SDK host registers the first-party `coding` tool provider automatically. An
agent sees only the qualified tools selected in its definition. These tools run
in the session's tool runner, using the selected execution backend; they are not
callbacks executing inside the trusted Node application or Rust host.

`coding` is now a reserved first-party namespace. Use another namespace for
application tools or external MCP services. Match SDK and host revisions. The
host advertises `coding_tools`, `coding_processes` (Linux only), and
`sdk_question_policy`; session question overrides reject older hosts explicitly.

## Server integration

A server may run the TypeScript SDK and its managed Rust subprocess in the same
learner container. Each container can use the same preview port. `sandbox: "off"`
means the harness does not add OS isolation: the deployment supplies the container
boundary. Sharing a container does not isolate tools from the IDE's own process,
files or credentials. Keep credentials/state outside the tool workspace and choose
container permissions appropriate to your application.

```typescript
const harness = await Harness.start({
  executable: "/opt/openworker/openworker-harness",
  stateDir: "/var/lib/ide/harness",
  sandbox: "off", // The deployment supplies a learner container.
});
await harness.setModelProvider({
  name: "OpenAI",
  api: "chat-completions", // Match the API exposed by your provider/proxy.
  baseUrl: configuredProviderUrl,
  credentials: { apiKeyEnv: "PLATFORM_LLM_TOKEN", storage: "memory" },
});
// Node resolves the environment reference; the key is not a tool environment var.
// Resupply memory-only credentials when the application restarts. For rotating
// bearer tokens, use the provider auth callback/proactive update API instead.
const coder = harness.createAgent({
  name: "coder",
  instructions: "Build the learner's app. Serve its preview on port 4000.",
  defaultModel: { provider: "OpenAI", name: selectedModelId },
  approvals: { mode: "never" },
  autoSkipQuestions: true,
  tools: [
    "coding.read_file", "coding.write_file", "coding.edit_file",
    "coding.list_files", "coding.search_files", "coding.run_shell",
    "coding.process_start", "coding.process_status",
    "coding.process_logs", "coding.process_stop",
  ],
});
const session = await coder.newSession({ workspace: "/workspace" });
const run = await session.send("Build a small quiz app.");
for await (const event of run.events()) {
  // Translate into your browser UI's event vocabulary.
}
const result = await run.result();
```

```rust,ignore
let coder = harness.create_agent(
    Agent::new("coder")
        .instructions("Build the learner's app. Serve previews on port 4000.")
        .default_model(Model::new("OpenAI", selected_model_id))
        .approvals(Approvals::Never)
        .auto_skip_questions(true)
        .tools(["coding.read_file", "coding.write_file", "coding.edit_file",
                "coding.list_files", "coding.search_files", "coding.run_shell",
                "coding.process_start", "coding.process_status",
                "coding.process_logs", "coding.process_stop"])
).await?;
let session = coder.new_session_in("/workspace").await?;
```

An evaluator can be a separate agent/session selecting only `read_file`,
`list_files` and `search_files`. It does not need a team board just to grade a
submission. Shell access can modify files even if no writing tool is selected.

## Questions are independent of approvals

`autoSkipQuestions` / `.auto_skip_questions(true)` defaults to false. It applies
only to structured `ask_user` calls. The runtime records a skipped-question result
with no answer and tells the model to use reasonable assumptions or report missing
essential information. It never invents an answer or grants tool permission.

Override it when creating a session:

```typescript
const interactive = await coder.newSession({
  workspace: "/workspace", autoSkipQuestions: false,
});
```

```rust,ignore
let interactive = coder.new_session_with(
    SessionOptions::default().workspace("/workspace").auto_skip_questions(false)
).await?;
```

The resolved choice is stored with the session and survives reconnect/restart.
A lead-session override does not overwrite worker-agent defaults. Ordinary chat
questions are still text; this flag does not suppress them. `approvals: never`
means bypass, while auto-review may still park a tool call for human judgment.

## Tools

| Tool | Behavior |
|---|---|
| `read_file` | UTF-8 lines with zero-based offset, bounded output and whole-file SHA-256. Files limited to 1 MiB; long-line clipping is explicit. |
| `write_file` | Atomic file replacement, optional `create_only` and `expected_sha256`. |
| `edit_file` | Exact single-occurrence replacement with required `expected_sha256`; rejects stale or ambiguous edits. |
| `list_files` | Sorted, bounded recursive listing; optional subdirectory and hidden files. Skips symlinks, `.git`, `node_modules`, `target`. |
| `search_files` | Bounded literal text search with file/line results; skips binary/large files. Not regex or `.gitignore` parity yet. |
| `run_shell` | Fresh shell in workspace; returns exit information or a tracked process ID after `yield_ms` (default 1,000, max 10,000). |
| `process_start` | Starts a tracked server/build immediately; default lifetime 3,600 seconds. |
| `process_status` | Running/exited/stopped/timed-out status and exit code, when available. |
| `process_logs` | Bounded stdout/stderr tails with truncation flags. |
| `process_stop` | Stops only a process owned by this session runner, including ordinary background descendants. |

File tools reject traversal and symlinks. Writes use a cooperative workspace lock
and atomic replacement; existing executable permissions are preserved. That lock
coordinates these tools, not unrelated editors or arbitrary shell commands. It
is not a replacement for filesystem isolation against malicious concurrent changes.

Shell/process tools currently support **Linux**. macOS and Windows report an
explicit unsupported error; native process-ownership integration is a follow-up. File
tool code is portable, but these changes have not been qualified on a Windows VM.
The shell's cwd and environment do not persist between commands. Its environment
contains a fixed PATH, temporary HOME and sandbox proxy/CA plumbing, not inherited
model credentials. Commands can still access anything their OS identity permits.

Linux images must include the binary's shared-library dependencies. For example,
Debian Bookworm slim Node images need `libssl3` and `ca-certificates`; including a
Rust executable alone does not supply those libraries.

Both shell and process-start accept `timeout_seconds` from 1 to 86,400. Shell
defaults to 60 seconds. Long installs/builds should use a suitable timeout and
poll the returned process ID. Output buffers and the number of live processes
are bounded (8 live, up to 64 retained records per runner); completed records can
be evicted. Logs are transient snapshots, not a durable audit archive.

## Process lifetime

Selecting `process_start` or `run_shell` permits the first-party coding runner to
remain alive between successful turns in the same local SDK host. Arbitrary
unsandboxed MCP servers keep their existing turn-bounded cleanup. Explicit
turn-scoped resource grants also keep their existing cleanup; this feature does
not extend credential/network grants. A remote or distributed worker release can
end its runner attachment; portable dev-server handoff is not provided here.

Active-turn cancellation, failure, session close and host shutdown clean up local
owned runners. Cancelling an already completed turn is a no-op; use `process_stop`
or close the session to stop an idle preview. A container restart/harness recovery
does not restart dev servers. Old process handles become unknown; the application
or agent must explicitly decide to start a replacement. A successful start receipt
means a process was spawned, not that its HTTP port is ready—probe readiness.

Tests use real subprocesses and local files with scripted model fixtures, including
cross-turn status, question policy overrides, approval denial, timeout, bounded
logs, cleanup and SDK child-crash recovery. No live model is required.

## Verification (2026-10-26)

- Linux: 175 runtime/SDK tests passed, including 8 coding tests and 2 SDK coding
  tests in embedded/managed modes. The single ignored test entry is the HTTP
  server fixture, explicitly launched by the preview acceptance test.
- macOS: 14 SDK unit tests, 2 SDK file/question tests, 5 coding file/platform tests
  and 3 real-host TypeScript tests passed. These do not claim native process-tool
  support on macOS. The runtime's Linux `/bin/true` unit fixtures cannot run as
  native Mach-O helpers; the full runtime suite was verified on Linux instead.
- TypeScript: 17 configuration/transport tests passed, including recovery when a
  descendant holds a pipe open and explicit rejection of unsupported old hosts.
- The final real-host TypeScript acceptance test passed in a Linux Node container:
  cross-turn process status, approval denial, question skipping, forced host death,
  child cleanup, restart and rejection of stale handles without replaying the start.
- Strict Rust Clippy and formatting passed on Linux/macOS; documentation links
  passed. No live model, Windows VM or OpenShell cluster was exercised in this batch.

Commands for the main Linux checks:

```sh
cd harness
cargo test --locked -p openworker-runtime --lib --tests -- --test-threads=1
cargo test --locked -p openworker-sdk --features test-support --lib --test coding -- --test-threads=1
npm --prefix typescript-sdk test
OW_TS_TEST_HOST="$PWD/target/debug/sdk-test-host" node --test typescript-sdk/test/coding.test.mjs
```
