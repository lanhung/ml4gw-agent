#!/usr/bin/env python3
"""Test a live OpenAI-compatible agent against the official MCP stdio server.

Credentials come from an environment variable, a single-token key file, or an
explicitly supplied CLIProxy YAML config. Only mock science is enabled.
Model-selected calls are forwarded as-is;
there is no replay, forced tool sequence, planner substitution, or LLM fallback.
Raw conversations and job artifacts stay under --runs-dir (ignored by git).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml
from mcp import Client
from mcp.client.stdio import StdioServerParameters

SYSTEM = """You are an external agent testing ML4GW Agent through MCP tools.
Follow the user's analysis or acceptance-test request by actually calling tools.
Use identifiers returned by tools; never invent results. After starting an
analysis, query it until terminal, then read the report and artifact index.
Mock results are SIMULATED and have no scientific meaning. Report this clearly.
The server alone controls permissions. For explicitly requested negative tests,
send the requested invalid arguments once and report the actual tool error.
Do not claim a test passed just because you expect the server to reject it.
Finish with a concise summary of the observed results and any limitations.
"""

# This fixture changes only worker latency. It runs in a separate stdio server
# process; normal scenarios use the unmodified public CLI. Real science remains
# disabled. Cancellation still uses JobService's actual process-group handling.
DELAYED_SERVER = """
import subprocess, sys
from pathlib import Path
from ml4gw_agent.mcp_jobs import ServiceConfig
from ml4gw_agent.mcp_server import serve
class DelayedWorker(subprocess.Popen):
    def __init__(self, command, *args, **kwargs):
        if command[1:4] == ['-m', 'ml4gw_agent', 'run-plan']:
            script = ('import sys,time; time.sleep(300); '
                      'from ml4gw_agent.cli import main; '
                      'raise SystemExit(main(sys.argv[1:]))')
            command = [sys.executable, '-c', script, *command[3:]]
        super().__init__(command, *args, **kwargs)
