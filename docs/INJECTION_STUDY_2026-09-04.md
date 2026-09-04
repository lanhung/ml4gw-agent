# Injection study — Aframe and GWAK efficiency, DeepClean signal preservation (2026-09-04)

Work package B of `PAPER_PLAN.md`. Everything below was produced by the
adapters the planner runs (`aframe.detect`, `gwak.scan`,
`deepclean_model.clean_strain`) on the GPU node; evidence in
`docs/acceptance/injections-2026-09-04/` (`injection_study.json` with every
injection's parameters and adapter outputs, `efficiency.png`,
`deepclean_injections.json`).

## Injection framework

`src/ml4gw_agent/adapters/injection.py`:

- `project_bbh`: IMRPhenomD through `ml4gw.waveforms.generator.
  TimeDomainCBCWaveformGenerator` (f_min = f_ref = 20 Hz, 8 s, coalescence
  0.5 s before the end), projected onto the detectors with
  `ml4gw.gw.compute_observed_strain` (sky position converted to detector
  frame with the Greenwich sidereal time of the injection time).
- `welch_psd` / `optimal_snr` / `scale_to_snr`: per-detector optimal SNR
  against the median-Welch PSD of the artifact itself (4 s FFTs, 20 Hz
  low cut), network SNR in quadrature, amplitude rescaled to the requested
  network SNR (the equivalent luminosity distance is recorded).
- `inject`: adds the projected signals with the coalescence at `tc`, and
  appends the full parameter record to an `injections` attribute of the
  strain artifact, so an injected artifact carries its own provenance.

The NumPy bookkeeping is unit-tested locally (`tests/test_injection.py`);
the torch path was verified on the node (merger sample 30720 vs. envelope
peak 30649 at 4096 Hz; requested network SNR 12.0 reproduced to 0.3 % by an
independent optimal-SNR calculation on the injected strain).

## Aframe and GWAK efficiency versus injected SNR

`scripts/injection_study.py`, run as

```
CUDA_VISIBLE_DEVICES=2 GWPY_CACHE=1 HF_ENDPOINT=https://hf-mirror.com \
  .venv/bin/python scripts/injection_study.py \
  --output /root/autodl-tmp/ml4gw-agent-runs/injections/study \
  --runs-dir /root/autodl-tmp/ml4gw-agent-runs/injections/study-runs \
  --n-per-bin 25 --controls 25
```

Setup: 128 s H1+L1 windows read from the cached public GWOSC 4096 s
stretches around GW150914 (O1), GW170817 (O2) and GW190521 (O3), the real
events and the first/last 32 s excluded, windows with gaps skipped (two O1
windows where L1 was not observing); 84 usable windows. Injection at 96 s
into the window; masses m1 ~ U(10, 80) Msun, m2 ~ U(10, m1), aligned spins
U(-0.5, 0.5), isotropic orientation and sky; 25 injections per SNR bin
{6, 8, 10, 12, 15, 20, 30} plus 25 windows without injection (controls);
200 analyses, 6.2 s median per injection for both adapters, no errors.
Each window is written as the 4096 Hz artifact for `gwak.scan` and the
2048 Hz artifact for `aframe.detect`, and both adapters run with the
calibrated 1/day thresholds (Aframe 2.701 for revision `3c947f6d…`, GWAK
25.55 for `gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad`), the
injection time as `target_time`, seed 0.

| network SNR | Aframe candidate (1/day cut, peak within 2 s) | GWAK anomaly (1/day cut) | GWAK: injection is the loudest kernel | GWAK: z ≥ 5 at the injection |
|---:|---:|---:|---:|---:|
| 6 | 1 / 25 | 0 / 25 | 0 / 25 | 6 / 25 |
| 8 | 12 / 25 | 0 / 25 | 1 / 25 | 9 / 25 |
| 10 | 18 / 25 | 0 / 25 | 13 / 25 | 16 / 25 |
| 12 | 23 / 25 | 0 / 25 | 14 / 25 | 19 / 25 |
| 15 | 22 / 25 | 0 / 25 | 22 / 25 | 23 / 25 |
| 20 | 25 / 25 | 0 / 25 | 17 / 25 | 19 / 25 |
| 30 | 25 / 25 | 0 / 25 | 22 / 25 | 22 / 25 |
| controls (no injection) | 0 / 25 false candidates | 0 / 25 | 0 / 25 | 8 / 25 |

Interpolated levels (linear between bins):

| quantity | SNR at 50 % | SNR at 90 % |
|---|---:|---:|
| Aframe candidate at 1/day | **8.2** | **11.8** |
| GWAK anomaly at 1/day | — (never) | — |
| GWAK injection loudest kernel | 9.9 | not reached (plateau ≈ 88 %) |
| GWAK z ≥ 5 | 9.0 | 14.6 (but 32 % of controls also pass) |

Reading:

