from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..models import SkillSpec, TaskRecord, TaskSpec


@dataclass(frozen=True)
class ExecutionContext:
    run_dir: Path
    mode: Literal["mock", "real"]
    task: TaskSpec
    skill: SkillSpec
    parameters: dict[str, Any]
    records: dict[str, TaskRecord]
    prompt: str


@dataclass
class AdapterOutcome:
    outputs: dict[str, Any]
    artifacts: list[Path] = field(default_factory=list)
    command: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class SkillAdapter(ABC):
    def preflight(self, context: ExecutionContext) -> list[str]:
        """Return non-fatal warnings or raise an expected agent error."""
        return []

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        """Describe the intended call before execution for failure provenance."""
        return None, {}

    @abstractmethod
    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        """Run deterministic code for a single registered skill."""
        raise NotImplementedError


def artifact_directory(context: ExecutionContext) -> Path:
    path = context.run_dir / "artifacts" / context.task.id
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative_to_run(path: Path, run_dir: Path) -> str:
    resolved_path = path.resolve()
    resolved_run = run_dir.resolve()
    try:
        return resolved_path.relative_to(resolved_run).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact escaped the run directory: {path}") from exc
