# Population run: 90 GWTC events through the agent on the CIT HTCondor pool (2026-09-04)

Work package C of `PAPER_PLAN.md`. Evidence: `docs/acceptance/population-2026-09-04/`
(one `run_manifest.json` per event, `summary.json`, `population_stats.json`,
`POPULATION.md`, `population.png`, `population.log`). Driver:
`scripts/cit/population_run.sh` (8 whole-plan HTCondor submissions in
parallel, `--data-source gwosc`, public data only); comparison:
`scripts/population_compare.py` and `scripts/population_figures.py`.

Request per event: "Fetch strain data for <GPS>, check data quality, run
Aframe detection and AMPLFI parameter estimation, then scan anomalies with
GWAK and reconcile the two results." with `--ifos H1 L1 --aframe-far 365.25
--gwak-far 365.25` and the pinned revisions (Aframe `3c947f6d…`, AMPLFI
`8b97d2f8…`, GWAK `gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad`).
Events: `benchmarks/population/events.json` (GWTC-1, GWTC-2.1-confident,
GWTC-3-confident; 11 O1/O2, 79 O3).

## Outcome by stage

| stage | events | note |
|---|---:|---|
| requested | 90 | |
| `fetch_data` failed closed | 7 | no public H1 or L1 data in the 128 s window (single-LIGO events: GW190620_030421, GW190630_185205, GW190708_232457, GW190925_232845, GW191216_213338, GW200112_155838, GW200302_015811) |
| `inspect_data` gate failed, Aframe/AMPLFI/GWAK skipped | 7 | H1 samples not finite or `H1_DATA` flag not covering the window (GW170608, GW190425, GW190513_205428, GW190725_174728, GW190814, GW190910_112807, GW200316_215756) |
| analysed end to end | 76 | |

Every non-analysed event carries its reason in the manifest; nothing was
retried by hand. The first pass lost 36 workers to `SIGILL` on the pool's
x86-64-v1 nodes (no AVX); the drivers now require `Microarch >= x86_64-v2`
and the affected events were resubmitted (`population.log`).

## Aframe (calibrated 1/day threshold 2.701, 2 s candidate window)

| quantity | value |
|---|---|
| candidates | 60 of 76 analysed; 60 of 71 with m2 ≥ 5 Msun (the model's training range) |
| misses with m2 < 5 Msun | 5 (GW170817, GW200115_042309, GW191219_163120, GW200210_092254, GW190917_114630) |
| misses with m2 ≥ 5 Msun, catalog SNR | 11: 4.7, 7.2, 7.4, 7.6, 7.8, 7.9, 8.3, 9.3, 10.8, 10.9, 12.0 |
| coalescence-time offset from catalog (candidates) | median 0.037 s, 90 % within 0.083 s |

Recovery by catalog network SNR (analysed events):

| SNR | < 8 | 8–10 | 10–12 | 12–15 | 15–20 | ≥ 20 |
|---|---:|---:|---:|---:|---:|---:|
| found / of | 2 / 8 | 18 / 23 | 12 / 15 | 17 / 18 | 7 / 7 | 4 / 5 |

Comparison with the published Aframe O3 search (Marx et al. 2025, 38 of
70 H1L1 GWTC-3 events at p_astro > 0.5 against a 100-year background): this
is a targeted analysis (known time, 128 s window, 1/day threshold), so a
higher recovery is expected and the two numbers are not competing
sensitivities. The pattern of misses matches theirs: sources below the
training mass range and network SNR below about 12.

## AMPLFI (HL model, 128 s window, candidates only)

| parameter | catalog inside AMPLFI 90 % interval | median(AMPLFI median / catalog) |
|---|---:|---:|
| source-frame chirp mass | 54 / 60 | 1.074 |
| luminosity distance | 37 / 60 | 0.715 |

Chirp-mass coverage is at the nominal 90 %; distances are biased low by
about 30 % relative to the catalog (which uses three-detector data and
different priors), a known behaviour of the two-detector model that the
AMPLFI paper also discusses. `population.png` shows the scatter.

## GWAK (1/day cut 25.55 from the 5.56 d study)

76 events scored; the target kernel is the loudest of its window for 31 and
within the top 10 for a further 16; median z-score at the target 8.8; no
event exceeds the glitch-dominated 1/day cut, as expected from
`PHASE2_GWAK_RUN_2026-09-03.md`. `target_far_per_year` is recorded per event.

## Cost

One event is one HTCondor job (fetch at 2048 and 4096 Hz, inspect, Aframe,
AMPLFI, GWAK, reconcile, report) on one GPU slot; wall time per job is in
the manifests (`scripts/cost_table.py`). The 90 submissions used about 12
concurrent slots of the pool's 112 AVX-capable GPU slots.
