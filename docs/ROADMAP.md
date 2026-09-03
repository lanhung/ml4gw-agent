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
- [x] Non-public frames: `data.fetch` with `source: ldg` (Buoy's channel map
      through `gwdatafind`; fails closed without IGWN credentials; not
      runnable from the public GPU node).
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
- [ ] FAR-calibrated Aframe threshold from a background study. The noise
      segment in the suite gives `candidate_found: true` at statistic 0.51
      with the raw threshold, so this is a blocker for any detection claim.
- [ ] Candidate-time window relative to the requested time, so a peak far
      from the target (59 s in the noise case) is not reported as its
      coalescence time.

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

Status: **routing implemented and benchmarked; the GWAK adapter is
fail-closed because upstream publishes no inference interface or weights
(`UPSTREAM_REVIEW.md`, 2026-09-03).**

Work items:

- [ ] Freeze the supported GWAK workflow and model revisions. Blocked
      upstream: no packaged release, scan entry point, or pretrained weights
      at an immutable revision exist.
- [ ] Map its Snakemake inputs/outputs to the skill contract (blocked by the
      same item).
- [ ] Define anomaly-score calibration and top-segment validation (blocked).
- [x] Discrepancy logic: `analysis.reconcile` runs after both detection
      tasks; Aframe negative/GWAK positive routes to morphology diagnostics
      and never to AMPLFI, which stays conditioned on the Aframe candidate.

Exit criteria:

- [ ] Known injections, known glitches, and background segments in the
      acceptance suite (needs a runnable GWAK).
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
      sources are accepted only with a reviewed configuration.
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

