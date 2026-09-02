# ML4GW Agent

ML4GW Agent is a typed, policy-controlled orchestration layer over the ML4GW
software ecosystem. The language model decides **what** scientific steps are
needed; deterministic adapters decide **how** approved software is invoked.

This repository is intentionally not a second gravitational-wave pipeline. It
wraps tools such as Buoy, Aframe, AMPLFI, GWAK, DeepClean, and data services as
versioned scientific skills with explicit inputs, outputs, preconditions,
resource needs, validation, and provenance.

## Current status: v0.2 (Phase 1b code complete, acceptance run pending)

Implemented now:

- Versioned YAML skill contracts and a validated capability registry.
- A deterministic baseline planner that converts supported prompts to a DAG.
- DAG validation, dependency resolution, task state transitions, and fail-closed
  execution.
- A safe Buoy CLI adapter that uses an argument vector (`shell=False`) and
  constrains every exposed option.
- Real decomposed adapters: `data.fetch` over public GWOSC strain,
  `data.inspect` quality gates, `aframe.detect` and `amplfi.pe` over
  `buoy.models`. They write Buoy-compatible files so agent and direct runs
  can be diffed with `scripts/compare_with_buoy.py`.
- An offline mock adapter for testing orchestration without model weights,
  credentials, or a GPU.
- Output schema checks, artifact checksums, checkpointed run manifests, and a
  Markdown report.
- CLI commands for capability inspection, planning, preflight checks, and runs.

Not yet claimed as complete:

- Real GWAK, DeepClean, mldatafind, HTCondor, Kubernetes, or Triton adapters.
- LLM-based planning and reflection.
- A scientifically validated run over GW150914. The adapters are ready; the
  run needs GWOSC access, model downloads, and preferably a GPU. See
  `docs/PHASE1B_ACCEPTANCE.md` and `scripts/phase1b_acceptance.sh`.

## Quick start

```bash
uv sync --group dev

uv run ml4gw-agent skills
uv run ml4gw-agent plan "Analyze GW150914"
uv run ml4gw-agent run "Analyze GW150914" --mode mock --runs-dir ./runs
```

The mock run creates a run directory containing:

```text
run_manifest.json
report.md
artifacts/
```

Every simulated value is explicitly marked as simulated. Mock output is useful
for testing the agent runtime; it is not a scientific result.

## Run the decomposed real pipeline

```bash
uv sync --extra buoy
uv run ml4gw-agent run \
  "Fetch strain data for GW150914, check data quality, run Aframe detection and AMPLFI parameter estimation." \
  --mode real --runs-dir ./runs --device cuda \
  --aframe-revision 3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4 \
  --amplfi-revision 8b97d2f8459d04924cb010dfee0262260bf3da80
```

This plans `data.resolve_event -> data.fetch -> data.inspect -> aframe.detect
-> amplfi.pe -> report.generate`. Aframe runs only when the quality gate
passes, and AMPLFI runs only when Aframe reports a candidate; its coalescence
time comes from the Aframe output through a typed reference.

## Run the real Buoy vertical slice

Install the optional Buoy dependency in a Python version supported by Buoy
(currently Python 3.10–3.12):

```bash
uv sync --extra buoy
uv run ml4gw-agent doctor --mode real
uv run ml4gw-agent run "Analyze GW150914" \
  --mode real \
  --runs-dir ./runs \
  --aframe-revision 3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4 \
  --amplfi-revision 8b97d2f8459d04924cb010dfee0262260bf3da80
```

The real adapter delegates event resolution, public-data retrieval, Aframe
inference, AMPLFI inference, plots, and HTML generation to Buoy. Pinning model
revisions is strongly recommended for reproducible science. The runtime records
the exact command, package version, timestamps, logs, artifacts, and SHA-256
checksums.

The CLI subprocess runner is the production default because it provides process
isolation and a hard timeout. A `--buoy-runner python` fallback exists for
restricted environments; it calls the documented `buoy.main.main` API in-process
and emits an explicit warning that those two protections are unavailable.

## Safety model

The planner never receives unrestricted shell access. It may select only skills
registered in the capability registry. Each adapter constructs a fixed argument
vector, the policy layer validates the plan before execution, and real mode
refuses skills that still have `planned` adapters.

## Repository guide

- `src/ml4gw_agent/skill_manifests/`: scientific skill contracts.
- `src/ml4gw_agent/adapters/`: deterministic execution adapters.
- `src/ml4gw_agent/planning.py`: baseline prompt router and DAG construction.
- `src/ml4gw_agent/runtime.py`: state machine, validation, and execution.
- `src/ml4gw_agent/provenance.py`: manifests and artifact hashing.
- `docs/ARCHITECTURE.md`: component boundaries and trust model.
- `docs/DESIGN_V0.1.md`: skill contracts, DAG structure, state machines, the
  LLM planner prompt, the GW150914 trace, and the design-to-code gap map.
- `docs/ROADMAP.md`: phased delivery plan and exit criteria.
- `docs/V0_ACCEPTANCE.md`: exact v0.1 acceptance checklist.
- `docs/PHASE1B_ACCEPTANCE.md`: GW150914 real-run runbook and criteria.
- `scripts/phase1b_acceptance.sh`, `scripts/compare_with_buoy.py`: acceptance
  driver and agent-versus-Buoy numerical comparison.
- `benchmarks/v0_prompts.yaml`: initial planning benchmark cases.

## Design principle

> The agent decides what to do. Versioned scientific software decides how it is
> done. Validators decide whether the result is acceptable. Provenance makes the
> run reproducible.
