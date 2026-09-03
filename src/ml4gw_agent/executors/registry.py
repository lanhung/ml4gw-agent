"""Executor registry and the selection rule."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import CommandRunner, Executor, ExecutorKind, JobHandle, JobStatus
from .estimate import ResourceEstimate
from .htcondor import HTCondorExecutor
from .kubernetes import KubernetesExecutor
from .local import LocalExecutor
from .ssh import SSHExecutor

KUBERNETES_DEFERRED = "deferred (no cluster available; the ssh executor stands in)"

PLANNED_REASONS = {
    ExecutorKind.SNAKEMAKE: (
        "planned: GWAK's Snakemake workflow has no reviewed inference target "
        "(docs/UPSTREAM_REVIEW.md)"
    ),
    ExecutorKind.LAW: (
        "planned: mldatafind Law tasks are replaced by data.fetch source=ldg; "
        "no Law executor is wired"
    ),
    ExecutorKind.TRITON: (
        "planned: Triton/Hermes serving needs exported models at pinned "
        "revisions; none are published"
    ),
}


class PlannedExecutor(Executor):
    """Placeholder for backends the roadmap names but nothing can drive yet."""

    def __init__(self, kind: ExecutorKind):
        self.kind = kind

    def probe(self) -> str:
        return PLANNED_REASONS[self.kind]

    def submit(
        self,
        job_id: str,
        work: Callable[[], Any],
        *,
        run_dir: Path,
        description: dict[str, Any] | None = None,
    ) -> JobHandle:
        self.require_available()
        raise AssertionError("unreachable")  # pragma: no cover

    def poll(self, handle: JobHandle) -> JobStatus:  # pragma: no cover
        return handle.status

    def cancel(self, handle: JobHandle) -> JobStatus:  # pragma: no cover
        return handle.status


def build_executors(
    runner: CommandRunner | None = None, *, image: str | None = None
) -> dict[ExecutorKind, Executor]:
    runner = runner or CommandRunner()
    executors: dict[ExecutorKind, Executor] = {
        ExecutorKind.LOCAL: LocalExecutor(),
        ExecutorKind.HTCONDOR: HTCondorExecutor(runner),
        ExecutorKind.KUBERNETES: KubernetesExecutor(runner, image=image),
        ExecutorKind.SSH: SSHExecutor(),
    }
    for kind in (ExecutorKind.SNAKEMAKE, ExecutorKind.LAW, ExecutorKind.TRITON):
        executors[kind] = PlannedExecutor(kind)
    return executors


def executor_availability(
    executors: dict[ExecutorKind, Executor],
) -> dict[str, str]:
    rows = {kind.value: executor.probe() for kind, executor in executors.items()}
    if "kubernetes" in rows and rows["kubernetes"] != "available":
        rows["kubernetes"] = f"{KUBERNETES_DEFERRED}; {rows['kubernetes']}"
    return rows


@dataclass(frozen=True)
class ExecutorSelection:
    kind: ExecutorKind
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"executor": self.kind.value, "reason": self.reason}


LOCAL_LATENCY_LIMIT_SECONDS = 2 * 3600.0


def select_executor(
    estimate: ResourceEstimate,
    available: dict[ExecutorKind, Executor],
    preference: ExecutorKind | str | None = None,
) -> ExecutorSelection:
    """Local for short single-node work; a batch backend for partitioned scans.

    An explicit preference wins when that executor is available; otherwise
    the rule is recorded together with the reason so the manifest explains
    why a job landed where it did.
    """
    if preference is not None:
        kind = ExecutorKind(preference)
        executor = available.get(kind)
        if executor is None or executor.probe() != "available":
            reason = executor.probe() if executor is not None else "not registered"
            raise ValueError(f"requested executor {kind.value} is unusable: {reason}")
        return ExecutorSelection(kind, "requested explicitly")

    batch_kinds = [
        kind
        for kind in (ExecutorKind.HTCONDOR, ExecutorKind.SSH, ExecutorKind.KUBERNETES)
        if kind in available and available[kind].probe() == "available"
    ]
    needs_batch = (
        estimate.n_segments > 1
        or estimate.expected_latency_seconds > LOCAL_LATENCY_LIMIT_SECONDS
    )
    if needs_batch and batch_kinds:
        return ExecutorSelection(
            batch_kinds[0],
            f"{estimate.n_segments} segments / {estimate.expected_latency_seconds:.0f}"
            " s expected: partitioned work goes to the batch scheduler",
        )
    if needs_batch:
        return ExecutorSelection(
            ExecutorKind.LOCAL,
            "partitioned work but no batch scheduler is available; running "
            "segments sequentially on this node",
        )
    return ExecutorSelection(
        ExecutorKind.LOCAL,
        f"single segment, {estimate.expected_latency_seconds:.0f} s expected: "
        "runs on this node",
    )
