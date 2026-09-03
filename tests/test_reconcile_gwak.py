"""Aframe/GWAK reconciliation and the fail-closed GWAK adapter."""

from __future__ import annotations

import pytest

from ml4gw_agent.adapters import PYTHON_ADAPTERS
from ml4gw_agent.adapters.base import ExecutionContext
from ml4gw_agent.adapters.builtin import BuiltinAdapter
from ml4gw_agent.adapters.gwak import GWAKAdapter
from ml4gw_agent.errors import AdapterUnavailableError
from ml4gw_agent.models import RunStatus, TaskRecord, TaskSpec, TaskStatus
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.runtime import AgentRuntime


def _record(task_id, status, outputs):
    return TaskRecord(
        task_id=task_id, skill="x", status=status, parameters={}, outputs=outputs
    )


def _reconcile(registry, tmp_path, records):
    params = {"aframe_task": "run_aframe", "gwak_task": "run_gwak"}
    context = ExecutionContext(
        skill=registry.get("analysis.reconcile"),
        task=TaskSpec(id="reconcile", skill="analysis.reconcile", parameters=params),
        parameters=params,
        run_dir=tmp_path,
        mode="real",
        records=records,
        prompt="test",
    )
    return BuiltinAdapter("reconcile_detections").execute(context).outputs


@pytest.mark.parametrize(
    ("aframe", "gwak", "route", "pe"),
    [
        (True, True, "consistent_candidate", True),
        (True, False, "aframe_only", True),
        (False, True, "gwak_only", False),
        (False, False, "consistent_null", False),
    ],
)
def test_reconcile_routes(registry, tmp_path, aframe, gwak, route, pe):
    records = {
        "run_aframe": _record(
            "run_aframe", TaskStatus.COMPLETED, {"candidate_found": aframe}
        ),
        "run_gwak": _record("run_gwak", TaskStatus.COMPLETED, {"anomaly_found": gwak}),
    }
    outputs = _reconcile(registry, tmp_path, records)
    assert outputs["route"] == route
    assert outputs["parameter_estimation_recommended"] is pe
    assert outputs["simulated"] is False
    if route == "gwak_only":
        assert "AMPLFI is not run" in outputs["follow_up"]


def test_reconcile_is_undetermined_when_a_route_did_not_complete(registry, tmp_path):
    records = {
        "run_aframe": _record(
            "run_aframe", TaskStatus.COMPLETED, {"candidate_found": True}
        ),
        "run_gwak": _record("run_gwak", TaskStatus.FAILED, {}),
    }
    outputs = _reconcile(registry, tmp_path, records)
    assert outputs["route"] == "undetermined"
    assert outputs["aframe_candidate"] is True
    assert outputs["gwak_anomaly"] is None
    assert outputs["parameter_estimation_recommended"] is True


def test_gwak_adapter_fails_closed(registry, tmp_path):
    assert PYTHON_ADAPTERS["gwak_snakemake"] is GWAKAdapter
    adapter = GWAKAdapter()
    assert adapter.probe().startswith("missing")
    params = {"strain_artifact": "artifacts/x.hdf5", "model_revision": "sha"}
    context = ExecutionContext(
        skill=registry.get("gwak.scan"),
        task=TaskSpec(id="run_gwak", skill="gwak.scan", parameters=params),
        parameters=params,
        run_dir=tmp_path,
        mode="real",
        records={},
        prompt="test",
    )
    with pytest.raises(AdapterUnavailableError, match="no reviewed inference"):
        adapter.preflight(context)
    with pytest.raises(AdapterUnavailableError):
        adapter.execute(context)


def test_composed_mock_run_reconciles_both_routes(registry, tmp_path):
    plan = BaselinePlanner(
        registry,
        PlannerConfig(aframe_revision="a", amplfi_revision="b", gwak_revision="c"),
    ).plan("Run Aframe and GWAK on GW150914 and reconcile the two results.")
    ids = [task.id for task in plan.tasks]
    assert "reconcile_detections" in ids and "run_amplfi" not in ids
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.COMPLETED
    record = manifest.tasks["reconcile_detections"]
    assert record.status == TaskStatus.COMPLETED
    assert record.outputs["simulated"] is True
    assert record.outputs["route"] in {
        "consistent_candidate",
        "aframe_only",
        "gwak_only",
        "consistent_null",
    }


def test_real_plan_with_gwak_is_blocked_before_execution(
    registry, tmp_path, monkeypatch
):
    # pretend the science stack is present so GWAK is the only blocker
    monkeypatch.setattr("ml4gw_agent.adapters.aframe._missing", lambda: [])
    monkeypatch.setattr("ml4gw_agent.adapters.aframe.shutil.which", lambda _: "x")
    plan = BaselinePlanner(
        registry,
        PlannerConfig(aframe_revision="a", gwak_revision="c"),
    ).plan("Run Aframe and GWAK on GW150914 and reconcile the two results.")
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="real")
    assert manifest.status == RunStatus.BLOCKED
    assert any("GWAK has no reviewed inference" in w for w in manifest.warnings)
