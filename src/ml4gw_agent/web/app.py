"""FastAPI application exposing the agent to a browser.

Every request goes through the same planner, policy, registry, and runtime
as the CLI; the web layer adds nothing that bypasses them. Mock runs execute
locally. Real runs are forwarded over SSH to a GPU node that has the science
environment (configured with ``ML4GW_NODE_*`` variables) and are serialised
with a lock, because the node has one GPU reserved for the agent.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..errors import ML4GWAgentError as AgentError
from ..errors import PlanningError
from ..executors import BudgetPolicy, estimate_plan
from ..models import PlanSpec, RunStatus
from ..planning import BaselinePlanner, PlannerConfig
from ..policy import ExecutionPolicy
from ..registry import load_default_registry
from ..runtime import AgentRuntime

DEFAULT_AFRAME = "3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4"
DEFAULT_AMPLFI = "8b97d2f8459d04924cb010dfee0262260bf3da80"
RUNS_DIR = Path(os.environ.get("ML4GW_WEB_RUNS", "runs/web")).resolve()
RECORDS_DIR = Path(os.environ.get("ML4GW_WEB_RECORDS", "docs/acceptance")).resolve()
PASSCODE = os.environ.get("ML4GW_WEB_PASSCODE", "")


class PlanRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=500)
    mode: str = Field(default="mock", pattern="^(mock|real)$")
    planner: str = Field(default="baseline", pattern="^(baseline|llm)$")
    ifos: list[str] = Field(default_factory=lambda: ["H1", "L1"])
    aframe_far_per_year: float = Field(default=365.25, gt=0)
    seed: int = Field(default=0, ge=0)
    passcode: str = ""


@dataclass
class Job:
    id: str
    request: dict[str, Any]
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    plan: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    report: str | None = None
    error: str | None = None
    log: str = ""


def _config(req: PlanRequest) -> PlannerConfig:
    return PlannerConfig(
        ifos=tuple(req.ifos),
        device="cuda" if req.mode == "real" else "cpu",
        seed=req.seed,
        aframe_revision=DEFAULT_AFRAME,
        amplfi_revision=DEFAULT_AMPLFI,
        gwak_revision="c" * 40 if req.mode == "mock" else None,
        aframe_far_per_year=req.aframe_far_per_year,
    )


def _planner(req: PlanRequest):
    registry = load_default_registry()
    config = _config(req)
    if req.planner == "llm":
        try:
            from ..llm_planner import AnthropicClient, LLMPlanner
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(400, f"LLM planner unavailable: {exc}") from exc
        if not (
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ):
            raise HTTPException(
                400, "LLM planner needs ANTHROPIC_API_KEY on the server; use baseline"
            )
        return LLMPlanner(registry, AnthropicClient(), config, mode=req.mode)
    return BaselinePlanner(registry, config)


def _plan_dict(plan: PlanSpec) -> dict[str, Any]:
    return json.loads(plan.model_dump_json())


class RemoteNode:
    """Runs real plans on the GPU node over SSH (paramiko, password from env)."""

    def __init__(self) -> None:
        self.host = os.environ.get("ML4GW_NODE_HOST")
        self.port = int(os.environ.get("ML4GW_NODE_PORT", "22"))
        self.user = os.environ.get("ML4GW_NODE_USER", "root")
        self.password = os.environ.get("ML4GW_NODE_PASSWORD")
        self.repo = os.environ.get("ML4GW_NODE_REPO", "/root/ml4gw-agent")
        self.runs = os.environ.get(
            "ML4GW_NODE_RUNS", "/root/autodl-tmp/ml4gw-agent-runs/web"
        )
        self.env = os.environ.get(
            "ML4GW_NODE_ENV",
            "export PATH=/root/miniconda3/bin:$PATH "
            "HF_HOME=/root/autodl-tmp/ml4gw-agent-hf "
            "HF_ENDPOINT=https://hf-mirror.com GWPY_CACHE=1 CUDA_VISIBLE_DEVICES=2 "
            "PYTHONUNBUFFERED=1; unset HF_HUB_OFFLINE",
        )
        self.lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.host and self.password)

    def _client(self):
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )
        return client

    def run(self, job: Job, req: PlanRequest) -> None:
        run_dir = f"{self.runs}/{job.id}"
        argv = [
            "uv",
            "run",
            "ml4gw-agent",
            "run",
            req.prompt,
            "--mode",
            "real",
            "--runs-dir",
            run_dir,
            "--device",
            "cuda",
            "--seed",
            str(req.seed),
            "--ifos",
            *req.ifos,
            "--aframe-far",
            str(req.aframe_far_per_year),
            "--aframe-revision",
            DEFAULT_AFRAME,
            "--amplfi-revision",
            DEFAULT_AMPLFI,
        ]
        command = (
            f"mkdir -p {shlex.quote(run_dir)} && cd {shlex.quote(self.repo)} && "
            f"{self.env} && {' '.join(shlex.quote(a) for a in argv)} "
            f"2> {shlex.quote(run_dir)}/console.err"
        )
        with self.lock:
            job.status = "running"
            client = self._client()
            try:
                _, stdout, stderr = client.exec_command(command, timeout=3600)
                out = stdout.read().decode("utf-8", "replace")
                err = stderr.read().decode("utf-8", "replace")
                code = stdout.channel.recv_exit_status()
                job.log = (out + err)[-4000:]
                start = out.rfind("\n{")
                summary = json.loads(out[start + 1 :] if start >= 0 else out)
                job.summary = summary
                sftp = client.open_sftp()
                with sftp.open(summary["manifest"]) as handle:
                    job.manifest = json.load(handle)
                if summary.get("report"):
                    with sftp.open(summary["report"]) as handle:
                        job.report = handle.read().decode("utf-8", "replace")
                sftp.close()
                job.status = "completed" if code == 0 else "failed"
                if code != 0 and not job.error:
                    job.error = f"agent exited with code {code}"
            finally:
                client.close()


NODE = RemoteNode()
JOBS: dict[str, Job] = {}
POOL = ThreadPoolExecutor(max_workers=4)
app = FastAPI(title="ML4GW Agent", version="0.3")


def _run_mock(job: Job, req: PlanRequest, plan: PlanSpec) -> None:
    job.status = "running"
    registry = load_default_registry()
    runs_dir = RUNS_DIR / job.id
    runs_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        manifest = AgentRuntime(registry, ExecutionPolicy()).run(
            plan, runs_dir=runs_dir, mode="mock"
        )
    run_dir = Path(manifest.run_directory)
    job.manifest = json.loads((run_dir / "run_manifest.json").read_text())
    report = run_dir / "report.md"
    job.report = report.read_text() if report.exists() else None
    job.summary = {
        "run_id": manifest.run_id,
        "status": manifest.status.value,
        "run_directory": str(run_dir),
        "warnings": manifest.warnings,
    }
    job.status = "completed" if manifest.status == RunStatus.COMPLETED else "failed"


def _execute(job: Job, req: PlanRequest, plan: PlanSpec) -> None:
    try:
        if req.mode == "mock":
            _run_mock(job, req, plan)
        else:
            NODE.run(job, req)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = time.time()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (
        resources.files("ml4gw_agent.web")
        .joinpath("static/index.html")
        .read_text("utf-8")
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "real_runs": NODE.configured,
        "llm_planner": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "passcode_required": bool(PASSCODE),
    }


@app.get("/api/skills")
def skills() -> list[dict[str, Any]]:
    from ..adapters import PYTHON_ADAPTERS
    from ..models import AdapterKind

    rows = []
    for skill in load_default_registry().all():
        availability = "available"
        if skill.adapter.kind == AdapterKind.PLANNED:
            availability = "planned"
        elif skill.adapter.kind == AdapterKind.PYTHON:
            cls = PYTHON_ADAPTERS.get(skill.adapter.entrypoint)
            availability = cls().probe() if cls else "broken"
        rows.append(
            {
                "name": skill.name,
                "version": skill.version,
                "status": skill.status.value,
                "adapter": skill.adapter.kind.value,
                "availability_here": availability,
                "description": skill.description,
                "risk": skill.risk.value,
            }
        )
    return rows


@app.post("/api/plan")
def make_plan(req: PlanRequest) -> dict[str, Any]:
    try:
        plan = _planner(req).plan(req.prompt)
    except PlanningError as exc:
        raise HTTPException(422, str(exc)) from exc
    registry = load_default_registry()
    estimate = estimate_plan(plan, registry)
    decision = BudgetPolicy().check(estimate)
    return {
        "plan": _plan_dict(plan),
        "estimate": asdict(estimate),
        "budget": asdict(decision),
    }


@app.post("/api/run")
def start_run(req: PlanRequest) -> dict[str, Any]:
    if req.mode == "real":
        if not NODE.configured:
            raise HTTPException(400, "real runs are not configured on this server")
        if PASSCODE and req.passcode != PASSCODE:
            raise HTTPException(403, "passcode required for real runs")
    try:
        plan = _planner(req).plan(req.prompt)
    except PlanningError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = Job(
        id=f"job_{uuid.uuid4().hex[:10]}", request=req.model_dump(exclude={"passcode"})
    )
    job.plan = _plan_dict(plan)
    JOBS[job.id] = job
    POOL.submit(_execute, job, req, plan)
    return {"job_id": job.id, "status": job.status}


def _job_view(job: Job) -> dict[str, Any]:
    data = asdict(job)
    if job.manifest:
        tasks = job.manifest.get("tasks", {})
        data["tasks"] = [
            {
                "id": tid,
                "skill": t.get("skill"),
                "status": t.get("status"),
                "error": t.get("error"),
                "outputs": {
                    k: v
                    for k, v in (t.get("outputs") or {}).items()
                    if k
                    in {
                        "quality_passed",
                        "issues",
                        "candidate_found",
                        "detection_statistic",
                        "threshold",
                        "threshold_calibrated",
                        "predicted_coalescence_time",
                        "target_offset_seconds",
                        "applicable",
                        "reasons",
                        "route",
                        "follow_up",
                        "n_samples",
                        "detectors_used",
                        "amplfi_network",
                        "simulated",
                        "credible_intervals",
                    }
                },
            }
            for tid, t in tasks.items()
        ]
        data["warnings"] = job.manifest.get("warnings", [])
        data["execution"] = job.manifest.get("execution")
    return data


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return _job_view(job)


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [
        {
            "id": j.id,
            "status": j.status,
            "mode": j.request.get("mode"),
            "prompt": j.request.get("prompt"),
            "created_at": j.created_at,
        }
        for j in sorted(JOBS.values(), key=lambda j: -j.created_at)[:50]
    ]


@app.get("/api/records")
def records() -> list[dict[str, Any]]:
    """Acceptance records shipped with the repository (real GPU runs)."""
    rows = []
    if not RECORDS_DIR.exists():
        return rows
    for directory in sorted(RECORDS_DIR.iterdir()):
        if not directory.is_dir():
            continue
        entry: dict[str, Any] = {"name": directory.name, "comparisons": [], "runs": []}
        for path in sorted(directory.glob("compare-*.json")):
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(path.read_text())
                entry["comparisons"].append(
                    {
                        "name": path.stem,
                        "passed": data.get("passed"),
                        "agent_network": data.get("agent_amplfi_network"),
                        "buoy_network": data.get("buoy_amplfi_network"),
                        "checks": data.get("checks", []),
                        "note": data.get("amplfi") or data.get("reason"),
                    }
                )
        for manifest in sorted(directory.rglob("run_manifest.json")) + sorted(
            directory.glob("manifest.json")
        ):
            with contextlib.suppress(json.JSONDecodeError, KeyError):
                m = json.loads(manifest.read_text())
                entry["runs"].append(
                    {
                        "path": str(manifest.relative_to(RECORDS_DIR)),
                        "run_id": m.get("run_id"),
                        "status": m.get("status"),
                        "prompt": m.get("plan", {}).get("prompt"),
                        "tasks": {
                            tid: t.get("status")
                            for tid, t in m.get("tasks", {}).items()
                        },
                        "aframe": (m.get("tasks", {}).get("run_aframe") or {})
                        .get("outputs", {})
                        .get("detection_statistic")
                        or (m.get("tasks", {}).get("analyze_event") or {})
                        .get("outputs", {})
                        .get("detection_statistic"),
                    }
                )
        for name in ("aframe_background_final_123lags.json",):
            path = directory / name
            if path.exists():
                data = json.loads(path.read_text())
                entry["background"] = {
                    "livetime_days": data.get("livetime_days"),
                    "n_peaks": data.get("n_peaks"),
                    "thresholds": data.get("thresholds"),
                    "loudest": data.get("loudest_background_peaks", [])[:5],
                }
        rows.append(entry)
    return rows


@app.get("/api/records/{name}/{path:path}")
def record_file(name: str, path: str) -> JSONResponse:
    target = (RECORDS_DIR / name / path).resolve()
    if not str(target).startswith(str(RECORDS_DIR)) or not target.is_file():
        raise HTTPException(404, "not found")
    if target.suffix == ".json":
        return JSONResponse(json.loads(target.read_text()))
    return JSONResponse({"text": target.read_text(errors="replace")})


@app.exception_handler(AgentError)
def agent_error(_, exc: AgentError):  # pragma: no cover - defensive
    return JSONResponse({"detail": str(exc)}, status_code=422)
