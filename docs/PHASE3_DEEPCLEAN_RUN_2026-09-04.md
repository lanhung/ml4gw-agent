# Phase 3 — DeepClean: a usable 60 Hz coupling model and the first real cleaning run (2026-09-04)

The DeepClean team has not supplied a deployed configuration or weights.
Following the user's instruction ("study the current code or deployed
version and give me something usable"), the agent ports the public
`ML4GW/deepcleanv2` recipe, trains it on non-public O4 H1 data reached
through NDS2 with the user's IGWN credential, ships the weights pinned by
SHA-256, and runs the real `deepclean.clean` adapter end to end. This is a
self-trained stand-in, recorded as such in
`calibration/deepclean_support.json` (`review` field); it is not the
collaboration's reviewed model.

## What was ported

`src/ml4gw_agent/adapters/deepclean_model.py` follows deepcleanv2's 60 Hz
configuration (`myprojects/60Hz-O3-MDC`, `couplings/sub_60Hz.py`):

| Item | Value |
|---|---|
| target | strain band-passed to 55–65 Hz (8th-order Butterworth, zero phase) |
| witness | `H1:PEM-CS_MAINSMON_EBAY_1_DQ` (the mains monitor) |
| sample rate | 4096 Hz (strain 16384 Hz and witness 8192 Hz are polyphase-resampled) |
| model | 1-D convolutional autoencoder, hidden channels [8, 16, 32, 64], Tanh + BatchNorm, kernel 7 |
| loss | PSD-ratio (ASD form) of residual over target inside the band, fftlength 2 s |
| training | 8 s kernels, 0.25 s stride, batch 32, Adam lr 3.2e-2 one-cycle, weight decay 1e-5, early stop patience 20, 10 % validation |
| cleaning | 1 s kernels at 4 Hz, only the central 0.25 s of each kernel is kept; prediction is band-passed before subtraction |

The prediction is a function of the witness only, and the subtraction is
band-limited, so strain content outside 55–65 Hz cannot change; the adapter
checks the out-of-band ASD ratio and refuses to report `applicable: true`
if it moves away from unity.

## Training data and result

The first stretch tried (GPS 1400000000, 5120 s) turned out to be out of
lock after ~1620 s (per-second strain RMS up to 1e-10 instead of ~4e-18),
which drove the loss to NaN. `scripts/deepclean_train.py` now refuses
non-stationary stretches (per-second RMS more than 100× the median) unless
told otherwise. The model was then trained on the observing stretch that
contains superevent S250119cv:

| Item | Value |
|---|---|
| data | `H1:GDS-CALIB_STRAIN` + witness, GPS 1421344000–1421349120 (5120 s), NDS2 `nds.ligo.caltech.edu:31200`, file SHA-256 `9e42008a…` |
| training | first 4096 s (3686 s train + 410 s validation) |
| held out | last 1024 s (contains S250119cv at +4576 s) |
| best validation in-band ASD ratio | 0.8948 at epoch 19 (40 epochs run, 489 s on one RTX 5000 Ada) |
| held-out in-band ASD ratio (55–65 Hz mean) | 0.910 |
| held-out 60 Hz line (59.9–60.1 Hz) ASD | 1.03e-22 → 1.49e-23 (ratio 0.144) |
| held-out out-of-band ASD ratio (20–500 Hz excluding band) | 1.0000 |
| weights | `models/deepclean/H1_60Hz/deepclean.pt`, SHA-256 `b1960171f6b1b8480f6a34926e357e1e7353b18d5744ea32ba732bd5ad1d897f` (175 kB) |

The band-mean ratio of 0.91 is what a single mains-monitor witness can
give: the 60 Hz line occupies about two of the 21 half-hertz bins in the
band, and the sidebands are not in the witness. Per-bin comparison of the
held-out stretch against LIGO's own `H1:GDS-CALIB_STRAIN_CLEAN`:

| band | ours / raw (median, min) | GDS-CALIB_STRAIN_CLEAN / raw (median, min) |
|---|---|---|
| 55–58 Hz | 1.000, 0.988 | 1.022, 0.973 |
| 58–59.5 Hz | 1.000, 0.998 | 1.033, 0.945 |
| 59.5–60.5 Hz | 0.973, **0.144** | 1.080, 0.986 |
| 60.5–62 Hz | 1.000, 0.991 | 0.999, 0.932 |
| 62–65 Hz | 1.000, 0.995 | 1.014, 0.967 |
| 20–55 Hz | 1.000, 1.000 | 1.002, 0.020 |
| 65–500 Hz | 1.000, 0.999 | 0.985, 0.006 |

