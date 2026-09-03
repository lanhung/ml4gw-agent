"""Executor contracts: job handles, retries, result caching, command seam.

An executor decides *where* an already-validated task runs. It never chooses
*what* runs: the plan, the adapter, and the policy checks are settled before
anything is submitted. Every executor exposes the same small surface so the
runtime can record a job handle, poll it, cancel it, or resume it from a
checkpoint regardless of the backend.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import AdapterUnavailableError, ML4GWAgentError


class ExecutorError(ML4GWAgentError):
    """Raised when a job cannot be submitted, polled, or cancelled."""


class ExecutorKind(str, Enum):
    LOCAL = "local"
    HTCONDOR = "htcondor"
    KUBERNETES = "kubernetes"
    SNAKEMAKE = "snakemake"
    LAW = "law"
    TRITON = "triton"


class JobStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Single seam for every subprocess call an executor makes.

    Tests replace ``run`` with a fake; production code always passes an
    argument vector with ``shell=False`` so nothing is interpreted by a shell.
    """

    def run(self, argv: list[str], *, timeout: float = 120.0) -> CommandResult:
        if not argv or not all(isinstance(part, str) for part in argv):
            raise ExecutorError("command must be a non-empty list of strings")
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutorError(
                f"command {argv[0]} failed to run: {type(exc).__name__}: {exc}"
            ) from exc
        return CommandResult(
            argv=list(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    @staticmethod
    def which(name: str) -> str | None:
        return shutil.which(name)


@dataclass(frozen=True)
class RetryPolicy:
    """How many times a failed submission may be retried and how long to wait."""

    max_attempts: int = 1
    backoff_seconds: float = 30.0

    def delay_before(self, attempt: int) -> float:
        """Exponential backoff for ``attempt`` (1-based); 0 for the first try."""
        if attempt <= 1:
            return 0.0
        return float(self.backoff_seconds * 2 ** (attempt - 2))


def cache_key(
    skill_name: str,
    skill_version: str,
    parameters: dict[str, Any],
    adapter_name: str,
) -> str:
    """Stable key for a task result: same skill, version, inputs, adapter."""
    payload = json.dumps(
        {
            "skill": skill_name,
            "version": skill_version,
            "parameters": parameters,
            "adapter": adapter_name,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResultCache:
    """In-memory result cache keyed by ``cache_key``.

    Kept deliberately small: the cache lives for one runtime instance so a
    partitioned scan does not recompute identical segments, and nothing is
    persisted that could be mistaken for provenance.
    """

    def __init__(self) -> None:
        self._entries: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._entries.get(key)

    def put(self, key: str, value: Any) -> None:
        self._entries[key] = value

    def __len__(self) -> int:
        return len(self._entries)


@dataclass
class JobHandle:
    """What the runtime keeps for a submitted job."""

    id: str
    executor: ExecutorKind
    status: JobStatus = JobStatus.PENDING
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    checkpoint: Path | None = None
    result: Any = None
    error: str | None = None
    owner: Executor | None = field(default=None, repr=False)

    def poll(self) -> JobStatus:
        if self.owner is None:
            return self.status
        self.status = self.owner.poll(self)
        return self.status

    def cancel(self) -> JobStatus:
        if self.owner is None:
            self.status = JobStatus.CANCELLED
            return self.status
        self.status = self.owner.cancel(self)
        return self.status

    def resume(self) -> JobHandle:
        if self.owner is None:
            raise ExecutorError("job has no executor to resume with")
        return self.owner.resume(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "executor": self.executor.value,
            "status": self.status.value,
            "submitted_at": self.submitted_at.isoformat(),
            "checkpoint": str(self.checkpoint) if self.checkpoint else None,
            "error": self.error,
        }


class Executor(ABC):
    """Common surface of every execution backend."""

    kind: ExecutorKind

    @abstractmethod
    def probe(self) -> str:
        """``available`` or a short reason the executor cannot be used."""

    def require_available(self) -> None:
        status = self.probe()
        if status != "available":
            raise AdapterUnavailableError(
                f"executor {self.kind.value} is not available: {status}"
            )

    @abstractmethod
    def submit(
        self,
        job_id: str,
        work: Callable[[], Any],
        *,
        run_dir: Path,
        description: dict[str, Any] | None = None,
    ) -> JobHandle:
        """Submit ``work``.

        Batch executors ignore the callable and use ``description`` to build a
        submission that re-invokes the agent on a saved plan.
        """

    @abstractmethod
    def poll(self, handle: JobHandle) -> JobStatus: ...

    @abstractmethod
    def cancel(self, handle: JobHandle) -> JobStatus: ...

    def resume(self, handle: JobHandle) -> JobHandle:
        """Resume from a checkpoint; default is to re-poll the same job."""
        if handle.checkpoint is not None and not handle.checkpoint.exists():
            raise ExecutorError(f"checkpoint {handle.checkpoint} does not exist")
        handle.status = self.poll(handle)
        return handle
