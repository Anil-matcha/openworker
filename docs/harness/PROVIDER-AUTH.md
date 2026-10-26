# Provider proxies: access tokens and refresh

OpenWorker can call ExampleApp's AWS proxy using the Chat Completions API. ExampleApp
owns device registration, authentication, abuse controls and metering. OpenWorker
needs only the proxy URL, model ID and a short-lived bearer **access token**.
No email login or OpenRouter key is required by the harness. Keep refresh tokens
and device credentials inside ExampleApp; never send them to OpenWorker.

## TypeScript: register the provider

Run this in the desktop application's trusted Node process, not its webview.
`appAuth` below represents ExampleApp's existing authentication client, not an
OpenWorker helper. Configure the actual proxy base URL; the harness appends
`/chat/completions`.

```typescript
import { Harness } from "@openworker/harness";

const harness = await Harness.start();

await harness.setModelProvider({
  name: "ExampleApp",
  api: "chat-completions",
  baseUrl: "https://YOUR-PROVIDER-PROXY/v1",
  auth: {
    getToken: async ({ reason, signal }) => {
      // missing: no token is held (including after a child restart).
      // expiring: the current token expires within 60 seconds.
      // rejected: the proxy rejected an HTTP request with 401.
      // A rejected token must be replaced, not returned from the same cache.
      const token = await appAuth.getAccessToken({
        forceRefresh: reason !== "missing",
        signal,
      });
      return {
        accessToken: token.accessToken,
        expiresAt: token.expiresAt, // Unix time in SECONDS, not milliseconds.
      };
    },
  },
});
```

The callback executes in ExampleApp. The Rust child requests it over the private
stdio control channel; it is not an agent tool and does not enter the agent's
conversation, tool inventory or approval flow. Tokens are held in memory only.
Do not combine `auth` with static `credentials` on the same provider.

Agents select it with the normal model configuration:

```typescript
const agent = harness.createAgent({
  name: "assistant",
  instructions: "Help the user with their daily workflows.",
  tools: ["example.web_search"], // Register this tool separately as usual.
  defaultModel: { provider: "ExampleApp", name: proxyModelId },
});
const session = await agent.newSession();
const run = await session.send("Help me plan my day.");
```

## Proactive refresh: recommended alongside the callback

ExampleApp can refresh a 15-minute token before it expires—for example, around minute
13—and supply the replacement immediately. Prefer scheduling against the issuer's
actual expiry rather than assuming every token lasts exactly 15 minutes.

```typescript
// Call whenever ExampleApp's authentication layer obtains a fresh access token,
// including immediately after the initial device connection.
await harness.updateProviderCredentials("ExampleApp", {
  accessToken: newAccessToken,
  expiresAt: expiresAtUnixSeconds,
});
```

This updates the provider's in-memory credential for subsequent requests. It does
not recreate agents/sessions, change their model identity, or cancel open streams.
A proactive update wins over an older pending refresh callback. Serialize
proactive updates in ExampleApp so an older refresh result is not pushed after a newer
one. Await the update acknowledgement before treating it as installed.

For push-only authentication, register `auth: {}` and push the initial token before
creating a session. No automatic refresh occurs without `getToken`. With the
callback configured, it is a fallback for startup, expiry and HTTP 401—not a
requirement to repeatedly refresh on every model request.

## Rust: embedded or SDK-managed child

The same API works in both deployments. Callback code stays in the application;
it need not be compiled into a custom child executable.

```rust,ignore
use openworker_sdk::{AccessToken, Error, ModelProvider};

let auth = example_auth.clone();
harness.set_model_provider(
    ModelProvider::chat_completions("ExampleApp")
        .base_url(proxy_base_url)
        .refresh_access_token(move |reason| {
            let auth = auth.clone();
            async move {
                let token = auth.get_access_token(reason).await
                    .map_err(|_| Error::InvalidInput("ExampleApp authentication required".into()))?;
                AccessToken::new(token.access_token, token.expires_at)
                    .map_err(|_| Error::InvalidInput("Invalid access token or expiry".into()))
            }
        })
).await?;

// Proactive rotation, with expiry expressed as Unix seconds:
harness.update_provider_credentials(
    "ExampleApp",
    AccessToken::new(new_access_token, expires_at_unix_seconds)?,
).await?;
```

