#!/bin/bash
export PATH=/root/miniconda3/bin:$PATH
unset HF_HUB_OFFLINE
export GWPY_CACHE=1 CUDA_VISIBLE_DEVICES=2 PYTHONUNBUFFERED=1
cd /root/ml4gw-agent
uv run python scripts/gwak_background.py \
  --stretch 1126256640 1126260736 --event 1126259462.4 \
  --stretch 1187006835 1187010931 --event 1187008882.4 \
  --stretch 1242440920 1242445016 --event 1242442967.4 \
  --shifts 40 --output /root/autodl-tmp/ml4gw-agent-runs/gwak-background/gwak_background.json
echo "exit=$? $(date -u +%FT%TZ)"
