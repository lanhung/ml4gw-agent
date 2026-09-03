# ML4GW Agent composed analysis: GW190521

## Request

Fetch strain data for GW190521, check data quality, run Aframe detection and AMPLFI parameter estimation.

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
  "catalog_time": 1242442967.4,
  "delegated_resolution": false,
  "event": "GW190521",
  "event_kind": "gwtc",
  "simulated": false
}
```

### fetch_data

```json
{
  "event_time": 1242442967.4,
  "gps_end": 1242442999.0,
  "gps_start": 1242442871.0,
  "ifos": [
    "H1",
    "L1",
    "V1"
  ],
  "sample_rate": 2048,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data/strain_GW190521.hdf5"
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
    1242442967.4375
  ],
  "detection_statistic": 8.733234265020915,
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
  "predicted_coalescence_time": 1242442967.4375,
  "simulated": false,
  "threshold": 0.0,
  "threshold_calibrated": false
}
```

### run_amplfi

```json
{
  "coalescence_time": 1242442967.4375,
  "credible_intervals": {
    "chirp_mass": {
      "mean": 85.20142296204381,
      "median": 87.6965560913086,
      "p5": 63.399674606323245,
      "p95": 98.94240798950196,
      "std": 11.45454443409874
    },
    "chirp_mass_source": {
      "mean": 63.52416284180164,
      "median": 64.09602026208815,
      "p5": 50.02504906401904,
      "p95": 75.46404812021485,
      "std": 7.851557307520202
    },
    "dec": {
      "mean": 0.17686001582167118,
      "median": 0.66036057472229,
      "p5": -1.1838935732841491,
      "p95": 0.9756627678871154,
      "std": 0.8510830077230571
    },
    "distance": {
      "mean": 1869.362329515205,
      "median": 1860.92041015625,
      "p5": 1080.195068359375,
      "p95": 2701.2191406249995,
      "std": 483.6940156806956
    },
    "inclination": {
      "mean": 1.5795569594865018,
      "median": 1.5854573249816895,
      "p5": 0.9570237696170807,
      "p95": 2.1931659460067747,
      "std": 0.40123187460671333
    },
    "mass_1": {
      "mean": 213.17883993761993,
      "median": 205.49267578125,
      "p5": 158.7754104614258,
      "p95": 281.06487731933595,
      "std": 39.14804133995756
    },
    "mass_2": {
      "mean": 50.81685203305176,
      "median": 50.61570358276367,
      "p5": 32.13066139221191,
      "p95": 69.97005386352538,
      "std": 11.5489866528123
    },
    "mass_ratio": {
      "mean": 0.24819035115611465,
      "median": 0.2377813458442688,
      "p5": 0.14021539092063903,
      "p95": 0.3929128438234329,
      "std": 0.08200689434745996
    },
    "ra": {
      "mean": 3.5340804574224554,
      "median": 3.867452621459961,
      "p5": 0.09010887145996094,
      "p95": 6.174075603485107,
      "std": 1.7445306697692684
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
  "n_samples": 19979,
  "posterior_artifact": "artifacts/run_amplfi/posterior_samples.dat",
  "simulated": false,
  "skymap_artifact": "artifacts/run_amplfi/amplfi_HLV.fits",
  "summary_artifact": "artifacts/run_amplfi/credible_intervals.json"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
