"""Regression checks for the execution boundary now exposed through MCP."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from ml4gw_agent.adapters import AdapterOutcome, MockAdapter
from ml4gw_agent.adapters.deepclean import DeepCleanCleanAdapter
from ml4gw_agent.adapters.deepclean_model import Scaler, resample
from ml4gw_agent.capabilities import skill_availability
from ml4gw_agent.errors import AdapterError, PolicyError, RegistryError, ValidationError
from ml4gw_agent.models import (
    AdapterKind,
    ConditionSpec,
    PlanSpec,
    TaskRecord,
    TaskSpec,
    TaskStatus,
)
from ml4gw_agent.policy import ExecutionPolicy
from ml4gw_agent.provenance import record_artifacts
from ml4gw_agent.registry import SkillRegistry
from ml4gw_agent.runtime import AgentRuntime, evaluate_condition, resolve_references


def test_capability_probe_reports_failure_without_executing_science(
    registry, monkeypatch
):
    skill = registry.get("buoy.analyze")
    monkeypatch.setattr("ml4gw_agent.capabilities.shutil.which", lambda _: "/bin/buoy")

    def probe(*args, **kwargs):
        assert args[0] == ["/bin/buoy", "--help"]
        assert kwargs["shell"] is False and kwargs["capture_output"] is True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("ml4gw_agent.capabilities.subprocess.run", probe)
    assert skill_availability(skill, "real") == "available"
    monkeypatch.setattr(
        "ml4gw_agent.capabilities.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=2),
    )
    assert skill_availability(skill, "real") == "broken: exit 2"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("buoy", 60)

    monkeypatch.setattr("ml4gw_agent.capabilities.subprocess.run", timeout)
    assert skill_availability(skill, "real") == "broken: TimeoutExpired"
    skill.adapter.kind, skill.adapter.entrypoint = AdapterKind.PYTHON, "not_registered"
    assert "unregistered" in skill_availability(skill, "real")
    skill.adapter.kind = AdapterKind.PLANNED
    assert skill_availability(skill, "real") == "planned"


@pytest.mark.parametrize(
    "reference,records,message",
    [
        ("${root.anything}", {}, "invalid reference"),
        ("${missing.outputs.x}", {}, "unknown task"),
        (
            "${root.outputs.x}",
            {"root": TaskRecord(task_id="root", skill="data.fetch")},
            "not completed",
        ),
        (
            "${root.outputs.x}",
            {
                "root": TaskRecord(
                    task_id="root", skill="data.fetch", status=TaskStatus.COMPLETED
                )
            },
            "does not exist",
        ),
    ],
)
def test_invalid_output_references_fail_closed(reference, records, message):
    with pytest.raises(ValidationError, match=message):
        resolve_references(reference, records)


def test_condition_type_error_is_a_validation_error():
    record = TaskRecord(
        task_id="root",
        skill="data.fetch",
        status=TaskStatus.COMPLETED,
        outputs={"value": None},
    )
    condition = ConditionSpec(reference="${root.outputs.value}", operator="gt", value=1)
    with pytest.raises(ValidationError, match="could not be evaluated"):
        evaluate_condition(condition, {"root": record})


def test_failed_skipped_and_invalid_condition_tasks_remain_distinct(registry, tmp_path):
    plan = PlanSpec(
        prompt="Analyze GW150914",
        goal="failure propagation",
        tasks=[
            TaskSpec(
                id="root", skill="data.resolve_event", parameters={"event": "GW150914"}
            ),
            TaskSpec(
                id="skip",
                skill="report.generate",
                depends_on=["root"],
                when=ConditionSpec(
                    reference="${root.outputs.catalog_time}", operator="equals", value=0
                ),
            ),
            TaskSpec(id="after_skip", skill="report.generate", depends_on=["skip"]),
            TaskSpec(
                id="invalid_condition",
                skill="report.generate",
                depends_on=["root"],
                when=ConditionSpec(
                    reference="${root.outputs.missing}", operator="truthy"
                ),
            ),
            TaskSpec(id="bad_input", skill="data.fetch", parameters={"ifos": []}),
            TaskSpec(
                id="after_failure", skill="report.generate", depends_on=["bad_input"]
            ),
        ],
    )
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path)
    assert manifest.tasks["skip"].status == TaskStatus.SKIPPED
    assert manifest.tasks["after_skip"].status == TaskStatus.SKIPPED
    assert manifest.tasks["invalid_condition"].status == TaskStatus.BLOCKED
    assert manifest.tasks["bad_input"].status == TaskStatus.FAILED
    assert manifest.tasks["after_failure"].status == TaskStatus.BLOCKED
    condition_only = plan.model_copy(update={"tasks": plan.tasks[:1] + [plan.tasks[3]]})
    assert (
        AgentRuntime(registry).run(condition_only, runs_dir=tmp_path).status.value
        == "blocked"
    )


@pytest.mark.parametrize(
    "failure", ["retry", "exhausted", "invalid_output", "no_output"]
)
def test_adapter_errors_are_recorded_and_retries_are_bounded(
    registry, tmp_path, monkeypatch, failure
):
    class Adapter(MockAdapter):
        attempts = 0

        def execute(self, context):
            self.attempts += 1
            if failure == "exhausted" or (failure == "retry" and self.attempts == 1):
                raise AdapterError("temporary science failure")
            if failure == "invalid_output":
                return AdapterOutcome(outputs={})
            if failure == "no_output":
                return None
            return super().execute(context)

    adapter = Adapter()
    runtime = AgentRuntime(registry)
    monkeypatch.setattr(runtime, "_adapter_for", lambda *args: adapter)
    task = TaskSpec(
        id="fetch",
        skill="data.fetch",
        parameters={"event": "GW150914", "ifos": ["H1", "L1"]},
        max_retries=1,
    )
    plan = PlanSpec(prompt="Fetch GW150914", goal="bounded retry", tasks=[task])
    manifest = runtime.run(plan, runs_dir=tmp_path)
    record = manifest.tasks["fetch"]
    assert record.status.value == ("completed" if failure == "retry" else "failed")
    assert adapter.attempts == (2 if failure in {"retry", "exhausted"} else 1)
    if failure == "no_output":
        assert "no outcome" in record.error


def test_result_cache_reuses_only_within_a_real_run(registry, tmp_path, monkeypatch):
    class Adapter(MockAdapter):
        calls = 0

        def execute(self, context):
            self.calls += 1
            return super().execute(context)

    adapter = Adapter()
    runtime = AgentRuntime(registry)
    monkeypatch.setattr(runtime, "_adapter_for", lambda *args: adapter)
    plan = PlanSpec(
        prompt="Fetch GW150914",
        goal="shared data",
        tasks=[
            TaskSpec(
                id=name,
                skill="data.fetch",
                parameters={"event": "GW150914", "ifos": ["H1", "L1"]},
            )
            for name in ["first", "second"]
        ],
    )
    one = runtime.run(plan, runs_dir=tmp_path, mode="real")
    assert one.tasks["second"].adapter_metadata["result_cache"] == "hit"
    two = runtime.run(plan, runs_dir=tmp_path, mode="real")
    assert adapter.calls == 2
    assert one.run_directory != two.run_directory


def test_unknown_adapter_is_blocked_without_importing_arbitrary_code(
    registry, tmp_path
):
    registry.get("data.fetch").adapter.entrypoint = "os.system"
    plan = PlanSpec(
        prompt="Fetch GW150914",
        goal="unknown adapter",
        tasks=[TaskSpec(id="fetch", skill="data.fetch")],
    )
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="real")
    assert manifest.status.value == "blocked"
    assert "unknown python adapter" in manifest.tasks["fetch"].error


def test_policy_limits_and_deferred_references(registry):
    params = {"window_seconds": 5000, "samples": 200000}
    plan = PlanSpec(
        prompt="Fetch GW150914",
        goal="policy bounds",
        tasks=[TaskSpec(id="fetch", skill="data.fetch", parameters=params)],
    )
    with pytest.raises(PolicyError, match="data window"):
        ExecutionPolicy().validate(plan, registry, "real")
    with pytest.raises(PolicyError, match="plan has"):
        ExecutionPolicy(max_tasks=0).validate(plan, registry, "mock")
    for reference in [
        "${root.outputs.value}",
        ["${root.outputs.value}"],
        {"nested": "${root.outputs.value}"},
    ]:
        plan.tasks[0].parameters = {"window_seconds": reference}
        assert ExecutionPolicy().validate(plan, registry, "mock") == []
    registry.get("data.fetch").adapter.kind = AdapterKind.PLANNED
    with pytest.raises(PolicyError, match="no real adapter"):
        ExecutionPolicy().validate(plan, registry, "real")


def test_registry_corruption_and_artifact_boundary(registry, tmp_path):
    with pytest.raises(RegistryError, match="does not exist"):
        SkillRegistry.from_directory(tmp_path / "missing")
    with pytest.raises(RegistryError, match="no skill manifests"):
        SkillRegistry.from_directory(tmp_path)
    (tmp_path / "bad.yaml").write_text("name: invalid\n")
    with pytest.raises(RegistryError, match="invalid skill manifest"):
        SkillRegistry.from_directory(tmp_path)
    with pytest.raises(RegistryError, match="unknown skill"):
        registry.get("absent.skill")
    root = tmp_path / "run"
    root.mkdir()
    artifact = root / "artifact"
    artifact.write_bytes(b"payload")
    assert len(record_artifacts([artifact, artifact], root)) == 1
    for path, message in [
        (tmp_path / "bad.yaml", "escaped"),
        (root / "missing", "not a regular file"),
    ]:
        with pytest.raises(ValidationError, match=message):
            record_artifacts([path], root)
    link = root / "link"
    link.symlink_to(artifact)
    with pytest.raises(ValidationError, match="symbolic-link"):
        record_artifacts([link], root)


def test_preprocessing_scaler_and_resampling_are_reproducible_without_torch():
    signal = np.sin(2 * np.pi * 10 * np.arange(1024) / 1024)
    for rate in [256, 2048, 1000]:
        result = resample(signal, 1024, rate)
        assert len(result) == rate and np.isfinite(result).all()
        assert np.sqrt(np.mean(result**2)) == pytest.approx(2**-0.5, abs=0.01)
    scaler = Scaler().fit(signal[None])
    normalized = scaler(signal[None])
    assert np.allclose(scaler.inverse(normalized), signal[None])
    assert np.allclose(Scaler.from_state(scaler.state())(signal[None]), normalized)


def test_deepclean_availability_requires_dependencies_and_model_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.deepclean.util.find_spec", lambda name: None
    )
    assert DeepCleanCleanAdapter().probe() == "missing: torch, ml4gw"
    monkeypatch.setattr(
        "ml4gw_agent.adapters.deepclean.util.find_spec", lambda name: object()
    )
    monkeypatch.setenv("ML4GW_DEEPCLEAN_MODEL_DIR", str(tmp_path / "absent"))
    assert "model directory" in DeepCleanCleanAdapter().probe()
    monkeypatch.setenv("ML4GW_DEEPCLEAN_MODEL_DIR", str(tmp_path))
    assert DeepCleanCleanAdapter().probe() == "available"
