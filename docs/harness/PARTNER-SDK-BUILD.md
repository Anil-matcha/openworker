# Build a custom Rust harness and partner SDK

Development tooling. This builds a wrapper crate and a companion executable from
an existing trusted Rust tool crate. It does not fork the OpenWorker runtime.

## Prerequisites

- Node.js 20+ and Cargo/Rust 1.96, with the native SDK's build dependencies.
- A checkout containing `harness/harness-sdk` and `harness/tools-sdk`.
- Your library crate implements the Tools SDK and exports this function:

```rust,ignore
pub fn register(registry: &mut openworker_tools::ToolRegistry) -> anyhow::Result<()> {
    registry.register(MyTool)?;
    Ok(())
}
```

For this first generator, the tool crate must use a **path dependency** on
`openworker-tools` from that same checkout. Mixing a Git/registry copy and a path
copy creates different Rust crate identities even if their version strings match.
The generator rejects that mismatch instead of producing confusing ToolRegistry
type errors. Portable Git/registry source packaging is a later extension.

Cargo build scripts/procedural macros can execute during compilation. Only build
trusted partner tools; this script is not an untrusted-code sandbox.

## One command

From the OpenWorker checkout:

```sh
node harness/partner/build-sdk.mjs \
  --name example \
  --tools-crate /absolute/path/to/example-tools \
  --output-dir /absolute/path/to/partner-project/generated/example
```

Optional `--sdk-root /absolute/path/to/openworker/harness` selects another SDK
checkout. `--generate-only` emits source without compiling; build-info explicitly
records `built: false`. The default command compiles both generated crates and
copies the executable into `bin`. Dependency resolution starts from the SDK's
Cargo.lock, preserves compatible pins, adds the generated/partner packages, and
verifies a locked rebuild. Unset CARGO_BUILD_TARGET: native builds only in
this milestone. The SDK rust-toolchain.toml is copied into the generated workspace.

Existing output paths (including links) are refused. To update, choose a new
versioned output directory. Failures preserve a staging directory for diagnosis;
the generator does not overwrite your tools or an older working package. A
build-info.json with `built: true` is written last as the completion marker.
Each workspace uses a unique intermediate Cargo binary name to avoid mixing
artifacts across concurrent builds sharing a Cargo target cache; the installed
`bin/example-harness` name stays stable. Build-info records the intermediate name.

```text
generated/example/
  sdk/                  example-sdk Rust library source
  runtime/              example-harness executable entry point
  bin/example-harness     compiled host-specific runtime (.exe on Windows)
  Cargo.toml
  Cargo.lock
  rust-toolchain.toml
  build-info.json
  OPENWORKER-LICENSE
  README.md
```

The wrapper and executable use the **same registry factory** and original tool
crate. Agent definitions still choose qualified tool names explicitly. No generated
agent gets all tools automatically; no approval or policy defaults are bypassed.

## Use from Rust

Add a dependency on the generated SDK directory:

```toml
[dependencies]
example-sdk = { path = "generated/example/sdk" }
tokio = { version = "1", features = ["full"] }
```

Inside a Tokio async application:

```rust,ignore
use example_sdk::{agents::Agent, Deployment};

let mut config = example_sdk::config(state_dir, &package_dir);
config.agents = vec![Agent::new("assistant")
    .instructions("Help the user with their approved tasks.")
    .tool("example.web_search")]; // A tool registered by your crate.

let harness = example_sdk::start(config, Deployment::Subprocess).await?;
// Or Deployment::Embedded: the same tool implementations run in this application.

// Continue with normal model connections, sessions, approvals and teams.
harness.shutdown().await?;
```

Use absolute state/package paths. `package_dir` contains the built `bin` directory.
The helper executable is needed even when embedding. OpenShell is the default;
installation and Docker provisioning are separate. Native Rust tools remain
trusted host code: placing other tools in a sandbox does not isolate them.

Configure SQLite/PostgreSQL and telemetry on the returned HostConfig as usual;
PostgreSQL migration remains explicit. Supply model keys through model connection
APIs, not agent instructions, generated files or command arguments. The wrapper
does not create credentials or a separate storage/permission implementation.

## Use from TypeScript

Point `@openworker/harness` at the generated binary:

```typescript
const harness = await Harness.start({
  executable: '/absolute/path/to/generated/example/bin/example-harness',
  stateDir: '/absolute/path/to/private-state',
  agents: [{
    id: 'assistant',
    instructions: 'Help the user with their approved tasks.',
    tools: ['example.web_search'],
  }],
});
```

The tool above still executes as Rust-native code in the child. A TypeScript app
does not need to reimplement it or convert it to MCP. TypeScript-authored tools
continue to use MCP. See the [TypeScript SDK guide](../../harness/typescript-sdk/README.md).

## Distribution limits

This first milestone generates a **source/development workspace**, not a published
SDK or relocatable source archive. Its relative path dependencies reference your
existing tools and SDK checkouts. Preserve that layout when checking it into a
partner workspace; dependent applications keep their own Cargo.lock.

The compiled runtime can run without those source directories. Match its OS/CPU
and required system libraries. Build-info records the executable checksum, lock
hash and available source revision information, not a signed provenance guarantee.
Review your tool and dependency licenses before distributing; this does not create
a complete SBOM/notice bundle, signed installer, cross-compiler or updater.
The upstream OpenWorker license is included as OPENWORKER-LICENSE; retain it with
the runtime and add your tools' and other dependencies' required notices.

The Agent/Session/send facade is supported by the SDK. This generator packages
that SDK with your registry; it does not move arbitrary native tools into a sandbox
or turn a library into an executable automatically. See the
[release checklist](RELEASE-CHECKLIST.md) for distribution gates.

## Tests

```sh
node --test harness/partner/build-sdk.test.mjs
# Linux, real builds and executions, no live-provider secrets:
npm --prefix harness/typescript-sdk ci
npm --prefix harness/typescript-sdk run build
node --test harness/partner/build-sdk.integration.mjs
```

The integration fixture builds an external tools crate, compiles a separate Rust
consumer, exercises embedded/subprocess approvals and effects, then relocates the
binary and calls its native tool through TypeScript with the original tool source
path absent. All model responses in this fixture are scripted.
