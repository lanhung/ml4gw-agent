# Phase 2 — GWAK route on real data — 2026-09-03

Evidence: `docs/acceptance/gwak-route-2026-09-03/<case>/run_manifest.json`
(runs on the GPU node, prompt "Run Aframe and GWAK on <event> and reconcile
the two results.", `--gwak-revision gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad`).

## Models

Upstream ML4GW/gwak publishes no inference package or weights. The models
used here are the user's own GWAK 2.0 training on the CIT LDG cluster
(repository commit `7b9f58a`, home-directory checkout), exported as
TorchScript and pinned by SHA-256 in `models/gwak/MANIFEST.json`:

| Role | File | Input | Output |
|---|---|---|---|
| embedder | `embedder_S4_SimCLR_multiSignalAndBkg.pt` (`f775aed5…`) | (batch, 2, 2048) whitened H1+L1 at 4096 Hz | (batch, 8) |
| metric | `metric_NF_onlyBkg.pt` (`a0c755ad…`) | (batch, 8) | log probability under the background flow |

Anomaly score = −log p. Preprocessing follows the training configuration
(4096 Hz, 0.5 s kernels, PSD from the first 64 s, 1 s whitening filter, 2 s
FFT); highpass 30 Hz and the 1/16 s stride are adapter parameters recorded
in every manifest. Two implementation findings: the exported flow hard-codes
CPU float64 inside its graph (it runs on the CPU on the embeddings), and
strain must be normalised before whitening because its PSD (~1e-42)
underflows float32.

## Results (1001 kernels per 62.5 s analysis segment)

| Case | Aframe statistic / candidate | GWAK max | GWAK median | score at target | z at target | rank of target kernel | reconcile route |
|---|---|---:|---:|---:|---:|---:|---|
| GW150914 | 9.506 / yes | 15.35 | 12.93 | 15.35 | 10.5 | 0 of 1001 | consistent_candidate |
| GW190521 | 8.733 / yes | 14.30 | 12.83 | 14.30 | 11.8 | 0 of 1001 | consistent_candidate |
| noise GPS 1126260200 | 0.513 / no | 14.04 | 12.90 | 13.25 | 1.5 | 153 of 1001 | gwak_only (see below) |
| GW170817 (GPS 1187008882.4) | −0.129 / no | 13.99 | 12.83 | 13.30 | 4.3 | 47 of 1001 | gwak_only |

The two binary black hole events are the loudest kernel of their windows at
exactly the catalog time; the noise segment's loudest kernel (14.04) sits
between the two events' peaks, so the separation is real but small with
these checkpoints. GW170817 gets a mild response (z 4.3) but is not the
loudest kernel.

`anomaly_found` is still the raw `threshold: 0.0` cut, so it is true for
every window and the reconcile route reports `gwak_only` on the noise
segment. As for Aframe, the threshold needs a time-shifted background
study before the flag means anything; until then `target_score`,
`target_zscore` and `target_rank` are the quantities to read.

## Stride matters

With the first default stride of 0.25 s the score was flat (12.685) because
the strain PSD underflowed, and after that fix the 0.25 s grid still missed
the 0.2 s chirp: max 14.13 at 2.6 s before the merger. At 1/16 s the peak
aligns with the merger on both events. The GWAK deploy pipeline's own
inference sampling rate is not in the exported configuration; this is one
of the questions for the GWAK team.

## Open

- Threshold calibration (time-shifted background, same method as Aframe).
- Confirmation from the GWAK authors of the embedder/metric pairing (the CIT
  checkout also holds `linear_metric/SimCLR_multiSignal_all` linear and MLP
  metrics and an `FM_multiSignalAndBkg` classifier trained on another
  embedder), the highpass, and the inference stride.
- Injection and glitch sets for the acceptance suite.

## Threshold calibration and model-pairing decision (2026-09-04)

Upstream GWAK 2.0 will not release for at least three months (developer
conversation, 2026-09-03), so the pairing shipped here is the agent's best
guess, chosen empirically among the user's exported checkpoints on CIT:

| embedder | metric | separates GW150914 / GW190521 from their windows? |
|---|---|---|
| S4 SimCLR `f775aed5` | normalizing flow trained on background only `a0c755ad` | **yes** (z 10.5 / 11.8, rank 0 of 1001) |
| S4 SimCLR | linear / MLP metrics | no |
| Tarantula embedder | any metric | no (whitened output collapses) |

Preprocessing that made it work: strain normalised by its standard deviation
before whitening (float32 underflow otherwise), 4096 Hz, 0.5 s kernels,
64 s PSD, 1 s fduration, 30 Hz high-pass, 1/16 s stride, flow on CPU in
float64 (hard-coded upstream).

### Time-shifted background (`scripts/gwak_background.py`)

Same protocol as the Aframe study (`AFRAME_THRESHOLD_CALIBRATION_2026-09-03.md`):
GWOSC stretches around GW150914, GW170817 and GW190521 with the events
excluded, L1 shifted by multiples of 8 s, 40 shifts per stretch, 123 lags.
Result `docs/acceptance/gwak-background/gwak_background.json`, folded into
`calibration/gwak_thresholds.json` for revision
`gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad`:

| quantity | value |
|---|---|
| livetime | 5.56 d (480 431 s), 44 813 clustered peaks |
| peak median / 99 % / 99.9 % | 13.77 / 14.19 / 24.29 |
| loudest background peaks | 25.91, 25.75, 25.63, 25.62, 25.55 |
| threshold at 1 per day | **25.55** (tighter rates need more livetime) |
| per-stretch loudest lag maxima (median over lags) | O1 GW150914 stretch 24.1, O2 GW170817 stretch 20.0, O3 GW190521 stretch 25.2 |

The distribution is bimodal: the Gaussian-like bulk ends near 14.2, and
every lag of every stretch carries one peak at 20–26. A time shift moves
only L1, so a loud single-detector transient in either detector reappears
in every lag; those peaks are glitches in the stretches, and GWAK (an
"anything that is not background" detector) scores them above the two
binary black hole mergers (15.35 and 14.30). Measured rates at the event
scores, from the study's FAR curve (now reported by `gwak.scan` as
`target_far_per_year` / `max_far_per_year`):

