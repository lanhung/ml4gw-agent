"""Discover and run a complete offline analysis using the official SDK v2."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def demo(prompt: str, runs_dir: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ml4gw_agent", "mcp", "--runs-dir", str(runs_dir.resolve())],
        env=dict(os.environ),
    )
    async with Client(parameters, raise_exceptions=True) as client:
        tools = await client.list_tools()
        print("Tools:", ", ".join(tool.name for tool in tools.tools))
        plan = await client.call_tool("plan_analysis", {"prompt": prompt})
        plan_id = plan.structured_content["plan_id"]
        job = await client.call_tool("start_analysis", {"plan_id": plan_id})
        job_id = job.structured_content["job_id"]
        print("Plan:", plan_id, "Job:", job_id)
        for _ in range(240):
            result = await client.call_tool("get_run", {"job_id": job_id})
            view = result.structured_content
            if view["status"] not in {"starting", "running"}:
                print("Status:", view["status"])
                if view["status"] != "completed":
                    raise RuntimeError(view["error"])
                print(view["report"])
                print("Artifacts:", len(view["artifacts"]))
                print("Manifest:", view["manifest_path"])
                return
            await asyncio.sleep(0.25)
        await client.call_tool("cancel_run", {"job_id": job_id})
        raise TimeoutError("Mock analysis did not finish in 60 seconds; cancelled")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default="Analyze GW150914")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs/mcp-demo"))
    args = parser.parse_args()
    asyncio.run(demo(args.prompt, args.runs_dir))
