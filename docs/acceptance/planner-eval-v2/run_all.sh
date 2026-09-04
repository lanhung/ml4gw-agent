#!/bin/bash
# Multi-backbone evaluation on benchmark v2 (planner + guardrail suite).
# The API key is read from a file and never echoed.
set -u
cd "$(dirname "$0")/../../.."
export ANTHROPIC_API_KEY="$(cat /home/dev/.anthropic_key)"
export PYTHONPATH=src
PY=/home/dev/work/ml4gw-agent/.venv-local/bin/python
OUT=docs/acceptance/planner-eval-v2
for MODEL in claude-opus-5 claude-sonnet-5 claude-haiku-4-5-20251001; do
  echo "=== $MODEL planner $(date -u +%FT%TZ)"
  $PY scripts/evaluate_planner.py --benchmark benchmarks/v2_prompts.yaml \
      --client anthropic --model "$MODEL" --workers 8 --repeats 3 \
      --output "$OUT/planner_eval_$MODEL.json"
  echo "exit=$?"
  echo "=== $MODEL guardrails $(date -u +%FT%TZ)"
  $PY scripts/evaluate_guardrails.py --benchmark benchmarks/v2_prompts.yaml \
      --client anthropic --model "$MODEL" --workers 8 \
      --output "$OUT/guardrails_$MODEL.json"
  echo "exit=$?"
done
echo "ALLDONE $(date -u +%FT%TZ)"
