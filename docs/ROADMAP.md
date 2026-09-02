# Delivery roadmap

The project is developed as vertical slices with explicit exit criteria. A
phase is complete only when its real adapter has passed both software tests and
a reviewed scientific acceptance case.

## Phase 0 — contracts and controlled runtime

Status: **implemented and locally verified in v0.1**.

Deliverables:

- Versioned `skill.yaml` contract model and capability registry.
- JSON Schema validation for inputs and outputs.
- Validated DAG, conditions, typed task-output references, and task states.
- Fail-closed policy layer and no arbitrary shell access.
- Mock adapters, reports, provenance manifests, and artifact hashes.
- Initial benchmark prompts and automated tests.

Exit evidence:

- Registry loads all initial contracts.
- Generic and composed prompts complete in mock mode.
- Invalid inputs, unknown skills, cycles, path escapes, and unpinned real runs
  are rejected.
- Test coverage is at least 85%; lint and formatting checks pass.

## V0 / Phase 1a — real Buoy vertical slice

Status: **adapter implemented; external scientific run pending**.

Deliverables already in code:

- Current Buoy CLI mapping for GWTC, GraceDB, and GPS event identifiers.
- Bounded arguments for event, detector set, device, posterior samples, HEALPix
  resolution, random seed, and immutable model revisions.
- Log collection, documented output discovery, optional HDF5 summary extraction,
  schema checks, artifact hashes, and a report.

Remaining exit test:

1. Provision a Python 3.10–3.12 environment with `ml4gw-buoy` and a CUDA GPU.
2. Pin the Aframe and AMPLFI Hugging Face revisions.
3. Run `Analyze GW150914` against public data.
4. Confirm Buoy outputs, finite Aframe response, posterior sample shape, plots,
   and HTML report.
5. Compare key outputs with a direct Buoy run and have an ML4GW domain reviewer
   sign off on the manifest and report.

## Phase 1b — data + Aframe + AMPLFI composition

Status: **adapters implemented and unit-tested with fake backends (v0.2);
GW150914 acceptance run pending on a GWOSC-connected GPU node.** Runbook:
`PHASE1B_ACCEPTANCE.md`.

Work items:

- [x] GWOSC data adapter (`data.fetch`, Buoy-compatible window and HDF5).
- [ ] `mldatafind` adapter for non-public frames.
- [x] Science-segment, finite-strain, duration, and detector validation
      (`data.inspect`, fails closed).
- [x] Aframe inference over `buoy.models.Aframe` with frozen config metadata
      and a sample-rate compatibility check (`aframe.detect`).
- [x] AMPLFI inference over `buoy.models.Amplfi` with HL/HLV selection and
      coalescence-time bounds check (`amplfi.pe`).
- [x] AMPLFI branches only on `candidate_found`; coalescence time arrives by
      typed reference.
- [ ] Cross-check decomposed outputs against Buoy on GW150914, then the
      five-event suite (`scripts/compare_with_buoy.py`).
- [ ] FAR-calibrated Aframe threshold from a background study.

Exit criteria:

- GW150914, GW170817 (where model support permits), GW190521, one GPS event, and
  one negative/noise segment have reviewed expected outcomes.
- Direct tool runs and agent runs are numerically equivalent within declared
  tolerance.
- Reruns from manifests reproduce the same versions, configuration, and seeded
  outputs.

## Phase 2 — GWAK anomaly route

Target: parallel CBC and unmodeled analysis paths.

Work items:

- Freeze the supported GWAK workflow and model revisions.
- Map its Snakemake inputs/outputs to the skill contract.
- Define anomaly-score calibration and top-segment validation.
- Add discrepancy logic: Aframe negative/GWAK positive leads to morphology
  diagnostics, not AMPLFI.

Exit criteria:

- Known injections, known glitches, and background segments are included in the
  acceptance suite.
- The planner chooses Aframe, GWAK, or both correctly on the benchmark.

## Phase 3 — DeepClean conditioning

Target: scientifically guarded noise subtraction.

Work items:

- Implement witness-channel discovery and access checks.
- Version coupling configurations and exact channel lists.
- Encode IFO, frequency-band, sample-rate, preprocessing, and weight support.
- Add before/after signal-preservation and subtraction diagnostics.
- Introduce the conditional cleaned/raw merge only after an applicability pass.

Exit criteria:

- Inapplicable public-data cases are skipped with a correct reason.
- Applicable cases preserve injected astrophysical signals within a reviewed
  tolerance while reducing the targeted noise coupling.

## Phase 4 — scalable execution

Target: choose compute based on bounded cost and data locality.

Work items:

- Add executor contracts for Law/Luigi, Snakemake, HTCondor, Kubernetes, and
  Triton/Hermes.
- Add job handles, polling, cancellation, checkpoint/resume, caching, and retry
  policies.
- Estimate CPU/GPU hours, memory, transfer volume, and expected latency before
  submission.

Exit criteria:

- Short event analyses run locally or on one GPU.
- Long scans are partitioned and aggregated without duplicate or missing
  segments.
- Budget and authorization policies are enforced before submission.

## Phase 5 — measured agentic planning

Target: add LLM planning, observation, reflection, and experiment memory without
weakening the deterministic execution boundary.

Work items:

- Require LLM output to validate as `PlanSpec`.
- Retrieve only registry summaries relevant to the request.
- Add structured observations and bounded replanning.
- Store experiment memory (data, model, configuration, result, failure), not
  merely chat history.
- Build 50–100 benchmark tasks and adversarial prompts.

Exit criteria:

- Report tool-selection accuracy, plan validity, execution success, scientific
  correctness, recovery, cost, latency, and reproducibility against the
  deterministic baseline.
- No prompt can bypass registry, policy, adapter, validation, or provenance
  controls.

