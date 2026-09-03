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
argument vectors; they do not prove that a real pool accepts them. The
`ssh` executor below is likewise tested only against a fake transport: no
job has yet been driven over a real SSH connection from the test suite. A
run on a real scheduler or host, recorded like the Phase 1 acceptance runs,
is the exit test that is still open.

## Contracts (`ml4gw_agent.executors`)

| Piece | What it is |
|---|---|
| `ExecutorKind` | `local`, `htcondor`, `ssh` (implemented; argv-driven, fake-tested), `kubernetes` (implemented but deferred: no cluster), `snakemake`, `law`, `triton` (planned; their probe states the upstream blocker). |
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

**Deferred.** There is no cluster to run it on, so `executor_availability`
reports it as `deferred (no cluster available; the ssh executor stands in)`
followed by the probe result. The code stays in place for when a cluster
exists; nothing selects it automatically.

### SSH executor

`SSHExecutor` (`executors/ssh.py`) replaces the Kubernetes path for now: it
runs a saved plan on one remote host that already has the agent checked out
and its environment installed, for example the GPU node. Configuration comes
from the environment, never from the plan:

| Variable | Meaning | Default |
|---|---|---|
| `ML4GW_SSH_HOST` | host to connect to; unset means the executor is unavailable | — |
| `ML4GW_SSH_PORT` | SSH port | `22` |
| `ML4GW_SSH_USER` | login user | `root` |
| `ML4GW_SSH_PASSWORD` or `ML4GW_SSH_KEY` | password, or path to a private key; one is required | — |
| `ML4GW_SSH_REPO` | agent checkout on the host (`cd` target) | `~/ml4gw-agent` |
| `ML4GW_SSH_RUNS` | directory for job directories on the host | `~/ml4gw-runs` |
| `ML4GW_SSH_ENV` | shell snippet prefixed to every command (exports, `source`) | empty |
| `ML4GW_SSH_PYTHON` | command prefix for the agent CLI | `uv run` |

`submit` needs the same description as HTCondor (`plan_file`, `mode`,
`runs_dir`). It creates `<RUNS>/<job>/` on the host, copies the saved plan
there with sftp, and starts
`nohup <python> ml4gw-agent run-plan <plan> --mode <mode> --runs-dir <RUNS>/<job>/worker`
detached, with `stdout.log`, `stderr.log` and a `pid` file next to the
plan. The handle id is `<host>:<pid>`; the checkpoint `handle.json` records
the remote job directory and the local worker directory. `poll` checks
`kill -0 <pid>` and reads the status of the worker's `run_manifest.json`;
once the process is gone it copies the whole remote worker directory back
into the local run directory, so `submit_plan` finds `run_*/run_manifest.json`
exactly as it does for HTCondor, and the handle is final (`completed` only
when the worker manifest says so, otherwise `failed`). `cancel` sends
`kill`, then `kill -9`, and marks the handle cancelled; `resume` re-polls
from the checkpoint. Password and key never reach the manifest or the
remote command line: they are used only to open the paramiko session.

`SSHTransport` (paramiko: `run`, `put`, `get_tree`) is the one seam; the
tests substitute a fake that records commands and simulates a process that
is alive, then gone. **What is proven:** the command lines, the plan copy,
the running → completed / failed / cancelled transitions, checkpoint reuse,
and the copy-back that makes the worker manifest visible to `submit_plan`.
**What is not:** any real connection, paramiko error handling against a
live host, and the remote environment actually running the agent. Those
need a recorded acceptance run on the GPU node.

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

### Segmented submission of long scans

`submit_plan` splits a scan automatically when the plan's `data.fetch`
window is longer than `ExecutionPolicy.max_data_window_seconds` (4096 s), or
when the CLI is given `--segment-seconds`. Segmentation only applies to
requests made by GPS time, because only then is the window's position known
at submission time; a catalog or GraceDB name is resolved on the worker, and
`--segment-seconds` on such a request is an `ExecutorError` rather than a
silent single job. Everything else goes through the unchanged single-plan
path.

The split uses `partition_scan` with an 8 s overlap by default. For each
segment `segment_plan` deep-copies the plan and rewrites `data.fetch` to the
segment's padded data window (`gps_time` = data start, `window_seconds` =
data length, `event_offset_fraction` = 0), drops the `target_time` of
`aframe.detect` / `gwak.scan` so the scan covers the whole segment, and
appends a warning naming the segment. The budget is checked once for the
whole scan (per-segment estimate × number of segments); the segments are
then submitted as separate jobs under `submission_<plan>/segment_<i>/` with
plan ids `<plan>_s<i>`, waited for in order, and merged: `run_aframe`
candidate times and `run_gwak` top segments are passed through
`merge_segment_outputs`, so a candidate that falls inside an overlap is kept
once, from the segment whose core contains it. `segments.json` in the
submission directory records the segments, one submission per segment, the
merged candidates with `coverage_fraction` and `missing_segments`, the
failed segment indices, and the overall status: `completed` when every
segment completed, `partial` otherwise. A failed segment is reported, never
hidden behind a merged result.

**Proven by tests** (`tests/test_ssh_executor.py`, with a fake batch
executor that writes worker manifests): N segments submitted for a 1000 s
window, abutting cores that cover exactly the requested interval, no
duplicate candidates from the overlaps, one failed segment surfacing as
`partial` with coverage ≈ 0.75, automatic splitting above the policy limit
and none below it. **Not proven:** a real segmented scan on a scheduler or
over SSH.

## CLI

```bash
ml4gw-agent estimate "Analyze GW150914" [--no-cache] [--no-gpu] [--max-gpu-hours H]
ml4gw-agent run "..." --executor local|htcondor|ssh|kubernetes --max-gpu-hours H [--authorize-budget] [--segment-seconds S]
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
  a recorded acceptance run. Kubernetes is deferred until a cluster exists;
  the `ssh` executor stands in and still needs its own recorded run on the
  GPU node.


## SSH executor against a real host (2026-09-04)

Run from the VPS to the AutoDL GPU node (`gpu.chzmark.com:2338`) with a
mock-mode plan ("Run Aframe detection on GW150914."), evidence in
`docs/acceptance/ssh-executor-2026-09-04/` (submission record and the
worker's `run_manifest.json` copied back):

| step | result |
|---|---|
| probe / submit | plan copied by SFTP to `ML4GW_SSH_RUNS/plan-<id>/plan.json`, worker started under `nohup`, handle `gpu.chzmark.com:<pid>` |
| poll | pid watched, worker manifest read; status `completed` after one poll |
| copy-back | worker `run_71484a371009` tree returned to `submission_<id>/worker/`, `manifest_path` set, `run_status: completed` |

One configuration detail learned on the live host: `ML4GW_SSH_PYTHON` is
a *command prefix in front of `ml4gw-agent`* (default `uv run`), so a
venv without `uv` is addressed as
`ML4GW_SSH_PYTHON="env PATH=/root/ml4gw-agent/.venv/bin:/usr/bin:/bin"`;
`python -m ml4gw_agent` is not a valid prefix (the first attempt failed
with "invalid choice: 'ml4gw-agent'", recorded in the worker's
`stderr.log`, and the executor reported `worker wrote no manifest`).
