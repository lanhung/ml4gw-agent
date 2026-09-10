# ml4gw-agent: project brief and how to read the run records (2026-09-10)

An English brief for talks and for readers of the acceptance panel on the web
interface. Every number below comes from a run manifest with SHA-256 artifact
hashes; the manifests ship in `docs/acceptance/`.

## 1. What the system is

Machine learning now covers the whole low-latency gravitational-wave workflow:
Aframe (detection), AMPLFI (parameter estimation), GWAK (unmodelled anomalies)
and DeepClean (witness-based noise subtraction). What is still manual is the
judgement that composes them for a given question: which data source can serve
the request, whether a model's training range and detector set apply, what
threshold turns a network output into a significance statement, whether an
expensive step is justified, and how every number can be traced back to
immutable inputs.

`ml4gw-agent` is an orchestration layer built on one principle: the agent may
decide **what** to run, but it is never trusted with **whether a result is
valid**. Concretely:

- **Typed skill contracts.** Every capability is a versioned YAML manifest with
  JSON-schema inputs and outputs, machine-checked preconditions, resource
  estimates, a risk level, and an immutable model revision. The planner sees
  only contracts; it cannot invent parameters or skip a precondition.
- **Two planners, one plan object.** A deterministic router (default for
  science) and an LLM planner (Claude, DeepSeek, Qwen, OpenRouter free models,
  Groq, local Ollama, or any OpenAI-compatible endpoint) both emit the same
  validated plan, so every downstream guarantee is independent of the planner.
- **Fail-closed adapters.** When a model, credential, witness channel or
  calibration is missing, the task fails with a recorded reason and its
  dependants are skipped. Nothing is filled in with defaults.
- **Provenance.** Each run writes a manifest with the plan, resolved
  parameters, outputs, validations, warnings, timings, package versions, model
  revisions and the SHA-256 of every artifact.
- **Calibration as a first-class object.** Thresholds come from time-shifted
  background studies keyed by model revision, together with the livetime that
  supports them. A rate the livetime cannot resolve is refused, not reported.
- **Executors and budget.** Local GPU, HTCondor on the LIGO Data Grid, or a
  remote host over SSH; GPU-hour estimates are checked against a budget policy
  before submission, and long scans are split into overlapping segments and
  merged.

## 2. Status

| Area | State |
|---|---|
| Framework (phases 0-5) | complete: contracts, planners, adapters, manifests, budget policy, three executors, segmentation |
| Aframe / AMPLFI | real adapters through Buoy 0.6.1 with pinned revisions |
| GWAK | real adapter on the user's own GWAK 2.0 export, threshold calibrated |
| DeepClean | real applicability gate and cleaning route, self-trained 60 Hz H1 coupling |
| Backgrounds | 69 d livetime for Aframe (1/day 2.986, 1/month 4.398) and 69 d for GWAK (27.85, 28.23) |
| Injections | Aframe 50 % efficiency at network SNR 8.2, 90 % at 11.8, zero false candidates in controls |
| Population validation | 90 GWTC events end to end on the CIT pool, 0.35 GPU-hours of compute |
| Planner evaluation | 317 prompts, three backbones, adversarial suite |
| Event question answering | 13 GraceDB superevents x 5 phrasings, 59/59 as expected |
| Interfaces | CLI, FastAPI web UI, multi-provider LLM planning, catalog lookup route |
| Manuscript | six-page AASTeX draft with all placeholders filled |

## 3. Where GWAK and DeepClean came from

**GWAK.** Upstream ML4GW/gwak publishes no inference package or weights, and
the developers expect at least three more months. The models used here are the
user's own GWAK 2.0 training on the LIGO Data Grid (repository commit
`7b9f58a`). Candidate checkpoints were exported to TorchScript and tested
empirically on GW150914, GW190521 and a noise segment: only the S4 SimCLR
embedder paired with the background-only normalizing-flow metric separates the
events from the rest of their window (z-scores 10.5 and 11.8, rank 0 of 1001).
Tarantula embedders and linear or MLP metrics do not. The pairing is pinned by
SHA-256 in `models/gwak/MANIFEST.json` as revision
`gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad`.

Usage: `ml4gw-agent run "Run Aframe and GWAK on GW150914 and reconcile the two
results." --mode real --gwak-far 365.25`. The planner fetches a separate
4096 Hz copy of the strain for GWAK. Preprocessing matches training: 0.5 s
kernels, 64 s PSD, 1 s fduration, 30 Hz high-pass, 1/16 s stride, strain
normalised before whitening, flow evaluated on CPU in float64. Because the
background is glitch-dominated, read `target_far_per_year`, the z-score and the
rank rather than the boolean `anomaly_found`.

