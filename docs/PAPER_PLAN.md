# Paper plan — agentic orchestration for ML4GW (drafted 2026-09-04)

## 1. Literature check (what is already done)

**O3 reanalyses with machine learning are published; a new O3 search is not a
contribution.**

| work | data | result | venue |
|---|---|---|---|
| Marx et al., "A machine learning-enabled search for BBH mergers in O3" (arXiv:2505.21261) | full O3, H1L1, 202.4 d coincident livetime, 100 yr time-slide background | 38 of 70 H1L1 GWTC-3 events at p_astro > 0.5; no new candidates; misses explained by m2 < 5 Msun (training range) and SNR < 12.6 | preprint (Aframe team) |
| Aframe pipeline paper (arXiv:2403.18661) | O3 injections | 3.1 s median latency; state-of-the-art at high mass | PRD 111, 042010 (2025) |
| AMPLFI (arXiv:2407.19048; 2509.22561) | O3 injections, BAYESTAR comparison | equivalent searched area/volume; ~6 s Aframe+AMPLFI latency | PRD (2025) |
| Koloniari et al., AresGW (10.1088/2632-2153/adb5ed) | O3 (6.7 months H1L1) | 8 new candidates with p_astro > 0.5; FAR from time-shifted background | MLST (2025) |
| Silver, Krastev, Berger (arXiv:2512.17204) | O1–O3 | 57 of 75 catalogued BBH; 57 false positives | preprint |
| Beveridge et al. (arXiv:2512.04516) | O3 | 31 LVK candidates + 1 IAS + 1 new (p_astro 0.63) | preprint |
| GWAK (10.1088/2632-2153/ad3a31) | O3a | semi-supervised anomaly detection | MLST 5, 025020 (2024) |
| DeepClean | O2/O3 (60 Hz, 21 witnesses) | nonlinear coupling subtraction | PRR 2, 033066 (2020); CQG (2024, low-latency) |

Consequence: in this paper an O1–O3 population run is a **validation of the
orchestration layer against published results** (does the agent reproduce
Marx et al.'s recovery pattern, GWTC parameters and sky areas with full
provenance?), not a search.

**Agentic AI for science: where comparable papers landed.**

| work | domain | venue |
|---|---|---|
| Coscientist (Boiko et al.) | autonomous chemistry | Nature 624 (2023) |
| ChemCrow (Bran et al.) | LLM + 18 chemistry tools | Nat. Mach. Intell. 6 (2024) |
| Virtual Lab (Swanson et al.) | LLM agent team, nanobody design, wet-lab validated | Nature (2025) |
| Co-Scientist (Google DeepMind) | hypothesis generation, validated experimentally | Nature (2026) |
| AI Scientist / end-to-end automation of AI research | ML research automation | Nature (2026) |
| Mephisto (Sun, Ting et al.) | LLM agents for multiband galaxy SED analysis with CIGALE; 256 COSMOS galaxies + 31 JWST LRDs; seven LLM backbones; expert comparison | **ApJS (2026)** |
| CMBAgent / Denario (Laverick et al.) | multi-agent cosmological parameter analysis; "Competing with AI scientists" (arXiv:2604.09621) | ICML-W 2025, preprints |
| "Plausible but Wrong" (Rawat & Flek, arXiv:2604.25345) | 18 astrophysical tasks with CMBAgent: silent incorrect computation is the dominant failure | preprint |
| gwBenchmarks (Islam, Wadekar, Zhou, arXiv:2605.11269) | 12 coding agents on 8 GW tasks: metric misuse, constraint violations, fabricated results | preprint |
| HEP analysis agents (Gendreau-Distler et al., arXiv:2512.07785) | supervisor-coder agent + Snakemake, ATLAS open data; success rate, cost, stability across Gemini/GPT-5/Claude | NeurIPS-W 2025 |
| Nature editorial "AI isn't ready to research itself" (2026) | reliability of research agents | Nature |

Reading: Nature-family papers carry an *experimentally validated discovery*;
ApJS accepted an agent framework paper on the strength of a large validation
sample, multi-backbone evaluation and expert comparison; MLST is the home of
the ML4GW method papers. Two 2026 preprints establish the failure mode our
design addresses (silent, plausible-but-wrong results), and nobody has yet
published an agent that drives *production* GW ML pipelines with typed
contracts and fail-closed execution.

## 2. Positioning

Title (working): *An agentic orchestration layer for machine-learning
gravitational-wave analysis: typed skill contracts, fail-closed execution and
calibrated multi-model inference.*

Claims, each with an experiment:

1. **Contracts turn LLM plans into executable, auditable science.** Planner
   benchmark (≥ 300 prompts, three Claude backbones), validity / route
   accuracy / reproducibility, ablation with contract validation disabled.
2. **Fail-closed execution removes silent failures.** Adversarial suite of
   prompts designed to elicit plausible-but-wrong outputs (public data with
   DeepClean, AMPLFI without a candidate, unpinned models, out-of-range
   masses, non-public events, unbounded scans). Metric: fraction that fail
   closed with a correct reason vs execute silently; compared with a
   contract-free agent baseline.
3. **The layer reproduces published science end to end with provenance.**
   O1–O3 population (90 GWTC events, 79 in O3) through Aframe + AMPLFI +
   GWAK on the CIT HTCondor pool from LDG frames; recovery vs Marx et al.
   2025, AMPLFI medians vs GWTC-2.1/3, sky areas, GWAK score distribution;
   every result traceable to a manifest with SHA-256 artifacts.
4. **Significance is calibrated, not asserted.** Aframe and GWAK time-shift
   backgrounds extended to ≥ 30 d each; injections (IMRPhenomD via ml4gw)
   into O3 noise for Aframe/GWAK efficiency vs SNR; DeepClean signal
   preservation with injections.
5. **Cost is bounded and measured.** GPU-hours per event, HTCondor vs local
   latency, segmented long scans, budget policy in action.

Venue: **ApJS** primary (precedent: Mephisto 2026; software + population
validation), MLST as fallback; PRD only if a physics result is added.

## 3. Data policy

The paper uses GWOSC public data (O1–O3) only. The O4 results (S250119cv,
DeepClean training on O4 witnesses) are collaboration data and are kept in a
separate supplementary section that either goes through LVK Presentations &
Publications review or is dropped before submission.

## 4. Work packages

| WP | content | where | owner |
|---|---|---|---|
| A | planner benchmark v2 (≥ 300 prompts, three backbones, ablation), adversarial silent-failure suite, contract-free baseline | local + Anthropic API | subagent (worktree) |
| B | injection framework: ml4gw waveform injection into strain artifacts, Aframe/GWAK efficiency vs SNR, DeepClean preservation with injections | GPU node | subagent (worktree) |
| C | O1–O3 population run through the agent on CIT HTCondor; comparison tables with GWTC and Marx et al. | CIT | main session |
| D | background extension ≥ 30 d for Aframe and GWAK | CIT GPUs | main session |
| E | cost/scalability tables from manifests | local | main session |
| F | manuscript (AASTeX for ApJS), figures | local | main session |

Event list: `benchmarks/population/events.json` (GWOSC event API, GWTC-1,
GWTC-2.1-confident, GWTC-3-confident; 90 unique events, 73 O3 events with
m2 ≥ 5 Msun inside Aframe's training range).
