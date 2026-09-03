# ML4GW Agent report: GW150914

## Request

Analyze GW150914

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
  "event": "GW150914",
  "event_kind": "gwtc",
  "simulated": false
}
```

### analyze_event

```json
{
  "aframe_output": "artifacts/analyze_event/buoy-output/GW150914/data/aframe_outputs.hdf5",
  "detection_statistic": 9.505906045436857,
  "event": "GW150914",
  "output_directory": "artifacts/analyze_event/buoy-output/GW150914",
  "plots": [
    "artifacts/analyze_event/buoy-output/GW150914/plots/H1_qtransform.png",
    "artifacts/analyze_event/buoy-output/GW150914/plots/L1_qtransform.png",
    "artifacts/analyze_event/buoy-output/GW150914/plots/aframe_response.png",
    "artifacts/analyze_event/buoy-output/GW150914/plots/corner_plot_HL.png",
    "artifacts/analyze_event/buoy-output/GW150914/plots/skymap_HL.png"
  ],
  "posterior_samples": "artifacts/analyze_event/buoy-output/GW150914/data/posterior_samples.dat",
  "predicted_coalescence_time": 1126259462.4140625,
  "simulated": false,
  "summary_html": "artifacts/analyze_event/buoy-output/GW150914/summary.html"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
