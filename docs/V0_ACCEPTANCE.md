# v0.1 acceptance record

Date: 2026-09-02

## Completed automatically

- [x] Ten initial scientific skill contracts load successfully.
- [x] Input and output contracts are valid JSON Schema 2020-12 documents.
- [x] Unknown skills, duplicate skills, and cyclic DAGs are rejected.
- [x] Exact typed task-output references resolve across the DAG.
- [x] Conditional tasks can be skipped without failing the run.
- [x] A final audit report can run after an upstream failure.
- [x] Real execution fails before the first task when adapters or immutable
      revisions are missing.
- [x] The Buoy command is an argument vector and never passes through a shell.
- [x] Artifact path escape and symlink protections are in place.
- [x] Manifests are checkpointed atomically and artifacts receive SHA-256 hashes.
- [x] Generic `Analyze GW150914` mock vertical slice completes.
- [x] Explicit Data + DeepClean applicability + Aframe + AMPLFI + GWAK mock DAG
      completes.
- [x] All 37 tests pass.
- [x] Total test coverage is 85.58%, above the 85% gate.
- [x] Ruff lint and formatting checks pass.
- [x] Wheel and source distribution build successfully.
- [x] The wheel installs in a clean environment, loads all ten contracts, and
      completes the GW150914 mock CLI run.

## External/scientific acceptance

Completed on 2026-09-03 in run `phase1b-GW150914-20260903T025339Z`
(AutoDL node, NVIDIA RTX 5000 Ada, Python 3.12.12, `ml4gw-buoy` 0.6.1);
full record in `PHASE1B_ACCEPTANCE_RUN_2026-09-03.md`, evidence in
`acceptance/phase1b-GW150914-20260903T025339Z/`.

- [x] Install `ml4gw-buoy` in a GPU-capable Python 3.10–3.12 environment
      (`doctor.json`: `v0_buoy_ready: true`, torch 2.10.0+cu128, CUDA).
- [x] Pin immutable Aframe and AMPLFI model revisions
      (`3c947f6d…` and `8b97d2f8…`, the revisions recorded in
      `UPSTREAM_REVIEW.md`). Maintainer confirmation that these are the
      intended production revisions is still to be obtained.
- [x] Run GW150914 from public data through the real adapter
      (`run_9314eea2eaaa`, `status: completed`, peak Aframe statistic 9.5059,
      predicted coalescence time 1126259462.414).
- [x] Compare with a direct Buoy invocation using the same versions and seed
      (`compare-buoy-slice.json`: 7/7 checks passed; posterior medians
      identical, Aframe statistic within 4e-6 relative).
- [ ] Review data, finite statistics, posterior dimensions, plots, model support,
      and the generated provenance manifest with an ML4GW domain expert.
      Reviewer: not yet assigned. The side-by-side GWTC-1 table in the run
      record is the material for this review.

`REAL_RUN_2026-09-02.md` records the earlier attempt that was stopped by a
GWOSC network blocker; the 2026-09-03 run replaced that blocker with a
verified pre-fetched strain cache (`scripts/prefetch_gwosc.py`).

Passing the software mock and unit suite proves orchestration behavior, not
scientific validity; the domain review item above is intentionally left open.

## Reproduce local verification

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest

uv run ml4gw-agent run "Analyze GW150914" \
  --mode mock \
  --runs-dir ./runs

uv run ml4gw-agent run \
  "Analyze GW150914, check data quality, use DeepClean if appropriate, run Aframe and AMPLFI parameter estimation, then scan anomalies with GWAK." \
  --mode mock \
  --runs-dir ./runs
```
