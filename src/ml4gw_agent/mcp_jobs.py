"""Persistent local jobs, independent of the optional MCP SDK.

Only the existing run-plan command executes science. The server owns a private
directory, an exclusive POSIX lock, and at most one child process group.
"""

from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from .capabilities import skill_availability
from .errors import ML4GWAgentError
from .executors import BudgetPolicy, estimate_plan
from .models import (
    PlanSpec,
    RunManifest,
    RunStatus,
    StrictModel,
    TaskStatus,
    new_identifier,
    utc_now,
)
from .planning import BaselinePlanner, PlannerConfig
from .policy import ExecutionPolicy
from .provenance import sha256_file, write_manifest
from .registry import load_default_registry

Mode = Literal["mock", "real"]
ACTIVE = {"starting", "running"}
# The tool schema enumerates the registered skills so a client sees the only
# valid exclude_skills values instead of guessing config keys or tool names.
SKILL_NAMES: tuple[str, ...] = tuple(s.name for s in load_default_registry().all())
SkillName = Literal[SKILL_NAMES]  # type: ignore[valid-type]


class ServiceError(ML4GWAgentError):
    """A stable error code and an actionable explanation for clients."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class AnalysisConfig(StrictModel):
    """Scientific options only; execution permissions belong to startup."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    ifos: list[Literal["H1", "L1", "V1", "K1"]] = Field(
        default_factory=lambda: ["H1", "L1"], min_length=1, max_length=4
    )
    device: Literal["cpu", "cuda"] = "cuda"
    samples_per_event: int = Field(default=20_000, gt=0, le=100_000)
    nside: int = Field(default=64, gt=0, le=2048)
    min_samples_per_pix: int = Field(default=5, gt=0)
    use_distance: bool = True
    use_true_tc_for_amplfi: bool = False
    buoy_runner: Literal["cli", "python"] = "cli"
    aframe_revision: str | None = Field(default=None, min_length=1)
    amplfi_revision: str | None = Field(default=None, min_length=1)
    gwak_revision: str | None = Field(default=None, min_length=1)
    seed: int | None = Field(default=0, ge=0)
    window_seconds: float = Field(default=128.0, gt=0, le=4096)
    event_offset_fraction: float = Field(default=0.75, gt=0, lt=1)
    sample_rate: int = Field(default=2048, gt=0)
    aframe_threshold: float | None = None
    aframe_far_per_year: float = Field(default=1.0, gt=0)
    gwak_threshold: float | None = None
    gwak_far_per_year: float = Field(default=365.25, gt=0)
    candidate_window_seconds: float = Field(default=2.0, gt=0)
    data_source: Literal["gwosc", "ldg", "nds2"] = "gwosc"
    pipeline: Literal["auto", "buoy", "decomposed"] = Field(
        default="auto",
        description="auto: generic prompts use the Buoy wrapper and named tools "
        "build the decomposed DAG; buoy / decomposed force one route.",
    )
    exclude_skills: list[SkillName] = Field(
        default_factory=list,
        max_length=len(SKILL_NAMES),
        description="Registered skill names (exactly as list_skills returns "
        "them) that must not be scheduled, for example ['amplfi.pe']. Config "
        "keys and tool families such as 'deepclean' are not skill names. The "
        "plan fails closed if an excluded skill would be scheduled.",
    )

    def planner_config(self) -> PlannerConfig:
        values = self.model_dump()
        values["ifos"] = tuple(values["ifos"])
        values["exclude_skills"] = tuple(values["exclude_skills"])
        return PlannerConfig(**values)


@dataclass(frozen=True)
class ServiceConfig:
    runs_dir: Path
    allow_real: bool = False
    approve_high_risk: bool = False
    max_gpu_hours: float = 4.0
    authorize_budget: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_gpu_hours) or self.max_gpu_hours < 0:
            raise ValueError("max_gpu_hours must be finite and non-negative")


class SavedPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    mode: Mode
    sha256: str


