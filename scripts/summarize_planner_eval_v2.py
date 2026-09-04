#!/usr/bin/env python3
"""Collect the v2 planner / guardrail reports into ``summary.json`` and
Markdown tables.

    uv run python scripts/summarize_planner_eval_v2.py docs/acceptance/planner-eval-v2

Reads ``planner_eval_<model>.json`` (from ``scripts/evaluate_planner.py``) and
``guardrails_<model>.json`` (from ``scripts/evaluate_guardrails.py``), writes
``summary.json`` next to them and prints the tables used in
``docs/PLANNER_EVAL_V2.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def planner_rows(directory: Path) -> list[dict]:
    rows = []
    baseline_done = False
    for path in sorted(directory.glob("planner_eval_*.json")):
        report = json.loads(path.read_text())
        for planner in report["planners"]:
            if planner["planner"] == "baseline-deterministic":
                if baseline_done:
                    continue
                baseline_done = True
                model = "deterministic baseline"
            else:
                model = report.get("model") or planner["planner"]
            by_tag = planner.get("by_tag", {})
            rows.append(
                {
                    "model": model,
                    "cases": planner["cases"],
                    "exact_match": planner["tool_selection_accuracy"],
                    "compatible": planner["tool_selection_compatible"],
                    "validity": planner["plan_validity"],
                    "executed": planner["execution_success"],
                    "reproducible": planner["reproducibility"],
                    "repeats": planner.get("repeats"),
                    "fallback": planner["fallback_rate"],
                    "latency_s": planner["mean_latency_seconds"],
                    "input_tokens": planner.get("total_input_tokens", 0),
                    "output_tokens": planner.get("total_output_tokens", 0),
                    "tokens": planner["total_tokens"],
                    "by_tag": {
                        tag: {
                            "cases": v["cases"],
                            "exact_match": v["tool_selection_accuracy"],
                            "compatible": v.get("tool_selection_compatible"),
                        }
                        for tag, v in by_tag.items()
                    },
                    "source": path.name,
                }
            )
    return rows


def guardrail_rows(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.glob("guardrails_*.json")):
        report = json.loads(path.read_text())
        model = report.get("model") or report["client"]
        for name, summary in report["summary"].items():
            if name == "baseline-deterministic" and rows:
                continue
            rows.append(
                {
                    "model": "deterministic baseline"
                    if name == "baseline-deterministic"
                    else model,
                    "path": name,
                    "cases": summary["cases"],
                    "fail_closed": summary["fail_closed"],
                    "silently_wrong": summary["silently_wrong"],
                    "crash": summary["crash"],
                    "kinds": summary["kinds"],
                    "by_guardrail": summary["by_guardrail"],
                    "tokens": summary.get("total_tokens", 0),
                    "source": path.name,
                }
            )
    return rows


def markdown(planners: list[dict], guardrails: list[dict]) -> str:
    out = []
    out.append(
        "| Model | Cases | Exact match | Superset-compatible | Validity | "
        "Mock execution | Same plan ×3 | Fallback | Latency | Tokens (in / out) |"
    )
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in planners:
        out.append(
            f"| {r['model']} | {r['cases']} | {r['exact_match']:.3f} | "
            f"{r['compatible']:.3f} | {r['validity']:.3f} | {r['executed']:.3f} | "
            f"{r['reproducible']:.3f} | {r['fallback']:.3f} | "
            f"{r['latency_s']:.1f} s | {r['input_tokens']:,} / {r['output_tokens']:,} |"
        )
    out.append("")
    tags = sorted({t for r in planners for t in r["by_tag"]})
    out.append(
        "| Model | " + " | ".join(f"{t} (exact / compatible)" for t in tags) + " |"
    )
    out.append("|---|" + "---:|" * len(tags))
    for r in planners:
        cells = []
        for t in tags:
            v = r["by_tag"].get(t)
            if not v:
                cells.append("—")
                continue
            compat = v["compatible"]
            compat_text = f"{compat:.3f}" if compat is not None else "—"
            cells.append(f"{v['exact_match']:.3f} / {compat_text} (n={v['cases']})")
        out.append(f"| {r['model']} | " + " | ".join(cells) + " |")
    out.append("")
    out.append(
        "| Model | Path | Cases | Fail closed | Silently wrong | Crash | "
        "Outcome kinds |"
    )
    out.append("|---|---|---:|---:|---:|---:|---|")
    for r in guardrails:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(r["kinds"].items()))
        out.append(
            f"| {r['model']} | {r['path']} | {r['cases']} | {r['fail_closed']:.3f} | "
            f"{r['silently_wrong']:.3f} | {r['crash']:.3f} | {kinds} |"
        )
    out.append("")
    kinds = sorted({k for r in guardrails for k in r["by_guardrail"]})
    out.append("| Model | Path | " + " | ".join(kinds) + " |")
    out.append("|---|---|" + "---:|" * len(kinds))
    for r in guardrails:
        cells = []
        for k in kinds:
            v = r["by_guardrail"].get(k)
            cells.append(f"{v['silently_wrong']:.2f} (n={v['cases']})" if v else "—")
        out.append(f"| {r['model']} | {r['path']} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("(last table: fraction silently wrong per guardrail family)")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    planners = planner_rows(args.directory)
    guardrails = guardrail_rows(args.directory)
    summary = {"planner": planners, "guardrails": guardrails}
    (args.directory / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(markdown(planners, guardrails))
    print(f"wrote {args.directory / 'summary.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
