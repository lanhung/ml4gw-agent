import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ml4gw_agent.adapters.base import ExecutionContext
from ml4gw_agent.adapters.buoy import BuoyCLIAdapter
from ml4gw_agent.errors import AdapterError, AdapterUnavailableError
from ml4gw_agent.models import TaskRecord, TaskSpec
from ml4gw_agent.planning import BaselinePlanner
from ml4gw_agent.validation import validate_outputs


def _buoy_context(registry, tmp_path, event="GW150914"):
    task = BaselinePlanner(registry).plan("Analyze GW150914").tasks[1]
    parameters = dict(task.parameters)
    parameters["event"] = event
    return ExecutionContext(
        run_dir=tmp_path,
        mode="real",
        task=TaskSpec(
            id=task.id,
            skill=task.skill,
            parameters=parameters,
            depends_on=task.depends_on,
        ),
        skill=registry.get("buoy.analyze"),
        parameters=parameters,
        records={
            "analyze_event": TaskRecord(task_id="analyze_event", skill="buoy.analyze")
        },
        prompt="Analyze GW150914",
    )


def test_buoy_command_is_an_argument_vector(registry, tmp_path):
    context = _buoy_context(registry, tmp_path)
    command = BuoyCLIAdapter().build_command(context, tmp_path / "out")
    assert command[:3] == ["buoy", "--events", "GW150914"]
    assert "--outdir" in command
    assert command[command.index("--ifos") + 1] == '["H1", "L1"]'
    assert all(";" not in item for item in command)


def test_buoy_preflight_rejects_command_injection_event(
    registry, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.shutil.which", lambda _: "/usr/bin/fake"
    )
    context = _buoy_context(registry, tmp_path, "GW150914;touch_bad")
    with pytest.raises(AdapterError, match="unsupported event"):
        BuoyCLIAdapter().preflight(context)


def test_buoy_preflight_reports_cpu_and_unpinned_warnings(
    registry, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.shutil.which", lambda _: "/usr/bin/fake"
    )
    context = _buoy_context(registry, tmp_path)
    context.parameters["device"] = "cpu"
    warnings = BuoyCLIAdapter().preflight(context)
    assert any("15 minutes" in warning for warning in warnings)
    assert any("Aframe" in warning for warning in warnings)
    assert any("AMPLFI" in warning for warning in warnings)


def test_buoy_preflight_requires_executable(registry, tmp_path, monkeypatch):
    monkeypatch.setattr("ml4gw_agent.adapters.buoy.shutil.which", lambda _: None)
    with pytest.raises(AdapterUnavailableError, match="requires the 'buoy'"):
        BuoyCLIAdapter().preflight(_buoy_context(registry, tmp_path))


def test_buoy_python_preflight_requires_package(registry, tmp_path, monkeypatch):
    context = _buoy_context(registry, tmp_path)
    context.parameters["runner"] = "python"
    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.importlib.util.find_spec", lambda _: None
    )
    with pytest.raises(AdapterUnavailableError, match="Python runner"):
        BuoyCLIAdapter().preflight(context)


def test_buoy_python_preflight_warns_about_isolation(registry, tmp_path, monkeypatch):
    context = _buoy_context(registry, tmp_path)
    context.parameters["runner"] = "python"
    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.importlib.util.find_spec", lambda _: object()
    )
    warnings = BuoyCLIAdapter().preflight(context)
    assert any("without subprocess isolation" in warning for warning in warnings)


def test_buoy_execute_collects_outputs_without_shell(registry, tmp_path, monkeypatch):
    context = _buoy_context(registry, tmp_path)

    def fake_run(command, **kwargs):
        assert kwargs["shell"] is False
        kwargs["stdout"].write("ok\n")
        output_root = command[command.index("--outdir") + 1]
        event_dir = tmp_path / output_root / "GW150914"
        data_dir = event_dir / "data"
        plots_dir = event_dir / "plots"
        data_dir.mkdir(parents=True)
        plots_dir.mkdir()
        (data_dir / "aframe_outputs.hdf5").write_bytes(b"not-real-hdf5")
        (data_dir / "posterior_samples.dat").write_text("sample\n")
        (plots_dir / "aframe_response.png").write_bytes(b"png")
        (event_dir / "summary.html").write_text("<html></html>")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("ml4gw_agent.adapters.buoy.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.importlib.metadata.version", lambda _: "9.9"
    )
    outcome = BuoyCLIAdapter().execute(context)
    assert outcome.outputs["event"] == "GW150914"
    assert outcome.outputs["simulated"] is False
    assert outcome.outputs["posterior_samples"].endswith("posterior_samples.dat")
    assert outcome.metadata["buoy_package_version"] == "9.9"
    assert any(path.name == "summary.html" for path in outcome.artifacts)


