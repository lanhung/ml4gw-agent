# Shared environment for agent runs on the CIT LDG cluster (source me).
cd "$HOME/ml4gw-agent" || exit 1
export ML4GW_CONDOR_ACCOUNTING_GROUP=ligo.dev.o4.cbc.explore.test ML4GW_CONDOR_ACCOUNTING_USER=fan.zhang
# The venv must use a uv-managed Python (uv venv --python 3.12 --python-preference only-managed): worker nodes lack /usr/bin/python3.12.
# no Microarch requirement: the full Aframe+GWAK run was verified on an x86-64-v2 RTX PRO 4000 node (2026-09-04)
export GWPY_CACHE=1 HF_HOME=$HOME/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PATH=$HOME/ml4gw-agent/.venv/bin:$HOME/.local/bin:$PATH
export AFRAME_REVISION=3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4
export AMPLFI_REVISION=8b97d2f8459d04924cb010dfee0262260bf3da80
export GWAK_REVISION=gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad
