#!/bin/bash
# Re-queue background shards whose JSON is missing or has fewer than 40 lags
# (e.g. workers killed by SIGILL on x86-64-v1 nodes before the requirement fix).
source "$(dirname "$0")/env.sh"
OUT="${1:-$HOME/ml4gw-runs/background}"
python - "$OUT" > "$OUT/redo.txt" <<'PY'
import json, sys, os
out = sys.argv[1]
for line in open(os.path.join(out, "stretches.txt")):
    idx, start, end = line.split()
    for pipe, mem in (("aframe", "32GB"), ("gwak", "16GB")):
        f = os.path.join(out, f"{pipe}_{idx}.json")
        done = os.path.exists(f) and len(json.load(open(f)).get("lags", [])) >= 40
        if not done:
            print(f"{pipe},{idx},{start},{end},{mem}")
PY
wc -l < "$OUT/redo.txt"
sed -e '/^queue pipe/,$d' "$OUT/background.sub" > "$OUT/background_redo.sub"
sed -i 's/^requirements = .*/requirements = (GPUs_Capability >= 7.0) \&\& (Microarch >= "x86_64-v2")/' "$OUT/background_redo.sub"
{ echo "queue pipe,idx,start,end,mem from ("; cat "$OUT/redo.txt"; echo ")"; } >> "$OUT/background_redo.sub"
condor_submit "$OUT/background_redo.sub"
