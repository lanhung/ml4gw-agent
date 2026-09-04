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


## LLM providers (2026-09-04)

The LLM planner is no longer tied to Anthropic. Any OpenAI-compatible
chat-completions endpoint works through `OpenAICompatibleClient`
(`src/ml4gw_agent/llm_planner.py`), selected in the web form or with
`ml4gw-agent run --planner llm --llm-provider <name> [--llm-model M]
[--llm-base-url URL]`:

| provider | default model | key variable | notes |
|---|---|---|---|
| `anthropic` | claude-opus-5 | `ANTHROPIC_API_KEY` | structured outputs |
| `deepseek` | deepseek-chat | `DEEPSEEK_API_KEY` | cheap |
| `qwen` | qwen-plus | `DASHSCOPE_API_KEY` | DashScope compatible mode |
| `openrouter` | qwen/qwen3-235b-a22b:free | `OPENROUTER_API_KEY` | free-tier models (`:free` suffix) |
| `siliconflow` | Qwen/Qwen2.5-7B-Instruct | `SILICONFLOW_API_KEY` | free small models |
| `groq` | llama-3.3-70b-versatile | `GROQ_API_KEY` | free developer tier |
| `ollama` | qwen2.5:14b | none | local server, `http://127.0.0.1:11434/v1` |
| `openai` | gpt-4o-mini | `OPENAI_API_KEY` | |
| `custom` | — | `ML4GW_LLM_API_KEY` | any base URL + model |

`ML4GW_LLM_API_KEY` overrides every provider-specific variable. The web
page shows which providers have a server-side key (`/api/health`,
`llm_providers`); a key pasted into the form is used for that request only,
is never stored, and for real runs travels to the GPU node only inside the
command environment. Structured output is requested as a JSON schema, then
JSON mode, then plain JSON in the prompt, whichever the endpoint accepts;
the plan is validated by the same contracts either way, so a weaker model
costs repairs and deterministic fallbacks, not invalid plans.
