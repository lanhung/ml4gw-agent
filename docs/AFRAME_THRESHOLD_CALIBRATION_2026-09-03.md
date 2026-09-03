# Aframe threshold calibration — time-shifted background study — 2026-09-03

Closes the Phase 1b item "FAR-calibrated Aframe threshold from a background
study" for the false-alarm rate the study livetime can measure (1 per day).
Script: `scripts/aframe_background.py`; table update:
`scripts/update_aframe_calibration.py`; shipped table:
`src/ml4gw_agent/calibration/aframe_thresholds.json`; raw results:
`docs/acceptance/aframe-background-2026-09-03/aframe_background_final_123lags.json`
(final) and `aframe_background_interim_28lags.json` (the interim state the
first verification runs used).

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
- Final state: 41 lags per stretch (zero lag plus 40 shifts), 123 analyses,
  5.54 days of livetime, 44137 clustered peaks, about 100–112 s of GPU time
  per analysis on the RTX 5000 Ada (3.6 h in total).

## Result

| Quantity | Value |
|---|---|
| peak-statistic median / 99 % / 99.9 % / 99.99 % | −0.70 / 0.81 / 1.87 / 2.67 |
| loudest background peaks | 3.47, 3.33, 2.84, 2.73, 2.70, 2.62, 2.57 |
| FAR at 1.0 / 2.0 / 2.5 / 3.0 | 18992 / 1912 / 462 / 132 per year |
| **threshold for FAR 1 per day** (365.25 / yr) | **2.701** (five background peaks above it in 5.54 days) |
| 1 per month, 1 per year | not measurable with 5.54 d (would need 30 d / 365 d); left out of the table on purpose |

Interim table (29 lags, 1.26 d) had put the 1/day threshold at 3.468, set by
the single loudest peak; the final value 2.701 is set by the fifth loudest
peak and is the one shipped.

Reference values from the acceptance runs (same statistic): GW150914 9.51,
GW190521 8.73, GW170817 −0.13, noise segment 1126260200 0.51.

With five background peaks above 2.70 in 5.54 days the 1/day rate is
measured, not bounded, but its Poisson uncertainty is still about 45 %.
The separation from the real signals (GW150914 9.51, GW190521 8.73) is
more than a factor of three in the statistic, while the loudest background
peak in 5.5 days is 3.47. Tighter rates (1/month, 1/year) need 30 days to a
year of background livetime, which is 6 to 70 GPU hours on this node with
the same script; the table refuses to serve them rather than extrapolate.

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
