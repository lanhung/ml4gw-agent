"""SSH executor: run a saved plan on a remote host over SSH.

The user's compute is reachable over SSH (a rented GPU node, an LDG head
node) but not through a container scheduler, so this executor stands in for
Kubernetes: it copies the validated plan to the remote checkout, starts
``ml4gw-agent run-plan`` detached under ``nohup`` with a pid file, polls the
pid and the worker's manifest, kills the pid to cancel, and copies the
worker's run directory back so :func:`submit_plan` finds the manifest
exactly as it does for HTCondor. Every remote interaction goes through one
transport seam (``paramiko`` in production, a fake in the tests).

Configuration (environment):

``ML4GW_SSH_HOST``, ``ML4GW_SSH_PORT`` (22), ``ML4GW_SSH_USER`` (root),
``ML4GW_SSH_PASSWORD`` or ``ML4GW_SSH_KEY`` (private key path),
``ML4GW_SSH_REPO`` (remote checkout), ``ML4GW_SSH_RUNS`` (remote runs
directory), ``ML4GW_SSH_ENV`` (shell line exported before the command),
``ML4GW_SSH_PYTHON`` (remote command prefix, default ``uv run``).
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import Executor, ExecutorError, ExecutorKind, JobHandle, JobStatus


@dataclass
class SSHConfig:
    host: str | None
    port: int = 22
    user: str = "root"
    password: str | None = None
    key: str | None = None
    repo: str = "~/ml4gw-agent"
    runs: str = "~/ml4gw-runs"
    env: str = ""
    python: str = "uv run"

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> SSHConfig:
        env = os.environ if environ is None else environ
        return cls(
            host=env.get("ML4GW_SSH_HOST") or None,
            port=int(env.get("ML4GW_SSH_PORT", "22")),
            user=env.get("ML4GW_SSH_USER", "root"),
            password=env.get("ML4GW_SSH_PASSWORD") or None,
            key=env.get("ML4GW_SSH_KEY") or None,
            repo=env.get("ML4GW_SSH_REPO", "~/ml4gw-agent"),
            runs=env.get("ML4GW_SSH_RUNS", "~/ml4gw-runs"),
            env=env.get("ML4GW_SSH_ENV", ""),
            python=env.get("ML4GW_SSH_PYTHON", "uv run"),
        )


class SSHTransport:  # pragma: no cover - real paramiko seam, needs a host
    """Thin paramiko wrapper: ``run``, ``put``, ``get_tree``.

    Connections are opened per call so a long poll loop never holds a stale
    socket; the cost is negligible next to the jobs it drives.
    """

    def __init__(self, config: SSHConfig):
        self.config = config

    def _client(self):
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.config.host,
            port=self.config.port,
            username=self.config.user,
            password=self.config.password,
            key_filename=self.config.key,
            timeout=30,
            look_for_keys=self.config.key is not None,
            allow_agent=False,
        )
        return client

    def run(self, command: str, timeout: float = 120.0) -> tuple[int, str, str]:
        client = self._client()
        try:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            return stdout.channel.recv_exit_status(), out, err
        finally:
            client.close()

    def put(self, local: Path, remote: str) -> None:
        client = self._client()
        try:
            sftp = client.open_sftp()
            try:
                sftp.put(str(local), remote)
            finally:
                sftp.close()
        finally:
            client.close()

    def get_tree(self, remote: str, local: Path) -> list[Path]:
        """Copy a remote directory tree into ``local``; returns copied files."""
        client = self._client()
        copied: list[Path] = []
        try:
            sftp = client.open_sftp()
            try:
                stack = [(remote, local)]
                while stack:
                    rdir, ldir = stack.pop()
                    ldir.mkdir(parents=True, exist_ok=True)
                    for entry in sftp.listdir_attr(rdir):
                        rpath = f"{rdir}/{entry.filename}"
                        lpath = ldir / entry.filename
                        if entry.st_mode is not None and (entry.st_mode & 0o40000):
                            stack.append((rpath, lpath))
                        else:
                            sftp.get(rpath, str(lpath))
                            copied.append(lpath)
            finally:
                sftp.close()
        finally:
            client.close()
        return copied


class SSHExecutor(Executor):
    kind = ExecutorKind.SSH

    def __init__(
        self,
        transport: SSHTransport | None = None,
        config: SSHConfig | None = None,
    ):
        self.config = config or SSHConfig.from_environment()
        self.transport = transport or SSHTransport(self.config)

    # ---- availability -----------------------------------------------------
    def probe(self) -> str:
        if not self.config.host:
            return "missing: ML4GW_SSH_HOST not set"
        if not (self.config.password or self.config.key):
            return "missing: ML4GW_SSH_PASSWORD or ML4GW_SSH_KEY not set"
        return "available"

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _remote(*parts: str) -> str:
        return "/".join(part.rstrip("/") for part in parts)

    def _job_dir(self, job_id: str) -> str:
        return self._remote(self.config.runs, job_id)

    def _sh(self, command: str) -> tuple[int, str, str]:
        prefix = f"{self.config.env} && " if self.config.env else ""
        return self.transport.run(f"bash -lc {shlex.quote(prefix + command)}")

    @staticmethod
    def _parse_id(handle_id: str) -> tuple[str, int]:
        host, _, pid = handle_id.rpartition(":")
        try:
            return host, int(pid)
        except ValueError as exc:
            raise ExecutorError(f"malformed ssh job id {handle_id!r}") from exc

    # ---- executor surface -------------------------------------------------
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
        plan_file = description.get("plan_file")
        if not plan_file:
            raise ExecutorError("ssh submission needs description['plan_file']")
        remote_job = self._job_dir(job_id)
        remote_plan = self._remote(remote_job, "plan.json")
        remote_worker = self._remote(remote_job, "worker")
        code, _, err = self._sh(f"mkdir -p {shlex.quote(remote_worker)} && echo ok")
        if code != 0:
            raise ExecutorError(f"could not create {remote_job}: {err.strip()}")
        self.transport.put(Path(plan_file), remote_plan)
        mode = str(description.get("mode", "real"))
        agent = f"{self.config.python} ml4gw-agent"
        command = (
            f"cd {shlex.quote(self.config.repo)} && "
            f"nohup {agent} run-plan {shlex.quote(remote_plan)} --mode {mode} "
            f"--runs-dir {shlex.quote(remote_worker)} "
            f"> {shlex.quote(remote_job + '/stdout.log')} "
            f"2> {shlex.quote(remote_job + '/stderr.log')} < /dev/null & "
            f"echo $! > {shlex.quote(remote_job + '/pid')} && cat "
            f"{shlex.quote(remote_job + '/pid')}"
        )
        code, out, err = self._sh(command)
        pid = out.strip().splitlines()[-1] if out.strip() else ""
        if code != 0 or not pid.isdigit():
            raise ExecutorError(f"remote start failed: {err.strip() or out.strip()}")
        local_job = run_dir / "jobs" / job_id
        local_job.mkdir(parents=True, exist_ok=True)
        handle = JobHandle(
            id=f"{self.config.host}:{pid}",
            executor=self.kind,
            status=JobStatus.SUBMITTED,
            checkpoint=local_job / "handle.json",
            owner=self,
        )
        (local_job / "handle.json").write_text(
            json.dumps(
                {
                    **handle.as_dict(),
                    "remote_job_dir": remote_job,
                    "remote_worker_dir": remote_worker,
                    "local_worker_dir": description.get("runs_dir", str(run_dir)),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return handle

    def _handle_meta(self, handle: JobHandle) -> dict[str, Any]:
        if handle.checkpoint is None or not Path(handle.checkpoint).exists():
            raise ExecutorError(f"no checkpoint for ssh job {handle.id}")
        return json.loads(Path(handle.checkpoint).read_text(encoding="utf-8"))

    def _remote_status(self, meta: dict[str, Any]) -> str | None:
        """Status field of the worker manifest on the remote, if any."""
        worker = meta["remote_worker_dir"]
        reader = "import json,sys;print(json.load(open(sys.argv[1]))['status'])"
        code, out, _ = self._sh(
            f"for m in {shlex.quote(worker)}/run_*/run_manifest.json; do "
            f'[ -f "$m" ] && python3 -c {shlex.quote(reader)} "$m"; done '
            "2>/dev/null | tail -1"
        )
        if code != 0:
            return None
        return out.strip() or None

    def poll(self, handle: JobHandle) -> JobStatus:
        meta = self._handle_meta(handle)
        if meta.get("collected"):
            return JobStatus(meta["final_status"])
        _, pid = self._parse_id(handle.id)
        _, out, _ = self._sh(f"kill -0 {pid} 2>/dev/null && echo alive || echo gone")
        alive = "alive" in out
        status = self._remote_status(meta)
        if alive:
            return JobStatus.RUNNING if status else JobStatus.SUBMITTED
        # process is gone: collect the worker directory once
        local_worker = Path(meta["local_worker_dir"])
        try:
            self.transport.get_tree(meta["remote_worker_dir"], local_worker)
        except Exception as exc:  # noqa: BLE001 - reported through the handle
            handle.error = f"could not copy worker results: {exc}"
        final = JobStatus.COMPLETED if status == "completed" else JobStatus.FAILED
        if status is None:
            handle.error = handle.error or "worker wrote no manifest"
        meta["collected"] = True
        meta["final_status"] = final.value
        Path(handle.checkpoint).write_text(json.dumps(meta, indent=2) + "\n")
        return final

    def cancel(self, handle: JobHandle) -> JobStatus:
        meta = self._handle_meta(handle)
        _, pid = self._parse_id(handle.id)
        self._sh(f"kill {pid} 2>/dev/null; sleep 1; kill -9 {pid} 2>/dev/null; true")
        meta["collected"] = True
        meta["final_status"] = JobStatus.CANCELLED.value
        Path(handle.checkpoint).write_text(json.dumps(meta, indent=2) + "\n")
        return JobStatus.CANCELLED
