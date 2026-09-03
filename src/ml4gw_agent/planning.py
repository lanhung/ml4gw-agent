from __future__ import annotations

import re
from dataclasses import dataclass, field

from .calibration import aframe_threshold
from .errors import PlanningError
from .models import ConditionSpec, PlanSpec, TaskSpec
from .registry import SkillRegistry

EVENT_PATTERN = re.compile(
    r"\b(?:GW\d{6}(?:_\d{6})?|G\d{6,}|S\d{6}[a-z]+|\d{9,10}(?:\.\d+)?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlannerConfig:
    ifos: tuple[str, ...] = ("H1", "L1")
    device: str = "cuda"
    samples_per_event: int = 20_000
    nside: int = 64
    min_samples_per_pix: int = 5
    use_distance: bool = True
    use_true_tc_for_amplfi: bool = False
    buoy_runner: str = "cli"
    aframe_revision: str | None = None
    amplfi_revision: str | None = None
    gwak_revision: str | None = None
    seed: int | None = 0
    window_seconds: float = 128.0
    event_offset_fraction: float = 0.75
    sample_rate: int = 2048
    aframe_threshold: float | None = None
    aframe_far_per_year: float = 1.0
    candidate_window_seconds: float = 2.0
    data_source: str = "gwosc"
    extra_warnings: tuple[str, ...] = field(default_factory=tuple)


AFRAME_IFOS: tuple[str, ...] = ("H1", "L1")


class BaselinePlanner:
    """Deterministic baseline router used before an LLM planner is introduced.

    Its narrowness is deliberate: it gives the runtime a reproducible planning
    baseline and refuses prompts whose scope cannot be bounded safely.
    """

    def __init__(self, registry: SkillRegistry, config: PlannerConfig | None = None):
        self.registry = registry
        self.config = config or PlannerConfig()

    @staticmethod
    def extract_event(prompt: str) -> str:
        match = EVENT_PATTERN.search(prompt)
        if not match:
            raise PlanningError(
                "No supported event identifier was found. Provide a GWTC event "
                "(for example GW150914), a GraceDB ID, a superevent ID, or a GPS time."
            )
        event = match.group(0)
        if event[:2].lower() == "gw":
            return event.upper()
        if event[:1].lower() in {"g", "s"}:
            return event[0].upper() + event[1:]
        return event

    @staticmethod
    def _contains(text: str, *phrases: str) -> bool:
        return any(phrase in text for phrase in phrases)

    def plan(self, prompt: str) -> PlanSpec:
        if not prompt.strip():
            raise PlanningError("Prompt cannot be empty.")
        event = self.extract_event(prompt)
        text = prompt.casefold()

        wants_aframe = self._contains(
            text, "aframe", "cbc detection", "detect compact", "并合检测", "cbc 检测"
        )
        wants_amplfi = self._contains(
            text,
            "amplfi",
            "parameter estimation",
            "estimate parameters",
            "参数估计",
            "参数反演",
        )
        wants_gwak = self._contains(
            text,
            "gwak",
            "anomaly",
            "unmodeled",
            "unusual",
            "异常",
            "未建模",
        )
        wants_deepclean = self._contains(
            text,
            "deepclean",
            "noise subtraction",
            "clean the data",
            "denoise",
            "去噪",
            "噪声扣除",
        )
        wants_data = self._contains(
            text,
            "fetch data",
            "download data",
            "data quality",
            "strain data",
            "下载数据",
            "数据质量",
            "应变数据",
        )
        explicitly_composed = any(
            (wants_aframe, wants_amplfi, wants_gwak, wants_deepclean, wants_data)
        )

        if not explicitly_composed or "buoy" in text:
            plan = self._buoy_plan(prompt, event)
        else:
            plan = self._composed_plan(
                prompt=prompt,
                event=event,
                wants_aframe=wants_aframe,
                wants_amplfi=wants_amplfi,
                wants_gwak=wants_gwak,
                wants_deepclean=wants_deepclean,
            )

        self.registry.validate_plan_skills(plan)
        return plan

    def _buoy_plan(self, prompt: str, event: str) -> PlanSpec:
        parameters: dict[str, object] = {
            "event": event,
            "samples_per_event": self.config.samples_per_event,
            "nside": self.config.nside,
            "min_samples_per_pix": self.config.min_samples_per_pix,
            "use_distance": self.config.use_distance,
            "use_true_tc_for_amplfi": self.config.use_true_tc_for_amplfi,
            "runner": self.config.buoy_runner,
            "device": self.config.device,
            "seed": self.config.seed,
            "ifos": list(self.config.ifos),
        }
        if self.config.aframe_revision:
            parameters["aframe_revision"] = self.config.aframe_revision
        if self.config.amplfi_revision:
            parameters["amplfi_revision"] = self.config.amplfi_revision

        warnings = list(self.config.extra_warnings)
        if not self.config.aframe_revision or not self.config.amplfi_revision:
            warnings.append(
                "Buoy model revisions are not fully pinned; use immutable revisions "
                "before treating a real run as reproducible science."
            )

        return PlanSpec(
            prompt=prompt,
            goal=f"Analyze {event} with the Buoy Aframe+AMPLFI vertical pipeline.",
            warnings=warnings,
            tasks=[
                TaskSpec(
                    id="resolve_event",
                    skill="data.resolve_event",
                    parameters={"event": event},
                ),
                TaskSpec(
                    id="analyze_event",
                    skill="buoy.analyze",
                    parameters=parameters,
                    depends_on=["resolve_event"],
                ),
                TaskSpec(
                    id="generate_report",
                    skill="report.generate",
                    parameters={"title": f"ML4GW Agent report: {event}"},
                    depends_on=["analyze_event"],
                    allow_failed_dependencies=True,
                ),
            ],
        )

    def _aframe_threshold(
        self, warnings: list[str]
    ) -> tuple[float, dict[str, object] | None]:
        """Explicit threshold, else the calibrated one for the pinned revision."""
        if self.config.aframe_threshold is not None:
            return float(self.config.aframe_threshold), None
        calibrated = aframe_threshold(
            self.config.aframe_revision, self.config.aframe_far_per_year
        )
        if calibrated is None:
            warnings.append(
                "No background calibration exists for the requested Aframe "
                "revision and false-alarm rate; using the raw 0.0 cut, so "
                "candidate_found is not a significance statement."
            )
            return 0.0, None
        return calibrated.threshold, calibrated.as_dict()

    def _composed_plan(
        self,
        *,
        prompt: str,
        event: str,
        wants_aframe: bool,
        wants_amplfi: bool,
        wants_gwak: bool,
        wants_deepclean: bool,
    ) -> PlanSpec:
        # AMPLFI needs a coalescence-time estimate, so the baseline planner
        # schedules Aframe first unless a future structured request supplies one.
        wants_aframe = wants_aframe or wants_amplfi
        tasks = [
            TaskSpec(
                id="resolve_event",
                skill="data.resolve_event",
                parameters={"event": event},
            ),
            TaskSpec(
                id="fetch_data",
                skill="data.fetch",
                parameters={
                    "event": event,
                    "source": self.config.data_source,
                    "gps_time": "${resolve_event.outputs.catalog_time}",
                    "ifos": list(self.config.ifos),
                    "window_seconds": self.config.window_seconds,
                    "event_offset_fraction": self.config.event_offset_fraction,
                    "sample_rate": self.config.sample_rate,
                },
                depends_on=["resolve_event"],
            ),
            TaskSpec(
                id="inspect_data",
                skill="data.inspect",
                parameters={
                    "strain_artifact": "${fetch_data.outputs.strain_artifact}",
                    "expected_ifos": list(self.config.ifos),
                    "min_duration_seconds": self.config.window_seconds,
                    "require_science_mode": True,
                },
                depends_on=["fetch_data"],
            ),
        ]
        terminal_ids: list[str] = ["inspect_data"]
        warnings = list(self.config.extra_warnings)

        if wants_deepclean:
            tasks.append(
                TaskSpec(
                    id="check_deepclean",
                    skill="deepclean.check_applicability",
                    parameters={
                        "event": event,
                        "strain_artifact": "${fetch_data.outputs.strain_artifact}",
                        "ifos": list(self.config.ifos),
                    },
                    depends_on=["inspect_data"],
                )
            )
            terminal_ids.append("check_deepclean")
            warnings.append(
                "DeepClean is applicability-check-only in v0.1. Cleaning is not "
                "scheduled unless witness channels, coupling configuration, and "
                "compatible immutable weights are all verified."
            )

        if wants_aframe:
            aframe_revision = self.config.aframe_revision or "UNPINNED"
            threshold, calibration = self._aframe_threshold(warnings)
            if tuple(self.config.ifos) != AFRAME_IFOS:
                warnings.append(
                    f"Aframe runs on {list(AFRAME_IFOS)} only (the published model's "
                    f"detector set); the requested {list(self.config.ifos)} are "
                    "used for data fetching, quality checks, and AMPLFI."
                )
            tasks.append(
                TaskSpec(
                    id="run_aframe",
                    skill="aframe.detect",
                    parameters={
                        "strain_artifact": "${fetch_data.outputs.strain_artifact}",
                        "ifos": list(AFRAME_IFOS),
                        "model_revision": aframe_revision,
                        "device": self.config.device,
                        "threshold": threshold,
                        "threshold_calibration": calibration,
                        "target_time": "${resolve_event.outputs.catalog_time}",
                        "candidate_window_seconds": (
                            self.config.candidate_window_seconds
                        ),
                        "seed": self.config.seed,
                    },
                    depends_on=["inspect_data"],
                    when=ConditionSpec(
                        reference="${inspect_data.outputs.quality_passed}",
                        operator="truthy",
                    ),
                )
            )
            terminal_ids.append("run_aframe")
            if aframe_revision == "UNPINNED":
                warnings.append("Aframe model revision is not pinned.")

        if wants_amplfi:
            amplfi_revision = self.config.amplfi_revision or "UNPINNED"
            tasks.append(
                TaskSpec(
                    id="run_amplfi",
                    skill="amplfi.pe",
                    parameters={
                        "strain_artifact": "${fetch_data.outputs.strain_artifact}",
                        "coalescence_time": (
                            "${run_aframe.outputs.predicted_coalescence_time}"
                        ),
                        "ifos": list(self.config.ifos),
                        "model_revision": amplfi_revision,
                        "samples": self.config.samples_per_event,
                        "device": self.config.device,
                        "seed": self.config.seed,
                        "nside": self.config.nside,
                        "min_samples_per_pix": self.config.min_samples_per_pix,
                        "use_distance": self.config.use_distance,
                    },
                    depends_on=["run_aframe"],
                    when=ConditionSpec(
                        reference="${run_aframe.outputs.candidate_found}",
                        operator="truthy",
                    ),
                )
            )
            terminal_ids.append("run_amplfi")
            if amplfi_revision == "UNPINNED":
                warnings.append("AMPLFI model revision is not pinned.")

        if wants_gwak:
            gwak_revision = self.config.gwak_revision or "UNPINNED"
            # GWAK models were trained at 4096 Hz; fetch a dedicated copy so the
            # Aframe/AMPLFI 2048 Hz path stays byte-for-byte what Buoy sees.
            tasks.append(
                TaskSpec(
                    id="fetch_data_4k",
                    skill="data.fetch",
                    parameters={
                        "event": event,
                        "source": self.config.data_source,
                        "gps_time": "${resolve_event.outputs.catalog_time}",
                        "ifos": list(AFRAME_IFOS),
                        "window_seconds": self.config.window_seconds,
                        "event_offset_fraction": self.config.event_offset_fraction,
                        "sample_rate": 4096,
                    },
                    depends_on=["resolve_event"],
                )
            )
            tasks.append(
                TaskSpec(
                    id="run_gwak",
                    skill="gwak.scan",
                    parameters={
                        "strain_artifact": "${fetch_data_4k.outputs.strain_artifact}",
                        "model_revision": gwak_revision,
                        "top_k": 10,
                        "target_time": "${resolve_event.outputs.catalog_time}",
                        "device": self.config.device,
                        "seed": self.config.seed,
                    },
                    depends_on=["inspect_data", "fetch_data_4k"],
                    when=ConditionSpec(
                        reference="${inspect_data.outputs.quality_passed}",
                        operator="truthy",
                    ),
                )
            )
            terminal_ids.append("run_gwak")
            if gwak_revision == "UNPINNED":
                warnings.append("GWAK model revision is not pinned.")

        if wants_gwak and wants_aframe:
            # Discrepancy logic: an Aframe-negative / GWAK-positive segment is
            # routed to morphology diagnostics, never to AMPLFI (which stays
            # conditioned on the Aframe candidate above).
            tasks.append(
                TaskSpec(
                    id="reconcile_detections",
                    skill="analysis.reconcile",
                    parameters={"aframe_task": "run_aframe", "gwak_task": "run_gwak"},
                    depends_on=["run_aframe", "run_gwak"],
                    allow_failed_dependencies=True,
                )
            )
            terminal_ids.append("reconcile_detections")

        tasks.append(
            TaskSpec(
                id="generate_report",
                skill="report.generate",
                parameters={"title": f"ML4GW Agent composed analysis: {event}"},
                depends_on=list(dict.fromkeys(terminal_ids)),
                allow_failed_dependencies=True,
            )
        )

        return PlanSpec(
            prompt=prompt,
            goal=f"Compose a bounded ML4GW analysis for {event}.",
            tasks=tasks,
            warnings=warnings,
        )
