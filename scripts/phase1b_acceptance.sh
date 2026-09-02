#!/usr/bin/env bash
# Phase 1b acceptance run for ML4GW Agent.
#
# Run on a node with GWOSC network access and (preferably) a CUDA GPU, for
# example an AutoDL GPU instance or an LDG head node. Everything it needs is
# pinned; the only inputs are the two immutable model revisions.
#
#   AFRAME_REVISION=<sha> AMPLFI_REVISION=<sha> bash scripts/phase1b_acceptance.sh
#
# Optional: DEVICE=cpu (slow), RUNS_DIR=./runs, SEED=0, EVENT=GW150914.
set -euo pipefail

EVENT="${EVENT:-GW150914}"
DEVICE="${DEVICE:-cuda}"
SEED="${SEED:-0}"
RUNS_DIR="${RUNS_DIR:-./runs}"
: "${AFRAME_REVISION:?set AFRAME_REVISION to an immutable ML4GW/aframe commit}"
: "${AMPLFI_REVISION:?set AMPLFI_REVISION to an immutable ML4GW/amplfi commit}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${RUNS_DIR}/phase1b-${EVENT}-${STAMP}"
mkdir -p "${OUT}"
echo "acceptance output: ${OUT}"

echo "== 0. environment"
uv sync --extra buoy --group dev
uv run python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" | tee "${OUT}/env.txt"
uv run python -c "import gwosc.datasets as d; print('GWOSC reachable, ${EVENT} at', d.event_gps('${EVENT}'))" | tee -a "${OUT}/env.txt"
uv run ml4gw-agent doctor --mode real | tee "${OUT}/doctor.json"

echo "== 1. Buoy vertical slice through the agent"
uv run ml4gw-agent run "Analyze ${EVENT}" \
  --mode real --runs-dir "${OUT}/agent-buoy" \
  --device "${DEVICE}" --seed "${SEED}" \
  --aframe-revision "${AFRAME_REVISION}" \
  --amplfi-revision "${AMPLFI_REVISION}" | tee "${OUT}/agent-buoy.json"

echo "== 2. Decomposed plan: data.fetch -> data.inspect -> aframe.detect -> amplfi.pe"
uv run ml4gw-agent run \
  "Fetch strain data for ${EVENT}, check data quality, run Aframe detection and AMPLFI parameter estimation." \
  --mode real --runs-dir "${OUT}/agent-decomposed" \
  --device "${DEVICE}" --seed "${SEED}" \
  --aframe-revision "${AFRAME_REVISION}" \
  --amplfi-revision "${AMPLFI_REVISION}" | tee "${OUT}/agent-decomposed.json"

echo "== 3. Direct Buoy reference run with the same seed and revisions"
uv run buoy --events "${EVENT}" --outdir "${OUT}/buoy-direct" \
  --device "${DEVICE}" --seed "${SEED}" \
  --aframe_revision "${AFRAME_REVISION}" --amplfi_revision "${AMPLFI_REVISION}" \
  --to_html true 2>&1 | tee "${OUT}/buoy-direct.log"

echo "== 4. Numerical comparison"
AGENT_BUOY_DIR="$(python3 -c "import json;print(json.load(open('${OUT}/agent-buoy.json'))['run_directory'])")"
AGENT_DECOMPOSED_DIR="$(python3 -c "import json;print(json.load(open('${OUT}/agent-decomposed.json'))['run_directory'])")"
uv run python scripts/compare_with_buoy.py "${AGENT_BUOY_DIR}" "${OUT}/buoy-direct/${EVENT}" \
  | tee "${OUT}/compare-buoy-slice.json"
uv run python scripts/compare_with_buoy.py "${AGENT_DECOMPOSED_DIR}" "${OUT}/buoy-direct/${EVENT}" \
  | tee "${OUT}/compare-decomposed.json"

echo "== done. Attach ${OUT} (manifests, reports, comparisons) to docs/V0_ACCEPTANCE.md"
