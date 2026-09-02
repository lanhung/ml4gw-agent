import json
from pathlib import Path

import pytest

from ml4gw_agent.adapters.base import SkillAdapter
from ml4gw_agent.models import ConditionSpec, PlanSpec, RunStatus, TaskSpec, TaskStatus
from ml4gw_agent.planning import BaselinePlanner
from ml4gw_agent.runtime import AgentRuntime


def test_mock_buoy_run_creates_manifest_report_and_hashes(registry, tmp_path):
    plan = BaselinePlanner(registry).plan("Analyze GW150914")
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")

    run_dir = Path(manifest.run_directory)
    assert manifest.status == RunStatus.COMPLETED
    assert (run_dir / "run_manifest.json").is_file()
    assert "SIMULATED ORCHESTRATION OUTPUT" in (run_dir / "report.md").read_text()
    assert all(
        record.status == TaskStatus.COMPLETED for record in manifest.tasks.values()
    )
    buoy_record = manifest.tasks["analyze_event"]
    assert buoy_record.outputs["simulated"] is True
    assert buoy_record.artifacts
    assert all(len(artifact.sha256) == 64 for artifact in buoy_record.artifacts)

    saved = json.loads((run_dir / "run_manifest.json").read_text())
    assert saved["status"] == "completed"
    assert saved["run_id"] == manifest.run_id


def test_mock_composed_run_exercises_multiple_skills(registry, tmp_path):
    plan = BaselinePlanner(registry).plan(
        "Analyze GW150914, check data quality, use DeepClean if appropriate, "
        "run Aframe and AMPLFI parameter estimation, then scan anomalies with GWAK."
    )
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.COMPLETED
    assert manifest.tasks["check_deepclean"].outputs["applicable"] is False
    assert manifest.tasks["run_aframe"].status == TaskStatus.COMPLETED
    assert manifest.tasks["run_amplfi"].status == TaskStatus.COMPLETED
    assert manifest.tasks["run_gwak"].status == TaskStatus.COMPLETED


def test_false_condition_skips_task_without_failing_run(registry, tmp_path):
    plan = PlanSpec(
        prompt="Test GW150914",
        goal="exercise a false condition",
        tasks=[
            TaskSpec(
                id="resolve_event",
                skill="data.resolve_event",
                parameters={"event": "GW150914"},
            ),
            TaskSpec(
                id="conditional_report",
                skill="report.generate",
                parameters={"title": "will not run"},
                depends_on=["resolve_event"],
                when=ConditionSpec(
                    reference="${resolve_event.outputs.delegated_resolution}",
                    operator="truthy",
                ),
            ),
        ],
    )
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.COMPLETED
    assert manifest.tasks["conditional_report"].status == TaskStatus.SKIPPED


def test_real_run_is_blocked_before_execution_when_unpinned(registry, tmp_path):
    plan = BaselinePlanner(registry).plan("Analyze GW150914")
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="real")
    assert manifest.status == RunStatus.BLOCKED
    assert all(record.attempts == 0 for record in manifest.tasks.values())
    assert any("revision" in warning for warning in manifest.warnings)


def test_failed_dependency_still_allows_audit_report(registry, tmp_path):
    plan = PlanSpec(
        prompt="Test GW150914",
        goal="exercise failure reporting",
        tasks=[
            TaskSpec(
                id="bad_fetch",
                skill="data.fetch",
                parameters={"event": "GW150914", "ifos": []},
            ),
            TaskSpec(
                id="audit_report",
                skill="report.generate",
                parameters={"title": "partial report"},
                depends_on=["bad_fetch"],
                allow_failed_dependencies=True,
            ),
        ],
    )
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.FAILED
    assert manifest.tasks["bad_fetch"].status == TaskStatus.FAILED
    assert manifest.tasks["audit_report"].status == TaskStatus.COMPLETED
    assert Path(manifest.run_directory, "report.md").exists()


def test_high_risk_skill_can_be_exercised_safely_in_mock_mode(registry, tmp_path):
    plan = PlanSpec(
        prompt="Mock DeepClean for GPS 1187008882.4",
        goal="test a simulated high-risk adapter",
        tasks=[
            TaskSpec(
                id="mock_clean",
                skill="deepclean.clean",
                parameters={
                    "strain_artifact": "input/mock-strain.hdf5",
                    "witness_artifact": "input/mock-witness.hdf5",
                    "coupling_config": "config/mock.yaml",
                    "model_revision": "mock-revision",
                    "ifo": "H1",
                },
            )
        ],
    )
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.COMPLETED
    assert manifest.tasks["mock_clean"].outputs["simulated"] is True
    assert any("high-risk skill is simulated" in item for item in manifest.warnings)


def test_operator_interrupt_is_checkpointed_as_cancelled(
    registry, tmp_path, monkeypatch
):
    class CancellingAdapter(SkillAdapter):
        def execute(self, context):
            raise KeyboardInterrupt

    plan = PlanSpec(
        prompt="Fetch GW150914 strain data",
        goal="exercise cancellation",
        tasks=[
            TaskSpec(
                id="fetch_data",
                skill="data.fetch",
                parameters={"event": "GW150914", "ifos": ["H1", "L1"]},
            )
        ],
    )
    runtime = AgentRuntime(registry)
    monkeypatch.setattr(runtime, "_adapter_for", lambda *args: CancellingAdapter())
    with pytest.raises(KeyboardInterrupt):
        runtime.run(plan, runs_dir=tmp_path, mode="mock")

    manifest_path = next(tmp_path.glob("run_*/run_manifest.json"))
    saved = json.loads(manifest_path.read_text())
    assert saved["status"] == "cancelled"
    assert saved["tasks"]["fetch_data"]["status"] == "cancelled"
