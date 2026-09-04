#!/bin/bash
# O1-O3 population run through the agent on the CIT HTCondor pool.
#   bash scripts/cit/population_run.sh [parallel] [events.json] [runs-dir] [data-source]
# Each event becomes one whole-plan HTCondor submission (fetch, inspect, Aframe,
# AMPLFI, GWAK at 4096 Hz, reconcile, report); N submissions are polled in parallel.
source "$(dirname "$0")/env.sh"
PAR="${1:-12}"; EVENTS="${2:-benchmarks/population/events.json}"
RUNS="${3:-$HOME/ml4gw-runs/population}"; SOURCE="${4:-ldg}"
mkdir -p "$RUNS"
python - "$EVENTS" <<'PY' > "$RUNS/events.txt"
import json, sys
for name, e in json.load(open(sys.argv[1])).items():
    print(name, e["gps"])
PY
run_one() {
  name="$1"; gps="$2"
  out="$RUNS/$name"; mkdir -p "$out"
  if python "$HOME/ml4gw-agent/scripts/cit/is_complete.py" "$out"
  then echo "$name done"; return; fi
  rm -rf "$out"/submission_*
  uv run ml4gw-agent run "Fetch strain data for $gps, check data quality, run Aframe detection and AMPLFI parameter estimation, then scan anomalies with GWAK and reconcile the two results." \
    --mode real --executor htcondor --runs-dir "$out" --device cuda --seed 0 --ifos H1 L1 \
    --data-source "$SOURCE" --aframe-far 365.25 --gwak-far 365.25 \
    --aframe-revision "$AFRAME_REVISION" --amplfi-revision "$AMPLFI_REVISION" --gwak-revision "$GWAK_REVISION" \
    --poll-interval 30 --wait-timeout 7200 > "$out/agent.log" 2>&1
  echo "$name exit=$?"
}
export -f run_one; export RUNS SOURCE AFRAME_REVISION AMPLFI_REVISION GWAK_REVISION
xargs -a "$RUNS/events.txt" -L 1 -P "$PAR" bash -c 'run_one $0 $1' | tee -a "$RUNS/population.log"
