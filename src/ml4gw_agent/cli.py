from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from .adapters import PYTHON_ADAPTERS
from .errors import ML4GWAgentError
from .executors import (
    BudgetPolicy,
    EstimateConfig,
    ExecutorKind,
    build_executors,
    estimate_plan,
    executor_availability,
    select_executor,
)
from .models import AdapterKind, PlanSpec, RunStatus
from .planning import BaselinePlanner, PlannerConfig
from .policy import ExecutionPolicy
from .registry import load_default_registry
from .runtime import AgentRuntime


def _add_planner_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ifos", nargs="+", default=["H1", "L1"])
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--samples-per-event", type=int, default=20_000)
    parser.add_argument("--nside", type=int, default=64)
    parser.add_argument("--min-samples-per-pix", type=int, default=5)
    parser.add_argument("--no-distance", action="store_false", dest="use_distance")
    parser.add_argument("--use-true-tc-for-amplfi", action="store_true")
    parser.add_argument("--buoy-runner", choices=["cli", "python"], default="cli")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--aframe-revision")
    parser.add_argument("--amplfi-revision")
    parser.add_argument("--gwak-revision")
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=128.0,
        help="Strain window for decomposed plans (Buoy uses 2 x psd_length = 128)",
    )
    parser.add_argument("--sample-rate", type=int, default=2048)
    parser.add_argument(
        "--planner",
        choices=["baseline", "llm"],
        default="baseline",
        help="llm: Claude proposes the plan, validated by the same rules (needs the "
        "llm extra and ANTHROPIC_API_KEY); baseline: deterministic router",
    )
    parser.add_argument("--llm-model", default="claude-opus-5")
    parser.add_argument(
        "--memory",
        type=Path,
        default=None,
        help="JSONL experiment memory read for prior runs and appended after runs",
    )
    parser.add_argument(
        "--data-source",
        choices=["gwosc", "ldg", "nds2"],
        default="gwosc",
        help="gwosc: public strain; ldg: authenticated frames (needs IGWN credentials)",
    )
    parser.add_argument(
        "--aframe-threshold",
        type=float,
        default=None,
        help=(
            "Explicit integrated-output threshold for candidate_found; by default "
            "the calibrated threshold for --aframe-revision at --aframe-far is used"
        ),
    )
    parser.add_argument(
        "--aframe-far",
        type=float,
        default=1.0,
        dest="aframe_far_per_year",
        help="Target false-alarm rate per year for the calibrated threshold",
    )
    parser.add_argument(
        "--gwak-threshold",
        type=float,
        default=None,
        help="Explicit GWAK score cut; by default the calibrated one at --gwak-far",
    )
    parser.add_argument(
        "--gwak-far",
        type=float,
        default=365.25,
        dest="gwak_far_per_year",
        help="Target false-alarm rate per year for the calibrated GWAK threshold",
    )
    parser.add_argument(
        "--candidate-window",
        type=float,
        default=2.0,
        dest="candidate_window_seconds",
        help="Seconds around the requested time within which a peak counts",
    )


def _config_from_args(args: argparse.Namespace) -> PlannerConfig:
    return PlannerConfig(
        ifos=tuple(args.ifos),
        device=args.device,
        samples_per_event=args.samples_per_event,
        nside=args.nside,
        min_samples_per_pix=args.min_samples_per_pix,
        use_distance=args.use_distance,
        use_true_tc_for_amplfi=args.use_true_tc_for_amplfi,
        buoy_runner=args.buoy_runner,
        aframe_revision=args.aframe_revision,
        amplfi_revision=args.amplfi_revision,
        gwak_revision=args.gwak_revision,
        seed=args.seed,
        window_seconds=args.window_seconds,
        sample_rate=args.sample_rate,
        aframe_threshold=args.aframe_threshold,
        aframe_far_per_year=args.aframe_far_per_year,
        gwak_threshold=args.gwak_threshold,
        gwak_far_per_year=args.gwak_far_per_year,
        candidate_window_seconds=args.candidate_window_seconds,
        data_source=args.data_source,
    )


