# Phase 1a/1b acceptance run — GW150914 — 2026-09-03

Run identifier: `phase1b-GW150914-20260903T025339Z`
Evidence bundle: `docs/acceptance/phase1b-GW150914-20260903T025339Z/`
Repository commit under test: `736edee` (v0.2.0) plus the test fix in `c6519b2`.

## Outcome

The complete `scripts/phase1b_acceptance.sh` run finished with exit code 0
in about two minutes of wall time. Both agent runs completed, every task
completed, and both numerical comparisons against a direct Buoy run passed.

| Step | Result |
|---|---|
| `doctor --mode real` | every adapter `available`; `v0_buoy_ready` and `phase1b_decomposed_ready` both `true` |
| 1. `Analyze GW150914` (Buoy vertical slice, `run_9314eea2eaaa`) | `completed`, 3/3 tasks completed, 0 warnings |
| 2. decomposed plan (`run_6202b5282c2a`) | `completed`, 6/6 tasks completed, `run_amplfi` executed because `candidate_found` was true |
| 3. direct `buoy` run, same seed and revisions | completed, outputs in `buoy-direct/GW150914/` |
| 4. `compare_with_buoy.py` vertical slice | `passed: true`, 7/7 checks |
| 4. `compare_with_buoy.py` decomposed run | `passed: true`, 7/7 checks |

Software acceptance criteria from `PHASE1B_ACCEPTANCE.md`:

- [x] `doctor` reports every adapter `available`.
- [x] Both agent runs end with `status: completed`; every task `completed`.
- [x] No `simulated: true` anywhere in either manifest (checked by string search).
- [x] Every artifact in both manifests has a SHA-256 and a run-relative path
      (13 + 1 + 1 artifacts in the slice, 1 + 1 + 1 + 1 + 3 + 1 in the
      decomposed run).

## Environment

| Item | Value |
|---|---|
| Host | AutoDL container `autodl-container-7fb444a9ae-9b4ed319`, Ubuntu 22.04, Linux 6.8.0-90 |
| GPU | NVIDIA RTX 5000 Ada Generation (32 GB), driver 570.124.06, `CUDA_VISIBLE_DEVICES=2` |
| Python | 3.12.12 in the repository `uv` environment |
| torch | 2.10.0+cu128, `cuda True` |
| ml4gw-buoy / ml4gw / amplfi | 0.6.1 / 0.8.3 / 0.6.0 |
| jsonargparse / zuko | 4.50.0 / 1.4.1 (the reviewed upstream pins) |
| gwpy / gwosc / astropy / ligo.skymap | 4.0.2 / 0.8.3 / 7.2.2 / 2.4.0 |
| Aframe revision | `3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4` |
| AMPLFI revision | `8b97d2f8459d04924cb010dfee0262260bf3da80` |
| Seed / device | 0 / cuda |
| Model source | Hugging Face through `HF_ENDPOINT=https://hf-mirror.com` (direct `huggingface.co` connections time out from this node); the pinned revisions are verified by the hub client, so the mirror does not change which files are loaded |
| Strain source | GWOSC 4 kHz `V1` frame files `H-H1_LOSC_4_V1-1126256640-4096.hdf5` and `L-L1_LOSC_4_V1-1126256640-4096.hdf5`, SHA-256 `30ad150a…c41a` and `b6896cb7…f384`, served through the astropy download cache with `GWPY_CACHE=1` (see "Operational findings") |

## Science results (for domain review)

### Data quality (`data.inspect`)

`quality_passed: true`, no issues. Window `[1126259366.0, 1126259494.0)`
(128 s, event at 0.75 of the window), both `H1` and `L1` present, 262144
samples each at 2048 Hz after resampling from the native 4096 Hz, finite
fraction 1.0, non-constant, science segments covered.

### Aframe (`aframe.detect`)

| Quantity | Agent slice | Agent decomposed | Direct Buoy |
|---|---:|---:|---:|
| peak `detection_statistic` | 9.505906 | 9.505905 | 9.505943 |
| `predicted_coalescence_time` | 1126259462.4140625 | 1126259462.4140625 | 1126259462.4140625 |
| offset from catalog time 1126259462.4 | +0.014 s | +0.014 s | +0.014 s |
| all outputs finite | yes | yes | yes |

The predicted coalescence time lies within the 0.1 s acceptance window.
The threshold is still the uncalibrated raw cut (`threshold: 0.0`,
`threshold_calibrated: false`), and the run manifest carries the warning
that says so.

### AMPLFI (`amplfi.pe`, HL network, 19966 posterior samples)

Detector-frame unless stated. `p5`/`p95` are the 5th and 95th percentiles
from `credible_intervals.json`.

