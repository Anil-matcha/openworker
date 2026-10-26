# Task Desk AWS experiment

This is an **experimental account-scoped deployment/qualification reference**, not
a general-purpose production installer. Use a dedicated test account and an
explicitly approved role. These scripts create billable resources and include
cleanup operations. Review the generated plan and resource scope before execution.

```sh
export OW_AWS_ACCOUNT_ID=123456789012             # Your dedicated test account
export OW_AWS_ROLE_ARN=arn:aws:iam::123456789012:role/OpenWorkerExperiment
export OW_AWS_REGION=us-west-2
export OW_AWS_BUDGET_EMAIL=cloud-ops@example.com
```

No account or recipient is selected implicitly. The existing fixed experiment
resource prefix is `ow-taskdesk-20261012`; do not run concurrent experiments with
that prefix in one account. Cost alerts do not impose a hard spending cap.

Start with the [developer guide](../../docs/harness/DEVELOPER-GETTING-STARTED.md)
for application integration or your own infrastructure. Internal account-specific
qualification records are intentionally not part of this source distribution.
Preserve previous `.ow-aws` evidence before an explicitly approved fresh experiment;
do not regenerate an expired plan or reuse deleted infrastructure IDs.

## Architecture and cost boundaries

- CloudFormation: dedicated VPC, two public infrastructure subnets and two private
  database subnets; EKS 1.36 on two bounded t4g.large Linux ARM64 nodes; private,
  encrypted RDS PostgreSQL 16.15; private S3 and three ECR repositories.
- Public node addresses provide outbound access without NAT charges. No inbound
  SSH or public application endpoint. EKS's public control endpoint is limited
  to the operator's discovered IPv4 /32, also protected by IAM; private endpoint
  enabled. Application access is an authenticated Kubernetes port-forward.
- Independent pinned OpenShell 0.1.3 chart plus Agent Sandbox 1.0.6. AWS VPC CNI
  1.22.4 enforces policies; controller policies are installed before switching
  to strict mode and admitting sandbox work. One network-policy engine, no Calico
  installed on this EKS cluster. Real deny/allow checks are mandatory.
- Separate harness API/worker deployments, optional one-replica Task Desk BFF.
  The same native loop/store/protocol is used; no Python runtime in application
  images. The runner executable is the exact Linux binary the harness pins.
- AWS Pod Identity supplies the API's narrowly scoped S3 role. No permanent AWS
  access key in a pod. EBS CSI has its own role. Workers alone receive the temporary
  OpenAI Secret for the explicit live test; neither browser nor sandbox receives it.
  RDS uses a managed Secrets Manager master credential in this disposable test;
  production should provision a least-privilege database user separately.
- $100 experiment authorization; separate $100 Oregon monthly budget alerts at
  50/80/100% to the supplied owner email. No cost-allocation tags were activated,
  so this conservatively counts all Oregon spend. Alerts are delayed, **not a
  hard billing cap**. Capacity is fixed at two nodes; no autoscaler or NAT gateway.

The separate guard stack runs cleanup in AWS every five minutes after a fixed
24-hour deadline, independent of the laptop. It verifies the main stack's exact
ownership tag/name, empties only the experiment bucket, requests stack deletion,
and removes only detached EBS volumes with its exact Project tag. Attached owned
volumes keep the schedule active until they detach. No caller-supplied target or
blanket account cleanup. When stack and volumes are gone the schedule disables
itself; remove the guard/budget/log resources after verification.

Cleanup's IAM policy is deletion-only and mostly resource-scoped. Some EC2
CloudFormation cleanup operations require regional wildcard resources; the guard's
code limits them to its owned stack. It is a trusted infrastructure component,
never exposed to the agent or application. IAM signing/release, policy refinement,
and independent security review remain production follow-ups.

## Reproduce the approved experiment

Prerequisites: existing authorized CLI identity able to assume the member role,
AWS CLI, Node 20.19+, Docker, kubectl, Helm 3.22.0, OpenSSL and the pinned OpenShell
CLI for diagnostics. `OW_HELM` selects the qualified Helm executable. Scripts
assert the target account, use temporary credentials in process memory, and never
modify AWS CLI profiles. All generated state is gitignored `.ow-aws/` (0700;
private files 0600). Keep this directory until teardown is verified.

