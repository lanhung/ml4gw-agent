# ML4GW Agent composed analysis: 1187008882.4

## Request

Run Aframe and GWAK on 1187008882.4 and reconcile the two results.

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
  "catalog_time": 1187008882.4,
  "delegated_resolution": false,
  "event": "1187008882.4",
  "event_kind": "gps",
  "simulated": false
}
```

### fetch_data

```json
{
  "event_time": 1187008882.4,
  "gps_end": 1187008914.0,
  "gps_start": 1187008786.0,
  "ifos": [
    "H1",
    "L1"
  ],
  "sample_rate": 2048,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data/strain_1187008882.4.hdf5"
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
  "detection_statistic": -0.12894825424466813,
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
  "peak_in_window": false,
  "peak_near_target": false,
  "predicted_coalescence_time": null,
  "raw_peak_time": 1187008784.0078125,
  "simulated": false,
  "target_offset_seconds": -98.39218759536743,
  "target_time": 1187008882.4,
  "threshold": 2.7006401797746933,
  "threshold_calibrated": true,
  "threshold_far_per_year": 365.25
}
```

### fetch_data_4k

```json
{
  "event_time": 1187008882.4,
  "gps_end": 1187008914.0,
  "gps_start": 1187008786.0,
  "ifos": [
    "H1",
    "L1"
  ],
  "sample_rate": 4096,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data_4k/strain_1187008882.4.hdf5"
}
```

### run_gwak

```json
{
  "analysis_end": 1187008913.5,
  "analysis_start": 1187008850.5,
  "anomaly_artifact": "artifacts/run_gwak/gwak_scores.hdf5",
  "anomaly_found": true,
  "max_score": 13.99051284790039,
  "median_score": 12.825523376464844,
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
  "target_rank": 47,
  "target_score": 13.29777717590332,
  "target_time": 1187008882.4,
  "target_zscore": 4.254152616997057,
  "threshold": 0.0,
  "threshold_calibrated": false,
  "top_segments": [
    {
      "log_prob": -13.99051284790039,
      "score": 13.99051284790039,
      "time": 1187008875.375
    },
    {
      "log_prob": -13.797908782958984,
      "score": 13.797908782958984,
      "time": 1187008871.125
    },
    {
      "log_prob": -13.774504661560059,
      "score": 13.774504661560059,
      "time": 1187008872.5
    },
    {
      "log_prob": -13.766273498535156,
      "score": 13.766273498535156,
      "time": 1187008895.125
    },
    {
      "log_prob": -13.753866195678711,
      "score": 13.753866195678711,
      "time": 1187008876.5
    },
    {
      "log_prob": -13.749340057373047,
      "score": 13.749340057373047,
      "time": 1187008898.3125
    },
    {
      "log_prob": -13.746456146240234,
      "score": 13.746456146240234,
      "time": 1187008888.9375
    },
    {
      "log_prob": -13.741211891174316,
      "score": 13.741211891174316,
      "time": 1187008854.6875
    },
    {
      "log_prob": -13.69317626953125,
      "score": 13.69317626953125,
      "time": 1187008851.25
    },
    {
      "log_prob": -13.658647537231445,
      "score": 13.658647537231445,
      "time": 1187008900.6875
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
