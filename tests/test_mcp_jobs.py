"""Job isolation, persistence and failure semantics without the optional SDK."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from ml4gw_agent import mcp_jobs
from ml4gw_agent.mcp_jobs import (
    AnalysisConfig,
    Job,
    JobService,
    ServiceConfig,
    ServiceError,
)
from ml4gw_agent.models import PlanSpec, RunManifest, RunStatus, TaskStatus
from ml4gw_agent.provenance import write_manifest
from ml4gw_agent.runtime import AgentRuntime


@pytest.fixture
def service(tmp_path):
    service = JobService(ServiceConfig(tmp_path / "service"))
    yield service
    service.close()


def wait_for_job(service, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        view = service.get_run(job_id)
        if view["status"] not in {"starting", "running"}:
            return view
        time.sleep(0.02)
    pytest.fail("worker did not finish")


@pytest.mark.parametrize(
    "prompt",
    [
        "Analyze GW150914",
        "Run Aframe and AMPLFI on GW150914",
        "Run Aframe and GWAK on GW150914",
    ],
)
def test_saved_plan_matches_direct_runtime(service, tmp_path, prompt):
    planned = service.plan_analysis(prompt)
    plan = PlanSpec.model_validate(planned["plan"])
    started = service.start_analysis(planned["plan_id"])
    view = wait_for_job(service, started["job_id"])
    assert view["status"] == "completed"
    assert "SIMULATED" in view["report"]
    direct = AgentRuntime(service.registry).run(plan, runs_dir=tmp_path / "direct")
    assert view["tasks"].keys() == direct.tasks.keys()
    for key, task in direct.tasks.items():
        assert view["tasks"][key]["status"] == task.status.value
        assert view["tasks"][key]["outputs"] == task.outputs
        # Reports contain timestamps/run ids; scientific artifacts are deterministic.
        if task.skill != "report.generate":
            assert view["tasks"][key]["artifacts"] == [
                a.model_dump() for a in task.artifacts
            ]
    assert all(
        Path(a["path"]).is_file() and len(a["sha256"]) == 64 for a in view["artifacts"]
    )
    service.close()
    restarted = JobService(service.config)
    try:
        assert restarted.get_run(started["job_id"])["report"] == view["report"]
        assert restarted.start_analysis(plan.id)["mode"] == "mock"
    finally:
        restarted.close()


def test_guards_and_single_owner(service):
    assert len(service.list_skills()["skills"]) == 12
    with pytest.raises(ServiceError, match="SERVICE_BUSY"):
        JobService(service.config)
    for identifier, code in [
        ("../x", "INVALID_ID"),
        ("plan_000000000000", "UNKNOWN_PLAN"),
    ]:
        with pytest.raises(ServiceError, match=code):
            service.start_analysis(identifier)
    with pytest.raises(ServiceError, match="UNKNOWN_JOB"):
        service.get_run("job_000000000000")
    with pytest.raises(ServiceError, match="REAL_DISABLED"):
        service.plan_analysis("Analyze GW150914", mode="real")
    with pytest.raises(ServiceError, match="INVALID_MODE"):
        service.plan_analysis("Analyze GW150914", mode="shell")
    for config in [
        {"allow_real": True},
        {"runs_dir": "/tmp"},
        {"window_seconds": float("nan")},
        {"device": "arbitrary"},
    ]:
        with pytest.raises(ValidationError):
            AnalysisConfig.model_validate(config)
    with pytest.raises(ValueError):
        ServiceConfig(service.root, max_gpu_hours=float("inf"))


def test_plan_checksum_budget_and_real_permissions(service, tmp_path):
    planned = service.plan_analysis("Analyze GW150914")
    path = service.root / "plans" / planned["plan_id"] / "plan.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ServiceError, match="INVALID_PLAN"):
        service.start_analysis(planned["plan_id"])
    zero = JobService(ServiceConfig(tmp_path / "zero", max_gpu_hours=0))
    try:
        planned = zero.plan_analysis("Analyze GW150914")
        assert planned["budget"]["allowed"] is False
        with pytest.raises(ServiceError, match="BUDGET_EXCEEDED"):
            zero.start_analysis(planned["plan_id"])
    finally:
        zero.close()
    real = JobService(ServiceConfig(tmp_path / "real", allow_real=True))
    try:
        with pytest.raises(mcp_jobs.ML4GWAgentError, match="revision"):
            real.plan_analysis("Analyze GW150914", mode="real")
        planned = real.plan_analysis(
            "Analyze GW150914",
            AnalysisConfig(aframe_revision="a" * 40, amplfi_revision="b" * 40),
            "real",
        )
    finally:
        real.close()
    disabled = JobService(ServiceConfig(tmp_path / "real"))
    try:
        with pytest.raises(ServiceError, match="REAL_DISABLED"):
            disabled.start_analysis(planned["plan_id"])
    finally:
        disabled.close()


def replace_worker(monkeypatch, code):
    popen = subprocess.Popen

    def launch(command, **kwargs):
        assert command[1:4] == ["-m", "ml4gw_agent", "run-plan"]
        assert kwargs["shell"] is False
        assert (
            kwargs["stdout"] == kwargs["stderr"]
            or kwargs["stderr"] == subprocess.STDOUT
        )
        return popen([sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr(mcp_jobs.subprocess, "Popen", launch)


def test_busy_cancel_and_shutdown_preserve_records(service, monkeypatch):
    replace_worker(monkeypatch, "import time; time.sleep(60)")
    planned = service.plan_analysis("Analyze GW150914")
    job = service.start_analysis(planned["plan_id"])
    assert service.get_run(job["job_id"])["status"] == "running"
    with pytest.raises(ServiceError, match="SERVICE_BUSY"):
        service.start_analysis(planned["plan_id"])
    # A partially completed record survives cancellation; only unfinished tasks change.
    plan = PlanSpec.model_validate(planned["plan"])
    manifest = AgentRuntime(service.registry).run(
        plan, runs_dir=service.root / "jobs" / job["job_id"] / "runs"
    )
    manifest.status = RunStatus.RUNNING
    manifest.tasks["generate_report"].status = TaskStatus.RUNNING
    path = Path(manifest.run_directory) / "run_manifest.json"
    write_manifest(manifest, path)
    process = service._process
    assert service.cancel_run(job["job_id"])["status"] == "cancelled"
    assert process.poll() is not None
    view = service.get_run(job["job_id"])
    assert view["tasks"]["generate_report"]["status"] == "cancelled"
    assert view["tasks"]["analyze_event"]["status"] == "completed"
    assert view["report"]
    assert service.cancel_run(job["job_id"])["status"] == "cancelled"
    second = service.start_analysis(planned["plan_id"])
    service.close()
    assert (
        json.loads((service.root / "jobs" / second["job_id"] / "job.json").read_text())[
            "status"
        ]
        == "cancelled"
    )
    with pytest.raises(ServiceError, match="SERVICE_CLOSED"):
        service.start_analysis(planned["plan_id"])


def test_child_crash_and_spawn_failure(service, monkeypatch):
    replace_worker(monkeypatch, "raise SystemExit(17)")
    planned = service.plan_analysis("Analyze GW150914")
    job = service.start_analysis(planned["plan_id"])
    view = wait_for_job(service, job["job_id"])
    assert view["status"] == "failed" and view["returncode"] == 17
    assert "PROCESS_EXIT" in view["error"]

    def fail(*args, **kwargs):
        raise OSError("unavailable executable")

    monkeypatch.setattr(mcp_jobs.subprocess, "Popen", fail)
    job = service.start_analysis(planned["plan_id"])
    assert job["status"] == "failed" and "PROCESS_START_FAILED" in job["error"]


def test_restart_marks_unfinished_job_interrupted(service):
    planned = service.plan_analysis("Analyze GW150914")
    job = Job(
        job_id="job_000000000001",
        plan_id=planned["plan_id"],
        mode="mock",
        status="running",
    )
    service._job_path(job.job_id).mkdir()
    service._save_job(job)
    service.close()
    restarted = JobService(service.config)
    try:
        view = restarted.get_run(job.job_id)
        assert view["status"] == "interrupted"
        assert "SERVER_RESTARTED" in view["error"]
        assert restarted._process is None
    finally:
        restarted.close()


def test_real_job_records_missing_runtime(tmp_path, monkeypatch):
    # No Buoy executable, regardless of optional science packages on the host.
    monkeypatch.setenv("PATH", "")
    service = JobService(ServiceConfig(tmp_path, allow_real=True))
    try:
        plan = service.plan_analysis(
            "Analyze GW150914",
            AnalysisConfig(aframe_revision="a" * 40, amplfi_revision="b" * 40),
            mode="real",
        )
        job = service.start_analysis(plan["plan_id"])
        view = wait_for_job(service, job["job_id"])
        assert view["mode"] == "real" and view["status"] == "blocked"
        assert "requires the 'buoy' executable" in view["error"]
        assert all(t["attempts"] == 0 for t in view["tasks"].values())
    finally:
        service.close()


def test_missing_model_is_a_blocked_runtime_record(tmp_path, monkeypatch):
    # Pretend dependencies are installed, so the real GWAK preflight reaches
    # the absent manifest. No scientific backend is loaded or executed.
    popen = subprocess.Popen

    def launch(command, **kwargs):
        script = (
            "import sys; from ml4gw_agent.adapters import gwosc, gwak; "
            "gwosc.missing_modules = lambda names: []; gwak._missing = lambda: []; "
            "from ml4gw_agent.cli import main; raise SystemExit(main(sys.argv[1:]))"
        )
        return popen([sys.executable, "-c", script, *command[3:]], **kwargs)

    monkeypatch.setattr(mcp_jobs.subprocess, "Popen", launch)
    monkeypatch.setenv("ML4GW_GWAK_MODEL_DIR", str(tmp_path / "absent_models"))
    service = JobService(ServiceConfig(tmp_path / "service", allow_real=True))
    try:
        plan = service.plan_analysis(
            "Run GWAK on GW150914",
            AnalysisConfig(
                gwak_revision="gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad"
            ),
            mode="real",
        )
        job = service.start_analysis(plan["plan_id"])
        view = wait_for_job(service, job["job_id"])
        assert view["status"] == "blocked"
        assert "MANIFEST.json" in view["error"]
        assert all(t["attempts"] == 0 for t in view["tasks"].values())
    finally:
        service.close()


def test_cli_mcp_missing_sdk_and_clean_shutdown(tmp_path, monkeypatch, capsys):
    from ml4gw_agent import mcp_server
    from ml4gw_agent.cli import main

    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "mcp.server", None)
        assert main(["mcp", "--runs-dir", str(tmp_path)]) == 2
        assert "uv sync --extra mcp" in capsys.readouterr().err

    class Server:
        def run(self, transport):
            assert transport == "stdio"
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(mcp_server, "create_server", lambda service: Server())
    previous = signal.getsignal(signal.SIGTERM)
    assert main(["mcp", "--runs-dir", str(tmp_path)]) == 0
    assert signal.getsignal(signal.SIGTERM) == previous
    service = JobService(ServiceConfig(tmp_path))  # shutdown released the lock
    service.close()


def test_high_risk_approval_is_only_startup_configuration(tmp_path):
    from ml4gw_agent.models import RiskLevel

    for approved in [False, True]:
        service = JobService(
            ServiceConfig(
                tmp_path / str(approved), allow_real=True, approve_high_risk=approved
            )
        )
        # Make the planned skill require approval to exercise the service boundary
        # without needing data/model availability or a scientific computation.
        skill = service.registry.get("buoy.analyze")
        skill.risk, skill.requires_approval = RiskLevel.HIGH, True
        try:
            config = AnalysisConfig(aframe_revision="a" * 40, amplfi_revision="b" * 40)
            if approved:
                assert (
                    service.plan_analysis("Analyze GW150914", config, "real")["mode"]
                    == "real"
                )
            else:
                with pytest.raises(
                    mcp_jobs.ML4GWAgentError, match="high-risk approval"
                ):
                    service.plan_analysis("Analyze GW150914", config, "real")
        finally:
            service.close()


@pytest.mark.parametrize(
    "attack",
    [
        "artifact_escape",
        "artifact_symlink",
        "report_symlink",
        "manifest_escape",
        "modified_artifact",
        "missing_artifact",
        "jobs_symlink",
    ],
)
def test_result_paths_are_confined(service, tmp_path, attack):
    job = service.start_analysis(service.plan_analysis("Analyze GW150914")["plan_id"])
    view = wait_for_job(service, job["job_id"])
    manifest_path = Path(view["manifest_path"])
    manifest = RunManifest.model_validate_json(manifest_path.read_text())
    outside = tmp_path / "private.txt"
    outside.write_text("PRIVATE FILE MUST NEVER BE READ")
    artifact = next(t.artifacts[0] for t in manifest.tasks.values() if t.artifacts)
    target = manifest_path.parent / artifact.relative_path
    if attack == "artifact_escape":
        artifact.relative_path = str(outside)
        write_manifest(manifest, manifest_path)
    elif attack in {"artifact_symlink", "report_symlink"}:
        target = (
            target
            if attack == "artifact_symlink"
            else manifest_path.parent / "report.md"
        )
        target.unlink()
        target.symlink_to(outside)
    elif attack == "manifest_escape":
        manifest.run_directory = str(tmp_path)
        write_manifest(manifest, manifest_path)
    elif attack == "modified_artifact":
        target.write_text("changed")
    elif attack == "missing_artifact":
        target.unlink()
    else:
        (service.root / "jobs").rename(service.root / "old_jobs")
        (service.root / "jobs").symlink_to(
            service.root / "old_jobs", target_is_directory=True
        )
    with pytest.raises(
        ServiceError,
        match="UNSAFE_PATH|INVALID_RECORD|ARTIFACT_CHANGED|MISSING_ARTIFACT",
    ):
        service.get_run(job["job_id"])


def test_cancel_escalates_to_terminate(service, monkeypatch, tmp_path):
    ready = tmp_path / "ready"
    code = (
        "import signal, time; from pathlib import Path; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        f"Path({str(ready)!r}).touch(); time.sleep(60)"
    )
    replace_worker(monkeypatch, code)
    job = service.start_analysis(service.plan_analysis("Analyze GW150914")["plan_id"])
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    assert service.cancel_run(job["job_id"])["returncode"] == -signal.SIGTERM
