from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from .adapters import (
    PYTHON_ADAPTERS,
    BuiltinAdapter,
    BuoyCLIAdapter,
    ExecutionContext,
    MockAdapter,
)
from .adapters.base import SkillAdapter
from .errors import (
    AdapterError,
    AdapterUnavailableError,
    ML4GWAgentError,
    ValidationError,
)
from .models import (
    AdapterKind,
    PlanSpec,
    RunManifest,
    RunStatus,
    TaskRecord,
    TaskStatus,
    ValidationRecord,
    new_identifier,
    utc_now,
)
from .policy import ExecutionPolicy
from .provenance import record_artifacts, runtime_environment, write_manifest
from .registry import SkillRegistry
from .validation import validate_inputs, validate_outputs

REFERENCE_PATTERN = re.compile(
    r"^\$\{([a-z][a-z0-9_]*)\.outputs\.([A-Za-z_][A-Za-z0-9_.]*)\}$"
)


def _lookup_output(records: dict[str, TaskRecord], reference: str) -> Any:
    match = REFERENCE_PATTERN.fullmatch(reference)
    if not match:
        raise ValidationError(
            f"invalid reference '{reference}'; only exact task output references "
            "are allowed"
        )
    task_id, dotted_path = match.groups()
    if task_id not in records:
        raise ValidationError(f"reference uses unknown task '{task_id}'")
    record = records[task_id]
    if record.status != TaskStatus.COMPLETED:
        raise ValidationError(
            f"reference task '{task_id}' is {record.status.value}, not completed"
        )
    value: Any = record.outputs
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValidationError(f"reference '{reference}' does not exist")
        value = value[key]
    return value


def resolve_references(value: Any, records: dict[str, TaskRecord]) -> Any:
    if isinstance(value, str) and value.startswith("${"):
        return _lookup_output(records, value)
    if isinstance(value, list):
        return [resolve_references(item, records) for item in value]
    if isinstance(value, dict):
        return {key: resolve_references(item, records) for key, item in value.items()}
    return value


def evaluate_condition(condition: Any, records: dict[str, TaskRecord]) -> bool:
    actual = _lookup_output(records, condition.reference)
    expected = condition.value
    operations = {
        "exists": lambda: actual is not None,
        "equals": lambda: actual == expected,
        "not_equals": lambda: actual != expected,
        "truthy": lambda: bool(actual),
        "gt": lambda: actual > expected,
        "gte": lambda: actual >= expected,
        "lt": lambda: actual < expected,
        "lte": lambda: actual <= expected,
    }
    try:
        return bool(operations[condition.operator]())
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(
            f"condition could not be evaluated: {condition.reference} "
            f"{condition.operator} {expected!r}"
        ) from exc


