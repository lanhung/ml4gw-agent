# ML4GW Agent report: GW190521

## Request

Analyze GW190521

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
  "catalog_time": 1242442967.4,
  "delegated_resolution": false,
  "event": "GW190521",
  "event_kind": "gwtc",
  "simulated": false
}
```

### analyze_event

```json
{
  "aframe_output": "artifacts/analyze_event/buoy-output/GW190521/data/aframe_outputs.hdf5",
  "amplfi_network": "HLV",
  "detection_statistic": 8.7332799328225,
  "detectors_used": [
    "H1",
    "L1",
    "V1"
  ],
  "event": "GW190521",
  "output_directory": "artifacts/analyze_event/buoy-output/GW190521",
  "plots": [
    "artifacts/analyze_event/buoy-output/GW190521/plots/H1_qtransform.png",
    "artifacts/analyze_event/buoy-output/GW190521/plots/L1_qtransform.png",
    "artifacts/analyze_event/buoy-output/GW190521/plots/V1_qtransform.png",
    "artifacts/analyze_event/buoy-output/GW190521/plots/aframe_response.png",
    "artifacts/analyze_event/buoy-output/GW190521/plots/corner_plot_HLV.png",
    "artifacts/analyze_event/buoy-output/GW190521/plots/skymap_HLV.png"
  ],
  "posterior_samples": "artifacts/analyze_event/buoy-output/GW190521/data/posterior_samples.dat",
  "predicted_coalescence_time": 1242442967.4375,
  "simulated": false,
  "summary_html": "artifacts/analyze_event/buoy-output/GW190521/summary.html"
}
```

## Interpretation boundary

The report summarizes adapter outputs and validation state. It does not replace detector-characterization review, independent pipeline checks, or collaboration publication policy.