def test_buoy_python_runner_collects_outputs(registry, tmp_path, monkeypatch):
    context = _buoy_context(registry, tmp_path)
    context.parameters["runner"] = "python"
    fake_module = ModuleType("buoy.main")

    def fake_main(**kwargs):
        event_dir = kwargs["outdir"] / "GW150914"
        data_dir = event_dir / "data"
        plots_dir = event_dir / "plots"
        data_dir.mkdir(parents=True)
        plots_dir.mkdir()
        (data_dir / "aframe_outputs.hdf5").write_bytes(b"not-real-hdf5")
        (data_dir / "posterior_samples.dat").write_text("sample\n")
        (event_dir / "summary.html").write_text("<html></html>")
        print("python runner completed")

    fake_module.main = fake_main
    monkeypatch.setitem(sys.modules, "buoy.main", fake_module)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.importlib.metadata.version", lambda _: "9.9"
    )
    outcome = BuoyCLIAdapter().execute(context)
    assert outcome.outputs["simulated"] is False
    assert outcome.command is None
    assert outcome.metadata["python_call"] == "buoy.main.main"
    assert outcome.metadata["hard_timeout_enforced"] is False
    assert (
        "python runner completed"
        in (tmp_path / "logs" / "analyze_event.stdout.log").read_text()
    )


def test_buoy_execute_records_nonzero_exit(registry, tmp_path, monkeypatch):
    def failed_process(*args, **kwargs):
        kwargs["stdout"].write("partial")
        kwargs["stderr"].write("failed")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(
        "ml4gw_agent.adapters.buoy.subprocess.run",
        failed_process,
    )
    with pytest.raises(AdapterError, match="code 7"):
        BuoyCLIAdapter().execute(_buoy_context(registry, tmp_path))
    assert (tmp_path / "logs" / "analyze_event.stderr.log").read_text() == "failed"


def test_buoy_execute_records_timeout(registry, tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        kwargs["stdout"].write("partial")
        kwargs["stderr"].write("late")
        raise subprocess.TimeoutExpired(args[0], timeout=1)

    monkeypatch.setattr("ml4gw_agent.adapters.buoy.subprocess.run", timeout)
    with pytest.raises(AdapterError, match="timed out"):
        BuoyCLIAdapter().execute(_buoy_context(registry, tmp_path))
    assert (tmp_path / "logs" / "analyze_event.stdout.log").read_text() == "partial"


def test_output_validation_rejects_path_escape(registry, tmp_path):
    outside = tmp_path.parent / "outside-report.md"
    outside.write_text("outside")
    checks = validate_outputs(
        registry.get("report.generate"),
        {"report_path": "../outside-report.md", "simulated": True},
        tmp_path,
    )
    assert any(not check.passed for check in checks)


def test_buoy_execute_records_detectors_actually_used(registry, tmp_path, monkeypatch):
    """Buoy ignores --ifos for catalog events; the manifest must say what ran."""
    import h5py

    context = _buoy_context(registry, tmp_path)

    def fake_run(command, **kwargs):
        assert command[command.index("--ifos") + 1] == '["H1", "L1"]'
        kwargs["stdout"].write("ok\n")
        output_root = command[command.index("--outdir") + 1]
        data_dir = tmp_path / output_root / "GW150914" / "data"
        data_dir.mkdir(parents=True)
        with h5py.File(data_dir / "GW150914.hdf5", "w") as handle:
            for ifo in ("V1", "H1", "L1"):
                handle.create_dataset(ifo, data=[0.0, 1.0])
        (data_dir / "aframe_outputs.hdf5").write_bytes(b"not-real-hdf5")
        (data_dir / "posterior_samples.dat").write_text("sample\n")
        (data_dir / "amplfi_HLV.fits").write_bytes(b"fits")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("ml4gw_agent.adapters.buoy.subprocess.run", fake_run)
    outcome = BuoyCLIAdapter().execute(context)
    assert outcome.outputs["detectors_used"] == ["H1", "L1", "V1"]
    assert outcome.outputs["amplfi_network"] == "HLV"
    assert len(outcome.warnings) == 1
    assert "ignoring --ifos" in outcome.warnings[0]


def test_buoy_execute_without_strain_cache_reports_unknown_detectors(
    registry, tmp_path, monkeypatch
):
    context = _buoy_context(registry, tmp_path)

    def fake_run(command, **kwargs):
        kwargs["stdout"].write("ok\n")
        output_root = command[command.index("--outdir") + 1]
        data_dir = tmp_path / output_root / "GW150914" / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "aframe_outputs.hdf5").write_bytes(b"not-real-hdf5")
        (data_dir / "posterior_samples.dat").write_text("sample\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("ml4gw_agent.adapters.buoy.subprocess.run", fake_run)
    outcome = BuoyCLIAdapter().execute(context)
    assert outcome.outputs["detectors_used"] is None
    assert outcome.outputs["amplfi_network"] is None
    assert outcome.warnings == []
