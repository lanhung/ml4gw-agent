"""SSH executor (fake transport) and segmented long-scan submission."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml4gw_agent.executors import (
    ExecutorKind,
    JobHandle,
    JobStatus,
    SSHConfig,
    SSHExecutor,
    build_executors,
    executor_availability,
    submit_plan,
)
from ml4gw_agent.executors.base import Executor, ExecutorError
from ml4gw_agent.executors.submit import scan_interval, segment_plan
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig

CONFIG = PlannerConfig(aframe_revision="a" * 40, amplfi_revision="b" * 40)


class FakeTransport:
    """Records commands; simulates a remote host with a running process."""

    def __init__(self, tmp_path: Path, manifest_status="completed"):
        self.tmp_path = tmp_path
        self.commands: list[str] = []
        self.puts: list[tuple[Path, str]] = []
        self.alive = True
        self.manifest_status = manifest_status
        self.remote_worker: str | None = None

    def run(self, command, timeout=120.0):
        self.commands.append(command)
        if "mkdir -p" in command:
            return 0, "ok\n", ""
        if "nohup" in command:
            return 0, "4242\n", ""
        if "kill -0" in command:
            return 0, ("alive\n" if self.alive else "gone\n"), ""
        if "run_manifest.json" in command:
            return 0, (self.manifest_status + "\n" if self.manifest_status else ""), ""
        if "kill " in command:
            self.alive = False
            return 0, "", ""
        return 0, "", ""

    def put(self, local, remote):
        self.puts.append((Path(local), remote))
        self.remote_worker = remote.rsplit("/", 1)[0] + "/worker"

    def get_tree(self, remote, local):
        run = Path(local) / "run_fake"
        run.mkdir(parents=True, exist_ok=True)
        (run / "run_manifest.json").write_text(
            json.dumps(
                {"run_id": "run_fake", "status": self.manifest_status, "tasks": {}}
            )
        )
        return [run / "run_manifest.json"]


def _executor(tmp_path, **kw):
    config = SSHConfig(
        host="gpu.example",
        port=2338,
        user="root",
        password="pw",
        runs="/r/runs",
        repo="/r/repo",
        env="export X=1",
        python="uv run",
    )
    transport = FakeTransport(tmp_path, **kw)
    return SSHExecutor(transport=transport, config=config), transport


def test_ssh_probe_and_registry(monkeypatch):
    monkeypatch.delenv("ML4GW_SSH_HOST", raising=False)
    executors = build_executors()
    assert ExecutorKind.SSH in executors
    availability = executor_availability(executors)
    assert availability["ssh"].startswith("missing: ML4GW_SSH_HOST")
    assert availability["kubernetes"].startswith("deferred (no cluster")
    monkeypatch.setenv("ML4GW_SSH_HOST", "h")
    assert SSHExecutor().probe().startswith("missing: ML4GW_SSH_PASSWORD")
    monkeypatch.setenv("ML4GW_SSH_KEY", "/k")
    assert SSHExecutor().probe() == "available"


def test_ssh_submit_poll_collect(tmp_path, registry):
    executor, transport = _executor(tmp_path)
    plan = BaselinePlanner(registry, CONFIG).plan("Run Aframe detection on GW150914.")
    submission = submit_plan(
        plan, executor, registry, runs_dir=tmp_path, mode="real", wait=False
    )
    assert submission.job_id == "gpu.example:4242"
    assert transport.puts and transport.puts[0][1].endswith("/plan.json")
    started = [c for c in transport.commands if "nohup" in c][0]
    assert "export X=1 && cd /r/repo && nohup uv run ml4gw-agent run-plan" in started
    assert "--mode real" in started and "/r/runs/plan-" in started
    handle = JobHandle(
        id=submission.job_id,
        executor=ExecutorKind.SSH,
        owner=executor,
        checkpoint=submission.submission_dir
        / "jobs"
        / f"plan-{plan.id}"
        / "handle.json",
    )
    assert executor.poll(handle) == JobStatus.RUNNING
    transport.alive = False
    assert executor.poll(handle) == JobStatus.COMPLETED
    manifests = list(
        (submission.submission_dir / "worker").glob("run_*/run_manifest.json")
    )
    assert manifests, "worker results are copied back after completion"
    # a second poll uses the checkpoint, no more remote calls needed
    n = len(transport.commands)
    assert executor.poll(handle) == JobStatus.COMPLETED and len(transport.commands) == n


def test_ssh_cancel_and_failed_worker(tmp_path, registry):
    executor, transport = _executor(tmp_path, manifest_status="failed")
    plan = BaselinePlanner(registry, CONFIG).plan("Run Aframe detection on GW150914.")
    submission = submit_plan(
        plan, executor, registry, runs_dir=tmp_path, mode="real", wait=False
    )
    handle = JobHandle(
        id=submission.job_id,
        executor=ExecutorKind.SSH,
        owner=executor,
        checkpoint=submission.submission_dir
        / "jobs"
        / f"plan-{plan.id}"
        / "handle.json",
    )
    assert executor.cancel(handle) == JobStatus.CANCELLED
    assert any("kill 4242" in c for c in transport.commands)
    assert executor.poll(handle) == JobStatus.CANCELLED

    executor2, transport2 = _executor(tmp_path / "b", manifest_status="failed")
    submission2 = submit_plan(
        plan, executor2, registry, runs_dir=tmp_path / "b", mode="real", wait=False
    )
    handle2 = JobHandle(
        id=submission2.job_id,
        executor=ExecutorKind.SSH,
        owner=executor2,
        checkpoint=submission2.submission_dir
        / "jobs"
        / f"plan-{plan.id}"
        / "handle.json",
    )
    transport2.alive = False
    assert executor2.poll(handle2) == JobStatus.FAILED
    with pytest.raises(ExecutorError, match="plan_file"):
        executor2.submit("x", lambda: None, run_dir=tmp_path, description={})


# ---- segmentation -----------------------------------------------------------


class FakeBatch(Executor):
    """Batch executor that writes a worker manifest with candidates."""

    kind = ExecutorKind.HTCONDOR

    def __init__(self, fail_segment: int | None = None):
        self.descriptions: list[dict] = []
        self.fail_segment = fail_segment

    def probe(self):
        return "available"

    def submit(self, job_id, work, *, run_dir, description=None):
        self.descriptions.append(description)
        return JobHandle(
            id=f"job{len(self.descriptions)}", executor=self.kind, owner=self
        )

    def poll(self, handle):
        index = int(handle.id[3:]) - 1
        description = self.descriptions[index]
        plan = json.loads(Path(description["plan_file"]).read_text())
        fetch = next(t for t in plan["tasks"] if t["skill"] == "data.fetch")
        params = fetch["parameters"]
        window = float(params["window_seconds"])
        try:
            start = float(params["gps_time"])
        except ValueError:  # unsegmented plan still references resolve_event
            start = float(params["event"]) - params["event_offset_fraction"] * window
        worker = Path(description["runs_dir"]) / "run_fake"
        worker.mkdir(parents=True, exist_ok=True)
        if index == self.fail_segment:
            (worker / "run_manifest.json").write_text(
                json.dumps({"run_id": "r", "status": "failed", "tasks": {}})
            )
            return JobStatus.FAILED
        # one candidate every 100 s of data, including in the overlaps, so a
        # candidate near a boundary is reported by both neighbours
        times = [
            t
            for t in range(int(start) - int(start) % 100, int(start + window) + 1, 100)
            if start <= t < start + window
        ]
        (worker / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "r",
                    "status": "completed",
                    "tasks": {
                        "run_aframe": {
                            "status": "completed",
                            "outputs": {
                                "candidate_times": times,
                                "detection_statistic": 5.0 + index,
                            },
                        }
                    },
                }
            )
        )
        return JobStatus.COMPLETED

    def cancel(self, handle):
        return JobStatus.CANCELLED


def test_scan_interval_and_segment_plan(registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", window_seconds=1000)
    ).plan("Run Aframe detection on 1126259000.")
    assert scan_interval(plan) == (1126259000 - 750.0, 1126259000 + 250.0)
    named = BaselinePlanner(registry, CONFIG).plan("Run Aframe detection on GW150914.")
    assert scan_interval(named) is None
    from ml4gw_agent.executors import partition_scan

    segment = partition_scan(1000.0, 1300.0, 100.0, 8.0)[1]
    clone = segment_plan(plan, segment)
    fetch = {t.id: t for t in clone.tasks}["fetch_data"]
    assert fetch.parameters["gps_time"] == 92.0 + 1000.0
    assert fetch.parameters["window_seconds"] == 116.0
    assert fetch.parameters["event_offset_fraction"] == 0.0
    assert {t.id: t for t in clone.tasks}["run_aframe"].parameters[
        "target_time"
    ] is None
    assert plan.tasks[1].parameters["window_seconds"] == 1000  # original untouched


def test_segmented_submission_covers_without_duplicates(tmp_path, registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", window_seconds=1000)
    ).plan("Run Aframe detection on 1126259000.")
    executor = FakeBatch()
    result = submit_plan(
        plan,
        executor,
        registry,
        runs_dir=tmp_path,
        mode="real",
        poll_interval=0,
        sleep=lambda s: None,
        segment_seconds=300.0,
        max_window_seconds=4096.0,
    )
    assert len(result.segments) == 4 and len(executor.descriptions) == 4
    cores = [(s.core_start, s.core_end) for s in result.segments]
    assert cores[0][0] == 1126258250.0 and cores[-1][1] == 1126259250.0
    assert all(a[1] == b[0] for a, b in zip(cores, cores[1:], strict=False))
    merged = result.merged["run_aframe"]
    assert merged["complete"] and merged["coverage_fraction"] == 1.0
    times = [c["time"] for c in merged["candidates"]]
    assert times == sorted(set(times)), "no duplicates from the 8 s overlaps"
    assert all(1126258250.0 <= t < 1126259250.0 for t in times)
    assert result.status == "completed" and result.manifest["status"] == "completed"
    saved = json.loads((result.submission_dir / "segments.json").read_text())
    assert saved["n_segments"] == 4 and len(saved["submissions"]) == 4


def test_segmented_submission_reports_a_failed_segment(tmp_path, registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", window_seconds=1000)
    ).plan("Run Aframe detection on 1126259000.")
    result = submit_plan(
        plan,
        FakeBatch(fail_segment=2),
        registry,
        runs_dir=tmp_path,
        mode="real",
        poll_interval=0,
        sleep=lambda s: None,
        segment_seconds=250.0,
    )
    assert result.status == "partial" and result.merged["failed_segments"] == [2]
    merged = result.merged["run_aframe"]
    assert merged["missing_segments"] == [2] and not merged["complete"]
    assert 0.74 < merged["coverage_fraction"] < 0.76
    assert result.manifest["runs"][2]["status"] == "failed"


def test_window_above_policy_limit_is_segmented_automatically(tmp_path, registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", window_seconds=1000)
    ).plan("Run Aframe detection on 1126259000.")
    executor = FakeBatch()
    result = submit_plan(
        plan,
        executor,
        registry,
        runs_dir=tmp_path,
        mode="real",
        poll_interval=0,
        sleep=lambda s: None,
        max_window_seconds=400.0,
    )
    assert len(result.segments) == 3
    single = submit_plan(
        plan,
        FakeBatch(),
        registry,
        runs_dir=tmp_path / "single",
        mode="real",
        poll_interval=0,
        sleep=lambda s: None,
        max_window_seconds=4096.0,
    )
    assert not hasattr(single, "segments")
    named = BaselinePlanner(registry, CONFIG).plan("Run Aframe detection on GW150914.")
    with pytest.raises(ExecutorError, match="GPS time"):
        submit_plan(
            named,
            FakeBatch(),
            registry,
            runs_dir=tmp_path / "n",
            mode="real",
            poll_interval=0,
            sleep=lambda s: None,
            segment_seconds=100.0,
        )


# ---- resume, timeout, and merge helpers --------------------------------------


def test_ssh_resume_submission_reuses_checkpoint(tmp_path, registry):
    from ml4gw_agent.executors import resume_submission

    executor, transport = _executor(tmp_path)
    plan = BaselinePlanner(registry, CONFIG).plan("Run Aframe detection on GW150914.")
    submission = submit_plan(
        plan, executor, registry, runs_dir=tmp_path, mode="real", wait=False
    )
    transport.alive = False
    resumed = resume_submission(
        submission.submission_dir, executor, poll_interval=0, sleep=lambda s: None
    )
    assert resumed.job_id == "gpu.example:4242"
    assert resumed.status == "completed" and resumed.manifest["status"] == "completed"
    with pytest.raises(ExecutorError, match="malformed ssh job id"):
        SSHExecutor._parse_id("nohost")
    with pytest.raises(ExecutorError, match="no checkpoint"):
        executor.poll(JobHandle(id="h:1", executor=ExecutorKind.SSH, owner=executor))

    # a worker that vanished without a manifest, and a copy-back that fails
    executor3, transport3 = _executor(tmp_path / "c", manifest_status="")
    transport3.get_tree = lambda remote, local: (_ for _ in ()).throw(OSError("x"))
    submission3 = submit_plan(
        plan, executor3, registry, runs_dir=tmp_path / "c", mode="real", wait=False
    )
    handle3 = JobHandle(
        id=submission3.job_id,
        executor=ExecutorKind.SSH,
        owner=executor3,
        checkpoint=submission3.submission_dir
        / "jobs"
        / f"plan-{plan.id}"
        / "handle.json",
    )
    assert executor3.poll(handle3) == JobStatus.SUBMITTED  # alive, no manifest yet
    transport3.alive = False
    assert executor3.poll(handle3) == JobStatus.FAILED
    assert "could not copy worker results" in handle3.error


class StuckBatch(FakeBatch):
    def __init__(self, status=JobStatus.RUNNING):
        super().__init__()
        self.status = status

    def poll(self, handle):
        return self.status


def test_wait_for_times_out_and_missing_manifest_fails(tmp_path, registry):
    plan = BaselinePlanner(registry, CONFIG).plan("Run Aframe detection on GW150914.")
    stuck = submit_plan(
        plan,
        StuckBatch(),
        registry,
        runs_dir=tmp_path / "stuck",
        mode="real",
        poll_interval=0,
        wait_timeout=-1.0,
        sleep=lambda s: None,
    )
    assert stuck.status == "timeout" and "gave up waiting" in stuck.error
    empty = submit_plan(
        plan,
        StuckBatch(JobStatus.COMPLETED),
        registry,
        runs_dir=tmp_path / "empty",
        mode="real",
        poll_interval=0,
        sleep=lambda s: None,
    )
    assert empty.status == "failed" and "no run manifest" in empty.error


def test_candidates_from_gwak_and_missing_manifests():
    from ml4gw_agent.executors.submit import _candidates

    manifest = {
        "tasks": {
            "run_gwak": {
                "outputs": {"top_segments": [{"time": 5.0, "score": 2.5}, {"time": 9}]}
            }
        }
    }
    assert _candidates(manifest, "run_gwak") == [
        {"time": 5.0, "statistic": 2.5},
        {"time": 9.0, "statistic": 0.0},
    ]
    assert _candidates(None, "run_gwak") == []
    assert _candidates(manifest, "run_other") == []