```sh
node deploy/aws/inventory.mjs
node deploy/aws/preflight.mjs
node deploy/aws/cost-preflight.mjs
node deploy/aws/experiment.mjs plan
node deploy/aws/experiment.mjs guard
node deploy/aws/experiment.mjs status
node deploy/aws/verify-guard.mjs
node deploy/aws/experiment.mjs launch
```

Wait for the guard before launch and the main stack's CREATE_COMPLETE before
workload setup, including healthy initial DNS/storage add-ons. The prerequisite
script now enforces this gate.
`plan` resolves/persists available add-on/PG versions and validates both templates;
it does not renew the deadline on rerun. The guard must remain enabled. This
experiment deliberately pins a specific account/name; don't edit it into a
generic installer and point it at existing customer resources without review.

Build the native harness per `../helm/README.md` with
`--build-arg COWORKER_BUNDLE=harness/examples/task-desk`, its matching runner image,
and the app using `harness/task-desk/Dockerfile`. Source/runtime images contain no
credentials. This qualification used Linux ARM64 native binaries from the cached
build, not a cold release/SBOM/signing pipeline. `images.mjs` publishes through a
private temporary Docker auth directory (removed afterward), records immutable
digests, and refuses to replace an existing immutable tag with different content.

```sh
node deploy/aws/images.mjs qualification-v1
OW_HELM=/path/to/helm node deploy/aws/kubernetes.mjs prerequisites
node deploy/aws/probe-network.mjs
OW_HELM=/path/to/helm node deploy/aws/kubernetes.mjs openshell
OW_HELM=/path/to/helm node deploy/aws/kubernetes.mjs configure
OW_HELM=/path/to/helm node deploy/aws/kubernetes.mjs bootstrap
OW_HELM=/path/to/helm node deploy/aws/kubernetes.mjs app
kubectl --kubeconfig .ow-aws/kubeconfig --context ow-taskdesk-20261012 -n ow-app port-forward deployment/ow-openworker-taskdesk 54351:54350 --address 127.0.0.1
```

Open `http://127.0.0.1:54351`. The separate workspace access key stays in
`.ow-aws/access`. It is not the API/operator/model key. The BFF binds loopback
inside its pod; there is no Service/Ingress for it. Only an authorized Kubernetes
operator can establish the private tunnel. Public customer deployment needs
separate app identity/TLS ingress rather than exposing this port.

`configure` is first-install only and refuses to stop a running app. Secrets are
not embedded in Helm values. Use intentional Helm upgrades afterward; credential
subPath mounts require rollout. The optional database-readiness init container
only probes connectivity with verified TLS, without the database password or SQL
mutations; it avoids racing strict CNI policy installation at process startup.

## Qualification

```sh
node --test harness/task-desk/server.test.mjs deploy/aws/cleanup.test.mjs deploy/aws/qualification.test.mjs deploy/recovery/backup.test.mjs
HELM=/path/to/helm node --test deploy/helm/chart.test.mjs
node deploy/aws/qualify-current.mjs
```

These deterministic-model tests use real infrastructure/tools. They check stable
creation IDs, two API nodes, complete API/worker pod replacement during approval,
contiguous event replay, actual sandbox write/read, S3 publication/download,
questions, cancellation, kernel denial and four concurrent sessions.

Prepare a separate immutable coworker variant for the operations drill. Keep the
base image manifest intact: `images.mjs` normally writes `images.json`.

```sh
cp .ow-aws/images.json .ow-aws/base-images.json
docker build -f deploy/aws/fixtures/variant.Dockerfile \
  -t openworker-harness:variant-20261012 deploy/aws/fixtures
node deploy/aws/images.mjs qualification-variant openworker-harness:variant-20261012
cp .ow-aws/images.json .ow-aws/variant-images.json
cp .ow-aws/base-images.json .ow-aws/images.json
node deploy/aws/qualify-operations.mjs
node deploy/aws/qualify-restore.mjs
node deploy/aws/qualify-telemetry.mjs
```

The operations drill deliberately removes/restores the original worker pool,
performs an active-tool rolling restart, rolls back API creation only, then
force-stops an exact disposable worker after a real effect starts. Never run it
against customer state. `--resume-crash` is an explicit fixture-only option after
the preceding five gates passed; it starts a new synthetic crash case, not a
retry of an uncertain tool. Compatible old/new pools remain until teardown.

The restore drill uses a new database and zero-worker inspection deployment;
the original S3 store is retained. Telemetry uses pinned loopback collector
sidecars and private debug evidence, not a public collector or hosted Grafana.
Apply telemetry last because this qualification overlay replaces API/worker pods.