The O4 online cleaned channel does not subtract the 60 Hz line at all
(its 60 Hz ASD is 1.26e-22, slightly above raw); it targets other
couplings (the deep notches in the 20–55 Hz and 65–500 Hz rows). The two
are therefore complementary, and the coupling configuration is applied to
whichever H1 strain channel the plan fetched (`GDS-CALIB_STRAIN_CLEAN` for
O4 by default).

## Where it plugs in

- `deepclean.check_applicability` (adapter v0.4) keeps the three static
  gates (non-public source, reviewed configuration, interval) and now also
  fetches the configuration's witness channels through NDS2 into
  `artifacts/check_deepclean/witnesses.hdf5`; a fetch failure is a reason
  for `applicable: false`. It outputs `ifo`, `coupling_config`,
  `model_revision`, `witness_artifact`.
- `deepclean.clean` (adapter v0.1, `experimental`, high risk, needs
  `--approve-high-risk`): verifies the weights hash against both the plan's
  `model_revision` and the training record, resamples strain and witnesses
  to 4096 Hz, predicts and subtracts the band-limited noise, resamples the
  noise estimate back to the strain's native rate, writes
  `cleaned_strain.hdf5` (other detectors untouched) and
  `subtraction_diagnostics.json` (in-band / out-of-band ASD ratios,
  training-record summary, signal-preservation statement). `applicable` is
  false when the in-band ratio is not below 1 or the out-of-band ratio
  moves by more than 5 %.
- The baseline planner schedules `clean_deepclean` after `check_deepclean`
  with `when: ${check_deepclean.outputs.applicable} truthy`, so public-data
  requests still skip cleaning with the recorded reason (unchanged
  GW150914 behaviour), and the v0/v1 benchmarks expect the conditional
  task.

## Real run: S250119cv (GPU node, 2026-09-03 22:40 UTC)

Request: "Fetch strain data for 1421348576.32, check data quality, use
DeepClean if appropriate, then run Aframe detection." with
`--mode real --data-source nds2 --ifos H1 L1 --aframe-far 365.25
--approve-high-risk` (run `run_b08580ad3a0d`, evidence in
`docs/acceptance/S250119cv-deepclean/`). Every task completed:

| task | result |
|---|---|
| `fetch_data` (nds2) | 128 s of `H1:GDS-CALIB_STRAIN_CLEAN`, `L1:GDS-CALIB_STRAIN_CLEAN` at 16384 Hz → 2048 Hz |
| `inspect_data` | passed |
| `check_deepclean` | `applicable: true`, configuration H1 60 Hz, `uncovered_ifos: ["L1"]`, witness `H1:PEM-CS_MAINSMON_EBAY_1_DQ` fetched through NDS2 into `witnesses.hdf5` |
| `clean_deepclean` | `applicable: true`; in-band ASD ratio 0.902 (min 0.275 at the 60 Hz line), out-of-band ratio 1.0000003; H1 cleaned, L1 untouched |
| `run_aframe` | statistic 8.50 above the calibrated 1/day threshold 2.70, coalescence 1421348576.234 (unchanged from the earlier S250119cv run) |

A first attempt returned `applicable: false` because the check demanded a
configuration for every requested detector; DeepClean is per-detector, so
the check now passes when at least one detector is covered and reports the
others as `uncovered_ifos` (public data and unconfigured intervals still
fail closed with the reason).

### Signal preservation on a real signal

`aframe.detect` was run again on the raw and on the cleaned artifact of
the same run (`aframe_raw_vs_cleaned.json`):

| strain | detection statistic | coalescence time |
|---|---|---|
| raw (`fetch_data`) | 8.503 | 1421348576.234 |
| DeepClean-cleaned H1 | 8.666 | 1421348576.234 |

The binary-coalescence candidate survives cleaning with an unchanged peak
time and a slightly higher statistic, consistent with a band-limited,
witness-only subtraction that cannot remove a broadband chirp. This is a
one-event check, not the injection campaign the exit criterion asks for;
that campaign (injections into O4 data, tolerance set by the reviewer)
stays open, as does replacing the self-trained weights with the DeepClean
team's reviewed model when they release one.

## Exit criteria after this run

- Inapplicable public-data cases skipped with the reason: unchanged.
- Applicable case reduces the targeted coupling (60 Hz line by 7× on held
  out data, 3.6× at the line bin of the 128 s event window) and preserves
  the astrophysical signal in the one real case tested (Aframe statistic
  8.50 → 8.67, same time). Reviewed tolerance and injections: open.
