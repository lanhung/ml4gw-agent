#!/bin/bash
# Re-runs after the first pass of run_all.sh: the claude-sonnet-5 planner
# evaluation was killed by a SIGTERM after 15 minutes, and claude-haiku-4-5
# rejects the `effort` parameter (400 "This model does not support the effort
# parameter"), so it is rerun with --effort none.
set -u
cd "$(dirname "$0")/../../.."
export ANTHROPIC_API_KEY="$(cat /home/dev/.anthropic_key)"
export PYTHONPATH=src
PY=/home/dev/work/ml4gw-agent/.venv-local/bin/python
OUT=docs/acceptance/planner-eval-v2
echo "=== claude-sonnet-5 planner $(date -u +%FT%TZ)"
$PY scripts/evaluate_planner.py --benchmark benchmarks/v2_prompts.yaml \
    --client anthropic --model claude-sonnet-5 --workers 8 --repeats 3 \
    --output "$OUT/planner_eval_claude-sonnet-5.json"
echo "exit=$?"
MODEL=claude-haiku-4-5-20251001
echo "=== $MODEL planner (effort none) $(date -u +%FT%TZ)"
$PY scripts/evaluate_planner.py --benchmark benchmarks/v2_prompts.yaml \
    --client anthropic --model "$MODEL" --effort none --workers 8 --repeats 3 \
    --output "$OUT/planner_eval_$MODEL.json"
echo "exit=$?"
echo "=== $MODEL guardrails (effort none) $(date -u +%FT%TZ)"
$PY scripts/evaluate_guardrails.py --benchmark benchmarks/v2_prompts.yaml \
    --client anthropic --model "$MODEL" --effort none --workers 8 \
    --output "$OUT/guardrails_$MODEL.json"
echo "exit=$?"
echo "ALLDONE $(date -u +%FT%TZ)"
