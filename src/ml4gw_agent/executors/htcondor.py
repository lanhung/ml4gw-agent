"""HTCondor executor: submit-description generation and argv-only control.

The job re-invokes the agent on a saved plan (``ml4gw-agent run-plan``) so
the worker node runs exactly the validated DAG; nothing is composed from
prompt text on the pool. Every scheduler interaction is a fixed argument
vector through :class:`CommandRunner`. This executor has not been exercised
against a real pool; the unit tests fake the scheduler binaries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .base import (
    CommandRunner,
    Executor,
    ExecutorError,
    ExecutorKind,
    JobHandle,
    JobStatus,
)

# condor_q JobStatus integers (HTCondor manual, "Job ClassAd attributes")
CONDOR_STATUS = {
    1: JobStatus.SUBMITTED,  # idle
    2: JobStatus.RUNNING,
    3: JobStatus.CANCELLED,  # removed
    4: JobStatus.COMPLETED,
    5: JobStatus.SUBMITTED,  # held
    6: JobStatus.RUNNING,  # transferring output
    7: JobStatus.SUBMITTED,  # suspended
}

TERSE_PATTERN = re.compile(r"^\s*(\d+)\.(\d+)\s*-\s*(\d+)\.(\d+)\s*$")


def render_submit_description(
    *,
    executable: str,
    arguments: list[str],
    job_dir: Path,
    cpus: int,
    memory_gb: float,
    gpus: int,
    extra: dict[str, str] | None = None,
) -> str:
    """HTCondor submit description; one job per description, no shell."""
    lines = [
        f"executable = {executable}",
        "arguments = " + " ".join(_quote(part) for part in arguments),
        f"initialdir = {job_dir}",
        f"log = {job_dir / 'condor.log'}",
        f"output = {job_dir / 'condor.out'}",
        f"error = {job_dir / 'condor.err'}",
        f"request_cpus = {int(cpus)}",
        f"request_memory = {int(round(memory_gb * 1024))}MB",
        f"request_gpus = {int(gpus)}",
        "should_transfer_files = NO",
        "getenv = True",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"{key} = {value}")
    lines.append("queue 1")
    return "\n".join(lines) + "\n"


def _quote(part: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@+-]+", part):
        return part
    escaped = part.replace("'", "''").replace('"', '""')
    return f"'{escaped}'"


def parse_cluster_id(terse_output: str) -> str:
    """Cluster id from ``condor_submit -terse`` (``123.0 - 123.0``)."""
    for line in terse_output.splitlines():
        match = TERSE_PATTERN.match(line)
        if match:
            return match.group(1)
    raise ExecutorError(f"could not parse a cluster id from: {terse_output!r}")


class HTCondorExecutor(Executor):
    kind = ExecutorKind.HTCONDOR

    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        agent_executable: str = "ml4gw-agent",
    ):
        self.runner = runner or CommandRunner()
        self.agent_executable = agent_executable

    def probe(self) -> str:
        missing = [
            name
            for name in ("condor_submit", "condor_q", "condor_rm")
            if self.runner.which(name) is None
        ]
        if missing:
            return f"missing: {', '.join(missing)} not on PATH"
        return "available"

    def submit(
        self,
        job_id: str,
        work: Callable[[], Any],
        *,
        run_dir: Path,
        description: dict[str, Any] | None = None,
    ) -> JobHandle:
        self.require_available()
        description = description or {}
        job_dir = run_dir / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        plan_file = description.get("plan_file")
        if not plan_file:
            raise ExecutorError(
                "HTCondor submission needs description['plan_file'] (a saved plan)"
            )
        arguments = [
            "run-plan",
            str(plan_file),
            "--mode",
            str(description.get("mode", "real")),
            "--runs-dir",
            str(description.get("runs_dir", run_dir)),
        ]
        agent = self.runner.which(self.agent_executable) or self.agent_executable
        text = render_submit_description(
            executable=agent,
            arguments=arguments,
            job_dir=job_dir,
            cpus=int(description.get("cpus", 1)),
            memory_gb=float(description.get("memory_gb", 2.0)),
            gpus=int(description.get("gpus", 0)),
            extra=description.get("extra"),
        )
        submit_file = job_dir / "job.sub"
        submit_file.write_text(text, encoding="utf-8")
        result = self.runner.run(["condor_submit", "-terse", str(submit_file)])
        if result.returncode != 0:
            raise ExecutorError(
                f"condor_submit failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        cluster = parse_cluster_id(result.stdout)
        handle = JobHandle(
            id=cluster,
            executor=self.kind,
            status=JobStatus.SUBMITTED,
            checkpoint=submit_file,
            owner=self,
        )
        (job_dir / "handle.json").write_text(
            json.dumps(handle.as_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return handle

    def poll(self, handle: JobHandle) -> JobStatus:
        result = self.runner.run(["condor_q", "-json", handle.id])
        if result.returncode != 0:
            raise ExecutorError(
                f"condor_q failed (exit {result.returncode}): {result.stderr.strip()}"
            )
        text = result.stdout.strip()
        if not text:
            # Left the queue: completed unless we recorded a cancellation.
            return (
                JobStatus.CANCELLED
                if handle.status == JobStatus.CANCELLED
                else JobStatus.COMPLETED
            )
        try:
            ads = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExecutorError(f"condor_q returned invalid JSON: {exc}") from exc
        if not ads:
            return JobStatus.COMPLETED
        code = int(ads[0].get("JobStatus", 0))
        if code == 4 and int(ads[0].get("ExitCode", 0)) != 0:
            handle.error = f"job exited with code {ads[0].get('ExitCode')}"
            return JobStatus.FAILED
        return CONDOR_STATUS.get(code, JobStatus.SUBMITTED)

    def cancel(self, handle: JobHandle) -> JobStatus:
        result = self.runner.run(["condor_rm", handle.id])
        if result.returncode != 0:
            raise ExecutorError(
                f"condor_rm failed (exit {result.returncode}): {result.stderr.strip()}"
            )
        handle.status = JobStatus.CANCELLED
        return handle.status
