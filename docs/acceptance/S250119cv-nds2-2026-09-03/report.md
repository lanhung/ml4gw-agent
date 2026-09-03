# ML4GW Agent composed analysis: 1421348576.32

## Request

Fetch strain data for 1421348576.32, check data quality, run Aframe detection and AMPLFI parameter estimation.

## Workflow status

| Task | Skill | Status |
|---|---|---|
| `resolve_event` | `data.resolve_event` | completed |
| `fetch_data` | `data.fetch` | completed |
| `inspect_data` | `data.inspect` | completed |
| `run_aframe` | `aframe.detect` | completed |
| `run_amplfi` | `amplfi.pe` | completed |
| `generate_report` | `report.generate` | completed |

## Recorded outputs

### resolve_event

```json
{
  "catalog_time": 1421348576.32,
  "delegated_resolution": false,
  "event": "1421348576.32",
  "event_kind": "gps",
  "simulated": false
}
```

### fetch_data

```json
{
  "event_time": 1421348576.32,
  "gps_end": 1421348608.0,
  "gps_start": 1421348480.0,
  "ifos": [
    "H1",
    "L1",
    "V1"
  ],
  "sample_rate": 2048,
  "simulated": false,
  "source": "nds2",
  "strain_artifact": "artifacts/fetch_data/strain_1421348576.32.hdf5"
}
```

### inspect_data

```json
{
  "available_ifos": [
    "H1",
    "L1",
    "V1"
  ],
  "diagnostics_artifact": "artifacts/inspect_data/quality_diagnostics.json",
  "duration_seconds": 128.0,
  "issues": [],
  "quality_passed": true,
  "sample_rate": 2048.0,
  "simulated": false
}
```

### run_aframe

```json
{
  "candidate_found": true,
  "candidate_times": [
    1421348576.234375
  ],
  "detection_statistic": 8.502807289361952,
  "model": {
    "config": {
      "aframe_right_pad": 0.0,
      "batch_size": 32,
      "fduration": 1.0,
      "fftlength": 2.5,
      "highpass": 32.0,
      "inference_sampling_rate": 128.0,
      "integration_window_length": 1.5,
      "kernel_length": 1.5,
      "lowpass": null,
      "offline_sampling_rate": 4.0,
      "psd_length": 64.0,
      "sample_rate": 2048.0
    },
    "device": "cuda",
    "repo_id": "ML4GW/aframe",
    "revision": "3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4"
  },
  "output_artifact": "artifacts/run_aframe/aframe_outputs.hdf5",
  "peak_in_window": true,
  "peak_near_target": true,
  "predicted_coalescence_time": 1421348576.234375,
  "raw_peak_time": 1421348576.234375,
  "simulated": false,
  "target_offset_seconds": -0.08562493324279785,
  "target_time": 1421348576.32,
  "threshold": 2.7006401797746933,
  "threshold_calibrated": true,
  "threshold_far_per_year": 365.25
}
```

### run_amplfi

```json
{
  "coalescence_time": 1421348576.234375,
  "credible_intervals": {
    "chirp_mass": {
      "mean": 10.280315230743602,
      "median": 10.228796005249023,
      "p5": 10.028392791748047,
      "p95": 10.707023620605469,
      "std": 0.21848033933906316
    },
    "chirp_mass_source": {
      "mean": 9.547776793643282,
      "median": 9.539513953268688,
      "p5": 9.06993656639183,
      "p95": 10.060390249572421,
      "std": 0.30182297226089144
    },
    "dec": {
      "mean": -0.6684787895769719,
      "median": -0.9062042832374573,
      "p5": -1.3609257638454437,
      "p95": 0.3785797208547592,
      "std": 0.6765660747416449
    },
    "distance": {
      "mean": 364.60392189555523,
      "median": 344.48968505859375,
      "p5": 183.53076171875,
      "p95": 602.91943359375,
      "std": 131.49231275854666
    },
    "inclination": {
      "mean": 1.6575435379220687,
      "median": 1.6805906891822815,
      "p5": 0.7417312115430832,
      "p95": 2.513930380344391,
      "std": 0.532243570453696
    },
    "mass_1": {
      "mean": 15.640581056037028,
      "median": 14.730053901672363,
      "p5": 12.0307297706604,
      "p95": 22.460233211517334,
      "std": 3.389430042224373
    },
    "mass_2": {
      "mean": 9.396364802561058,
      "median": 9.548138618469238,
      "p5": 6.688268780708313,
      "p95": 11.532035827636719,
      "std": 1.509403157619395
    },
    "mass_ratio": {
      "mean": 0.6418224300700506,
      "median": 0.6489107608795166,
      "p5": 0.2973480373620987,
      "p95": 0.956561952829361,
      "std": 0.20337398686664968
    },
    "ra": {
      "mean": 2.482349276926654,
      "median": 0.9431419372558594,
      "p5": 0.3123002052307129,
      "p95": 5.751735687255859,
      "std": 2.381905994805837
    }
  },
  "ifos": [
    "H1",
    "L1",
    "V1"
  ],
  "model": {
    "config": "amplfi-hlv-config.yaml",
    "device": "cuda",
    "inference_params": [
      "chirp_mass",
      "mass_ratio",
      "distance",
      "phic",
      "inclination",
      "dec",
      "psi",
      "phi"
    ],
    "kernel_length": 3.0,
    "psd_length": 10.0,
    "repo_id": "ML4GW/amplfi",
    "revision": "8b97d2f8459d04924cb010dfee0262260bf3da80",
    "sample_rate": 2048.0,
    "weights": "amplfi-hlv.ckpt"
  },
  "n_samples": 18006,
  "posterior_artifact": "artifacts/run_amplfi/posterior_samples.dat",
  "simulated": false,
  "skymap_artifact": "artifacts/run_amplfi/amplfi_HLV.fits",
  "summary_artifact": "artifacts/run_amplfi/credible_intervals.json"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
