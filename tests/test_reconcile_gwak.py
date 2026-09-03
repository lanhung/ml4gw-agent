"""Aframe/GWAK reconciliation and the fail-closed GWAK adapter."""

from __future__ import annotations

import json

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


def _gwak_manifest(tmp_path, embedder=b"embedder-bytes", metric=b"metric-bytes"):
    import hashlib

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "embedder.pt").write_bytes(embedder)
    (model_dir / "metric.pt").write_bytes(metric)
    manifest = {
        "revision": "test-rev",
        "source_commit": "abc",
        "files": {
            "embedder": {
                "path": "embedder.pt",
                "sha256": hashlib.sha256(embedder).hexdigest(),
            },
            "metric": {
                "path": "metric.pt",
                "sha256": hashlib.sha256(metric).hexdigest(),
            },
        },
        "preprocessing": {
            "sample_rate": 4096,
            "kernel_length_seconds": 0.5,
            "psd_length_seconds": 4,
            "fduration_seconds": 1,
            "fftlength_seconds": 2,
            "highpass_hz": 30,
            "stride_seconds": 0.25,
        },
    }
    (model_dir / "MANIFEST.json").write_text(json.dumps(manifest))
    return model_dir


def _gwak_strain(tmp_path, seconds=12.0, rate=4096.0, t0=1000.0):
    import numpy as np

    from ml4gw_agent.adapters.strain_io import StrainData, write_strain

    n = int(seconds * rate)
    rng = np.random.default_rng(3)
    data = StrainData(
        ifos=["H1", "L1"],
        series={"H1": rng.normal(size=n), "L1": rng.normal(size=n)},
        t0=t0,
        sample_rate=rate,
        event_time=t0 + 9.0,
        source="test",
        event="GW150914",
    )
    return write_strain(tmp_path / "artifacts" / "fetch_data_4k" / "strain.hdf5", data)


def _fake_backend(spike_index=7):
    import numpy as np

    from ml4gw_agent.adapters.gwak import GWAKBackend

    class Embedder:
        def __call__(self, kernels):
            return np.zeros((kernels.shape[0], 8))

    class Metric:
        def __call__(self, embeddings):
            log_prob = -np.full(embeddings.shape[0], 12.0)
            log_prob[spike_index] = -40.0  # one very unlikely kernel
            return log_prob

    def load_jit(path, device):
        return Embedder() if "embedder" in path.name else Metric()

    def whiten(strain, sample_rate, psd_length, fduration, fftlength, highpass):
        n_psd = int(psd_length * sample_rate)
        crop = int(fduration * sample_rate / 2)
        return np.asarray(strain)[:, n_psd + crop : -crop]

    return GWAKBackend(
        load_jit=load_jit,
        whiten=whiten,
        to_tensor=lambda a, d: np.asarray(a),
        to_numpy=lambda a: np.asarray(a),
        seed=lambda s: None,
    )


