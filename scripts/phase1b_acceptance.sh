#!/usr/bin/env bash
# Phase 1b acceptance run for ML4GW Agent.
#
# Run on a node with GWOSC network access and (preferably) a CUDA GPU, for
# example an AutoDL GPU instance or an LDG head node. Everything it needs is
# pinned; the only inputs are the two immutable model revisions.
#
#   AFRAME_REVISION=<sha> AMPLFI_REVISION=<sha> bash scripts/phase1b_acceptance.sh
#
# Optional: DEVICE=cpu (slow), RUNS_DIR=./runs, SEED=0, EVENT=GW150914,
# IFOS="H1 L1" (the detector set given to the agent *and* to the direct Buoy
# run; without it Buoy would pick every detector GWOSC lists for the event,
# which for three-detector events selects a different AMPLFI model than the
# agent and makes the comparison meaningless).
# Steps 1-3 are allowed to fail: a failed step is recorded (exit code in
# status.txt, failure manifest/log kept) and the later steps still run, so
# an event Buoy cannot handle still yields the decomposed run. The script's
# own exit code is non-zero when any step failed.
set -uo pipefail

EVENT="${EVENT:-GW150914}"
DEVICE="${DEVICE:-cuda}"
SEED="${SEED:-0}"
RUNS_DIR="${RUNS_DIR:-./runs}"
IFOS="${IFOS:-H1 L1}"
# shellcheck disable=SC2206
IFO_ARRAY=(${IFOS})
IFOS_JSON="$(printf '"%s",' "${IFO_ARRAY[@]}")"
IFOS_JSON="[${IFOS_JSON%,}]"
: "${AFRAME_REVISION:?set AFRAME_REVISION to an immutable ML4GW/aframe commit}"
: "${AMPLFI_REVISION:?set AMPLFI_REVISION to an immutable ML4GW/amplfi commit}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${RUNS_DIR}/phase1b-${EVENT}-${STAMP}"
mkdir -p "${OUT}"
echo "acceptance output: ${OUT} (event ${EVENT}, detectors ${IFOS})"

STATUS="${OUT}/status.txt"
: > "${STATUS}"
record() { echo "$1 exit=$2" | tee -a "${STATUS}"; }
FAILED=0

echo "== 0. environment"
uv sync --extra buoy --group dev || exit 1
uv run python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" | tee "${OUT}/env.txt"
uv run python - "${EVENT}" <<'PY' | tee -a "${OUT}/env.txt"
import sys
import gwosc.datasets
import gwosc.timeline

event = sys.argv[1]
if event.upper().startswith("GW"):
    gps = gwosc.datasets.event_gps(event)
    print(f"GWOSC reachable, {event} at {gps}")
else:
    gps = float(event)
    segments = gwosc.timeline.get_segments("H1_DATA", int(gps) - 64, int(gps) + 64)
    print(f"GWOSC reachable, GPS {gps}: H1_DATA segments {segments}")
PY
uv run ml4gw-agent doctor --mode real | tee "${OUT}/doctor.json"

echo "== 1. Buoy vertical slice through the agent"
uv run ml4gw-agent run "Analyze ${EVENT}" \
  --mode real --runs-dir "${OUT}/agent-buoy" \
  --device "${DEVICE}" --seed "${SEED}" --ifos "${IFO_ARRAY[@]}" \
  --aframe-revision "${AFRAME_REVISION}" \
  --amplfi-revision "${AMPLFI_REVISION}" | tee "${OUT}/agent-buoy.json"
RC=${PIPESTATUS[0]}; record agent-buoy "${RC}"; [ "${RC}" -eq 0 ] || FAILED=1

echo "== 2. Decomposed plan: data.fetch -> data.inspect -> aframe.detect -> amplfi.pe"
uv run ml4gw-agent run \
  "Fetch strain data for ${EVENT}, check data quality, run Aframe detection and AMPLFI parameter estimation." \
  --mode real --runs-dir "${OUT}/agent-decomposed" \
  --device "${DEVICE}" --seed "${SEED}" --ifos "${IFO_ARRAY[@]}" \
  --aframe-revision "${AFRAME_REVISION}" \
  --amplfi-revision "${AMPLFI_REVISION}" | tee "${OUT}/agent-decomposed.json"
RC=${PIPESTATUS[0]}; record agent-decomposed "${RC}"; [ "${RC}" -eq 0 ] || FAILED=1

echo "== 3. Direct Buoy reference run with the same seed and revisions"
uv run buoy --events "${EVENT}" --outdir "${OUT}/buoy-direct" \
  --device "${DEVICE}" --seed "${SEED}" --ifos "${IFOS_JSON}" \
  --aframe_revision "${AFRAME_REVISION}" --amplfi_revision "${AMPLFI_REVISION}" \
  --to_html true 2>&1 | tee "${OUT}/buoy-direct.log"
RC=${PIPESTATUS[0]}; record buoy-direct "${RC}"; [ "${RC}" -eq 0 ] || FAILED=1

echo "== 4. Numerical comparison"
run_dir() { python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('run_directory',''))" "$1" 2>/dev/null; }
AGENT_BUOY_DIR="$(run_dir "${OUT}/agent-buoy.json")"
AGENT_DECOMPOSED_DIR="$(run_dir "${OUT}/agent-decomposed.json")"
for pair in "buoy-slice:${AGENT_BUOY_DIR}" "decomposed:${AGENT_DECOMPOSED_DIR}"; do
  name="${pair%%:*}"; dir="${pair#*:}"
  if [ -n "${dir}" ] && [ -f "${dir}/run_manifest.json" ] && [ -d "${OUT}/buoy-direct/${EVENT}" ]; then
    uv run python scripts/compare_with_buoy.py "${dir}" "${OUT}/buoy-direct/${EVENT}" \
      | tee "${OUT}/compare-${name}.json"
    RC=${PIPESTATUS[0]}; record "compare-${name}" "${RC}"; [ "${RC}" -eq 0 ] || FAILED=1
  else
    record "compare-${name}" "skipped (missing agent run or direct Buoy output)"
    FAILED=1
  fi
done

echo "== done (failed=${FAILED}). Attach ${OUT} (manifests, reports, comparisons, status.txt) to the acceptance record"
exit "${FAILED}"