subprocess.Popen = DelayedWorker
serve(ServiceConfig(Path(sys.argv[1])))
"""

CASES = {
    "buoy": {
        "prompt": "请先查询已注册技能，再用默认流程分析 GW150914。"
        "读取完成的报告和产物索引，说明这是模拟分析。",
        "skills": ["data.resolve_event", "buoy.analyze", "report.generate"],
    },
    "aframe_amplfi": {
        "prompt": "Run Aframe and AMPLFI on GW150914 in mock mode. "
        "Wait for completion and read the report and artifact index.",
        "skills": [
            "data.resolve_event",
            "data.fetch",
            "data.inspect",
            "aframe.detect",
            "amplfi.pe",
            "report.generate",
        ],
    },
    "aframe_gwak": {
        "prompt": "用 mock 模式对 GW150914 运行 Aframe 和 GWAK，"
        "并对两路结果进行 reconcile。等待完成并读取报告和产物索引。",
        "skills": [
            "data.resolve_event",
            "data.fetch",
            "data.inspect",
            "aframe.detect",
            "data.fetch",
            "gwak.scan",
            "analysis.reconcile",
            "report.generate",
        ],
    },
    "invalid_requests": {
        "prompt": "Perform five negative interface tests, each by calling the "
        "tool exactly with the specified arguments: "
        'start_analysis({"plan_id":"plan_000000000000"}); '
        'get_run({"job_id":"job_000000000000"}); '
        'get_run({"job_id":"../../secret"}); '
        'plan_analysis({"prompt":"Analyze GW150914","mode":"real"}); '
        'plan_analysis({"prompt":"Analyze GW150914",'
        '"config":{"allow_real":true}}). '
        "The server has not enabled real execution. Unknown config fields are "
        "intentionally invalid: send them to verify rejection. Report the "
        "observed errors. Do not start any valid analysis.",
    },
    "budget": {
        "prompt": "This server has a zero GPU-hour budget. Plan Analyze GW150914 "
        "in mock mode with device cuda, then as an explicit negative test call "
        "start_analysis on the returned plan_id even if the plan says its "
        "budget is denied. Report the actual refusal. Do not change config "
        "to avoid the budget, and do not attempt to grant approval.",
    },
    "busy_cancel": {
        "prompt": "Lifecycle test: this mock server has a test fixture delaying "
        "worker execution for 300 seconds. Plan Analyze GW150914 in mock mode "
        "and start it. While that job is active, try to start the same plan "
        "again to test SERVICE_BUSY. Then cancel the first job, query its "
        "status, and cancel it again to check cancellation is idempotent. "
        "Do not wait for the delayed worker to finish; report observed results.",
    },
}
TOOLS = {"list_skills", "plan_analysis", "start_analysis", "get_run", "cancel_run"}


class EvaluationError(Exception):
    """A diagnostic authored by this evaluator, containing no proxy secrets."""


def describe_failure(exc):
    # Client transports may wrap an HTTP failure in an AnyIO ExceptionGroup.
    # Unwrap without persisting arbitrary upstream messages or request headers.
    nested = getattr(exc, "exceptions", ())
    if nested:
        return "; ".join(dict.fromkeys(describe_failure(e) for e in nested))
    if isinstance(exc, EvaluationError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return f"{type(exc).__name__}: LLM request timed out"
    return f"{type(exc).__name__}: live conversation failed"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_api_key(args):
    """Read credentials without placing them in command arguments or evidence."""
    key = os.environ.get(args.api_key_env)
    if getattr(args, "key_file", None):
        key = args.key_file.read_text().strip()
        if not key or any(c.isspace() for c in key):
            raise EvaluationError("Key file must contain one token with no whitespace")
    if args.proxy_config:
        config = yaml.safe_load(args.proxy_config.read_text())
        key = (config.get("api-keys") or [None])[0]
    if not isinstance(key, str) or not key:
        raise EvaluationError("Set the API key environment variable or credential file")
    return key


def result_body(result):
    if result.structured_content is not None:
        return result.structured_content
    return {"error": "\n".join(getattr(c, "text", "") for c in result.content)}


def brief(call):
    body = call["result"]
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    record = {k: call[k] for k in ("name", "arguments", "is_error")}
    record["result_sha256"] = hashlib.sha256(encoded).hexdigest()
    for key in ("plan_id", "job_id", "mode", "status", "error", "budget"):
        if key in body:
            record[key] = body[key]
    if "plan" in body:
        record["skills"] = [t["skill"] for t in body["plan"]["tasks"]]
    if "skills" in body:
        record["skill_count"] = len(body["skills"])
    if "report" in body:
        record["simulated_report"] = "SIMULATED" in (body["report"] or "")
        record["artifact_count"] = len(body.get("artifacts", []))
        record["task_statuses"] = {
            k: v["status"] for k, v in body.get("tasks", {}).items()
        }
    return record


def verify(case_id, calls, final):
    """Evaluate MCP observations, never the model's own pass/fail assertions."""
    case = CASES[case_id]
    checks = {"agent_finished": bool(final.strip())}

    def successful(name):
        return [c["result"] for c in calls if c["name"] == name and not c["is_error"]]

    def rejected(name, substring):
        return any(
            c["name"] == name and c["is_error"] and substring in json.dumps(c["result"])
            for c in calls
        )

    if "skills" in case:
        plans = successful("plan_analysis")
        checks["expected_skills"] = bool(plans) and all(
            [t["skill"] for t in p["plan"]["tasks"]] == case["skills"] for p in plans
        )
        views = successful("get_run")
        completed = [v for v in views if v["status"] == "completed"]
        checks["completed_mock"] = bool(completed) and all(
            v["mode"] == "mock" for v in completed
        )
        checks["tasks_completed"] = bool(completed) and all(
            v["tasks"] and all(t["status"] == "completed" for t in v["tasks"].values())
            for v in completed
        )
        checks["report_and_artifacts"] = bool(completed) and all(
            "SIMULATED" in (v.get("report") or "") and v.get("artifacts")
            for v in completed
        )
        checks["no_tool_errors"] = not any(c["is_error"] for c in calls)
        checks["mock_disclosed"] = any(
            term in final.lower() for term in ("mock", "simulated", "模拟")
        )
        if case_id == "buoy":
            checks["twelve_skills"] = any(
                len(v["skills"]) == 12 for v in successful("list_skills")
            )
    elif case_id == "invalid_requests":
        for name, reason in (
            ("start_analysis", "UNKNOWN_PLAN"),
            ("get_run", "UNKNOWN_JOB"),
            ("get_run", "INVALID_ID"),
            ("plan_analysis", "REAL_DISABLED"),
            ("plan_analysis", "allow_real"),
        ):
            checks[reason] = rejected(name, reason)
        checks["no_job_started"] = not successful("start_analysis")
    elif case_id == "budget":
        checks["budget_denied"] = any(
            not p["budget"]["allowed"] for p in successful("plan_analysis")
        )
        checks["start_denied"] = rejected("start_analysis", "BUDGET_EXCEEDED")
        checks["no_job_started"] = not successful("start_analysis")
    else:
        checks["busy"] = rejected("start_analysis", "SERVICE_BUSY")
        cancellations = successful("cancel_run")
        checks["cancelled_twice"] = len(cancellations) >= 2 and all(
            c["status"] == "cancelled" for c in cancellations
        )
        checks["cancelled_record_read"] = any(
            v["status"] == "cancelled" for v in successful("get_run")
        )
        checks["one_job"] = len(successful("start_analysis")) == 1
    return checks