def test_gwak_adapter_scores_kernels_and_maps_times(registry, tmp_path, monkeypatch):
    import json as _json

    assert PYTHON_ADAPTERS["gwak_snakemake"] is GWAKAdapter
    model_dir = _gwak_manifest(tmp_path)
    path = _gwak_strain(tmp_path)
    monkeypatch.setattr("ml4gw_agent.adapters.gwak._missing", lambda: [])
    monkeypatch.setattr("ml4gw_agent.adapters.gwak.load_gwak_backend", _fake_backend)
    params = {
        "strain_artifact": str(path.relative_to(tmp_path)),
        "model_revision": "test-rev",
        "model_dir": str(model_dir),
        "top_k": 3,
        "threshold": 20.0,
        "device": "cpu",
    }
    context = ExecutionContext(
        skill=registry.get("gwak.scan"),
        task=TaskSpec(id="run_gwak", skill="gwak.scan", parameters=params),
        parameters=params,
        run_dir=tmp_path,
        mode="real",
        records={},
        prompt="test",
    )
    adapter = GWAKAdapter()
    assert any(
        "uncalibrated" in w or "calibrated" in w for w in adapter.preflight(context)
    )
    outcome = adapter.execute(context)
    out = outcome.outputs
    assert out["anomaly_found"] is True and out["max_score"] == 40.0
    assert out["simulated"] is False and out["threshold_calibrated"] is False
    # analysis starts after the 4 s PSD and the 0.5 s filter crop; kernel 7 at
    # stride 0.25 s has its centre at 4.5 + 7*0.25 + 0.25 s after t0
    assert out["top_segments"][0]["time"] == 1000.0 + 4.5 + 7 * 0.25 + 0.25
    assert out["top_segments"][0]["score"] == 40.0
    assert len(out["top_segments"]) == 3
    assert out["n_kernels"] == int((12 - 4 - 1 - 0.5) / 0.25) + 1
    assert (tmp_path / out["anomaly_artifact"]).exists()
    _json.dumps(out)  # JSON-serialisable outputs

    below = dict(params, threshold=100.0)
    context2 = ExecutionContext(
        skill=registry.get("gwak.scan"),
        task=TaskSpec(id="run_gwak", skill="gwak.scan", parameters=below),
        parameters=below,
        run_dir=tmp_path,
        mode="real",
        records={},
        prompt="test",
    )
    assert adapter.execute(context2).outputs["anomaly_found"] is False


def test_gwak_adapter_refuses_wrong_revision_hash_and_rate(
    registry, tmp_path, monkeypatch
):
    from ml4gw_agent.errors import AdapterError

    model_dir = _gwak_manifest(tmp_path)
    path = _gwak_strain(tmp_path)
    monkeypatch.setattr("ml4gw_agent.adapters.gwak._missing", lambda: [])
    monkeypatch.setattr("ml4gw_agent.adapters.gwak.load_gwak_backend", _fake_backend)

    def ctx(**over):
        params = {
            "strain_artifact": str(path.relative_to(tmp_path)),
            "model_revision": "test-rev",
            "model_dir": str(model_dir),
            "device": "cpu",
        }
        params.update(over)
        return ExecutionContext(
            skill=registry.get("gwak.scan"),
            task=TaskSpec(id="run_gwak", skill="gwak.scan", parameters=params),
            parameters=params,
            run_dir=tmp_path,
            mode="real",
            records={},
            prompt="test",
        )

    with pytest.raises(AdapterError, match="does not match"):
        GWAKAdapter().preflight(ctx(model_revision="other"))
    (model_dir / "metric.pt").write_bytes(b"tampered")
    with pytest.raises(AdapterError, match="sha256"):
        GWAKAdapter().preflight(ctx())
    (model_dir / "metric.pt").write_bytes(b"metric-bytes")
    slow = _gwak_strain(tmp_path / "slow", rate=2048.0)
    with pytest.raises(AdapterError, match="4096"):
        GWAKAdapter().execute(ctx(strain_artifact=str(slow.relative_to(tmp_path))))
    monkeypatch.setattr("ml4gw_agent.adapters.gwak._missing", lambda: ["torch"])
    assert GWAKAdapter().probe().startswith("missing")
    with pytest.raises(AdapterUnavailableError):
        GWAKAdapter().preflight(ctx())


def test_planner_fetches_a_4k_copy_for_gwak(registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", gwak_revision="c")
    ).plan("Run Aframe and GWAK on GW150914 and reconcile the two results.")
    by_id = {t.id: t for t in plan.tasks}
    assert by_id["fetch_data_4k"].parameters["sample_rate"] == 4096
    assert by_id["fetch_data"].parameters["sample_rate"] == 2048
    assert by_id["run_gwak"].parameters["strain_artifact"].startswith("${fetch_data_4k")
    assert "fetch_data_4k" in by_id["run_gwak"].depends_on


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
    monkeypatch.setenv("ML4GW_GWAK_MODEL_DIR", str(tmp_path / "nowhere"))
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="real")
    assert manifest.status == RunStatus.BLOCKED
    assert any("GWAK" in w for w in manifest.warnings)
