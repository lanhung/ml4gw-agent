# Web interface

`ml4gw_agent.web.app` is a FastAPI application over the same planner,
policy, registry, and runtime the CLI uses; nothing in it bypasses them.

```bash
uv sync --extra web
uvicorn ml4gw_agent.web.app:app --host 0.0.0.0 --port 8080
```

| Variable | Meaning |
|---|---|
| `ML4GW_WEB_RUNS` | directory for mock runs executed by the server |
| `ML4GW_WEB_RECORDS` | acceptance records shown on the page (default `docs/acceptance`) |
| `ML4GW_WEB_PASSCODE` | if set, real runs require this passcode |
| `ML4GW_NODE_HOST`, `ML4GW_NODE_PORT`, `ML4GW_NODE_USER`, `ML4GW_NODE_PASSWORD` | SSH target that has the science environment; real runs execute there, one at a time |
| `ML4GW_NODE_REPO`, `ML4GW_NODE_RUNS`, `ML4GW_NODE_ENV` | repository, run directory, and environment line on the node |
| `ANTHROPIC_API_KEY` | enables the LLM planner option |

Endpoints: `POST /api/plan` (plan + resource estimate + budget decision),
`POST /api/run` and `GET /api/jobs/{id}` (task table, warnings, report,
manifest, log), `GET /api/records` (shipped acceptance records),
`GET /api/skills`, `GET /api/health`.

The demo deployment of 2026-09-03 ran on a VPS with mock runs local and
real runs forwarded to the GPU node; the page lists the verified real runs
so visitors can inspect the GW150914, GW190521, noise-segment, GW170817,
background-calibration, and non-public-data records without touching the
GPU.
