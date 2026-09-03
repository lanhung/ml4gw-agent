# Phase 4 — HTCondor execution on the CIT LIGO Data Grid pool — 2026-09-03

Evidence: `docs/acceptance/htcondor-cit-2026-09-03/` (`submission.json`,
`plan.json`, the generated `job.sub`, HTCondor's `condor.log`, the worker's
`run_manifest.json`, `report.md`, `credible_intervals.json`).

## Setup

- Submit host: `ldas-grid.ligo.caltech.edu`, reached through the IGWN SSH
  portal (`ssh.igwn.org`, LIGO.ORG password + Duo passcode), HTCondor 25.13.2,
  repository checkout `~/ml4gw-agent` with the `buoy` and `ldg` extras in a
  `uv` environment on the shared home filesystem.
- Caches pre-populated on the shared home from the head node, because
  workers have no need for outbound network: GWOSC strain for GW150914 via
  `scripts/prefetch_gwosc.py`, Aframe and AMPLFI weights at the pinned
  revisions in `~/hf-cache` (`HF_HUB_OFFLINE=1` on the worker).
- Accounting: `ML4GW_CONDOR_ACCOUNTING_GROUP=ligo.dev.o4.cbc.explore.test`,
  `ML4GW_CONDOR_ACCOUNTING_USER=fan.zhang`.

## What the pool taught the executor (three rejected submissions)

| Attempt | Pool response | Change |
|---|---|---|
| 1 | `getenv = true command not allowed (SUBMIT_ALLOW_GETENV = false)` | submit file now carries an explicit, whitelisted `environment` line (`ML4GW_*`, `GWPY_*`, `HF_*`, datafind, token and cache variables; passwords excluded) |
| 2 | `Please specify the amount of disk needed using "request_disk"` | `request_disk` (default 4 GB, `description["disk_gb"]`) |
| 3 | job matched `node2236` (RTX PRO 4000, `Microarch = x86_64-v2`), terminated with signal 4 after `fetch_data` and `inspect_data` had completed and `run_aframe` had started | torch 2.10 wheels need AVX2; `ML4GW_CONDOR_EXTRA='{"requirements": "(Microarch >= \"x86_64-v3\")"}'` |

Each rejection is recorded in the submitting agent's manifest; the third
left a checkpointed worker manifest with `run_aframe: running`, which is
the state the executor reports as "job completed, run running".

## The accepted run

Job `557860537`, submitted 12:56:59 local, executed on `aframe.ldas.cit`
(GPU `GPU-...`), normal termination with return value 0 at 13:00:20; the
submit-side agent polled every 20 s (13 polls: submitted, running,
completed) and collected the worker manifest.

| Item | Value |
|---|---|
| plan | `Fetch strain data for GW150914, check data quality, run Aframe detection and AMPLFI parameter estimation.` (6 tasks, saved as `plan.json`, executed with `ml4gw-agent run-plan` on the worker) |
| request | 4 CPUs, 16 GB memory, 1 GPU, 4 GB disk (from the resource estimate) |
| budget decision | allowed (0.0056 GPU h estimated) |
| worker run | `run_c044f735ccbb`, all six tasks completed; fetch 30 s (cache), Aframe 104 s, AMPLFI 32 s |
| Aframe | statistic 9.5059, candidate at 1126259462.414, threshold 2.701 (calibrated, 1/day) |
| AMPLFI medians | chirp mass 29.48 M☉, mass ratio 0.829, distance 461 Mpc (19966 samples) |

The numbers match the GPU-node runs of the same plan (`PHASE1B_SUITE_RUN_2026-09-03.md`)
to the same precision as before, on different hardware and a different
node type.

## Cancel and resume on the same pool

`resume_submission` on the saved handle of job `557860537` returned
`completed` with the worker manifest. A fresh submission (`557860550`,
Aframe-only plan, `wait=False`) polled as `submitted`, was cancelled through
`condor_rm`, disappeared from `condor_q`, and shows `JobStatus = 3`
(removed) in `condor_history`; the executor then polls it as `cancelled`.

## Status of the Phase 4 exit criteria

- Short event analyses run locally or on one GPU: yes (Phase 1 runs).
- Long scans partitioned and aggregated: helpers and tests exist; automatic
  splitting of one request into per-segment jobs is still the next step.
- Budget and authorization enforced before submission: yes (recorded in
  `submission.json`).
- Real scheduler: HTCondor on the CIT LDG pool, this record. Kubernetes
  remains fake-tested only.