**DeepClean.** The DeepClean team supplied no configuration or weights, so the
public `deepcleanv2` 60 Hz recipe was ported into
`src/ml4gw_agent/adapters/deepclean_model.py`: a 1-D convolutional autoencoder
with hidden channels [8, 16, 32, 64], PSD-ratio loss, 55-65 Hz band, 4096 Hz,
8 s training kernels, 1 s cleaning kernels. It was trained on non-public O4 H1
data reached through NDS2 with the user's IGWN credential, using the mains
monitor `H1:PEM-CS_MAINSMON_EBAY_1_DQ` as the only witness. On held-out data
the 60 Hz line drops by a factor of seven and the out-of-band ASD ratio stays
at 1.0000. The weights (175 kB) ship in `models/deepclean/H1_60Hz/` and the
configuration is registered in `calibration/deepclean_support.json`, marked
explicitly as a self-trained stand-in.

Usage: the planner always schedules `deepclean.check_applicability` first. It
requires a data source that can serve witness channels (public GWOSC strain
cannot), a reviewed configuration covering the detector and interval, and an
actual witness fetch. Only then does `deepclean.clean` run, and it verifies the
weights hash, subtracts a band-limited witness-only estimate, and reports
`applicable: false` if the in-band ASD does not improve or the out-of-band ASD
moves by more than 5 %. On superevent S250119cv the Aframe statistic went from
8.50 to 8.67 after cleaning with an unchanged merger time, so the signal
survives.

## 4. How to read the "verified real runs" panel

The panel lists acceptance records shipped with the repository. Two conventions
matter:

- **"failed" is usually the system working.** A run marked failed did not crash;
  an adapter refused to proceed and recorded the reason. The manifest names the
  detector, the interval and the missing resource.
- **A blank Aframe statistic means the analysis never ran.** Either the fetch
  failed closed, or the data-quality gate rejected the window and the plan's
  condition skipped the detection and parameter-estimation tasks.

### Record by record

| Record | What it demonstrates |
|---|---|
| `phase1b-*` (five events) | The agent's decomposed plan reproduces a direct Buoy run to 1e-6 in the detection statistic and to 1e-5 in AMPLFI medians. `GW170817` and its GPS twin show `Analyze …` failing because Buoy 0.6.1 does not support that event, while the decomposed route still completes and returns a below-threshold statistic of -0.129: a binary neutron star is outside the BBH model's training range. |
| `ldg-GW150914-2026-09-03` | Strain fetched from authenticated LIGO Data Grid frames instead of the public archive. |
| `htcondor-cit-2026-09-03` | The same plan submitted as a whole to the Caltech HTCondor pool, with poll, cancel and resume verified. |
| `S250119cv-nds2-2026-09-03` | A non-public O4 superevent streamed through NDS2, statistic 8.50, merger time 0.086 s before the GraceDB t0. |
| `S250119cv-deepclean` | The same event with the DeepClean route: witness fetched, cleaning applied to H1 only, statistic 8.50 on raw and 8.67 on cleaned strain. |
| `aframe-background-2026-09-03`, `background-extended-2026-09-04` | Time-shifted background studies: 5.5 d giving the 1/day cut 2.701, then 69 d giving 2.986 at 1/day and 4.398 at 1/month. Recalibration re-labels earlier results automatically: 59 of the 60 population candidates survive the tighter cut. |
| `gwak-route-2026-09-03`, `gwak-calibrated-2026-09-04` | Four cases through the joint Aframe plus GWAK route before and after GWAK calibration. GW150914 and GW190521 are the loudest kernel of their window; the noise segment and GW170817 are not. |
| `population-2026-09-04` | 90 GWTC events end to end. 7 fetch failures are single-LIGO events with no public two-detector data. 7 quality-gated events have non-finite H1 samples or an uncovered data flag. Of the 76 analysed, Aframe finds 60, and 60 of the 71 inside its training range. |
| `injections-2026-09-04` | Efficiency versus injected SNR for Aframe and GWAK, plus the DeepClean preservation check. |
| `gracedb-qa-2026-09-09` | 13 GraceDB superevents asked five different ways each. |
| `planner-eval-*`, `ssh-executor-2026-09-04` | Planning benchmarks and the SSH executor verified against a real remote host. |

