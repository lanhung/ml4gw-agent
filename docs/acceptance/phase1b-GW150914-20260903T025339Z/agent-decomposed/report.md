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
  "detection_statistic": 9.505905176912034,
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
  "predicted_coalescence_time": 1126259462.4140625,
  "simulated": false,
  "threshold": 0.0,
  "threshold_calibrated": false
}
```

### run_amplfi

```json
{
  "coalescence_time": 1126259462.4140625,
  "credible_intervals": {
    "chirp_mass": {
      "mean": 29.454236098595853,
      "median": 29.482913970947266,
      "p5": 27.2085018157959,
      "p95": 31.587624549865723,
      "std": 1.3582406133204574
    },
    "chirp_mass_source": {
      "mean": 26.91003058925336,
      "median": 26.89158811560901,
      "p5": 24.935178881241278,
      "p95": 28.95830773628937,
      "std": 1.2352923659101454
    },
    "dec": {
      "mean": -1.0695491209009895,
      "median": -1.1524468660354614,
      "p5": -1.3084561824798584,
      "p95": -0.42563314735889435,
      "std": 0.26379482415075534
    },
    "distance": {
      "mean": 451.2705642530534,
      "median": 461.0126953125,
      "p5": 246.78656005859375,
      "p95": 637.7847290039062,
      "std": 121.52453887591274
    },
    "inclination": {
      "mean": 2.176898594184043,
      "median": 2.365996241569519,
      "p5": 0.5716603398323059,
      "p95": 2.940663456916809,
      "std": 0.681905407433536
    },
    "mass_1": {
      "mean": 37.9580359459401,
      "median": 37.523643493652344,
      "p5": 33.63354206085205,
      "p95": 43.67301940917969,
      "std": 3.1093033830525725
    },
    "mass_2": {
      "mean": 30.480845553906256,
      "median": 30.925559997558594,
      "p5": 24.64669942855835,
      "p95": 34.81468105316162,
      "std": 3.1405097800889528
    },
    "mass_ratio": {
      "mean": 0.8118585002281427,
      "median": 0.8285669684410095,
      "p5": 0.5817181617021561,
      "p95": 0.9825723767280579,
      "std": 0.12638126269337213
    },
    "ra": {
      "mean": 2.205339880203611,
      "median": 2.406169891357422,
      "p5": 1.1288261413574219,
      "p95": 2.7323241233825684,
      "std": 0.518215786388737
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
  "n_samples": 19966,
  "posterior_artifact": "artifacts/run_amplfi/posterior_samples.dat",
  "simulated": false,
  "skymap_artifact": "artifacts/run_amplfi/amplfi_HL.fits",
  "summary_artifact": "artifacts/run_amplfi/credible_intervals.json"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
