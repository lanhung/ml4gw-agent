"""Whole-plan submission to a batch executor, single or segmented.

A batch executor (HTCondor, SSH, Kubernetes) does not run adapters one by
one on the submit host: it re-invokes the agent on the worker with
``run-plan`` on the validated, saved plan, so the worker executes exactly
the DAG that was approved here. This module owns that round trip: save the
plan, derive the resource request from the estimate, check the budget,
submit, poll, and collect the worker's manifest. Everything is written next
to the plan so a crashed submit host can resume from the job handle.

Long requests are segmented: when the data window exceeds the policy limit
or a segment length is given, the plan is cloned once per segment with the
fetch window replaced, the segments are submitted as independent jobs, and
their candidate lists are merged without duplicates or gaps
(:func:`submit_segmented`).
"""

from __future__ import annotations

import copy
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
from .partition import Segment, merge_segment_outputs, partition_scan

TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
DEFAULT_OVERLAP_SECONDS = 8.0


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


def _fetch_tasks(plan: PlanSpec):
    return [task for task in plan.tasks if task.skill == "data.fetch"]


def scan_interval(plan: PlanSpec) -> tuple[float, float] | None:
    """Absolute ``[start, end)`` of the plan's data window, when derivable.

    Only a request made by GPS time has a window that can be positioned
    without running ``data.resolve_event``; catalog and GraceDB names return
    ``None`` and cannot be segmented at submission time.
    """
    fetch = _fetch_tasks(plan)
    if not fetch:
        return None
    params = fetch[0].parameters
    event = str(params.get("event", ""))
    try:
        event_time = float(event)
    except ValueError:
        return None
    window = float(params.get("window_seconds", 128.0))
    fraction = float(params.get("event_offset_fraction", 0.75))
    start = event_time - fraction * window
    return start, start + window


def segment_plan(plan: PlanSpec, segment: Segment) -> PlanSpec:
    """Clone ``plan`` with every data window replaced by the segment's."""
    clone = copy.deepcopy(plan)
    window = float(segment.data_end - segment.data_start)
    for task in clone.tasks:
        if task.skill == "data.fetch":
            task.parameters["event"] = f"{segment.data_start:.6f}".rstrip("0").rstrip(
                "."
            )
            task.parameters["gps_time"] = segment.data_start
            task.parameters["window_seconds"] = window
            task.parameters["event_offset_fraction"] = 0.0
        elif task.skill == "data.inspect":
            task.parameters["min_duration_seconds"] = window
        elif task.skill in {"aframe.detect", "gwak.scan"}:
            # a segment has no single target time; keep every candidate
            task.parameters["target_time"] = None
        elif task.skill == "data.resolve_event":
            task.parameters["event"] = f"{segment.data_start:.6f}".rstrip("0").rstrip(
                "."
            )
    clone.warnings.append(
        f"segment {segment.index}: core [{segment.core_start}, {segment.core_end}), "
        f"data [{segment.data_start}, {segment.data_end})"
    )
    return PlanSpec.model_validate(clone.model_dump())


def _candidates(manifest: dict[str, Any] | None, task_id: str) -> list[dict[str, Any]]:
    if not manifest:
        return []
    record = manifest.get("tasks", {}).get(task_id) or {}
    outputs = record.get("outputs") or {}
    if task_id == "run_aframe":
        stat = outputs.get("detection_statistic")
        return [
            {"time": float(t), "statistic": float(stat) if stat is not None else 0.0}
            for t in outputs.get("candidate_times", [])
        ]
    if task_id == "run_gwak":
        return [
            {"time": float(s["time"]), "statistic": float(s.get("score", 0.0))}
            for s in outputs.get("top_segments", [])
        ]
    return []


@dataclass
class SegmentedSubmission:
    """One long request split into per-segment jobs and merged back."""

    submission_dir: Path
    executor: str
    segments: list[Segment]
    submissions: list[Submission]
    merged: dict[str, Any] = field(default_factory=dict)
    status: str = "submitted"
    error: str | None = None

    @property
    def job_id(self) -> str:
        return ",".join(s.job_id for s in self.submissions)

    @property
    def manifest(self) -> dict[str, Any]:
        """Manifest-like summary so callers can treat it like a Submission."""
        return {
            "status": self.status,
            "segments": [s.as_dict() for s in self.segments],
            "runs": [
                {
                    "segment": index,
                    "job_id": sub.job_id,
                    "status": sub.status,
                    "manifest_path": str(sub.manifest_path)
                    if sub.manifest_path
                    else None,
                    "run_status": sub.manifest.get("status") if sub.manifest else None,
                    "error": sub.error,
                }
                for index, sub in enumerate(self.submissions)
            ],
            "merged": self.merged,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "submission_dir": str(self.submission_dir),
            "executor": self.executor,
            "job_id": self.job_id,
            "status": self.status,
            "error": self.error,
            "n_segments": len(self.segments),
            "segments": [s.as_dict() for s in self.segments],
            "submissions": [s.as_dict() for s in self.submissions],
            "merged": self.merged,
        }

    def save(self) -> Path:
        path = self.submission_dir / "segments.json"
        path.write_text(json.dumps(self.as_dict(), indent=2, default=str) + "\n")
        return path


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
    segment_seconds: float | None = None,
    max_window_seconds: float | None = None,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
) -> Submission | SegmentedSubmission:
    interval = scan_interval(plan)
    if interval is not None:
        start, end = interval
        needs_split = segment_seconds is not None or (
            max_window_seconds is not None and end - start > max_window_seconds
        )
        if needs_split:
            length = float(segment_seconds or max_window_seconds)
            return submit_segmented(
                plan,
                executor,
                registry,
                runs_dir=runs_dir,
                mode=mode,
                budget=budget,
                poll_interval=poll_interval,
                wait_timeout=wait_timeout,
                sleep=sleep,
                segment_seconds=length,
                overlap_seconds=overlap_seconds,
            )
    elif segment_seconds is not None:
        raise ExecutorError(
            "segmentation needs a request made by GPS time; catalog and GraceDB "
            "names are resolved on the worker and cannot be split here"
        )
    return _submit_single(
        plan,
        executor,
        registry,
        runs_dir=Path(runs_dir),
        mode=mode,
        budget=budget,
        poll_interval=poll_interval,
        wait_timeout=wait_timeout,
        wait=wait,
        sleep=sleep,
    )


