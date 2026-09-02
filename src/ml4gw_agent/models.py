from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillStatus(str, Enum):
    PLANNED = "planned"
    EXPERIMENTAL = "experimental"
    STABLE = "stable"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AdapterKind(str, Enum):
    BUILTIN = "builtin"
    BUOY_CLI = "buoy_cli"
    PLANNED = "planned"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class AdapterSpec(StrictModel):
    kind: AdapterKind
    entrypoint: str = Field(min_length=1)
    timeout_seconds: int = Field(default=3600, ge=1, le=7 * 24 * 3600)


class ResourceSpec(StrictModel):
    cpu_cores: int = Field(default=1, ge=1)
    memory_gb: float = Field(default=1.0, gt=0)
    gpu: Literal["none", "preferred", "required"] = "none"
    estimated_runtime: str = "unknown"


class PreconditionSpec(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    machine_check: str | None = None
    required: bool = True


class ValidationSpec(StrictModel):
    kind: Literal["artifact_exists", "artifact_nonempty", "output_field"]
    target: str = Field(min_length=1)
    required: bool = True


class SkillSpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: SkillStatus
    risk: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    adapter: AdapterSpec
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    preconditions: list[PreconditionSpec] = Field(default_factory=list)
    validations: list[ValidationSpec] = Field(default_factory=list)
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    tags: list[str] = Field(default_factory=list)
    source_repository: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        pattern = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
        if not re.fullmatch(pattern, value):
            raise ValueError("skill name must be a dotted lowercase identifier")
        return value


class ConditionSpec(StrictModel):
    reference: str = Field(
        description="Reference such as ${task_id.outputs.candidate_found}"
    )
    operator: Literal[
        "exists", "equals", "not_equals", "gt", "gte", "lt", "lte", "truthy"
    ]
    value: Any = None


class TaskSpec(StrictModel):
    id: str
    skill: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    when: ConditionSpec | None = None
    max_retries: int = Field(default=0, ge=0, le=3)
    allow_failed_dependencies: bool = False

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not re.fullmatch(r"^[a-z][a-z0-9_]*$", value):
            raise ValueError("task id must be a lowercase identifier")
        return value


class PlanSpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(default_factory=lambda: new_identifier("plan"))
    prompt: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    tasks: list[TaskSpec] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    planner: str = "baseline-deterministic-v0.1"
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> PlanSpec:
        task_ids = [task.id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task ids must be unique")

        known = set(task_ids)
        for task in self.tasks:
            missing = set(task.depends_on) - known
            if missing:
                raise ValueError(
                    f"task {task.id} has unknown dependencies: {sorted(missing)}"
                )
            if task.id in task.depends_on:
                raise ValueError(f"task {task.id} cannot depend on itself")

        self.topological_order()
        return self

    def topological_order(self) -> list[TaskSpec]:
        indexed = {task.id: task for task in self.tasks}
        indegree = {task.id: len(task.depends_on) for task in self.tasks}
        children: dict[str, list[str]] = {task.id: [] for task in self.tasks}
        for task in self.tasks:
            for dependency in task.depends_on:
                children[dependency].append(task.id)

        ready = [task.id for task in self.tasks if indegree[task.id] == 0]
        ordered: list[TaskSpec] = []
        while ready:
            task_id = ready.pop(0)
            ordered.append(indexed[task_id])
            for child in children[task_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)

        if len(ordered) != len(self.tasks):
            raise ValueError("plan contains a dependency cycle")
        return ordered


class ArtifactRecord(StrictModel):
    relative_path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    media_type: str = "application/octet-stream"


class ValidationRecord(StrictModel):
    check: str
    passed: bool
    message: str


class TaskRecord(StrictModel):
    task_id: str
    skill: str
    status: TaskStatus = TaskStatus.PENDING
    parameters: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    validations: list[ValidationRecord] = Field(default_factory=list)
    command: list[str] | None = None
    adapter_metadata: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None


class RunManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(default_factory=lambda: new_identifier("run"))
    mode: Literal["mock", "real"]
    status: RunStatus = RunStatus.PENDING
    plan: PlanSpec
    tasks: dict[str, TaskRecord]
    run_directory: str
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=dict)
