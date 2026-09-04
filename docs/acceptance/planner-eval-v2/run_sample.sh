#!/bin/bash
# Secondary backbones on the stratified 62-case sample, one repeat (user-approved budget run, 2026-09-04).
set -u
cd "$(dirname "$0")/../../.."
export ANTHROPIC_API_KEY="$(cat /home/dev/.anthropic_key)"
export PYTHONPATH=src
PY=/home/dev/work/ml4gw-agent/.venv-local/bin/python
OUT=docs/acceptance/planner-eval-v2
for MODEL in claude-sonnet-5 claude-haiku-4-5-20251001; do
  echo "=== $MODEL planner $(date -u +%FT%TZ)"
  $PY scripts/evaluate_planner.py --benchmark benchmarks/v2_sample.yaml --client anthropic --model "$MODEL" --workers 4 --repeats 1 --output "$OUT/planner_eval_${MODEL}_sample.json"; echo "exit=$?"
  echo "=== $MODEL guardrails $(date -u +%FT%TZ)"
  $PY scripts/evaluate_guardrails.py --benchmark benchmarks/v2_sample.yaml --client anthropic --model "$MODEL" --workers 4 --output "$OUT/guardrails_${MODEL}_sample.json"; echo "exit=$?"
done
echo "ALLDONE $(date -u +%FT%TZ)"
