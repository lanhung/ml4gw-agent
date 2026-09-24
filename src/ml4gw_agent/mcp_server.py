"""Official MCP Python SDK v2 entry point; local stdio only."""

from __future__ import annotations

import signal
from collections.abc import Callable
from typing import Any

from .errors import ML4GWAgentError
from .mcp_jobs import AnalysisConfig, JobService, Mode, ServiceConfig


def create_server(service: JobService):
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError as exc:
        raise ML4GWAgentError(
            "MCP requires the official SDK v2; install 'uv sync --extra mcp'."
        ) from exc

    server = MCPServer(
        "ML4GW Agent",
        instructions="Plan a complete analysis, start its saved plan_id, then poll "
        "get_run(job_id). Mock is the default and has no scientific meaning. "
        "Only server startup configuration can enable real execution or approvals. "
        "plan_analysis takes `mode` as a top-level argument (never inside "
        "`config`). Routing contract: a generic request such as 'Analyze "
        "GW150914' plans the Buoy wrapper (data.resolve_event, buoy.analyze, "
        "report.generate); naming Aframe, AMPLFI, GWAK, DeepClean or data quality "
        "plans the decomposed DAG. Force a route with config.pipeline "
        "('buoy' | 'decomposed') and rule tools out with config.exclude_skills "
        "or a negated phrase such as 'do not run AMPLFI'. Check the returned "
        "`route` and `skills` before start_analysis.",
    )

    def invoke(function: Callable, *args: Any) -> dict[str, Any]:
        try:
            return function(*args)
        except (ML4GWAgentError, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def list_skills() -> dict[str, Any]:
        """List all scientific contracts, maturity and local availability probes."""
        return invoke(service.list_skills)

    @server.tool()
    def plan_analysis(
        prompt: str, config: AnalysisConfig | None = None, mode: Mode = "mock"
    ) -> dict[str, Any]:
        """Plan and save a deterministic analysis DAG for one event.

        `mode` ('mock' | 'real') is this top-level argument; `config` holds
        scientific options only and rejects `mode`. Routing: a generic prompt
        uses the Buoy wrapper (3 tasks); naming Aframe, AMPLFI, GWAK, DeepClean
        or data quality builds the decomposed DAG. Set config.pipeline to
        'buoy' or 'decomposed' to force a route, and config.exclude_skills (for
        example ['amplfi.pe']) or a negated phrase ('do not run AMPLFI') to rule
        tools out. Returns plan_id, route, excluded_skills, the ordered task
        skills, estimate, budget and warnings.
        """
        return invoke(service.plan_analysis, prompt, config, mode)

    @server.tool()
    def start_analysis(plan_id: str) -> dict[str, Any]:
        """Start a saved plan in its saved mode; immediately return a job_id."""
        return invoke(service.start_analysis, plan_id)

    @server.tool()
    def get_run(job_id: str) -> dict[str, Any]:
        """Read job state, task results, failure reasons, report and artifact index."""
        return invoke(service.get_run, job_id)

    @server.tool()
    def cancel_run(job_id: str) -> dict[str, Any]:
        """Cancel an active process group and preserve all existing run records."""
        return invoke(service.cancel_run, job_id)

    return server


def serve(config: ServiceConfig) -> None:
    service = JobService(config)
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, terminate)
        create_server(service).run(transport="stdio")
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        signal.signal(signal.SIGTERM, previous_handler)
