#!/usr/bin/env bash
# Re-run the GPT (CLIProxy) and GLM (Zhipu) MCP model matrices against the
# current server contract and compare them with the 2026-09-24 baselines.
#
# Run on the machine that has CLIProxy and the GLM key file:
#   CLIPROXY_CONFIG=/abs/path/cli-proxy/config.yaml bash scripts/rerun_mcp_matrices.sh
# Options: GLM_KEY_FILE (default docs/key/glm.md), SKIP_GPT=1, SKIP_GLM=1,
#          WORKERS (default 2), DATE (default today, UTC).
# Output dirs must not exist yet; the scripts refuse to overwrite evidence.
set -euo pipefail

DATE="${DATE:-$(date -u +%Y-%m-%d)}"
WORKERS="${WORKERS:-2}"
GLM_KEY_FILE="${GLM_KEY_FILE:-docs/key/glm.md}"
GPT_BASELINE=docs/acceptance/p0-p1-2026-09-24/gpt-matrix/summary.json
GLM_BASELINE=docs/test/glm-retry-2026-09-24/effective-summary.json

uv sync --locked --extra mcp --group dev
uv run --no-sync ruff check . >/dev/null
echo "== contract: planner constraint evidence"
uv run --no-sync python scripts/planner_constraints_check.py \
  --output "docs/test/planner-constraints-${DATE}.json"

if [[ "${SKIP_GPT:-0}" != "1" ]]; then
  : "${CLIPROXY_CONFIG:?set CLIPROXY_CONFIG to the CLIProxy config.yaml (or SKIP_GPT=1)}"
  OUT="docs/test/gpt-matrix-${DATE}"
  echo "== GPT matrix via CLIProxy -> ${OUT}"
  uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \
    --proxy-config "${CLIPROXY_CONFIG}" --workers "${WORKERS}" \
    --runs-dir "runs/mcp-gpt-matrix-${DATE}" --output-dir "${OUT}" || true
  uv run --no-sync python scripts/compare_mcp_matrices.py \
    --baseline "${GPT_BASELINE}" --new "${OUT}/summary.json" \
    --output "${OUT}/compare-vs-2026-09-24.md" || true
fi

if [[ "${SKIP_GLM:-0}" != "1" ]]; then
  [[ -f "${GLM_KEY_FILE}" ]] || { echo "missing ${GLM_KEY_FILE} (or SKIP_GLM=1)"; exit 2; }
  OUT="docs/test/glm-matrix-${DATE}"
  echo "== GLM matrix via open.bigmodel.cn -> ${OUT}"
  uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \
    --base-url https://open.bigmodel.cn/api/paas/v4 \
    --key-file "${GLM_KEY_FILE}" --model-prefix glm- --preserve-reasoning \
    --workers "${WORKERS}" \
    --runs-dir "runs/mcp-glm-matrix-${DATE}" --output-dir "${OUT}" || true
  uv run --no-sync python scripts/compare_mcp_matrices.py \
    --baseline "${GLM_BASELINE}" --new "${OUT}/summary.json" \
    --output "${OUT}/compare-vs-2026-09-24.md" || true
fi

echo "== done. Review docs/test/*-matrix-${DATE}/compare-vs-2026-09-24.md; rate-limited"
echo "   (HTTP 429) models can be retried alone with evaluate_mcp_gpt.py --model <id>."
