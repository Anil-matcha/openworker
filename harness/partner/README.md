# Custom applications and tool packages

The normal desktop integration uses the [Rust SDK](../harness-sdk/README.md) or
[TypeScript SDK](../typescript-sdk/README.md). Begin with the
[QuickStart](../../docs/harness/QUICKSTART.md).

Use this directory when your app needs a custom executable with linked Rust tools,
or when it implements the private process protocol directly.

- [Build a custom SDK and host](../../docs/harness/PARTNER-SDK-BUILD.md):
  `build-sdk.mjs` generates a wrapper crate and executable sharing one registry.
- [Native tool example](../examples/native-tools-runtime/README.md):
  notification, device and optional computer-use crates.
- [SDK protocol](../../docs/harness/AGENT-RUN-PROTOCOL.md): app/agent/session/run API.
- [Runtime protocol](PROTOCOL.md): lower-level coworker process integration.
- [Provider auth](../../docs/harness/PROVIDER-AUTH.md): access tokens, callbacks,
  proactive rotation and restart handling.
- [Model connections](MODEL-CONNECTIONS.md), [policy](POLICY.md) and
  [computer-use controls](COMPUTER-USE.md).

The old application-specific Linux partner kit is not distributed here.
Lantern and Luma are not part of this release candidate; reusable tool crates and
direct-stdio regression tests remain as independent examples/tests.
