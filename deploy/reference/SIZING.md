# Bounded local load results and sizing guidance

Qualification date: 2026-10-12 (local). These are **worker/store fixture results**,
not production capacity promises, HTTP/SSE load tests, or live-model benchmarks.
Use them to choose a starting experiment, not an instance-count SLA.

## What ran

- Release-profile Linux ARM64 binaries, locked dependencies, native scripted tool
  fixture and real PostgreSQL. No paid model calls or AWS resources.
- Worker/test container: **2 CPU quota / 3 GiB limit in total**, not per worker.
  Fresh PostgreSQL container: **1 CPU / 1 GiB**. Shared local Docker VM, not
  independent machines or an otherwise idle production host.
- 250ms worker polling, 30s leases, 5s DB deadlines. One burst of 24 fresh sessions
  per short-tool run; 16 per longer-tool run. Two repetitions of each case.
- Each turn appends/fsyncs one uniquely identified native effect, then waits at
  least 250ms or 1000ms for a test-controlled gate. Explicit bypass in isolated
  fixture workspaces; **no OS sandbox**. OpenShell correctness was tested separately.
- Session seeding and expiry of the direct-protocol fixture's 3s seed leases happen
  before the measured interval. Measurements include burst admission, worker
  startup, queueing and completion. They are not steady-state warm-session rates.
- Queue/end-to-end timings use PostgreSQL audit timestamps. RSS/CPU and active
  sessions are sampled every 100ms; short peaks can be missed. RSS is the sampled
  **sum across worker processes**, includes shared mappings, and excludes the
  database, API server, tools in other processes, filesystem cache and sandboxes.

All **224 turns/effects** completed in the final ten-run matrix with zero duplicate
effects or failed turns. Actual session/turn/call identities and contiguous event
cursors were checked, rather than inferring correctness from a throughput counter.

## Results

Ranges are the two observed trial values, not confidence intervals. p95 is a
per-trial nearest-rank percentile of a small burst, not a production tail estimate.

| Workers × slots each | Sessions | Tool wait | Completed turns/s | End-to-end p95 | Peak sum worker RSS |
|---|---:|---:|---:|---:|---:|
| 1 × 1 | 24 | 250ms | 1.42–1.54 | 14.90–16.03s | 147MiB |
| 1 × 4 | 24 | 250ms | 4.63–4.91 | 4.66–4.96s | 238–275MiB |
| 2 × 2 | 24 | 250ms | 4.82–5.04 | 4.46–4.88s | 311–356MiB |
| 2 × 4 | 24 | 250ms | 6.77–6.98 | 3.36–3.45s | 442–449MiB |
| 2 × 2 | 16 | 1000ms | 2.54–2.73 | 5.78–6.22s | 268–346MiB |

Short-tool runs consumed 3.88–4.19 worker CPU-seconds for 24 turns. Observed active
sessions reached but never exceeded configured slots. Idle drain at the end of
these cases took 0.07–0.51s across the worker processes; this is **not** the drain
time for an active long-running model/tool. Separate gated tests verify finishing
active work, timeout interruption, controls and renewed leases.

Fresh PostgreSQL's measured cgroup peak was about **114 MiB**, with zero OOMs in
the final matrix. This tiny retained dataset does not establish a production DB
memory requirement or include realistic history/retention/query workloads.

## Important failed experiment

The first optimized matrix used our long-lived 1 GiB regression database. It
passed smaller cases, then PostgreSQL was OOM-killed during the eight-slot case
at 2026-10-11 19:49:42 UTC. Its checkpointer was killed, other DB connections were
terminated, and PostgreSQL recovered. The cgroup OOM counter increased from 1 to 2.

