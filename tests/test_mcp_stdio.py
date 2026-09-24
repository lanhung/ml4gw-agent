"""Wire tests use the official v2 client and a real stdio server process."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

pytest.importorskip(
    "mcp", reason="MCP interface suite: uv sync --extra mcp --group dev"
)
from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from ml4gw_agent.mcp_jobs import JobService, ServiceConfig  # noqa: E402
from ml4gw_agent.mcp_server import create_server  # noqa: E402


def test_official_stdio_workflow(tmp_path):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ml4gw_agent", "mcp", "--runs-dir", str(tmp_path)],
            env=dict(os.environ),
        )
        async with Client(parameters) as client:
            discovered = await client.list_tools()
            assert {tool.name for tool in discovered.tools} == {
                "list_skills",
                "plan_analysis",
                "start_analysis",
                "get_run",
                "cancel_run",
            }
            skills = await client.call_tool("list_skills")
            assert len(skills.structured_content["skills"]) == 12
            for prompt in [
                "Analyze GW150914",
                "Run Aframe and AMPLFI on GW150914",
                "Run Aframe and GWAK on GW150914",
            ]:
                plan = await client.call_tool("plan_analysis", {"prompt": prompt})
                assert not plan.is_error
                job = await client.call_tool(
                    "start_analysis", {"plan_id": plan.structured_content["plan_id"]}
                )
                job_id = job.structured_content["job_id"]
                for _ in range(200):
                    result = await client.call_tool("get_run", {"job_id": job_id})
                    assert not result.is_error
                    if result.structured_content["status"] not in {
                        "running",
                        "starting",
                    }:
                        break
                    await asyncio.sleep(0.05)
                assert result.structured_content["status"] == "completed"
                assert "SIMULATED" in result.structured_content["report"]
                assert result.structured_content["artifacts"]
                cancelled = await client.call_tool("cancel_run", {"job_id": job_id})
                assert cancelled.structured_content["status"] == "completed"
            for tool, args, message in [
                ("start_analysis", {"plan_id": "plan_000000000000"}, "UNKNOWN_PLAN"),
                (
                    "plan_analysis",
                    {"prompt": "Analyze GW150914", "mode": "real"},
                    "REAL_DISABLED",
                ),
                ("get_run", {"job_id": "../../secret"}, "INVALID_ID"),
                (
                    "plan_analysis",
                    {"prompt": "Analyze GW150914", "config": {"allow_real": True}},
                    "allow_real",
                ),
            ]:
                result = await client.call_tool(tool, args)
                assert result.is_error
                assert message in str(result.content)

    asyncio.run(check())


def test_sdk_handlers_in_process(tmp_path):
    # Also exercise handlers in the coverage process; wire behavior is above.
    service = JobService(ServiceConfig(tmp_path))

    async def check():
        async with Client(create_server(service)) as client:
            assert not (await client.call_tool("list_skills")).is_error
            plan = await client.call_tool(
                "plan_analysis", {"prompt": "Analyze GW150914"}
            )
            result = await client.call_tool(
                "start_analysis", {"plan_id": plan.structured_content["plan_id"]}
            )
            job_id = result.structured_content["job_id"]
            assert not (await client.call_tool("get_run", {"job_id": job_id})).is_error
            assert not (
                await client.call_tool("cancel_run", {"job_id": job_id})
            ).is_error
            assert (await client.call_tool("get_run", {"job_id": "bad"})).is_error

    try:
        asyncio.run(check())
    finally:
        service.close()
