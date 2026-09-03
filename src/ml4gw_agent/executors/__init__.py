"""Phase 4: executor contracts, resource estimates, budget policy, partitioning."""

from .base import (
    CommandResult,
    CommandRunner,
    Executor,
    ExecutorError,
    ExecutorKind,
    JobHandle,
    JobStatus,
    ResultCache,
    RetryPolicy,
    cache_key,
)
from .budget import BudgetDecision, BudgetPolicy
from .estimate import EstimateConfig, ResourceEstimate, estimate_plan
from .htcondor import HTCondorExecutor
from .kubernetes import KubernetesExecutor
from .local import LocalExecutor
from .partition import Segment, merge_segment_outputs, partition_scan
from .registry import (
    ExecutorSelection,
    PlannedExecutor,
    build_executors,
    executor_availability,
    select_executor,
)

__all__ = [
    "BudgetDecision",
    "BudgetPolicy",
    "CommandResult",
    "CommandRunner",
    "EstimateConfig",
    "Executor",
    "ExecutorError",
    "ExecutorKind",
    "ExecutorSelection",
    "HTCondorExecutor",
    "JobHandle",
    "JobStatus",
    "KubernetesExecutor",
    "LocalExecutor",
    "PlannedExecutor",
    "ResourceEstimate",
    "ResultCache",
    "RetryPolicy",
    "Segment",
    "build_executors",
    "cache_key",
    "estimate_plan",
    "executor_availability",
    "merge_segment_outputs",
    "partition_scan",
    "select_executor",
]
