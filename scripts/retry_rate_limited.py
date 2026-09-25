#!/usr/bin/env python3
"""Re-run rate-limited models once, alone, and write an effective summary.

An HTTP 429 carries no information about tool use: the provider refused
before the model answered. Following the 2026-09-24 GLM methodology, every
model with a 429 in the matrix is re-run once, serially, after a pause. The
matrix ``summary.json`` is left untouched; ``effective-summary.json`` next to
it replaces only the re-run rows and records why. A second 429 is kept as the
result, not retried again. Other failures (HTTP 408, wrong task graphs,
parameter errors) are never re-run.

    uv run --no-sync python scripts/retry_rate_limited.py \\
        --summary docs/test/glm-matrix-<date>/summary.json \\
        --retry-dir docs/test/glm-retry-<date> \\
        --runs-dir runs/mcp-glm-retry-<date> --wait 100 \\
        -- --base-url https://open.bigmodel.cn/api/paas/v4 \\
           --api-key-env GLM_API_KEY --preserve-reasoning

Arguments after ``--`` are passed to ``evaluate_mcp_gpt.py`` unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RATE_LIMITED = "HTTP 429"


def rate_limited_models(summary: dict) -> list[str]:
    """Models with at least one conversation refused with HTTP 429."""
    models = []
    for row in summary.get("models", []):
        errors = [row.get("error") or ""]
        errors += [c.get("error") or "" for c in row.get("cases", [])]
        if any(RATE_LIMITED in e for e in errors):
            models.append(row["model"])
    return models


def effective_summary(
    summary: dict, replacements: dict[str, dict], source: str, wait: float
) -> dict:
    rows = []
    for row in summary.get("models", []):
        rows.append(copy.deepcopy(replacements.get(row["model"], row)))
    total_assertions = sum(r.get("assertions_total", 0) for r in rows)
    return {
        "definition": (
            "First complete conversation per model: the matrix run, except that "
            "models refused with HTTP 429 are replaced by one serial re-run after "
            f"a {wait:g} s pause. {source} is unchanged."
        ),
        "source_summary": source,
        "replaced_models": sorted(replacements),
        "models": rows,
        "passed": sum(r.get("passed", 0) for r in rows),
        "total": sum(r.get("total", 0) for r in rows),
        "assertions_passed": sum(r.get("assertions_passed", 0) for r in rows),
        "assertions_total": total_assertions,
    }


def rerun(model: str, args: argparse.Namespace, passthrough: list[str]) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    from evaluate_mcp_gpt_matrix import summarize, verify_artifacts

    output = args.retry_dir / f"{model}.json"
    command = [
        sys.executable,
        str(SCRIPTS / "evaluate_mcp_gpt.py"),
        "--model",
        model,
        "--runs-dir",
        str(args.runs_dir / model),
        "--output",
        str(output),
        *passthrough,
    ]
    started = time.monotonic()
    completed = subprocess.run(command, check=False)
    elapsed = time.monotonic() - started
    if not output.is_file():
        return {
            "model": model,
            "error": f"retry produced no report (exit {completed.returncode})",
            "passed": 0,
            "total": 0,
            "retry": {"report": None, "wait_seconds": args.wait},
        }
    report = json.loads(output.read_text(encoding="utf-8"))
    row = summarize(report, elapsed)
    try:
        row["artifact_verification"] = verify_artifacts(report)
    except Exception as exc:  # recorded, never raised: evidence over exceptions
        row["artifact_verification"] = {"passed": False, "error": type(exc).__name__}
    row["retry"] = {
        "reason": "HTTP 429 in the matrix run",
        "wait_seconds": args.wait,
        "report": output.name,
    }
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--retry-dir", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--wait", type=float, default=100.0)
    parser.add_argument("passthrough", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    passthrough = args.passthrough[1:] if args.passthrough[:1] == ["--"] else []

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    targets = rate_limited_models(summary)
    replacements: dict[str, dict] = {}
    if targets:
        args.retry_dir.mkdir(parents=True, exist_ok=True)
    for model in targets:
        print(
            f"[retry] {model}: HTTP 429 in matrix; waiting {args.wait:g} s", flush=True
        )
        time.sleep(args.wait)
        replacements[model] = rerun(model, args, passthrough)
        row = replacements[model]
        print(f"[retry] {model}: {row.get('passed')}/{row.get('total')}", flush=True)
    if targets:
        (args.retry_dir / "summary.json").write_text(
            json.dumps(
                {"retried": targets, "wait_seconds": args.wait, "models": replacements},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    effective = effective_summary(summary, replacements, args.summary.name, args.wait)
    path = args.summary.with_name("effective-summary.json")
    path.write_text(
        json.dumps(effective, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"effective: {effective['passed']}/{effective['total']} scenarios, "
        f"retried {targets or 'none'} -> {path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
