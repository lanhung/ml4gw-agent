"""Whole-plan submission to a batch executor.

A batch executor (HTCondor, Kubernetes) does not run adapters one by one on
the submit host: it re-invokes the agent on the worker with ``run-plan`` on
the validated, saved plan, so the worker executes exactly the DAG that was
approved here. This module owns that round trip: save the plan, derive the
resource request from the estimate, check the budget, submit, poll, and
collect the worker's manifest. Everything is written next to the plan so a
crashed submit host can resume from the job handle.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..models import PlanSpec
from ..registry import SkillRegistry
from .base import Executor, ExecutorError, JobHandle, JobStatus
from .budget import BudgetPolicy
from .estimate import EstimateConfig, estimate_plan

TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class Submission:
    submission_dir: Path
    plan_file: Path
    executor: str
    job_id: str
    description: dict[str, Any]
    status: str = "submitted"
    polls: list[dict[str, Any]] = field(default_factory=list)
    manifest_path: Path | None = None
    manifest: dict[str, Any] | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["submission_dir"] = str(self.submission_dir)
        data["plan_file"] = str(self.plan_file)
        data["manifest_path"] = str(self.manifest_path) if self.manifest_path else None
        data.pop("manifest", None)
        return data

    def save(self) -> Path:
        path = self.submission_dir / "submission.json"
        path.write_text(json.dumps(self.as_dict(), indent=2, default=str) + "\n")
        return path


def describe_request(plan: PlanSpec, registry: SkillRegistry) -> dict[str, Any]:
    """Resource request for the whole plan from the estimate."""
    estimate = estimate_plan(plan, registry, EstimateConfig())
    cpus = max([int(t.get("cpu_cores", 1)) for t in estimate.per_task] or [1])
    return {
        "cpus": cpus,
        "memory_gb": max(2.0, float(estimate.memory_gb)),
        "gpus": 1 if estimate.gpu_hours > 0 else 0,
        "estimate": estimate.as_dict(),
    }


def submit_plan(
    plan: PlanSpec,
    executor: Executor,
    registry: SkillRegistry,
    *,
    runs_dir: Path,
    mode: str = "real",
    budget: BudgetPolicy | None = None,
    poll_interval: float = 15.0,
    wait_timeout: float = 7200.0,
    wait: bool = True,
    sleep=time.sleep,
) -> Submission:
    runs_dir = Path(runs_dir)
    submission_dir = runs_dir / f"submission_{plan.id}"
    worker_dir = submission_dir / "worker"
    submission_dir.mkdir(parents=True, exist_ok=True)
    plan_file = submission_dir / "plan.json"
    plan_file.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")

    request = describe_request(plan, registry)
    estimate = estimate_plan(plan, registry, EstimateConfig())
    decision = (budget or BudgetPolicy()).check(estimate)
    if not decision.allowed:
        raise ExecutorError(
            "budget refused the submission: " + "; ".join(decision.reasons)
        )
    description = {
        "plan_file": str(plan_file),
        "mode": mode,
        "runs_dir": str(worker_dir),
        "cpus": request["cpus"],
        "memory_gb": request["memory_gb"],
        "gpus": request["gpus"],
    }
    handle = executor.submit(
        f"plan-{plan.id}", lambda: None, run_dir=submission_dir, description=description
    )
    submission = Submission(
        submission_dir=submission_dir,
        plan_file=plan_file,
        executor=executor.kind.value,
        job_id=handle.id,
        description={
            **description,
            "budget": asdict(decision),
            "estimate": request["estimate"],
        },
    )
    submission.save()
    if not wait:
        return submission
    return wait_for(submission, executor, handle, poll_interval, wait_timeout, sleep)


def wait_for(
    submission: Submission,
    executor: Executor,
    handle: JobHandle,
    poll_interval: float,
    wait_timeout: float,
    sleep=time.sleep,
) -> Submission:
    started = time.time()
    status = JobStatus.SUBMITTED
    while True:
        status = executor.poll(handle)
        submission.polls.append({"at": time.time(), "status": status.value})
        submission.status = status.value
        submission.save()
        if status in TERMINAL:
            break
        if time.time() - started > wait_timeout:
            submission.error = (
                f"gave up waiting after {wait_timeout:g} s "
                f"(job {handle.id} still {status.value})"
            )
            submission.status = "timeout"
            submission.save()
            return submission
        sleep(poll_interval)
    manifests = sorted(
        Path(submission.description["runs_dir"]).glob("run_*/run_manifest.json")
    )
    if manifests:
        submission.manifest_path = manifests[-1]
        submission.manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
        inner = submission.manifest.get("status")
        if status == JobStatus.COMPLETED and inner != "completed":
            submission.status = f"job completed, run {inner}"
    elif status == JobStatus.COMPLETED:
        submission.error = "job finished but no run manifest was written on the worker"
        submission.status = "failed"
    submission.save()
    return submission


def resume_submission(submission_dir: Path, executor: Executor, **kwargs) -> Submission:
    """Pick up a saved submission (after a submit-host restart) and wait again."""
    data = json.loads((Path(submission_dir) / "submission.json").read_text())
    submission = Submission(
        submission_dir=Path(submission_dir),
        plan_file=Path(data["plan_file"]),
        executor=data["executor"],
        job_id=data["job_id"],
        description=data["description"],
        status=data.get("status", "submitted"),
        polls=data.get("polls", []),
    )
    handle = JobHandle(id=submission.job_id, executor=executor.kind, owner=executor)
    handle = executor.resume(handle)
    return wait_for(
        submission,
        executor,
        handle,
        kwargs.get("poll_interval", 15.0),
        kwargs.get("wait_timeout", 7200.0),
        kwargs.get("sleep", time.sleep),
    )
