# Aframe threshold calibration — interim background study — 2026-09-03

Closes the Phase 1b item "FAR-calibrated Aframe threshold from a background
study" for the one false-alarm rate the study livetime can measure so far.
Script: `scripts/aframe_background.py`; table update:
`scripts/update_aframe_calibration.py`; shipped table:
`src/ml4gw_agent/calibration/aframe_thresholds.json`; raw result:
`docs/acceptance/aframe-background-2026-09-03/aframe_background_interim_28lags.json`.

## Method

- Model: `ML4GW/aframe` revision `3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4`
  through `buoy.models.Aframe`, exactly as `aframe.detect` runs it; statistic
  = Buoy's offline integrated output (`signif_integrated`), the quantity the
  agent reports as `detection_statistic`.
- Data: the three cached public GWOSC 4 kHz stretches (H1+L1, resampled to
  2048 Hz as Buoy does): O1 `[1126256829, 1126260736)` (3907 s after
  dropping a 189 s L1 gap), O2 `[1187006835, 1187010931)`, O3
  `[1242440920, 1242445016)`; ±16 s around GW150914, GW170817, GW190521
  excluded (also at the shifted position), first 80 s of every analysis
  (PSD/whitening start-up) dropped.
- Background: zero lag plus circular time shifts of L1 against H1 in 8 s
  steps; peaks clustered with an 8 s minimum separation; FAR(x) = number of
  peaks ≥ x divided by the summed livetime.
- Interim state used here: 29 lags, 1.26 days of livetime, 10121 clustered
  peaks. The study continues to 41 lags per stretch (about 5.4 days); the
  table is refreshed from the final file with the same script.

## Result

| Quantity | Value |
|---|---|
| peak-statistic median / 99 % / 99.9 % / 99.99 % | −0.58 / 0.76 / 1.75 / 2.73 |
| loudest background peaks | 3.47, 2.73, 2.62, 2.28, 2.00 |
| FAR at 1.0 / 2.0 / 3.0 | 18784 / 1156 / 289 per year |
| **threshold for FAR 1 per day** (365.25 / yr) | **3.468** (just above the loudest peak; upper-bounded by the livetime) |
| 1 per month, 1 per year | not measurable with 1.26 d; left out of the table on purpose |

Reference values from the acceptance runs (same statistic): GW150914 9.51,
GW190521 8.73, GW170817 −0.13, noise segment 1126260200 0.51.

The 3.47 threshold is a one-sided bound set by the single loudest
background peak in 1.26 days; its statistical uncertainty is therefore
large and it should be read as "a peak louder than any of ~10 000
background peaks", not as a precise 1/day rate. Longer livetime will move
it; tighter rates need days to years of background that this node cannot
compute quickly (about 100 s of GPU time per 3900 s stretch).

## Verification on real data (same node, calibrated plan)

`ml4gw-agent run ... --aframe-far 365.25` on the decomposed plan:

| Case | statistic | threshold | `threshold_calibrated` | `candidate_found` | AMPLFI |
|---|---:|---:|---|---|---|
| GW150914 | 9.5059 | 3.468 | true (FAR 365.25/yr, livetime 105437 s recorded) | true (peak +0.014 s from target) | completed |
| noise GPS 1126260200 | 0.5129 | 3.468 | true | **false** (peak 58.9 s from target, below threshold) | **skipped** |

Both manifests record `threshold_calibration` (revision, FAR, livetime,
source) on the Aframe task; the uncalibrated-threshold warning is no longer
emitted for calibrated plans. Requests for a FAR the study cannot measure
(default 1 per year) still fall back to the raw cut with an explicit
warning, so the run's own metadata says which regime it is in.
