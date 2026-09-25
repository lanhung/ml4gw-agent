from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .calibration import aframe_threshold, gwak_threshold
from .errors import PlanningError
from .models import ConditionSpec, PlanSpec, TaskSpec
from .registry import SkillRegistry

EVENT_PATTERN = re.compile(
    r"\b(?:GW\d{6}(?:_\d{6})?|G\d{6,}|S\d{6}[a-z]+|\d{9,10}(?:\.\d+)?"
    r"|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s?(?:UTC|Z))?)\b",
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
    gwak_threshold: float | None = None
    gwak_far_per_year: float = 365.25
    candidate_window_seconds: float = 2.0
    data_source: str = "gwosc"
    pipeline: Literal["auto", "buoy", "decomposed"] = "auto"
    exclude_skills: tuple[str, ...] = ()
    extra_warnings: tuple[str, ...] = field(default_factory=tuple)


AFRAME_IFOS: tuple[str, ...] = ("H1", "L1")

# Prompt vocabulary per tool. A mention counts as a request only when no
# negation cue precedes it inside the same clause (see ``mentions``).
TOOL_PHRASES: dict[str, tuple[str, ...]] = {
    "aframe": ("aframe", "cbc detection", "detect compact", "并合检测", "cbc 检测"),
    "amplfi": (
        "amplfi",
        "parameter estimation",
        "estimate parameters",
        "参数估计",
        "参数反演",
    ),
    "gwak": ("gwak", "anomaly", "unmodeled", "unusual", "异常", "未建模"),
    "deepclean": (
        "deepclean",
        "noise subtraction",
        "clean the data",
        "denoise",
        "去噪",
        "噪声扣除",
    ),
    "data": (
        "fetch data",
        "download data",
        "data quality",
        "strain data",
        "下载数据",
        "数据质量",
        "应变数据",
    ),
    "buoy": ("buoy",),
}

# Skill names each tool word stands for; used for structured exclusions and
# for the fail-closed check that a plan never schedules an excluded skill.
TOOL_SKILLS: dict[str, tuple[str, ...]] = {
    "aframe": ("aframe.detect",),
    "amplfi": ("amplfi.pe",),
    "gwak": ("gwak.scan", "analysis.reconcile"),
    "deepclean": ("deepclean.check_applicability", "deepclean.clean"),
    "buoy": ("buoy.analyze",),
}

NEGATION_CUES: tuple[str, ...] = (
    "do not",
    "don't",
    "dont ",
    "does not",
    "doesn't",
    "not ",
    "no ",
    "never",
    "without",
    "skip",
    "exclude",
    "excluding",
    "omit",
    "avoid",
    "instead of",
    "rather than",
    "不要",
    "不需要",
    "无需",
    "不用",
    "不必",
    "别",
    "跳过",
    "排除",
    "不运行",
    "不做",
    "不进行",
    "不含",
    "不包括",
    "不跑",
    "免去",
)
# A contrast or continuation marker after the cue ends its scope:
# "not Aframe but AMPLFI", "skip detection and go straight to AMPLFI".
CONTRAST_MARKERS: tuple[str, ...] = (
    " but ",
    " only ",
    " just ",
    " then ",
    " go ",
    " straight",
    "而是",
    "只",
    "仅",
    "直接",
    "然后",
    "接着",
    "再",
)
# Between an earlier negated tool and a later one, only a bare conjunction
# keeps the negation: "do not run AMPLFI or GWAK".
CONJUNCTION_GAP = re.compile(r"^[\s,、]*(?:and|or|nor|和|或|及|以及|与)?[\s,、]*$")
CLAUSE_SPLIT = re.compile(r"[.;!?\n。；！？,，]")
NEGATION_WINDOW = 48


@dataclass(frozen=True)
class ToolMentions:
    """Which tools a prompt asks for and which it rules out."""

    requested: frozenset[str]
    excluded: frozenset[str]


@dataclass(frozen=True)
class RequestConstraints:
    """What a request rules out, after prompt and configuration are merged.

    Both planners honour the same object: the baseline builds its DAG from it
    and the LLM planner rejects any model plan that schedules an excluded
    skill. ``overrides`` are warnings for worded exclusions that precondition
    reasoning had to ignore (AMPLFI needs Aframe).
    """

    requested: frozenset[str]
    excluded_tools: frozenset[str]
    excluded_skills: frozenset[str]
    overrides: tuple[str, ...] = ()


def mentions(text: str) -> ToolMentions:
    """Classify every tool mention as requested or negated.

    The scan is clause-local: a negation cue only affects tool words that
    follow it in the same clause, within ``NEGATION_WINDOW`` characters, and
    with no contrast marker in between. Structured ``exclude_skills`` remain
    the authoritative channel; this heuristic exists so a plain sentence like
    "do not run AMPLFI" is never read as a request to run it.
    """
    requested: set[str] = set()
    excluded: set[str] = set()
    all_phrases = [phrase for phrases in TOOL_PHRASES.values() for phrase in phrases]
    for clause in CLAUSE_SPLIT.split(text):
        for tool, phrases in TOOL_PHRASES.items():
            for phrase in phrases:
                start = clause.find(phrase)
                while start != -1:
                    window = clause[max(0, start - NEGATION_WINDOW) : start]
                    cue_at = max(
                        (window.rfind(cue) for cue in NEGATION_CUES), default=-1
                    )
                    negated = cue_at != -1
                    if negated:
                        scope = window[cue_at:]
                        negated = not any(m in scope for m in CONTRAST_MARKERS)
                    if negated:
                        # an earlier tool inside the scope takes the negation
                        # unless this mention is joined to it by a conjunction
                        ends = [
                            scope.find(other) + len(other)
                            for other in all_phrases
                            if other != phrase and other in scope
                        ]
                        if ends:
                            negated = bool(CONJUNCTION_GAP.match(scope[max(ends) :]))
                    (excluded if negated else requested).add(tool)
                    start = clause.find(phrase, start + len(phrase))
    return ToolMentions(frozenset(requested), frozenset(excluded))


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

        constraints = self.constraints(prompt)
        found = constraints
        excluded_tools = set(constraints.excluded_tools)
        excluded_skills = set(constraints.excluded_skills)
        override = list(constraints.overrides)
        wants = {tool: tool in found.requested for tool in TOOL_PHRASES}
        wants_aframe = wants["aframe"]
        wants_amplfi = wants["amplfi"]
        wants_gwak = wants["gwak"]
        wants_deepclean = wants["deepclean"]
        wants_data = wants["data"]
        wants_buoy = wants["buoy"]
        explicitly_composed = any(
            (wants_aframe, wants_amplfi, wants_gwak, wants_deepclean, wants_data)
        )
        wants_lookup = (
            not explicitly_composed
            and not wants_buoy
            and not excluded_tools
            and self.config.pipeline == "auto"
            and (
                self._contains(
                    text,
                    "what is the mass",
                    "what are the masses",
                    "how massive",
                    "how far",
                    "what is the distance",
                    "when did",
                    "what time",
                    "which detectors",
                    "what is the far",
                    "false alarm rate of",
                    "look up",
                    "lookup",
                    "catalog value",
                    "catalog parameters",
                    "was it retracted",
                    "is it retracted",
                    "质量是多少",
                    "多大质量",
                    "距离是多少",
                    "有多远",
                    "什么时候",
                    "发生时间",
                    "哪些探测器",
                    "误报率是多少",
                    "查一下",
                    "查询",
                    "是否被撤回",
                    "撤回了吗",
                )
            )
        )
        route = self._route(
            wants_buoy=wants_buoy,
            wants_lookup=wants_lookup,
            explicitly_composed=explicitly_composed,
            excluded_tools=excluded_tools,
            wants_gwak=wants_gwak,
            wants_deepclean=wants_deepclean,
        )

        if route == "lookup":
            plan = self._lookup_plan(prompt, event)
        elif route == "buoy":
            plan = self._buoy_plan(prompt, event)
        else:
            if not explicitly_composed:
                # A generic request routed away from Buoy gets Buoy's content:
                # detection followed by conditional parameter estimation.
                wants_aframe, wants_amplfi = True, True
            wants_aframe = (wants_aframe or wants_amplfi) and "aframe" not in (
                excluded_tools
            )
            if wants_amplfi and "aframe" in excluded_tools:
                raise PlanningError(
                    "AMPLFI needs the coalescence time that Aframe estimates; "
                    "it cannot run with aframe.detect excluded."
                )
            plan = self._composed_plan(
                prompt=prompt,
                event=event,
                wants_aframe=wants_aframe,
                wants_amplfi=wants_amplfi and "amplfi" not in excluded_tools,
                wants_gwak=wants_gwak and "gwak" not in excluded_tools,
                wants_deepclean=wants_deepclean and "deepclean" not in excluded_tools,
            )

        plan = self._constrain(plan, route, excluded_tools, excluded_skills)
        if override:
            plan = plan.model_copy(update={"warnings": plan.warnings + override})
        self.registry.validate_plan_skills(plan)
        return plan

    def constraints(self, prompt: str) -> RequestConstraints:
        """Merge worded and structured exclusions; refuse contradictions."""
        found = mentions(prompt.casefold())
        overrides: tuple[str, ...] = ()
        if "amplfi" in found.requested and "aframe" in found.excluded:
            # Precondition reasoning wins over wording: AMPLFI needs the
            # coalescence time Aframe estimates, so Aframe stays scheduled.
            found = ToolMentions(found.requested, found.excluded - {"aframe"})
            overrides = (
                "Aframe was ruled out by the prompt but is scheduled anyway: "
                "AMPLFI needs the coalescence time that Aframe estimates.",
            )
        excluded_tools, excluded_skills = self._exclusions(found)
        conflict = sorted(found.requested & excluded_tools - {"data"})
        if conflict:
            raise PlanningError(
                f"The request both asks for and rules out {conflict}. Reword the "
                "prompt or pass exclude_skills explicitly."
            )
        return RequestConstraints(
            requested=found.requested,
            excluded_tools=frozenset(excluded_tools),
            excluded_skills=frozenset(excluded_skills),
            overrides=overrides,
        )

    def _exclusions(self, found: ToolMentions) -> tuple[set[str], set[str]]:
        """Merge negated prompt mentions with structured exclude_skills."""
        skills: set[str] = set()
        for name in self.config.exclude_skills:
            if name not in self.registry:
                valid = ", ".join(skill.name for skill in self.registry.all())
                raise PlanningError(
                    f"exclude_skills names an unknown skill: {name}. "
                    f"Valid skill names: {valid}"
                )
            skills.add(name)
        tools = {tool for tool in found.excluded if tool != "data"}
        # A structured skill name stands for its whole tool: ruling out
        # gwak.scan also rules out the reconciliation that needs it.
        tools.update(
            tool
            for tool, tool_skills in TOOL_SKILLS.items()
            if skills & set(tool_skills)
        )
        for tool in tools:
            skills.update(TOOL_SKILLS[tool])
        return tools, skills

    def _route(
        self,
        *,
        wants_buoy: bool,
        wants_lookup: bool,
        explicitly_composed: bool,
        excluded_tools: set[str],
        wants_gwak: bool,
        wants_deepclean: bool,
    ) -> Literal["buoy", "decomposed", "lookup"]:
        buoy_blocked = bool(excluded_tools & {"buoy", "aframe", "amplfi"})
        if self.config.pipeline == "buoy":
            if buoy_blocked:
                raise PlanningError(
                    "pipeline='buoy' runs Aframe and AMPLFI inside Buoy, which "
                    f"conflicts with excluding {sorted(excluded_tools)}."
                )
            if wants_gwak or wants_deepclean:
                raise PlanningError(
                    "pipeline='buoy' covers Aframe and AMPLFI only; GWAK or "
                    "DeepClean requests need pipeline='decomposed'."
                )
            return "buoy"
        if self.config.pipeline == "decomposed":
            return "decomposed"
        if wants_lookup:
            return "lookup"
        if buoy_blocked:
            return "decomposed"
        if wants_buoy or not explicitly_composed:
            return "buoy"
        return "decomposed"

    @staticmethod
    def _constrain(
        plan: PlanSpec,
        route: Literal["buoy", "decomposed", "lookup"],
        excluded_tools: set[str],
        excluded_skills: set[str],
    ) -> PlanSpec:
        """Record the route and fail closed if an excluded skill slipped in."""
        scheduled = sorted({task.skill for task in plan.tasks} & excluded_skills)
        if scheduled:
            raise PlanningError(f"plan would schedule excluded skills: {scheduled}")
        warnings = list(plan.warnings)
        if excluded_skills:
            warnings.append(
                "Excluded by request: " + ", ".join(sorted(excluded_skills)) + "."
            )
        return plan.model_copy(
            update={
                "route": route,
                "excluded_skills": sorted(excluded_skills),
                "warnings": warnings,
            }
        )

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

    def _gwak_threshold(
        self, warnings: list[str]
    ) -> tuple[float, dict[str, object] | None]:
        """Explicit GWAK threshold, else the calibrated one for the revision."""
        if self.config.gwak_threshold is not None:
            return float(self.config.gwak_threshold), None
        calibrated = gwak_threshold(
            self.config.gwak_revision, self.config.gwak_far_per_year
        )
        if calibrated is None:
            warnings.append(
                "No background calibration exists for the requested GWAK "
                "revision and false-alarm rate; using the raw 0.0 cut, so "
                "anomaly_found is not a significance statement."
            )
            return 0.0, None
        return calibrated.threshold, calibrated.as_dict()

    def _lookup_plan(self, prompt: str, event: str) -> PlanSpec:
        """Answer from catalogs and GraceDB only: no strain, no models."""
        tasks = [
            TaskSpec(
                id="resolve_event",
                skill="data.resolve_event",
                parameters={"event": event},
            ),
            TaskSpec(
                id="lookup",
                skill="catalog.lookup",
                parameters={"event": event, "question": prompt},
                depends_on=["resolve_event"],
            ),
            TaskSpec(
                id="generate_report",
                skill="report.generate",
                parameters={"title": f"Catalog lookup for {event}"},
                depends_on=["lookup"],
                allow_failed_dependencies=True,
            ),
        ]
        return PlanSpec(
            prompt=prompt,
            goal=f"Answer a catalog question about {event} without running an analysis",
            tasks=tasks,
            warnings=[
                "Lookup route: values come from the GWTC catalogs and GraceDB; "
                "no strain was fetched and no model ran."
            ],
        )

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
            tasks.append(
                TaskSpec(
                    id="clean_deepclean",
                    skill="deepclean.clean",
                    parameters={
                        "strain_artifact": "${fetch_data.outputs.strain_artifact}",
                        "witness_artifact": (
                            "${check_deepclean.outputs.witness_artifact}"
                        ),
                        "coupling_config": (
                            "${check_deepclean.outputs.coupling_config}"
                        ),
                        "model_revision": "${check_deepclean.outputs.model_revision}",
                        "ifo": "${check_deepclean.outputs.ifo}",
                    },
                    depends_on=["check_deepclean"],
                    when=ConditionSpec(
                        reference="${check_deepclean.outputs.applicable}",
                        operator="truthy",
                    ),
                )
            )
            terminal_ids.append("clean_deepclean")
            warnings.append(
                "DeepClean cleaning runs only if the applicability check verifies "
                "witness channels, a reviewed coupling configuration, and "
                "compatible immutable weights; otherwise the task is skipped."
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
            gwak_cut, gwak_calibration = self._gwak_threshold(warnings)
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
                        "threshold": gwak_cut,
                        "threshold_calibration": gwak_calibration,
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
