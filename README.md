# ML4GW Agent

ML4GW Agent is a typed, policy-controlled orchestration layer over the ML4GW
software ecosystem. The language model decides **what** scientific steps are
needed; deterministic adapters decide **how** approved software is invoked.

This repository is intentionally not a second gravitational-wave pipeline. It
wraps tools such as Buoy, Aframe, AMPLFI, GWAK, DeepClean, and data services as
versioned scientific skills with explicit inputs, outputs, preconditions,
resource needs, validation, and provenance.

## Current status (2026-09-24)

| Area | Implemented and connected | Acceptance / remaining confirmation |
|---|---|---|
| Core | 12 versioned contracts, deterministic planner, validated DAG, policies, budgets, local executor, reports and provenance | Offline mock workflows are reproducible; mock values are not scientific results |
| Buoy / Aframe / AMPLFI | Real CLI and decomposed adapters, conditional PE | Historical GPU comparison records and five-event suite; domain sign-off pending |
| GWAK | Real adapter, dedicated 4096 Hz input branch, reconciliation, versioned background calibration | Historical runs exist; training attribution and model pairing need Fan / author confirmation |
| DeepClean | Applicability gate, witness access, cleaning and diagnostics | Historical H1 60 Hz stand-in model runs; reviewed weights and applicability require confirmation |
| Execution | Local, HTCondor, SSH; estimates, budgets and segmented batch plans | Historical HTCondor / SSH records; Kubernetes has code but no real-cluster acceptance |
| Planning / interfaces | Baseline and optional LLM planner, CLI, Web, local stdio MCP | Observation and bounded replanning exist as APIs; automatic observation → replan → execution is not connected |

Data reuse mainly follows the fixed plan's references and dedicated fetches.
The runtime cache is scoped to a run; it does not provide general cross-run data
reuse. The default Aframe branch still reads the original fetched strain and
**does not consume DeepClean's cleaned artifact**. Historical manual before/after
comparisons do not imply that this connection is automatic.

See [the roadmap](docs/ROADMAP.md) for phase-specific evidence and
[the model provenance review](docs/MODEL_PROVENANCE_REVIEW.md) for source claims,
missing evidence and domain review status. Scientific correctness and model
ownership are not established by software test results.

## Quick start

```bash
uv sync --locked --group dev

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

## Local MCP and developer integration

```bash
uv sync --locked --group dev --extra mcp
uv run --no-sync python examples/mcp_mock_client.py
# A local MCP host launches:
uv run --no-sync ml4gw-agent mcp --runs-dir ./runs/mcp
```

The official SDK v2 service exposes `list_skills`, `plan_analysis`,
`start_analysis`, `get_run` and `cancel_run`. It runs a saved complete plan in a
separate local process, defaults to mock and keeps jobs/results across restarts.
See [client configuration and real-mode setup](docs/MCP.md), the
[upstream integration checklist](docs/SKILL_INTEGRATION.md), the
[complete contract example](docs/SKILL_CONTRACT_EXAMPLE.md), and
[installation / repository handoff](docs/REPOSITORY_HANDOFF.md).

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
inference, AMPLFI inference, plots, and HTML generation to Buoy. The default policy requires pinned model
revisions for real execution. The runtime records
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
- [P0/P1 implementation plan (2026-09-24)](docs/plan/P0_P1_IMPLEMENTATION_PLAN_2026-09-24.md):
  repository readiness, skill guidance, and local stdio MCP delivery and validation.
- `docs/V0_ACCEPTANCE.md`: exact v0.1 acceptance checklist.
- `docs/PHASE1B_ACCEPTANCE.md`: GW150914 real-run runbook and criteria.
- `scripts/phase1b_acceptance.sh`, `scripts/compare_with_buoy.py`: acceptance
  driver and agent-versus-Buoy numerical comparison.
- `benchmarks/v0_prompts.yaml`: initial planning benchmark cases.

## Design principle

> The agent decides what to do. Versioned scientific software decides how it is
> done. Validators decide whether the result is acceptable. Provenance makes the
> run reproducible.
