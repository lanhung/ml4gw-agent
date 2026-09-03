"""Measured LLM planning behind the deterministic execution boundary.

Phase 5 adds a language-model planner without weakening anything the runtime
already enforces. The model sees only registry summaries relevant to the
request and must answer with JSON that validates as :class:`PlanSpec`;
skills outside the registry, unknown parameters, malformed references,
cycles, and unpinned models are rejected exactly as they are for any other
plan source. One bounded repair round is allowed; after that the
deterministic baseline plan is used and the manifest records why.

Observation and replanning are bounded the same way: after a run the
structured observation (task statuses, key outputs, failures) is turned into
one replanning request at most. Experiment memory stores what was run and
what happened (data, models, configuration, result, failures) as JSON lines,
never raw chat history.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .errors import PlanningError, PolicyError, RegistryError
from .models import PlanSpec, RunManifest, TaskStatus
from .planning import BaselinePlanner, PlannerConfig
from .policy import ExecutionPolicy
from .registry import SkillRegistry

DEFAULT_MODEL = "claude-opus-5"
PLANNER_NAME = "llm-claude-v0.3"
REFERENCE = re.compile(r"^\$\{([A-Za-z0-9_.-]+)\.outputs\.([A-Za-z0-9_]+)\}$")

# Plan schema the model must satisfy. Kept in sync with PlanSpec/TaskSpec by
# the unit tests; the runtime never trusts it alone.
PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goal", "tasks", "warnings"],
    "properties": {
        "goal": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "tasks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "skill", "parameters", "depends_on"],
                "properties": {
                    "id": {"type": "string"},
                    "skill": {"type": "string"},
                    "parameters": {"type": "object"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "when": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "required": ["reference", "operator"],
                        "properties": {
                            "reference": {"type": "string"},
                            "operator": {
                                "enum": ["truthy", "falsy", "equals", "not_equals"]
                            },
                            "value": {},
                        },
                    },
                    "allow_failed_dependencies": {"type": "boolean"},
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You plan gravitational-wave analyses for the ML4GW Agent.
You decide WHAT to run; deterministic adapters decide HOW. Rules:
- Use only the skills listed in the request, with only the parameters their
  input schema names. Never invent skills, shell commands, file paths, or
  credentials.
- Express data flow with typed references of the exact form
  ${task_id.outputs.field}; a task that reads another task's output must list
  it in depends_on.
- Every plan starts with data.resolve_event for the event identifier in the
  request and ends with report.generate (allow_failed_dependencies true).
- amplfi.pe may run only after aframe.detect and only when
  ${run_aframe.outputs.candidate_found} is truthy; its coalescence_time must be
  ${run_aframe.outputs.predicted_coalescence_time}.
- aframe.detect uses ifos ["H1", "L1"]; inspect_data gates every analysis on
  ${inspect_data.outputs.quality_passed}.
- deepclean.clean is never scheduled without a completed
  deepclean.check_applicability whose applicable output is truthy.
- Use the model revisions given in the request verbatim; never mark a model
  as pinned yourself.
- Refuse unbounded requests (whole observing runs, "everything") by returning
  a single report.generate task with a warning explaining the bound.
Answer with JSON only, matching the provided schema."""


class LLMClient(Protocol):
    """One seam: given prompts and a JSON schema, return the JSON text."""

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str: ...


@dataclass
class AnthropicClient:
    """Thin wrapper over the official SDK with structured output."""

    model: str = DEFAULT_MODEL
    max_tokens: int = 16000
    effort: str = "high"
    last_usage: dict[str, int] = field(default_factory=dict)

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised by the extra
            raise PlanningError(
                "the LLM planner needs the anthropic SDK: uv sync --extra llm"
            ) from exc
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        if response.stop_reason == "refusal":
            raise PlanningError("the model declined to plan this request")
        self.last_usage = {
            "input_tokens": int(response.usage.input_tokens),
            "output_tokens": int(response.usage.output_tokens),
        }
        return next(block.text for block in response.content if block.type == "text")


@dataclass
class ReplayClient:
    """Deterministic stand-in: answers from a callable or a recorded table.

    Used by the tests and by ``scripts/evaluate_planner.py`` so the planning
    pipeline can be exercised and its metrics reported without credentials.
    """

    responder: Callable[[str, str, dict[str, Any]], str]
    calls: list[dict[str, str]] = field(default_factory=list)

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls.append({"system": system, "user": user})
        return self.responder(system, user, schema)


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    # a few domain synonyms, including Chinese request words seen in use
    synonyms = {
        "参数估计": "amplfi",
        "参数": "amplfi",
        "探测": "aframe",
        "异常": "gwak",
        "数据质量": "inspect",
        "质量": "inspect",
        "分析": "analyze",
        "清洗": "deepclean",
        "降噪": "deepclean",
    }
    for zh, en in synonyms.items():
        if zh in text:
            words.add(en)
    return words


