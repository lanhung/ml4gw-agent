from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from .errors import ML4GWAgentError
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


def _planner_from_args(args: argparse.Namespace) -> BaselinePlanner:
    registry = load_default_registry()
    config = PlannerConfig(
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
    manifest = AgentRuntime(registry, policy).run(
        plan, runs_dir=args.runs_dir, mode=args.mode
    )
    run_dir = Path(manifest.run_directory)
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


def _doctor(mode: str) -> int:
    registry = load_default_registry()
    rows = []
    vertical_ready = True
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
            {"mode": mode, "v0_buoy_ready": vertical_ready, "skills": rows},
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
    except (ML4GWAgentError, PydanticValidationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
