from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import PolicyError
from .models import AdapterKind, PlanSpec, RiskLevel
from .registry import SkillRegistry


def _has_reference(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("${") and value.endswith("}")
    if isinstance(value, list):
        return any(_has_reference(item) for item in value)
    if isinstance(value, dict):
        return any(_has_reference(item) for item in value.values())
    return False


@dataclass(frozen=True)
class ExecutionPolicy:
    max_tasks: int = 30
    max_data_window_seconds: float = 4096
    max_posterior_samples: int = 100_000
    allow_high_risk: bool = False
    allow_unpinned_models: bool = False

    def validate(self, plan: PlanSpec, registry: SkillRegistry, mode: str) -> list[str]:
        blockers: list[str] = []
        warnings: list[str] = []

        if len(plan.tasks) > self.max_tasks:
            blockers.append(
                f"plan has {len(plan.tasks)} tasks; policy limit is {self.max_tasks}"
            )

        for task in plan.tasks:
            skill = registry.get(task.skill)
            params = task.parameters
            if mode == "real" and skill.adapter.kind == AdapterKind.PLANNED:
                blockers.append(f"{task.id}: {skill.name} has no real adapter in v0.1")
            if (
                mode == "real"
                and skill.risk == RiskLevel.HIGH
                and skill.requires_approval
                and not self.allow_high_risk
            ):
                blockers.append(
                    f"{task.id}: {skill.name} requires explicit high-risk approval"
                )

            if "window_seconds" in params and not _has_reference(
                params["window_seconds"]
            ):
                if float(params["window_seconds"]) > self.max_data_window_seconds:
                    blockers.append(
                        f"{task.id}: requested data window exceeds policy limit"
                    )
            for sample_key in ("samples", "samples_per_event"):
                if sample_key in params and not _has_reference(params[sample_key]):
                    if int(params[sample_key]) > self.max_posterior_samples:
                        blockers.append(f"{task.id}: {sample_key} exceeds policy limit")

            if mode == "real" and not self.allow_unpinned_models:
                if params.get("model_revision") == "UNPINNED":
                    blockers.append(
                        f"{task.id}: an immutable model revision is required in "
                        "real mode"
                    )
                if skill.adapter.kind == AdapterKind.BUOY_CLI:
                    for key in ("aframe_revision", "amplfi_revision"):
                        if not params.get(key):
                            blockers.append(
                                f"{task.id}: {key} is required in real mode"
                            )

            if mode == "mock" and skill.risk == RiskLevel.HIGH:
                warnings.append(
                    f"{task.id}: high-risk skill is simulated only; no scientific "
                    "data will be modified"
                )

        if blockers:
            joined = "\n- ".join(blockers)
            raise PolicyError(f"plan blocked by execution policy:\n- {joined}")
        return warnings
