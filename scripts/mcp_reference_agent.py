#!/usr/bin/env python3
"""A deterministic, contract-following stand-in for a model behind the MCP tests.

It serves the two OpenAI-compatible endpoints ``evaluate_mcp_gpt.py`` uses
(``/v1/models`` and ``/v1/chat/completions``) and answers each turn with the
tool call a client that reads the plan_analysis contract would make: ``mode``
at the top level, ``config.pipeline`` / ``config.exclude_skills`` for routing,
and ``route`` / ``skills`` checked before ``start_analysis``.

It is not a language model. Its only purpose is to prove that the evaluation
harness, the six scenarios and the 44 assertions pass against the current
server for a client that follows the contract, so a later live-model rerun
measures the models and not the harness. Results produced with it must be
labelled as reference runs, never as model results.

    uv run --no-sync python scripts/mcp_reference_agent.py --port 8399
    uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \\
        --base-url http://127.0.0.1:8399/v1 --model-prefix ref- \\
        --output-dir docs/test/contract-reference-<date>
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "ref-contract-agent"
FINAL_NOTE = (
    "All results are SIMULATED mock outputs from the ML4GW Agent MCP server "
    "and have no scientific meaning."
)
TERMINAL = {"completed", "failed", "blocked", "cancelled", "interrupted"}


def scenario_for(prompt: str) -> str:
    if "默认流程" in prompt:
        return "buoy"
    if "Aframe and AMPLFI" in prompt:
        return "aframe_amplfi"
    if "Aframe 和 GWAK" in prompt:
        return "aframe_gwak"
    if "five negative" in prompt:
        return "invalid_requests"
    if "zero GPU-hour" in prompt:
        return "budget"
    if "Lifecycle test" in prompt:
        return "busy_cancel"
    raise ValueError("unknown scenario prompt")


def history(messages: list[dict]) -> list[tuple[str, dict, dict | None, bool]]:
    """(tool name, arguments, parsed result, is_error) for each earlier call."""
    pending: dict[str, tuple[str, dict]] = {}
    calls: list[tuple[str, dict, dict | None, bool]] = []
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                pending[call["id"]] = (
                    call["function"]["name"],
                    json.loads(call["function"]["arguments"]),
                )
        elif message.get("role") == "tool":
            name, arguments = pending.get(message["tool_call_id"], ("?", {}))
            try:
                body = json.loads(message.get("content") or "null")
            except json.JSONDecodeError:
                body = None
            is_error = not isinstance(body, dict) or "error" in body
            calls.append(
                (name, arguments, body if isinstance(body, dict) else None, is_error)
            )
    return calls


def analysis_policy(prompt_args: dict, expected_len: int, expected_route: str, calls):
    """plan -> check route/skills -> start -> poll -> final summary."""
    names = [c[0] for c in calls]
    if "plan_analysis" not in names:
        return ("plan_analysis", prompt_args)
    plan = next(c[2] for c in calls if c[0] == "plan_analysis")
    if (
        plan is None
        or plan.get("route") != expected_route
        or len(plan["skills"]) != expected_len
    ):
        return (
            None,
            "Stopping before start_analysis: the plan route is "
            f"{plan and plan.get('route')} with skills {plan and plan.get('skills')}, "
            f"not the requested graph. {FINAL_NOTE}",
        )
    if "start_analysis" not in names:
        return ("start_analysis", {"plan_id": plan["plan_id"]})
    job = next(c[2] for c in calls if c[0] == "start_analysis")
    views = [c[2] for c in calls if c[0] == "get_run" and c[2]]
    if not views or views[-1].get("status") not in TERMINAL:
        if views:
            time.sleep(1.0)  # give the mock worker time instead of burning rounds
        return ("get_run", {"job_id": job["job_id"]})
    view = views[-1]
    return (
        None,
        f"Analysis {view['status']} in {view['mode']} mode with "
        f"{len(view.get('tasks', {}))} tasks; report read "
        f"({len(view.get('artifacts', []))} artifacts). {FINAL_NOTE}",
    )


def next_step(scenario: str, calls) -> tuple[str | None, object]:
    names = [c[0] for c in calls]
    if scenario == "buoy":
        if "list_skills" not in names:
            return ("list_skills", {})
        return analysis_policy(
            {"prompt": "使用默认流程分析 GW150914", "mode": "mock"}, 3, "buoy", calls
        )
    if scenario == "aframe_amplfi":
        return analysis_policy(
            {
                "prompt": "Run Aframe and AMPLFI on GW150914.",
                "config": {"pipeline": "decomposed"},
                "mode": "mock",
            },
            6,
            "decomposed",
            calls,
        )
    if scenario == "aframe_gwak":
        return analysis_policy(
            {
                "prompt": "Run Aframe and GWAK on GW150914 and reconcile the two "
                "results. Do not run AMPLFI.",
                "config": {"exclude_skills": ["amplfi.pe"]},
                "mode": "mock",
            },
            8,
            "decomposed",
            calls,
        )
    if scenario == "invalid_requests":
        sequence = [
            ("start_analysis", {"plan_id": "plan_000000000000"}),
            ("get_run", {"job_id": "job_000000000000"}),
            ("get_run", {"job_id": "../../secret"}),
            ("plan_analysis", {"prompt": "Analyze GW150914", "mode": "real"}),
            (
                "plan_analysis",
                {"prompt": "Analyze GW150914", "config": {"allow_real": True}},
            ),
        ]
        if len(calls) < len(sequence):
            return sequence[len(calls)]
        errors = [json.dumps(c[2], ensure_ascii=False)[:120] for c in calls]
        return (
            None,
            f"All five calls were rejected by the server: {errors}. {FINAL_NOTE}",
        )
    if scenario == "budget":
        if "plan_analysis" not in names:
            return (
                "plan_analysis",
                {
                    "prompt": "Analyze GW150914",
                    "config": {"device": "cuda"},
                    "mode": "mock",
                },
            )
        plan = next(c[2] for c in calls if c[0] == "plan_analysis")
        if "start_analysis" not in names:
            return ("start_analysis", {"plan_id": plan["plan_id"]})
        start = next(c for c in calls if c[0] == "start_analysis")
        return (
            None,
            f"Plan budget allowed={plan['budget']['allowed']}; start_analysis returned "
            f"{json.dumps(start[2], ensure_ascii=False)[:160]}. {FINAL_NOTE}",
        )
    if scenario == "busy_cancel":
        if "plan_analysis" not in names:
            return ("plan_analysis", {"prompt": "Analyze GW150914", "mode": "mock"})
        plan = next(c[2] for c in calls if c[0] == "plan_analysis")
        starts = [c for c in calls if c[0] == "start_analysis"]
        if not starts:
            return ("start_analysis", {"plan_id": plan["plan_id"]})
        if len(starts) == 1:
            return ("start_analysis", {"plan_id": plan["plan_id"]})
        job_id = starts[0][2]["job_id"]
        cancels = [c for c in calls if c[0] == "cancel_run"]
        if not cancels:
            return ("cancel_run", {"job_id": job_id})
        if "get_run" not in names:
            return ("get_run", {"job_id": job_id})
        if len(cancels) == 1:
            return ("cancel_run", {"job_id": job_id})
        return (
            None,
            "Second start returned SERVICE_BUSY; cancel, get_run and a repeated cancel "
            f"all reported status {cancels[-1][2].get('status')}. {FINAL_NOTE}",
        )
    raise ValueError(scenario)


class Handler(BaseHTTPRequestHandler):
    counter = 0
    lock = threading.Lock()

    def log_message(self, *args):  # quiet
        return

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": MODEL}]})
        return self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "not found"}})
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        messages = request.get("messages", [])
        prompt = next(m["content"] for m in messages if m.get("role") == "user")
        try:
            name, payload = next_step(scenario_for(prompt), history(messages))
        except Exception as exc:  # report, never crash the harness silently
            name, payload = (
                None,
                f"Reference agent stopped: {type(exc).__name__}: {exc}",
            )
        with Handler.lock:
            Handler.counter += 1
            call_id = f"call_ref_{Handler.counter}"
        if name is None:
            message = {"role": "assistant", "content": payload}
            finish = "stop"
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(payload)},
                    }
                ],
            }
            finish = "tool_calls"
        size = len(json.dumps(messages, ensure_ascii=False)) // 4
        self._json(
            200,
            {
                "id": f"chatcmpl-{call_id}",
                "object": "chat.completion",
                "model": request.get("model", MODEL),
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": size,
                    "completion_tokens": 32,
                    "total_tokens": size + 32,
                    "note": "reference agent; character estimate, not model tokens",
                },
            },
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8399)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"reference agent {MODEL} listening on http://{args.host}:{args.port}/v1",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
