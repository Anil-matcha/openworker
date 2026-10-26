# Durable session tool approvals

Ask mode offers Allow once, Allow for this session, and Deny.
The session choice covers the entire tool, including all `computer.use` actions,
with different valid arguments. It is not a global or cross-session permission.

An explicit valid whole-tool session grant skips repeated prompts and reviewer
evaluation. Capability leases, schemas, sandbox enforcement and crash rules still
apply. The grant is stored atomically with the originating human decision; trusted
callers can list or revoke it. Revocation is serialized against execution start.
This document describes the Rust harness; it does not change Python/Desktop policy.

## Contract

`interaction/respond` accepts decision `session` in addition to `once` and `deny`
for an unanswered approval. Questions/compaction cannot mint grants. Persist the
grant and response in one SQLite transaction. Repeat responses are idempotent;
replaying the old decision after revocation cannot resurrect the grant.

`permissions/list` and `permissions/revoke` are app-only methods with session ID.
Revoke takes the exact grant ID, is idempotent, and never affects another session.
No model-callable tool grants itself authority. Never load grants from prompts,
summaries, tool output, coworker bundles or arbitrary client-supplied grant objects.

Bind session/coworker implicitly through its store row, and explicitly pin alias,
server + remote tool (fully qualified for v3), execution/bundle digest, catalog
digest, classification-policy digest and resource-policy digest. Existing strict
session binding checks may require a fresh session when code/policy changes; do
not silently refresh an old grant to changed authority. This initial scope also
supports legacy exact server/tool routes and runtime-internal read tools.

Revocation wins if it commits before the durable tool-start checkpoint. A queued
grant-authorized call then gets a NEW approval ID; the old answered interaction
stays immutable. Work already checkpointed as started may finish; revoke is not
rollback. A tool whose started result became uncertain is never automatically
replayed merely because its grant survives restart.

For `computer.use`, the persisted grant covers observe/click/type/scroll/keypress,
but screen sharing and input capability leases stay transient and independently
revocable. Restart restores approval metadata, NOT screen access or screenshots.
Revoking a tool grant causes future calls to ask again; stopping screen access
immediately revokes the separate capability and cancels the turn in the application.

## Verification

Regression coverage is in `harness/runtime/tests/session_grants.rs`, runtime policy
tests and the SDK integration suites. Qualify real desktop input separately with
explicit consent; a stored tool approval does not restore screen access.
