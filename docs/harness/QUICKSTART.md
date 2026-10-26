# Build an agentic desktop app

Focus on your product experience. OpenWorker handles the agent loop, tool calls,
approvals, streaming and durable sessions. Choose TypeScript + Electron or
Rust + Tauri; users install one desktop app in either case.

Prefer the tabbed guide? Open [DESKTOP-QUICKSTART.html](DESKTOP-QUICKSTART.html)
from this checkout in a browser. For a complete product rather than a minimal
starter, see [Arcade Studio](../../harness/examples/arcade/README.md).

This is a source-based release candidate. No published npm/crates.io package or
signed installer is assumed by the commands below. Pin a tested revision when
integrating. Use Node.js 24, npm 11+, the pinned Rust toolchain and your platform's
C++ build prerequisites; Tauri also needs its platform WebView prerequisites.

## 1. Start the harness

First build the host and SDK from the same checkout:

```sh
git clone --branch openworker-harness-sdk https://github.com/andrewyng/openworker.git
cd openworker/harness
cargo build --release --locked -p openworker-sdk --bin openworker-harness
npm --prefix typescript-sdk ci
npm --prefix typescript-sdk run build
cd ..
```

Generate **one** starter in a new directory:

```sh
# TypeScript / Electron:
node harness/desktop-starters/create.mjs ../my-arcade --template electron-game-builder

# Or Rust / Tauri (choose a different directory if you generated the first):
node harness/desktop-starters/create.mjs ../my-rust-arcade --template tauri-game-builder
```

The generated app wires the SDK to chat, settings, approvals/questions and an
isolated preview. Install its dependencies and launch it:

```sh
cd ../my-arcade
npm install
npm run dev
```

The following snippets explain the SDK calls inside your app; do not start a
second harness alongside the starter's existing instance.

**TypeScript** (trusted Electron main process):

```typescript
import { Harness } from "@openworker/harness";

const harness = await Harness.start({
  appId: "my-arcade",
  sandbox: "off", // Explicit host callbacks; no OS sandbox around your app.
});
```

**Rust** (your Tokio runtime):

```rust,no_run
use openworker_sdk::{Harness, Sandbox};
# async fn example() -> openworker_sdk::Result<()> {
let harness = Harness::builder().sandbox(Sandbox::Off).start().await?;
# harness.shutdown().await?;
# Ok(()) }
```

Rust embeds the engine by default; TypeScript owns a Rust child over private
stdio. The starter bundles/discovers the executable. Outside a generated app,
supply its absolute path with `executable` / `.executable(...)`. Optional state,
session and scratch directories are described in the visual guide. Keep app
catalogs separate from SDK-owned session storage.

## 2. Connect a model

Use the starter's Model settings panel or configure providers in code. The provider
name is your application's label; the API and base URL select the actual endpoint.

**TypeScript — cloud:**

```typescript
// Your UI collects the key; pass it privately to this trusted app process.
await harness.setModelProvider({
  name: "OpenAI",
  api: "responses",
  baseUrl: "https://api.openai.com/v1",
  credentials: { apiKey: keyFromSettings, storage: "secure" },
});
const selectedModel = { provider: "OpenAI", name: modelIdFromSettings };
```

**Rust — cloud:**

```rust,ignore
use openworker_sdk::{Credentials, Model, ModelProvider};
harness.set_model_provider(
    ModelProvider::responses("OpenAI")
        .credentials(Credentials::secure(key_from_settings))
).await?;
let selected_model = Model::new("OpenAI", model_id_from_settings);
```

**Local model alternative:** start Ollama or another compatible local server first.
Choose an installed model that supports the tools needed by your app. The SDK
does not install models or silently switch to another one.

```typescript
await harness.setModelProvider({
  name: "Ollama",
  api: "chat-completions",
  baseUrl: "http://127.0.0.1:11434/v1",
});
const selectedModel = { provider: "Ollama", name: installedModelId };
```

```rust,ignore
harness.set_model_provider(
    ModelProvider::chat_completions("Ollama")
        .base_url("http://127.0.0.1:11434/v1")
).await?;
let selected_model = Model::new("Ollama", installed_model_id);
```

Use the actual endpoint for vLLM or another compatible server. Anthropic uses
`api: "anthropic"` / `ModelProvider::anthropic(...)`. Static secrets use the
platform secret store; memory-only credentials must be resupplied after restart.
For custom proxies and short-lived JWTs, see [provider auth](PROVIDER-AUTH.md).

## 3. Register tools, create an agent, and stream

The starter already registers `game.show_preview`. Its callback validates HTML
and forwards it to a separate isolated preview—not to the privileged app UI.
For your own functions use `harness.registerTools(...)` or
`harness.register_tools(...)`; the [visual guide](DESKTOP-QUICKSTART.html#agent)
shows both signatures. Names in an agent's tool list must already be registered.

**TypeScript:**

```typescript
const builder = harness.createAgent({
  name: "builder",
  instructions: "Build self-contained HTML games. Use game.show_preview.",
  tools: ["game.show_preview"],
  defaultModel: selectedModel,
});
const session = await builder.newSession(); // Optional model override here.
// Save session.reference() in your application's project record.
const run = await session.send("Build a neon Snake game.");
for await (const item of run.events()) {
  if (item.event.type === "assistant_delta") {
    // Pass text and attempt_id to your UI; keep retried attempts separate.
    console.log(item.event.data.text);
  }
}
const result = await run.result();
// An interrupted result needs approval or an answer, not a new duplicate run.
```

**Rust:**

```rust,ignore
use futures_util::StreamExt;
use openworker_sdk::Agent;
let builder = harness.create_agent(
    Agent::new("builder")
        .instructions("Build self-contained HTML games. Use game.show_preview.")
        .tool("game.show_preview")
        .default_model(selected_model)
).await?;
let session = builder.new_session().await?;
// Save session.reference() in your application's project record.
let run = session.send("Build a neon Snake game.").await?;
let mut events = run.events();
while let Some(event) = events.next().await {
    let event = event?;
    // Forward the event to your UI; do not log sensitive payloads by default.
}
let result = run.result().await?;
```

The starter routes approvals/questions to its UI. Continue the same session using
the typed response methods. On restart, re-register callback handlers and use
`resumeSession(reference)` / `resume_session(reference)`. Resume does not replay a
previous action. Closing an event iterator is not cancellation: wire Stop to the
session cancellation method. Shut down the harness when the app exits.

## 4. Build your app

From either generated app directory:

```sh
npm run package
```

Build Windows packages on Windows and Mac packages on macOS. The generated app
includes the native helper; end users do not need a Rust or Python installation.
Review signing/notarization, Windows runtime dependencies and clean-machine
installation before distribution. Packaging is not a claim of release certification.

## Next steps

- [MCP and native tools](../../harness/tools-sdk/README.md): expose only each
  agent's selected tools. Host callbacks do not move into a sandbox automatically.
- [NVIDIA OpenShell](../../deploy/local/README.md): Linux sandbox execution with
  explicit filesystem/network policy; Docker/OpenShell are additional prerequisites.
- [Approvals and policy](APP-POLICY-CONTRACT.md): auto-approval review is separate
  from the working model, and cannot override hard resource restrictions.
- [Storage and teams](SDK-STORAGE.md): SQLite or PostgreSQL through the SDK.
- [Server deployment](DEVELOPER-GETTING-STARTED.md): REST/SSE and independently
  scheduled workers. This is a separate surface, not a TypeScript SDK REST mode.
