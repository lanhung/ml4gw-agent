#!/usr/bin/env bash
# One command for the live MCP model matrices under the current contract:
#   planner-constraint evidence -> GPT matrix (CLIProxy) -> GLM matrix (Zhipu)
#   -> one serial re-run of HTTP 429 models -> comparison with the 2026-09-24
#   baselines -> credential leak check -> optional commit / push.
#
# Credentials are read from the environment or files, never from arguments,
# and each matrix only sees its own key:
#   GPT: CLIPROXY_API_KEY=<client key>  or  CLIPROXY_CONFIG=/abs/cli-proxy/config.yaml
#   GLM: GLM_API_KEY=<key>              or  GLM_KEY_FILE (default docs/key/glm.md)
#
#   read -rs GLM_API_KEY && export GLM_API_KEY
#   CLIPROXY_CONFIG=/abs/path/config.yaml COMMIT=1 bash scripts/rerun_mcp_matrices.sh
#
# Options: SKIP_GPT=1, SKIP_GLM=1, COMMIT=1 (git add + commit after a clean leak
# check), PUSH=1 (also git push; implies COMMIT=1), DATE (UTC today), WORKERS (2),
# RETRY_WAIT (100 s), SYNC (1 = uv sync first), OUTPUT_ROOT (docs/test),
# RUNS_ROOT (runs), GPT_BASE_URL, GPT_MODEL_PREFIX, GLM_BASE_URL, GLM_MODEL_PREFIX.
# Output directories must not exist yet; earlier evidence is never overwritten.
set -euo pipefail
cd "$(dirname "$0")/.."

DATE="${DATE:-$(date -u +%Y-%m-%d)}"
WORKERS="${WORKERS:-2}"
RETRY_WAIT="${RETRY_WAIT:-100}"
OUTPUT_ROOT="${OUTPUT_ROOT:-docs/test}"
RUNS_ROOT="${RUNS_ROOT:-runs}"
GPT_BASE_URL="${GPT_BASE_URL:-http://127.0.0.1:8317/v1}"
GPT_MODEL_PREFIX="${GPT_MODEL_PREFIX:-gpt-}"
GLM_BASE_URL="${GLM_BASE_URL:-https://open.bigmodel.cn/api/paas/v4}"
GLM_MODEL_PREFIX="${GLM_MODEL_PREFIX:-glm-}"
GLM_KEY_FILE="${GLM_KEY_FILE:-docs/key/glm.md}"
GPT_BASELINE=docs/acceptance/p0-p1-2026-09-24/gpt-matrix/summary.json
GLM_BASELINE=docs/test/glm-retry-2026-09-24/effective-summary.json
if [[ "${PUSH:-0}" == 1 ]]; then COMMIT=1; fi
COMMIT="${COMMIT:-0}"
RUN_GPT=1; RUN_GLM=1
if [[ "${SKIP_GPT:-0}" == 1 ]]; then RUN_GPT=0; fi
if [[ "${SKIP_GLM:-0}" == 1 ]]; then RUN_GLM=0; fi

die() { echo "error: $*" >&2; exit 2; }
empty_or_absent() { [[ ! -e "$1" ]] || [[ -z "$(ls -A "$1")" ]]; }

# ---- fail fast: credentials and output directories ------------------------
LEAK_ARGS=(--env CLIPROXY_API_KEY --env GLM_API_KEY)
if [[ $RUN_GPT == 1 ]]; then
  if [[ -n "${CLIPROXY_API_KEY:-}" ]]; then
    GPT_CRED=(--api-key-env CLIPROXY_API_KEY)
  elif [[ -n "${CLIPROXY_CONFIG:-}" ]]; then
    [[ -f "$CLIPROXY_CONFIG" ]] || die "CLIPROXY_CONFIG not found: $CLIPROXY_CONFIG"
    GPT_CRED=(--proxy-config "$CLIPROXY_CONFIG")
    LEAK_ARGS+=(--proxy-config "$CLIPROXY_CONFIG")
  else
    die "set CLIPROXY_API_KEY or CLIPROXY_CONFIG (or SKIP_GPT=1)"
  fi
  empty_or_absent "$OUTPUT_ROOT/gpt-matrix-$DATE" \
    || die "$OUTPUT_ROOT/gpt-matrix-$DATE exists; choose another DATE"
