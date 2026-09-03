"""Budget policy applied to a resource estimate before anything is submitted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .estimate import ResourceEstimate


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    authorization_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "authorization_required": self.authorization_required,
        }


@dataclass(frozen=True)
class BudgetPolicy:
    """Conservative defaults: one event analysis is far below every limit."""

    max_cpu_hours: float = 24.0
    max_gpu_hours: float = 4.0
    max_transfer_gb: float = 20.0
    max_latency_seconds: float = 6 * 3600.0
    require_authorization_above_gpu_hours: float = 1.0
    authorized: bool = False

    def check(self, estimate: ResourceEstimate) -> BudgetDecision:
        reasons: list[str] = []
        if estimate.cpu_hours > self.max_cpu_hours:
            reasons.append(
                f"estimated {estimate.cpu_hours:.2f} CPU hours exceed the budget of "
                f"{self.max_cpu_hours:g}"
            )
        if estimate.gpu_hours > self.max_gpu_hours:
            reasons.append(
                f"estimated {estimate.gpu_hours:.2f} GPU hours exceed the budget of "
                f"{self.max_gpu_hours:g}"
            )
        if estimate.transfer_gb > self.max_transfer_gb:
            reasons.append(
                f"estimated {estimate.transfer_gb:.2f} GB of transfer exceed the "
                f"budget of {self.max_transfer_gb:g}"
            )
        if estimate.expected_latency_seconds > self.max_latency_seconds:
            reasons.append(
                f"expected latency {estimate.expected_latency_seconds:.0f} s exceeds "
                f"the budget of {self.max_latency_seconds:.0f} s"
            )
        needs_authorization = (
            estimate.gpu_hours > self.require_authorization_above_gpu_hours
        )
        if needs_authorization and not self.authorized:
            reasons.append(
                f"estimated {estimate.gpu_hours:.2f} GPU hours exceed "
                f"{self.require_authorization_above_gpu_hours:g}; explicit "
                "authorization is required before submission"
            )
        return BudgetDecision(
            allowed=not reasons,
            reasons=reasons,
            authorization_required=needs_authorization,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_cpu_hours": self.max_cpu_hours,
            "max_gpu_hours": self.max_gpu_hours,
            "max_transfer_gb": self.max_transfer_gb,
            "max_latency_seconds": self.max_latency_seconds,
            "require_authorization_above_gpu_hours": (
                self.require_authorization_above_gpu_hours
            ),
            "authorized": self.authorized,
        }
