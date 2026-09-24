# Examples

For a complete local MCP conversation using the official SDK v2:

```bash
uv sync --locked --extra mcp --group dev
uv run --no-sync python examples/mcp_mock_client.py
```

See [MCP setup and real-mode configuration](../docs/MCP.md), the
[client template](mcp-client.json), and the [complete skill contract example](../docs/SKILL_CONTRACT_EXAMPLE.md).

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
