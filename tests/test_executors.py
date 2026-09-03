"""Phase 4: executors, estimates, budgets, partitioning (fake schedulers only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ml4gw_agent.cli import main
from ml4gw_agent.errors import AdapterError, AdapterUnavailableError
from ml4gw_agent.executors import (
    BudgetPolicy,
    CommandResult,
    CommandRunner,
    EstimateConfig,
    ExecutorError,
    ExecutorKind,
    HTCondorExecutor,
    JobHandle,
    JobStatus,
    KubernetesExecutor,
    LocalExecutor,
    ResourceEstimate,
    ResultCache,
    RetryPolicy,
    build_executors,
    cache_key,
    estimate_plan,
    executor_availability,
    merge_segment_outputs,
    partition_scan,
    select_executor,
)
from ml4gw_agent.executors.htcondor import parse_cluster_id
from ml4gw_agent.executors.kubernetes import render_job_manifest
from ml4gw_agent.models import RunStatus
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.runtime import AgentRuntime


class FakeRunner(CommandRunner):
    """Scripted scheduler: records argv, replies from a queue."""

    def __init__(self, binaries, replies):
        self.binaries = set(binaries)
        self.replies = list(replies)
        self.calls: list[list[str]] = []

    def run(self, argv, *, timeout=120.0):
        assert isinstance(argv, list) and all(isinstance(p, str) for p in argv)
        self.calls.append(list(argv))
        code, out, err = self.replies.pop(0)
        return CommandResult(argv=list(argv), returncode=code, stdout=out, stderr=err)

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.binaries else None


# ----------------------------------------------------------------- partition


@pytest.mark.parametrize(
    ("start", "end", "segment", "overlap"),
    [(0, 100, 30, 0), (1e9, 1e9 + 4096 * 3 + 17, 4096, 64), (5, 6, 10, 2)],
)
def test_partition_covers_range_exactly_once(start, end, segment, overlap):
    segments = partition_scan(start, end, segment, overlap)
    assert segments[0].core_start == start
    assert segments[-1].core_end == end
    for previous, current in zip(segments, segments[1:], strict=False):
        assert previous.core_end == current.core_start  # no gap, no overlap
    assert sum(s.core_duration for s in segments) == pytest.approx(end - start)
    for s in segments:
        assert s.data_start <= s.core_start and s.data_end >= s.core_end
        assert s.core_start - s.data_start <= overlap
        assert s.data_end - s.core_end <= overlap
        assert s.data_start >= start and s.data_end <= end


def test_partition_rejects_bad_arguments():
    with pytest.raises(ValueError):
        partition_scan(10, 5, 1)
    with pytest.raises(ValueError):
        partition_scan(0, 5, 0)
    with pytest.raises(ValueError):
        partition_scan(0, 5, 1, -1)


def test_merge_drops_overlap_duplicates_and_reports_missing_segments():
    segments = partition_scan(0, 300, 100, 10)
    # segment 0 and 1 both see a candidate at t=105 (inside 1's core, in 0's
    # padding); segment 2 never reported
    outputs = {
        0: {
            "candidates": [
                {"time": 50.0, "statistic": 3.0},
                {"time": 105.0, "statistic": 4.0},
            ]
        },
        1: {
            "candidates": [
                {"time": 105.0, "statistic": 4.5},
                {"time": 105.4, "statistic": 2.0},
                {"time": 150.0, "statistic": 1.0},
            ]
        },
    }
    merged = merge_segment_outputs(segments, outputs)
    times = [c["time"] for c in merged["candidates"]]
    assert times == [50.0, 105.0, 150.0]
    assert merged["candidates"][1]["statistic"] == 4.5
    assert merged["candidates"][1]["segment"] == 1
    assert merged["missing_segments"] == [2]
    assert merged["complete"] is False
    assert merged["coverage_fraction"] == pytest.approx(2 / 3)
    with pytest.raises(ValueError, match="unknown segment"):
        merge_segment_outputs(segments, {7: {"candidates": []}})


def test_merge_is_complete_when_every_segment_reports():
    segments = partition_scan(0, 40, 10)
    merged = merge_segment_outputs(
        segments, {s.index: {"candidates": []} for s in segments}
    )
    assert merged["complete"] and merged["missing_segments"] == []


# ------------------------------------------------------------------ estimate


def test_estimate_single_event_is_small_and_records_basis(registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", amplfi_revision="b")
    ).plan("Fetch strain data for GW150914 and run Aframe and AMPLFI.")
    estimate = estimate_plan(plan, registry)
    assert estimate.n_segments == 1
    assert 0 < estimate.gpu_hours < 0.05
    assert estimate.transfer_gb == 0.0
    assert estimate.memory_gb >= 16
    assert {row["skill"] for row in estimate.per_task} >= {"aframe.detect", "amplfi.pe"}
    assert any("RTX 5000 Ada" in a for a in estimate.assumptions)


def test_estimate_models_uncached_transfer_and_cpu_fallback(registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", amplfi_revision="b")
    ).plan("Fetch strain data for GW150914 and run Aframe and AMPLFI.")
    cached = estimate_plan(plan, registry, EstimateConfig())
    uncached = estimate_plan(plan, registry, EstimateConfig(data_cached=False))
    assert uncached.transfer_gb == pytest.approx(0.26)
    assert uncached.expected_latency_seconds > cached.expected_latency_seconds + 3000
    cpu_only = estimate_plan(plan, registry, EstimateConfig(gpu_available=False))
    assert cpu_only.gpu_hours == 0.0
    assert cpu_only.cpu_hours > cached.cpu_hours


def test_estimate_partitions_long_windows(registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", window_seconds=3 * 4096.0)
    ).plan("Run Aframe detection on GW150914.")
    estimate = estimate_plan(plan, registry, EstimateConfig(segment_seconds=4096))
    assert estimate.n_segments == 3
    aframe = next(r for r in estimate.per_task if r["skill"] == "aframe.detect")
    assert aframe["seconds"] == pytest.approx(5.0 * 3 * 4096 / 128)


# -------------------------------------------------------------------- budget


def test_budget_policy_refuses_and_requires_authorization():
    policy = BudgetPolicy()
    assert policy.check(ResourceEstimate(gpu_hours=0.01)).allowed
    over = policy.check(
        ResourceEstimate(
            cpu_hours=100, gpu_hours=10, transfer_gb=50, expected_latency_seconds=1e6
        )
    )
    assert not over.allowed and len(over.reasons) == 5
    assert over.authorization_required
    pending = policy.check(ResourceEstimate(gpu_hours=2.0))
    assert not pending.allowed and pending.authorization_required
    granted = BudgetPolicy(authorized=True).check(ResourceEstimate(gpu_hours=2.0))
    assert granted.allowed and granted.authorization_required
    assert policy.as_dict()["max_gpu_hours"] == 4.0


# ----------------------------------------------------------- base contracts


def test_retry_policy_backoff_and_cache_key_stability():
    policy = RetryPolicy(max_attempts=3, backoff_seconds=10)
    assert [policy.delay_before(n) for n in (1, 2, 3)] == [0.0, 10.0, 20.0]
    a = cache_key("aframe.detect", "0.2.0", {"b": 1, "a": [1, 2]}, "x")
    b = cache_key("aframe.detect", "0.2.0", {"a": [1, 2], "b": 1}, "x")
    assert a == b and len(a) == 64
    assert cache_key("aframe.detect", "0.2.1", {"a": [1, 2], "b": 1}, "x") != a
    cache = ResultCache()
    cache.put(a, "value")
    assert cache.get(a) == "value" and cache.get("nope") is None and len(cache) == 1


def test_local_executor_runs_in_process_and_records_failures(tmp_path):
    executor = LocalExecutor()
    assert executor.probe() == "available"
    handle = executor.submit("job-1", lambda: 42, run_dir=tmp_path)
    assert handle.result == 42 and handle.poll() == JobStatus.COMPLETED
    assert handle.checkpoint == tmp_path / "run_manifest.json"
    assert handle.cancel() == JobStatus.COMPLETED  # finished jobs keep state

    def boom():
        raise AdapterError("nope")

    with pytest.raises(AdapterError):
        executor.submit("job-2", boom, run_dir=tmp_path)
    detached = JobHandle(id="x", executor=ExecutorKind.LOCAL)
    assert detached.cancel() == JobStatus.CANCELLED
    with pytest.raises(ExecutorError):
        detached.resume()


# ------------------------------------------------------------------ htcondor


def test_htcondor_probe_fails_closed_without_binaries():
    executor = HTCondorExecutor(FakeRunner([], []))
    assert executor.probe().startswith("missing")
    with pytest.raises(AdapterUnavailableError, match="condor_submit"):
        executor.submit("j", lambda: None, run_dir=Path("/tmp"))


def test_htcondor_submit_poll_cancel_with_fake_scheduler(tmp_path):
    runner = FakeRunner(
        ["condor_submit", "condor_q", "condor_rm", "ml4gw-agent"],
        [
            (0, "123.0 - 123.0\n", ""),
            (0, json.dumps([{"JobStatus": 2}]), ""),
            (0, json.dumps([{"JobStatus": 4, "ExitCode": 0}]), ""),
            (0, "", ""),
            (0, "All jobs marked for removal", ""),
        ],
    )
    executor = HTCondorExecutor(runner)
    assert executor.probe() == "available"
    with pytest.raises(ExecutorError, match="plan_file"):
        executor.submit("seg0", lambda: None, run_dir=tmp_path)
    handle = executor.submit(
        "seg0",
        lambda: None,
        run_dir=tmp_path,
        description={
            "plan_file": tmp_path / "plan.json",
            "mode": "real",
            "cpus": 4,
            "memory_gb": 16,
            "gpus": 1,
            "extra": {"requirements": "(HasGPU == True)"},
        },
    )
    assert handle.id == "123" and handle.status == JobStatus.SUBMITTED
    submit = (tmp_path / "jobs" / "seg0" / "job.sub").read_text()
    assert "executable = /usr/bin/ml4gw-agent" in submit
    assert "arguments = run-plan" in submit and "--mode real" in submit
    assert "request_gpus = 1" in submit and "request_memory = 16384MB" in submit
    assert "requirements = (HasGPU == True)" in submit and "queue 1" in submit
    assert runner.calls[0] == [
        "condor_submit",
        "-terse",
        str(tmp_path / "jobs" / "seg0" / "job.sub"),
    ]
    assert (tmp_path / "jobs" / "seg0" / "handle.json").exists()
    assert handle.poll() == JobStatus.RUNNING
    assert handle.poll() == JobStatus.COMPLETED
    assert handle.resume().status == JobStatus.COMPLETED  # empty queue
    assert handle.cancel() == JobStatus.CANCELLED
    assert runner.calls[-1] == ["condor_rm", "123"]


def test_htcondor_failure_paths():
    with pytest.raises(ExecutorError, match="cluster id"):
        parse_cluster_id("garbage")
    runner = FakeRunner(
        ["condor_submit", "condor_q", "condor_rm"],
        [
            (1, "", "permission denied"),
            (0, json.dumps([{"JobStatus": 4, "ExitCode": 3}]), ""),
            (0, "not json", ""),
            (2, "", "no such job"),
        ],
    )
    executor = HTCondorExecutor(runner)
    with pytest.raises(ExecutorError, match="permission denied"):
        executor.submit(
            "s", lambda: None, run_dir=Path("/tmp"), description={"plan_file": "p"}
        )
    handle = JobHandle(id="9", executor=ExecutorKind.HTCONDOR, owner=executor)
    assert handle.poll() == JobStatus.FAILED and "code 3" in handle.error
    with pytest.raises(ExecutorError, match="invalid JSON"):
        handle.poll()
    with pytest.raises(ExecutorError, match="no such job"):
        handle.cancel()


# ---------------------------------------------------------------- kubernetes


def test_kubernetes_manifest_probe_and_lifecycle(tmp_path):
    with pytest.raises(ExecutorError, match="invalid Kubernetes job name"):
        render_job_manifest(
            name="Bad_Name", image="i", arguments=[], cpus=1, memory_gb=1, gpus=0
        )
    assert KubernetesExecutor(FakeRunner([], [])).probe().startswith("missing: kubectl")
    assert (
        KubernetesExecutor(FakeRunner(["kubectl"], []))
        .probe()
        .startswith("missing: no pinned")
    )
    runner = FakeRunner(
        ["kubectl"],
        [
            (0, "job.batch/ml4gw-seg-0 created", ""),
            (0, json.dumps({"status": {"active": 1}}), ""),
            (0, json.dumps({"status": {"succeeded": 1}}), ""),
            (0, json.dumps({"status": {"failed": 1}}), ""),
            (1, "", 'Error from server (NotFound): jobs.batch "x" not found'),
            (0, "job.batch deleted", ""),
        ],
    )
    executor = KubernetesExecutor(runner, image="ghcr.io/x/ml4gw-agent:0.3.0")
    assert executor.probe() == "available"
    handle = executor.submit(
        "seg_0",
        lambda: None,
        run_dir=tmp_path,
        description={"plan_file": "plan.json", "gpus": 1, "cpus": 2, "memory_gb": 8},
    )
    assert handle.id == "ml4gw-seg-0"
    manifest = yaml.safe_load((tmp_path / "jobs" / "seg_0" / "job.yaml").read_text())
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "ghcr.io/x/ml4gw-agent:0.3.0"
    assert container["args"][:2] == ["run-plan", "plan.json"]
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert runner.calls[0][:3] == ["kubectl", "apply", "-f"]
    assert handle.poll() == JobStatus.RUNNING
    assert handle.poll() == JobStatus.COMPLETED
    assert handle.poll() == JobStatus.FAILED
    assert handle.poll() == JobStatus.COMPLETED  # gone from the API server
    assert handle.cancel() == JobStatus.CANCELLED
    assert runner.calls[-1][:3] == ["kubectl", "delete", "job"]


# ------------------------------------------------------ registry + selection


def test_registry_probes_and_selection_rules():
    executors = build_executors(FakeRunner([], []))
    availability = executor_availability(executors)
    assert availability["local"] == "available"
    assert availability["htcondor"].startswith("missing")
    assert availability["snakemake"].startswith("planned")
    with pytest.raises(AdapterUnavailableError, match="planned"):
        executors[ExecutorKind.TRITON].submit("j", lambda: None, run_dir=Path("/tmp"))

    short = ResourceEstimate(expected_latency_seconds=60, n_segments=1)
    assert select_executor(short, executors).kind == ExecutorKind.LOCAL
    scan = ResourceEstimate(expected_latency_seconds=60, n_segments=12)
    fallback = select_executor(scan, executors)
    assert fallback.kind == ExecutorKind.LOCAL
    assert "no batch scheduler" in fallback.reason

    with_condor = build_executors(
        FakeRunner(["condor_submit", "condor_q", "condor_rm"], [])
    )
    chosen = select_executor(scan, with_condor)
    assert chosen.kind == ExecutorKind.HTCONDOR and "12 segments" in chosen.reason
    slow = ResourceEstimate(expected_latency_seconds=3 * 3600, n_segments=1)
    assert select_executor(slow, with_condor).kind == ExecutorKind.HTCONDOR
    explicit = select_executor(scan, with_condor, preference="local")
    assert (
        explicit.kind == ExecutorKind.LOCAL
        and explicit.reason == "requested explicitly"
    )
    with pytest.raises(ValueError, match="unusable"):
        select_executor(scan, executors, preference="kubernetes")


# ------------------------------------------------------- runtime integration


def test_runtime_records_execution_and_enforces_budget(registry, tmp_path):
    plan = BaselinePlanner(registry).plan("Analyze GW150914")
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.COMPLETED
    execution = manifest.execution
    assert execution is not None and execution.executor == "local"
    assert execution.decision["allowed"] is True
    assert execution.estimate["n_segments"] == 1
    assert [job["status"] for job in execution.jobs] == ["completed"] * 3
    saved = json.loads((Path(manifest.run_directory) / "run_manifest.json").read_text())
    assert saved["execution"]["executor"] == "local"

    tight = BudgetPolicy(max_gpu_hours=1e-9, require_authorization_above_gpu_hours=1e-9)
    blocked = AgentRuntime(registry, budget=tight).run(
        plan, runs_dir=tmp_path, mode="mock"
    )
    assert blocked.status == RunStatus.BLOCKED
    assert any("execution budget" in w for w in blocked.warnings)
    assert all(record.status.value == "blocked" for record in blocked.tasks.values())


def test_runtime_refuses_unavailable_executor(registry, tmp_path):
    plan = BaselinePlanner(registry).plan("Analyze GW150914")
    executor = HTCondorExecutor(FakeRunner([], []))
    manifest = AgentRuntime(registry, executor=executor).run(
        plan, runs_dir=tmp_path, mode="mock"
    )
    assert manifest.status == RunStatus.BLOCKED
    assert any("executor htcondor is not available" in w for w in manifest.warnings)


def test_old_manifests_without_execution_still_validate():
    from ml4gw_agent.models import RunManifest

    payload = {
        "mode": "mock",
        "plan": {
            "prompt": "p",
            "goal": "g",
            "tasks": [{"id": "a", "skill": "report.generate"}],
        },
        "tasks": {},
        "run_directory": "/tmp/x",
    }
    assert RunManifest.model_validate(payload).execution is None


# ----------------------------------------------------------------------- cli


def test_cli_estimate_and_run_flags(capsys, tmp_path):
    assert main(["estimate", "Analyze GW150914", "--no-cache"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selection"]["executor"] == "local"
    assert payload["estimate"]["transfer_gb"] > 0
    assert payload["decision"]["allowed"] is True
    assert main(["estimate", "Analyze GW150914", "--max-gpu-hours", "0"]) == 3
    refused = json.loads(capsys.readouterr().out)
    assert refused["decision"]["allowed"] is False
    assert (
        main(
            [
                "run",
                "Analyze GW150914",
                "--mode",
                "mock",
                "--runs-dir",
                str(tmp_path),
                "--executor",
                "local",
                "--max-gpu-hours",
                "2",
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(summary["manifest"]).read_text())
    assert saved["execution"]["budget"]["max_gpu_hours"] == 2.0


def test_accounting_attributes_come_from_the_environment(monkeypatch, tmp_path):
    from ml4gw_agent.executors.htcondor import render_submit_description

    monkeypatch.setenv("ML4GW_CONDOR_ACCOUNTING_GROUP", "ligo.dev.o4.cbc.explore.test")
    monkeypatch.setenv("ML4GW_CONDOR_ACCOUNTING_USER", "fan.zhang")
    monkeypatch.setenv("ML4GW_CONDOR_EXTRA", '{"+MaxHours": "2"}')
    text = render_submit_description(
        executable="/bin/true",
        arguments=["x"],
        job_dir=tmp_path,
        cpus=1,
        memory_gb=1,
        gpus=1,
    )
    assert "accounting_group = ligo.dev.o4.cbc.explore.test" in text
    assert "accounting_group_user = fan.zhang" in text
    assert "+MaxHours = 2" in text
    assert text.strip().endswith("queue 1")
    assert "getenv" not in text  # forbidden on IGWN pools
    assert "request_disk = 4096MB" in text
    monkeypatch.setenv("GWPY_CACHE", "1")
    monkeypatch.setenv("ML4GW_NODE_PASSWORD", "never")
    monkeypatch.setenv("HOME", "/home/x")
    text = render_submit_description(
        executable="/bin/true",
        arguments=["x"],
        job_dir=tmp_path,
        cpus=1,
        memory_gb=1,
        gpus=0,
    )
    line = next(line for line in text.splitlines() if line.startswith("environment = "))
    assert (
        "GWPY_CACHE='1'" in line and "ML4GW_CONDOR_ACCOUNTING_USER='fan.zhang'" in line
    )
    assert "never" not in line and "HOME=" not in line


def test_submit_plan_round_trip_with_a_fake_batch_executor(tmp_path, registry):
    import json

    from ml4gw_agent.executors import ExecutorKind, JobHandle, JobStatus, submit_plan
    from ml4gw_agent.executors.base import Executor
    from ml4gw_agent.planning import BaselinePlanner, PlannerConfig

    class FakeBatch(Executor):
        kind = ExecutorKind.HTCONDOR

        def __init__(self):
            self.descriptions = []
            self.polls = 0

        def probe(self):
            return "available"

        def submit(self, job_id, work, *, run_dir, description=None):
            self.descriptions.append(description)
            return JobHandle(id="4242", executor=self.kind, owner=self)

        def poll(self, handle):
            self.polls += 1
            if self.polls < 3:
                return JobStatus.RUNNING
            # the "worker" writes a manifest into the requested runs dir
            worker = Path(self.descriptions[0]["runs_dir"]) / "run_fake"
            worker.mkdir(parents=True, exist_ok=True)
            (worker / "run_manifest.json").write_text(
                json.dumps({"run_id": "run_fake", "status": "completed", "tasks": {}})
            )
            return JobStatus.COMPLETED

        def cancel(self, handle):
            return JobStatus.CANCELLED

    plan = BaselinePlanner(
        registry, PlannerConfig(aframe_revision="a", amplfi_revision="b")
    ).plan("Run Aframe detection and AMPLFI parameter estimation on GW150914.")
    executor = FakeBatch()
    submission = submit_plan(
        plan,
        executor,
        registry,
        runs_dir=tmp_path,
        mode="real",
        poll_interval=0,
        sleep=lambda s: None,
    )
    desc = executor.descriptions[0]
    assert Path(desc["plan_file"]).exists() and desc["gpus"] == 1
    assert desc["mode"] == "real" and desc["runs_dir"].endswith("worker")
    assert submission.status == "completed" and submission.job_id == "4242"
    assert submission.manifest["run_id"] == "run_fake"
    saved = json.loads((submission.submission_dir / "submission.json").read_text())
    assert saved["job_id"] == "4242" and len(saved["polls"]) == 3
    assert saved["description"]["budget"]["allowed"] is True
