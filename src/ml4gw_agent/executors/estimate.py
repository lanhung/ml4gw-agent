"""Bounded resource estimates for a plan, computed before submission.

Numbers come from two places: the ``resources`` block of every skill
contract (cores, memory, GPU need) and a per-skill runtime table measured on
the 2026-09-03 acceptance runs (NVIDIA RTX 5000 Ada, cached GWOSC strain).
Uncached strain access is modelled from the same node's measured 70 kB/s to
``gwosc.org`` and the 130 MB size of one 4096 s, 4 kHz frame file per
detector. The estimate is deliberately coarse and conservative: it exists so
the budget policy can refuse or require authorization *before* anything runs,
not to predict wall time precisely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import PlanSpec
from ..registry import SkillRegistry
from .partition import partition_scan

WINDOW_SECONDS = 128.0
FRAME_FILE_BYTES = 130_000_000  # one 4096 s GWOSC 4 kHz file per detector
CPU_SLOWDOWN = 20.0  # Buoy documents ~15 min per event on CPU vs ~40 s on GPU
FETCHING_SKILLS = {"data.fetch", "buoy.analyze"}


@dataclass(frozen=True)
class MeasuredRuntime:
    """Seconds per unit of work on the reference node."""

    seconds: float
    per_window: bool = False  # scales with window_seconds / 128
    per_detector: bool = False
    uses_gpu: bool = False
    note: str = ""


# Measured on the acceptance runs (docs/PHASE1B_*_2026-09-03.md).
RUNTIME_TABLE: dict[str, MeasuredRuntime] = {
    "data.resolve_event": MeasuredRuntime(1.0, note="catalog lookup"),
    "data.fetch": MeasuredRuntime(
        5.0, per_detector=True, note="cached astropy download cache, per detector"
    ),
    "data.inspect": MeasuredRuntime(5.0, note="segment query and finite checks"),
    "aframe.detect": MeasuredRuntime(
        5.0, per_window=True, uses_gpu=True, note="per 128 s window, RTX 5000 Ada"
    ),
    "amplfi.pe": MeasuredRuntime(
        15.0, uses_gpu=True, note="20000 samples plus sky map, RTX 5000 Ada"
    ),
    "buoy.analyze": MeasuredRuntime(
        40.0, uses_gpu=True, note="per event, models cached, RTX 5000 Ada"
    ),
    "gwak.scan": MeasuredRuntime(
        30.0, per_window=True, uses_gpu=True, note="contract estimate; adapter blocked"
    ),
    "deepclean.check_applicability": MeasuredRuntime(1.0, note="table lookup"),
    "deepclean.clean": MeasuredRuntime(
        600.0, uses_gpu=True, note="planned; contract estimate"
    ),
    "analysis.reconcile": MeasuredRuntime(1.0),
    "report.generate": MeasuredRuntime(1.0),
}
AFRAME_BACKGROUND_SECONDS_PER_STRETCH = 100.0  # per 3900 s stretch, measured
DEFAULT_RUNTIME = MeasuredRuntime(60.0, note="unknown skill; conservative default")


@dataclass(frozen=True)
class EstimateConfig:
    data_cached: bool = True
    gpu_available: bool = True
    network_bytes_per_second: float = 70_000.0
    segment_seconds: float = 4096.0
    overlap_seconds: float = 64.0


@dataclass
class ResourceEstimate:
    cpu_hours: float = 0.0
    gpu_hours: float = 0.0
    memory_gb: float = 0.0
    transfer_gb: float = 0.0
    expected_latency_seconds: float = 0.0
    n_segments: int = 1
    per_task: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cpu_hours": round(self.cpu_hours, 4),
            "gpu_hours": round(self.gpu_hours, 4),
            "memory_gb": round(self.memory_gb, 2),
            "transfer_gb": round(self.transfer_gb, 4),
            "expected_latency_seconds": round(self.expected_latency_seconds, 1),
            "n_segments": self.n_segments,
            "per_task": list(self.per_task),
            "assumptions": list(self.assumptions),
        }


def _window_seconds(parameters: dict[str, Any]) -> float:
    value = parameters.get("window_seconds")
    try:
        return float(value) if value is not None else WINDOW_SECONDS
    except (TypeError, ValueError):
        return WINDOW_SECONDS


def _n_detectors(parameters: dict[str, Any]) -> int:
    ifos = parameters.get("ifos")
    return len(ifos) if isinstance(ifos, list) and ifos else 2


def estimate_plan(
    plan: PlanSpec, registry: SkillRegistry, config: EstimateConfig | None = None
) -> ResourceEstimate:
    """Sum per-task costs; partition long windows into scan segments."""
    config = config or EstimateConfig()
    estimate = ResourceEstimate()
    estimate.assumptions.append(
        "runtimes measured on an RTX 5000 Ada with cached GWOSC strain "
        "(2026-09-03 acceptance runs); CPU-only execution scaled by "
        f"{CPU_SLOWDOWN:g}x"
    )
    if not config.data_cached:
        estimate.assumptions.append(
            f"strain not cached: {FRAME_FILE_BYTES / 1e6:.0f} MB per detector at "
            f"{config.network_bytes_per_second / 1e3:.0f} kB/s"
        )
    # The strain window is set on data.fetch; downstream per-window skills
    # inherit it, so take the widest window declared anywhere in the plan.
    plan_window = max(
        (
            _window_seconds(task.parameters)
            for task in plan.tasks
            if isinstance(task.parameters, dict) and "window_seconds" in task.parameters
        ),
        default=WINDOW_SECONDS,
    )
    for task in plan.tasks:
        skill = registry.get(task.skill)
        runtime = RUNTIME_TABLE.get(task.skill, DEFAULT_RUNTIME)
        params = task.parameters if isinstance(task.parameters, dict) else {}
        window = _window_seconds(params) if "window_seconds" in params else plan_window
        segments = partition_scan(
            0.0, max(window, 1.0), config.segment_seconds, config.overlap_seconds
        )
        n_segments = len(segments)
        estimate.n_segments = max(estimate.n_segments, n_segments)
        detectors = _n_detectors(params)

        seconds = runtime.seconds
        if runtime.per_window:
            seconds *= max(window, 1.0) / WINDOW_SECONDS
        if runtime.per_detector:
            seconds *= detectors
        transfer_bytes = 0.0
        transfer_seconds = 0.0
        # both the decomposed fetch and Buoy's internal fetch pull one frame
        # file per detector when the astropy cache is cold
        if task.skill in FETCHING_SKILLS and not config.data_cached:
            transfer_bytes = FRAME_FILE_BYTES * detectors * n_segments
            transfer_seconds = transfer_bytes / config.network_bytes_per_second
        wants_gpu = skill.resources.gpu != "none" or runtime.uses_gpu
        on_gpu = wants_gpu and config.gpu_available
        if wants_gpu and not config.gpu_available:
            seconds *= CPU_SLOWDOWN
        if skill.resources.gpu == "required" and not config.gpu_available:
            estimate.assumptions.append(
                f"{task.skill} requires a GPU; none is available"
            )
        # per-window/per-detector work already scales with the window; other
        # steps repeat once per segment. Transfer time counts toward latency
        # only: a download does not occupy the accelerator.
        compute_seconds = seconds if runtime.per_window else seconds * n_segments
        total_seconds = compute_seconds + transfer_seconds
        cpu_hours = skill.resources.cpu_cores * compute_seconds / 3600.0
        gpu_hours = compute_seconds / 3600.0 if on_gpu else 0.0

        estimate.cpu_hours += cpu_hours
        estimate.gpu_hours += gpu_hours
        estimate.memory_gb = max(estimate.memory_gb, float(skill.resources.memory_gb))
        estimate.transfer_gb += transfer_bytes / 1e9
        estimate.expected_latency_seconds += total_seconds
        estimate.per_task.append(
            {
                "task": task.id,
                "skill": task.skill,
                "seconds": round(total_seconds, 1),
                "cpu_cores": skill.resources.cpu_cores,
                "memory_gb": skill.resources.memory_gb,
                "gpu": "yes" if on_gpu else ("cpu-fallback" if wants_gpu else "no"),
                "n_segments": n_segments,
                "basis": runtime.note or skill.resources.estimated_runtime,
            }
        )
    return estimate
