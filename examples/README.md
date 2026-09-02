# Examples

Create and inspect a Buoy-first plan:

```bash
uv run ml4gw-agent plan "Analyze GW150914" --output /tmp/gw150914-plan.json
uv run ml4gw-agent validate-plan /tmp/gw150914-plan.json
```

Exercise the complete orchestration path without claiming scientific output:

```bash
uv run ml4gw-agent run "Analyze GW150914" --mode mock
```

Exercise the decomposed DAG:

```bash
uv run ml4gw-agent run \
  "Analyze GW150914, check data quality, use DeepClean if appropriate, run Aframe and AMPLFI parameter estimation, then scan anomalies with GWAK." \
  --mode mock
```