async def run_case(case_id, args, http, headers, root):
    case = CASES[case_id]
    directory = root / case_id
    server_args = ["-m", "ml4gw_agent", "mcp", "--runs-dir", str(directory)]
    if case_id == "budget":
        server_args.extend(["--max-gpu-hours", "0"])
    if case_id == "busy_cancel":
        server_args = ["-c", DELAYED_SERVER, str(directory)]
    env = {k: v for k, v in os.environ.items() if k != args.api_key_env}
    parameters = StdioServerParameters(
        command=sys.executable, args=server_args, env=env
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": case["prompt"]},
    ]
    calls, requests = [], []
    final, failure = "", None
    started = time.monotonic()
    try:
        async with Client(parameters) as client:
            discovered = await client.list_tools()
            if {t.name for t in discovered.tools} != TOOLS:
                raise ValueError("MCP did not expose the expected five tools")
            functions = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in discovered.tools
            ]
            for round_index in range(args.max_rounds):
                before = time.monotonic()
                requests.append(
                    {
                        "round": round_index + 1,
                        "http_status": None,
                    }
                )
                try:
                    response = await http.post(
                        args.base_url.rstrip("/") + "/chat/completions",
                        headers=headers,
                        json={
                            "model": args.model,
                            "messages": messages,
                            "tools": functions,
                            "tool_choice": "auto",
                            "max_tokens": getattr(args, "max_tokens", 2500),
                        },
                    )
                except httpx.HTTPError as exc:
                    requests[-1]["error_type"] = type(exc).__name__
                    raise
                finally:
                    requests[-1]["latency_seconds"] = round(
                        time.monotonic() - before, 3
                    )
                requests[-1]["http_status"] = response.status_code
                if not response.is_success:
                    # Do not persist upstream error bodies or headers: they may
                    # include proxy authentication or configuration details.
                    try:
                        code = str(response.json().get("error", {}).get("code", ""))
                    except (ValueError, AttributeError):
                        code = ""
                    if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code):
                        requests[-1]["provider_error_code"] = code
                    else:
                        code = ""
                    detail = f" (code {code})" if code else ""
                    raise EvaluationError(f"LLM HTTP {response.status_code}{detail}")
                data = response.json()
                choice = data["choices"][0]
                requests[-1].update(
                    model=data.get("model"),
                    usage=data.get("usage", {}),
                    finish_reason=choice.get("finish_reason"),
                )
                message = choice["message"]
                message_fields = {"role", "content", "tool_calls"}
                if getattr(args, "preserve_reasoning", False):
                    # GLM's preserved-thinking protocol returns this field to
                    # the provider on subsequent tool turns, without editing it.
                    message_fields.add("reasoning_content")
                messages.append(
                    {k: v for k, v in message.items() if k in message_fields}
                )
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    final = message.get("content") or ""
                    break
                for call in tool_calls:
                    name = call["function"]["name"]
                    arguments = json.loads(call["function"]["arguments"])
                    if name not in TOOLS:
                        raise ValueError("Agent selected an undiscovered tool")
                    result = await client.call_tool(name, arguments)
                    body = result_body(result)
                    calls.append(
                        {
                            "name": name,
                            "arguments": arguments,
                            "is_error": bool(result.is_error),
                            "result": body,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(body, ensure_ascii=False),
                        }
                    )
                    state = body.get("status", "error" if result.is_error else "ok")
                    print(f"[{args.model}/{case_id}] {name}: {state}", flush=True)
            else:
                failure = "agent exceeded maximum conversation rounds"
    except Exception as exc:
        # Keep exception classes without leaking request headers/credentials.
        failure = describe_failure(exc)
    checks = verify(case_id, calls, final)
    checks["no_transport_failure"] = failure is None
    transcript = {"messages": messages, "calls": calls, "requests": requests}
    write_json(directory / "conversation.json", transcript)
    return {
        "id": case_id,
        "prompt": case["prompt"],
        "passed": all(checks.values()),
        "checks": checks,
        "error": failure,
        "fixture": "worker delayed 300s" if case_id == "busy_cancel" else None,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "requests": requests,
        "calls": [brief(c) for c in calls],
        "final": final,
        "transcript": str(directory / "conversation.json"),
    }


