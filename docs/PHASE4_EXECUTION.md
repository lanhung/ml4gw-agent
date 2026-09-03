# Phase 4 — scalable execution

Phase 4 adds the layer that decides *where* an already-validated task runs
and *whether it may run at all* given its expected cost. It changes nothing
about *what* runs: the plan, the adapters, the policy checks, the manifests,
and the fail-closed rules from Phases 0–3 are untouched.

## Honesty rule

Everything in this document has been exercised only with the in-process
executor and with unit tests that fake the scheduler binaries. **No HTCondor
pool and no Kubernetes cluster has run an agent job.** The HTCondor and
Kubernetes executors generate submissions and drive `condor_*` / `kubectl`
through fixed argument vectors, and the tests check those artifacts and
argument vectors; they do not prove that a real pool accepts them. A run on
a real scheduler, recorded like the Phase 1 acceptance runs, is the exit
test that is still open.

## Contracts (`ml4gw_agent.executors`)

| Piece | What it is |
|---|---|
| `ExecutorKind` | `local`, `htcondor`, `kubernetes` (implemented, argv-driven), `snakemake`, `law`, `triton` (planned; their probe states the upstream blocker). |
| `Executor` | `probe()`, `submit(job_id, work, run_dir, description)`, `poll(handle)`, `cancel(handle)`, `resume(handle)`; `require_available()` fails closed. |
| `JobHandle` | id, executor, status, submission time, checkpoint path, result, error; serialised into the manifest. |
| `RetryPolicy` | attempts and exponential backoff for submissions. |
| `ResultCache` / `cache_key` | SHA-256 over (skill, version, sorted parameters, adapter) so identical segments in one run are not recomputed. The cache is scoped to a single run because outcomes point at that run's artifacts. |
| `CommandRunner` | The one seam for subprocesses: argument vectors only, `shell=False`, faked in tests. |

### Local executor

`LocalExecutor` runs the adapter callable in-process, which is exactly what
the runtime did before Phase 4. It is the default and the only executor with
a completed end-to-end run.

### HTCondor executor

`HTCondorExecutor.submit` writes `jobs/<job>/job.sub` in the run directory
(one job per description: `executable = ml4gw-agent`, `arguments = run-plan
<saved plan> --mode ... --runs-dir ...`, `request_cpus/memory/gpus`,
`should_transfer_files = NO`, an explicit whitelisted `environment` line (IGWN pools forbid `getenv`), `accounting_group` from `ML4GW_CONDOR_*`, optional extra ClassAd lines),
submits with `condor_submit -terse`, parses the cluster id, polls with
`condor_q -json <cluster>` (JobStatus 1–7 mapped to the agent's `JobStatus`;
a non-zero `ExitCode` is a failure; an empty queue means done), and cancels
with `condor_rm`. Re-running a *saved plan* on the worker is deliberate: the
pool executes the validated DAG, never prompt text.

### Kubernetes executor

`KubernetesExecutor.submit` renders a `batch/v1` Job manifest (pinned image,
`command: ml4gw-agent`, `args: run-plan ...`, CPU/memory/GPU limits,
`backoffLimit: 0`), applies it with `kubectl apply -f`, polls `kubectl get
job -o json` (`succeeded`/`failed`/`active`), and deletes the job to cancel.
It refuses to run without `kubectl` on PATH and without a pinned image.

## Estimate and budget flow

```text
plan ──estimate_plan──▶ ResourceEstimate ──BudgetPolicy.check──▶ BudgetDecision
                                   │                                   │
                             select_executor                    allowed? else BLOCKED
                                   │                                   │
                              JobHandle(s) ◀──── AgentRuntime.run ◀────┘
```

`estimate_plan(plan, registry, EstimateConfig)` sums per-task costs from the
skill contracts' `resources` blocks and a runtime table measured on the
2026-09-03 acceptance runs (RTX 5000 Ada, cached strain):

| Skill | Measured basis |
|---|---|
| `data.fetch` | 5 s per detector from the astropy cache; uncached, 130 MB per detector at the node's measured 70 kB/s (about 31 min per file) |
| `aframe.detect` | 5 s per 128 s window |
| `amplfi.pe` | 15 s (20 000 samples plus sky map) |
| `buoy.analyze` | 40 s per event with cached models |
| Aframe background study | 100 s per 3900 s stretch (not a skill; recorded for scan planning) |
| other skills | contract estimate or a conservative default |

Windows longer than `segment_seconds` (default 4096 s, 64 s overlap) are
partitioned with `partition_scan`, and `n_segments` multiplies the per-step
costs. CPU-only execution scales GPU work by 20x (Buoy documents about 15
minutes per event on CPU versus 40 s on the GPU).

`BudgetPolicy` (defaults: 24 CPU h, 4 GPU h, 20 GB transfer, 6 h latency;
authorization required above 1 GPU h) is checked **before submission**. A
refusal blocks the run with the reasons in the manifest; a run above the
authorization threshold needs `--authorize-budget` (or
`BudgetPolicy(authorized=True)`).

`select_executor` picks `local` for single-segment work under two hours and a
batch executor for partitioned or long work when one is available; an
explicit preference wins if usable. The selection and its reason are
recorded.

## Manifest

`RunManifest.execution` (optional, so older manifests still validate) holds
the executor, the selection reason, the estimate, the budget, the decision,
and one handle per submitted job.

## Partitioned scans

`partition_scan(start, end, segment_seconds, overlap_seconds)` returns
abutting cores that cover `[start, end)` exactly once, each with a padded
data window for PSD and filter context. `merge_segment_outputs` keeps a
candidate only from the segment whose core contains it, merges
near-duplicates closer than `proximity_seconds` by keeping the louder one,
and reports missing segments and the coverage fraction instead of silently
returning a partial scan.

## CLI

```bash
ml4gw-agent estimate "Analyze GW150914" [--no-cache] [--no-gpu] [--max-gpu-hours H]
ml4gw-agent run "..." --executor local|htcondor|kubernetes --max-gpu-hours H [--authorize-budget]
```

`estimate` exits 3 when the budget would refuse the plan.

## Exit criteria (ROADMAP Phase 4)

- Short event analyses run locally or on one GPU: **yes** (all Phase 1
  acceptance runs went through `LocalExecutor`).
- Long scans partitioned and aggregated without duplicate or missing
  segments: **partitioning and merge implemented and property-tested; not yet
  driven end to end on a scheduler.**
- Budget and authorization policies enforced before submission: **yes**, in
  the runtime and the CLI.
- Real HTCondor / Kubernetes execution: **open**; needs a pool or cluster and
  a recorded acceptance run.