- **Aframe** behaves like a search: no false candidate in 25 control
  windows (largest control statistic 1.84 against the 2.70 cut), 50 %
  efficiency at network SNR 8.2 and 90 % at 11.8, consistent with the
  SNR ≈ 12.6 recovery boundary Marx et al. (2025) report for the O3 search
  at a far tighter false-alarm rate. Recovered coalescence times sit
  12 ms before the injected time (median), 90 % within 51 ms. The five
  misses above SNR 12 are one heavy system (80+60 Msun, statistic 2.16,
  just below the cut), three moderate systems with statistics 1.2–2.7,
  and one SNR-15 injection (49+11 Msun, O2) whose loudest peak fell 98 s
  away, so the adapter refused it as this target's candidate. Per-run
  efficiency at SNR 8–12 is the same within counting errors (O1 17/25,
  O2 18/24, O3 18/26).
- **GWAK** never reaches the 1/day cut of 25.55, as expected from the
  glitch-dominated background (`PHASE2_GWAK_RUN_2026-09-03.md`): the
  measured rate at the injection scores is 4e5 /yr at SNR 10 and 9e3 /yr
  from SNR 15 upward. As a *ranking* statistic it does respond: from
  SNR 15 the injection is the loudest kernel of its 128 s window in
  22 of 25 cases. The plateau below 100 % is mass-dependent: all eleven
  SNR ≥ 20 injections that were not the loudest kernel have m1 ≤ 24 Msun
  (chirp mass ≤ 20 Msun), i.e. long inspirals whose power is spread over
  many 0.5 s kernels, while the loudest-kernel criterion asks for a single
  kernel within 0.6 s of the coalescence. The z ≥ 5 criterion is not
  usable as a detection statement: 8 of 25 control windows exceed it.
- The two adapters therefore play the roles the reconcile logic assumes:
  Aframe carries the significance, GWAK supplies morphology ranking, and
  the calibrated GWAK flag stays off unless something louder than the
  detector glitch population appears.

## DeepClean signal preservation with injections (collaboration data)

**This section uses non-public O4 data (H1, GPS 1421348096–1421349120, the
held-out part of the DeepClean training file fetched through NDS2). It
stays out of the public paper unless it passes LVK review.**

`scripts/deepclean_injection_study.py`, run as

```
CUDA_VISIBLE_DEVICES=3 .venv/bin/python scripts/deepclean_injection_study.py \
  /root/autodl-tmp/deepclean/H1_1421344000_5120.hdf5 \
  --weights models/deepclean/H1_60Hz/deepclean.pt --n-per-bin 8 \
  --output /root/autodl-tmp/ml4gw-agent-runs/injections/deepclean_injections.json
```

32 IMRPhenomD injections (H1 optimal SNR 10, 15, 20, 30; eight each; masses
as above) into 128 s windows of the held-out strain. Both the raw and the
injected strain are cleaned with the shipped 60 Hz model, and the recovered
signal `clean(s + h) − clean(s)` is compared with the injected `h`.

| H1 SNR | n | match(recovered, injected) median / min | optimal-SNR ratio after/before | matched-filter SNR change (median) | in-band ASD ratio (55–65 Hz) |
|---:|---:|---:|---:|---:|---:|
| 10 | 8 | 1.0000 / 1.0000 | 1.0000 | +0.001 | 0.899 |
| 15 | 8 | 1.0000 / 1.0000 | 1.0000 | +0.003 | 0.899 |
| 20 | 8 | 1.0000 / 1.0000 | 1.0000 | −0.002 | 0.899 |
| 30 | 8 | 1.0000 / 1.0000 | 1.0000 | +0.003 | 0.899 |

The match is unity to double precision because the DeepClean estimate is a
function of the witness channel only: `clean(s + h) − clean(s) = h`
exactly, whatever `h` is. The study therefore confirms the *implementation*
(no path from the strain into the subtracted noise, e.g. through the
scalers or batch statistics), and the matched-filter SNR of the injection
changes by less than 0.01 while the 55–65 Hz ASD drops by 10 % (60 Hz line
by ~7×). A model that used the strain as an input (as some DeepClean
variants do for training) would need this test in earnest; for the
witness-only model the guarantee is structural and the test is a
regression check.

## What this does and does not establish

- Establishes: an injection framework with provenance; Aframe efficiency
  curves at the calibrated 1/day cut with zero false candidates in the
  controls; GWAK's usable role (ranking, not significance) and its
  low-mass blind spot; DeepClean's structural signal preservation.
- Does not establish: efficiency at the search-level FARs of the published
  O3 analyses (needs the ≥ 30 d backgrounds of work packages C/D), a
  precession/higher-mode waveform family (IMRPhenomD only, aligned spins),
  or a mass-binned efficiency with meaningful counts (25 per SNR bin over
  the whole 10–80 Msun range).