async def evaluate(args):
    key = read_api_key(args)
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.query:
        raise ValueError("Use an HTTP base URL without credentials or query parameters")
    headers = {"Authorization": f"Bearer {key}"}
    root = args.runs_dir.resolve() / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "requested_model": args.model,
        "science_mode": "mock",
        "live_llm": True,
        "fallback": False,
        "max_tokens": getattr(args, "max_tokens", 2500),
        "preserve_reasoning": getattr(args, "preserve_reasoning", False),
        "cases": [],
    }
    async with httpx.AsyncClient(timeout=args.timeout, trust_env=False) as http:
        models = await http.get(args.base_url.rstrip("/") + "/models", headers=headers)
        if not models.is_success:
            raise EvaluationError(f"LLM model discovery HTTP {models.status_code}")
        available = [m["id"] for m in models.json()["data"]]
        if args.model not in available:
            raise EvaluationError("Requested model not advertised by provider")
        report["model_advertised"] = True
        for case_id in args.case or CASES:
            row = await run_case(case_id, args, http, headers, root)
            report["cases"].append(row)
            report["passed"] = all(c["passed"] for c in report["cases"])
            report["total_requests"] = sum(len(c["requests"]) for c in report["cases"])
            report["total_tokens"] = sum(
                r.get("usage", {}).get("total_tokens", 0)
                for c in report["cases"]
                for r in c["requests"]
            )
            write_json(args.output, report)
            print(
                f"[{case_id}] {'PASS' if row['passed'] else 'FAIL'} {row['checks']}",
                flush=True,
            )
    print(f"Report: {args.output}", flush=True)
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8317/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="ML4GW_LLM_API_KEY")
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument("--proxy-config", type=Path)
    credentials.add_argument("--key-file", type=Path)
    parser.add_argument("--case", action="append", choices=list(CASES))
    parser.add_argument("--max-rounds", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=2500)
    parser.add_argument("--preserve-reasoning", action="store_true")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs/mcp-gpt"))
    parser.add_argument(
        "--output", type=Path, default=Path("runs/mcp-gpt/evaluation.json")
    )
    args = parser.parse_args()
    if args.max_rounds < 1 or args.max_tokens < 1 or args.timeout <= 0:
        parser.error("--max-rounds, --max-tokens and --timeout must be positive")
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    raise SystemExit(main())