class AgentRuntime:
    def __init__(
        self,
        registry: SkillRegistry,
        policy: ExecutionPolicy | None = None,
    ):
        self.registry = registry
        self.policy = policy or ExecutionPolicy()

    def _adapter_for(self, skill_name: str, mode: str) -> SkillAdapter:
        skill = self.registry.get(skill_name)
        if skill.adapter.kind == AdapterKind.BUILTIN:
            return BuiltinAdapter(skill.adapter.entrypoint)
        if mode == "mock":
            return MockAdapter()
        if skill.adapter.kind == AdapterKind.BUOY_CLI:
            return BuoyCLIAdapter(skill.adapter.entrypoint)
        if skill.adapter.kind == AdapterKind.PYTHON:
            try:
                return PYTHON_ADAPTERS[skill.adapter.entrypoint]()
            except KeyError as exc:
                raise AdapterUnavailableError(
                    f"{skill.name} names unknown python adapter entrypoint "
                    f"'{skill.adapter.entrypoint}'"
                ) from exc
        raise AdapterUnavailableError(
            f"{skill.name} has no real adapter in this release"
        )

    def preflight(
        self,
        plan: PlanSpec,
        mode: Literal["mock", "real"],
        run_dir: Path,
        records: dict[str, TaskRecord] | None = None,
    ) -> list[str]:
        self.registry.validate_plan_skills(plan)
        warnings = self.policy.validate(plan, self.registry, mode)
        records = records or {
            task.id: TaskRecord(task_id=task.id, skill=task.skill)
            for task in plan.tasks
        }
        for task in plan.topological_order():
            adapter = self._adapter_for(task.skill, mode)
            context = ExecutionContext(
                run_dir=run_dir,
                mode=mode,
                task=task,
                skill=self.registry.get(task.skill),
                parameters=task.parameters,
                records=records,
                prompt=plan.prompt,
            )
            warnings.extend(adapter.preflight(context))
        return list(dict.fromkeys(warnings))

    def run(
        self,
        plan: PlanSpec,
        *,
        runs_dir: Path,
        mode: Literal["mock", "real"] = "mock",
    ) -> RunManifest:
        run_id = new_identifier("run")
        run_dir = runs_dir.resolve() / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        records = {
            task.id: TaskRecord(
                task_id=task.id,
                skill=task.skill,
                parameters=task.parameters,
            )
            for task in plan.tasks
        }
        manifest = RunManifest(
            run_id=run_id,
            mode=mode,
            status=RunStatus.PENDING,
            plan=plan,
            tasks=records,
            run_directory=str(run_dir),
            warnings=list(plan.warnings),
            environment=runtime_environment(),
        )
        manifest_path = run_dir / "run_manifest.json"
        write_manifest(manifest, manifest_path)

        try:
            warnings = self.preflight(plan, mode, run_dir, records)
            manifest.warnings.extend(warnings)
        except ML4GWAgentError as exc:
            manifest.status = RunStatus.BLOCKED
            manifest.warnings.append(str(exc))
            for record in manifest.tasks.values():
                record.status = TaskStatus.BLOCKED
                record.error = str(exc)
                record.ended_at = utc_now()
            manifest.ended_at = utc_now()
            manifest.warnings = list(dict.fromkeys(manifest.warnings))
            write_manifest(manifest, manifest_path)
            return manifest

        manifest.status = RunStatus.RUNNING
        write_manifest(manifest, manifest_path)

        for task in plan.topological_order():
            record = manifest.tasks[task.id]
            failed_dependencies = [
                dependency
                for dependency in task.depends_on
                if manifest.tasks[dependency].status
                in {TaskStatus.FAILED, TaskStatus.BLOCKED}
            ]
            skipped_dependencies = [
                dependency
                for dependency in task.depends_on
                if manifest.tasks[dependency].status == TaskStatus.SKIPPED
            ]
            if failed_dependencies and not task.allow_failed_dependencies:
                record.status = TaskStatus.BLOCKED
                record.error = "failed or blocked dependencies: " + ", ".join(
                    failed_dependencies
                )
                record.ended_at = utc_now()
                write_manifest(manifest, manifest_path)
                continue
            if skipped_dependencies and not task.allow_failed_dependencies:
                record.status = TaskStatus.SKIPPED
                record.error = "skipped dependencies: " + ", ".join(
                    skipped_dependencies
                )
                record.ended_at = utc_now()
                write_manifest(manifest, manifest_path)
                continue

            if task.when is not None:
                try:
                    should_run = evaluate_condition(task.when, manifest.tasks)
                except ValidationError as exc:
                    record.status = TaskStatus.BLOCKED
                    record.error = str(exc)
                    record.ended_at = utc_now()
                    write_manifest(manifest, manifest_path)
                    continue
                record.validations.append(
                    ValidationRecord(
                        check="task_condition",
                        passed=should_run,
                        message=(
                            "condition evaluated true"
                            if should_run
                            else "condition evaluated false; task skipped"
                        ),
                    )
                )
                if not should_run:
                    record.status = TaskStatus.SKIPPED
                    record.ended_at = utc_now()
                    write_manifest(manifest, manifest_path)
                    continue

            record.started_at = utc_now()
            record.status = TaskStatus.RUNNING
            write_manifest(manifest, manifest_path)
            try:
                parameters = resolve_references(task.parameters, manifest.tasks)
                record.parameters = parameters
                skill = self.registry.get(task.skill)
                input_check = validate_inputs(skill, parameters)
                record.validations.append(input_check)
                if not input_check.passed:
                    raise ValidationError(input_check.message)

                adapter = self._adapter_for(task.skill, mode)
                context = ExecutionContext(
                    run_dir=run_dir,
                    mode=mode,
                    task=task,
                    skill=skill,
                    parameters=parameters,
                    records=manifest.tasks,
                    prompt=plan.prompt,
                )
                manifest.warnings.extend(adapter.preflight(context))
                command, adapter_metadata = adapter.describe_invocation(context)
                record.command = command
                record.adapter_metadata = adapter_metadata
                write_manifest(manifest, manifest_path)

                outcome = None
                for attempt in range(task.max_retries + 1):
                    record.attempts = attempt + 1
                    try:
                        outcome = adapter.execute(context)
                        break
                    except AdapterError:
                        if attempt >= task.max_retries:
                            raise
                if outcome is None:
                    raise AdapterError("adapter returned no outcome")

                record.outputs = outcome.outputs
                if outcome.command is not None:
                    record.command = outcome.command
                record.adapter_metadata.update(outcome.metadata)
                manifest.warnings.extend(outcome.warnings)
                output_checks = validate_outputs(skill, outcome.outputs, run_dir)
                record.validations.extend(output_checks)
                failed_checks = [check for check in output_checks if not check.passed]
                if failed_checks:
                    raise ValidationError(
                        "; ".join(check.message for check in failed_checks)
                    )
                record.artifacts = record_artifacts(outcome.artifacts, run_dir)
                record.status = TaskStatus.COMPLETED
            except ML4GWAgentError as exc:
                record.status = TaskStatus.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
            except KeyboardInterrupt:
                record.status = TaskStatus.CANCELLED
                record.error = "Execution cancelled by operator"
                record.ended_at = utc_now()
                manifest.status = RunStatus.CANCELLED
                manifest.ended_at = utc_now()
                write_manifest(manifest, manifest_path)
                raise
            except Exception as exc:  # pragma: no cover - last-resort audit boundary
                record.status = TaskStatus.FAILED
                record.error = f"Unexpected {type(exc).__name__}: {exc}"
            finally:
                record.ended_at = utc_now()
                manifest.warnings = list(dict.fromkeys(manifest.warnings))
                write_manifest(manifest, manifest_path)

        statuses = {record.status for record in manifest.tasks.values()}
        if TaskStatus.FAILED in statuses:
            manifest.status = RunStatus.FAILED
        elif TaskStatus.CANCELLED in statuses:
            manifest.status = RunStatus.CANCELLED
        elif TaskStatus.BLOCKED in statuses:
            manifest.status = RunStatus.BLOCKED
        else:
            manifest.status = RunStatus.COMPLETED
        manifest.ended_at = utc_now()
        manifest.warnings = list(dict.fromkeys(manifest.warnings))
        write_manifest(manifest, manifest_path)
        return manifest
