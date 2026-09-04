# Shared environment for agent runs on the CIT LDG cluster (source me).
cd "$HOME/ml4gw-agent" || exit 1
export ML4GW_CONDOR_ACCOUNTING_GROUP=ligo.dev.o4.cbc.explore.test ML4GW_CONDOR_ACCOUNTING_USER=fan.zhang
# Build with: uv python install 3.12 && uv venv --python 3.12 --python-preference only-managed && uv sync --extra buoy --extra ldg
# The venv must use a uv-managed Python (uv venv --python 3.12 --python-preference only-managed): worker nodes lack /usr/bin/python3.12.
# torch needs AVX: 517 of the pool's GPU slots are x86-64-v1 (no AVX, SIGILL in run_aframe); the 112 v2 slots work.
export ML4GW_CONDOR_EXTRA='{"requirements": "(Microarch >= \\"x86_64-v2\\")"}'
export GWPY_CACHE=1 HF_HOME=$HOME/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PATH=$HOME/ml4gw-agent/.venv/bin:$HOME/.local/bin:$PATH
export AFRAME_REVISION=3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4
export AMPLFI_REVISION=8b97d2f8459d04924cb010dfee0262260bf3da80
export GWAK_REVISION=gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad
