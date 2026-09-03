# ML4GW Agent composed analysis: 1421348576.32

## Request

Fetch strain data for 1421348576.32, check data quality, use DeepClean if appropriate, then run Aframe detection.

## Workflow status

| Task | Skill | Status |
|---|---|---|
| `resolve_event` | `data.resolve_event` | completed |
| `fetch_data` | `data.fetch` | completed |
| `inspect_data` | `data.inspect` | completed |
| `check_deepclean` | `deepclean.check_applicability` | completed |
| `clean_deepclean` | `deepclean.clean` | completed |
| `run_aframe` | `aframe.detect` | completed |
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
    "L1"
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

### check_deepclean

```json
{
  "applicable": true,
  "coupling_config": "H1_60Hz/training_record.json",
  "ifo": "H1",
  "model_revision": "b1960171f6b1b8480f6a34926e357e1e7353b18d5744ea32ba732bd5ad1d897f",
  "reasons": [],
  "simulated": false,
  "uncovered_ifos": [
    "L1"
  ],
  "witness_artifact": "artifacts/check_deepclean/witnesses.hdf5"
}
```

### clean_deepclean

```json
{
  "applicable": true,
  "cleaned_strain_artifact": "artifacts/clean_deepclean/cleaned_strain.hdf5",
  "simulated": false,
  "subtraction_diagnostics": "artifacts/clean_deepclean/subtraction_diagnostics.json"
}
```

### run_aframe

```json
{
  "candidate_found": true,
  "candidate_times": [
    1421348576.234375
  ],
  "detection_statistic": 8.502791068383626,
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

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