### The GraceDB question-answering block in detail

Seven superevents completed and six failed closed, in every phrasing:

| Superevent | Outcome | Why |
|---|---|---|
| S231123cg (GW231123, 137+101 Msun) | completed, statistic 8.85 | heaviest binary black hole to date |
| S231226av (GW231226, SNR 34.7) | completed, 8.80 | loudest O4a event |
| S231028bg (GW231028, 94+59) | completed, 8.48 | |
| S231224e (GW231224, 9.3+7.3) | completed, 4.90 | low-mass system, weaker statistic |
| S250114ax (GW250114) | completed, 9.29 | O4b discovery-paper event |
| S250119cv | completed, 8.50 | matches the earlier NDS2 run |
| S240104bl (GW240104) | completed, blank statistic | quality gate: the public L1 file has non-finite samples and no data flag, so the analysis was skipped |
| S230529ay (GW230529) | failed at fetch | mass-gap neutron-star black-hole event seen by L1 only; a two-detector analysis is refused rather than faked |
| S250206dm, S250727cl, S250810ck, S251108dn | failed at fetch | no public strain for these O4 candidates |
| S251017di | failed at fetch, retraction recorded | the alert was retracted by the collaboration; the resolver reports `retracted: true` before the fetch is even attempted |

The scoring for these 59 prompts: identifier extracted and a valid plan in
59 of 59; merger time resolved within 1 s of the GraceDB value in 59 of 59;
detector set correct in 26 of 26 superevent prompts; retraction status correct
in 26 of 26. The five phrasings of one event give the same resolved time, the
same plan and the same numbers, which is the property that matters for a
question-answering interface.

## 5. What is genuinely new, and what is not

New, and specific to this layer:

- A quantitative answer to the silent-failure problem for scientific agents.
  With the same language model, taking the first proposal at face value would
  have executed a plausible but wrong analysis for 35 % of adversarial
  requests; through the contract path the rate is 0 % for two backbones and
  2 % for the third, and the suite itself found the two validator gaps that
  produced that 2 %.
- Calibration and provenance as objects the agent cannot bypass, with
  recalibration propagating to earlier results.
- Population-scale reproduction of published model behaviour with a full audit
  trail at 0.35 GPU-hours.
- Free and open-weight models made safe to use, because the fallback is the
  deterministic router: a weaker model costs helpfulness, not correctness.

Not claimed: a new search, a new astrophysical event, or a replacement for
reviewed collaboration pipelines. The Aframe, AMPLFI, GWAK and DeepClean
numbers belong to those models; here they are a fidelity check on the layer.

## 6. Open items

- GWAK: the model pairing needs author confirmation, and a glitch veto is
  required before the anomaly flag is meaningful at astrophysical rates.
- DeepClean: one self-trained coupling; the team's reviewed weights and an
  injection-based tolerance study are pending.
- Significance: limited by background livetime; 1/month is measurable now,
  anything tighter needs more time slides.
- Publication: a decision on LVK review for the O4 material, author list and
  acknowledgements, and optionally a human-expert baseline for the planner
  benchmark.

## 7. Two design bullets in detail

### Fail-closed adapters

"Fail-closed" is borrowed from engineering: when a fail-closed door loses
power it locks, it does not swing open. Here, when a task loses a
precondition it stops, it does not proceed on a guess. An adapter is the
deterministic code behind one skill, and it has three hooks:

- `probe()` reports whether the adapter can run here at all. This is what the
  Skills table on the web page shows, for example `aframe.detect` as
  "missing: buoy, torch, ml4gw" on the web host, because real detection runs
  on the GPU node.
- `preflight(context)` checks the specific request before any computation and
  either returns non-fatal warnings or raises. Missing credential, unknown
  detector, GraceDB identifier without a resolved time: all caught here.
- `execute(context)` does the work and returns outputs, artifacts, the command
  that was run, metadata and warnings.

Four classes of missing input are named on the slide, and each has a concrete
refusal:

