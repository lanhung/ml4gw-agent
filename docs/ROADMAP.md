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

Status: **real GW150914 run completed and cross-checked against direct Buoy on
2026-09-03 (`PHASE1B_ACCEPTANCE_RUN_2026-09-03.md`); domain reviewer sign-off
pending**.

Deliverables already in code:

- Current Buoy CLI mapping for GWTC, GraceDB, and GPS event identifiers.
- Bounded arguments for event, detector set, device, posterior samples, HEALPix
  resolution, random seed, and immutable model revisions.
- Log collection, documented output discovery, optional HDF5 summary extraction,
  schema checks, artifact hashes, and a report.

Exit test:

1. [x] Provision a Python 3.10–3.12 environment with `ml4gw-buoy` and a CUDA GPU.
2. [x] Pin the Aframe and AMPLFI Hugging Face revisions.
3. [x] Run `Analyze GW150914` against public data.
4. [x] Confirm Buoy outputs, finite Aframe response, posterior sample shape, plots,
   and HTML report.
5. [x] Compare key outputs with a direct Buoy run (7/7 checks within tolerance);
   [ ] ML4GW domain reviewer sign-off on the manifest and report.

## Phase 1b — data + Aframe + AMPLFI composition

Status: **adapters implemented, unit-tested with fake backends (v0.2), and
passed the GW150914 acceptance run and the five-event suite on a GPU node on
2026-09-03; the calibrated threshold, a candidate-time window, mldatafind,
and domain-reviewer sign-off remain.** Runbook: `PHASE1B_ACCEPTANCE.md`;
records: `PHASE1B_ACCEPTANCE_RUN_2026-09-03.md`,
`PHASE1B_SUITE_RUN_2026-09-03.md`.

Work items:

- [x] GWOSC data adapter (`data.fetch`, Buoy-compatible window and HDF5).
- [x] Non-public frames: `data.fetch` with `source: ldg` (gwdatafind plus
      token-authorized OSDF download plus framel read; per-run frame types);
      verified on GW150914 against the public strain with an IGWN token
      (`LDG_ACCESS_2026-09-03.md`).
- [x] Science-segment, finite-strain, duration, and detector validation
      (`data.inspect`, fails closed).
- [x] Aframe inference over `buoy.models.Aframe` with frozen config metadata
      and a sample-rate compatibility check (`aframe.detect`).
- [x] AMPLFI inference over `buoy.models.Amplfi` with HL/HLV selection and
      coalescence-time bounds check (`amplfi.pe`).
- [x] AMPLFI branches only on `candidate_found`; coalescence time arrives by
      typed reference.
- [x] Cross-check decomposed outputs against Buoy on GW150914
      (`compare-decomposed.json`, 7/7 within tolerance, 2026-09-03).
- [x] Cross-check on the five-event suite (`PHASE1B_SUITE_RUN_2026-09-03.md`):
      GW190521 (HLV), a GPS-identified event, and a noise segment match Buoy
      within tolerance; GW170817 is unsupported by Buoy 0.6.1 (GEO in the
      GWOSC detector list, start-up peak before the window) and the
      decomposed path reports no candidate without failing.
- [x] FAR-calibrated Aframe threshold from a background study
      (`AFRAME_THRESHOLD_CALIBRATION_2026-09-03.md`): time-shifted GWOSC
      background, 1/day threshold 3.47 shipped for the pinned revision and
      selected with `--aframe-far`; the noise segment now yields
      `candidate_found: false` and AMPLFI is skipped. Tighter rates need
      more livetime and are refused rather than extrapolated.
- [x] Candidate-time window relative to the requested time
      (`candidate_window_seconds`, default 2 s): a peak far from the target
      is kept as `raw_peak_time` but not reported as the target's candidate.

Exit criteria:

- GW150914, GW170817 (where model support permits), GW190521, one GPS event, and
  one negative/noise segment have reviewed expected outcomes (runs and
  expected outcomes recorded; reviewer sign-off pending).
- Direct tool runs and agent runs are numerically equivalent within declared
  tolerance.
- Reruns from manifests reproduce the same versions, configuration, and seeded
  outputs.

## Phase 2 — GWAK anomaly route

Target: parallel CBC and unmodeled analysis paths.

Status: **real GWAK route running on the user's own exported GWAK 2.0
models; GW150914 and GW190521 are the loudest kernel at the catalog time,
the noise segment is not (`PHASE2_GWAK_RUN_2026-09-03.md`); threshold
calibration and author confirmation of the model pairing remain.**

Work items:

- [x] Freeze the supported GWAK workflow and model revisions: TorchScript
      embedder + background flow pinned by SHA-256 in `models/gwak/MANIFEST.json`
      (ML4GW/gwak `7b9f58a`, user-trained; not an upstream release).
- [x] Map inputs/outputs to the skill contract (`gwak.scan`: 4096 Hz H1+L1
      via a dedicated fetch, whitening per the training config, per-kernel
      scores, top segments, target-time score/rank).
- [ ] Anomaly-score calibration (time-shifted background) and top-segment
      validation on injections and glitches.