For push-only Rust configuration, use `.access_tokens()` instead of
`.refresh_access_token(...)`. Supply the initial token before creating a session.
The Rust authentication future must be cancellation-safe: the SDK may drop it
when a proactive update wins or the request is cancelled.

## Failure, concurrency and restart behavior

- Refreshes are single-flight per provider within one harness process. Separate
  harness instances do not coordinate refreshes; ExampleApp should share/cache tokens
  in its authentication layer if needed.
- The harness asks for a fresh token within 60 seconds of expiry. Callback results
  must have more than 60 seconds remaining. It uses the supplied expiry metadata;
  it does not verify JWT signatures or extend a JWT's lifetime.
- An HTTP 401 rejection permits one refresh and one retry of that model request.
  A second rejection fails the run. HTTP 403, network failures and errors inside a
  successful streaming response do not trigger this authentication retry.
- Refresh callbacks have a 30-second deadline. Failure is sanitized as provider
  authentication failure, with a five-second refresh-failure cooldown to avoid
  stampedes. Proactive updates clear that cooldown.
- If authentication cannot recover, the current run fails; it is **not parked for
  automatic replay**. The durable session remains available. Show an authentication
  prompt, update credentials, then explicitly continue in that session. Do not
  blindly replay a whole run that may already have performed tools.
- After a managed child restart, the SDK rebinds the callback automatically. The
  child has no saved access token, so it obtains one again through the callback.
  Push-only apps must resupply it. After a full application restart, re-register
  provider authentication and callbacks before resuming work. Authentication mode
  persists, so missing credentials do not silently become anonymous requests.
- The proxy authenticates at request start. Token expiry or rotation does not
  terminate an accepted stream in the harness. ExampleApp must likewise avoid cutting
  accepted streams off merely because their token later expires. Keeping the old
  JWT valid until its original expiry is normally sufficient; any extra overlap
  or revocation rules belong to ExampleApp's proxy.
- Use HTTPS outside loopback development. Endpoints are identity-pinned; token
  updates cannot change the provider URL. Redirects are disabled. Never put tokens
  in URLs, model prompts, tool arguments, logs or telemetry.

## Direct private-stdio clients

SDKs wrap these operations; a direct ExampleApp integration can implement the same
contract using the SDK host's `harness-stdio` entry point, not the older bare
runtime `serve --stdio` profile. Check
`initialize.capabilities.provider_access_tokens` first.

1. `provider/set`: `{name, api:"chat-completions", base_url, access_token_auth:true}`.
2. `provider/auth/register`: `{name, owner, refresh:true}`. Use one stable opaque
   owner ID for this client instance; re-register it on child restart.
3. Proactive `provider/auth/update`: `{name, access_token, expires_at}` returns
   `{updated:true}`. This is a normal acknowledged request.
4. Receive `application/event` with `kind:"provider_auth"`, `owner`, `provider`,
   `invocation_id` and `reason` (`missing`, `expiring` or `rejected`).
5. Reply with a JSON-RPC **notification**, method `provider/auth/result`, params
   `{owner, invocation_id, access_token, expires_at}` or
   `{owner, invocation_id, error:true}`. It uses the reserved control lane so a
   pending run wait cannot block refresh. Never include raw exception text.
6. `provider_auth_cancel` signals that the invocation is no longer needed.
   Expired, duplicate or wrong-owner replies cannot update credentials.

## Run the synthetic acceptance tests

```sh
cd harness
cargo test -p openworker-runtime --lib provider_auth::tests
cargo test --release -p openworker-sdk --features test-support --test provider_auth
cargo build --release -p openworker-sdk --bin openworker-harness
cd typescript-sdk
OW_TS_TEST_HOST=/absolute/path/to/openworker-harness npm run test:provider-auth
```

These tests use local HTTP fixtures and synthetic tokens. They do not verify
ExampleApp's actual AWS endpoint, device-registration flow or production JWT issuer.
Rebuild the native executable alongside the SDK when adopting this feature.
