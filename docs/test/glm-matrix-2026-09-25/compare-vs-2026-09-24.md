# MCP matrix comparison

- Baseline: `docs/test/glm-retry-2026-09-24/effective-summary.json` (55/66 scenarios)
- New: `docs/test/glm-matrix-2026-09-25/effective-summary.json` (65/66 scenarios)
- Fixed: 11; regressed: 1

| Model | Scenario | Baseline | New | Change | Failed checks (new) |
|---|---|---|---|---|---|
| glm-4.5 | buoy | FAIL | pass | fixed |  |
| glm-4.5 | aframe_amplfi | pass | pass | unchanged |  |
| glm-4.5 | aframe_gwak | pass | pass | unchanged |  |
| glm-4.5 | invalid_requests | pass | pass | unchanged |  |
| glm-4.5 | budget | pass | pass | unchanged |  |
| glm-4.5 | busy_cancel | pass | pass | unchanged |  |
| glm-4.5-air | buoy | pass | pass | unchanged |  |
| glm-4.5-air | aframe_amplfi | pass | pass | unchanged |  |
| glm-4.5-air | aframe_gwak | pass | FAIL | regressed | expected_skills, no_tool_errors |
| glm-4.5-air | invalid_requests | pass | pass | unchanged |  |
| glm-4.5-air | budget | pass | pass | unchanged |  |
| glm-4.5-air | busy_cancel | pass | pass | unchanged |  |
| glm-4.6 | buoy | pass | pass | unchanged |  |
| glm-4.6 | aframe_amplfi | pass | pass | unchanged |  |
| glm-4.6 | aframe_gwak | pass | pass | unchanged |  |
| glm-4.6 | invalid_requests | pass | pass | unchanged |  |
| glm-4.6 | budget | pass | pass | unchanged |  |
| glm-4.6 | busy_cancel | pass | pass | unchanged |  |
| glm-4.7 | buoy | FAIL | pass | fixed |  |
| glm-4.7 | aframe_amplfi | pass | pass | unchanged |  |
| glm-4.7 | aframe_gwak | pass | pass | unchanged |  |
| glm-4.7 | invalid_requests | pass | pass | unchanged |  |
| glm-4.7 | budget | pass | pass | unchanged |  |
| glm-4.7 | busy_cancel | pass | pass | unchanged |  |
| glm-5 | buoy | FAIL | pass | fixed |  |
| glm-5 | aframe_amplfi | pass | pass | unchanged |  |
| glm-5 | aframe_gwak | pass | pass | unchanged |  |
| glm-5 | invalid_requests | pass | pass | unchanged |  |
| glm-5 | budget | pass | pass | unchanged |  |
| glm-5 | busy_cancel | pass | pass | unchanged |  |
| glm-5-turbo | buoy | pass | pass | unchanged |  |
| glm-5-turbo | aframe_amplfi | pass | pass | unchanged |  |
| glm-5-turbo | aframe_gwak | pass | pass | unchanged |  |
| glm-5-turbo | invalid_requests | pass | pass | unchanged |  |
| glm-5-turbo | budget | pass | pass | unchanged |  |
| glm-5-turbo | busy_cancel | pass | pass | unchanged |  |
| glm-5.1 | buoy | pass | pass | unchanged |  |
| glm-5.1 | aframe_amplfi | pass | pass | unchanged |  |
| glm-5.1 | aframe_gwak | pass | pass | unchanged |  |
| glm-5.1 | invalid_requests | pass | pass | unchanged |  |
| glm-5.1 | budget | pass | pass | unchanged |  |
| glm-5.1 | busy_cancel | pass | pass | unchanged |  |
| glm-5.2 | buoy | FAIL | pass | fixed |  |
| glm-5.2 | aframe_amplfi | pass | pass | unchanged |  |
| glm-5.2 | aframe_gwak | pass | pass | unchanged |  |
| glm-5.2 | invalid_requests | pass | pass | unchanged |  |
| glm-5.2 | budget | pass | pass | unchanged |  |
| glm-5.2 | busy_cancel | pass | pass | unchanged |  |
| glm-5.3 | buoy | FAIL | pass | fixed |  |
| glm-5.3 | aframe_amplfi | FAIL | pass | fixed |  |
| glm-5.3 | aframe_gwak | pass | pass | unchanged |  |
| glm-5.3 | invalid_requests | pass | pass | unchanged |  |
| glm-5.3 | budget | pass | pass | unchanged |  |
| glm-5.3 | busy_cancel | pass | pass | unchanged |  |
| glm-5.3-flash | buoy | FAIL | pass | fixed |  |
| glm-5.3-flash | aframe_amplfi | FAIL | pass | fixed |  |
| glm-5.3-flash | aframe_gwak | FAIL | pass | fixed |  |
| glm-5.3-flash | invalid_requests | pass | pass | unchanged |  |
| glm-5.3-flash | budget | pass | pass | unchanged |  |
| glm-5.3-flash | busy_cancel | pass | pass | unchanged |  |
| glm-5.3-flashx | buoy | pass | pass | unchanged |  |
| glm-5.3-flashx | aframe_amplfi | FAIL | pass | fixed |  |
| glm-5.3-flashx | aframe_gwak | FAIL | pass | fixed |  |
| glm-5.3-flashx | invalid_requests | pass | pass | unchanged |  |
| glm-5.3-flashx | budget | pass | pass | unchanged |  |
| glm-5.3-flashx | busy_cancel | pass | pass | unchanged |  |
