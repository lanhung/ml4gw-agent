# Phase 1b acceptance runbook

Phase 1b has two deliverables, in this order:

1. The **real GW150914 acceptance run** that v0.1 could not finish because
   its execution environment had no route to GWOSC
   (`REAL_RUN_2026-09-02.md`).
2. The **decomposed skills** `data.fetch`, `data.inspect`, `aframe.detect`,
   and `amplfi.pe` as independent real adapters, cross-checked against
   Buoy.

Both are exercised by one script, `scripts/phase1b_acceptance.sh`, on a
node that can reach `gwosc.org` and Hugging Face and preferably has a CUDA
GPU. The development container used to write the adapters has neither
GWOSC access nor a GPU, so the run itself is an external step.

## Target environments

| Environment | Notes |
|---|---|
| AutoDL GPU instance | Ubuntu image with CUDA 12.x; Python 3.10 to 3.12 via `uv python install 3.11`; outbound HTTPS is open. Model weights (about 320 MB) download from Hugging Face on first use; set `HF_ENDPOINT` to a mirror if needed. |
| LIGO Data Grid head node | Use a personal conda or `uv` environment. Public GWOSC data does not need credentials. A GPU node via HTCondor is optional for GW150914. |
| CPU only | Works; Buoy documents roughly 15 minutes per event on CPU. Pass `DEVICE=cpu`. |

## Steps

```bash
git clone https://github.com/lanhung/ml4gw-agent
cd ml4gw-agent
git checkout claude/ml4gw-orchestration-layer-i86m2q

curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.11
uv sync --extra buoy --group dev

# reviewed starting revisions from docs/UPSTREAM_REVIEW.md; confirm with maintainers
export AFRAME_REVISION=3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4
export AMPLFI_REVISION=8b97d2f8459d04924cb010dfee0262260bf3da80
export DEVICE=cuda        # or cpu
export SEED=0

bash scripts/phase1b_acceptance.sh
```

The script:

0. (Optional, for nodes with slow or flaky GWOSC access.) Pre-populate the
   strain cache with `uv run python scripts/prefetch_gwosc.py GW150914` and
   export `GWPY_CACHE=1`; the 2026-09-03 run needed this because the in-run
   download from `gwosc.org` truncated at 70 kB/s.
1. Syncs the pinned environment, prints the torch and CUDA state, confirms
   GWOSC resolves GW150914, and records `ml4gw-agent doctor --mode real`.
   Both `v0_buoy_ready` and `phase1b_decomposed_ready` must be `true`.
2. Runs `Analyze GW150914` through the agent's Buoy vertical slice.
3. Runs the decomposed prompt
   `Fetch strain data for GW150914, check data quality, run Aframe detection
   and AMPLFI parameter estimation.` through the four new adapters.
4. Runs Buoy directly with the same seed, device, and revisions.
5. Compares both agent runs against the direct run with
   `scripts/compare_with_buoy.py`.

Everything lands under `runs/phase1b-GW150914-<timestamp>/`.

## Acceptance criteria

Result of run `phase1b-GW150914-20260903T025339Z` (2026-09-03); see
`PHASE1B_ACCEPTANCE_RUN_2026-09-03.md` for the numbers behind each tick.

Software:

- [x] `doctor` reports every adapter `available`.
- [x] Both agent runs end with `status: completed`; every task `completed`
      (`run_amplfi` may be `skipped` only if `candidate_found` is false, which
      for GW150914 would itself be a finding to investigate).
- [x] No `simulated: true` anywhere in either manifest.
- [x] Every artifact in the manifests has a SHA-256 and lives inside its run
      directory.

Science (to be reviewed by an ML4GW domain expert):

- [x] `data.inspect` reports `quality_passed: true`, both `H1_DATA` and
      `L1_DATA` cover the window, no non-finite samples.
- [x] `aframe.detect` peak `detection_statistic` is finite (9.5059) and its
      `predicted_coalescence_time` lies within 0.1 s of 1126259462.4
      (offset +0.014 s).
- [x] `compare_with_buoy.py` passes for the vertical slice with default
      tolerances. Note: the runs are *not* bit-identical; the Aframe peak
      differs by 4e-6 relative between two Buoy invocations on the same GPU
      (CUDA non-determinism), posterior medians are identical.
- [x] `compare_with_buoy.py` passes for the decomposed run (Aframe peak
      within 4e-6 relative, posterior medians within 6e-5 relative).
- [x] AMPLFI credible intervals are recorded side by side with GWTC-1 in
      `PHASE1B_ACCEPTANCE_RUN_2026-09-03.md` (detector-frame chirp mass
      29.5 M☉, mass ratio 0.83, distance 461 Mpc). Whether the low
      source-frame chirp mass edge and the 610 deg² HL-only sky area are
      acceptable is a reviewer judgement, not ticked here.
- [ ] Domain reviewer sign-off.
- [x] The sky map FITS file opens with `ligo.skymap` and its 90% area is
      recorded (610 deg²).

Provenance:

- [x] Both manifests, both reports, `doctor.json`, `env.txt`, the direct
      Buoy log, and both comparison JSON files are attached to the acceptance
      record (`acceptance/phase1b-GW150914-20260903T025339Z/`).
- [x] `V0_ACCEPTANCE.md` items are ticked with the run identifier, date, and
      hardware; the reviewer line stays open.

## What the adapters guarantee before the run

These properties are covered by the unit suite with fake backends and hold
regardless of the environment:

- `data.fetch` positions the window exactly like Buoy (`event_offset_fraction`
  0.75 of a 128 s window, integer-aligned start), refuses GraceDB identifiers
  on the public path, resamples only with a recorded warning, and writes the
  Buoy HDF5 layout (`t0`, `tc`, one dataset per detector).
- `data.inspect` fails closed: any missing detector, non-finite sample,
  constant series, short duration, uncovered science segment, or unreachable
  segment service sets `quality_passed` to false and lists the reason.
- `aframe.detect` refuses a sample-rate mismatch instead of resampling,
  requires the `['H1', 'L1']` detector order the published model expects,
  rejects non-finite outputs, and writes Buoy's `aframe_outputs.hdf5` layout
  plus the threshold used. The threshold is marked uncalibrated.
- `amplfi.pe` selects the HL or HLV checkpoint from the detector set,
  requires the coalescence time to lie inside the strain, writes
  `posterior_samples.dat`, a FITS sky map, and a credible-interval summary,
  and fails the task if the sky map cannot be produced.
- In the decomposed plan, `amplfi.pe` runs only when `aframe.detect`
  reports `candidate_found`, and it reads the coalescence time from the
  Aframe output through a typed reference.

## Known limits to record with the run

- The Aframe threshold is a raw integrated-output cut. Turning
  `candidate_found` into a statement about significance needs a background
  study; that is Phase 2 work and the manifest warning says so.
- `data.fetch` serves public GWOSC data only. Non-public frames through
  `mldatafind` remain planned.
- No Q-transform or morphology diagnostics exist yet; they arrive with the
  GWAK route.
