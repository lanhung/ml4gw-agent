# ML4GW Agent composed analysis: GW150914

## Request

Fetch strain data for GW150914, check data quality, run Aframe detection and AMPLFI parameter estimation.

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
  "catalog_time": 1126259462.4,
  "delegated_resolution": false,
  "event": "GW150914",
  "event_kind": "gwtc",
  "simulated": false
}
```

### fetch_data

```json
{
  "event_time": 1126259462.4,
  "gps_end": 1126259494.0,
  "gps_start": 1126259366.0,
  "ifos": [
    "H1",
    "L1"
  ],
  "sample_rate": 2048,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data/strain_GW150914.hdf5"
}
```

### inspect_data

```json
{
  "available_ifos": [
    "H1",
    "L1"
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
    1126259462.4140625
  ],
  "detection_statistic": 9.505908668041227,
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
  "predicted_coalescence_time": 1126259462.4140625,
  "raw_peak_time": 1126259462.4140625,
  "simulated": false,
  "target_offset_seconds": 0.01406240463256836,
  "target_time": 1126259462.4,
  "threshold": 2.7006401797746933,
  "threshold_calibrated": true,
  "threshold_far_per_year": 365.25
}
```

### run_amplfi

```json
{
  "coalescence_time": 1126259462.4140625,
  "credible_intervals": {
    "chirp_mass": {
      "mean": 29.447242663838924,
      "median": 29.47208881378174,
      "p5": 27.19626693725586,
      "p95": 31.606369018554688,
      "std": 1.3672264864506978
    },
    "chirp_mass_source": {
      "mean": 26.900156474436116,
      "median": 26.88485283722749,
      "p5": 24.915262111301256,
      "p95": 28.96428413327763,
      "std": 1.2431565872574886
    },
    "dec": {
      "mean": -1.0684956891150426,
      "median": -1.1522517800331116,
      "p5": -1.3090072333812715,
      "p95": -0.4143295958638199,
      "std": 0.266679825948135
    },
    "distance": {
      "mean": 451.9910554549633,
      "median": 461.89776611328125,
      "p5": 245.44632568359376,
      "p95": 637.3874145507812,
      "std": 121.62530346181454
    },
    "inclination": {
      "mean": 2.1794374286143396,
      "median": 2.3711172342300415,
      "p5": 0.5764278709888458,
      "p95": 2.9414106488227842,
      "std": 0.6828681176777296
    },
    "mass_1": {
      "mean": 37.95521177762212,
      "median": 37.53181076049805,
      "p5": 33.585899353027344,
      "p95": 43.664194869995114,
      "std": 3.122510029221842
    },
    "mass_2": {
      "mean": 30.469366126956466,
      "median": 30.908961296081543,
      "p5": 24.649024391174315,
      "p95": 34.8245491027832,
      "std": 3.145345964224342
    },
    "mass_ratio": {
      "mean": 0.8116550388110156,
      "median": 0.8291036486625671,
      "p5": 0.5814006239175796,
      "p95": 0.9827962279319762,
      "std": 0.1266302528548538
    },
    "ra": {
      "mean": 2.2072678392705245,
      "median": 2.406169891357422,
      "p5": 1.1327323913574219,
      "p95": 2.73095693588256,
      "std": 0.5161210037829856
    }
  },
  "ifos": [
    "H1",
    "L1"
  ],
  "model": {
    "config": "amplfi-hl-config.yaml",
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
    "weights": "amplfi-hl.ckpt"
  },
  "n_samples": 19968,
  "posterior_artifact": "artifacts/run_amplfi/posterior_samples.dat",
  "simulated": false,
  "skymap_artifact": "artifacts/run_amplfi/amplfi_HL.fits",
  "summary_artifact": "artifacts/run_amplfi/credible_intervals.json"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