def _planner_from_args(args: argparse.Namespace):
    registry = load_default_registry()
    config = _config_from_args(args)
    if getattr(args, "planner", "baseline") == "llm":
        from .llm_planner import AnthropicClient, ExperimentMemory, LLMPlanner

        memory = ExperimentMemory(args.memory) if args.memory else None
        return LLMPlanner(
            registry,
            AnthropicClient(model=args.llm_model),
            config,
            memory=memory,
            mode=getattr(args, "mode", "real"),
        )
    return BaselinePlanner(registry, config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ml4gw-agent",
        description="Safe, provenance-aware orchestration for ML4GW tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    skills = subparsers.add_parser("skills", help="List registered capabilities")
    skills.add_argument("--json", action="store_true", dest="as_json")

    plan = subparsers.add_parser("plan", help="Create a validated DAG from a prompt")
    plan.add_argument("prompt")
    plan.add_argument("--output", type=Path)
    _add_planner_arguments(plan)

    run = subparsers.add_parser("run", help="Plan and execute a prompt")
    run.add_argument("prompt")
    run.add_argument("--mode", choices=["mock", "real"], default="mock")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.add_argument("--allow-unpinned-models", action="store_true")
    run.add_argument("--approve-high-risk", action="store_true")
    _add_planner_arguments(run)

    run_plan = subparsers.add_parser("run-plan", help="Execute a saved plan JSON")
    run_plan.add_argument("plan_file", type=Path)
    run_plan.add_argument("--mode", choices=["mock", "real"], default="mock")
    run_plan.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run_plan.add_argument("--allow-unpinned-models", action="store_true")
    run_plan.add_argument("--approve-high-risk", action="store_true")

    # Phase 4: execution placement and budget (run, run-plan) and the
    # pre-submission estimate.
    for executing in (run, run_plan):
        executing.add_argument(
            "--poll-interval",
            type=float,
            default=15.0,
            help="seconds between batch-executor status polls",
        )
        executing.add_argument(
            "--wait-timeout",
            type=float,
            default=7200.0,
            help="seconds to wait for a batch job before giving up",
        )
        executing.add_argument(
            "--executor",
            choices=["local", "htcondor", "ssh", "kubernetes"],
            default="local",
            help="Where tasks execute; batch executors need their CLI on PATH",
        )
        executing.add_argument(
            "--segment-seconds",
            type=float,
            default=None,
            help="Split a long data window into segments of this length (batch only)",
        )
        executing.add_argument(
            "--max-gpu-hours",
            type=float,
            default=BudgetPolicy().max_gpu_hours,
            help="Refuse plans whose GPU estimate exceeds this before submission",
        )
        executing.add_argument(
            "--authorize-budget",
            action="store_true",
            help="Authorize GPU estimates above the authorization threshold",
        )
    estimate = subparsers.add_parser(
        "estimate", help="Estimate a prompt's resources and budget decision"
    )
    estimate.add_argument("prompt")
    estimate.add_argument("--no-cache", action="store_false", dest="data_cached")
    estimate.add_argument("--no-gpu", action="store_false", dest="gpu_available")
    estimate.add_argument("--max-gpu-hours", type=float, default=None)
    _add_planner_arguments(estimate)

    validate = subparsers.add_parser(
        "validate-plan", help="Validate a saved plan and registered skill names"
    )
    validate.add_argument("plan_file", type=Path)

    doctor = subparsers.add_parser(
        "doctor", help="Inspect adapter availability without executing science"
    )
    doctor.add_argument("--mode", choices=["mock", "real"], default="real")
    return parser


def _load_plan(path: Path) -> PlanSpec:
    return PlanSpec.model_validate_json(path.read_text(encoding="utf-8"))


def _run_plan(plan: PlanSpec, args: argparse.Namespace) -> int:
    registry = load_default_registry()
    policy = ExecutionPolicy(
        allow_high_risk=args.approve_high_risk,
        allow_unpinned_models=args.allow_unpinned_models,
    )
    executors = build_executors()
    executor = executors[
        select_executor(
            estimate_plan(plan, registry),
            executors,
            preference=getattr(args, "executor", "local"),
        ).kind
    ]
    budget = BudgetPolicy(
        max_gpu_hours=getattr(args, "max_gpu_hours", BudgetPolicy().max_gpu_hours),
        authorized=getattr(args, "authorize_budget", False),
    )
    if executor.kind != ExecutorKind.LOCAL:
        # Batch executors run the saved plan on a worker; submit and wait here.
        from .executors import submit_plan

        submission = submit_plan(
            plan,
            executor,
            registry,
            runs_dir=args.runs_dir,
            mode=args.mode,
            budget=budget,
            poll_interval=getattr(args, "poll_interval", 15.0),
            wait_timeout=getattr(args, "wait_timeout", 7200.0),
            segment_seconds=getattr(args, "segment_seconds", None),
            max_window_seconds=policy.max_data_window_seconds,
        )
        summary = submission.as_dict()
        summary["run_status"] = (
            submission.manifest.get("status") if submission.manifest else None
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0 if summary["run_status"] == "completed" else 2
    # Third-party libraries (bilby, astropy) print to stdout during real runs;
    # keep stdout for the JSON summary only.
    with contextlib.redirect_stdout(sys.stderr):
        manifest = AgentRuntime(registry, policy, executor=executor, budget=budget).run(
            plan, runs_dir=args.runs_dir, mode=args.mode
        )
    run_dir = Path(manifest.run_directory)
    if getattr(args, "memory", None):
        from .llm_planner import ExperimentMemory

        ExperimentMemory(args.memory).record(plan, manifest, _config_from_args(args))
    summary = {
        "run_id": manifest.run_id,
        "status": manifest.status.value,
        "run_directory": manifest.run_directory,
        "manifest": str(run_dir / "run_manifest.json"),
        "report": str(run_dir / "report.md")
        if (run_dir / "report.md").exists()
        else None,
        "warnings": manifest.warnings,
    }
    print(json.dumps(summary, indent=2))
    return 0 if manifest.status == RunStatus.COMPLETED else 2


PHASE1B_SKILLS = {"data.fetch", "data.inspect", "aframe.detect", "amplfi.pe"}


def _doctor(mode: str) -> int:
    registry = load_default_registry()
    rows = []
    vertical_ready = True
    phase1b_ready = True
    for skill in registry.all():
        if mode == "mock":
            availability = (
                "builtin" if skill.adapter.kind == AdapterKind.BUILTIN else "mock"
            )
        elif skill.adapter.kind == AdapterKind.BUILTIN:
            availability = "available"
        elif skill.adapter.kind == AdapterKind.BUOY_CLI:
            executable = shutil.which(skill.adapter.entrypoint)
            if executable is None:
                availability = "missing"
            else:
                try:
                    probe = subprocess.run(
                        [executable, "--help"],
                        capture_output=True,
                        text=True,
                        shell=False,
                        timeout=60,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    availability = f"broken: {type(exc).__name__}"
                else:
                    availability = (
                        "available"
                        if probe.returncode == 0
                        else f"broken: exit {probe.returncode}"
                    )
            vertical_ready = vertical_ready and availability == "available"
        elif skill.adapter.kind == AdapterKind.PYTHON:
            adapter_class = PYTHON_ADAPTERS.get(skill.adapter.entrypoint)
            if adapter_class is None:
                availability = "broken: unregistered entrypoint"
            else:
                availability = adapter_class().probe()
            if skill.name in PHASE1B_SKILLS:
                phase1b_ready = phase1b_ready and availability == "available"
        else:
            availability = "planned"
        rows.append(
            {
                "skill": skill.name,
                "adapter": skill.adapter.kind.value,
                "availability": availability,
            }
        )
    print(
        json.dumps(
            {
                "mode": mode,
                "v0_buoy_ready": vertical_ready,
                "phase1b_decomposed_ready": phase1b_ready,
                "skills": rows,
            },
            indent=2,
        )
    )
    return 0 if mode == "mock" or vertical_ready else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "skills":
            registry = load_default_registry()
            payload = [
                {
                    "name": skill.name,
                    "version": skill.version,
                    "status": skill.status.value,
                    "adapter": skill.adapter.kind.value,
                    "risk": skill.risk.value,
                }
                for skill in registry.all()
            ]
            if args.as_json:
                print(json.dumps(payload, indent=2))
            else:
                print("SKILL\tSTATUS\tADAPTER\tRISK")
                for item in payload:
                    print(
                        f"{item['name']}\t{item['status']}\t"
                        f"{item['adapter']}\t{item['risk']}"
                    )
            return 0

        if args.command == "plan":
            plan = _planner_from_args(args).plan(args.prompt)
            payload = plan.model_dump_json(indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload + "\n", encoding="utf-8")
                print(args.output)
            else:
                print(payload)
            return 0

        if args.command == "run":
            plan = _planner_from_args(args).plan(args.prompt)
            return _run_plan(plan, args)

        if args.command == "run-plan":
            return _run_plan(_load_plan(args.plan_file), args)

        if args.command == "validate-plan":
            plan = _load_plan(args.plan_file)
            registry = load_default_registry()
            registry.validate_plan_skills(plan)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "plan_id": plan.id,
                        "tasks": [task.id for task in plan.topological_order()],
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "doctor":
            return _doctor(args.mode)

        if args.command == "estimate":
            plan = _planner_from_args(args).plan(args.prompt)
            registry = load_default_registry()
            estimate = estimate_plan(
                plan,
                registry,
                EstimateConfig(
                    data_cached=args.data_cached, gpu_available=args.gpu_available
                ),
            )
            budget = (
                BudgetPolicy(max_gpu_hours=args.max_gpu_hours)
                if args.max_gpu_hours is not None
                else BudgetPolicy()
            )
            executors = build_executors()
            selection = select_executor(estimate, executors)
            print(
                json.dumps(
                    {
                        "plan_id": plan.id,
                        "tasks": [task.id for task in plan.topological_order()],
                        "estimate": estimate.as_dict(),
                        "budget": budget.as_dict(),
                        "decision": budget.check(estimate).as_dict(),
                        "executors": executor_availability(executors),
                        "selection": selection.as_dict(),
                    },
                    indent=2,
                )
            )
            return 0 if budget.check(estimate).allowed else 3
    except (ML4GWAgentError, PydanticValidationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
