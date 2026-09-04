#!/bin/bash
# Sharded time-shift background on the CIT GPU pool: one job per stretch and
# pipeline (aframe | gwak), 40 lags of 8 s each (~1.8 d livetime per job).
#   bash scripts/cit/background_submit.sh [stretches.json] [out-dir]
source "$(dirname "$0")/env.sh"
STRETCHES="${1:-benchmarks/population/background_stretches.json}"
OUT="${2:-$HOME/ml4gw-runs/background}"; mkdir -p "$OUT/log"
python - "$STRETCHES" > "$OUT/stretches.txt" <<'PY'
import json, sys
for i, s in enumerate(json.load(open(sys.argv[1]))):
    print(i, s["start"], s["end"])
PY
cat > "$OUT/worker.sh" <<'WRK'
#!/bin/bash
pipe="$1"; idx="$2"; start="$3"; end="$4"; out="$5"
cd "$HOME/ml4gw-agent" || exit 1
export GWPY_CACHE=1 HF_HOME=$HOME/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 PATH=$HOME/ml4gw-agent/.venv/bin:$PATH
if [ "$pipe" = aframe ]; then
  python scripts/aframe_background.py --revision 3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4 --stretch "$start" "$end" --shifts 40 \
    --output "$out/aframe_$idx.json" --peaks-output "$out/aframe_$idx.npy"
else
  python scripts/gwak_background.py --stretch "$start" "$end" --shifts 40 \
    --output "$out/gwak_$idx.json" --peaks-output "$out/gwak_$idx.npy"
fi
WRK
chmod +x "$OUT/worker.sh"
cat > "$OUT/background.sub" <<SUB
universe = vanilla
executable = $OUT/worker.sh
arguments = \$(pipe) \$(idx) \$(start) \$(end) $OUT
request_cpus = 4
request_memory = 16GB
request_disk = 8GB
request_gpus = 1
requirements = (Microarch >= "x86_64-v3")
accounting_group = ligo.dev.o4.cbc.explore.test
accounting_group_user = fan.zhang
should_transfer_files = NO
environment = "HOME=$HOME"
log = $OUT/log/\$(pipe)_\$(idx).log
output = $OUT/log/\$(pipe)_\$(idx).out
error = $OUT/log/\$(pipe)_\$(idx).err
queue pipe,idx,start,end from (
$(awk '{print "aframe," $1 "," $2 "," $3 "\ngwak," $1 "," $2 "," $3}' "$OUT/stretches.txt")
)
SUB
condor_submit "$OUT/background.sub"
