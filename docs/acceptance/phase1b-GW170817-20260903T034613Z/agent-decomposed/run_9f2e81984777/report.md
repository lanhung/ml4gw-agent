# ML4GW Agent composed analysis: GW170817

## Request

Fetch strain data for GW170817, check data quality, run Aframe detection and AMPLFI parameter estimation.

## Workflow status

| Task | Skill | Status |
|---|---|---|
| `resolve_event` | `data.resolve_event` | completed |
| `fetch_data` | `data.fetch` | completed |
| `inspect_data` | `data.inspect` | completed |
| `run_aframe` | `aframe.detect` | completed |
| `run_amplfi` | `amplfi.pe` | skipped |
| `generate_report` | `report.generate` | completed |

## Recorded outputs

### resolve_event

```json
{
  "catalog_time": 1187008882.4,
  "delegated_resolution": false,
  "event": "GW170817",
  "event_kind": "gwtc",
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
  "strain_artifact": "artifacts/fetch_data/strain_GW170817.hdf5"
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
  "predicted_coalescence_time": null,
  "raw_peak_time": 1187008784.0078125,
  "simulated": false,
  "threshold": 0.0,
  "threshold_calibrated": false
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
