#!/bin/bash
# Real runs for the GraceDB QA set: one HTCondor submission per prompt.
#   bash scripts/cit/qa_run.sh <qa_prompts.json> [runs-dir] [parallel]
source "$(dirname "$0")/env.sh"
PROMPTS="$1"; RUNS="${2:-$HOME/ml4gw-runs/gracedb-qa}"; PAR="${3:-6}"
mkdir -p "$RUNS"
python - "$PROMPTS" <<'PY' > "$RUNS/cases.tsv"
import json, sys
for case, prompt in json.load(open(sys.argv[1])).items():
    print(case + "\t" + prompt)
PY
run_one() {
  case="$1"; prompt="$2"; out="$RUNS/$case"; mkdir -p "$out"
  if python "$HOME/ml4gw-agent/scripts/cit/is_complete.py" "$out"; then echo "$case done"; return; fi
  rm -rf "$out"/submission_*
  uv run ml4gw-agent run "$prompt" --mode real --executor htcondor --runs-dir "$out" --device cuda --seed 0 --ifos H1 L1 \
    --data-source gwosc --aframe-far 365.25 --aframe-revision "$AFRAME_REVISION" --amplfi-revision "$AMPLFI_REVISION" \
    --poll-interval 30 --wait-timeout 7200 > "$out/agent.log" 2>&1
  echo "$case exit=$?"
}
export -f run_one; export RUNS AFRAME_REVISION AMPLFI_REVISION
while IFS=$'\t' read -r case prompt; do printf '%s\0%s\0' "$case" "$prompt"; done < "$RUNS/cases.tsv" | xargs -0 -n 2 -P "$PAR" bash -c 'run_one "$0" "$1"' | tee -a "$RUNS/qa.log"
