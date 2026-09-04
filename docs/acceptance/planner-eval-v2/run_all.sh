#!/bin/bash
# Multi-backbone evaluation on benchmark v2 (planner + guardrail suite).
# The API key is read from a file and never echoed. Haiku 4.5 rejects the
# `effort` parameter (400), so it runs with --effort none.
set -u
cd "$(dirname "$0")/../../.."
export ANTHROPIC_API_KEY="$(cat /home/dev/.anthropic_key)"
export PYTHONPATH=src
PY=/home/dev/work/ml4gw-agent/.venv-local/bin/python
OUT=docs/acceptance/planner-eval-v2
for MODEL in claude-opus-5 claude-sonnet-5 claude-haiku-4-5-20251001; do
  EFFORT=high
  case "$MODEL" in *haiku*) EFFORT=none ;; esac
  echo "=== $MODEL planner (effort $EFFORT) $(date -u +%FT%TZ)"
  $PY scripts/evaluate_planner.py --benchmark benchmarks/v2_prompts.yaml \
      --client anthropic --model "$MODEL" --effort "$EFFORT" --workers 8 --repeats 3 \
      --output "$OUT/planner_eval_$MODEL.json"
  echo "exit=$?"
  echo "=== $MODEL guardrails (effort $EFFORT) $(date -u +%FT%TZ)"
  $PY scripts/evaluate_guardrails.py --benchmark benchmarks/v2_prompts.yaml \
      --client anthropic --model "$MODEL" --effort "$EFFORT" --workers 8 \
      --output "$OUT/guardrails_$MODEL.json"
  echo "exit=$?"
done
echo "ALLDONE $(date -u +%FT%TZ)"