def retrieve_skill_summaries(
    registry: SkillRegistry, prompt: str, limit: int = 8
) -> list[dict[str, Any]]:
    """Registry summaries ranked by lexical overlap with the request.

    The baseline skills every plan needs (event resolution, data, quality,
    report) are always included; the rest are ranked so the model sees only
    what is relevant instead of the whole registry.
    """
    always = {"data.resolve_event", "data.fetch", "data.inspect", "report.generate"}
    words = _tokens(prompt)
    scored = []
    for skill in registry.all():
        haystack = " ".join(
            [skill.name.replace(".", " "), skill.description, " ".join(skill.tags)]
        )
        overlap = len(words & _tokens(haystack))
        if skill.name in always:
            overlap += 100
        if overlap:
            scored.append((overlap, skill))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    summaries = []
    for _, skill in scored[:limit]:
        properties = skill.input_schema.get("properties", {})
        summaries.append(
            {
                "name": skill.name,
                "description": skill.description,
                "status": skill.status.value,
                "adapter": skill.adapter.kind.value,
                "inputs": {
                    key: {
                        k: v
                        for k, v in spec.items()
                        if k in {"type", "enum", "default", "description"}
                    }
                    for key, spec in properties.items()
                },
                "required": skill.input_schema.get("required", []),
                "outputs": list(skill.output_schema.get("properties", {})),
                "preconditions": [p.name for p in skill.preconditions],
            }
        )
    return summaries


