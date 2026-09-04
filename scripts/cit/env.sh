# Shared environment for agent runs on the CIT LDG cluster (source me).
cd "$HOME/ml4gw-agent" || exit 1
export ML4GW_CONDOR_ACCOUNTING_GROUP=ligo.dev.o4.cbc.explore.test ML4GW_CONDOR_ACCOUNTING_USER=fan.zhang
# torch 2.10 wheels need AVX2 (x86-64-v3); the pool's RTX PRO 4000 nodes are v2 and die with SIGILL
export ML4GW_CONDOR_EXTRA='{"requirements": "(Microarch >= \"x86_64-v3\")"}'
export GWPY_CACHE=1 HF_HOME=$HOME/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PATH=$HOME/ml4gw-agent/.venv/bin:$HOME/.local/bin:$PATH
export AFRAME_REVISION=3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4
export AMPLFI_REVISION=8b97d2f8459d04924cb010dfee0262260bf3da80
export GWAK_REVISION=gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad
