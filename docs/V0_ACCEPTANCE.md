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

## Pending external/scientific acceptance

- [ ] Install `ml4gw-buoy` in a GPU-capable Python 3.10–3.12 environment.
- [ ] Select immutable Aframe and AMPLFI model revisions with ML4GW maintainers.
- [ ] Run GW150914 from public data through the real adapter.
- [ ] Compare with a direct Buoy invocation using the same versions and seed.
- [ ] Review data, finite statistics, posterior dimensions, plots, model support,
      and the generated provenance manifest with an ML4GW domain expert.

See `REAL_RUN_2026-09-02.md` for the attempted real acceptance run and its
external GWOSC network blocker.

These pending items are intentionally not represented as completed. Passing the
software mock and unit suite proves orchestration behavior, not scientific
validity.

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