def plan_hash(plan: PlanSpec) -> str:
    payload = json.dumps(
        [
            {
                "id": t.id,
                "skill": t.skill,
                "parameters": t.parameters,
                "depends_on": t.depends_on,
                "when": t.when.model_dump() if t.when else None,
            }
            for t in plan.tasks
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def observe(manifest: RunManifest) -> dict[str, Any]:
    """Structured observation of a run: what ran, what it produced, what broke."""
    interesting = (
        "quality_passed",
        "candidate_found",
        "detection_statistic",
        "predicted_coalescence_time",
        "applicable",
        "route",
        "anomaly_found",
        "n_samples",
    )
    tasks = {}
    for task_id, record in manifest.tasks.items():
        tasks[task_id] = {
            "skill": record.skill,
            "status": record.status.value,
            "outputs": {
                k: record.outputs[k] for k in interesting if k in record.outputs
            },
            "error": record.error,
        }
    return {
        "run_id": manifest.run_id,
        "status": manifest.status.value,
        "tasks": tasks,
        "warnings": list(manifest.warnings),
    }


@dataclass
class ExperimentMemory:
    """Append-only JSON-lines memory of experiments, not of conversation."""

    path: Path

    def record(
        self, plan: PlanSpec, manifest: RunManifest, config: PlannerConfig
    ) -> dict[str, Any]:
        event = next(
            (
                str(t.parameters.get("event"))
                for t in plan.tasks
                if "event" in t.parameters
            ),
            None,
        )
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": manifest.run_id,
            "prompt": plan.prompt,
            "planner": plan.planner,
            "plan_hash": plan_hash(plan),
            "data": {
                "event": event,
                "ifos": list(config.ifos),
                "window_seconds": config.window_seconds,
                "source": config.data_source,
            },
            "models": {
                "aframe_revision": config.aframe_revision,
                "amplfi_revision": config.amplfi_revision,
                "gwak_revision": config.gwak_revision,
            },
            "configuration": {
                "device": config.device,
                "seed": config.seed,
                "aframe_far_per_year": config.aframe_far_per_year,
                "candidate_window_seconds": config.candidate_window_seconds,
            },
            "result": {
                "status": manifest.status.value,
                "tasks": {t: r.status.value for t, r in manifest.tasks.items()},
                "failures": {
                    t: r.error
                    for t, r in manifest.tasks.items()
                    if r.status in {TaskStatus.FAILED, TaskStatus.BLOCKED}
                },
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def recall(self, event: str | None, limit: int = 3) -> list[dict[str, Any]]:
        if event is None or not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("data", {}).get("event") == event:
                entries.append(entry)
        return entries[-limit:]


@dataclass
class LLMPlanner:
    """LLM proposals validated by the same rules as any other plan."""

    registry: SkillRegistry
    client: LLMClient
    config: PlannerConfig = field(default_factory=PlannerConfig)
    max_repairs: int = 1
    memory: ExperimentMemory | None = None
    mode: str = "real"
    last_diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.baseline = BaselinePlanner(self.registry, self.config)
        self.policy = ExecutionPolicy()

    # ---- prompt construction -------------------------------------------------
    def _request(self, prompt: str, extra: str = "") -> str:
        summaries = retrieve_skill_summaries(self.registry, prompt)
        try:
            event = self.baseline.extract_event(prompt)
        except PlanningError:
            event = None
        prior = self.memory.recall(event) if self.memory else []
        payload = {
            "request": prompt,
            "event": event,
            "available_skills": summaries,
            "configuration": {
                "ifos": list(self.config.ifos),
                "device": self.config.device,
                "seed": self.config.seed,
                "window_seconds": self.config.window_seconds,
                "sample_rate": self.config.sample_rate,
                "aframe_revision": self.config.aframe_revision or "UNPINNED",
                "amplfi_revision": self.config.amplfi_revision or "UNPINNED",
                "gwak_revision": self.config.gwak_revision or "UNPINNED",
                "data_source": self.config.data_source,
            },
            "prior_runs_for_this_event": [
                {
                    "status": p["result"]["status"],
                    "failures": p["result"]["failures"],
                    "planner": p["planner"],
                }
                for p in prior
            ],
            "reference_plan_from_deterministic_baseline": (self._baseline_json(prompt)),
        }
        text = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
        return text + ("\n\n" + extra if extra else "")

    def _baseline_json(self, prompt: str) -> dict[str, Any] | str:
        try:
            plan = self.baseline.plan(prompt)
        except PlanningError as exc:
            return f"baseline refused: {exc}"
        return {
            "goal": plan.goal,
            "tasks": [
                {
                    "id": t.id,
                    "skill": t.skill,
                    "parameters": t.parameters,
                    "depends_on": t.depends_on,
                    "when": t.when.model_dump() if t.when else None,
                    "allow_failed_dependencies": t.allow_failed_dependencies,
                }
                for t in plan.tasks
            ],
            "warnings": plan.warnings,
        }

    # ---- validation ----------------------------------------------------------
    def _validate(self, prompt: str, text: str) -> PlanSpec:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanningError(f"model output is not JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            raise PlanningError("model output lacks a tasks list")
        for task in data["tasks"]:
            if not isinstance(task, dict):
                raise PlanningError("every task must be an object")
            task.setdefault("parameters", {})
            task.setdefault("depends_on", [])
            task.pop("max_retries", None)
        try:
            plan = PlanSpec(
                prompt=prompt,
                goal=str(data.get("goal") or "LLM-planned analysis"),
                tasks=data["tasks"],
                warnings=[str(w) for w in data.get("warnings", [])],
                planner=PLANNER_NAME,
            )
        except ValidationError as exc:
            raise PlanningError(f"plan does not validate as PlanSpec: {exc}") from exc
        try:
            self.registry.validate_plan_skills(plan)
        except RegistryError as exc:
            raise PlanningError(f"registry rejects the plan: {exc}") from exc
        ids = {task.id for task in plan.tasks}
        upstream = _transitive_dependencies(plan)
        for task in plan.tasks:
            skill = self.registry.get(task.skill)
            allowed = set(skill.input_schema.get("properties", {}))
            if skill.input_schema.get("additionalProperties", True) is False:
                unknown = sorted(set(task.parameters) - allowed)
                if unknown:
                    raise PlanningError(
                        f"task {task.id} passes parameters {unknown} that "
                        f"{task.skill} does not accept"
                    )
            for value in _walk(task.parameters):
                if isinstance(value, str) and value.startswith("${"):
                    match = REFERENCE.fullmatch(value)
                    if not match:
                        raise PlanningError(
                            f"task {task.id} uses a malformed reference {value!r}"
                        )
                    source = match.group(1)
                    if source not in ids:
                        raise PlanningError(
                            f"task {task.id} references unknown task {source!r}"
                        )
                    if source not in upstream[task.id]:
                        raise PlanningError(
                            f"task {task.id} reads {source} but does not depend on it"
                        )
            if task.when is not None:
                match = REFERENCE.fullmatch(task.when.reference)
                if not match or match.group(1) not in ids:
                    raise PlanningError(
                        f"task {task.id} has a condition on an unknown reference"
                    )
        try:
            self.policy.validate(plan, self.registry, self.mode)
        except PolicyError as exc:
            raise PlanningError(f"execution policy rejects the plan: {exc}") from exc
        return plan

    # ---- planning --------------------------------------------------------
    def plan(self, prompt: str) -> PlanSpec:
        diagnostics: dict[str, Any] = {"attempts": [], "planner": PLANNER_NAME}
        self.last_diagnostics = diagnostics
        # A request without a bounded event identifier has nothing the
        # contracts can execute; refuse before spending a model call, exactly
        # as the baseline does.
        self.baseline.extract_event(prompt)
        extra = ""
        for attempt in range(self.max_repairs + 1):
            started = time.time()
            try:
                text = self.client.complete(
                    SYSTEM_PROMPT, self._request(prompt, extra), PLAN_JSON_SCHEMA
                )
                plan = self._validate(prompt, text)
            except PlanningError as exc:
                diagnostics["attempts"].append(
                    {
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "seconds": time.time() - started,
                    }
                )
                extra = (
                    "The previous plan was rejected by the validator with this "
                    f"error; return a corrected plan:\n{exc}"
                )
                continue
            diagnostics["attempts"].append(
                {
                    "attempt": attempt + 1,
                    "error": None,
                    "seconds": time.time() - started,
                }
            )
            diagnostics["plan_hash"] = plan_hash(plan)
            return plan
        fallback = self.baseline.plan(prompt)
        reasons = "; ".join(a["error"] for a in diagnostics["attempts"] if a["error"])
        fallback.warnings.append(
            f"LLM plan rejected after {self.max_repairs + 1} attempts ({reasons}); "
            "the deterministic baseline plan was used instead."
        )
        diagnostics["fallback"] = True
        diagnostics["plan_hash"] = plan_hash(fallback)
        return fallback

    def replan(self, prompt: str, manifest: RunManifest) -> PlanSpec | None:
        """One bounded replanning round from a structured observation."""
        observation = observe(manifest)
        failures = {
            t: o["error"] for t, o in observation["tasks"].items() if o["error"]
        }
        if not failures:
            return None
        extra = (
            "The previous run of this request failed. Observation:\n"
            + json.dumps(observation, indent=1, default=str)
            + "\nReturn a corrected plan that avoids the failure, or the same plan "
            "with a warning if the failure is external and a rerun is appropriate."
        )
        try:
            text = self.client.complete(
                SYSTEM_PROMPT, self._request(prompt, extra), PLAN_JSON_SCHEMA
            )
            plan = self._validate(prompt, text)
        except PlanningError as exc:
            self.last_diagnostics["replan_error"] = str(exc)
            return None
        plan.warnings.append(
            f"replanned once after run {manifest.run_id} failed in {sorted(failures)}"
        )
        return plan


def _transitive_dependencies(plan: PlanSpec) -> dict[str, set[str]]:
    direct = {task.id: set(task.depends_on) for task in plan.tasks}
    closure: dict[str, set[str]] = {}

    def resolve(task_id: str, seen: set[str]) -> set[str]:
        if task_id in closure:
            return closure[task_id]
        result: set[str] = set()
        for dep in direct.get(task_id, set()):
            if dep in seen:
                continue  # cycles are rejected by PlanSpec itself
            result.add(dep)
            result |= resolve(dep, seen | {dep})
        closure[task_id] = result
        return result

    for task_id in direct:
        resolve(task_id, {task_id})
    return closure


def _walk(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def baseline_responder(registry: SkillRegistry, config: PlannerConfig):
    """A ReplayClient responder that answers with the baseline plan as JSON.

    It lets the evaluation harness measure the pipeline's own overhead and
    reproducibility without an API key; it is not an LLM.
    """
    baseline = BaselinePlanner(registry, config)

    def respond(system: str, user: str, schema: dict[str, Any]) -> str:
        request, _ = json.JSONDecoder().raw_decode(user)
        try:
            plan = baseline.plan(request["request"])
        except PlanningError as exc:
            return json.dumps(
                {
                    "goal": "refused",
                    "tasks": [
                        {
                            "id": "generate_report",
                            "skill": "report.generate",
                            "parameters": {"title": "Refused request"},
                            "depends_on": [],
                        }
                    ],
                    "warnings": [str(exc)],
                }
            )
        return json.dumps(
            {
                "goal": plan.goal,
                "warnings": plan.warnings,
                "tasks": [
                    {
                        "id": t.id,
                        "skill": t.skill,
                        "parameters": t.parameters,
                        "depends_on": t.depends_on,
                        "when": t.when.model_dump() if t.when else None,
                        "allow_failed_dependencies": t.allow_failed_dependencies,
                    }
                    for t in plan.tasks
                ],
            }
        )

    return respond