class Job(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    plan_id: str
    mode: Mode
    status: Literal[
        "starting",
        "running",
        "completed",
        "failed",
        "blocked",
        "cancelled",
        "interrupted",
    ] = "starting"
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    ended_at: str | None = None
    returncode: int | None = None
    error: str | None = None


def _write_json(path: Path, value: StrictModel) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class JobService:
    def __init__(self, config: ServiceConfig):
        if os.name != "posix":
            raise ServiceError("UNSUPPORTED_PLATFORM", "stdio jobs require Linux/macOS")
        import fcntl

        self.config = config
        self.root = config.runs_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._closed = False
        self._process: subprocess.Popen | None = None
        self._active: Job | None = None
        self._directory_lock = self._path(".service.lock").open("a")
        try:
            fcntl.flock(self._directory_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._directory_lock.close()
            raise ServiceError(
                "SERVICE_BUSY", "run directory is already in use"
            ) from exc
        try:
            self._path("plans").mkdir(exist_ok=True)
            self._path("jobs").mkdir(exist_ok=True)
            self.registry = load_default_registry()
            self.policy = ExecutionPolicy(allow_high_risk=config.approve_high_risk)
            self.budget = BudgetPolicy(
                max_gpu_hours=config.max_gpu_hours, authorized=config.authorize_budget
            )
            self._recover()
        except Exception:
            self._directory_lock.close()
            raise

    def _path(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        try:
            relative = path.relative_to(self.root)
            path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise ServiceError(
                "UNSAFE_PATH", "path escapes the service directory"
            ) from exc
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            if part == ".." or cursor.is_symlink():
                raise ServiceError(
                    "UNSAFE_PATH", "traversal and symlinks are forbidden"
                )
        return path

    @staticmethod
    def _identifier(value: str, prefix: str) -> str:
        if not re.fullmatch(prefix + r"_[0-9a-f]{12}", value):
            raise ServiceError("INVALID_ID", f"invalid {prefix} identifier")
        return value

    def _require_open(self) -> None:
        if self._closed:
            raise ServiceError("SERVICE_CLOSED", "service is shutting down")

    def _mode(self, mode: Mode) -> None:
        if mode not in {"mock", "real"}:
            raise ServiceError("INVALID_MODE", "mode must be mock or real")
        if mode == "real" and not self.config.allow_real:
            raise ServiceError(
                "REAL_DISABLED", "restart with --allow-real to enable science"
            )

    def list_skills(self) -> dict[str, Any]:
        return {
            "skills": [
                {
                    **skill.model_dump(mode="json"),
                    "availability": {
                        "mock": skill_availability(skill, "mock"),
                        "real": skill_availability(skill, "real"),
                    },
                }
                for skill in self.registry.all()
            ],
            "real_enabled": self.config.allow_real,
            "availability_note": "Probes check local installation only; per-plan "
            "preflight, credentials, model loading and validation still apply.",
        }

    def plan_analysis(
        self, prompt: str, config: AnalysisConfig | None = None, mode: Mode = "mock"
    ) -> dict[str, Any]:
        with self._lock:
            self._require_open()
            self._mode(mode)
            plan = BaselinePlanner(
                self.registry, (config or AnalysisConfig()).planner_config()
            ).plan(prompt)
            self.registry.validate_plan_skills(plan)
            warnings = self.policy.validate(plan, self.registry, mode)
            estimate = estimate_plan(plan, self.registry)
            decision = self.budget.check(estimate)
            directory = self._path("plans", self._identifier(plan.id, "plan"))
            directory.mkdir()
            plan_file = directory / "plan.json"
            _write_json(plan_file, plan)
            _write_json(
                directory / "metadata.json",
                SavedPlan(plan_id=plan.id, mode=mode, sha256=sha256_file(plan_file)),
            )
            return {
                "plan_id": plan.id,
                "mode": mode,
                "route": plan.route,
                "excluded_skills": list(plan.excluded_skills),
                "skills": [task.skill for task in plan.tasks],
                "plan": plan.model_dump(mode="json"),
                "estimate": estimate.as_dict(),
                "budget": decision.as_dict(),
                "warnings": list(
                    dict.fromkeys(plan.warnings + warnings + decision.reasons)
                ),
            }

    def _load_plan(self, plan_id: str) -> tuple[PlanSpec, SavedPlan]:
        self._identifier(plan_id, "plan")
        path = self._path("plans", plan_id, "plan.json")
        metadata_path = self._path("plans", plan_id, "metadata.json")
        if not path.is_file() or not metadata_path.is_file():
            raise ServiceError("UNKNOWN_PLAN", "no saved plan with this identifier")
        metadata = SavedPlan.model_validate_json(metadata_path.read_text())
        plan = PlanSpec.model_validate_json(path.read_text())
        if (
            plan.id != plan_id
            or metadata.plan_id != plan_id
            or metadata.sha256 != sha256_file(path)
        ):
            raise ServiceError(
                "INVALID_PLAN", "saved plan identity or checksum changed"
            )
        return plan, metadata

    def _job_path(self, job_id: str, *parts: str) -> Path:
        return self._path("jobs", self._identifier(job_id, "job"), *parts)

    def _save_job(self, job: Job) -> None:
        _write_json(self._job_path(job.job_id, "job.json"), job)

    def _load_job(self, job_id: str) -> Job:
        path = self._job_path(job_id, "job.json")
        if not path.is_file():
            raise ServiceError("UNKNOWN_JOB", "no managed job with this identifier")
        job = Job.model_validate_json(path.read_text())
        if job.job_id != job_id:
            raise ServiceError(
                "INVALID_RECORD", "job identity does not match its directory"
            )
        return job

    def start_analysis(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_open()
            plan, metadata = self._load_plan(plan_id)
            self._mode(metadata.mode)
            if self._process is not None:
                if self._process.poll() is None:
                    raise ServiceError(
                        "SERVICE_BUSY", f"job {self._active.job_id} is running"
                    )
                self._finish(self._active, self._process.returncode)
            self.policy.validate(plan, self.registry, metadata.mode)
            decision = self.budget.check(estimate_plan(plan, self.registry))
            if not decision.allowed:
                raise ServiceError("BUDGET_EXCEEDED", "; ".join(decision.reasons))
            job = Job(job_id=new_identifier("job"), plan_id=plan.id, mode=metadata.mode)
            directory = self._job_path(job.job_id)
            directory.mkdir()
            _write_json(directory / "plan.json", plan)
            self._save_job(job)
            command = [
                sys.executable,
                "-m",
                "ml4gw_agent",
                "run-plan",
                str(directory / "plan.json"),
                "--mode",
                job.mode,
                "--runs-dir",
                str(directory / "runs"),
                "--executor",
                "local",
                "--max-gpu-hours",
                str(self.config.max_gpu_hours),
            ]
            if self.config.approve_high_risk:
                command.append("--approve-high-risk")
            if self.config.authorize_budget:
                command.append("--authorize-budget")
            try:
                with (directory / "job.log").open("wb") as log:
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        shell=False,
                        start_new_session=True,
                    )
            except OSError as exc:
                job.status, job.error = "failed", f"PROCESS_START_FAILED: {exc}"
                job.ended_at = utc_now().isoformat()
                self._save_job(job)
                return job.model_dump(mode="json")
            job.status = "running"
            self._active, self._process = job, process
            self._save_job(job)
            threading.Thread(
                target=self._watch, args=(job, process), daemon=True
            ).start()
            return job.model_dump(mode="json")

    def _watch(self, job: Job, process: subprocess.Popen) -> None:
        code = process.wait()
        with self._lock:
            if self._active is job:
                self._finish(job, code)

    def _manifest(self, job: Job) -> tuple[RunManifest, Path] | None:
        runs = self._job_path(job.job_id, "runs")
        paths = list(runs.glob("*/run_manifest.json"))
        if not paths:
            return None
        if len(paths) != 1:
            raise ServiceError("INVALID_RECORD", "expected exactly one run per job")
        path = self._job_path(
            job.job_id, "runs", paths[0].parent.name, "run_manifest.json"
        )
        manifest = RunManifest.model_validate_json(path.read_text())
        self._identifier(manifest.run_id, "run")
        if (
            manifest.run_id != path.parent.name
            or manifest.plan.id != job.plan_id
            or manifest.mode != job.mode
            or Path(manifest.run_directory) != path.parent
        ):
            raise ServiceError("INVALID_RECORD", "manifest does not belong to this job")
        return manifest, path

    def _finish(self, job: Job, returncode: int | None) -> None:
        job.returncode = returncode
        try:
            found = self._manifest(job)
            if found and found[0].status.value not in {"pending", "running"}:
                manifest = found[0]
                job.status = manifest.status.value
                if job.status != "completed":
                    job.error = "; ".join(
                        dict.fromkeys(
                            r.error for r in manifest.tasks.values() if r.error
                        )
                    ) or "; ".join(manifest.warnings)
                if returncode not in {None, 0} and job.status == "completed":
                    job.status = "failed"
                    job.error = f"PROCESS_EXIT: worker exited with code {returncode}"
            else:
                job.status = "interrupted" if returncode is None else "failed"
                job.error = (
                    "SERVER_RESTARTED: interrupted job was not restarted"
                    if returncode is None
                    else f"PROCESS_EXIT: worker exited with code {returncode} "
                    "without a terminal manifest"
                )
        except (OSError, ValueError, ServiceError) as exc:
            job.status, job.error = "failed", f"INVALID_RESULT: {exc}"
        job.ended_at = utc_now().isoformat()
        self._save_job(job)
        if self._active is job:
            self._active, self._process = None, None

    def _recover(self) -> None:
        for path in self._path("jobs").glob("*/job.json"):
            job = self._load_job(path.parent.name)
            if job.status in ACTIVE:
                self._finish(job, None)

    def get_run(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._require_open()
            if self._active and self._active.job_id == job_id:
                if self._process.poll() is not None:
                    self._finish(self._active, self._process.returncode)
            job = self._load_job(job_id)
            response = job.model_dump(mode="json")
            response.update(tasks={}, report=None, artifacts=[], warnings=[])
            response["log_path"] = str(self._job_path(job_id, "job.log"))
            found = self._manifest(job)
            if found is None:
                return response
            manifest, path = found
            response.update(
                run_id=manifest.run_id,
                manifest_path=str(path),
                run_status=manifest.status.value,
                warnings=manifest.warnings,
                tasks={
                    key: value.model_dump(mode="json")
                    for key, value in manifest.tasks.items()
                },
            )
            for task in manifest.tasks.values():
                for artifact in task.artifacts:
                    relative = Path(artifact.relative_path)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ServiceError(
                            "UNSAFE_PATH", "artifact must be relative to its run"
                        )
                    target = self._job_path(
                        job_id, "runs", manifest.run_id, str(relative)
                    )
                    if not target.is_file():
                        raise ServiceError("MISSING_ARTIFACT", artifact.relative_path)
                    if (
                        target.stat().st_size != artifact.size_bytes
                        or sha256_file(target) != artifact.sha256
                    ):
                        raise ServiceError("ARTIFACT_CHANGED", artifact.relative_path)
                    response["artifacts"].append(
                        {**artifact.model_dump(), "path": str(target)}
                    )
            report = self._job_path(job_id, "runs", manifest.run_id, "report.md")
            if report.is_file():
                with report.open(encoding="utf-8") as stream:
                    response["report"] = stream.read(256_000)
                    response["report_truncated"] = bool(stream.read(1))
            return response

    def cancel_run(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._load_job(job_id)
            if self._active is None or self._active.job_id != job_id:
                return job.model_dump(mode="json")
            process = self._process
            if process.poll() is not None:
                self._finish(self._active, process.returncode)
                return self._load_job(job_id).model_dump(mode="json")
            # Signal the whole group, including Buoy descendants. Wait before
            # editing the final manifest, so the worker cannot overwrite it.
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    continue
                # A descendant may ignore SIGINT even after the worker exits.
                # Escalate for the entire group instead of leaving it running.
            process.wait()
            job.status, job.error = (
                "cancelled",
                "CANCELLED: cancelled by client or server shutdown",
            )
            job.returncode, job.ended_at = process.returncode, utc_now().isoformat()
            try:
                found = self._manifest(job)
                if found:
                    manifest, path = found
                    manifest.status, manifest.ended_at = RunStatus.CANCELLED, utc_now()
                    for task in manifest.tasks.values():
                        if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
                            task.status, task.error, task.ended_at = (
                                TaskStatus.CANCELLED,
                                job.error,
                                utc_now(),
                            )
                    write_manifest(manifest, path)
            except (OSError, ValueError, ServiceError) as exc:
                job.error += f"; INVALID_RESULT: {exc}"
            self._save_job(job)
            self._active, self._process = None, None
            return job.model_dump(mode="json")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if self._active:
                    self.cancel_run(self._active.job_id)
            finally:
                self._closed = True
                self._directory_lock.close()
