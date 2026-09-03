# ML4GW Agent composed analysis: 1126260200

## Request

Run Aframe and GWAK on 1126260200 and reconcile the two results.

## Workflow status

| Task | Skill | Status |
|---|---|---|
| `resolve_event` | `data.resolve_event` | completed |
| `fetch_data` | `data.fetch` | completed |
| `inspect_data` | `data.inspect` | completed |
| `run_aframe` | `aframe.detect` | completed |
| `fetch_data_4k` | `data.fetch` | completed |
| `run_gwak` | `gwak.scan` | completed |
| `reconcile_detections` | `analysis.reconcile` | completed |
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
  "candidate_found": false,
  "candidate_times": [],
  "detection_statistic": 0.5129588161196028,
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
  "peak_near_target": false,
  "predicted_coalescence_time": 1126260141.140625,
  "raw_peak_time": 1126260141.140625,
  "simulated": false,
  "target_offset_seconds": -58.859375,
  "target_time": 1126260200.0,
  "threshold": 2.7006401797746933,
  "threshold_calibrated": true,
  "threshold_far_per_year": 365.25
}
```

### fetch_data_4k

```json
{
  "event_time": 1126260200.0,
  "gps_end": 1126260232.0,
  "gps_start": 1126260104.0,
  "ifos": [
    "H1",
    "L1"
  ],
  "sample_rate": 4096,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data_4k/strain_1126260200.hdf5"
}
```

### run_gwak

```json
{
  "analysis_end": 1126260231.5,
  "analysis_start": 1126260168.5,
  "anomaly_artifact": "artifacts/run_gwak/gwak_scores.hdf5",
  "anomaly_found": true,
  "max_score": 14.042835235595703,
  "median_score": 12.90293025970459,
  "model": {
    "device": "cuda",
    "embedder_sha256": "f775aed557370a77b1fb0568b1e45015a6482bb7213832782d54e05979620c6f",
    "metric_sha256": "a0c755adebfadb678dd4bcd7c190c57007d089ac4281f989e0a0ebef62bb3812",
    "preprocessing": {
      "fduration_seconds": 1.0,
      "fftlength_seconds": 2.0,
      "highpass_hz": 30.0,
      "kernel_length_seconds": 0.5,
      "psd_length_seconds": 64.0,
      "sample_rate": 4096.0,
      "stride_seconds": 0.0625
    },
    "revision": "gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad",
    "source_commit": "7b9f58a"
  },
  "n_kernels": 1001,
  "simulated": false,
  "target_rank": 153,
  "target_score": 13.245210647583008,
  "target_time": 1126260200.0,
  "target_zscore": 1.4978455066554544,
  "threshold": 0.0,
  "threshold_calibrated": false,
  "top_segments": [
    {
      "log_prob": -14.042835235595703,
      "score": 14.042835235595703,
      "time": 1126260219.625
    },
    {
      "log_prob": -14.014457702636719,
      "score": 14.014457702636719,
      "time": 1126260219.25
    },
    {
      "log_prob": -13.979143142700195,
      "score": 13.979143142700195,
      "time": 1126260205.8125
    },
    {
      "log_prob": -13.952064514160156,
      "score": 13.952064514160156,
      "time": 1126260177.375
    },
    {
      "log_prob": -13.912707328796387,
      "score": 13.912707328796387,
      "time": 1126260184.625
    },
    {
      "log_prob": -13.908575057983398,
      "score": 13.908575057983398,
      "time": 1126260219.875
    },
    {
      "log_prob": -13.901592254638672,
      "score": 13.901592254638672,
      "time": 1126260211.8125
    },
    {
      "log_prob": -13.89153003692627,
      "score": 13.89153003692627,
      "time": 1126260185.875
    },
    {
      "log_prob": -13.88493537902832,
      "score": 13.88493537902832,
      "time": 1126260228.5625
    },
    {
      "log_prob": -13.880130767822266,
      "score": 13.880130767822266,
      "time": 1126260189.1875
    }
  ]
}
```

### reconcile_detections

```json
{
  "aframe_candidate": false,
  "follow_up": "unmodeled anomaly without a modelled candidate: morphology diagnostics (time-frequency, glitch classification) are the next step; AMPLFI is not run because there is no CBC coalescence time to condition on",
  "gwak_anomaly": true,
  "parameter_estimation_recommended": false,
  "route": "gwak_only",
  "simulated": false
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
