#!/usr/bin/env python3
"""Compare two MCP model-matrix summaries scenario by scenario.

    uv run --no-sync python scripts/compare_mcp_matrices.py \\
        --baseline docs/acceptance/p0-p1-2026-09-24/gpt-matrix/summary.json \\
        --new docs/test/gpt-matrix-<date>/summary.json \\
        --output docs/test/gpt-matrix-<date>/compare.md

Both inputs are ``summary.json`` files written by ``evaluate_mcp_gpt_matrix.py``
(the GLM effective summary has the same ``models`` list). The Markdown table
shows, per model and scenario, the baseline and new outcome with the failed
checks, plus totals and models present on only one side. A JSON twin is
written next to the Markdown file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYMBOL = {True: "pass", False: "FAIL", None: "n/a"}


def load(path: Path) -> dict[str, dict]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    return {row["model"]: row for row in summary["models"]}


def outcome(row: dict | None, case_id: str) -> tuple[bool | None, list[str]]:
    if row is None:
        return None, []
    for case in row.get("cases", []):
        if case["id"] == case_id:
            return bool(case["passed"]), list(case.get("failed_checks", []))
    return None, [row["error"]] if row.get("error") else []


def compare(baseline: dict[str, dict], new: dict[str, dict]) -> dict:
    models = sorted(set(baseline) | set(new))
    case_ids: list[str] = []
    for row in list(baseline.values()) + list(new.values()):
        for case in row.get("cases", []):
            if case["id"] not in case_ids:
                case_ids.append(case["id"])
    rows = []
    for model in models:
        for case_id in case_ids:
            before, before_failed = outcome(baseline.get(model), case_id)
            after, after_failed = outcome(new.get(model), case_id)
            change = (
                "unchanged"
                if before == after
                else "fixed"
                if before is False and after is True
                else "regressed"
                if before is True and after is False
                else "new"
                if before is None
                else "missing"
            )
            rows.append(
                {
                    "model": model,
                    "case": case_id,
                    "baseline": before,
                    "baseline_failed_checks": before_failed,
                    "new": after,
                    "new_failed_checks": after_failed,
                    "change": change,
                }
            )

    def total(table: dict[str, dict]) -> tuple[int, int]:
        return (
            sum(r.get("passed", 0) for r in table.values()),
            sum(r.get("total", len(case_ids)) for r in table.values()),
        )

    return {
        "models": models,
        "cases": case_ids,
        "only_in_baseline": sorted(set(baseline) - set(new)),
        "only_in_new": sorted(set(new) - set(baseline)),
        "baseline_total": total(baseline),
        "new_total": total(new),
        "fixed": sum(r["change"] == "fixed" for r in rows),
        "regressed": sum(r["change"] == "regressed" for r in rows),
        "rows": rows,
    }


def markdown(report: dict, baseline_path: Path, new_path: Path) -> str:
    lines = [
        "# MCP matrix comparison",
        "",
        f"- Baseline: `{baseline_path}` ({report['baseline_total'][0]}/"
        f"{report['baseline_total'][1]} scenarios)",
        f"- New: `{new_path}` ({report['new_total'][0]}/"
        f"{report['new_total'][1]} scenarios)",
        f"- Fixed: {report['fixed']}; regressed: {report['regressed']}",
    ]
    if report["only_in_baseline"]:
        lines.append(f"- Only in baseline: {', '.join(report['only_in_baseline'])}")
    if report["only_in_new"]:
        lines.append(f"- Only in new: {', '.join(report['only_in_new'])}")
    lines += [
        "",
        "| Model | Scenario | Baseline | New | Change | Failed checks (new) |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['model']} | {row['case']} | {SYMBOL[row['baseline']]} | "
            f"{SYMBOL[row['new']]} | {row['change']} | "
            f"{', '.join(row['new_failed_checks']) or ''} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, help="Markdown path; JSON twin alongside"
    )
    args = parser.parse_args(argv)
    report = compare(load(args.baseline), load(args.new))
    text = markdown(report, args.baseline, args.new)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        args.output.with_suffix(".json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(text)
    return 0 if report["regressed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
