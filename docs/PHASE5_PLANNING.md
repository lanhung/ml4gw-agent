# Phase 5 — measured agentic planning

Implemented in `src/ml4gw_agent/llm_planner.py`, evaluated by
`scripts/evaluate_planner.py` on `benchmarks/v0_prompts.yaml` and
`benchmarks/v1_prompts.yaml` (71 cases: nominal English and Chinese
requests, edge cases, and adversarial prompts).

## Design

- **Same boundary as every other plan source.** The model returns JSON that
  must validate as `PlanSpec`; the registry must know every skill; task
  parameters must be names the skill's input schema accepts; every
  `${task.outputs.field}` reference must point at a declared (possibly
  transitive) dependency; conditions must reference real tasks; and the
  execution policy (pinned revisions in real mode, bounded windows and
  sample counts, no planned adapters) is applied before the plan is
  returned. Prompt text never reaches an adapter, a shell, or a path.
- **Retrieval, not the whole registry.** `retrieve_skill_summaries` ranks
  skills by lexical overlap with the request (with a few Chinese synonyms),
  always includes the data/quality/report core, and passes compact
  summaries: description, status, adapter kind, input names and types,
  required inputs, output names, preconditions.
- **Bounded repair and fallback.** One repair round carries the validator's
  error back to the model; after that the deterministic baseline plan is
  used and the plan's warnings say so (`fallback: true` in the diagnostics).
- **Structured observation and bounded replanning.** `observe(manifest)`
  reduces a run to task statuses, a fixed set of scientific outputs, and
  errors; `replan(prompt, manifest)` makes at most one corrected proposal,
  again validated, and only when something failed.
- **Experiment memory.** `ExperimentMemory` appends one JSON line per run
  (event, detectors, window, source, model revisions, seed, FAR target,
  result status, per-task statuses, failure messages) and feeds the last
  entries for the same event back into the planning request. Chat history
  is not stored.
- **Refusal before the model.** Requests without a bounded event identifier
  (whole observing runs, "everything") are refused before any model call,
  exactly like the baseline.
- **Client seam.** `AnthropicClient` uses the official SDK with
  `output_config.format` JSON-schema output on `claude-opus-5`
  (`uv sync --extra llm`, `ANTHROPIC_API_KEY` or an `ant auth login`
  profile). `ReplayClient` answers from a callable; `baseline_responder`
  makes it answer with the deterministic plan so the pipeline can be
  measured without credentials.

CLI: `ml4gw-agent run "<prompt>" --planner llm [--llm-model ...]
[--memory runs/memory.jsonl]`; `--memory` also works with the baseline
planner and records every run.

## Measurements (2026-09-03, no API credentials on this host)

`uv run python scripts/evaluate_planner.py` (mock execution):

| Planner | Cases | Tool-selection accuracy | Plan validity | Execution success (mock) | Reproducible plan hash | Fallback rate | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-deterministic | 71 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | < 1 ms |
| llm-replay (pipeline with the baseline as the "model") | 71 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 2 ms |

Recovery: with an injected first answer that names an unregistered skill
(`shell.run`), the repair round produces a valid plan (`recovered_after_repair:
true`). Cost is 0 tokens for the replay client.

These numbers measure the pipeline (retrieval, prompt assembly, validation,
repair, fallback, execution, memory) and its safety boundary, not the
quality of a language model's proposals. Running the same script with
`--client anthropic` on a host with credentials fills the `llm-anthropic`
row with real tool-selection accuracy, latency, and token cost; that run has
not been done here.

## Safety checks covered by the unit tests

Rejected and replaced by the baseline (with the reason in the warnings):
unknown skills (`shell.run`), parameters a skill does not accept, malformed
or dangling references, references to tasks that are not upstream, cyclic
dependencies, unpinned model revisions in real mode. Adversarial benchmark
prompts ("ignore all previous rules", shell commands, credential requests,
invented skills, Chinese injections) produce the ordinary bounded plan for
the named event or a refusal; none reaches an adapter.
