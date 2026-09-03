#!/usr/bin/env python3
"""Evaluate planners on the prompt benchmarks.

Reports, per planner: tool-selection accuracy (exact skill sequence match
against the benchmark), plan validity (validated by the same rules the
runtime applies), execution success in mock mode, recovery (whether one
bounded replan repairs an injected failure), cost (tokens when the client
reports them), latency, and reproducibility (identical plan hash on a
second planning pass).

    uv run python scripts/evaluate_planner.py                 # baseline + replay
    uv run python scripts/evaluate_planner.py --client anthropic --model claude-opus-5

The ``replay`` client answers with the deterministic baseline plan, which
exercises the whole LLM pipeline (retrieval, prompt, validation, repair,
fallback, memory) without credentials; its numbers describe the pipeline,
not a language model. The ``anthropic`` client needs ANTHROPIC_API_KEY (or an
``ant auth login`` profile) and the ``llm`` extra.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import yaml

from ml4gw_agent.errors import PlanningError
from ml4gw_agent.llm_planner import (
    AnthropicClient,
    ExperimentMemory,
    LLMPlanner,
    ReplayClient,
    baseline_responder,
    plan_hash,
)
from ml4gw_agent.models import RunStatus, TaskStatus
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.registry import load_default_registry
from ml4gw_agent.runtime import AgentRuntime

CONFIG = PlannerConfig(
    aframe_revision="a" * 40, amplfi_revision="b" * 40, gwak_revision="c" * 40
)


def load_cases(paths):
    cases = []
    for path in paths:
        cases.extend(yaml.safe_load(Path(path).read_text())["cases"])
    return cases


def evaluate(name, make_planner, cases, registry, execute):
    rows = []
    for case in cases:
        planner = make_planner()
        started = time.time()
        error = None
        plan = None
        try:
            plan = planner.plan(case["prompt"])
        except PlanningError as exc:
            error = str(exc)
        latency = time.time() - started
        row = {"id": case["id"], "tag": case.get("tag", "nominal"), "latency": latency}
        diagnostics = getattr(planner, "last_diagnostics", {})
        row["llm_attempts"] = len(diagnostics.get("attempts", []))
        row["fallback"] = bool(diagnostics.get("fallback"))
        if "expected_error" in case:
            row["selection_correct"] = (
                error is not None and case["expected_error"] in error
            )
            row["valid"] = row["selection_correct"]
        else:
            skills = [t.skill for t in plan.tasks] if plan else []
            row["selection_correct"] = skills == case["expected_skills"] and not any(
                f in skills for f in case.get("forbidden_skills", [])
            )
            row["valid"] = plan is not None
        if plan is not None:
            second = make_planner().plan(case["prompt"])
            row["reproducible"] = plan_hash(plan) == plan_hash(second)
            if execute:
                with tempfile.TemporaryDirectory() as tmp:
                    manifest = AgentRuntime(registry).run(
                        plan, runs_dir=Path(tmp), mode="mock"
                    )
                row["executed"] = manifest.status == RunStatus.COMPLETED
                row["tasks_completed"] = sum(
                    r.status == TaskStatus.COMPLETED for r in manifest.tasks.values()
                )
        usage = getattr(getattr(planner, "client", None), "last_usage", None) or {}
        row["tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        rows.append(row)
    summary = {
        "planner": name,
        "cases": len(rows),
        "tool_selection_accuracy": (
            sum(r["selection_correct"] for r in rows) / len(rows)
        ),
        "plan_validity": sum(r["valid"] for r in rows) / len(rows),
        "execution_success": (
            sum(r.get("executed", False) for r in rows)
            / max(1, sum("executed" in r for r in rows))
        ),
        "reproducibility": (
            sum(r.get("reproducible", False) for r in rows)
            / max(1, sum("reproducible" in r for r in rows))
        ),
        "fallback_rate": sum(r["fallback"] for r in rows) / len(rows),
        "mean_latency_seconds": sum(r["latency"] for r in rows) / len(rows),
        "total_tokens": sum(r["tokens"] for r in rows),
        "by_tag": {},
    }
    for tag in sorted({r["tag"] for r in rows}):
        subset = [r for r in rows if r["tag"] == tag]
        summary["by_tag"][tag] = {
            "cases": len(subset),
            "tool_selection_accuracy": sum(r["selection_correct"] for r in subset)
            / len(subset),
        }
    return summary, rows


def recovery_check(make_planner, registry):
    """Inject a failure (unknown skill in the first answer) and see if the
    bounded repair round recovers; only meaningful for LLM-style planners."""
    planner = make_planner()
    if not hasattr(planner, "client") or not isinstance(planner.client, ReplayClient):
        return None
    good = planner.client.responder
    state = {"first": True}

    def flaky(system, user, schema):
        if state["first"]:
            state["first"] = False
            return json.dumps(
                {
                    "goal": "bad",
                    "tasks": [
                        {
                            "id": "x",
                            "skill": "shell.run",
                            "parameters": {},
                            "depends_on": [],
                        }
                    ],
                    "warnings": [],
                }
            )
        return good(system, user, schema)

    planner.client.responder = flaky
    plan = planner.plan("Run Aframe detection on GW150914.")
    return {
        "recovered_after_repair": not planner.last_diagnostics.get("fallback")
        and len(planner.last_diagnostics["attempts"]) == 2,
        "plan_hash": plan_hash(plan),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--benchmark", action="append", default=None)
    parser.add_argument("--client", choices=["replay", "anthropic"], default="replay")
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1] / "benchmarks"
    paths = args.benchmark or [root / "v0_prompts.yaml", root / "v1_prompts.yaml"]
    registry = load_default_registry()
    cases = load_cases(paths)

    def baseline():
        return BaselinePlanner(registry, CONFIG)

    memory_path = Path(tempfile.mkdtemp()) / "memory.jsonl"

    def llm():
        if args.client == "anthropic":
            client = AnthropicClient(model=args.model)
        else:
            client = ReplayClient(baseline_responder(registry, CONFIG))
        return LLMPlanner(
            registry, client, CONFIG, mode="mock", memory=ExperimentMemory(memory_path)
        )

    report = {"benchmarks": [str(p) for p in paths], "planners": []}
    planners = (("baseline-deterministic", baseline), (f"llm-{args.client}", llm))
    for name, factory in planners:
        summary, rows = evaluate(name, factory, cases, registry, not args.no_execute)
        summary["recovery"] = recovery_check(factory, registry)
        summary["rows"] = rows
        report["planners"].append(summary)
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.write_text(text + "\n")
    for planner in report["planners"]:
        print(
            f"{planner['planner']:24s} cases={planner['cases']:3d} "
            f"selection={planner['tool_selection_accuracy']:.3f} "
            f"valid={planner['plan_validity']:.3f} "
            f"executed={planner['execution_success']:.3f} "
            f"reproducible={planner['reproducibility']:.3f} "
            f"fallback={planner['fallback_rate']:.3f} "
            f"latency={planner['mean_latency_seconds'] * 1000:.0f}ms "
            f"tokens={planner['total_tokens']} recovery={planner['recovery']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
