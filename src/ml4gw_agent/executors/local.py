"""In-process executor: what the runtime has always done, behind the contract."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import ML4GWAgentError
from .base import Executor, ExecutorKind, JobHandle, JobStatus


class LocalExecutor(Executor):
    kind = ExecutorKind.LOCAL

    def probe(self) -> str:
        return "available"

    def submit(
        self,
        job_id: str,
        work: Callable[[], Any],
        *,
        run_dir: Path,
        description: dict[str, Any] | None = None,
    ) -> JobHandle:
        handle = JobHandle(id=job_id, executor=self.kind, owner=self)
        handle.checkpoint = run_dir / "run_manifest.json"
        handle.status = JobStatus.RUNNING
        try:
            handle.result = work()
        except ML4GWAgentError as exc:
            handle.status = JobStatus.FAILED
            handle.error = f"{type(exc).__name__}: {exc}"
            raise
        except KeyboardInterrupt:
            handle.status = JobStatus.CANCELLED
            handle.error = "cancelled by operator"
            raise
        handle.status = JobStatus.COMPLETED
        return handle

    def poll(self, handle: JobHandle) -> JobStatus:
        return handle.status

    def cancel(self, handle: JobHandle) -> JobStatus:
        # An in-process job that is still running can only be interrupted by
        # the operator; a finished one keeps its terminal state.
        if handle.status in {JobStatus.PENDING, JobStatus.SUBMITTED}:
            handle.status = JobStatus.CANCELLED
        return handle.status
