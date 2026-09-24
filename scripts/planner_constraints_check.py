#!/usr/bin/env python3
"""Deterministic evidence for the planner's request-constraint handling.

Re-plans the prompts that failed in the 2026-09-24 GPT and GLM MCP matrices
(negated AMPLFI mentions, the Buoy-worded decomposed request) plus structured
``pipeline`` / ``exclude_skills`` controls, and writes a JSON record with the
planner source hash. No model is called and no science runs.

    uv run --no-sync python scripts/planner_constraints_check.py \\
        --output docs/acceptance/p0-p1-2026-09-24/planner-constraints.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ml4gw_agent.errors import PlanningError
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.registry import load_default_registry

AFRAME_GWAK = [
    "data.resolve_event",
    "data.fetch",
    "data.inspect",
    "aframe.detect",
    "data.fetch",
    "gwak.scan",
    "analysis.reconcile",
    "report.generate",
]
AFRAME_AMPLFI = [
    "data.resolve_event",
    "data.fetch",
    "data.inspect",
    "aframe.detect",
    "amplfi.pe",
    "report.generate",
]
BUOY = ["data.resolve_event", "buoy.analyze", "report.generate"]

CASES: list[dict] = [
    {
        "id": "control",
        "prompt": "Run Aframe and GWAK on GW150914 and reconcile the two results.",
        "expected_skills": AFRAME_GWAK,
    },
    {
        "id": "negative_english",
        "origin": "gpt-5.6-sol aframe_gwak, matrix 2026-09-24",
        "prompt": "Run Aframe and GWAK on GW150914 and reconcile the two results. "
        "Do not run AMPLFI.",
        "expected_skills": AFRAME_GWAK,
        "expected_excluded": ["amplfi.pe"],
    },
    {
        "id": "negative_chinese",
        "origin": "gpt-6-sol aframe_gwak, matrix 2026-09-24",
        "prompt": "Run Aframe and GWAK on GW150914 and reconcile the two results. "
        "不要运行 AMPLFI 参数估计。",
        "expected_skills": AFRAME_GWAK,
        "expected_excluded": ["amplfi.pe"],
    },
    {
        "id": "buoy_wording_forced_decomposed",
        "origin": "gpt-6-luna aframe_amplfi, matrix 2026-09-24",
        "prompt": "Run the Buoy event analysis pipeline for GW150914, using Aframe "
        "detection followed by AMPLFI parameter estimation.",
        "config": {"pipeline": "decomposed"},
        "expected_skills": AFRAME_AMPLFI,
    },
    {
        "id": "buoy_wording_auto",
        "prompt": "Run the Buoy event analysis pipeline for GW150914, using Aframe "
        "detection followed by AMPLFI parameter estimation.",
        "expected_skills": BUOY,
    },
    {
        "id": "generic_default_route",
        "origin": "GLM default-route mismatches, matrix 2026-09-24",
        "prompt": "使用默认流程分析 GW150914",
        "expected_skills": BUOY,
    },
    {
        "id": "generic_forced_buoy_despite_tool_words",
        "prompt": "Analyze GW150914 using the default pipeline: resolve event, "
        "fetch strain, run Aframe detection and AMPLFI parameter estimation.",
        "config": {"pipeline": "buoy"},
        "expected_skills": BUOY,
    },
    {
        "id": "structured_exclusion",
        "prompt": "Analyze GW150914.",
        "config": {"exclude_skills": ["amplfi.pe"]},
        "expected_skills": [
            "data.resolve_event",
            "data.fetch",
            "data.inspect",
            "aframe.detect",
            "report.generate",
        ],
        "expected_excluded": ["amplfi.pe"],
    },
    {
        "id": "contradiction_fails_closed",
        "prompt": "Run AMPLFI parameter estimation on GW150914 and do not run AMPLFI.",
        "expected_error": "both asks for and rules out",
    },
    {
        "id": "worded_prerequisite_exclusion_is_overridden",
        "origin": "v1/v2 benchmark adv_amplfi_conditional cases",
        "prompt": "Run AMPLFI on GW150914 without running Aframe first.",
        "expected_skills": AFRAME_AMPLFI,
        "expected_excluded": [],
    },
    {
        "id": "structured_prerequisite_exclusion_fails_closed",
        "prompt": "Run AMPLFI parameter estimation on GW150914.",
        "config": {"exclude_skills": ["aframe.detect"]},
        "expected_error": "cannot run with aframe.detect excluded",
    },
    {
        "id": "buoy_pipeline_with_gwak_fails_closed",
        "prompt": "Run GWAK on GW150914.",
        "config": {"pipeline": "buoy"},
        "expected_error": "covers Aframe and AMPLFI only",
    },
]


def run_case(registry, case: dict) -> dict:
    config = PlannerConfig(
        **{
            key: tuple(value) if isinstance(value, list) else value
            for key, value in case.get("config", {}).items()
        }
    )
    record = {k: v for k, v in case.items()}
    try:
        plan = BaselinePlanner(registry, config).plan(case["prompt"])
    except PlanningError as exc:
        record["error"] = str(exc)
        record["passed"] = "expected_error" in case and case["expected_error"] in str(
            exc
        )
        return record
    record["route"] = plan.route
    record["skills"] = [task.skill for task in plan.tasks]
    record["excluded_skills"] = list(plan.excluded_skills)
    passed = "expected_error" not in case
    passed = passed and record["skills"] == case["expected_skills"]
    if "expected_excluded" in case:
        passed = passed and record["excluded_skills"] == case["expected_excluded"]
    record["passed"] = passed
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    registry = load_default_registry()
    source = Path(__file__).resolve().parents[1] / "src/ml4gw_agent/planning.py"
    results = [run_case(registry, case) for case in CASES]
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "live_llm": False,
        "science_executed": False,
        "source_file": "src/ml4gw_agent/planning.py",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "cases": results,
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(
        text
        if not args.output
        else f"{report['passed']}/{report['total']} -> {args.output}"
    )
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
