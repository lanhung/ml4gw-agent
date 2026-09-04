# Extended time-shift backgrounds for Aframe and GWAK (2026-09-04)

Work package D of `PAPER_PLAN.md`. Evidence: `docs/acceptance/background-extended-2026-09-04/`
(`aframe_background_merged.json`, `gwak_background_merged.json`, the shard
list `stretches.txt`, the HTCondor submit file; the clustered peak arrays
`*_peaks.npy` are kept outside git). Driver: `scripts/cit/background_submit.sh`
(72 GPU jobs on the CIT pool, one per stretch and pipeline), merged with
`scripts/merge_background.py`, folded into the calibration tables with
`scripts/update_aframe_calibration.py`.

Protocol (unchanged from the first study): 36 event-free H1L1 coincident
GWOSC stretches of 4096 s (30 in O3a/O3b, 6 in O2; chosen from the GWOSC
segment lists with no catalog event within 64 s, seed 20260904), L1
shifted against H1 by 8 s multiples, 40 lags per stretch, peaks clustered
within 8 s, FAR(x) = N(peaks ≥ x) / livetime. A rate is reported only when
the livetime holds at least one expected background event at that rate.

| pipeline | livetime | peaks | 1/day threshold | 1/month threshold | loudest peaks |
|---|---:|---:|---:|---:|---|
| Aframe `3c947f6d…` (integrated statistic) | 68.60 d | 546 923 | **2.986** (was 2.701 from 5.5 d) | **4.398** | 4.54, 4.40, 4.31, 4.22, 4.19 |
| GWAK `gwak2-7b9f58a-S4SimCLR…` (score) | 68.86 d | 554 049 | **27.85** (was 25.55 from 5.56 d) | **28.23** | 28.23, 28.23, 28.21, 28.19, 28.13 |

Peak quantiles: Aframe median −0.78, 99 % 0.91, 99.9 % 2.01, 99.99 % 3.08;
GWAK median 13.7, 99 % 15.7, 99.9 % 26.3, 99.99 % 28.0. The GWAK
distribution keeps its two components (Gaussian bulk to ~15.7, one
glitch-level peak per lag at 20–28); the extended O2/O3 sample contains
louder glitches than the first three stretches, which moves both the
1/day and the 1/month cuts to the glitch floor.

## Effect on the results already reported

The population run and the injection study used the first study's 1/day
thresholds (Aframe 2.701, GWAK 25.55), which are recorded in every
manifest. Against the extended study:

- Aframe: 59 of the 60 population candidates stay above the new 1/day cut
  (2.986); 54 of 60 stay above the 1/month cut (4.398). Injection
  efficiencies at the new cut are within the counting errors of the
  reported curve (the cut moved by 0.29 on a statistic whose signal values
  are 5–15).
- GWAK: no event or injection exceeded 25.55, so none exceeds 27.85; the
  measured per-score rates change by less than the shot noise of the peak
  counts.

The shipped tables (`calibration/aframe_thresholds.json`,
`calibration/gwak_thresholds.json`) now carry the extended study, so new
runs use 2.986 / 27.85 at 1/day and can request 1/month.
