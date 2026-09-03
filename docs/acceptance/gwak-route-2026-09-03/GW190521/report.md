# ML4GW Agent composed analysis: GW190521

## Request

Run Aframe and GWAK on GW190521 and reconcile the two results.

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
    "L1"
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
  "peak_in_window": true,
  "peak_near_target": true,
  "predicted_coalescence_time": 1242442967.4375,
  "raw_peak_time": 1242442967.4375,
  "simulated": false,
  "target_offset_seconds": 0.03749990463256836,
  "target_time": 1242442967.4,
  "threshold": 2.7006401797746933,
  "threshold_calibrated": true,
  "threshold_far_per_year": 365.25
}
```

### fetch_data_4k

```json
{
  "event_time": 1242442967.4,
  "gps_end": 1242442999.0,
  "gps_start": 1242442871.0,
  "ifos": [
    "H1",
    "L1"
  ],
  "sample_rate": 4096,
  "simulated": false,
  "source": "gwosc",
  "strain_artifact": "artifacts/fetch_data_4k/strain_GW190521.hdf5"
}
```

### run_gwak

```json
{
  "analysis_end": 1242442998.5,
  "analysis_start": 1242442935.5,
  "anomaly_artifact": "artifacts/run_gwak/gwak_scores.hdf5",
  "anomaly_found": true,
  "max_score": 14.300853729248047,
  "median_score": 12.827664375305176,
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
  "target_rank": 0,
  "target_score": 14.300853729248047,
  "target_time": 1242442967.4,
  "target_zscore": 11.788122982532451,
  "threshold": 0.0,
  "threshold_calibrated": false,
  "top_segments": [
    {
      "log_prob": -14.300853729248047,
      "score": 14.300853729248047,
      "time": 1242442967.4375
    },
    {
      "log_prob": -14.03049087524414,
      "score": 14.03049087524414,
      "time": 1242442951.4375
    },
    {
      "log_prob": -13.955455780029297,
      "score": 13.955455780029297,
      "time": 1242442988.125
    },
    {
      "log_prob": -13.843173027038574,
      "score": 13.843173027038574,
      "time": 1242442967.125
    },
    {
      "log_prob": -13.761545181274414,
      "score": 13.761545181274414,
      "time": 1242442980.5
    },
    {
      "log_prob": -13.731313705444336,
      "score": 13.731313705444336,
      "time": 1242442980.8125
    },
    {
      "log_prob": -13.722783088684082,
      "score": 13.722783088684082,
      "time": 1242442976.4375
    },
    {
      "log_prob": -13.684585571289062,
      "score": 13.684585571289062,
      "time": 1242442952.25
    },
    {
      "log_prob": -13.640872955322266,
      "score": 13.640872955322266,
      "time": 1242442957.625
    },
    {
      "log_prob": -13.627763748168945,
      "score": 13.627763748168945,
      "time": 1242442956.25
    }
  ]
}
```

### reconcile_detections

```json
{
  "aframe_candidate": true,
  "follow_up": "both routes fired: AMPLFI parameter estimation on the Aframe candidate and GWAK morphology review of the same time",
  "gwak_anomaly": true,
  "parameter_estimation_recommended": true,
  "route": "consistent_candidate",
  "simulated": false
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