| Missing | What happens |
|---|---|
| model | `AdapterUnavailableError` when the package or the weights are absent; `AdapterError` when the shipped SHA-256 does not match the requested revision. `UNPINNED` revisions are rejected by the execution policy, and invented tags such as `v99` by the planner validator. |
| credential | `credential_status()` returns false with the exact remedy, for example "set BEARER_TOKEN_FILE (SciToken from `htgettoken -a vault.ligo.org -i igwn`) or X509_USER_PROXY". Cluster-local datafind servers are an explicit exception. |
| witness | `deepclean.check_applicability` fetches the configured witness channels; a failure becomes `applicable: false` with the reason, and the cleaning task is skipped by its plan condition. |
| calibration | If no background study covers the pinned revision at the requested false-alarm rate, the plan carries a warning and the adapter sets `threshold_calibrated: false`, so a boolean flag is never presented as a significance statement. |

Failure propagates through the plan rather than being swallowed. The runtime
walks tasks in topological order and, before running each one, inspects its
dependencies:

- a failed or blocked dependency marks the task `blocked` with
  `failed or blocked dependencies: fetch_data`;
- a skipped dependency marks it `skipped`;
- a task whose `when` condition evaluates false is `skipped`, and the
  evaluation itself is recorded as a validation
  ("condition evaluated false; task skipped").

The one deliberate exception is `allow_failed_dependencies`, which
`report.generate` sets, so a run that failed still produces a readable report
explaining why.

After `execute` returns, the outputs are validated against the skill's output
schema and its declared checks (required fields present, declared artifacts
actually on disk). A failed check raises and the task is marked failed, so an
adapter cannot return a malformed or half-filled result and have it pass.
Retries are bounded and only apply to expected adapter errors. Errors are a
typed hierarchy (`AdapterError`, `AdapterUnavailableError`, `ValidationError`,
`PolicyError`, `PlanningError`); anything outside it is caught at a last-resort
boundary and recorded as `Unexpected <type>`, so an unknown bug is visible as
an unknown bug rather than as a result.

The property to state in one sentence: **there is no partial credit**. A plan
that completes 60 % of its tasks does not hand you a number for the other 40 %.

### Run manifest

Every run writes one JSON file, `run_manifest.json`, and rewrites it after
every state change, so it is simultaneously the audit record and the
checkpoint used for cancel and resume. It is schema-versioned.

At the top level it holds the run id and directory, the mode (`mock` or
`real`), status, start and end times, the full validated plan, the environment
(agent version, platform, Python version and executable, process id), the
execution block (which executor, the budget policy and its decision, the
resource estimate, and every job handle), and the accumulated warnings.

Each task record holds:

| Field | Content |
|---|---|
| `parameters` | the **resolved** parameters, after `${task.outputs.field}` substitution, so you see the values actually used |
| `command` | the exact argument vector when a command-line tool was invoked |
| `outputs` | the adapter's output object, schema-validated |
| `adapter_metadata` | adapter name and version, device, package versions, model repository and immutable revision, the exact Python call |
| `validations` | every check with its verdict and message |
| `artifacts` | relative path, SHA-256, size and media type for each file produced |
| `started_at`, `ended_at`, `attempts`, `status`, `error` | timing, retries, outcome |

A real example, the Aframe task of the S231123cg run:

```
adapter        aframe-buoy-v0.2, device cuda, 16352 inference steps
packages       torch 2.10.0, ml4gw 0.8.3, ml4gw-buoy 0.6.1, h5py 3.16.0
model          ML4GW/aframe @ 3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4
validations    task_condition, input_json_schema, output_json_schema,
               output_field:detection_statistic, artifact_exists:output_artifact
artifact       artifacts/run_aframe/aframe_outputs.hdf5
               sha256 85b10eedc11cb8ecc784e7d08a6f25a5fd82c6c8ae75a5ebd035f379040b59b5
               404728 bytes
timing         2026-09-09T02:00:00.913Z to 02:00:35.193Z, 1 attempt
```

The command and adapter metadata are written *before* execution, so a task that
dies still leaves the exact call that was attempted.

What this buys, concretely:

- **Reproducibility**: the same request, model revisions, package versions and
  seed can be replayed from the manifest.
- **Auditability**: a reviewer checks any number in the talk without rerunning
  anything, and the artifact hash proves the file was not edited afterwards.
- **Attribution**: "which model version produced this?" is answered by the
  record, not by memory.
- **Recalibration**: because thresholds and their provenance are recorded,
  growing the background from 5.5 to 69 days let us re-label every earlier
  candidate automatically; 59 of 60 survived the tighter cut.
- **Cost accounting**: the timing fields across 113 manifests produce the
  measured cost table, which is also what the budget policy is calibrated on.
- **Failure provenance**: the failed runs discussed above are readable months
  later because the reason, the detector and the interval are in the record.
