# ML4GW Agent composed analysis: 1126260200

## Request

Fetch strain data for 1126260200, check data quality, run Aframe detection and AMPLFI parameter estimation.

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
  "catalog_time": 1126260200.0,
  "delegated_resolution": false,
  "event": "1126260200",
  "event_kind": "gps",
  "simulated": false
}
```

### fetch_data

```json
{
  "event_time": 1126260200.0,
  "gps_end": 1126260232.0,
  "gps_start": 1126260104.0,
  "ifos": [
    "H1",
    "L1"
  ],
  "sample_rate": 2048,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data/strain_1126260200.hdf5"
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
    1126260141.140625
  ],
  "detection_statistic": 0.5130131393671036,
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
  "predicted_coalescence_time": 1126260141.140625,
  "simulated": false,
  "threshold": 0.0,
  "threshold_calibrated": false
}
```

### run_amplfi

```json
{
  "coalescence_time": 1126260141.140625,
  "credible_intervals": {
    "chirp_mass": {
      "mean": 41.7720171087547,
      "median": 36.97712326049805,
      "p5": 12.400211524963378,
      "p95": 86.72206420898436,
      "std": 22.813225184937515
    },
    "chirp_mass_source": {
      "mean": 30.19847629118059,
      "median": 26.787867993897592,
      "p5": 9.707258219849514,
      "p95": 61.757099711944996,
      "std": 16.148645860015428
    },
    "dec": {
      "mean": 0.03432706641720697,
      "median": 0.030104253441095352,
      "p5": -0.9807402431964874,
      "p95": 1.147399091720581,
      "std": 0.662217509469931
    },
    "distance": {
      "mean": 2099.5012179129462,
      "median": 2226.10888671875,
      "p5": 773.2308135986328,
      "p95": 3034.6464233398438,
      "std": 719.4008846031203
    },
    "inclination": {
      "mean": 1.6028364013370715,
      "median": 1.6121220588684082,
      "p5": 0.528163057565689,
      "p95": 2.651978552341461,
      "std": 0.6325710936772617
    },
    "mass_1": {
      "mean": 82.68033376296958,
      "median": 70.30447387695312,
      "p5": 18.913762092590332,
      "p95": 191.7772232055664,
      "std": 54.80204130290692
    },
    "mass_2": {
      "mean": 32.18427453373309,
      "median": 27.129825592041016,
      "p5": 9.667312955856323,
      "p95": 74.24218826293944,
      "std": 19.92409238546437
    },
    "mass_ratio": {
      "mean": 0.4817307903219883,
      "median": 0.43487608432769775,
      "p5": 0.14802300781011582,
      "p95": 0.9375985473394394,
      "std": 0.2591562893855042
    },
    "ra": {
      "mean": 3.264527685098481,
      "median": 3.4159178733825684,
      "p5": 0.18741989135742188,
      "p95": 6.048730373382568,
      "std": 1.8786890901050686
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
  "n_samples": 19950,
  "posterior_artifact": "artifacts/run_amplfi/posterior_samples.dat",
  "simulated": false,
  "skymap_artifact": "artifacts/run_amplfi/amplfi_HL.fits",
  "summary_artifact": "artifacts/run_amplfi/credible_intervals.json"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