That database had accumulated regression/diagnostic state and surrounding test
activity. Repeating on a **fresh isolated database at the same CPU/memory limits**
passed all cases. We cannot attribute the initial OOM solely to eight worker slots,
nor dismiss it as harmless. Keep retention/catalog growth, checkpoint activity,
cache and memory headroom in the deployment budget. Do not size PostgreSQL from
the clean fixture's 114 MiB peak. No timeout or safety rule was relaxed to pass.

An earlier development-binary measurement was deliberately stopped and excluded
from this table. Performance must be measured with the intended optimized build.

## How to size an application

1. **Separate three budgets:** API/stream connections, active harness workers,
   and sandbox/tool compute. More REST replicas do not automatically create
   worker or sandbox capacity. This test did not measure API/SSE scaling.
2. **Start with a small worker experiment.** Two workers with two slots each is a
   reasonable *next evaluation configuration* from these results: similar observed
   throughput to one four-slot worker, with more process-level failure isolation
   and more aggregate memory. It is not a guarantee for another workload.
3. **Measure actual active-turn duration.** As a first-order planning estimate,
   required active slots ≈ arrival rate × average active-turn seconds, then add
   measured headroom for bursts and variance. A hypothetical 1 turn/s taking 10s
   needs roughly 10 busy slots before headroom—not the rates in this fixture.
   Approvals/questions park and release slots; their total session count is not
   active concurrency. Long tools still occupy slots while awaiting their result.
4. **Measure memory per worker with real histories and outputs.** Set requests
   and limits with headroom above that high-water mark. Do not divide aggregate
   RSS by worker count and assume it is a per-worker bound. The chart's example
   resources are not customer sizing advice. Native tools share process memory;
   sandbox/MCP processes need their own budgets and isolation decisions.
5. **Budget database connections and retained data.** Roughly account for one
   connection per worker slot, API connections, optional observation connections,
   administration and headroom; measure the actual deployment. Sample queue age,
   storage latency, DB memory, connection use and checkpoint/WAL behavior. Do not
   mask overload by increasing DB timeouts without revisiting lease bounds.
6. **Bound admission above the harness.** Per-session queue limits and exact
   idempotent retries are tested (including a 12-producer/four-item burst), but
   this is not a global/tenant quota or automatic scaling policy. Applications
   still need tenant quotas, aggregate backlog limits and overload UX.
7. **Tune one dimension at a time.** Increase slots/replicas only while queue age
   improves without unacceptable CPU, memory, DB latency or provider throttling.
   Account for replacement capacity and [drain budgets](DRAINING.md), especially
   when old version-pinned sessions still need an old compatible worker pool.

Before production claims, repeat with the real coworker/tools/models and sandbox
topology, warm/long-lived sessions, larger retained histories, sustained traffic,
concurrent SSE clients, provider throttling, and node/storage failures. Monitor
unknown effects rather than treating retries as proof of correctness. We have
not measured fairness under an indefinitely busy session, >8 slots, multi-AZ or
physical tenant isolation in this matrix.

## Reproduce

Use a clean, dedicated local PostgreSQL test instance. Record its image, limits,
initial OOM counters and the worker container's CPU/memory limits. Do not run
other fault/regression suites against it during the matrix.

```sh
# harness/; supply OW_PG_TEST_URL securely for the isolated database.
OW_RUN_LOAD=1 OW_CONCURRENCY_REPORT_DIR=/absolute/private/reports \
  cargo test --release --locked -p openworker-store-postgres \
  --features test-support --test worker_recovery load::bounded_load_matrix \
  -- --include-ignored --test-threads=1 --nocapture
```

The load test returns early without `OW_RUN_LOAD=1`; a generic test-suite pass is
not evidence that the matrix ran. Each completed case stops its children and
drops only its own generated schema. Failed cases may retain diagnostic schemas;
inspect exact ownership before removal, never prune the database broadly.

Final evidence on the qualification host:
`.ow-stack/drain-load-20261012/drain-load-reports/isolated-release/` (10 JSON files).
Development and initial failed optimized-attempt evidence are kept separately.
