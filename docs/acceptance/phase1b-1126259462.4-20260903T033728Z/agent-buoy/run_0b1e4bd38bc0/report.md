# ML4GW Agent report: 1126259462.4

## Request

Analyze 1126259462.4

## Workflow status

| Task | Skill | Status |
|---|---|---|
| `resolve_event` | `data.resolve_event` | completed |
| `analyze_event` | `buoy.analyze` | completed |
| `generate_report` | `report.generate` | completed |

## Recorded outputs

### resolve_event

```json
{
  "catalog_time": 1126259462.4,
  "delegated_resolution": false,
  "event": "1126259462.4",
  "event_kind": "gps",
  "simulated": false
}
```

### analyze_event

```json
{
  "aframe_output": "artifacts/analyze_event/buoy-output/1126259462.4/data/aframe_outputs.hdf5",
  "amplfi_network": "HL",
  "detection_statistic": 9.505909034184045,
  "detectors_used": [
    "H1",
    "L1"
  ],
  "event": "1126259462.4",
  "output_directory": "artifacts/analyze_event/buoy-output/1126259462.4",
  "plots": [
    "artifacts/analyze_event/buoy-output/1126259462.4/plots/H1_qtransform.png",
    "artifacts/analyze_event/buoy-output/1126259462.4/plots/L1_qtransform.png",
    "artifacts/analyze_event/buoy-output/1126259462.4/plots/aframe_response.png",
    "artifacts/analyze_event/buoy-output/1126259462.4/plots/corner_plot_HL.png",
    "artifacts/analyze_event/buoy-output/1126259462.4/plots/skymap_HL.png"
  ],
  "posterior_samples": "artifacts/analyze_event/buoy-output/1126259462.4/data/posterior_samples.dat",
  "predicted_coalescence_time": 1126259462.4140625,
  "simulated": false,
  "summary_html": "artifacts/analyze_event/buoy-output/1126259462.4/summary.html"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