| Parameter | Agent decomposed median [p5, p95] | Direct Buoy median | GWTC-1 reference (GW150914) |
|---|---|---:|---|
| chirp mass (detector frame) | 29.48 [27.21, 31.59] M☉ | 29.48 | ≈ 31.2 M☉ (28.6 source-frame × (1+z), z ≈ 0.09) |
| chirp mass (source frame) | 26.89 [24.94, 28.96] M☉ | — | 28.6 (+1.7/−1.5) M☉ |
| mass 1 (detector frame) | 37.52 [33.63, 43.67] M☉ | 37.53 | 35.6 (+4.7/−3.1) M☉ source frame |
| mass 2 (detector frame) | 30.93 [24.65, 34.81] M☉ | 30.93 | 30.6 (+3.0/−4.4) M☉ source frame |
| mass ratio | 0.83 [0.58, 0.98] | 0.83 | ≈ 0.86 (from the median masses) |
| luminosity distance | 461 [247, 638] Mpc | 461 | 440 (+150/−170) Mpc |
| 90 % sky area (`ligo.skymap` crossmatch) | 610 deg² | 610 deg² | 182 deg² |
| 50 % sky area | 159 deg² | 159 deg² | — |

The GWTC-1 numbers are quoted from Abbott et al. 2019 (PRX 9, 031040,
Table III) and must be re-checked by the reviewer against the catalog
release. Chirp mass, masses, mass ratio, and distance are consistent with
the catalog within the quoted intervals. The source-frame chirp mass sits at
the low edge of the catalog interval, and the HL-only AMPLFI sky area is
roughly three times the GWTC-1 90 % area. Neither is a software failure;
both are the kind of item the domain reviewer needs to judge.

The sky map FITS files open with `ligo.skymap.io.read_sky_map` and the
90 % areas are recorded above.

### Numerical equivalence with direct Buoy

| Quantity | Slice vs Buoy | Decomposed vs Buoy | Tolerance |
|---|---:|---:|---|
| detection statistic (relative) | 3.9e-6 | 4.0e-6 | 1e-3 |
| predicted tc (absolute) | 0 | 0 | 0.01 s |
| median distance (relative) | 0 | 2.8e-5 | 0.05 |
| median chirp mass (relative) | 0 | 4.4e-5 | 0.05 |
| median mass 1 / mass 2 / q (relative) | 0 / 0 / 0 | 5.7e-5 / 3.2e-5 / 3.8e-5 | 0.05 |

The runbook expected the Buoy slice and the direct run to be "numerically
identical" with the same seed. They are not bit-identical: the peak Aframe
statistic differs at the 4e-6 relative level between two Buoy invocations
with identical arguments on the same GPU, while the posterior medians are
identical. The most likely cause is non-deterministic CUDA kernels in the
Aframe forward pass; this is upstream behaviour, not agent behaviour, and it
is far inside the declared tolerance. The decomposed adapters additionally
build the strain window themselves and resample to 2048 Hz; their results
agree with Buoy to 1e-5–1e-4 relative, also inside tolerance.

## Operational findings

1. **GWOSC bulk downloads are unreliable from this node.** The first
   attempt (`run_e08cf63b9f02`, 2026-09-02) failed after 21 minutes with
   `ContentTooShortError` (84 MB of 130 MB received). Throughput to
   `gwosc.org` from the node is about 70 kB/s, and the archive does not
   advertise byte-range support, so resuming is not possible. The fix was
   to download the two 4 kHz frame files elsewhere (7 MB/s), verify their
   size and SHA-256, copy them to the node, and import them into the
   astropy download cache under their original URLs with
   `astropy.utils.data.import_file_to_cache`. With `GWPY_CACHE=1` both
   Buoy and the agent's `data.fetch` then read the cached files;
   `gwpy` still contacts the GWOSC API for the URL lookup, which works.
   `scripts/prefetch_gwosc.py` automates this for future events.
2. **Hugging Face is unreachable directly** from the node; the mirror
   `hf-mirror.com` serves the same pinned revisions.
3. **`HF_HUB_OFFLINE=1` is set globally** in the node's `.bashrc`. The
   first attempt (`run_321bc5135056`) was correctly rejected by the hub
   client with a failure manifest and report; the run scripts now unset it.
4. Three unit tests in `tests/test_real_adapters.py` assumed that
   `ml4gw-buoy` is *not* installed and failed on the GPU node. They now
   monkeypatch the module probe so the suite passes both with and without
   the science extra (58 passed, 88 % coverage on both hosts).

## Still open after this run

- ML4GW domain reviewer sign-off on this record, the manifests, and the
  reports (roadmap Phase 1a exit item 5 and every "Science" checkbox in
  `PHASE1B_ACCEPTANCE.md`). The tables above are the material for that
  review; the agent does not certify scientific validity by itself.
- The rest of the Phase 1b acceptance suite: GW170817, GW190521, one GPS
  event, and one noise segment.
- A FAR-calibrated Aframe threshold from a background study.
- `mldatafind` for non-public frames.

## Reproduce

```bash
git clone https://github.com/lanhung/ml4gw-agent
cd ml4gw-agent && git checkout claude/ml4gw-orchestration-layer-i86m2q
uv sync --extra buoy --group dev

# on a node with slow or flaky GWOSC access, pre-populate the cache first
uv run python scripts/prefetch_gwosc.py GW150914

export AFRAME_REVISION=3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4
export AMPLFI_REVISION=8b97d2f8459d04924cb010dfee0262260bf3da80
export DEVICE=cuda SEED=0 GWPY_CACHE=1
unset HF_HUB_OFFLINE            # if your image sets it
export HF_ENDPOINT=https://hf-mirror.com   # only if huggingface.co is blocked
bash scripts/phase1b_acceptance.sh
```