For the optional live check, supply the previously authorized OpenAI key **on
stdin** to `node deploy/aws/qualify-live.mjs` through your approved secret manager.
It verifies model availability and deploys a separate live pool. Only two exact
checklist write/read approvals are allowed; unexpected tools fail the check.
No key goes into local state, arguments, Helm values, browser or sandbox.
The old `live-model.mjs`/browser helpers document the earlier 11 October flow;
do not use their in-place model promotion for current pinned session pools.

Browser acceptance is separate: sign in to the private tunnel; submit the file
fixture; reload at approval; inspect/allow that exact write; save/download the
response; reload and compare bytes. Record the actual checks and screenshot in
`current-ui-qualification.json`. The 12 October run used the interactive browser
tool, not the older hardcoded browser scripts. No new mobile-layout pass is claimed.

`current-{http,operations,restore,telemetry,ui,live}-qualification.json` plus
`network-proof.json`, `build-evidence.json` and image digests are private evidence.
After all required reports pass, run `node deploy/aws/finalize-qualification.mjs`.
It refuses incomplete evidence and records application qualification separately
from teardown. Failed attempts retain their state for inspection; use explicit
abort teardown if a gate cannot be completed. Never forge a success report to clean up.

## Earlier failure and recovery lessons

These lessons are from the 11 October run; its private evidence is retained
separately. The latest qualification has its own results and provisioning notes.

1. RDS publishes multi-root CA bundles. The native PG adapter initially read only
   the first root. It now validates/loads every root (256 KiB / 32 certificate
   bounds), rejecting empty, malformed or key-containing bundles. TLS and hostname
   verification remain mandatory. New tests passed on Mac/Linux, plus existing
   PG integration tests. An uncertain first migration was inspected with read-only
   verify-full `psql`: no schema existed. Its failed Job was removed only after
   recording that evidence; no database reset or blind migration replay.
2. The gateway needs inbound control traffic from supervisors as well as harness
   pods. The corrected policy admits supervisor-labelled pods in its namespace
   and harness namespace traffic on TCP 8080; it doesn't open workload egress.
3. OpenShell rolled back the initial failed sandbox and empty PVC. Authenticated
   NotFound and Kubernetes absence were recorded before an explicitly new test
   request (`v2`); the failed original receipt stayed in PostgreSQL.
4. The second sandbox's cold startup exceeded the harness's 120-second wait, but
   then became ready. New trusted CLI `environment-inspect` / `environment-reconcile`
   resolved the **same original** object, checking its ownership label, profile,
   image and admitted policy. No implicit re-creation. A missing original object
   fails reconciliation. These are trusted host/DB administration commands, not
   browser APIs or permission to reset customer state.

The diagnostic/reconciliation scripts are deliberately explicit, fixed-experiment
operations. Inspect original outcomes before retrying a failed Job. Don't delete
sandboxes/PVCs or use a fresh request ID to conceal an uncertain outcome.

## Finish and verify removal

```sh
node deploy/aws/teardown.mjs begin
# After the Lambda configuration update completes:
node deploy/aws/teardown.mjs invoke
node deploy/aws/teardown.mjs verify
# Repeat bounded inspection/invocation while deletion progresses.
node deploy/aws/teardown.mjs remove-guard
node deploy/aws/experiment.mjs status
```

Early teardown stops workers/removes the temporary model Secret and advances the
same guard's expiry to now. It deletes the **disposable** DB, S3 objects, images,
cluster and workspace disks; local code/evidence remain. Verify actual AWS
resource absence, not merely that DeleteStack returned success. Never remove the
guard while main resources or owned volumes remain. Billing can arrive late.
If qualification fails, use `node deploy/aws/teardown.mjs abort` instead of
`begin`; it invokes the same exact ownership-bounded cleanup without claiming
success, even if application-level cleanup is unavailable.

After the guard also disappears, run `node deploy/aws/verify-removed.mjs` for
read-only service-level absence checks, including cluster, database, bucket,
repositories, roles, cleanup resources, experiment budget, VPC, disks and compute.
It saves a private audit and fails on query errors or remaining resources.

Not claimed: multi-tenant isolation, SSO/public app access, HA RDS, full disaster recovery,
load capacity, long-lived credential/certificate rotation, Windows nodes,
production certification, or a generic AWS/Azure one-click installer. OpenShell's
Kubernetes path is still upstream experimental. This is a concrete integration
reference and recovery qualification, not a replacement for an operational review.