- [x] Discrepancy logic: `analysis.reconcile` runs after both detection
      tasks; Aframe negative/GWAK positive routes to morphology diagnostics
      and never to AMPLFI, which stays conditioned on the Aframe candidate.

Exit criteria:

- [ ] Known injections, known glitches, and background segments in the
      acceptance suite (two catalog events, one noise segment, one BNS run so
      far).
- [x] The planner chooses Aframe, GWAK, or both correctly on the benchmark
      (`benchmarks/v0_prompts.yaml`: `route_aframe_only`, `route_gwak_only`,
      `route_both_reconciled`, `composed_analysis`).

## Phase 3 — DeepClean conditioning

Target: scientifically guarded noise subtraction.

Status: **applicability gate implemented and verified on real public data
(GW150914, 2026-09-03: `applicable: false` with the public-strain and
missing-configuration reasons, cleaning skipped); the cleaning step needs
LDG witness channels and a reviewed configuration.**

Work items:

- [x] Witness-channel access check: public strain sources are refused; LDG
      sources are accepted only with a reviewed configuration. Witness
      channels themselves were reached through NDS2 with the IGWN credential
      at an O4 time (`LDG_ACCESS_2026-09-03.md`).
- [x] Versioned coupling configurations with exact channel lists, band,
      sample rate, interval, and immutable weights
      (`calibration/deepclean_support.json`, empty until reviewed).
- [x] IFO, frequency-band, sample-rate, and weight support encoded in the
      same table and checked per detector and interval.
- [ ] Before/after signal-preservation and subtraction diagnostics
      (`deepclean.clean`, needs LDG access).
- [ ] Conditional cleaned/raw merge after an applicability pass.

Exit criteria:

- [x] Inapplicable public-data cases are skipped with a correct reason.
- [ ] Applicable cases preserve injected astrophysical signals within a reviewed
      tolerance while reducing the targeted noise coupling.

## Phase 4 — scalable execution

Target: choose compute based on bounded cost and data locality.

Status: **executor contracts, estimates, budget policy, partitioning, and
local/HTCondor/Kubernetes executors implemented (`PHASE4_EXECUTION.md`);
whole-plan submission verified on the CIT LDG HTCondor pool with submit,
poll, resume and cancel on 2026-09-03 (`PHASE4_HTCONDOR_RUN_2026-09-03.md`).
Kubernetes is fake-tested only.**

Work items:

- [x] Executor contracts: local, HTCondor, and Kubernetes implemented;
      Law/Luigi, Snakemake, and Triton/Hermes registered as planned with
      stated blockers (`ml4gw_agent.executors`).
- [x] Job handles, polling, cancellation, checkpoint/resume, a per-run
      result cache, and retry policies.
- [x] `estimate_plan`: CPU/GPU hours, memory, transfer volume, and expected
      latency from the contracts plus the runtimes measured in the Phase 1
      runs; `ml4gw-agent estimate "<prompt>"`.

Exit criteria:

- [x] Short event analyses run locally or on one GPU (every Phase 1 run).
- [x] Long scans are partitioned and aggregated without duplicate or missing
      segments (`partition_scan`/`merge_segment_outputs`, property tests).
      Automatic splitting of one long request into per-segment sub-plans is
      the next wiring step.
- [x] Budget and authorization policies are enforced before submission
      (`BudgetPolicy`, checked before preflight, recorded in the manifest).
- [x] The HTCondor executor on a real pool (CIT LDG, job 557860537: all six
      tasks completed on `aframe.ldas.cit`; cancel and resume verified).
- [ ] The Kubernetes executor on a real cluster.

## Phase 5 — measured agentic planning

Target: add LLM planning, observation, reflection, and experiment memory without
weakening the deterministic execution boundary.

Status: **implemented and measured with a replay client
(`PHASE5_PLANNING.md`); the real-model row of the evaluation needs API
credentials, which this host does not have.**

Work items:

- [x] Require LLM output to validate as `PlanSpec` (plus registry, parameter,
      reference, condition, and policy checks; one repair round; baseline
      fallback).
- [x] Retrieve only registry summaries relevant to the request.
- [x] Structured observations (`observe`) and bounded replanning (`replan`,
      at most once, only after a failure).
- [x] Experiment memory (`ExperimentMemory`: data, models, configuration,
      result, failures), fed back per event.
- [x] 71 benchmark cases across `v0_prompts.yaml` and `v1_prompts.yaml`,
      including adversarial and Chinese prompts.

Exit criteria:

- [x] Tool-selection accuracy, plan validity, execution success (mock),
      recovery, cost, latency, and reproducibility are reported by
      `scripts/evaluate_planner.py` against the deterministic baseline
      (replay client: all 1.000, recovery true). Scientific correctness is
      carried by the Phase 1 acceptance records, which the planner reuses
      unchanged.
- [ ] The same report with `--client anthropic` on a credentialed host.
- [x] No prompt bypasses registry, policy, adapter, validation, or provenance
      controls (unit tests over injected invalid plans and adversarial
      prompts).