fi
if [[ $RUN_GLM == 1 ]]; then
  if [[ -n "${GLM_API_KEY:-}" ]]; then
    GLM_CRED=(--api-key-env GLM_API_KEY)
  elif [[ -f "$GLM_KEY_FILE" ]]; then
    GLM_CRED=(--key-file "$GLM_KEY_FILE")
    LEAK_ARGS+=(--key-file "$GLM_KEY_FILE")
  else
    die "set GLM_API_KEY or create $GLM_KEY_FILE (or SKIP_GLM=1)"
  fi
  empty_or_absent "$OUTPUT_ROOT/glm-matrix-$DATE" \
    || die "$OUTPUT_ROOT/glm-matrix-$DATE exists; choose another DATE"
fi
[[ $RUN_GPT == 1 || $RUN_GLM == 1 ]] || die "both SKIP_GPT and SKIP_GLM are set"

if [[ "${SYNC:-1}" == 1 ]]; then uv sync --locked --extra mcp --group dev; fi
PY=(uv run --no-sync python)

echo "== planner constraint evidence"
CONSTRAINTS="$OUTPUT_ROOT/planner-constraints-$DATE.json"
"${PY[@]}" scripts/planner_constraints_check.py --output "$CONSTRAINTS"
NEW_PATHS=("$CONSTRAINTS")

# run_matrix NAME BASE_URL PREFIX BASELINE HIDDEN_ENV CRED...
run_matrix() {
  local name=$1 base=$2 prefix=$3 baseline=$4 hidden=$5
  shift 5
  local out="$OUTPUT_ROOT/$name-matrix-$DATE" retry="$OUTPUT_ROOT/$name-retry-$DATE"
  echo "== $name matrix ($base, prefix $prefix) -> $out"
  env -u "$hidden" "${PY[@]}" scripts/evaluate_mcp_gpt_matrix.py \
    --base-url "$base" --model-prefix "$prefix" --workers "$WORKERS" \
    --runs-dir "$RUNS_ROOT/mcp-$name-matrix-$DATE" --output-dir "$out" "$@" \
    || echo "   (matrix exit $?: failures are recorded in $out/summary.json)"
  [[ -f "$out/summary.json" ]] || die "$name matrix wrote no summary; see output above"
  env -u "$hidden" "${PY[@]}" scripts/retry_rate_limited.py \
    --summary "$out/summary.json" --retry-dir "$retry" \
    --runs-dir "$RUNS_ROOT/mcp-$name-retry-$DATE" --wait "$RETRY_WAIT" \
    -- --base-url "$base" "$@"
  "${PY[@]}" scripts/compare_mcp_matrices.py --baseline "$baseline" \
    --new "$out/effective-summary.json" --output "$out/compare-vs-2026-09-24.md" \
    >/dev/null || true
  NEW_PATHS+=("$out")
  if [[ -d "$retry" ]]; then NEW_PATHS+=("$retry"); fi
}

if [[ $RUN_GPT == 1 ]]; then
  run_matrix gpt "$GPT_BASE_URL" "$GPT_MODEL_PREFIX" "$GPT_BASELINE" GLM_API_KEY \
    "${GPT_CRED[@]}"
fi
if [[ $RUN_GLM == 1 ]]; then
  run_matrix glm "$GLM_BASE_URL" "$GLM_MODEL_PREFIX" "$GLM_BASELINE" CLIPROXY_API_KEY \
    "${GLM_CRED[@]}" --preserve-reasoning
fi

echo "== results"
for name in gpt glm; do
  report="$OUTPUT_ROOT/$name-matrix-$DATE/compare-vs-2026-09-24.json"
  [[ -f "$report" ]] || continue
  "${PY[@]}" -c 'import json, sys
r = json.load(open(sys.argv[1]))
n, b, fixed, regressed = r["new_total"], r["baseline_total"], r["fixed"], r["regressed"]
print(f"{sys.argv[2]}: {n[0]}/{n[1]} scenarios (2026-09-24: {b[0]}/{b[1]}); "
      f"fixed {fixed}, regressed {regressed}")' "$report" "$name"
done

echo "== credential leak check"
"${PY[@]}" scripts/check_no_secrets.py "${LEAK_ARGS[@]}" "${NEW_PATHS[@]}" \
  || { echo "leak check failed: nothing was committed" >&2; exit 1; }

if [[ $COMMIT == 1 ]]; then
  git add -- "${NEW_PATHS[@]}"
  git commit -m "MCP matrices rerun under the plan_analysis contract ($DATE)"
  if [[ "${PUSH:-0}" == 1 ]]; then git push origin HEAD; fi
else
  echo "Review, then: git add ${NEW_PATHS[*]} && git commit && git push"
fi