def _submit_single(
    plan: PlanSpec,
    executor: Executor,
    registry: SkillRegistry,
    *,
    runs_dir: Path,
    mode: str,
    budget: BudgetPolicy | None,
    poll_interval: float,
    wait_timeout: float,
    wait: bool,
    sleep,
) -> Submission:
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


def submit_segmented(
    plan: PlanSpec,
    executor: Executor,
    registry: SkillRegistry,
    *,
    runs_dir: Path,
    segment_seconds: float,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    mode: str = "real",
    budget: BudgetPolicy | None = None,
    poll_interval: float = 15.0,
    wait_timeout: float = 7200.0,
    sleep=time.sleep,
) -> SegmentedSubmission:
    """Split the plan's window into segments, submit each, wait, merge."""
    interval = scan_interval(plan)
    if interval is None:
        raise ExecutorError(
            "segmentation needs a request made by GPS time; catalog and GraceDB "
            "names are resolved on the worker and cannot be split here"
        )
    start, end = interval
    segments = partition_scan(start, end, segment_seconds, overlap_seconds)
    runs_dir = Path(runs_dir)
    submission_dir = runs_dir / f"submission_{plan.id}"
    submission_dir.mkdir(parents=True, exist_ok=True)
    (submission_dir / "plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    # Budget is checked once for the whole scan, not per segment, so a large
    # request cannot slip through as many small ones.
    total = estimate_plan(plan, registry, EstimateConfig())
    total.gpu_hours *= len(segments)
    total.cpu_hours *= len(segments)
    total.n_segments = len(segments)
    decision = (budget or BudgetPolicy()).check(total)
    if not decision.allowed:
        raise ExecutorError(
            "budget refused the segmented submission: " + "; ".join(decision.reasons)
        )

    submissions: list[Submission] = []
    handles: list[JobHandle] = []
    for segment in segments:
        seg_plan = segment_plan(plan, segment)
        seg_dir = submission_dir / f"segment_{segment.index:04d}"
        seg_plan = seg_plan.model_copy(update={"id": f"{plan.id}_s{segment.index:04d}"})
        sub = _submit_single(
            seg_plan,
            executor,
            registry,
            runs_dir=seg_dir,
            mode=mode,
            budget=BudgetPolicy(authorized=True, max_gpu_hours=float("inf")),
            poll_interval=poll_interval,
            wait_timeout=wait_timeout,
            wait=False,
            sleep=sleep,
        )
        submissions.append(sub)
        handles.append(JobHandle(id=sub.job_id, executor=executor.kind, owner=executor))
    segmented = SegmentedSubmission(
        submission_dir=submission_dir,
        executor=executor.kind.value,
        segments=segments,
        submissions=submissions,
    )
    segmented.merged = {"budget": asdict(decision)}
    segmented.save()

    for sub, handle in zip(submissions, handles, strict=True):
        wait_for(sub, executor, handle, poll_interval, wait_timeout, sleep)
        segmented.save()

    outputs = {
        "run_aframe": {},
        "run_gwak": {},
    }
    for index, sub in enumerate(submissions):
        for task_id in outputs:
            if sub.manifest and task_id in sub.manifest.get("tasks", {}):
                record = sub.manifest["tasks"][task_id]
                if record.get("status") == "completed":
                    outputs[task_id][index] = {
                        "candidates": _candidates(sub.manifest, task_id)
                    }
    merged: dict[str, Any] = {"budget": asdict(decision)}
    for task_id, per_segment in outputs.items():
        if per_segment or any(
            sub.manifest and task_id in sub.manifest.get("tasks", {})
            for sub in submissions
        ):
            merged[task_id] = merge_segment_outputs(segments, per_segment)
    failed = [
        index
        for index, sub in enumerate(submissions)
        if sub.status != "completed"
        or (sub.manifest or {}).get("status") != "completed"
    ]
    merged["failed_segments"] = failed
    segmented.merged = merged
    segmented.status = "completed" if not failed else "partial"
    if failed:
        segmented.error = f"{len(failed)} of {len(segments)} segments did not complete"
    segmented.save()
    return segmented


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
    if handle.error and not submission.error:
        submission.error = handle.error
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
    checkpoint = (
        Path(submission_dir)
        / "jobs"
        / f"plan-{data['plan_file'].split('/')[-2].removeprefix('submission_')}"
        / "handle.json"
    )
    if checkpoint.exists():
        handle.checkpoint = checkpoint
    handle = executor.resume(handle)
    return wait_for(
        submission,
        executor,
        handle,
        kwargs.get("poll_interval", 15.0),
        kwargs.get("wait_timeout", 7200.0),
        kwargs.get("sleep", time.sleep),
    )