| score | background rate |
|---|---|
| 15.35 (GW150914 at target) | 9.0e3 / yr (25 / day) |
| 14.30 (GW190521 at target) | 1.2e4 / yr |
| 13.3 (noise and GW170817 windows) | 2.8e6 / yr |
| ≥ 25.55 | 1 / day |

Consequences, recorded rather than hidden: with `--gwak-far 365.25` the
planner passes the calibrated 25.55 cut, so `anomaly_found` is false for
the BBH events (they are not louder than the stretches' glitches), while
`target_zscore` and `target_rank` still separate them from the Gaussian
bulk. Glitch rejection (a veto or a glitch-trained metric) is what the
upstream release is expected to add; until then the reconcile route treats
GWAK as a morphology hint, not a significance statement. The 1/day
threshold is measurable from 5.56 d; anything tighter needs a longer study
(`--shifts N`, ~28 s of GPU per lag).

### The four cases rerun with the calibrated cut (2026-09-03 23:22 UTC)

`docs/acceptance/gwak-calibrated-2026-09-04/<case>/run_manifest.json`,
prompt unchanged, `--gwak-far 365.25` (all tasks completed, Aframe results
identical to the table above):

| case | GWAK score at target | z | rank | measured rate at that score | `anomaly_found` at 1/day (cut 25.55) |
|---|---:|---:|---:|---:|---|
| GW150914 | 15.35 | 10.5 | 0 of 1001 | 9.0e3 / yr | false |
| GW190521 | 14.30 | 11.8 | 0 of 1001 | 1.2e4 / yr | false |
| noise 1126260200 | 13.25 | 1.5 | 153 | 2.9e6 / yr | false |
| GW170817 | 13.30 | 4.3 | 47 | 2.8e6 / yr | false |

`threshold_calibrated` is now true and the uncalibrated-threshold warning
is gone; the flag is honest (nothing in these windows is louder than the
glitch population), and the per-score rates give the reader the actual
separation: the two BBH mergers sit two to three orders of magnitude below
the noise/GW170817 windows in background rate, while still 300× above the
1/day glitch floor.
