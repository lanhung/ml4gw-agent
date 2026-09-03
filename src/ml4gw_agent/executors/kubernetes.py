"""Kubernetes executor: Job manifest rendering and ``kubectl`` argv control.

Same shape as the HTCondor executor: the Job re-runs a saved plan through
the agent CLI inside a pinned image; ``kubectl`` is called with argument
vectors only. Not exercised against a real cluster; unit tests fake kubectl.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .base import (
    CommandRunner,
    Executor,
    ExecutorError,
    ExecutorKind,
    JobHandle,
    JobStatus,
)

NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def render_job_manifest(
    *,
    name: str,
    image: str,
    arguments: list[str],
    cpus: int,
    memory_gb: float,
    gpus: int,
    namespace: str = "default",
) -> str:
    if not NAME_PATTERN.fullmatch(name):
        raise ExecutorError(f"invalid Kubernetes job name: {name!r}")
    limits: dict[str, Any] = {"cpu": str(int(cpus)), "memory": f"{memory_gb:g}Gi"}
    if gpus:
        limits["nvidia.com/gpu"] = str(int(gpus))
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "backoffLimit": 0,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "ml4gw-agent",
                            "image": image,
                            "command": ["ml4gw-agent"],
                            "args": list(arguments),
                            "resources": {"limits": limits, "requests": limits},
                        }
                    ],
                }
            },
        },
    }
    return yaml.safe_dump(manifest, sort_keys=False)


class KubernetesExecutor(Executor):
    kind = ExecutorKind.KUBERNETES

    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        image: str | None = None,
        namespace: str = "default",
    ):
        self.runner = runner or CommandRunner()
        self.image = image
        self.namespace = namespace

    def probe(self) -> str:
        if self.runner.which("kubectl") is None:
            return "missing: kubectl not on PATH"
        if not self.image:
            return "missing: no pinned agent container image configured"
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
        plan_file = description.get("plan_file")
        if not plan_file:
            raise ExecutorError(
                "Kubernetes submission needs description['plan_file'] (a saved plan)"
            )
        name = f"ml4gw-{job_id}".replace("_", "-").lower()
        job_dir = run_dir / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        text = render_job_manifest(
            name=name,
            image=str(self.image),
            arguments=[
                "run-plan",
                str(plan_file),
                "--mode",
                str(description.get("mode", "real")),
                "--runs-dir",
                str(description.get("runs_dir", run_dir)),
            ],
            cpus=int(description.get("cpus", 1)),
            memory_gb=float(description.get("memory_gb", 2.0)),
            gpus=int(description.get("gpus", 0)),
            namespace=self.namespace,
        )
        manifest_file = job_dir / "job.yaml"
        manifest_file.write_text(text, encoding="utf-8")
        result = self.runner.run(["kubectl", "apply", "-f", str(manifest_file)])
        if result.returncode != 0:
            raise ExecutorError(
                f"kubectl apply failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        return JobHandle(
            id=name,
            executor=self.kind,
            status=JobStatus.SUBMITTED,
            checkpoint=manifest_file,
            owner=self,
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        result = self.runner.run(
            ["kubectl", "get", "job", handle.id, "-n", self.namespace, "-o", "json"]
        )
        if result.returncode != 0:
            if "NotFound" in result.stderr or "not found" in result.stderr:
                return (
                    JobStatus.CANCELLED
                    if handle.status == JobStatus.CANCELLED
                    else JobStatus.COMPLETED
                )
            raise ExecutorError(
                f"kubectl get job failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        try:
            status = json.loads(result.stdout).get("status", {})
        except json.JSONDecodeError as exc:
            raise ExecutorError(f"kubectl returned invalid JSON: {exc}") from exc
        if int(status.get("succeeded", 0)) >= 1:
            return JobStatus.COMPLETED
        if int(status.get("failed", 0)) >= 1:
            handle.error = "job pod failed"
            return JobStatus.FAILED
        if int(status.get("active", 0)) >= 1:
            return JobStatus.RUNNING
        return JobStatus.SUBMITTED

    def cancel(self, handle: JobHandle) -> JobStatus:
        result = self.runner.run(
            ["kubectl", "delete", "job", handle.id, "-n", self.namespace]
        )
        if result.returncode != 0:
            raise ExecutorError(
                f"kubectl delete failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        handle.status = JobStatus.CANCELLED
        return handle.status
